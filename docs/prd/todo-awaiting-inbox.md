---
title: Todo Awaiting Status and Trace Liveness Watchdog
type: prd
project: y-agent
feature: todo-awaiting-inbox
status: active
---

# Todo Awaiting Status and Trace Liveness Watchdog

## Problem Statement

Roy runs work as a tree of agent sessions and has agreed to stop polling
them. From his side a session is only ever in one of three states: working,
done, or blocked on a decision only he can make. The system has to make those
two non-working endings machine-visible, and it has to catch a dead session
that looks exactly like a working one.

**Telegram is a stream, not a queue.** A session that finishes or gets stuck
sends at most one push message. It scrolls away. Nothing answers the question
"what is waiting on me right now?" A finished todo used to be announced with
the prose "ready for user verification" in a progress note, which no machine
can read. A blocked session asks its question in its own chat, and if that
chat is an anonymous `--skill` child it has no Telegram route, so the question
is never pushed anywhere.

**A dead session looks exactly like a working one.** When a turn ends in an
error the worker stores the error text on the chat and, without an inbox,
pushes nothing. Rate-limit and authorization errors (403, 429) are the most
common cause and are not covered by the automatic resume that only handles
5xx. Hard timeouts and tail failures on topic-less child sessions are equally
silent. From outside, "still working", "silently died", and "stopped without
declaring anything" are indistinguishable.

The three-state contract in the agent configuration already obliges sessions
to end every turn as done or blocked. A rule cannot make a dead session
declare anything, and a live session needs a durable place to declare it.

This rewrite supersedes the earlier separate-field model (`todo.awaiting` as
`question` / `review` / `stalled` / `external` beside `status`). That model
is historical; past delivery notes remain evidence, not a second authority.

## Solution

Make **`awaiting` a todo status meaning "needs human intervention"**,
alongside pending, active, completed and deleted. Normal work follows
`pending → active ↔ awaiting → completed`. Review, question and stalled are
explanations in the result / question / error record, not three persistent
machine states. Status says who has the next action; progress, chat and note
say what that action is.

The unit of the inbox is the trace, which is the todo (trace id equals todo
id). One task may spread across many chats, most of them anonymous children;
Roy handles tasks, not chats. So the inbox is not a new noun and not a new
table. It is the existing todo list filtered on `status=awaiting`.

Use `y todo await <id> [--chat <chat_id>]` and `y todo resume <id>` for the
two transitions. Keep one optional navigation pointer, the existing
`awaiting_chat` column, valid only while status is awaiting. It is not a
second state, reason, ownership claim, or prerequisite for resume.

Drop the reason enum and the `external` machine-wait plus its deadline field.
Machine waits remain `active`, not in the human inbox. Existing durable
machine evidence, rather than a todo flag, tells the watchdog that silence is
expected. Untracked tmux-only waits lose the old grace exemption; that
limitation is explicit below.

Any accepted human message in a bound non-root trace chat auto-resumes
awaiting to active. A callback, server notice, plain dispatch or process
start can occur while human intervention remains outstanding; only
human-message provenance or an explicit resume operation moves awaiting to
active. Resume changes status, not execution: no implicit chat, dispatch,
completion, approval or publication permission, and it does not acquire a
coordinator claim or a publication slot.

The invariant the whole design serves: **every open trace, at every moment,
is either running (`status=active` with live evidence), in the inbox
(`status=awaiting`), or closed.** Anything else on an `active` row with no
live evidence is a fault, and the watchdog converts it into an awaiting
inbox row plus one push message, at most once per fault.

Runtime death stops being silent. Rate-limit-class errors are retried in
place so the most common death becomes a slower working state. An error that
does end the turn is delivered somewhere that wakes someone: Telegram when
the chat has a topic, the parent chat when the child has one, and the inbox
when it has neither. Post hooks never fire on error.

Roy's three exit actions are things he already does: answer in a bound trace
chat (or resume explicitly), finish the todo, or re-dispatch after inspecting
a faulted one. An empty inbox means nothing is waiting on him. The watchdog,
when enabled, guarantees that an empty inbox plus no running session means no
live work exists; enablement remains a separate rollout step.

## User Stories

### The awaiting status on todos

1. As Roy, I want each todo to use `status=awaiting` when the ball is in my
   court, so that "needs human intervention" is a first-class status the
   system can list, not a side field or prose I have to read.
2. As Roy, I want human verification, a question and a terminal failure to
   share that one status, so that I have one inbox and one resume operation
   instead of three machine reasons.
3. As Roy, I want an optional chat pointer on an awaiting todo, so that I can
   jump straight to the conversation that needs my answer, without making
   that pointer a second state or a prerequisite for resume.
4. As Roy, I want the chat pointer to be navigation only, so that clearing
   the row never depends on which chat I happened to answer in.
5. As the trace's reporting session, I want to declare awaiting once after
   the last phase of the trace, in a single command, so that "ready for user
   verification" means the whole task is ready, not that a child phase
   finished.
6. As a session, I want to declare awaiting with an optional chat to answer
   in, in a single command, so that stopping on a decision leaves a durable,
   visible record instead of vanishing.
7. As a session parking on a long machine wait, I want to remain `active`
   while real process or queue evidence exists, so that sanctioned silence
   does not look like something I must act on and does not need a separate
   `external` reason.
8. As Roy, I want any accepted human message in a non-root chat of that
   trace to resume awaiting to active, so that answering is the exit action
   and I never have to clear anything by hand. An informational reply and a
   request for more work are treated the same.
9. As Roy, I want an explicit `y todo resume` (or generic `status=active`)
   to do the same transition without dispatching work, so that I can continue
   in the reporting session or dispatch a later phase independently.
10. As Roy, I want callbacks, generated notices, worker starts and
    read/unread updates never to resume an awaiting todo, so that a child
    finishing a phase, or a process starting, cannot pretend the human
    intervention is resolved.
11. As Roy, I want finishing or deleting a todo to leave awaiting (and
    clear the pointer), so that closed work never lingers in the inbox.
12. As Roy, I want an awaiting change recorded in the todo's history like
    any other field change, so that I can see when a trace entered and left
    the inbox.

### Reading the inbox

13. As Roy, I want `y todo list --status awaiting` to list every todo that
    needs me, so that one command answers "what is waiting on me?".
14. As Roy, I want that filter to compose with the existing priority, tag
    and time filters, so that the inbox is a view of the todo list rather
    than a separate list with its own rules.
15. As Roy, I want the todo sidebar, table and kanban to treat awaiting as
    an ordinary status (shortcut, column, filter, drag target), so that the
    inbox is one click away and each task appears once in its actual status.
