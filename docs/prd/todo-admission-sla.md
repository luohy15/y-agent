---
title: Todo Admission Control and Completion SLA
type: prd
project: y-agent
feature: todo-admission-sla
status: active
---

# Todo Admission Control and Completion SLA

## Problem Statement

The todo list is Roy's work queue, but an item can enter it with no promised
completion time and nothing in the system ever asks for one. "Pending" therefore
mixes a two-minute fix, a three-week project and a someday idea. Pinning exists,
but it only sorts a row to the top, so it cannot distinguish a long-term goal
from unfinished near-term work.

The result is a queue that grows faster than it clears. It cannot answer the
question Roy actually plans against: what am I finishing today, this week and
this month? A backlog can accumulate without ever forcing a decision, and the
list stops being a reliable picture of committed work.

`due_date` does not solve this. It is optional, entered by hand, not derived
from priority, has no decision point when missed, and has no review surface.
The existing creation authorization rule also does not bound a legitimately
created todo: it says who may add an item, not how long that item may sit.

The Todo full view groups by status only. It can show that something is pending,
but not whether the promise attached to it is today, next week or already
broken.

## Solution

Every non-pinned todo carries a completion promise, the SLA, from the moment it
is created. The promise defaults from priority: high in 3 days, medium in 7
days, low in 14 days, and a missing or `none` priority also uses 7 days. A
caller may override it with a duration or an explicit date, but the non-pinned
maximum is 14 days. Anything longer must be an explicit long-term goal, which
means pinning it. The server applies the default, so every client gets the same
rule.

Pin now means "long-term goal". A pinned todo has no SLA, never becomes
overdue, and sits outside the load buckets. Pinning survives a return to
`pending`; completing or deleting still clears it. Unpinning requires a fresh
promise from that day.

The clock starts at creation and keeps running through `pending`, `active` and
`awaiting`. Completed and deleted work stops it. Editing priority does not move
the deadline. Only an explicit renewal resets it from the renewal moment.
Renewals are recorded in history so repeated extension is visible.

Overdue is derived, not a status: an open, non-pinned todo whose promised date
is before today is overdue. The system never auto-completes, auto-deletes,
auto-pins or auto-awaits an overdue item. One deterministic daily Telegram
digest lists overdue and due-today items, and `y todo audit` provides the same
data on demand. Each overdue item needs a renew or archive decision from Roy;
archive uses the existing soft delete.

The Todo full view gains a Load tab, with tabs ordered kanban, load, table.
With no stored view preference, kanban is the default; a stored preference
still wins. Load groups committed work into Overdue, Today, This Week, This Month,
Later and Long-term (pinned), with a count on each group header. The buckets use
the promised date only. Completed and deleted items are excluded, while pending,
active and awaiting items share the buckets, with their existing waiting and
running indicators. Load inherits the approved full-view design language
established by todo 4280, and opening a row keeps the existing detail and trace
behavior.

Rollout is deliberate. Existing open non-pinned todos are backfilled from the
rollout date plus their priority default, not from their creation date, so the
backfill does not create an instant wave of breaches. A one-time audit then
lists every existing open item for pin, renew or archive with per-item
confirmation. No existing todo is deleted or reclassified automatically.

## User Stories

### Admission and defaults

1. As the user, I want every non-pinned todo to carry a promised completion date
   from the moment it is created, so no item can exist without a commitment.
2. As the user, I want the promise defaulted from priority (high 3 days, medium
   7 days, low 14 days), so ordinary creation asks me no extra question.
3. As the user, I want a todo created without a priority, or with priority
   `none`, to use the 7-day default, so omission is not an escape from the
   promise.
4. As an agent creating a todo on the user's explicit request, I want the server
   to set the default SLA, so I cannot forget or bypass it.
5. As the user, I want to override the default with a duration or an explicit
   date, so a known deadline is recorded as the promise.
