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
3. As a web user, I want each list row to show the title (first user
   message), timestamp, and badges for trace id, chat id, topic, skill, and
   routine, so that I can identify a chat's place in the session tree at a
   glance.
4. As a web user, I want a running spinner, an interrupted icon, and an
   unread dot on list rows, so that I can see which conversations need
   attention without opening them.
5. As a web user, I want to filter the list by free-text search, todo (trace)
   id, topic, skill, routine name, and running status, so that I can narrow
   hundreds of chats to the ones relevant to a task.
6. As a web user, I want clicking a row badge to apply that badge's value as
   a filter, so that I can pivot from one chat to all its trace / topic /
   skill siblings in one click.
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
    than start a parallel run (delivery mechanics per the steer PRD), so that
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
43. As a user, I want each chat's backend and bot fixed at first run, so
    that changing my default bot never migrates an existing conversation
    between agent backends mid-session.
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
    backend, bot) immutable once set, with mutation attempts logged and
    refused, so that a chat's place in the session tree cannot drift.

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
  (mechanics owned by the steer PRD).
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
  inline (message-list in, reply out, no VM). All CLI agent backends
  (claude_code, claude_tui, codex, gemini_cli, pi_cli) launch as detached tmux
  subprocesses on the user's EC2 VM over SSH, are registered in a process
  table (DynamoDB) for monitoring, and are tailed by a monitor loop that
  appends each streamed event as a chat message. An unset or unrecognized
  backend defaults to claude_tui (subscription usage rather than API budget).
- **Session continuity**: the backend's native session id lives in the chat's
  `external_id`; a follow-up resumes it only when the chat's stored work dir
  matches the resolved cwd, otherwise a fresh session starts. Work-dir
  conflicts on send are rejected, not silently rebased.
- **Identity immutability**: backend, bot name, topic, skill, trace id, and
  routine id are write-once at the repository layer; later saves keep the
  existing value and log a warning on attempted mutation. Root (manager)
  chats deliberately never persist a trace id (a root participates in many
  traces; per-message metadata carries trace context instead).
- **Lambda time limit**: the worker releases its monitoring lease before the
  deadline and re-enqueues itself; the next invocation resumes tailing from
  the stored offset. This is core lifecycle; steer-specific handoff behavior
  (consumed-message continuity) is in the steer PRD.
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
  extraction, and identity-field immutability.
- Steer delivery mechanics are tested under the steer PRD; here only the
  dispatch-side contract (running chat → append without enqueue) is asserted.

## Out of Scope

- **Mid-turn message delivery mechanics** (claim/unclaim, turn-end drain,
  backend kill-and-resume, exactly-once guarantees): owned by the steer PRD.
  This PRD owns only the dispatch-side rule that a running chat gets an append
  with no new task.
- **Bot and tier selection policy** (which bot a dispatch resolves to, tier
  routing, skill-to-tier defaults): owned by the bot-dispatch-tier-routing
  PRD. This PRD treats the resolved bot config as an input.
- **Spend/usage accounting**: owned by the usage-tracking PRD. The per-chat
  context-usage badge (session token counts) is in scope here; the historical
  spend time series is not.
- **Telegram surface specifics** (forum topic binding, webhook routing,
  markdown conversion, image reference delivery): adjacent subsystem; this
  PRD covers only that a completed turn delivers the reply to the chat's
  bound topic.
- **Trace waterfall visualization and public trace shares**: the trace
  subsystem consumes chat records but has its own views and share flow.
- **Context monitor auto-restart** (fresh-chat rollover at context/turn
  thresholds): a policy layered on top of chats, worth its own PRD if it
  changes.
- **Chat import** (`y chat import`, `import-claude`) and the legacy pandoc
  HTML export: maintenance utilities, not part of the core contract.
