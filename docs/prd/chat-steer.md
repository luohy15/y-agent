# Steer: Mid-Turn Message Delivery to a Running Session

## Problem Statement

An agent turn can run for minutes. While it runs, the user often has something
to add: a correction ("not that file, the other one"), a scope change, extra
context, or an attached screenshot. Without steer, a message sent mid-turn
either spawns a duplicate parallel task (two workers fighting over one chat) or
sits unread until the turn ends, by which point the agent may have gone far
down the wrong path. The user should be able to keep typing into a busy chat
and trust that the running agent sees the message promptly and exactly once.

## Solution

Sending a message to a running chat requires no special UI or command: the
message is appended to the chat like any other, but no new worker task is
enqueued. The already-running worker polls the chat for new user messages every
couple of seconds and delivers each one into the live agent session. Backends
that accept mid-run input (Claude Code print mode) receive the message live;
backends that cannot (Codex, Gemini CLI, Pi CLI) are killed and resumed with
the message as the next prompt. Delivery is exactly-once: a
claim/unclaim protocol plus a turn-end drain and a post-turn reconciliation
pass guarantee a steer message is neither delivered twice nor silently dropped,
even across Lambda handoffs and turn-end races.

## User Stories

1. As a web user, I want to type a follow-up message into a chat whose turn is
   still running, so that the agent adjusts course without me waiting for the
   turn to finish.
2. As a web user, I want the chat to show a running state immediately after I
   send into a busy chat, so that I know my message was accepted as a steer
   rather than starting a new turn.
3. As a CLI user, I want a message dispatched to a running chat (by chat id or
   topic) to be steered into it instead of enqueuing a parallel task, so that
   one chat never has two concurrent workers.
4. As a Telegram user, I want a message to the root (manager) topic to be
   steered into the running manager chat when it is busy, so that my inbox
   conversation stays a single thread instead of spawning overflow chats.
5. As a Telegram user, I want messages addressed to a specific chat id to
   follow the same append-or-steer semantics, so that addressing a busy child
   chat behaves the same as addressing an idle one.
6. As a user, I want a steer message that includes images to reach the agent
   with those images, so that I can drop a screenshot mid-turn.
7. As a user, I want every steer message delivered exactly once, so that the
   agent neither misses my correction nor processes it twice.
8. As a user, I want a message that arrives in the instant the turn is ending
   to still be handled (delivered before teardown, or answered by a fresh
   continuation turn), so that nothing I typed is silently lost.
9. As a user, I want an explicit stop to interrupt the running turn with
   priority over pending steers, so that "stop" always wins over "and also do
   X".
10. As a user, I want steer to keep working when the platform hands a long run
    off between worker invocations, so that messages consumed before the
    handoff are not re-delivered after it.
11. As a user on a backend without live input injection, I want my mid-turn
    message to restart the run from its persisted session with my message as
    the new prompt, so that steer is available on every backend even if the
    mechanics differ.
12. As a user, I want multiple steer messages sent in quick succession
    delivered in the order I sent them, so that a two-part correction reads
    coherently.
13. As a user starting a new turn on a chat with unanswered trailing user
    messages, I want all of them folded into the new turn's prompt, so that a
    message that slipped past a previous turn is still answered.

## Implementation Decisions

- **No new task for a busy chat.** The message-ingestion API appends the user
  message to the chat and checks the chat's running flag: if the chat is
  running, it saves and returns without enqueuing; the running worker discovers
  the message by polling the database. Only an idle chat gets a new worker
  task. All ingestion surfaces (web/API send, cross-skill notify, Telegram)
  share this append-or-steer rule.
- **Steer detection is set-difference on message IDs.** At session start the
  worker records the initial message count; the steer checker returns user
  messages whose IDs are neither in the initial set nor already consumed.
  Detection runs inside a unified poll loop (single daemon thread, ~2 s
  cadence) that also checks for interrupts. Interrupt is checked first and
  takes priority: an interrupted chat kills the session and skips steer.
