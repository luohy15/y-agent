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
alongside pending, active, completed and deleted. Typical work still follows
`pending → active ↔ awaiting → completed`, but every explicit source-to-target
pair among the five statuses is legal, including completed/deleted to
awaiting as one atomic reopen-to-inbox write. Review, question and stalled are
explanations in the result / question / error record, not three persistent
machine states. Status says who has the next action; progress, chat and note
say what that action is.

The unit of the inbox is the trace, which is the todo (trace id equals todo
id). One task may spread across many chats, most of them anonymous children;
Roy handles tasks, not chats. So the inbox is not a new noun and not a new
table. It is the existing todo list filtered on `status=awaiting`.

Use `y todo status <id> <status> [--chat <chat_id>]` as the single public
write. Target `awaiting` with optional `--chat` parks the todo in the inbox;
target `active` continues work. Keep one optional navigation pointer, the
existing `awaiting_chat` column, valid only while status is awaiting. It is
not a second state, reason, ownership claim, or prerequisite for leaving
awaiting. Dedicated `y todo await` / `y todo resume` commands and
`POST /api/todo/await|resume` are retired.

Drop the reason enum and the `external` machine-wait plus its deadline field.
Machine waits remain `active`, not in the human inbox. Existing durable
machine evidence, rather than a todo flag, tells the watchdog that silence is
expected. Untracked tmux-only waits lose the old grace exemption; that
limitation is explicit below.

Any accepted human message in a bound non-root trace chat auto-resumes
awaiting to active. A callback, server notice, plain dispatch or process
start can occur while human intervention remains outstanding; only
human-message provenance or an explicit `status=active` write moves awaiting
to active. Automatic resume is eligibility-gated: it never activates pending
or closed work just because explicit transitions are unrestricted. Setting
status to active changes status, not execution: no implicit chat, dispatch,
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
   share that one status, so that I have one inbox and one `status=active`
   continuation instead of three machine reasons.
3. As Roy, I want an optional chat pointer on an awaiting todo, so that I can
   jump straight to the conversation that needs my answer, without making
   that pointer a second state or a prerequisite for leaving awaiting.
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
9. As Roy, I want an explicit `y todo status <id> active` to do the same
   transition without dispatching work, so that I can continue in the
   reporting session or dispatch a later phase independently.
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
30. As Roy, I want a trace that already has a chat, and that has no running
    process record, no chat marked running, and no pending publication-queue
    receipt, to be moved from active to awaiting at the next five-minute scan,
    so that a silent death or a session that stopped without declaring
    anything is caught without an extra idle wait.
31. As Roy, I want the stall message to name the trace, the last session,
    its exit status, and its error text, so that I can decide the next action
    from the message alone.
32. As Roy, I want an already-awaiting trace never to be re-alerted, so
    that a broken trace costs me one message, not one every five minutes.
33. As Roy, I want a trace that is already awaiting to be left alone by the
    watchdog, so that legitimate waits never trigger a stall.
34. As a session that registered a durable wakeup instead of a tmux sleep
    timer (todo 3655), I want a pending wakeup on my trace to suppress the
    watchdog until its due time plus grace, so that a scheduled server-side
    timer is treated as real evidence the same way a publication-queue
    receipt already is, and I want that suppression to end on its own once
    the wakeup delivers or goes stale, so that a wakeup that never fires is
    still caught.
35. As Roy, I want an active todo older than twenty-four hours with zero
    chats to enter the inbox once as awaiting, so that a todo whose dispatch
    never happened is not invisible to a trace-level check.
36. As Roy, I want the watchdog to never write progress on a session's
    behalf or re-run any work, so that the only thing it can ever do is make
    a fault visible by moving active to awaiting.
37. As Roy, I want a session that ends a turn without declaring done or
    blocked to be caught by the watchdog exactly like a death, so that the
    forbidden third ending is detectable rather than merely prohibited.

### Contract alignment

38. As a reporting session, I want the three-state contract in the agent
    configuration to name the exact command for the two legal trace-level
    endings (`y todo status <id> awaiting` with optional `--chat`), so that
    "put the todo in the inbox" is executable and not a paraphrase.