6. As the user, I want a requested SLA longer than 14 days rejected with a clear
   message, so long-horizon work becomes a deliberate long-term goal instead of
   an accidental pending item.
7. As the user, I want to pin a todo at creation or afterwards, so a long-term
   goal is exempt from the SLA.
8. As the user, I want pinned items to show no SLA and to live outside the load
   buckets, so they do not distort near-term load.
9. As the user, I want pinning to survive a later `pending` status, so a
   long-term goal is not quietly pulled back into the SLA system.
10. As the user, I want `completed` and `deleted` to clear the pin
    automatically, so closed work does not stay in the long-term list.
11. As the user, I want unpinning to assign a fresh promise from that day (or an
    explicit `--sla`), so an item cannot leave long-term limbo without a new
    commitment.
12. As an agent, I must not pin a todo to escape its SLA unless the user
    explicitly asks, so pinning stays a user decision.
13. As the user, I want this policy stated in the todo reference that agents
    read, so enforcement is not only schema-level.

### Clock and renewal

14. As the user, I want the clock to start at creation and keep running in
    `pending`, `active` and `awaiting`, so parking an item in an open status
    does not stop the promise.
15. As the user, I want `completed` and `deleted` to stop the clock, so closed
    work is never reported overdue.
16. As the user, I want a priority edit not to move the promised date, so
    changing urgency does not silently rewrite the commitment.
17. As the user, I want a renewal command that resets the promise from the
    renewal moment, so an item that needs more time gets an honest new date.
18. As the user, I want renewal to accept the priority default or an explicit
    duration or date, so it is one small action.
19. As the user, I want renewal events in the todo history, so repeated
    extension is visible in the audit.
20. As the user, I want no hard cap on renewals, so the decision to keep or drop
    an item stays mine.

### Overdue

21. As the user, I want overdue derived from the promised date versus today in
    the deployment timezone, so the system adds no status and no background
    mutation.
22. As the user, I want an overdue item to keep its real status (`pending`,
    `active` or `awaiting`), so the reason it is late stays visible.
23. As the user, I want overdue items excluded from the Today, This Week and
    This Month groups, so the normal load view is not inflated by old breaches.
24. As the user, I want overdue items visible in their own group and in the CLI,
    so they cannot be hidden by the buckets.
25. As the user, I want one daily summary of overdue and due-today items on
    Telegram, so I get a nudge without per-item messages.
26. As the user, I want the daily summary silent when nothing is overdue or due
    today, so it does not become background noise.
27. As the user, I want the summary to include item IDs and names, so I can act
    without opening the web app.
28. As the user, I want each overdue item to require either a renew or an
    archive decision, so it cannot linger indefinitely without a choice.
29. As the user, I want archive to use the existing soft delete, so no new
    lifecycle state is introduced.
30. As the user, I want the system to never auto-complete, auto-delete,
    auto-pin or auto-await an overdue item, so only I change commitments.
31. As the user, I want overdue `awaiting` items included, so work blocked on my
    answer is visible as a breach.
32. As the user, I want an on-demand audit command as well as the daily summary,
    so I can review the whole open set whenever I want.

### Load view

33. As the user, I want a Load tab in the Todo full view, so I can see what I
    intend to finish today, this week and this month.
34. As the user, I want kanban to be the full view's default when no view
    preference is stored, with tabs ordered kanban, load, table, so the status
    board is the first thing I see.
35. As the user, I want my stored kanban, load or table choice to still win, so
    the default does not override an explicit preference.
36. As the user, I want Today to contain items promised for today, so the
    current day's commitment is unambiguous.
37. As the user, I want This Week to contain the rest of the current
    Monday-to-Sunday week, so the weekly load matches my planning week.
38. As the user, I want This Month to contain the rest of the current calendar
    month, so the monthly load matches the calendar.
39. As the user, I want anything promised after this month in a Later group, so
    no open item silently disappears from Load.