16. As Roy, I want an `active` filter to mean work underway and to exclude
    awaiting, so that "what is running" is not silently mixed with "what is
    waiting on me". An explicit open-work query includes pending, active and
    awaiting.
17. As Roy, I want the todo detail to show status awaiting and, when set,
    the chat pointer, so that I can act on a row without leaving the page.
18. As Roy, I want the todo list API to accept `status=awaiting` the same
    way the CLI does, so that the web view and the CLI show the same inbox.

### Runtime death is never silent

19. As Roy, I want a turn that ends on a rate-limit or authorization class
    error (403, 429) with no usable output to be retried automatically with
    backoff, so that the most common cause of a dead session becomes a slower
    working state instead of a death.
20. As Roy, I want that retry bounded to one or two attempts, so that a
    truly broken backend fails within minutes rather than looping.
21. As Roy, I want the retry to keep the existing "no usable output this
    turn" guard, so that a turn that already produced side effects (a commit,
    a message, a todo write) is never replayed.
22. As Roy, I want an errored turn to mark its chat unread, so that the
    death is at least visible in the chat list without opening the chat.
23. As Roy, I want an errored turn on a chat with a topic to be pushed to
    Telegram the way a successful turn is, so that a death on a named session
    arrives where its results would have.
24. As a parent session, I want a child's death delivered into my chat as
    an inbound message naming the child chat, its exit status, and the error
    text, so that I wake up and decide whether to re-dispatch, change tier,
    or escalate, without Roy being disturbed.
25. As Roy, I want a death on a chat with neither a topic nor a reachable
    parent to put its trace into the inbox as awaiting and push one message
    to me, so that no death path ends in silence.
26. As Roy, I want a hard-timeout death delivered through the same
    resolution (topic, then parent, then inbox), so that a timed-out child
    session is no longer mute.
27. As Roy, I want post hooks (plan-to-todo, trace registration, and
    similar success-side effects) to never run on an errored turn, so that a
    death cannot masquerade as a completed step.
28. As Roy, I want the death notice to carry the standard trace prefix when
    it lands in a parent chat, so that the parent's existing trace-mismatch
    checks apply to it.

### The watchdog

29. As Roy, I want a scheduled server-side job, not a session, to check
    every active todo every five minutes, so that liveness is guaranteed by
    the system and the no-poll rule for agents stays exactly as it is.
30. As Roy, I want a trace with no running process record, no chat marked
    running, no pending publication-queue receipt, and no activity for ten
    minutes to be moved from active to awaiting, so that a silent death or a
    session that stopped without declaring anything is caught within minutes.
31. As Roy, I want the stall message to name the trace, the last session,
    its exit status, and its error text, so that I can decide the next action
    from the message alone.
32. As Roy, I want an already-awaiting trace never to be re-alerted, so
    that a broken trace costs me one message, not one every five minutes.
33. As Roy, I want a trace that is already awaiting to be left alone by the
    watchdog, so that legitimate waits never trigger a stall.
34. As Roy, I want an active todo older than twenty-four hours with zero
    chats to enter the inbox once as awaiting, so that a todo whose dispatch
    never happened is not invisible to a trace-level check.
35. As Roy, I want the watchdog to never write progress on a session's
    behalf or re-run any work, so that the only thing it can ever do is make
    a fault visible by moving active to awaiting.
36. As Roy, I want a session that ends a turn without declaring done or
    blocked to be caught by the watchdog exactly like a death, so that the
    forbidden third ending is detectable rather than merely prohibited.

### Contract alignment

37. As a reporting session, I want the three-state contract in the agent
    configuration to name the exact commands for the two legal trace-level
    endings (`y todo await` with optional `--chat`), so that "put the todo in
    the inbox" is executable and not a paraphrase.
38. As Roy, I want the existing chat attention flag left untouched and
    unused by this feature, so that no removal migration or contract bump is
    spent on dead code here.
39. As a leaf session, I never declare the whole trace awaiting for
    verification; my legal turn ending is the callback, so that a finished
    phase does not put the whole trace in the inbox.
40. As the reporting session, I want to write await with a pointer to my
    own chat when the trace ends on a decision only Roy can make, so that a
    genuine block is not labelled as verification in the progress/note even
    though the machine status is the same.
41. As Roy, I want no API guard on which session may write awaiting for
    now, so that the correction stays in contract text until premature writes
    are shown to recur.
42. As Roy, I want to be notified once when a todo newly enters awaiting,
    so that a genuine inbox entry reaches me without polling and without a
    second message for progress-only edits or pointer-only changes.

## Implementation Decisions

### Schema

`status` is the write target. Valid values are `pending`, `active`,
`awaiting`, `completed`, `deleted`. Lifecycle is
`pending → active ↔ awaiting → completed`, with the last step always
performed by Roy (or explicit completion authority). Await is also allowed
from pending so a not-yet-started task can genuinely need input. Resume
always goes to active, never back to a remembered previous status; there is
no previous-status column.

One optional navigation column remains on the kernel `todo` table:

| Column | Type | Meaning |
|--------|------|---------|
| `awaiting_chat` | string, nullable | public chat id to navigate to while `status=awaiting`; navigation only, never used to decide which chat may resume |

The obsolete physical columns `awaiting` and `awaiting_until` are nulled at
cutover and left unread/unwritten until a separately authorized destructive
column-drop step. They are rollback safety, not a second runtime source or
an active compatibility field.

Rejected: a new inbox table (one-to-one with todo, two states to keep
aligned); a reason enum beside status (three values that no longer drive
three exit actions); restoring `external` under another name to hide
untracked tmux waits.

### Command and API contract

```text
y todo await <todo_id> [--chat <same-owner-same-trace-chat>]
y todo resume <todo_id>
y todo list --status awaiting
```

| Surface | Meaning |
|---|---|
| `await ID [--chat CHAT]` | Move pending/active to awaiting, or replace the optional pointer on an already-awaiting todo. |
| `resume ID` | Move awaiting to active and clear the pointer; active is an idempotent no-op. |
| `POST /api/todo/await` | Body: public `todo_id`, optional public `chat_id`; same transition as CLI. |
| `POST /api/todo/resume` | Body: public `todo_id` only; same transition as CLI. |
| Status APIs and bulk changes | Accept awaiting and reuse the same transition helper; they are not a second state writer. |

- Require an explicit todo ID; no implicit environment fallback. Await takes
  no reason or deadline. Omitted `--chat` / `chat_id` clears an old pointer;
  an identical resulting state is a no-op.