39. As Roy, I want the existing chat attention flag left untouched and
    unused by this feature, so that no removal migration or contract bump is
    spent on dead code here.
40. As a leaf session, I never declare the whole trace awaiting for
    verification; my legal turn ending is the callback, so that a finished
    phase does not put the whole trace in the inbox.
41. As the reporting session, I want to write `status=awaiting` with a
    pointer to my own chat when the trace ends on a decision only Roy can
    make, so that a genuine block is not labelled as verification in the
    progress/note even though the machine status is the same.
42. As Roy, I want no API guard on which session may write awaiting for
    now, so that the correction stays in contract text until premature writes
    are shown to recur.
43. As Roy, I want to be notified once when a todo newly enters awaiting,
    so that a genuine inbox entry reaches me without polling and without a
    second message for progress-only edits or pointer-only changes.

## Implementation Decisions

### Schema

`status` is the write target. Valid values are `pending`, `active`,
`awaiting`, `completed`, `deleted`. Typical work still follows
`pending → active ↔ awaiting → completed`, with completion always performed
by Roy (or explicit completion authority), but every explicit pair among the
five statuses is legal. Completed/deleted to awaiting is one atomic
reopen-to-inbox write, not two requests. Automatic human resume and fault
claims stay eligibility-gated: a human message or watchdog/death claim never
activates or reopens work that is not currently awaiting (human) or active
(fault). There is no previous-status column; leaving awaiting always goes to
the requested target.

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
y todo status <todo_id> <pending|active|awaiting|completed|deleted> [--chat <same-owner-same-trace-chat>] [--note "<sentence>"]
y todo list --status awaiting
```

| Surface | Meaning |
|---|---|
| `status ID awaiting [--chat CHAT] [--note TEXT]` | Move any current status to awaiting (including completed/deleted as one atomic reopen-to-inbox write), or replace/clear the optional pointer on an already-awaiting todo. `--note` is the optional one-sentence DM context, valid only with awaiting, and only on entry into awaiting. A nonempty note on an already-awaiting row is rejected with no pointer or history mutation and no new DM (the error says no new notice was sent). Pointer-only already-awaiting writes without `--note` stay idempotent. |
| `status ID active` | Move any current status to active and clear the pointer; identical resulting state is a no-op. |
| `POST /api/todo/status` | Body: public `todo_id`, enum `status`, optional public `chat_id`, optional `notice`; same transition as CLI. Keep the existing public todo response shape (no `changed` field). |
| Generic update and bulk | Accept awaiting and reuse the same transition helper; they are not a second state writer. Bulk does not take `chat_id`. |
| Retired | `y todo await` / `y todo resume` and `POST /api/todo/await` / `POST /api/todo/resume` are gone. Stale calls fail without mutation (CLI unknown command; HTTP 404/405). No thin aliases. |

- Require an explicit todo ID; no implicit environment fallback. Status
  writes take no reason or deadline. `--chat` / `chat_id` and `--note` /
  `notice` are valid only for target awaiting; a supplied non-null chat or
  notice with any other target is rejected before mutation (CLI before the
  request). API null/omitted chat or notice on other targets is harmless.
- Omitted or null chat on target awaiting clears an old pointer, including
  when already awaiting. Target awaiting plus a chat sets or replaces the
  pointer. Identical resulting state is a no-op. UI same-status
  re-select / re-drop remains no-write to preserve an existing pointer.
  `--note` / `notice` is entry-only: it is folded into history and sent as
  the DM second line only when status newly becomes awaiting. An already-
  awaiting row that also carries a nonempty notice is rejected inside the
  locked transition before any pointer or history write, so the writer
  cannot lose a sentence against a stale fault DM. The write does not
  auto-resume to active and does not resend. An explicit empty or
  whitespace-only note is rejected the same way as an over-long note.
- Automatic human resume still requires current `status=awaiting`; it must
  not silently revive closed work or activate an unstarted task. Fault
  claims still require current `status=active` plus a matching timestamp.
  Explicit `status=active` / `status=awaiting` may reopen closed work.
- Supplied chat must exist for the owner and have this persisted trace ID.
  No root-manager pointer inferred from dispatch metadata. Missing pointer
  still leaves todo-to-trace navigation available.
- Changing status away from awaiting clears the pointer. Metadata-only
  edits do not change status or erase a pointer. A repeated generic
  `status=awaiting` write on an already-awaiting todo therefore clears an
  existing pointer; UI writers must not issue a no-op status write on
  re-drop / re-select.
- Keep activate/deactivate/reopen/finish/delete as ordinary status
  conveniences, not additional transition authorities. `activate` /
  `reopen` remain `status=active`. The canonical agent wording is
  `y todo status`.
- Status writes preserve pin, priority, progress and tags except for the
  existing unpin-on-pending/completed/deleted side effect. They do not
  populate `completed_at` except when the target is completed; leaving
  completed clears it. The generic status side-effect code must not
  auto-unpin on active/awaiting transitions merely because status changed.
- `/status` returns the public todo. CLI reports the returned current
  status neutrally (`Todo ...: active/awaiting`) and shows the pointer when
  present; it does not claim a mutation on a no-op. Errors apply no
  partial changes. The API remains owner-scoped; no public integer IDs.
- `todo update --awaiting/--awaiting-chat/--awaiting-until`, `chat
  --resume-work`, list `--awaiting`, API awaiting filters, UI `awaiting:`
  query vocabulary and dispatch resume plumbing remain removed. Old request
  keys fail clearly with no mutation (`awaiting filter is removed; use
  status=awaiting`, `resume_work is removed; use y todo status <id> active /
  POST /api/todo/status`). No permanent aliases or automatic interpretation
  of old reason values.

### Writers and clearing

- **Every todo mutation is a transaction-local field patch under an
  owner-scoped row lock**, with the history entry appended to the current
  row. Creation is the only remaining whole-row save. Status, pin, bulk and
  generic updates all go through the same primitive, and a combined request
  is validated and applied in one transaction: a rejected request applies
  nothing. Preserve todo-before-chat lock order; no detached DTO can restore
  an older status.
- **Sessions write awaiting through `y todo status <id> awaiting [--chat]`
  / `POST /api/todo/status`** (or generic `status=awaiting`). The API does
  not distinguish a reporting session from a leaf: any session on the trace
  may still write awaiting. Contract text, not the API, restricts
  verification-await to the reporting session after the last phase. A leaf
  may write awaiting with its own pointer only for a decision neither it
  nor its parent can resolve.
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
  chat write but does not call `resume_locked`. `resume_work` is rejected
  before any delivery, enqueue, or todo mutation.
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
  can be moved to awaiting from the menu or kanban as one `/status`
  write; that is an explicit reopen-to-inbox, not a disabled option.
- **Awaiting is listed first in the module's status orders**, so the inbox is
  the first thing read on a row of statuses: the sidebar status shortcuts and
  the table filter row are `awaiting, pending, active, completed, all`
  (module v19), and the right-click status options are
  `awaiting, pending, active, completed, deleted` (module v20). The relative
  order of the other statuses is unchanged. This is a module reading-order
  choice, not a contract the slices must share: the host's own
  `TraceTodoDetail` status select deliberately stays in lifecycle order
  (`pending, active, awaiting, completed, deleted`).
- Every changed status pair from the module, including awaiting-to-active
  and closed-to-awaiting, routes to `POST /api/todo/status` with the target
  enum and no `chat_id`. Same-status re-select / re-drop still sends no
  request. The host generic update and bulk reuse the same transition.
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

### Registered wakeup indicator

An active todo whose trace has an outstanding registered chat wakeup
(`pending` or `accepted`, same owner) is still `active`. It is not awaiting,
and it is not a new status. Readers that list active todos also show the
nearest outstanding receipt so a machine wait is not indistinguishable from
work that is actually running.

The read is `next_wakeup_at_unix` (milliseconds), the minimum `due_at_unix`
among those receipts. Cancelled and delivered receipts do not count. No
receipt, and every status other than active, is null. The field is derived
at read time on the authenticated todo list, todo detail, and trace todo
projection. It is not stored, not writable, and not copied into an update
payload. Public trace shares omit it. The value does not say the trace is
only waiting: a running chat does not hide the receipt, and this read does
not apply the watchdog grace cutoff.

Wording, accepted 2026-09-30, is `Wakeup scheduled · <local date time>` while
the receipt is not yet due, and `Wakeup overdue · <local date time>` once
`due_at_unix` is before now. Exact equality with now stays scheduled. The
web uses browser local time. The CLI uses `Y_AGENT_TIMEZONE` (else the
system zone), not the todo due-date column. Surfaces in this delivery: the
todo module sidebar, table, and kanban; host trace detail; `y todo list` and
`y todo get`. Not the public share, tag-result previews, or `y todo dashboard`.
The indicator is informational. Status stays active. The watchdog is unchanged.

### Release slot waiting

An active todo whose trace has a same-owner pending publication waiter
(`dev_release_waiter.status = pending`) is still `active`. It is not awaiting,
and it is not a new status. Readers that list active todos also show
`Waiting for release slot`, so a queued publication is not indistinguishable
from work that is actually running.

The read is `has_pending_release_waiter`, a boolean derived at read time. It
is true only when status is active and at least one same-owner receipt for
that trace id is `pending`. Granted, cancelled and rejected receipts do not
qualify. A pending receipt on two projects is still one boolean. A trace id
that appears only in the receipt's `todo_ids` list does not match. No receipt,
and every status other than active, is false. The field is not stored, not
writable, and `Todo.from_dict` ignores a client copy of it. Public trace
shares omit it. A running chat does not hide it. The value names one
outstanding dependency: it does not say the trace is only waiting, and it is
not publication authorization.

Surfaces: the authenticated todo list, todo detail, and authenticated trace
todo projection; host trace detail; `y todo list` (Release column) and
`y todo get` (Release line); the todo module sidebar, table, and kanban.
Wakeup and release-slot lines show independently when both exist. There is no
project, queue position, holder, count, link, filter, or action. The indicator
updates on the next existing refetch or manual refresh. There is no migration,
no polling, and no worker change. Status stays active. The watchdog is unchanged.

### Agent notice and fault-notice wording

Agent notice is compact: a fixed one-line heading plus optional bounded
context from the triggering event. The heading is literal lowercase
`【progress】`, then the todo id and name separated by one space. There is still
no literal `todo`, invented review/question/stalled label, "needs you", or
reply instruction. Missing context is valid: the notice is just the one-line
heading.

```text
【progress】<id> <name>
[<one-line context>]
```

The optional second line is evidence, not a reason enum. It is supplied by the
writer (`y todo status <id> awaiting --note "<sentence>"` /
`POST /api/todo/status` `notice`) or by a watchdog/death claim's
structural sentence plus optional error tail. The renderer
(`awaiting_notice_text`) still just prints `extra` when present; it does
not invent urgency, completion, or a decision.

Writer-supplied text is never silently altered. Validation runs before
any mutation and raises (API 400, clean CLI `Error:` line) when the
whitespace-collapsed summary exceeds 200 characters, is empty, or
matches a credential shape (`sk-`, `ghp_`, `gho_`, `github_pat_`,
`AKIA`, `xoxb-`, `Bearer `, `Authorization:`, `://user:pass@`, and
unbroken 40+ character mixed tokens that contain both a letter and a
digit, excluding pure hex so git SHAs and content digests stay allowed).
A nonempty `--note` on an already-awaiting row is also rejected inside
the locked transition, before pointer or history mutation, because a
notice is sent only on entry; the error says no new notice was sent.
Truncating would drop the ask; silent dropping would hide the loss.
Machine-fed fault text uses conservative omission instead
(`notice_excerpt`): a matching tail is dropped and the structural
sentence survives, because a watchdog or death claim cannot retry. The
accepted summary is folded into the same history entry as the status
change, labelled `notice:` (fault claims keep `fault:`).

