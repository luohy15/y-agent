# Core Chat System

## Problem Statement

Everything in y-agent happens through conversations with agent sessions, but
those sessions run as subprocesses on a remote VM, take minutes per turn, and
are started from three different surfaces (web, CLI, Telegram). The user needs
one durable conversation model behind all of them: a way to browse and filter
past and running conversations, watch a running turn stream in live, send a
message from any surface and trust exactly one agent run handles it, and
address a conversation programmatically (from another agent session) without a
human in the loop. Without this, each surface would invent its own session
handling, running state would be invisible, and cross-session dispatch (the
session tree) would have no transport.

## Solution

A chat is a durable, per-user conversation record: an ordered message list
plus identity metadata (topic, skill, trace id, backend, bot, work dir) and a
derived status (running / interrupted / idle). All surfaces converge on the
same lifecycle: the API persists the user message and marks the chat running
synchronously, then enqueues a task; an async worker resolves the bot
configuration and drives the agent backend (usually a detached tmux subprocess
on EC2 over SSH); every event the backend emits is appended to the chat as a
message; readers observe progress by polling the same record (the web UI via a
snapshot fetch plus an SSE stream, the CLI via snapshot polling).

The GUI exposes this as a filterable chat list (with the root manager chat
pinned) and a chat detail view that live-streams the running turn, shows tool
calls and context usage, and offers steer / stop while running and follow-up /
share when idle.

The CLI's top-level `y chat -m` is the programmatic dispatch edge of the
session tree: fire-and-forget by default (send, print the chat id, return
immediately), with an opt-in `--wait` mode that blocks until the assistant
reply is ready and prints the reply text instead. A separate interactive REPL
mode (`-i`) serves a human at a terminal.

## User Stories

### GUI: chat list

1. As a web user, I want a list of my chats ordered by recent activity, so
   that I can find and resume any conversation.
2. As a web user, I want the root manager chat pinned above the list, so that
   my main inbox conversation is always one click away regardless of filters.
   In the right-side chat drawer specifically, when the query is filtered by
   `todo:<id>`, I also want the newest `dev` chat for that trace pinned
   directly below manager, so that I can jump straight to whichever session
   is actually coordinating that todo (this second pin does not apply to the
   left activity-bar panel or to an unfiltered list).
3. As a web user, I want each list row to show the title (first user
   message), timestamp, and badges for trace id, chat id, topic, skill, and
   routine, so that I can identify a chat's place in the session tree at a
   glance.
4. As a web user, I want a running spinner, an interrupted icon, and an
   unread dot on list rows, so that I can see which conversations need
   attention without opening them.
5. As a web user, I want to filter the list through one compact `key:value`
   query input (GitHub/Lucene style: space-separated terms AND together, a
   repeated key overwrites the earlier one, an empty value like `todo:`
   clears that key, and bare words are free text) instead of a stack of
   separate filter boxes, so that I can narrow hundreds of chats to the ones
   relevant to a task with one field. Values that contain whitespace are
   written and parsed as double-quoted spans (e.g. `routine:"Daily Scan"`);
   a bare value never needs quotes. The recognized keys are:

   | Term | Filters by |
   |------|------------|
   | `todo:<id>` | todo / trace id |
   | `topic:<name>` | topic |
   | `skill:<name>` | skill |
   | `bot:<name>` | bot |
   | `routine:<name>` / `routine:"Name With Spaces"` | routine name |
   | `tier:<tier>` | bot tier |
   | `tag:<tag>` | tag |
   | `is:running` | running status |
   | `is:routine` | routine-originated chats only |
   | bare word(s) | free-text search |

   The input surfaces this vocabulary while focused (a one-line key hint, and
   prefix autocomplete on the token under the caret). Choosing a suggestion
   (Tab/Enter or a click on the dropdown option) replaces the active token
   with that key.
6. As a web user, I want clicking a row badge to write that badge's value as
   the matching `key:value` term in the query input (replacing any earlier
   term for that key, and auto-quoting the value when it contains whitespace),
   so that I can pivot from one chat to all its trace / topic / skill / bot /
   routine siblings in one click.