40. As the user, I want Overdue and Long-term (pinned) in their own groups, so
    they are visible but separate from the near-term load.
41. As the user, I want each group header to show its count, so I can read the
    load at a glance.
42. As the user, I want `pending`, `active` and `awaiting` items together in the
    buckets, so status does not hide committed work.
43. As the user, I want `awaiting` rows marked as waiting on me and `active`
    rows to keep their running evidence, so I know what needs me.
44. As the user, I want `completed` and `deleted` items excluded, so Load shows
    only open work.
45. As the user, I want buckets keyed by the promised date only, so `due_date`
    cannot double-book an item into another period.
46. As the user, I want `due_date` still displayed where it already is, so
    manual targets remain visible without becoming the promise.
47. As the user, I want Load to use the approved full-view design language, so
    it looks and behaves like the table and kanban tabs.
48. As the user, I want opening a Load row to keep the existing detail and trace
    behavior, so navigation is unchanged.
49. As the user, I want Load to restore on reload and tab switches like the
    other modes, so my place is preserved.
50. As the user, I want empty groups to use the standard empty state, so an
    empty bucket is explicit rather than missing.

### Audit and operations

51. As the user, I want `y todo list --overdue`, so I can filter breaches from
    the CLI.
52. As the user, I want `y todo audit` to report counts by status, priority and
    overdue state, the oldest open items, and the pinned long-term list, so I
    can see the queue's health in one read.
53. As the user, I want audit to be read-only, so reviewing never changes work.
54. As the user, I want set, renew, pin and unpin recorded in history, so the
    audit can explain how an item reached its state.

### Rollout

55. As the user, I want existing open non-pinned todos backfilled from the
    rollout date plus their priority default, so the migration does not create
    an instant mass-overdue wave.
56. As the user, I want a one-time audit listing every existing open item for
    pin, renew or archive, with my confirmation per item, so no existing todo is
    deleted or reclassified automatically.
57. As the user, I want routine-created todos to follow the same rule, so there
    is no exemption path.
58. As the user, I want the data change applied deliberately, so the backfill is
    a reviewed operation and not an automatic migration.

## Implementation Decisions

### Data model

- `todo.sla_due_at` is a nullable ISO date string (`YYYY-MM-DD`) interpreted in
  the deployment timezone. `NULL` means a pinned long-term goal, or a legacy row
  that has not been backfilled.
- The column is additive and hand-applied, following the project migration rule.
  No automatic migration or background writer is introduced.
- `pinned` keeps its existing storage and presentation and gains the long-term
  meaning. The status side effects stop clearing `pinned` on a transition to
  `pending`; they keep clearing it on `completed` and `deleted`.
- Pinning clears `sla_due_at` and records the change in history. Unpinning sets
  `sla_due_at` from that day using the priority default, or the explicit
  `--sla`, and records it.
- The list and detail payloads gain `sla_due_at` and a derived `overdue`
  boolean. `pinned` keeps its current boolean shape.
- History actions record SLA set, renewal, pin and unpin, including the new
  value, so the audit can explain the current state.
- `due_date` keeps its current meaning, storage and display. It is not derived
  from the SLA and does not feed the buckets.

### Defaults and validation

- Defaults: high 3 days, medium 7 days, low 14 days. A missing priority and an
  explicit `none` both use 7 days.
- The non-pinned maximum is 14 days from the reference date. The reference date
  is creation for a new todo, the release date for an unpinned todo, and the
  renewal date for a renewal.
- A longer request is rejected with a validation error that names pinning as the
  explicit alternative. A pinned todo takes no SLA.
- `--sla` accepts a day or week duration (`3d`, `2w`) or an explicit
  `YYYY-MM-DD`; an explicit date must fall within the cap.
- The todo service computes the SLA in the create path. The API accepts an
  optional `sla` and `pinned`; omitted values get the default, so every client
  path is covered.