**No awaiting notice carries a reply instruction.** The notice names the
todo; it never tells Roy where to type the answer, and it makes no
distinction between a human-declared await and a fault claim. Shipped in
`awaiting_notice_text`: the one-line `【progress】<id> <bounded name>`
heading, then `extra` when present, and nothing else. The chat pointer is not
rendered by any writer.

**The `awaiting_chat` pointer and its consumers are retained.** What was
removed is a rendered instruction, not a column and not a navigation path.
`y todo status <id> awaiting --chat` still stores the pointer and echoes it, `y todo get`
still prints `Reply in:` when it is set, `y todo list` still carries its
pointer column, and the host trace todo detail still renders it as a
chat-navigation control while the viewer is authenticated and
`status === "awaiting"` (see Schema and Reading above). Only the notice path
stopped reading it.

This wording changed twice and the reasons are kept as history, because the
fault-notice argument still explains the shape even though it is no longer
expressed as a branch:

1. Todo 3495 iteration 2 trimmed the DM to its essential lines but kept an
   `Answer in chat <chat_id>: reply here with "/<chat_id> <your answer>"`
   line on question-style awaits, on the grounds that the chat id is not
   derivable from the todo id.
2. Todo 3506 S2 (`6ef2766`) scoped that line out of fault notices only
   (`if todo.awaiting_chat and not extra`). A watchdog idle/backstop claim or
   an undeliverable death stores the newest-chat id as `awaiting_chat`, that
   chat is often a dead child, and replying there would auto-resume the todo
   and restart it. A fault notice is inspection context (last chat, exit,
   bounded error text), not a place to type the next instruction.