- Resume on pending, completed or deleted is an explicit error with guidance
  to activate/reopen as appropriate. It must not silently revive closed work
  or activate an unstarted task. Await on completed/deleted is also rejected.
- Supplied chat must exist for the owner and have this persisted trace ID.
  No root-manager pointer inferred from dispatch metadata. Missing pointer
  still leaves todo-to-trace navigation available.
- Generic `status=awaiting` has await semantics without a pointer; changing
  status away from awaiting clears the pointer. Metadata-only edits do not
  change status or erase a pointer. A repeated generic `status=awaiting`
  write on an already-awaiting todo therefore clears an existing pointer;
  UI writers must not issue a no-op status write on re-drop / re-select.
- Keep activate/deactivate/reopen/finish/delete as ordinary status
  conveniences. `activate` on awaiting delegates to the same
  awaiting-to-active transition, not a side path. Await/resume are the
  canonical agent wording, not redundant required calls.
- Await/resume preserve pin, priority, progress and tags. They do not
  populate `completed_at`. Existing completion/reopen semantics continue;
  the generic status side-effect code must not auto-unpin on active/awaiting
  transitions merely because status changed.
- New endpoints return the public todo and `changed`; CLI reports the actual
  status/no-op. Errors apply no partial changes. The API remains
  owner-scoped; no public integer IDs.
- `todo update --awaiting/--awaiting-chat/--awaiting-until`, `chat
  --resume-work`, list `--awaiting`, API awaiting filters, UI `awaiting:`
  query vocabulary and dispatch resume plumbing are removed. Old request
  keys fail clearly with no mutation (`awaiting filter is removed; use
  status=awaiting`, `resume_work is removed; use y todo resume / POST
  /api/todo/resume`). No permanent aliases or automatic interpretation of
  old reason values.

### Writers and clearing

- **Every todo mutation is a transaction-local field patch under an
  owner-scoped row lock**, with the history entry appended to the current
  row. Creation is the only remaining whole-row save. Status, pin, bulk and
  generic updates all go through the same primitive, and a combined request
  is validated and applied in one transaction: a rejected request applies
  nothing. Preserve todo-before-chat lock order; no detached DTO can restore
  an older status.
- **Sessions write awaiting through `y todo await` / `POST /api/todo/await`**
  (or generic `status=awaiting`). The API does not distinguish a reporting
  session from a leaf: any session on the trace may still write awaiting.
  Contract text, not the API, restricts verification-await to the reporting
  session after the last phase. A leaf may await with its own pointer only
  for a decision neither it nor its parent can resolve.
- **The watchdog and the worker write awaiting** through one internal
  `claim_fault` primitive that holds the todo lock, requires the expected
  todo timestamp and current `active` status, and runs a mandatory
  caller-supplied evidence recheck under the lock. Callers' recheck closures
  refuse any trace with a SQL-running chat, a live process, or a pending
  publication waiter. `recheck` is a required keyword argument (a missing
  one is a `TypeError`, not a graceful abstain); returning `None` from
  recheck aborts without mutation. Fault explanation is stored in the
  existing history entry (`; fault: …`, bounded to 1000 characters), not a
  reason enum or a synthetic agent progress message.
- **Awaiting clears on an accepted human message**, resolved by the chat's
  persisted trace id, never by the pointer, and only when the current status
  is awaiting. Human replies and agent dispatches both carry the user role,
  so the accept path takes an explicit provenance argument rather than
  inferring from role or prose: plain web and interactive-CLI sends and
  authenticated Telegram user messages are human; dispatch-shaped requests
  and worker-generated notices are not. A human deliberately using the
  dispatch surface keeps dispatch semantics. Root manager messages do not
  resolve a todo from prose or queue trace metadata. An answer relayed from
  manager may be followed by explicit resume in the reporting session. Read-
  state and unread changes clear nothing.
- **Human auto-resume is atomic with accepted message persistence**; a
  rejected or rolled-back append preserves awaiting. User input already
  accepted does not mean the worker was successfully enqueued or finished.
  If a human asks "what does this mean?", the task becomes active while the
  session answers. If intervention is still needed afterward, the reporting
  session awaits again; that re-entry sends a new notice. Auto-resume means
  "input received, session takes responsibility", not "the decision is
  resolved" or "push authorized".
- **No callback / run-entry auto-resume.** Chat acceptance of a dispatch,
  generated notice, or worker start shares the locked transaction for the
  chat write but does not call resume. `resume_work` is rejected before any
  delivery, enqueue, or todo mutation.
- **Conflicting trace identity is rejected, not reconciled.** An existing
  non-root chat that receives an explicitly conflicting trace id fails before
  acceptance: the API returns 400 with no append, enqueue, or mutation; the
  worker's run entry raises before delivery or launch. An omitted trace is
  not a conflict, and an unbound non-root chat may acquire its first trace.
  Root `manager` chats are long-lived conversations: a queue trace never
  binds them to a todo or resumes anything, and a legacy persisted root
  trace is preserved. The accepted record is
  `pages/decision-3458-trace-identity-rejection.md`.
- **Finish and delete** (single, bulk, or generic status update) move
  awaiting to completed/deleted and clear the pointer. Deactivate moves it
  to pending and clears the pointer.
- **The existing `chat.needs_attention` column, its API, CLI command, and
  module wiring stay in place and unused.** Nothing reads or writes it from
  this feature.

### Reading

- `y todo list --status awaiting` is an additional AND over every existing
  priority, tag, time and pagination filter. There is no independent
  `--awaiting` flag.
- Every returned row carries `status` and `awaiting_chat` (explicit null
  when unset). `y todo get` renders `Reply in:` only when a pointer is set.
  Public DTOs omit the obsolete `awaiting` / `awaiting_until` fields.
- The trace todo projection, both authenticated and public share, carries
  `status` and `awaiting_chat` so the host todo detail renders awaiting and,
  when set, the chat pointer without another request. The pointer is a
  chat-navigation control only when the viewer is authenticated and
  `status === "awaiting"`; on a public share it is inert text. The
  projection widens no disclosure: a pointer can only name a same-owner chat
  of a trace the share already lists.
- The todo module panel (UI-only, consuming host REST) treats awaiting as a
  status: sidebar shortcut, table filter, kanban column with its own
  status-scoped fetch and drag-drop, context-menu status list, detail sort
  defaults, and demo fixture. The independent Awaiting shortcut, submenu,
  reason badge, `awaiting:` query vocabulary and reason colour palette are
  gone. Same-status re-select / re-drop sends no request. Closed todos
  cannot be moved to awaiting from the menu or kanban.