7. As a web user, I want infinite-scroll pagination, so that old chats load
   on demand instead of slowing the initial view.
8. As a web user, I want a copy-chat-id button on each row, so that I can
   address the chat from the CLI or a dispatch message.
9. As a web user, I want opening a chat to clear its unread marker
   (optimistically in the list, persisted server-side), so that unread state
   reflects what I have actually seen.
10. As a web user, I want the list to refresh when a chat I am watching
    completes, and a manual refresh button, so that statuses stay current.

### GUI: chat detail

11. As a web user, I want opening a chat to load its full message history
    immediately, and to attach a live stream only when the chat is running,
    so that idle history is cheap and running turns are live.
12. As a web user, I want assistant output, tool calls, and tool results
    rendered as they happen, with tool results merged into their pending tool
    call, so that I can follow the agent's work in real time.
13. As a web user, I want a toggle to show or hide intermediate progress
    (tool activity), persisted across sessions, so that I can read a chat as
    either a transcript or a summary.
14. As a web user, I want a context-usage badge (percent of the model window,
    with a token breakdown and turn count on hover), so that I can judge when
    a session is close to needing a restart.
15. As a web user, I want Steer and Stop controls while a turn is running,
    so that I can redirect or interrupt the agent without leaving the view.
16. As a web user, I want a follow-up input once the turn completes, so that
    the conversation continues in the same chat and session.
17. As a web user, I want to share a chat via a public link, optionally
    protected by a password (mine or generated), so that I can show a
    conversation to someone without granting account access.
18. As a web user, I want to select messages and export them as an image, so
    that I can capture part of a conversation for posting elsewhere.
