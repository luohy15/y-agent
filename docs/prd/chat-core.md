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

1. As a web user, I want a list of my chats ordered by recent activity by
   default, so that I can find and resume any conversation. In the left
   activity-bar chat panel only, I also want to choose server-side sorting by
   updated time or created time, each ascending or descending, so that the
   order is globally correct across infinite-scroll pages rather than only
   among already-loaded rows (todo 3152). The closed options are
   `sort_by=updated_at|created_at` and `sort_order=asc|desc`, defaulting to
   `updated_at` + `desc`. The right-side chat drawer does not expose sort
   controls and always requests the default ordinary-list order
   (`updated_at` + `desc`); its per-location localStorage sort keys from the
   earlier both-mounts ship are ignored. Manager and right-drawer dev pin
   requests stay newest-updated navigation shortcuts and do not take the
   ordinary-list sort mode.
2. As a web user, I want the root manager chat pinned above the list, so that
   my main inbox conversation is always one click away regardless of filters.
   In the right-side chat drawer specifically, when the query is filtered by
   `todo:<id>`, I also want the newest `dev` chat for that trace pinned
   directly below manager, so that I can jump straight to whichever session
   is actually coordinating that todo (this second pin does not apply to the
   left activity-bar panel or to an unfiltered list). When that right-drawer
   `todo:` filter is applied, default selection follows the rendered eligible
   order rather than an independent "newest regular list row" pick: if the
   dev pin is shown, select that dev chat; otherwise select the first regular
   list result. Manager stays a navigation pin and does not win the default
   under a todo filter (todo 3070).
3. As a web user, I want each list row to show the title (first user
   message), timestamp, and badges for trace id, chat id, topic, skill, and
   routine, so that I can identify a chat's place in the session tree at a
   glance.
4. As a web user, I want a running spinner, an interrupted icon, and one
   attention marker per row, so that I can see which conversations need
   attention without opening them. The marker reflects one of three mutually
   exclusive states, `needs_attention`, `unread`, or `none` (an orange marker
   for the first, the existing blue dot for the second, nothing for the
   third). The marker is display-only: attention flags never influence row
   order. Default list order is pure recency (`updated_at` descending, with a
   deterministic internal-id tiebreaker in the same direction as the chosen
   timestamp), so opening a chat or flipping an attention flag never
   repositions its row under the default sort. Running and interrupted stay
   independent execution statuses that render alongside the attention marker,
   not additional attention states.
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
   with that key. The raw query string is persisted in localStorage with a
   distinct key per panel location (`left` activity bar vs `right` drawer), so
   filter state survives refresh and view switches without the two mounts
   overwriting each other (todo 3072; same localStorage restore pattern as the
   bot table sort and todo panel query). On the right drawer the host's trace
   filter still takes precedence for the `todo:` term: if the host holds a
   restored `chatListTraceId`, remount re-applies that value over a
   panel-local override (3046 R7/R8).
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
   reflects what I have actually seen. Opening does not clear
   `needs_attention`: merely reading a question a session is blocked on does
   not unblock the session, so a `needs_attention` chat stays that way until I
   actually reply.
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
54. As a running agent session, I want an explicit built-in command
    (`y chat attention [CHAT_ID]`, defaulting to `Y_CHAT_ID`, with `--clear`
    to reverse it) that flips a chat's `needs_attention` signal, so that I can
    announce I am blocked on Roy answering or confirming without the runtime
    guessing it from my prose. This stays a built-in runtime command, like
    dispatch and stop, so a missing chat module can never prevent a running
    agent from signaling that it is waiting.
55. As a user, I want a completed turn's unread marking to never downgrade an
    already-`needs_attention` chat, so that a session's explicit blocked
    signal survives its own completion hook rather than being silently
    overwritten by the same turn's "mark unread" post-hook.
56. As a user, I want any new user message accepted into an existing chat
    (web/CLI send, dispatch, Telegram routed message, Telegram DM append) to
    clear both `needs_attention` and `unread`, so that replying always
    resolves whatever the chat was waiting on or announcing.