- `awaiting → active` from the module routes to `POST /api/todo/resume`;
  `* → awaiting` routes to `POST /api/todo/await` without a `chat_id`.
  Functionally the host's generic `update_status` delegates to the same
  helpers; the module uses the canonical surface.
- Host `TraceTodoDetail` adds awaiting to the status select and deletes the
  patch key when the selected value equals the current status, so the host
  detail never issues the no-op status write that would clear a pointer.
  Status badges: awaiting is cyan on the host (`statusBadgeClass`) and on
  the module (table badge, kanban column, context-menu dot), so the two
  slices agree and no longer collide with pending (grey on the host, yellow
  on the module). Status text is always rendered next to the badge. History
  actions `awaiting` / `resumed` have colours.
- Dashboard "urgent" and "important" open-work filters include awaiting;
  the "active" / current-task bucket stays `status == "active"`.
- **Inbox entry notification.** After the locked transition commits, one
  best-effort owner DM fires iff the todo newly entered awaiting (previous
  status was not awaiting). Pointer-only changes, progress-only edits,
  resume and closure are silent. Await → resume → await notifies again. Any
  writer, including Roy's own context-menu click or a fault claim, triggers
  the DM. A failed send never raises and never undoes the durable inbox row.
  No exactly-once promise.

### Agent notice and fault-notice wording

Agent notice is compact: todo ID, name, and optional answer-chat pointer,
with no invented review/question/stalled label.

```text
Todo <id> needs you
<name>
Answer in chat <chat_id>: reply here with "/<chat_id> <your answer>"
```

The third line is present only when `awaiting_chat` is set and the notice
is not a fault notice. System fault notice may additionally carry bounded
fault evidence supplied by the triggering event, not read from a reason
field.

**Neutral fault-notice wording.** When the triggering event supplies fault
`extra` (watchdog idle/backstop or undeliverable death), the notice must
not tell Roy to answer in the pointed chat, even if the claim stored the
newest-chat id as `awaiting_chat`. That pointer is often a dead child.
Replying there would auto-resume the todo and restart that child. Fault
notices therefore omit the "Answer in chat … reply here with …" line and
present the pointer, if shown at all, as inspection context (last chat,
exit, bounded error text), not as a place to type the next instruction.
Human-declared awaits (reporting session, optional `--chat`) keep the
answer-chat line, because that pointer names a live session waiting for
input. Shipped in `awaiting_notice_text`: the answer-chat line is appended
only when `todo.awaiting_chat` is set and `extra` is absent
(`if todo.awaiting_chat and not extra`).

### Runtime death delivery

- **Rate-limit-class resume, narrower than story 19's wording.** The retry
  predicate shared by the monitor and the stream converter accepts anchored
  API 429 text, and API 403 text only with affirmative throttling or
  rate-limit evidence and no permanent-failure evidence (invalid
  credentials, billing, access, or model permission). Generic forbidden
  errors are not retried. The anchored 5xx arm is unchanged. The refusal,
  prior-output, and single-retry guards stay: one retry means **two attempts
  in total**. The converter suppresses retryable error text only when the
  message carries no tool calls, so an error accompanying a tool call still
  counts as usable output and the turn is never replayed.
- **Bounded backoff without a silent gap.** The retry waits one 30-second
  non-blocking delay. The pending result and an absolute retry deadline are
  persisted on the process record; the process stays running and the chat
  stays SQL-running through the delay, so the watchdog and the orphan sweep
  keep treating the trace as live. If the Lambda has insufficient time left
  the lease is released without completing the process and the next
  invocation finishes the retry. The delay re-reads the chat and re-checks
  interruption and current run identity before consuming the single retry
  through a conditional claim; a crash after that claim cannot replay a
  second retry, because the exhausted counter sends the next pass to the
  error arm. This favors no duplicate side effects over guaranteed retry.
- **Terminal handling is a single-winner claim.** Error and timeout share
  one owner-scoped terminal transaction (todo lock, then chat lock, reload
  messages) that conditionally completes the process record only if it is
  still running for the same owner and start time. A loser writes nothing,
  so two concurrent handlers for one death cannot append two error messages
  or wake a parent twice. Process registration uses fractional-second start
  times so fast successive turns stay distinct. The timeout path appends its
  message into the same DTO the terminal persistence writes.
- **The error branch** marks the chat unread independently, then resolves
  one delivery target in order:
  1. the chat has a topic: push to Telegram through a checked text send that
     reports success or failure (primary success, formatting fallback,
     rejection, missing target, transport error all classified). A failed
     topic push falls through to the inbox instead of reporting success;
  2. the chat has a validated parent: the parent chat id is parsed from the
     anchored, full-line dispatch prefix on the child chat's first user
     message (duplicate keys rejected; `trace` and `to_chat` must match the
     child; `from_chat` must not be the child itself), and the parent must
     exist for the same owner, carry the same persisted trace, and not be a
     root topic. The death is delivered as an inbound message with the
     standard trace prefix through the shared dispatch acceptance in the
     service layer, which the API route also uses. Missing, malformed, or
     mismatched evidence is never guessed into topic routing; a refused or
     failed delivery falls through;
  3. neither: conditionally claim awaiting on the trace's todo via
     `claim_fault` (never over a non-active row, a closed todo, a newer live
     run, a SQL-running or process-running sibling chat, or a pending
     publication waiter) and, only as the claim winner, let the shared
     post-commit notice hook send one owner DM. The old death/watchdog
     direct send is gone so it cannot duplicate the status-entry notice.
- A chat with no topic, no parent, and no trace (a plain web chat) ends with
  the unread mark only; there is no todo to mark awaiting and nothing is
  pushed. This is unchanged from before and is recorded under Delivered
  limitations.
- The tail-retry-exhausted and orphan-running-chat paths keep their current
  behaviour and are covered by the watchdog. Post hooks, image
  consolidation, and the success-side Telegram reply never run on error or
  timeout.
- Death persistence and target resolution use owner-scoped reads and writes
  throughout; a public chat id is never an ownership authority.

### The watchdog

- A scheduled action in the worker Lambda's dispatcher, fired by its own
  EventBridge schedule every five minutes. The schedule is deployed
  **disabled** and flipped on only at the last rollout step; it is disabled
  again first when rolling the host back. The same dispatcher action runs
  the orphan maintenance below before classification and reports both
  results. This task has not checked live AWS state or enabled it. Do not
  claim runtime recovery guarantees from design-only checks.