3. Todo 3506 follow-up (`93da425`) deleted the line outright for every
   awaiting notice, after Roy read a real human-declared notice and asked for
   it to go. This is a user-directed override of step 1's visible-instruction
   decision; step 2's reasoning is unaffected and now simply has nothing to
   suppress. Record: `pages/impl-3506-awaiting-notice-trim.md`.
4. Todo 3523 adds optional writer-supplied or sanitized fault evidence.
   Deriving it from the newest progress write was rejected: truncation drops
   the ask, the newest write is often a child phase note, and progress is not
   authored for this DM.
5. Todo 3645 iteration 1 replaces the first heading line `Todo <id> needs you` with
   `【progress】todo <id>`. The name remains on the next line, and entry-only /
   pointer / trigger / dedup semantics are unchanged. `【progress】` is a
   literal label, not the todo's progress field.
6. Todo 3645 iteration 2 combines the label, id, and name as
   `【progress】<id> <name>`. The literal `todo` and the newline between id and
   name are removed; optional context follows on the second line. All other
   notice semantics remain unchanged.

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
- **Classification is a pure function** over (live, chat count, created
  time, now) returning idle, backstop, or nothing. It no longer reads a
  reason field, `awaiting_until`, or last activity. Each suppressor stands
  alone. A trace that already has chats is idle as soon as live evidence is
  absent; there is no extra idle duration. Zero-chat todos fall only under
  the 24-hour backstop. The pass scans `status == "active"` only. The
  schedule itself stays every five minutes, so a finished-but-undeclared
  trace is claimed on the next tick.