## Implementation Decisions

- **One record, many readers.** The chat row owns the ordered message list
  (JSON), identity metadata, derived status, and unread flag. Workers write
  messages into it as the backend emits them; every surface reads the same
  row. There is no separate streaming channel with its own state: the web SSE
  endpoint and the CLI `--wait` loop are both pollers over the persisted chat.
- **Three-state attention model (todo 3137).** Every chat carries two
  booleans, `unread` (existing) and `needs_attention` (additive: `chat`
  gained a `needs_attention BOOLEAN NOT NULL DEFAULT false` column). The
  projected state a reader sees is `needs_attention` > `unread` > `none`, in
  that precedence: `needs_attention` wins even if legacy or racing writes
  temporarily leave both booleans true. `needs_attention` is never inferred
  from turn content or punctuation — the runtime cannot reliably classify
  whether a successful assistant turn is a completed result or a question, so
  the state has one explicit producer: `POST /api/chat/attention` /
  `y chat attention [CHAT_ID] [--clear]`, owner-scoped like every other
  per-chat mutation (a missing or cross-owner chat both 404 identically
  because the lookup itself is scoped to the authenticated owner). All
  attention/unread writes go through raw-SQL repository setters
  (`set_chat_attention`, `clear_attention_and_unread`,
  `mark_completion_unread`) that never touch `updated_at`, so toggling either
  flag never bumps a chat to the top of the recency-ordered list on its own.
  These three take `user_id` alongside `chat_id` and filter on both in the
  SQL predicate, not `chat_id` alone: `(user_id, chat_id)` is the unique key
  on `chat` (see identity allocation below), so a public chat id is only
  unique per user and a `chat_id`-only predicate could mutate a different
  user's same-id row. Every caller threads its already-known owner through:
  the API endpoint and the four other inbound-reply write sites use the
  authenticated request's `user_id`, the three worker completion sites use
  the `user_id` already carried on their process/proc record. This is a
  correction from the review round that first caught the gap; the pre-existing
  `set_chat_unread` (unread-only, not part of this delivery) still has the
  narrower `chat_id`-only predicate and is a candidate for the same fix as a
  separate follow-up. Three transition rules compose the lifecycle:
  - **Completion preserves a stronger state**: successful completion marks
    `unread` only when `needs_attention` is false (`mark_completion_unread`),
    so a turn that called the attention command mid-run is not immediately
    downgraded by its own completion hook.
  - **Opening clears only `unread`**: inspecting a chat's content does not
    resolve what it is blocked on.
  - **Accepting a new user message clears both flags** (`clear_attention_on_reply`
    / `clear_attention_and_unread`), wired at all five existing-chat inbound
    write sites (the same five as the handoff-reminder mechanism below): a
    reply resolves whatever the chat was waiting on or announcing, whether it
    lands on an idle chat or steers a running one.
  - Ordinary list queries (`storage.repository.chat.list_chats`) accept
    optional closed `sort_by` (`updated_at` | `created_at`) and `sort_order`
    (`asc` | `desc`), defaulting to `updated_at` + `desc` so callers that omit
    them keep the pure-recency order from todo 3141. Ordering is applied after
    every filter and before offset/limit. The chosen timestamp column is paired
    with internal `id` in the same direction as the deterministic pagination
    tiebreaker; `id` stays SQL-only and is never exposed in response payloads.
    On the `created_at` branch only, `created_at_unix` uses `NULLS LAST` in both
    directions: a large historical cohort has NULL `created_at_unix` (and no
    recoverable source column), and Postgres would otherwise put those rows at
    the top of `desc`. The `updated_at` branch stays without an explicit NULLS
    clause so `idx_chat_user_updated` remains usable (`updated_at_unix` has no
    NULLs in production). Attention flags are display-only markers and never
    influence row order, so opening a chat or flipping an attention flag never
    repositions a row under the default sort, and `limit=1` pin fetches remain
    "newest updated".
  - The module contract (`agent.module_host.chat_list`) exposes
    `needs_attention` alongside the existing `unread` (todo 3137, contract v6)
    and optional `sort_by` / `sort_order` (todo 3152, contract v7, floor for
    the chat module). The `chat` module's UI (marker rendering, left-sidebar
    sort controls with a fixed default order on the right drawer,
    `min_backend_version`) is that module's surface, documented in
    `code/y-module/chat/README.md`.