- Renewal is its own write path and records a history entry. The generic todo
  update does not accept `sla_due_at`, so the only ways to move a promise are
  creation, renewal and pin or unpin.

### Overdue and bucket derivation

- The open set is `pending`, `active` and `awaiting`.
- Overdue means open, not pinned, `sla_due_at` is non-null and earlier than
  today in the deployment timezone.
- The bucket membership is:
  - Overdue: the overdue rule.
  - Today: promised today and not overdue.
  - This Week: promised after today through the last day of the current
    Monday-to-Sunday week.
  - This Month: promised after this week through the last day of the current
    calendar month.
  - Later: promised after the current calendar month.
  - Long-term: pinned, regardless of any stored date.
- Every open non-pinned todo with an SLA appears in exactly one of Overdue,
  Today, This Week, This Month or Later.
- Default ordering inside a group is promised date ascending, then priority
  (high, medium, low, none), then a stable todo-ID tiebreak. This applies until
  the user clicks a sortable column header in that group. Each Load group keeps
  its own selected column and direction, which override the default only within
  that group. Sorting does not change other groups' ordering, group membership
  or group order.
- The list API accepts a derived open-set filter, an overdue filter and a
  promised-date sort. The Load view reads the open set once and derives the
  groups and counts client-side, so the header counts always match the rows.

### CLI

- `y todo add` gains `--sla <duration|date>` and `--pin`. `--pin` skips the SLA.
- `y todo renew <id> [--sla <duration|date>]` resets the promise from now.
- `y todo pin <id>` and `y todo unpin <id>` keep their current names;
  unpinning accepts an optional `--sla`.
- `y todo list` gains `--overdue`, and shows the promised date, the remaining
  or overdue days, or "long-term" for a pinned row.
- A new read-only `y todo audit` reports counts by status, priority and overdue
  state, the oldest open items, and the pinned long-term list. Its `--notify`
  mode is the deterministic daily digest described below.
- `y todo get` shows the promised date, remaining or overdue days, and the
  pinned state.

### Full view

- The view tabs are ordered `kanban`, `load`, `table`. `kanban` is the default
  when no `todoViewMode` preference is stored. A stored `kanban`, `load` or
  `table` choice still wins, preserving explicit preferences.
- Load follows the approved 4280 full view: the same page header, view tabs,
  controls row and section framing. The status segmented filter is hidden in
  Load because the groups are the status dimension; the name search still
  filters. Table and kanban keep both controls.
- Each group is a section with a header that names the group and shows its
  count. Rows reuse the existing row presentation, including status, priority,
  tags, waiting and running indicators, and the pinned marker.
- Load groups reuse the table tab's sortable column headers and header-click
  behavior, but each group has independent sort state. Clicking a header changes
  only that group's selected column and direction; other groups keep their own
  sort selections or default order.
- On mobile, each Load group's table scrolls horizontally so columns remain
  accessible on a narrow screen.
- Load is read-only with respect to status: no drag and drop, no status edit
  from the group. Existing row actions and detail navigation stay available.
- Opening a row uses the existing detail and trace path. Load does not add a
  second selection or navigation model.
- The selected view mode and Load scroll participate in the existing navigation
  preference, so reload and tab switches restore them.
- Empty groups use the standard empty state. No new local style or token is
  introduced for Load.
- The sidebar panel is unchanged.

### Policy and enforcement

- The todo reference text and the always-on summary state: every non-pinned
  todo has an SLA; creation applies the priority default; an SLA longer than 14
  days needs a pin; agents must not pin on their own; an overdue item needs a
  renew or archive decision; the review surfaces are `y todo audit` and
  `y todo list --overdue`.
- The server is the enforcement point. CLI validation and the reference text
  support the rule but cannot replace the server default.
- The existing todo creation authorization rule is unchanged. This feature
  constrains a created todo's lifetime, not who may create it.

### Rollout and backfill