- **Evidence.** The pass first takes a fully paginated process snapshot
  keyed by owner (live by owner plus trace id, and by owner plus chat id
  mapped back to the chat's persisted trace). A snapshot failure aborts the
  pass before any SQL read or write, because a partial snapshot is unknown,
  not empty. Active todos are read across all owners in keyset batches with
  one grouped chat aggregate per batch (count, running count). Chat recency
  is not an input. The under-lock recheck still orders chats by
  `updated_at_unix` descending so the notice pointer and outcome come from
  the newest chat.
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
- **Registered scheduled wakeup is the durable evidence for a pure time
  wait (todo 3655).** A session with a pure time wait registers a
  `chat_wakeup` row (`y chat --chat-id <id> -m "..." --at ...`) instead of a
  tmux sleep timer. A same-owner trace's `chat_wakeup` with status `pending`
  or `accepted` and `now < due_at + grace` suppresses idle fault
  classification the same way a pending `dev_release_waiter` does, including
  under-lock recheck (`has_pending_wakeup`, folded into the same batch pass
  as `pending_wakeup_traces`). Its own scheduled delivery pass
  (`deliver_chat_wakeups`, every minute) appends the message as an ordinary
  dispatch and enqueues the worker; that append leaves the chat SQL-running,
  which is itself evidence, and once the run finishes a delivered wakeup no
  longer suppresses. A wakeup stuck
  undelivered past due_at plus grace stops suppressing, so a stall in the
  delivery path itself is still caught, not hidden behind an unbounded wait.
  The maximum registrable horizon is 7 days.
- **Untracked tmux-only waits lose the old grace exemption for anything
  that is not a pure time wait covered by a registered wakeup.** A detached
  tmux job without a live existing process record, durable queue receipt, or
  registered wakeup can be classified as idle even if its eventual callback
  is configured. Progress text is not machine evidence. Do not promise that
  merely naming tmux or setting a callback prevents this. Prefer
  already-monitored execution for long tasks. An awaiting notice in this
  case requests inspection, not proof the job died. Do not use fake running
  flags, periodic progress heartbeats, pending status or new timeout flags
  to hide it. If maintaining arbitrary tmux grace for a real long-running
  job (not a pure time wait) is mandatory, that requires a separately
  approved real process-liveness integration, not silently
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
  for orphans or tail exhaustion. Crash detection stays bounded by this
  sweep: a crashed run leaves its chat SQL-running, which suppresses the
  evidence-only classifier until the 15-minute orphan grace clears it. This
  change only speeds up cleanly finished runs.

### Contract text and trace-terminal ownership

`done` and `blocked` are trace-level states. Only the trace's reporting
session declares them: a topic-bound coordinator, or any session whose
dispatch prefix says it came from the root manager topic. That session
writes `y todo status <id> awaiting [--chat <reporting_chat>]` after the last
phase of the trace (implementation, review, commit, and deploy when the todo
requires it), having first recorded the actual result or question in
progress/note. It writes `y todo status <id> active` when continuing directly
after input received elsewhere, then independently dispatches if a later
phase is needed. Dispatch and status=active are separate transactions by
design: dispatch failure leaves active because the caller took
responsibility.

A leaf never declares the whole trace ready. Its legal turn ending is the
callback, which wakes the parent and keeps the trace live. Stopping without
a callback is the forbidden third ending. A leaf may write `status=awaiting`
with its own pointer (or hand the question to the parent via callback) only
for a decision that neither it nor the parent can make.

There is no API guard: any session on the trace can still write awaiting.
Ownership is contract text, owned by the `hr` role. A server-side rejection
of awaiting from topic-less chats is out of scope unless premature writes
recur.

The watchdog scans only `active` rows, so a premature leaf awaiting write
would hide later silence, which is why leaves must not write it for
verification.
This is a contract decision, not a hidden worker auto-clear.

Agent configuration (`AGENTS.md`, `dev` / `impl` / `review` SKILL.md, tmux
guidance) still currently describes `y todo await` / `y todo resume` as
applied from `pages/hr-3506-awaiting-status-config.md` (home-repo commit
`f71d5fb`, `dev` skill 9.33 → 9.34). Todo 3514 retires those commands in
host/CLI/module first; the live-config sweep to `y todo status <id>
awaiting|active` is a separately sequenced step (plan S4) and must not
activate until the installed CLI and deployed API match. The old `--awaiting
review|none` / `--resume-work` surface remains gone.

### Atomicity and notices

- One owner-scoped locked transition function owns status, pointer cleanup,
  history, completed_at and pin semantics for explicit status writes,
  ordinary update/bulk APIs, human acceptance and fault claims.
- Explicit `status=active` and subsequent dispatch are separate
  transactions. It self-recovers or records the final inability and writes
  awaiting again; a crashed caller is covered by the watchdog only when
  enabled. No rollback to an old wait after intervening work.
- Identical operations are idempotent, not generation-scoped requests: a
  later explicit `status=active` can consume a newly declared awaiting row.
  Do not blindly replay an ambiguous request after intervening work. No
  generation column/outbox framework is proposed for todo lifecycle.

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
- **Awaiting notice is entry-only.** A later `status=awaiting --note`
  against an already-awaiting row is rejected rather than replacing the
  original DM. The realistic path after a watchdog claim is resume to
  active, then await again with `--note`.
- **Credential-shape filtering is conservative, not a secret scanner.**
  Unbroken 40+ character mixed tokens that contain both a letter and a
  digit (including path and URL fragments with `/`) can omit a useful
  machine-fed error tail or reject an otherwise honest writer sentence.
  Slash-containing tokens are not exempted, because credentials can
  contain slashes. The structural fault sentence still survives.

## Testing Decisions

Tests are local-only and untracked per repo convention.

- **Awaiting status transitions** are table-driven over the service layer:
  all 25 explicit pairs; completed/deleted to awaiting as one atomic
  reopen-to-inbox write; pointer replace vs omitted-chat clear vs identical
  no-op; invalid owner/trace pointer rejected with no mutation; `--chat` /
  `chat_id` rejected for non-awaiting targets before mutation; generic
  `status=awaiting` without a pointer; metadata-only edits; pin/completion
  semantics; bulk completed/deleted-to-awaiting; rejected legacy `awaiting`
  / `awaiting_until` / `resume_work` requests. Automatic resume still
  refuses pending/closed work.
- **List filtering** at the service and API level: `status=awaiting` is the
  inbox; `status=active` excludes awaiting; open-work queries include
  pending/active/awaiting; unknown awaiting filter keys 400.
- **Human auto-resume** on an accepted human message in a non-root persisted
  trace chat, including a different same-trace chat than the pointer, atomic
  with the append; rejected/rolled-back append preserves awaiting; dispatch,
  callback, run-entry and root-manager messages never resume; no
  cross-owner resume; completed/deleted human replies do not reopen.
- **Fault claims** enter awaiting with fault text in history plus one
  notice; abstain on `recheck=None`; skip recheck on stale `updated_at_unix`
  or non-active, including completed/deleted; never repeat and never reopen
  closed work. Pending waiter suppresses; granted / cancelled / rejected
  receipts do not.
- **Awaiting notice context** is a pure renderer plus validation suite:
  representative one- and two-line outputs byte-for-byte (ready / publication /
  blocked / idle fault / credential-omitted fault / missing `--note`);
  200/201 length boundary; each credential shape rejected and hex SHA /
  digest accepted; whitespace collapse; explicit empty note rejected;
  `notice` rejected for non-awaiting targets with no mutation; nonempty
  `notice` on an already-awaiting row rejected inside the locked
  transition with no pointer or history mutation; pointer-only already-
  awaiting writes without notice remain no-op / replace as before;
  machine-fed `notice_excerpt` drops a credential tail and keeps the
  structural sentence.
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
  todo age) tested as a table, with a row per suppressor proving it alone
  prevents a stall. A trace with chats and no live evidence is idle on the
  same scan, including one whose chats were just updated. Two consecutive
  passes produce one push. The backstop row fires once. A mutation test
  asserts the pass never writes progress or a chat.
- **Owner scoping** follows the chat-core precedent: two todos sharing a
  public id under different users, asserting every awaiting read and write
  touches only the owner's row.
- **Web / module** unit tests cover status shortcuts, kanban, enabled
  closed-to-awaiting options, same-status no-write, and `/status`-only
  routing against fixture rows; no browser-driven runtime check by default.
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
  sweep continues, and a swept chat (no longer SQL-running, no other live
  evidence) is claimed on the next scan with no extra idle wait. Crash
  detection itself stays bounded by the 15-minute orphan grace above.
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
  paths.** Covered by the watchdog once the orphan sweep clears the
  SQL-running row, not by targeted messages.
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
- **Watchdog enablement and automatic todo finish.** The
  `CheckTraceLivenessSchedule` rule is still deployed with `Enabled: false`;
  flipping it on is a separately authorized rollout step and no live AWS state
  was checked here. Production mutation left this list once the cutover SQL was
  maintainer-run after authorization and the S4 agent-config activation
  happened; both are recorded under Delivery Records.
- **Non-blocking review nits** listed in the review notes under Delivery
  Records and deliberately not expanded into this delivery (including stale
  `actionColor` keys and `awaiting-menu.ts` naming).