- **Synchronous accept, asynchronous run.** Every send path (create, message)
  persists the user message and sets `running` before returning, then
  enqueues a queue task (SQS in production, Celery filesystem broker in dev)
  carrying the chat id plus routing hints. If the chat is already running, no
  task is enqueued; the running worker's steer polling picks the message up
  (mechanics owned by the chat-steer PRD).
- **One accept-body primitive, one authoritative route (todo 3167).**
  `storage.service.chat.deliver_user_message` is the single place that builds
  the user `Message` (handoff reminder folded in), appends it, saves the chat
  exactly once, clears attention, and enqueues the worker only when the chat
  wasn't already running. It is shared by every existing-chat inbound write
  site: `POST /api/chat/message`'s dispatch-shaped and non-dispatch arms, and
  both Telegram sites (routed message, DM append). The DM-append site absorbs
  the former manager-only "steer a busy root chat" special case: since the
  primitive's already-running check is topic-agnostic, a busy chat on *any*
  topic now steers instead of enqueueing a parallel run, not just `manager`
  (a deliberate behavior change, not just a refactor). The prior duplication
  (`/message` and `/notify` each re-implementing this body, plus three more
  copies in `telegram.py`) collapsed to one primitive; the former `/notify`'s
  existing-chat arm additionally did a redundant second DB write
  (`append_message` read+save, then a second save) that this removes. The
  primitive raises domain errors only, never `HTTPException`; HTTP-shaped
  target resolution (404/400/409) stays in the controller.