- After the additive column is applied, a reviewed one-time backfill sets
  `sla_due_at = rollout date + priority default` for every open non-pinned row.
  Pinned rows stay `NULL`, and closed rows stay `NULL`.
- The backfill is a deliberate manual data operation, not an automatic
  migration.
- A one-time audit report lists the open backlog for pin, renew or archive.
  Roy confirms per item. No bulk agent classification and no deletion without
  per-item confirmation.
- Shipping the mechanism does not edit the live backlog.

### Daily digest

- The daily digest is a deterministic scheduled step, not an agent chat
  session. It reads the same derived data as `y todo audit --notify` and sends
  one Telegram message listing overdue and due-today items with their IDs and
  names.
- It stays silent when nothing is overdue and nothing is due today.
- It writes no todo status. There are no per-item timers, wakeups or automatic
  resumes.
- The digest and the CLI report cannot disagree because they share one data
  path.

## Testing Decisions

The project's no-unit-test default applies. Verification is targeted and
external-behavior oriented, not a committed test suite.

- Pure date and bucket rules get a small fixed-date check during development:
  each priority default, the 14-day cap, the overdue boundary, the
  Sunday-to-Monday week boundary, the last day of the month, and the Later
  boundary. These run as one-off checks, not as committed tests.
- CLI behavior is checked against a test user: create with each priority, an
  override, an over-cap rejection, a pin bypass, unpin with and without an
  explicit SLA, renew, `list --overdue`, and `audit`.
- API behavior is checked for: an omitted SLA receiving the default on every
  client path, the generic update refusing to move the SLA, and the overdue
  filter agreeing with the CLI.
- UI verification is module typecheck plus build, with static checks for the
  three view modes, the stored-preference precedence and the six groups. No
  browser check unless the user asks.
- Deployed verification: after the host and module are live, create a real
  todo, confirm its default, renew it, and confirm the audit and the digest
  agree.
- Boundary rows to verify: an item promised exactly today, a pinned item with
  no SLA, a completed item with a past date, an awaiting item, and a legacy row
  before the backfill.
- Prior art: the todo module's pure query and navigation helpers and the CLI's
  existing status and time-filter behavior. No local database-connected tests.

## Out of Scope

- **New statuses or awaiting semantics.** `pending`, `active`, `awaiting`,
  `completed` and `deleted` stay as they are, including the inbox and its
  automatic resume rules. Owned by [todo-awaiting-inbox](todo-awaiting-inbox.md).
- **The single-todo detail viewer and its navigation.** Reaching, presenting
  and leaving a todo detail, including reload restoration and the trace
  round trip, stay owned by [todo-detail-view](todo-detail-view.md). This
  feature changes list modes only.
- **Automatic status changes, deletion, pinning or awaiting on breach.** The
  system reports and the user decides.
- **Agent-led backlog classification or bulk cleanup.** The one-time audit
  lists candidates; deletion needs per-item user confirmation.
- **Creation quotas, rate limits, or a mandatory description or next-action
  field.** Admission control here is a completion promise, not a form.
- **Changes to todo creation authorization, tag rules, routine scheduling or
  the module system.** The existing rules stand.
- **Removing or redefining `due_date`.** It remains an independent manual
  target.
- **Per-item reminders before the promise date.** The daily digest and audit
  are the review surfaces.
- **Per-todo timezones.** The deployment timezone is authoritative.
- **Drag and drop or status edits from Load.** Load is a read-only grouping.
- **A broader full-view redesign.** Load uses the 4280-approved language and
  adds no new design system.
- **Public or anonymous exposure of SLA data.** The new fields stay in the
  owner-scoped authenticated surfaces.
- **A background worker that mutates todo rows on a schedule.** The digest
  only reads and reports.
- **Sidebar panel changes.** Only the full view gains Load.
- **Exact digest wording, hour and delivery mechanics beyond one daily
  Telegram message.** The implementation may use the existing routine and CLI
  surface.