- **Claim on discovery, unclaim on failed delivery.** The checker marks a
  message consumed the moment it is returned, so two concurrent consumers (the
  poll loop and the turn-end drain) cannot both pick it up. Claiming is not
  delivery: if the delivery callback reports failure, the caller invokes the
  checker's unclaim hook so the message is re-surfaced to the next mechanism.
  Delivery callbacks return three-valued status: success, unknown (treated as
  success for backends that cannot confirm), or explicit failure (triggers
  unclaim).
- **Per-backend delivery, two families.** Live injection: Claude Code print
  mode appends a stream-json user message to a remote stdin file that is piped
  into the process via a follow-tail, with the SSH write's exit status as
  delivery confirmation. Kill-and-resume: Codex, Gemini CLI, and Pi CLI cannot
  accept mid-run input, so the first steer kills the tmux session, the tailer
  returns a steer status with the collected messages, and the monitor
  restarts the run via the backend's resume command using the steer text as
  the new prompt.
- **Turn-end race is closed by a shared lock plus final drain.** Live steer
  writes and session teardown are serialized by one lock. Teardown first drains
  the checker one last time and delivers any straggler before killing the
  session; after teardown, delivery attempts return failure (and unclaim)
  instead of silently no-opping against a dead session.
- **Reconciliation safety net after completion.** When a live-injection turn
  completes, the monitor checks for trailing user messages whose delivery was
  never confirmed; if any exist, the turn is not finalized and a continuation
  turn is relaunched. Symmetrically, any new turn folds all unanswered trailing
  user messages into its prompt, so a message dropped by an earlier race is
  recovered at the next turn boundary. Kill-and-resume backends reconcile via
  their restart branch instead.
- **Consumed IDs survive Lambda handoff.** The set of confirmed-delivered steer
  IDs is persisted in the per-process lease record and merged (not overwritten)
  on each handoff, so a later invocation neither re-delivers a consumed message
  nor forgets one confirmed earlier.
- **Steer teardown owns process exit for stream-json mode.** Because the stdin
  pipe never reaches EOF, the process does not exit on its own after the result
  event; the tailer kills the tmux session and removes the temp files itself.
- **Images ride along.** Steer tuples carry the message's image list; live
  backends deliver them as image content blocks, and restart backends include
  them in the resume prompt.
- **Telegram root-topic steer only.** Steering an incoming topic message into a
  busy chat applies to root topics (the long-lived inbox); non-root topics
  serialize naturally because each is scoped to a single task.

## Testing Decisions

- Test external behavior at the seam of "messages appended to the chat while a
  session runs": given a running session and a newly appended user message,
  assert the message reaches the backend (live write, paste, or resume prompt)
  exactly once, in order, with images intact. Do not assert on poll cadence or
  internal thread structure.
- The race protocol is the highest-value target: claim-then-unclaim on failed
  delivery, the turn-end drain delivering a straggler before teardown,
  post-teardown delivery returning failure, and the completion-time
  reconciliation relaunching a turn for an unconfirmed trailing message.
- Handoff behavior: consumed IDs recorded before a handoff must suppress
  re-delivery after it, and a completion that consumed nothing new must not
  erase previously confirmed IDs.
- Per-backend monitor tests cover the two delivery families, including the
  kill-and-resume restart carrying the steer text and the correct resume
  handle.
- Prior art: the agent and worker packages already have dedicated tests for the
  poll-loop unclaim contract, steer race drain, steer images, race
  reconciliation, and each backend's monitor restart path; extend those rather
  than inventing a new harness.

## Out of Scope

- Editing or retracting a steer message after it is sent: once delivered to the
  running session it is part of the turn.
- A dedicated steer UI affordance (compose modes, "send as steer" toggles):
  steer is intentionally invisible; users just type.
- Steering a chat's running turn from a different chat's context: cross-chat
  messages go through normal dispatch, which itself applies append-or-steer.
- Root-topic-style steer routing for non-root Telegram topics.
- Guarantees about where within the turn the agent acts on a steer: delivery is
  prompt, but the model decides when to attend to it.