- **A request is dispatch-shaped iff it carries any of `trace_id` /
  `from_topic` / `from_chat_id` / `topic` / `skill` / `force_new`.** Only
  dispatch-shaped requests to `POST /api/chat/message` get the
  `[trace:… to_chat:…]` prefix, root-topic rejection, topic/skill stamping on
  a fresh chat, and may create a chat without an explicit `chat_id`.
  Non-dispatch requests (web send, `y chat -i`) require `chat_id` and behave
  exactly as the pre-unification `/message` route always did. The CLI always
  sends `from_topic` (default `manager`), so every `y chat` dispatch stays
  dispatch-shaped. Dispatch-shaped target resolution order: explicit chat id
  (404 if missing, 400 on topic mismatch, owner-scoped lookup so a chat owned
  by someone else 404s identically to a missing one — closing a pre-3167 gap
  where the explicit-`chat_id` arm used an unscoped lookup) > topic + trace
  lookup (resume the trace's existing chat for that topic unless `--new`) >
  create a new chat. Skill defaults to the topic for non-root topics; explicit
  `--skill` overrides. A new chat claiming a topic without a trace id is a
  root claim and releases the topic from any previous holder (singleton root
  topic).
- **`POST /api/chat/notify` was removed outright, not kept as an alias**: Roy
  confirmed every CLI install upgrades in lockstep with the API deploy (no
  out-of-band PyPI consumer to protect), so the CLI's `_fire_and_forget` was
  repointed at `/api/chat/message` (field renamed `message` → `prompt` to
  match) in the same change that deleted the route, rather than staging a
  deprecation window.
- **Root-topic callback rejection** is enforced at the API on the resolved
  target chat's topic, with the `--new` escape hatch only for starting a fresh
  root session. The root topic set is currently the single hard-coded name
  `manager`.
- **Trace metadata rides in-band**: a dispatch-shaped `/api/chat/message`
  request prefixes the message with
  `[trace:<id> from:<topic> to:<topic> from_chat:<id> to_chat:<id>]`
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
- **Chat identity allocation is collision-free and insert-only** (todo 3131):
  a `chat_id` is a 6-hex public id. Generated creation goes through one shared
  allocate-and-insert boundary (`chat_service.insert_generated_chat` /
  `_insert_generated_chat_sync`, used by `create_chat` when no id is supplied
  and by every other create site) that retries the full mint+insert on
  `ChatIdCollision` up to five attempts, so a DB unique-constraint race is
  recoverable rather than user-visible. Creation never upserts: `insert_chat`
  / `add_chat` insert a new row and raise `ChatIdCollision` on the pre-check
  or on the `UNIQUE (user_id, chat_id)` constraint, so a new dispatch can never
  silently overwrite an existing conversation or its running VM session.
  Caller-supplied ids are single-attempt only and surface as HTTP 409 on
  `POST /api/chat`. Re-dispatching an existing chat under a different
  trace/topic/skill is legitimate; the worker logs a loud mismatch warning
  with both values and keeps the persisted identity (write-once). Historical
  overwrite damage is unrecoverable for lost messages; identity-column repair
  is a maintainer-only SQL step, never automatic.
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
- **Handoff reminder is appended at write time, in-band** (plan-2951, folded
  into `deliver_user_message` by todo 3167): every existing-chat inbound write
  site (`/api/chat/message`'s dispatch and non-dispatch arms, Telegram routed
  message, Telegram DM append/steer) appends the handoff reminder to the
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

- Test external behavior at the seams, not the internals: the dispatch-shaped
  `/api/chat/message` resolution matrix (chat id vs topic+trace vs new,
  `--new`, topic mismatch, root-topic rejection, work-dir mismatch) via
  API-level tests with a stubbed queue — prior art exists as an API test
  suite for the former `/notify` route (todo 3167 repoints it at the unified
  handler).
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
- Attention/unread transitions (todo 3137) are repository-level, table-driven
  against an in-memory SQLite chat table: `needs_attention -> completion`
  stays `needs_attention` (unread stays false), `unread -> open` becomes
  `none`, `needs_attention -> open` stays `needs_attention`, and
  `needs_attention -> user reply` becomes `none`; plus a no-timestamp-bump
  assertion for every attention-only write. List ordering (todo 3141) is a
  separate repository-level recency test: `needs_attention`, `unread`, and
  neutral rows still sort newest-first regardless of flags (including
  `limit=1`), equal `updated_at_unix` ties break on internal `id` DESC, and
  paginated pages together return each chat_id exactly once. Owner scoping
  across the three setters has its own repository-level fixture: two rows
  sharing one `chat_id` under different `user_id`s, asserting a mutation on
  one owner's row never touches the other's (the review-round-1 blocking
  finding). The `POST /api/chat/attention` producer endpoint gets its own
  owner-scoped API test (default id via CLI `Y_CHAT_ID`, explicit id,
  `--clear`, missing id, unknown chat, cross-owner rejection, and that the
  authenticated `user_id` is the one threaded into the mutation call).
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
| 3070 | Right-drawer default chat selection follows rendered eligible order under a `todo:` filter: prefer the pinned newest dev chat when present, otherwise the first regular list result; manager remains a navigation pin and does not win the default | - | - | - | `pages/review-3070-right-drawer-default-selection.md` | shipped |
| 3072 | Persist the chat panel query input in localStorage with distinct keys per panel location (`chatListQueryLeft` / `chatListQueryRight`), preserving the compact query input from 3064/3070 | - | - | - | `pages/review-3072-chat-query-persistence.md` | reviewed; shared publish coordinated by 3070 |
| 3103 | Linkify tightly validated absolute `/...` and home-relative `~/...` file paths only inside inline-code spans; resolve `~/...` from the selected VM's runtime `HOME`, preserve relative-path opening, and avoid free-prose or URL false positives | - | - | - | `pages/review-3103-chat-path-links.md` | shipped in chat v17 |
| 3131 | Make chat_id allocation collision-safe: shared `generate_unique_id` allocator, insert-only chat creation (`ChatIdCollision` on pre-check or unique constraint), 409 on caller-supplied id conflicts, loud worker mismatch warnings when dispatch identity differs from the persisted row, and a damage-scan script for historical overwrites. Identity-repair SQL for known victims is maintainer-only and not auto-run | - | `pages/plan-3131-chat-id-collision.md` | - | `pages/review-3131-chat-id-collision.md` | reviewed; local commit `a4c87ba`, not deployed |
| 3137 | Add the three-state `needs_attention` / `unread` / `none` chat attention model: additive `chat.needs_attention` column + raw-SQL semantic setters that never bump `updated_at`, explicit producer (`POST /api/chat/attention`, `y chat attention [CHAT_ID] [--clear]`), completion-preserves-stronger-state and clear-on-reply transitions wired at the worker and all five existing-chat inbound write sites, and `agent.module_host.BACKEND_CONTRACT_VERSION` 5→6. The original delivery also ordered the list by attention precedence before recency; todo 3141 reverts that ordering to pure recency while keeping the marker display-only. Delivered as two halves: the host half (storage/worker/API/CLI/agent contract, migration SQL generated but not applied) and the `chat` module's marker UI + `min_backend_version` 6 bump, see `code/y-module/chat/README.md`. All attention mutations are owner-scoped on `(user_id, chat_id)`, since a public `chat_id` is only unique per user | - | `pages/plan-3137-chat-attention-states.md` | - | `pages/review-3137-chat-attention-host.md` (host), `pages/review-3137-chat-module-attention-ui.md` (module UI) | both halves reviewed and approved, committed; release sequence (migration → backend deploy → module publish) pending user approval |
| 3141 | Restore pure recency ordering in the chat list (`updated_at_unix DESC, id DESC`), keep attention markers display-only, fix module live list refresh so a completed turn repositions its row without a host `chat.refreshList` command, and update chat-core / chat-module docs | - | `pages/plan-3141-chat-list-recency-order.md` | - | `pages/review-3141-chat-list-recency-order.md`, `pages/review-3141-chat-list-live-refresh.md` | reviewed and committed; backend deploy and chat module publish pending approval |
| 3152 | Add server-side chat-list sorting by updated/created time ascending or descending via separate closed `sort_by` / `sort_order` parameters on host `list_chats` and `chat_list` (backend contract 6→7); chat module API/UI request the selected order and stop sorting loaded pages locally. Round-2 host fix: `created_at` order uses `NULLS LAST` so historical NULL `created_at_unix` rows sink instead of leading "Created ↓". Round-4 correction: sort controls live only in the left activity-bar panel; the right drawer always requests `updated_at`/`desc` and ignores any earlier drawer-local sort keys | - | `pages/plan-3152-chat-list-backend-sorting.md` | - | `pages/review-3152-chat-list-sort-controls.md` | host + module implemented in worktrees; left-only UI correction and chat-core docs update; deploy host first then publish chat (not yet authorized from this chat) |
| 3167 | Collapse the duplicated "accept a user message into a chat" body (five existing-chat write sites) behind one primitive, `storage.service.chat.deliver_user_message`, and one authoritative route, `POST /api/chat/message`, with a dispatch-shape predicate (`trace_id`/`from_topic`/`from_chat_id`/`topic`/`skill`/`force_new`) gating the prefix/root-topic/create-without-chat_id behavior formerly unique to `/notify`. Per Roy's confirmed decision, `POST /api/chat/notify` was deleted outright (no deprecation alias) since every CLI install upgrades in lockstep with the API; the CLI's `_fire_and_forget` now posts `prompt` to `/api/chat/message`. Closes an authorization gap (explicit-`chat_id` arm now owner-scoped) and a double-write bug in the former notify existing-chat arm. Telegram's DM steer and DM append sites merged into one call site; the primitive's own running check now steers a busy chat on any topic, not just `manager` (deliberate behavior change). Upload prefix unified to `chat-upload` (drops `chat-notify-upload`) | - | `pages/plan-3167-chat-message-notify-unification.md` | - | `pages/review-3167-chat-message-notify-unification.md` | reviewed and committed locally; not pushed or deployed |
