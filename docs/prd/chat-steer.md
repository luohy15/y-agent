---
title: Mid-turn message delivery
type: prd
project: y-agent
feature: chat-steer
status: active
---

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
couple of seconds and delivers each one into the live agent session. The only
agentic backend (Claude Code print mode) accepts mid-run input. An accepted
message is either completed by that session or assigned to one serialized
continuation. A successful stdin-file write is not evidence of consumption.
Native per-input lifecycle events, persisted delivery state, and a locked
busy-to-idle transition protect closeout and ordinary Lambda handoffs. This
is not a distributed exactly-once side-effect guarantee across arbitrary
worker/VM crashes.

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
11. As a user, I want multiple steer messages sent in quick succession
    delivered in the order I sent them, so that a two-part correction reads
    coherently.
12. As a user starting a new turn on a chat with unanswered trailing user
    messages, I want all of them folded into the new turn's prompt, so that a
    message that slipped past a previous turn is still answered.

## Implementation Decisions

- **No new task for a busy chat.** The message-ingestion API appends the user
  message to the chat and checks the chat's running flag: if the chat is
  running, it saves and returns without enqueuing; the running worker discovers
  the message by polling the database. Only an idle chat gets a new worker
  task. All ingestion surfaces (web/API send, cross-skill notify, Telegram)
  share this append-or-steer rule.
- **Discovery is not consumption.** The checker claims stable message IDs so
  one ordered writer submits each input once. A failed SSH append releases the
  claim. Teardown never drains or submits new work. Interrupt remains the first
  poll-loop check and suppresses automatic continuation.
- **Native input identity is explicit (todo 3643).** Every stdin write carries
  a UUID. The launch write maps that UUID to its ordered input IDs; live steers
  map one UUID to one ID. Claude Code 2.1.259's `command_lifecycle` schema echoes
  it as `command_uuid`: `queued` / `started` acknowledge native admission;
  `completed` marks the consuming turn ended; `cancelled`, `discarded`, and
  `refused` do not prove an answer. Native bookkeeping is not another user
  bubble. Missing events never fall back to write-confirmation.
- **Result and input completion are distinct.** Standalone command completion
  follows its result; a folded command may complete before its result. A new
  `started` invalidates an older cached result. The tailer requires a result
  and no outstanding submitted/acknowledged input before teardown, under the
  same lock as submission. A broken tail with an outstanding input and live
  process resumes monitoring rather than launching a second process.
- **Handoff keeps the ledger and result boundary.** The process record carries
  initial message IDs, input groups, submitted/acknowledged/completed states,
  lifecycle observation, and the pending result alongside the stdout offset.
  Forced cancellation joins both the shielded stdout reader and input writer
  before taking one coherent checkpoint; the retired reader cannot tear down
  the native session afterward. Already-written input is not written again
  after an ordinary handoff.
- **Whole-run reconciliation replaces the trailing suffix.** Closeout selects
  all unhandled user IDs from the run's explicit first input, including
  `U0,U1,A0` where old assistant output follows the unanswered question. The
  continuation uses only the ordered pending subset, preserving text, images,
  and effort; completed peers remain excluded across successive continuations.
  Pre-upgrade process records without an anchor retain only their old recovery
  scope, not a retroactive repair guarantee.
- **Acceptance and closeout share a row lock.** After native teardown, a durable
  `closeout_pending` phase fences further tailing before SQL exposes idle. The
  process record remains discoverable as recovery work until arbitration and
  successor queue delivery succeed. A SQL receipt commits the decision and
  input subset with the new reservation; retry returns that same receipt rather
  than reserving twice. Queue-send failure retries from the receipt, and repeated
  sends carry the same claimed-once run sequence. Input accepted after idle owns
  its own next queue send. Blob-only `run_seq` / `run_claimed_seq` fence duplicate
  worker entry. Runtime stream append/dedup and hook patches mutate current
  state, not a stale whole chat.
- **Images ride along.** Live stdin content includes image blocks; a continuation
  combines the images of its selected pending inputs with their text.
- **Protocol limits are explicit.** The native schema documents that cancelled
  folds in a failed turn can already have caused work, and completion on
  max-turn/hook/deferred exits is not proof of semantic fulfillment. Unknown
  UUIDs do not retire our inputs. No transport ledger proves exactly-once model
  side effects under all failures, and this task does not add a queue outbox
  or repair historical messages.
- **Ingress is topic-agnostic.** Web, CLI/dispatch and Telegram use the same
  acceptance primitive. A busy non-root chat steers too; root-topic policy
  governs Telegram reply delivery, not input serialization.

## Testing Decisions

- Deterministic gated fake SSH channels cover write-without-read, ack after an
  old result, standalone/folded completion ordering, failed-write unclaim,
  teardown refusal, rapid ordered inputs, images, interruption, and handoff.
- Worker fixtures cover `U0,U1,A0`, mixed handled/pending subsets, persisted
  ledger state and result boundaries, retired-generation rejection, and retry
  budget continuity. A successful file append alone must never pass a
  consumption assertion.
- An isolated throwaway PostgreSQL cluster uses independent connections and
  barriers to exercise acceptance/closeout serialization and locked runtime
  mutation. Production rows are never test fixtures. Existing stream replay
  identity remains `(id, tool_call_id)`.
- Tests remain local-only. Verification commands and any shared-test baseline
  drift belong in the delivery implementation note; no browser is needed.

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
- **Module migration**: steer stays host (the conversational routes did not move);
  the surface that sends it is the `chat` module's `shell`. See
  `docs/prd/module-system.md` ("Chat: a control-plane module over the runtime
  kernel").

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3643 | Native input ledger, serialized closeout ownership, and whole-run pending-input recovery | - | `pages/plan-3643.md` | `pages/impl-3643.md` | - | implemented; review pending; not published |