19. As a web user, I want file paths in agent output to be clickable and open
    in the file viewer (resolved against the chat's work dir), so that I can
    jump from conversation to code.
20. As a web user, I want inline rendering of artifact fences (diagrams,
    charts, SVG) and a sources sidebar for citation links, so that rich
    assistant output is readable in place.
21. As a web user, I want a table of contents and a scroll-to-bottom button
    on long chats, so that navigation stays manageable at hundreds of
    messages.

### GUI: sending

22. As a web user, I want to start a new chat by typing a prompt (optionally
    with pasted or uploaded images), so that starting a conversation is one
    action.
23. As a web user, I want the new chat to appear at the top of the list
    immediately (optimistic update) and its running state to show without
    waiting for the worker, so that the UI confirms my send instantly.
24. As a web user, I want a follow-up send to reuse the chat's existing work
    dir and bot identity, so that the conversation stays in one session.
25. As a web user, I want sending into a running chat to steer it rather
    than start a parallel run (delivery mechanics per the chat-steer PRD), so that
    one chat never has two concurrent workers.

### CLI: dispatch (fire-and-forget vs wait)

26. As an agent session, I want `y chat -m` to return immediately after the
    message is accepted, printing only the target chat id, so that dispatching
    a subtask never blocks my own turn.
27. As an agent session, I want to address a dispatch by topic (named
    persistent address), by explicit chat id, or by skill (anonymous session),
    each independently optional, so that one command covers named, direct, and
    ephemeral targets.
28. As an agent session, I want a topic dispatch that carries a trace id to
    resume that topic's existing chat for the same trace, so that one trace
    maps to one chat per topic.
29. As an agent session, I want `--new` to force a fresh chat even when the
    topic has an existing one, so that a new trace never leaks into an old
    chat's history.
30. As an agent session, I want the dispatch to stamp a machine-readable
    metadata prefix (`[trace:... from:... to:... from_chat:... to_chat:...]`)
    onto the delivered message, so that the receiver can identify the trace
    and reply address without extra lookups.
31. As an agent session, I want callbacks to a root topic (manager) rejected
    at the API with a clear error, so that a conversation inbox is never
    treated as a function-call return address.
32. As an agent session, I want a one-shot query to use `--wait` and get the
    assistant's reply text (plus citation references) printed directly, so
    that quick lookups (e.g. a Perplexity fact check) behave like a synchronous
    command instead of a dispatch-then-poll dance.
33. As an agent session, I want `--wait` to time out after a configurable
    period (default 300s), falling back to printing the chat id with an error
    on stderr and a nonzero exit, so that a slow or stuck reply never hangs my
    turn forever.
34. As an agent session, I want `--wait` to detect an interrupted chat and
    exit nonzero with whatever partial reply exists, so that interruption is
    distinguishable from success.
35. As an agent session, I want to attach images and set the working
    directory, bot, or tier on a dispatch, so that a child session starts with
    the right context (bot/tier selection policy per the tier-routing PRD).
36. As a dispatcher, I want a work-dir that conflicts with the target chat's
    existing work-dir rejected with an explicit error, so that a session never
    silently changes its filesystem context mid-conversation.

### CLI: interactive and query

37. As a terminal user, I want `y chat -i` to open a streaming REPL (new
    chat, `-l` latest, `-c` specific, `-p` one-off prompt), so that I can hold
    a conversation without the web UI.
38. As a terminal user, I want Ctrl-C during streaming to stop the running
    turn (same interrupt as the web Stop button), so that escape is always
    available.
39. As a user, I want `y chat list / get / search` with the standard time and
    identity filters, so that chat history is queryable from scripts and other
    sessions.
40. As a user, I want `y chat stop <id>` as an explicit interrupt path, so
    that any surface can stop a runaway turn.

### Underlying lifecycle

41. As a user on any surface, I want my message persisted and the chat marked
    running before the send call returns, so that no message is lost even if
    the worker lags or dies, and every reader sees the running state
    immediately.
42. As a user, I want a message sent to an already-running chat to be
    appended without enqueuing a second worker task, so that steer never
    creates duplicate runs.
43. As a user, I want each chat's backend fixed at first run, so that
    changing my default bot never migrates an existing conversation between
    agent backends mid-session. With claude_code the only agentic backend,
    this now mainly pins a chat away from the inline query backends and keeps
    its native session resumable. The bot itself is not pinned: a chat runs on
    its own bot until a later message names a different one, and that bot
    change is honored (bot name and tier follow it) when the name resolves to
    a runnable bot on the chat's backend. Anything else keeps the current bot;
    the routing rules live in the bot-routing PRD.
44. As a user, I want follow-up turns to resume the backend's native session
    (via the stored external session id, only when the work dir still
    matches), so that the agent keeps its full context across turns.
45. As a user, I want a chat created with a skill (defaulting to the topic
    for non-root topics) to have that skill force-loaded at session start, so
    that a dispatched session always runs with its intended capability set.
46. As a user, I want every event the running backend emits appended to the
    chat as it happens, so that all surfaces (web SSE, CLI polling, trace
    view) observe the same single source of truth.
47. As a user, I want turn completion defined by one predicate everywhere
    (chat not running and the last message is an assistant message with no
    pending tool calls), so that the web done event, the CLI `--wait` return,
    and completion hooks all agree.
48. As a user, I want a failed backend launch to mark the chat idle and
    append a visible error message, so that a chat never appears stuck
    running with no process behind it.
49. As a user, I want long runs to survive the platform's execution time
    limit via lease handoff between worker invocations, so that a turn's
    length is bounded by the task, not the infrastructure.
50. As a user, I want a completed turn to mark the chat unread and deliver
    the reply to the chat's bound Telegram topic (if any), so that I learn of
    completion without watching the screen.
51. As a user, I want simple query backends (Perplexity, plain OpenAI-style
    chat) to run inline in the worker without a VM subprocess, so that
    one-shot questions stay cheap and fast.
52. As an operator, I want chat identity fields (topic, skill, trace id,
    backend) immutable once set, with mutation attempts logged and refused,
    so that a chat's place in the session tree cannot drift. Bot name and
    tier are excluded: they are routing state that follows the bot each run
    actually used, so an accepted re-bot is persisted rather than refused.
53. As a user sending a message into a chat that has already used more
    tokens than the recommended context-handoff threshold
    (`min(50% of its context window, 200k tokens)`), I want a
    `[context-handoff-reminder]` block appended to the end of my message,
    stating the session's actual usage, so that the receiving session is
    nudged to wrap up and hand off per AGENTS.md rather than running
    unboundedly long.

## Implementation Decisions

- **One record, many readers.** The chat row owns the ordered message list
  (JSON), identity metadata, derived status, and unread flag. Workers write
  messages into it as the backend emits them; every surface reads the same
  row. There is no separate streaming channel with its own state: the web SSE
  endpoint and the CLI `--wait` loop are both pollers over the persisted chat.
- **Synchronous accept, asynchronous run.** Every send path (create, message,
  notify) persists the user message and sets `running` before returning, then
  enqueues a queue task (SQS in production, Celery filesystem broker in dev)
  carrying the chat id plus routing hints. If the chat is already running, no
  task is enqueued; the running worker's steer polling picks the message up
  (mechanics owned by the chat-steer PRD).
- **Notify target resolution order:** explicit chat id (404 if missing, 400 on
  topic mismatch) > topic + trace lookup (resume the trace's existing chat for
  that topic unless `--new`) > create a new chat. Skill defaults to the topic
  for non-root topics; explicit `--skill` overrides. A new chat claiming a
  topic without a trace id is a root claim and releases the topic from any
  previous holder (singleton root topic).
- **Root-topic callback rejection** is enforced at the API on the resolved
  target chat's topic, with the `--new` escape hatch only for starting a fresh
  root session. The root topic set is currently the single hard-coded name
  `manager`.
- **Trace metadata rides in-band**: the notify endpoint prefixes the message
  with `[trace:<id> from:<topic> to:<topic> from_chat:<id> to_chat:<id>]`
  (omitting absent parts) rather than using a side channel, so any backend
  sees the routing context as plain text. The same context is exported to the
  subprocess as environment variables.
- **Status is derived, not stored independently**: `running` →
  `interrupted` → `idle`, computed from the chat flags at save time and
  denormalized to an indexed column for list filtering. Title (first user
  message, truncated) and search text (concatenated user + assistant text)
  are likewise denormalized at save time.
- **Completion predicate** (shared by the SSE done event and CLI `--wait`):
  not running, not interrupted, and the last message is an assistant message
  without tool calls. Interruption is a separate terminal signal carrying its
  own done status.
- **Interrupt is a flag, not a signal**: stop sets `interrupted` on the chat
  row; the running worker's poll loop observes it and tears down. Any surface
  can set it.
- **Backend dispatch in the worker**: Perplexity and OpenAI-style backends run
  inline (message-list in, reply out, no VM). `claude_code` is the single
  agentic CLI backend; it launches as a detached tmux subprocess on the user's
  EC2 VM over SSH, is registered in a process table (DynamoDB) for monitoring,
  and is tailed by a monitor loop that appends each streamed event as a chat
  message. An unset backend defaults to claude_code; any other backend is
  rejected with a clear launch error rather than falling through, so a chat
  still carrying a removed backend's session id can never launch
  `claude -p -r` against an unresumable handle.
- **Session continuity**: the backend's native session id lives in the chat's
  `external_id`; a follow-up resumes it only when the chat's stored work dir
  matches the resolved cwd, otherwise a fresh session starts. Work-dir
  conflicts on send are rejected, not silently rebased. Two further guarantees
  (todo 2930):
  - **The `external_id` column is authoritative.** `chat` persists the field
    both in its `json_content` blob and as a promoted column; the column is
    what the runtime reads, and NULL there means "no resumable session" rather
    than "look in the blob". So clearing a session handle in SQL works, and no
    tool may re-derive the column from the blob's copy.
  - **A refused handle is dropped, on the CLI's own evidence only.** When a
    resumed turn is refused, the handle is cleared so the next turn starts fresh
    instead of retrying it forever, and the turn reports the refusal by name
    instead of a bare "exited with an error". The evidence is the CLI's own
    `No conversation found with session ID` message, read from the run's final
    `result` event (its structured `errors` list — the shape a refusal actually
    produces: an error result event, not the absence of one) or, if a run left no
    result event at all, from that run's stderr. Only those two, and only the
    structured field — never text the model itself authored, which can quote the
    message. No other failure clears the handle: a launcher that never started
    the CLI, an external kill, or a CLI-level startup failure all keep it,
    because those are not evidence about the session and are correlated across
    chats. Missing or reworded evidence keeps the handle too, costing one wedged
    turn rather than risking a live session. A refused turn also never *writes* a
    handle, whatever the column currently holds: the refusal names the id it
    rejected, so persisting it would resurrect a dead handle into a column
    cleared out of band (by migration SQL) while the turn was in flight.
- **Identity immutability**: backend, topic, skill, trace id, and routine id
  are write-once at the repository layer; later saves keep the existing value
  and log a warning on attempted mutation. Bot name and tier are deliberately
  not in that set (todo 2930): they record which bot a run used, and a
  same-backend bot change accepted by the worker must be persisted, so the
  repository takes the new value and only refuses to let an unset one clear
  a persisted one. Root (manager) chats deliberately never persist a trace id
  (a root participates in many traces; per-message metadata carries trace
  context instead).
- **Lambda time limit**: the worker releases its monitoring lease before the
  deadline and re-enqueues itself; the next invocation resumes tailing from
  the stored offset. This is core lifecycle; steer-specific handoff behavior
  (consumed-message continuity) is in the chat-steer PRD.
- **CLI `--wait` is client-side polling** of the snapshot endpoint (2s
  cadence) applying the shared completion predicate; the server has no
  blocking-wait API. Timeout and interrupt both exit nonzero, printing the
  chat id (timeout) or partial reply (interrupt) so callers can degrade to
  fire-and-forget semantics.
- **Web streaming**: detail view loads the snapshot, then opens SSE only when
  the chat is running; the SSE stream re-polls the chat row and emits new
  messages by index, ending with a done event from the completion predicate.
  On done the client re-fetches the snapshot as ground truth.
- **Sharing** copies the chat (optionally truncated to a message path) under
  a public share id owned by the default user, deduplicated by origin chat and
  message; password protection stores only a hash and rate-limits attempts.
- **Post-turn hooks** (Telegram reply delivery, unread marking, plan-to-todo
  extraction, trace registration) run in the worker after completion, keyed
  off the same chat record.
- **Handoff reminder is appended at write time, in-band** (plan-2951): each
  of the five existing-chat inbound write sites (web/CLI send, notify
  existing-chat, Telegram routed/steer/DM) appends the handoff reminder to the
  persisted message content itself rather than at prompt-assembly time,
  so steer (which forwards `msg.content` verbatim into the live stdin pipe)
  and Lambda-handoff turn relaunches (which reread already-persisted
  messages) both see it for free with no separate recomputation path. At
  most one reminder is appended per pending batch: before appending, the
  helper scans backwards from the end of `chat.messages` to the first
  non-user message, and skips if the marker is already present in that
  trailing run, so several steer messages arriving in one over-threshold
  window don't each get their own copy.
- **Handoff threshold is `min(50% of context window, 200k tokens)`, not a flat
  ratio** (todo 2951 revision, supersedes the original 20%-ratio decision): a
  flat percentage fired 5x earlier in absolute terms on a 200k-window bot than
  on a 1M-window (fable-class) bot. The absolute cap makes the trigger mean
  the same token budget everywhere: a 200k-window bot fires at 50% usage
  (100k tokens), a 1M-window bot fires at 20% usage (200k tokens). The
  reminder wording states the session's actual usage percentage and token
  count rather than a fixed threshold percentage, since the effective
  percentage now varies by window size.

## Testing Decisions

- Test external behavior at the seams, not the internals: the notify
  resolution matrix (chat id vs topic+trace vs new, `--new`, topic mismatch,
  root-topic rejection, work-dir mismatch) via API-level tests with a stubbed
  queue — prior art exists as an API test suite for notify.
- The completion predicate deserves table-driven tests (message tail shapes ×
  running/interrupted flags) since three consumers depend on it agreeing.
- CLI `--wait` behavior (reply ready, interrupted, timeout: what is printed,
  exit code) tested against a faked snapshot endpoint; the 2s cadence is an
  implementation detail, the terminal outcomes are the contract.
- Worker runner tests stub the SSH/tmux launchers and assert the observable
  contract: prompt assembly from trailing user messages, resume vs fresh
  decision, env propagation, failure path (running cleared + error message
  appended) — prior art exists as pytest suites in the agent package (stream
  converters, steer drain, poll loop).
- Repository-level tests for status derivation, title/search-text
  extraction, identity-field immutability, and the opposite rule for the
  routing fields (a new bot name / tier is written, an unset one never
  clears the stored value).
- Steer delivery mechanics are tested under the chat-steer PRD; here only the
  dispatch-side contract (running chat → append without enqueue) is asserted.

## Out of Scope

- **Mid-turn message delivery mechanics** (claim/unclaim, turn-end drain,
  backend kill-and-resume, exactly-once guarantees): owned by the chat-steer PRD.
  This PRD owns only the dispatch-side rule that a running chat gets an append
  with no new task.
- **Bot and tier selection policy** (which bot a dispatch resolves to, tier
  routing, skill-to-tier defaults): owned by the bot-routing
  PRD. This PRD treats the resolved bot config as an input.
- **Spend/usage accounting**: owned by the bot-usage PRD. The per-chat
  context-usage badge (session token counts) is in scope here; the historical
  spend time series is not.
- **Telegram surface specifics** (forum topic binding, webhook routing,
  markdown conversion, image reference delivery): adjacent subsystem; this
  PRD covers only that a completed turn delivers the reply to the chat's
  bound topic.
- **Module migration**: chat browsing and the whole message renderer are the
  `chat` module's `panel` / `detail` / `shell` surfaces; the chat runtime (table,
  worker, Telegram, conversational routes) stays host. See
  `docs/prd/module-system.md` ("Chat: a control-plane module over the runtime
  kernel").
- **Trace waterfall visualization and public trace shares**: the trace
  subsystem consumes chat records but has its own views and share flow.
- **Context monitor auto-restart** (fresh-chat rollover at context/turn
  thresholds): a policy layered on top of chats, worth its own PRD if it
  changes. Distinct from the context-handoff reminder above: the reminder is
  an earlier, softer nag appended to in-band message content once usage
  exceeds `min(50% of context window, 200k tokens)`; it does not restart or
  roll over a chat by itself.
- **Handoff reminder wording and per-role handoff mechanics**: the handoff
  reminder text is role-agnostic in code (`build_handoff_reminder`, no branching on
  chat.topic / chat.skill) and defers classification (callback vs.
  self-restart) to the session itself, per the AGENTS.md "Context handoff"
  playbook owned by the `hr` skill (todo 2976). This PRD owns only the
  mechanism: when the reminder fires, where it is appended, and idempotency.
- **Chat import** (`y chat import`, `import-claude`) and the legacy pandoc
  HTML export: maintenance utilities, not part of the core contract.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 2813 | Stream Grok reasoning, text, tool calls, and tool results live with restart-safe ordering and deduplication | - | `pages/plan-2813-grok-intermediate-stream.md` | - | `pages/review-2813-grok-intermediate-stream.md` | shipped |
| 2873 | Fully remove the temporary claude_tui backend + subscription /usage tooling; `_start_detached` defaults to claude_code and rejects unknown backends; migration repoints persisted backend pins claude_tui->claude_code with external_id preserved | - | `pages/plan-2873-remove-claude-tui.md` | - | `pages/review-2873-remove-claude-tui.md` | shipped |
| 2885 | Prevent large Grok updates polls from deadlocking SSH persistence and retain the cumulative updates offset across resumed turns | - | `pages/plan-2885-grok-updates-poll-deadlock.md` | `pages/recovery-2885-aa346e-lost-turn.md` | `pages/review-2885-grok-updates-poll-deadlock.md` | shipped |
| 2930 | Remove the codex / gemini_cli / grok_build / pi_cli agentic backends so claude_code is the only detached backend; `_start_detached` rejects every other backend; the two steer delivery families collapse to live stdin injection; migration repoints persisted chat pins to claude_code and NULLs `external_id` (a foreign CLI session id is not resumable by `claude -p -r`). Chat identity narrows to backend-only: bot name and tier leave the write-once set so a same-backend re-bot on a live chat persists, keeping `external_id` and the session. Follow-up: the `external_id` column becomes authoritative over the `json_content` copy (the Track A migration's NULL never reached the runtime and broke the 983 repointed chats that held a session handle), and a handle Claude Code affirmatively refuses is dropped instead of retried forever. That heal as first deployed (437b4f2) never fired: it sat on the no-result branch, while a refused resume emits an error `result` event (so `result_data` was always set and the probe was unreachable, and the event's echoed session id was re-persisted). Detection now reads the marker from that event's structured `errors` list, with the stderr probe kept only as the fallback for a run that leaves no result event | - | `pages/plan-2930-single-backend.md` | `pages/decision-2930-external-id-column-authority.md` | `pages/review-2930-single-backend.md` (Track A), `pages/review-2930-track-c-rebot.md` (Track C), `pages/review-2930-external-id-column-authority.md` + `pages/review-2930-external-id-column-authority-fixes.md` (column authority), `pages/review-2930-refused-handle-heal-branch.md` (heal branch) | in progress |
| 2951 | Append a context-handoff reminder to inbound user messages once a chat's used tokens exceed `min(50% of context window, 200k tokens)` (revised from a flat 20% ratio, which fired 5x earlier in absolute terms on 200k-window bots than on 1M-window fable-class ones). `Chat.context_usage_ratio()` remains the single Python source for the displayed percentage, and `Chat.used_tokens()` is the shared absolute-token accessor both it and the threshold comparison use; `maybe_append_handoff_reminder` runs at the API layer into the persisted message content, wired at all five existing-chat write sites (API send + notify, Telegram routed / DM steer / DM append). Chat-creation sites are deliberately skipped (`context_window is None` makes the check a no-op). Idempotency is structural: the append is decided once where the `Message` is built, deduped across the trailing user batch via the shared `trailing_user_messages()` that the worker also uses to concatenate a prompt, and no worker/agent path recomputes it. Reminder wording states the session's actual usage percentage and token count (no hardcoded threshold percentage, since the effective percentage now varies by window size) and is role-agnostic (no branching on `chat.topic` / `chat.skill`), deferring callback-vs-self-restart to the session per the AGENTS.md "Context handoff" playbook (todo 2976). `english_correction` strips the trailing reminder block so an injected nag is never scored as the user's own prose. Blob-only usage fields, so no migration and no new columns | - | `pages/plan-2951-context-handoff-reminder.md` | - | `pages/review-2951-context-handoff-reminder.md` | shipped |
| 2989 | Established that the displayed context window comes from Claude Code's own `result.modelUsage[*].contextWindow`, which `monitor.py` copies into `Chat.context_window` verbatim. The initial delivery configured `sol` as `gpt-5.6-sol[1m]` and kept claude-relay-service commit `4527d56a` to strip the client-only suffix before upstream dispatch. Todo 2993 supersedes the suffix as the active y-agent mechanism but does not revert that relay-side defensive normalization or alter historical 200K telemetry | - | `pages/plan-2989.md` | - | `pages/review-2989-sol-1m-relay-normalization.md` | shipped; superseded by 2993 for active configuration |
| 2993 | Set `CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000` for every Claude Code subprocess so unknown custom model IDs such as plain `gpt-5.6-sol` report and use a 1M window without a model-string suffix. Known Claude models retain their registered windows. Accepted tradeoff: every unrecognized custom model is declared as 1M even if its real upstream window is smaller; per-bot context-window configuration is the fallback if that becomes a problem. The existing handoff reminder remains capped at 200K used tokens. Deployed from commit `a6ee296`; after the deployment passed, the `sol` bot was reverted to plain `gpt-5.6-sol` | - | - | - | `pages/review-2993-global-max-context-tokens-env.md` | shipped |
| 3064 | Replace the chat panel's stacked filters with one compact `key:value` query input; keep manager always pinned, pin the newest dev chat below it for right-drawer todo filters, and scope routine-filter intents to the left panel | - | `pages/plan-3064-chat-query-input.md` | - | `pages/review-3064-chat-query-input.md` | reviewed; publish pending |