- **Classification is a pure function** over (live, chat count, last
  activity, created time, now) returning idle, backstop, or nothing. It no
  longer reads a reason field or `awaiting_until`. Each suppressor stands
  alone. Zero-chat todos fall only under the 24-hour backstop, never the
  ten-minute idle rule. The pass scans `status == "active"` only.
- **Evidence.** The pass first takes a fully paginated process snapshot
  keyed by owner (live by owner plus trace id, and by owner plus chat id
  mapped back to the chat's persisted trace). A snapshot failure aborts the
  pass before any SQL read or write, because a partial snapshot is unknown,
  not empty. Active todos are read across all owners in keyset batches with
  one grouped chat aggregate per batch (count, newest chat update, running
  count). Last activity is the newer of the todo's update time and the
  newest chat update on the trace.
- **Publication queue is existing real dependency, not a todo flag.** Todo
  3493's park/unpark writes of `external` are removed. A same-owner trace's
  pending `dev_release_waiter` suppresses idle fault classification,
  including under-lock recheck. It ends on grant/cancel/reject; grant wakeup
  recovery remains owned by that subsystem. No pending-queue TTL or user
  question is invented here. A granted receipt with failed/unfinished
  delivery is not a pending waiter and must not suppress silence forever.
  Its existing recovery can wake the coordinator; otherwise ordinary
  active-trace fault detection can put it in awaiting. That does not
  release or transfer publication ownership.
- **Untracked tmux-only waits lose the old grace exemption.** A detached
  tmux job without a live existing process record or durable queue receipt
  can be classified as idle even if its eventual callback is configured.
  Progress text is not machine evidence. Do not promise that merely naming
  tmux or setting a callback prevents this. Prefer already-monitored
  execution for long tasks. An awaiting notice in this case requests
  inspection, not proof the job died. Do not use fake running flags,
  periodic progress heartbeats, pending status or new timeout flags to hide
  it. If maintaining arbitrary tmux grace is mandatory, that requires a
  separately approved real process-liveness integration, not silently
  restoring `external` under another name.
- **Claiming.** Each candidate goes through `claim_fault`: under the todo
  lock it re-reads the trace's chats, rejects any SQL-running chat, performs
  a consistent per-chat process read (owner matched; a running record
  suppresses), consults pending waiters, and re-runs the classifier on the
  locked row with the current clock. Concurrent or consecutive passes yield
  one claim and one push. Only the winner notifies, through the shared
  post-commit hook; a failed push leaves the durable inbox row in place and
  is never retried because the row is already awaiting.
- **The notice** names the trace, the newest chat on it, that chat's own
  exit outcome from its same-owner process record (else `unknown`; process
  records expire after 24 hours and an idle chat status is not an outcome),
  and, only when the outcome is error or timeout, that chat's last assistant
  error text bounded to 1000 characters. An older chat's record is live or
  not-live evidence only and is never attributed to the newest chat.
- The watchdog writes only status, pointer, history and timestamps. It
  never touches progress or chats, and never enqueues work.
- **Periodic orphan maintenance is a prerequisite and a separate step.** The
  existing orphan-running-chat sweep ran only when a monitor loop started,
  so a chat stuck SQL-running with no process could suppress the watchdog
  indefinitely once the last process disappeared. Its cutoff also compared a
  millisecond timestamp against seconds and could never match; the fix makes
  the intended 15-minute grace effective for the first time. The sweep is
  now owner-aware, keyset-paginated, runs both at monitor start and from the
  scheduled action, and only shortlists from the scan: each clear happens
  under the todo-then-chat lock, re-checks status and age, and requires a
  fresh owner-matched consistent process read showing no live process,
  because a successful scan can omit a live record. A scan failure clears
  nothing; a per-candidate lookup failure leaves that chat running, is
  counted, and marks the sweep `degraded`. A start that lands between the
  page read and the locked clear wins. No direct death delivery was added
  for orphans or tail exhaustion.

### Contract text and trace-terminal ownership

`done` and `blocked` are trace-level states. Only the trace's reporting
session declares them: a topic-bound coordinator, or any session whose
dispatch prefix says it came from the root manager topic. That session
writes `y todo await <id> [--chat <reporting_chat>]` after the last phase
of the trace (implementation, review, commit, and deploy when the todo
requires it), having first recorded the actual result or question in
progress/note. It writes `y todo resume <id>` when continuing directly
after input received elsewhere, then independently dispatches if a later
phase is needed. Dispatch and resume are separate transactions by design:
dispatch failure leaves active because the caller took responsibility.

A leaf never declares the whole trace ready. Its legal turn ending is the
callback, which wakes the parent and keeps the trace live. Stopping without
a callback is the forbidden third ending. A leaf may await with its own
pointer (or hand the question to the parent via callback) only for a
decision that neither it nor the parent can make.

There is no API guard: any session on the trace can still write awaiting.
Ownership is contract text, owned by the `hr` role. A server-side rejection
of await from topic-less chats is out of scope unless premature writes
recur.

The watchdog scans only `active` rows, so a premature leaf await would hide
later silence, which is why leaves must not write it for verification.
This is a contract decision, not a hidden worker auto-clear.

Agent configuration (`AGENTS.md`, `dev` / `impl` / `review` SKILL.md, tmux
guidance) activates only after the S4 cutover, when installed CLI and
deployed API match. Until then the live files still describe the old
`--awaiting review|none` / `--resume-work` surface.

### Atomicity and notices

- One owner-scoped locked transition function owns status, pointer cleanup,
  history, completed_at and pin semantics for await/resume, ordinary status
  APIs, human acceptance and fault claims.
- Explicit resume and subsequent dispatch are separate transactions. It
  self-recovers or records the final inability and awaits again; a crashed
  caller is covered by the watchdog only when enabled. No rollback to an
  old wait after intervening work.
- Identical operations are idempotent, not generation-scoped requests: a
  later explicit resume can consume a newly declared await. Do not blindly
  replay an ambiguous request after intervening work. No generation
  column/outbox framework is proposed for todo lifecycle.

### Migration and rollout

This is a status/data-contract change, not a field rename. Old readers that
query active will no longer see awaiting tasks, and old binaries cannot
safely write the new model. Coordinated maintenance cutover, not dual-write
state authorities. Manual SQL only, under
`/Users/roy/luohy15/code/y-agent/migration/`; maintainer runs it after
authorization. Companion checklist:
`pages/migration-3506-todo-awaiting-status.md`.

| Existing row at cutover | New representation |
|---|---|
| Non-closed status + awaiting review/question/stalled | status awaiting; keep valid same-owner same-trace pointer if present. |
| Non-closed status + awaiting external | status active; no deadline or reason; inspect any real outstanding machine wait in preflight. |
| No old awaiting value | Status unchanged. |
| Completed/deleted regardless of stale old fields | Remain closed; clear obsolete fields/pointer. |
| Unknown status/reason or invalid non-null pointer | Report in preflight; resolve explicitly, do not silently invent a mapping. |

Capture affected rows/counts and preserve previous status/reason/deadline in
migration history evidence without sending inbox notifications. Keep
historical entries intact. No mechanical old-binary rollback is safe: new
awaiting rows no longer reveal whether they used to be
review/question/stalled. Recovery needs the cutover snapshot plus
reconciliation of later writes and separate approval. Do not restore a
database snapshot over subsequent user activity automatically.

Stage tested host/CLI/module candidates first. Pause mutating
ingress/worker dispatch and scheduled fault writers, drain running
old-instruction sessions, inspect outstanding queue/tmux work, perform the
maintainer migration, deploy the matching binaries/module, upgrade
local/EC2 CLI, activate HR wording, then resume traffic. Existing browser
tabs must refresh; reject obsolete payloads explicitly rather than silently
ignoring them.

### Delivered limitations

Recorded so they are not mistaken for regressions:

- **Best-effort push.** The awaiting transition is durable and
  deduplicated, but a crash between the commit and the Telegram send omits
  the push, and a run starting after the final recheck can race an
  already-issued notice. Exactly-once delivery would need an outbox, which
  is not part of this design. Notices describe an observed outcome, not a
  guarantee that the trace is still dead.
- **Root snapshot lag.** A root `manager` process carrying a todo's queue
  trace is visible to the watchdog only through the initial snapshot, not
  the per-chat recheck, because it has no persisted trace. The exposure is
  the snapshot-to-claim lag, which has no demonstrated upper bound; strict
  suppression of root processes under races is not claimed.
- **Classifier degraded health.** The orphan sweep reports `degraded` when a
  candidate lookup fails; the classifier still records pipeline success when
  a candidate recheck fails. Fail-closed behaviour (no awaiting write on
  failed evidence) holds either way.
- **Silent trace-less death.** A chat with no topic, parent, or trace ends
  with the unread mark only.
- **Untracked tmux waits.** Dropping `external` means a detached tmux job
  without a live process record or durable queue receipt can be classified
  idle. An awaiting notice then requests inspection, not proof of death.
- **Pre-existing TypeScript errors.** Host typecheck reports one unrelated
  error (`TerminalView.tsx`); the module SDK typecheck reports pre-existing
  errors under the todo UI. None were expanded into this delivery.
- **SQL and DynamoDB are not one transaction.** A SQL failure after the
  process record is completed can leave an orphan SQL-running row; periodic
  orphan maintenance is the required cover.

## Testing Decisions

Tests are local-only and untracked per repo convention.

- **Awaiting status transitions** are table-driven over the service layer:
  await from pending/active; resume to active; closed/unstarted resume
  rejected; pointer replace vs identical no-op; generic `status=awaiting`
  without a pointer; metadata-only edits; pin/completion semantics; bulk
  behaviour; rejected legacy `awaiting` / `awaiting_until` / `resume_work`
  requests.
- **List filtering** at the service and API level: `status=awaiting` is the
  inbox; `status=active` excludes awaiting; open-work queries include
  pending/active/awaiting; unknown awaiting filter keys 400.
- **Human auto-resume** on an accepted human message in a non-root persisted
  trace chat, atomic with the append; rejected/rolled-back append preserves
  awaiting; dispatch, callback and run-entry never resume; no cross-owner
  resume.
- **Fault claims** enter awaiting with fault text in history plus one
  notice; abstain on `recheck=None`; skip recheck on stale `updated_at_unix`
  or non-active; never repeat. Pending waiter suppresses; granted /
  cancelled / rejected receipts do not.
- **Resume widening** extends the existing resume tests: 429 and
  throttling-class 403 error text with no usable output resumes; permanent
  403 does not; the same with usable output (including an error line that
  carries tool calls) does not; a third attempt never fires; 5xx behaviour
  is unchanged. Fake-clock and deadline tests prove the 30-second delay
  leaves no completed-to-unlaunched gap across a Lambda handoff, that
  interruption cancels the retry, and that only one relaunch occurs.
- **Error-branch delivery** is one focused test per resolver arm: topic chat
  pushes to Telegram; topic-less child with a parent appends a prefixed
  inbound message to the parent chat; refused parent delivery falls through
  to awaiting plus notice; no topic and no parent sets awaiting and notices
  once; post hooks are asserted absent on every arm; the timeout handler
  reaches the same arms.
- **Watchdog classification** is a pure function over (live, chat count,
  last activity age, todo age) tested as a table, with a row per suppressor
  proving it alone prevents a stall. Two consecutive passes produce one
  push. The backstop row fires once. A mutation test asserts the pass never
  writes progress or a chat.
- **Owner scoping** follows the chat-core precedent: two todos sharing a
  public id under different users, asserting every awaiting read and write
  touches only the owner's row.
- **Web / module** unit tests cover status shortcuts, kanban, closed-todo
  refusal, same-status no-write, and await/resume routing against fixture
  rows; no browser-driven runtime check by default.
- **Verification isolation is mandatory.** Every Python verification sets
  the database URL environment variables before application imports and
  installs a fail-closed SQLAlchemy connection guard: mocked suites permit
  no connection at all; integration suites permit only a throwaway local
  PostgreSQL cluster. The guard counts unexpected attempts and forces a
  non-zero exit even when application code swallows the exception. This
  became a rule after review found stale fixtures reaching the production
  database while green; a green unguarded suite is not evidence of no
  production access.
- **Concurrency tests run on real PostgreSQL**, not mocks: two fault
  claimers with one winner; progress and pin saves that cannot erase a claim
  or its history; claim-versus-start and claim-versus-new-running-insert
  races ending live; duplicate concurrent terminal handlers yielding exactly
  one persisted error message and one parent or topic notice, against a
  DynamoDB fake that evaluates the caller's own condition expression so
  removing the guard fails the test.
- **Orphan maintenance** tests prove a stale successful scan cannot clear a
  chat whose fresh consistent read is running, another owner's identical
  public id is not evidence, a lookup failure preserves that row while the
  sweep continues, and a swept chat is detected exactly at the following
  ten-minute grace.
- The suites actually run and their counts are recorded per slice in the
  review notes listed under Delivery Records.

## Out of Scope

- **Inbox items without a todo**: routine alerts (daily scan, ingest
  monitor, credit check) and self-started design or PRD chats. They still
  push to Telegram and still scroll away. Bringing them in would abandon
  "inbox is a todo view" for a separate table; revisit after the todo-backed
  inbox has run for a while.
- **Progress-reporting obligations, heartbeats, or a dispatch-time backend
  health check.** All rejected in the approved proposal.
- **Restating or changing the no-poll rules** for agents. The watchdog is
  the single system-side reconciler; agents keep the existing prohibition.
- **Removing `chat.needs_attention`** and its API, CLI, module wiring, and
  contract version. Left as dead code for a later cleanup.
- **Direct delivery for the tail-retry-exhausted and orphan-running-chat
  paths.** Covered by the watchdog's ten-minute grace, not by targeted
  messages.
- **Multiple simultaneous questions on one trace.** `awaiting_chat` holds
  one pointer; leaf sessions are expected to route questions through their
  parent, so one question per trace at a time is the contract. Widen to a
  list only if it is observed to collide.
- **A generic machine-wait framework or live-process fencing for arbitrary
  tmux jobs.** Dropping `external` accepts the untracked-tmux limitation
  unless a separately approved process-liveness integration lands.
- **Persisted dispatch edges, callback quarantine, synthesized recovery
  callbacks, and the `y trace` operator surface**: owned by the
  [session-tree-recovery](session-tree-recovery.md) PRD. That PRD's
  classifier currently names the chat attention flag as its "blocked on Roy"
  suppressor and states that it does not extend the automatic retry; this
  feature makes `status=awaiting` the source of "blocked on Roy" and widens
  the retry's error class. Reconciling those two statements is a pending
  edit to that PRD, not to this one.
- **Dispatch target resolution, root-topic rejection, and the notify
  request contract**: owned by the [chat-core](chat-core.md) PRD. The
  error-branch delivery uses that route as-is.
- **Org-review detection** of the forbidden third turn ending as a monthly
  scan item.
- **A push outbox or exactly-once notice delivery**, global unscoped
  worker-id cleanup, and callback idempotency. The awaiting status
  guarantees durable dedup, not crash-safe Telegram delivery.
- **Watchdog enablement, production mutation, and automatic todo finish.**
  Cutover SQL is maintainer-run after authorization. Agent-config activation
  waits on S4.
- **Non-blocking review nits** listed in the review notes under Delivery
  Records and deliberately not expanded into this delivery (including stale
  `actionColor` keys and `awaiting-menu.ts` naming).

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3455 | Approved proposal: three-state contract, inbox as a todo field, liveness watchdog; rejected alternatives recorded | - | - | `pages/proposal-3455-three-state-model.md` | - | approved; contract text shipped to the agent configuration |
| 3458 | Rate-limit-class resume with bounded backoff, single-winner terminal handling and ordered death delivery (topic, validated parent, inbox), `awaiting` field with locked transitions and conditional clears, CLI/API filter, host trace detail reason and question pointer, todo module inbox panel, five-minute liveness watchdog plus periodic orphan maintenance | - | `pages/plan-3458-todo-awaiting-inbox.md` | `pages/decision-3458-trace-identity-rejection.md` | `pages/review-3458-awaiting-foundation.md`, `pages/review-3458-awaiting-runtime.md`, `pages/review-3458-awaiting-watchdog.md`, `pages/review-3458-awaiting-ui-module.md`, `pages/review-3458-awaiting-host-detail-ui.md`, `pages/review-3458-awaiting-integration.md` | host `06e9de6` deployed via successful backend/web workflows; schema applied and verified (`pages/migration-3458-todo-awaiting.md`); module source `acafb17` plus iteration-2 `d7d0f7a` landed locally and todo v15 published active (UI `8eec93ccb926b13e4b72be7304120a6ea7db5a21a8fd7182343580336385ed44`); Awaiting is first with exclusive shortcut highlighting; all slice/integration reviews and module round 3 approved, canonical pre-publish digest matches published v15 and source identity matches review; ready for user verification. Iteration-2 delivery: `pages/delivery-3458-awaiting-ui.md`. Host landing: `pages/landing-3458-awaiting-host.md`. Module Git push held because main includes three unrelated unpushed commits. Compatibility correction: `pages/impl-3458-awaiting-s8-auto-unpin-compatibility.md`. Impl notes: `pages/impl-3458-awaiting-foundation.md`, `pages/impl-3458-awaiting-runtime.md`, `pages/impl-3458-awaiting-watchdog.md`, `pages/impl-3458-awaiting-ui-module.md`, `pages/impl-3458-awaiting-host-detail-ui.md`. Remaining gates: hr executable commands and trace-terminal ownership alignment, representative-trace verification and orphan-maintenance rollout review before enabling watchdog. Five-minute EventBridge schedule deployed DISABLED. CLI/API read-only awaiting checks passed; no browser verification. Rollback latest UI iteration: `y module activate todo 14`; rollback entire inbox module feature: `y module activate todo 13` |
| 3467 | Verdict: `review` intentionally rejects `awaiting_chat` / `awaiting_until` (3458 design, kept). Fixed the actual defect: `y todo update` surfaced the server's rejection as a raw traceback instead of the API's `detail` message. Sharpened both rejection messages to name the required reason; `api_request` now re-raises `HTTPStatusError` carrying the response `detail`; the root CLI group renders any uncaught `HTTPStatusError` as a clean `Error:` line instead of a traceback | - | `pages/plan-3467-awaiting-chat-review-rejection.md` | - | `pages/review-3467-awaiting-chat-error-surface.md` | shipped cc7946e (deploy run 34466919844) |
| 3471 | Awaiting set/reset from the shared todo context menu (sidebar, table, kanban) via a new `Awaiting ▸` submenu. Final shipped set is `none` (the only reset) and `review`; `stalled` is display-only and never a write target, status is never changed, closed todos are fully disabled | - | `pages/plan-3471-todo-awaiting-context-menu.md` | - | `pages/review-3471-todo-awaiting-context-menu.md` | module source `de1e3b0` landed on y-module main and todo **v16** published active (UI `41af8e781f5731e8ad31b3b68f0e3e8167adaff841520e61196ac76002300b16`, source digest `8a841773d9c5c518dfe46e740199e436b25d5f7208d79a37c39cbdca7e06210b`, min host 13). Module-UI only: no host, CLI, schema, or module-contract change, no migration. Review approved at round 2 after blocking R1 (async submenu measured placement once against the 7-row placeholder and never remeasured when the chat fetch grew it to ~14 rows, so choices could fall off-screen near a viewport edge); fixed by extracting a pure `placeSubmenu()` into `awaiting-menu.ts`, remeasuring on `awaitingChoices` change, a viewport-capped `maxHeight` with `overflowY: auto`, and exempting in-submenu targets from the capture-phase scroll dismiss. Static verification only, no browser checks: awaiting-menu 34/34, query 92/92, demo 31/31, selection 52/52, stale-payload 78/78, build exit 0, typecheck at the unchanged 14 pre-existing `todo/ui` errors. Impl note: `pages/impl-3471-todo-awaiting-context-menu.md`. Digest note: a worktree build and a canonical-main build of identical source differ in UI sha256 because esbuild embeds build-relative path comments; `source_digest` is the source-identity invariant and matched, and the canonical rebuild reproduced the published `41af8e78…` exactly. Iteration 2 (user-requested on shipped v16): trimmed the submenu to `none` + `review`, deleting `external`, the `+4h`/`+24h` presets and the whole same-trace chat picker along with every helper that died with them (`externalUntil`, picker limit/loading/format helpers, the SWR chat fetch, the async remeasure dependency) rather than leaving them unreachable; `placeSubmenu` viewport clamping retained. Also root-caused a hover cross-highlight defect in v16: `Set priority` and `Awaiting` shared one `submenuRowHover` boolean, so entering either highlighted both while the open submenu was already exclusive; fixed by deleting the boolean and deriving the highlight from the same exclusive `openSubmenu === item.key`. Landed `c3d13af`; todo **v17** published active (UI `1c8d6c93f2509219daeed65638888273a2caad606f1e2bf795fc6e88da0fa1b8`, 135089B, source digest `527a9b66b3a9f1283f3fa42587e9a42085611a3d97a7974ff8159adde8039f69`), canonical-main rebuild reproduced that UI digest exactly and the source digest matches review round 3. Review approved at round 3 (awaiting-menu 23/23, other suites unchanged, typecheck at the same 14 pre-existing errors), with one documentation nit: the impl note's `mouseleave` DOM rationale is inaccurate, though the shared-boolean root cause and the fix are correct and do not depend on it. Hover regression assertions inspect source wiring, not dispatched DOM events. Module Git push still held because main carries unrelated unpushed commits. Rollback iteration 2: `y module activate todo 16`; rollback the whole 3471 delivery: `y module activate todo 15` |
| 3473 | Text-only scoping of `awaiting=review` to the trace's reporting session after the last phase of the trace (leaves never write `review`; no API guard). Root cause: the three-state contract was per-turn, so leaf sessions declared trace-level done when only their phase finished | - | `pages/plan-3473-premature-awaiting.md` | - | - | delivered, text-only, no code change and no deploy. PRD `review` writer scoped in this file; agent config landed on home repo main `df5f22c` (unpushed): `AGENTS.md` 三态工作契约 scopes done/blocked to the reporting session, bars leaves from `review`, limits `external` to real external waits; `dev/SKILL.md` step 12 carries the three literal awaiting commands; `impl`/`review` SKILL.md carry the prohibition. All plan verification greps re-run by the coordinator and passing. Open: behavioural check on the next dev trace (`y todo list --awaiting review` must not list a todo before the coordinator's RELEASE); revisit an API guard only if premature writes recur |
| 3484 | Opt-in `resume_work` dispatch (`y chat --resume-work`) clears stale `awaiting=review` atomically on existing-chat accept and fresh-chat insert; default behavior unchanged; explicit `--awaiting none` remains mandatory pending rollout | - | `pages/plan-3484-awaiting-reset.md` | - | `pages/review-3484-awaiting-reset.md` | deployed `d7f9ce381828a9e51c7366f906a680ca408a0192` on baseline `b2564051c31a2a2dd0227ca5e2507908e429ab30`; user-authorized publication of todo 3484 only, Actions run `34649539981` succeeded. 45 isolated tests independently passed, no blocking findings; installed CLI help and production rejection-path smoke passed. S8 workflow active locally: `pages/hr-3484-awaiting-reset-s8.md`; explicit awaiting-none remains mandatory on every real reopen, with resume-work required for reopened-work dispatches. Impl: `pages/impl-3484-awaiting-reset.md`. Final evidence: `pages/delivery-3484-awaiting-reset.md`. Worktree removed, release register closed; ready for user verification. Tests and this pre-existing untracked PRD remain local-only; home config edits uncommitted/unpushed. |
| 3495 | One owner Telegram DM when a todo newly enters `question` or `review`, deduplicated by reason transition; pointer-only / progress-only / clear stay silent | - | `pages/plan-3495-awaiting-telegram-notice.md` | - | `pages/review-3495-awaiting-telegram-notice.md` | shipped in two rounds. Iteration 1 `87de0af` to main/production (deploy run 34650644904, success); iteration 2 `9573887` (deploy run 34651796247, success) trimmed the message to its essential lines after the owner received a real notice and asked for the finish hint and the trace link to be dropped. Final shape: `review` is header plus todo name, `question` additionally keeps its answer-chat pointer because the chat id is not derivable from the todo id. The `template.yaml` API-function `Y_AGENT_WEB_URL` assignment is retained but is now unused by the API (the CLI reads that variable from its own environment); removing it is optional cleanup, reported not done. Review approved round 1, no blocking findings. Iteration 2 (user trim of the v1 DM): drop the review finish hint and the `/trace/<id>` link; keep the question `awaiting_chat` pointer. `Y_AGENT_WEB_URL` SAM/AGENTS wiring stays because `y login` still reads it. |
| 3506 | `awaiting` is a todo **status** (`pending → active ↔ awaiting → completed`) meaning "needs human intervention"; `y todo await <id> [--chat]` / `y todo resume <id>` + `POST /api/todo/await|resume` are the two transitions, inbox is `status=awaiting`, reason enum, `external` and all `--awaiting*` / `--resume-work` write flags removed, optional navigation-only `awaiting_chat` kept, human message in a bound trace chat auto-resumes, watchdog/death claim faults active→awaiting through one locked `claim_fault`, dev_release parks replaced by pending-waiter evidence, todo module UI and host projections on the status model, cyan awaiting hue on both sides | - | `pages/plan-3506.md` | - | `pages/review-3506-awaiting-status.md` (rounds 1-9, all slices approved) | host candidate `79d5f79` (5 commits on baseline `74279e9`) and module candidate `931770e` (2 commits on `c3d13af`, todo v17) frozen in worktrees; cutover SQL `migration/3506_todo_awaiting_status.sql` + runbook `pages/migration-3506-todo-awaiting-status.md` (migrate before deploy, maintainer-run); agent-config draft `pages/hr-3506-awaiting-status-config.md` applied only after cutover; awaiting publication authorization |
