---
title: Email Module
type: prd
project: y-agent
feature: email-module
status: active
---

# Email Module

## Problem Statement

Email is one of the last first-class domains still hard-wired into the host
application. Calendar, Todo, Note, Chat, File, Bot, Tag, Monitor, and Finance
all ship as versioned modules; email's list, reader, and formatting helpers ship
inside the host web bundle. Four costs follow.

- **Email changes cost a full host deploy.** Every tweak to the reader rides the
  host web pipeline instead of a module publish, and there is no per-version
  rollback for the email surface alone.
- **The reader lives in a pseudo-file tab.** Selecting a thread opens the
  reserved `email.md` workspace tab: a path that is not a file, restored from
  persisted tab state, and unlike every migrated domain's `panel` + `detail`
  pair. This is the same shape [todo-detail-view](todo-detail-view.md) retired
  for `trace.md`.
- **The host owns the domain's selection state.** The selected thread id and
  account are host React state, persisted under host storage keys, and threaded
  as props through generic host components that have nothing to do with email.
- **Email's data cannot simply follow Finance.** The host tag projection treats
  `email` as a direct carrier and resolves email titles in process. A
  Finance-style table move would leave the host reading a module's table, which
  the module system forbids, and would degrade tag drill-down to bare ids. The
  ownership boundary has to be decided deliberately rather than copied.

## Solution

An `email` module owning the domain's presentation: the Email panel as its
`panel` surface and the thread reader as its `detail` surface, published and
rolled back independently of the host.

The host keeps what it must keep: the `email` and `email_account` tables, the
`/api/email/*` HTTP surface, the `y email` CLI including Gmail sync and
app-password custody, and the tag carrier and resolver. Email therefore becomes
a **UI module over host-owned domain state**, the shape Calendar and Todo
already use, not a data move.

The migration finishes by retiring the legacy surface: the `email.md` reserved
tab, the host-held thread selection, and the host panel and reader are removed
once the module reaches parity, so exactly one email presentation exists.

## User Stories

### Reading email (behavior parity)

1. As a signed-in user, I want an Email panel in the activity bar, so that I
   reach my synced mail the same way I do today.
2. As a user, I want the panel to list threads newest first with sender,
   subject, one-line snippet, date, and a message-count badge for multi-message
   threads, so that I can scan a mailbox at a glance.
3. As a user, I want the snippet to show my correspondent's own text rather than
   the quoted reply chain, and readable text rather than markup for HTML-only
   mail, so that the list stays legible.
4. As a user, I want to search threads by subject, sender, or body text and have
   the result set replace the list, so that I can find a conversation.
5. As a user with more than one connected account, I want an account filter, so
   that I can read one mailbox at a time.
6. As a user, I want the account filter to clear itself when the account it
   points at is removed, so that I am never stuck on an empty filtered list.
7. As a user, I want to page through older threads with an explicit load-more
   action that appends to the list, so that scrolling back is predictable.
8. As a user, I want a refresh control that re-fetches the current query, so
   that mail synced since I opened the panel appears.
9. As a user, I want the currently open thread highlighted in the list, so that
   I know where I am.
10. As a user, I want to manage connected Gmail accounts (see them, add one with
    its app password, remove one with confirmation that synced mail is kept)
    from the panel, so that account setup does not require the CLI.
11. As a user, I want the reader to show a thread as a conversation: subject
    heading, the first and latest messages expanded, intermediate messages
    collapsed to one-line rows, and runs of collapsed messages bundled behind a
    count bubble that reveals them, so that long threads stay navigable.
12. As a user, I want to expand any collapsed message by clicking it, so that I
    can read the middle of a thread.
13. As a user, I want a message's trailing quoted reply chain hidden behind a
    toggle, so that I read the new text first.
14. As a user, I want HTML mail rendered sanitized, style-isolated, and on a
    light background regardless of app theme, so that mail looks right and
    cannot restyle or script the application.
15. As a user, I want each message's sender name, address, avatar, timestamp,
    and a recipients line with an expandable to/cc detail view, so that I can
    tell who saw what.
16. As a user, I want my own address shown as "me" in the recipients line, so
    that the thread reads the way mail clients read.
17. As a user, I want distinct sign-in, loading, empty, and error states in both
    the panel and the reader, so that "no mail" and "load failed" never look
    alike.
18. As a user, I want the reader to invite me to pick a thread when nothing is
    selected, so that an open reader tab is never blank.
19. As a user whose session expired, I want the surface to fall back to its
    signed-out state instead of erroring, so that I can sign in again and
    continue.
20. As a mobile user, I want the panel and reader to stay usable at small
    widths, so that email works on the phone layout.

### Navigation and state migration

21. As a user, I want opening a thread to open the module's own full view, so
    that email behaves like every other domain's detail surface.
22. As a user, I want the panel to offer an explicit way to open that full view
    without selecting a thread, so that I can go straight to the reader.
23. As a user who already had the legacy email tab open, I want it to disappear
    cleanly on my next load instead of trying to open a file that does not
    exist, so that the migration is invisible.
24. As a user who ordered the Email entry in my activity bar, I want that
    position preserved after the migration, so that my sidebar does not
    reshuffle.
25. As a user, I want my selected thread to survive a reload and a restored
    tab, so that returning to the browser resumes where I left off.
26. As a user, I want a tag drill-down on an email result to open that thread in
    the reader, and to fall back to opening the Email panel when the lookup
    fails, so that tag navigation never dead-ends.
27. As a user, I want selecting a thread in the panel to focus the reader even
    when the reader tab is not mounted yet, so that the first click after a cold
    load is never swallowed.

### Sync, accounts, and privacy

28. As the owner, I want `y email sync-gmail` to keep fanning out over every
    registered account and importing starred threads exactly as it does now, so
    that ingestion is unaffected by the migration.
29. As the owner, I want app passwords to stay in host custody, never rendered
    after entry and never returned to the browsing surface, so that the
    migration does not widen credential exposure.
30. As the owner, I want Gmail access to stay exactly as broad as it is today
    (IMAP app password, starred threads, read-only), so that the migration adds
    no new permission.
31. As the owner, I want `y email list`, `get`, and `account` to keep working
    unchanged, so that agents and scripts that read mail are unaffected.
32. As the owner, I want mail to stay owner-scoped on every read path, so that
    no surface can serve another account's mail.

### Module lifecycle and failure isolation

33. As the maintainer, I want to publish and roll back the email surface as one
    versioned module, so that a bad reader change is one command to undo.
34. As the maintainer, I want a disabled or rolled-back email module to leave
    mail data, sync, and the CLI fully working, so that presentation failure is
    never data loss.
35. As a user, I want a failing email module to be contained by its own error
    boundary, so that the rest of the app keeps working.
36. As the maintainer, I want email tag drill-downs to keep resolving subjects
    after the migration, so that the tag surface does not silently degrade to
    raw ids.

### Retirement

37. As the maintainer, I want the legacy host panel, reader, helpers, selection
    state, and reserved tab deleted once the module reaches parity, so that only
    one email implementation exists.
38. As the maintainer, I want no email rendering or formatting logic duplicated
    between host and module at any point after cutover, so that fixes cannot
    land on the dead copy.

## Implementation Decisions

### Boundary: a UI module over host-owned domain state

The module declares the `ui` part only, with `panel` and `detail` surfaces —
the Calendar and Todo shape, not the Note or Chat shape. Tables, HTTP, and CLI
stay host-owned. Three facts drive this:

- **The host reads email rows in process.** `email` is a direct tag carrier and
  the host registers a batch resolver that hydrates tag results with each
  email's subject or sender. Modules may not be read by the host, so the tables
  must stay host-owned; without the resolver, tag results fall back to bare ids
  (story 36).
- **A module HTTP half would buy nothing.** It would mean new owner-bound
  `email_*` backend capabilities and a backend contract bump purely to re-expose
  the queries the host already serves owner-scoped. The domain has no
  module-specific business logic to relocate.
- **Credential custody should not move into hot-loadable code.** The account
  credential read exists solely for the sync CLI. Keeping the account routes and
  `y email sync-gmail` host-side keeps plaintext app passwords out of a
  per-version published artifact and keeps ingestion working while the module is
  disabled or rolled back (stories 29, 34).

The module UI calls the existing host routes with the SDK's authenticated fetch,
exactly as the Todo and Calendar modules call their host routes.

### Surfaces and the retired tab

The panel becomes the module panel key; the reader becomes the module detail
tab. `email.md` joins the host's retired-tab set so restored tab state is
dropped instead of resolved as a file, and the activity-bar key migration map
gains an `email` → module-panel-key entry so persisted sidebar order survives.
Both mechanisms already exist and were used for the `bot.md`, `calendar.md`,
`todo.md`, and `trace.md` retirements.

### Selection state moves into the module

Selected thread id and account become module-owned persisted state, seeded once
from the legacy host keys `selectedThreadId` / `selectedThreadAccount` so an
in-flight selection survives cutover; the host then removes those keys, the
corresponding React state, and the props threaded through the workspace
components. Panel-to-reader focus uses a module-local retained latch with a
fresh nonce per click (Calendar's pattern), so re-selecting the same thread
re-triggers. Host-to-module focus uses the retained artifact intent channel.

### Host navigation adapter

An email navigation helper on the host mirrors the calendar focus helper: set
the retained intent `{ kind: "thread", threadId, account, nonce }`, then open
the module detail tab. The tag drill-down keeps its existing single detail fetch
(the tag result carries no thread id or account) and keeps its panel fallback on
failure, retargeted at the module panel key.

### Sanitization is a host leaf; isolation stays in the module

The module cannot bundle DOMPurify: `.sdk/build.mjs` resolves third-party
packages from the SDK's own `node_modules`, no module imports any npm dependency
today, and `dompurify` is unresolvable from `code/y-module/**`. Dependencies are
host-owned by the module contract.

Host deploy A therefore exports `sanitizeEmailHtml(html)` on `@y/host` at
browser contract v11, keeping the current configuration verbatim (whole-document
parsing plus the existing forbidden-tag list). The shadow-root,
forced-light-background wrapper stays in the module. The host already ships
DOMPurify for artifacts and markdown export, so the export adds no bundle cost.
The contract bump is the same v10 → v11 bump that adds the `mail` icon.

### Signed-in address without a contract bump

The "me" recipient label derives the signed-in address from the JWT `email`
claim through the contract-stable token accessor, replacing the host-only stored
email helper. No browser-contract change is needed.

### Icon

The activity-bar icon key `mail` is added to the host icon contract list and the
host icon map as part of the v10 → v11 contract bump. Unknown icon keys still
degrade to the default icon, but publish stamps `min_host_version` from
`contract.json`, so the host web deploy must land before any module is published
against v11.

### Read-only stays read-only

The reply and overflow affordances in the reader are decorative today and remain
decorative. The star in collapsed rows is decorative today (no backend flag) and
remains so. No mailbox mutation, no scope change, no new Gmail surface.

### No public demo surface

Email is personal correspondence. The module does not publish `ui_public` and
adds no `/demo` surface, so no fictional mailbox has to be maintained and no
anonymous path can reach the domain.

### Staged sequencing

Mirroring the todo 3179 staging, and required because publish stamps the minimum
host version from the local contract:

1. **Host deploy A** — contract v11 (`mail` icon + `sanitizeEmailHtml`),
   navigation adapter, and any other host seams the module needs, while the
   legacy surface still works.
2. **Publish** the email module and verify the live surface.
3. **Parity check** against the stories above.
4. **Host deploy B** — delete the legacy panel, reader, helpers, host selection
   state, and reserved tab; add the retired-tab and activity-key migrations.

Rollback at each stage is `y module activate email <previous>` for the module
half and a host revert plus redeploy for the host half. Between B and a module
rollback the panel is simply absent; mail, sync, and CLI are unaffected.

## Testing Decisions

Tests assert user-visible behavior, and the repo default applies: verification
is static (typecheck, build, unit tests), runtime UI acceptance stays with Roy.
Test files remain local-only and untracked.

- **Pure helpers move with the module except the sanitizer.** Date formatting,
  sender parsing, own-versus-quoted splitting, HTML-body detection, and snippet
  projection already have host unit tests; those tests move into the module and
  the host copies are deleted with the host surface. `sanitizeEmailHtml` stays a
  host export (one copy, re-exported from the host email helpers until deploy B);
  its allow/deny cases (script, event handler, `javascript:` URI, embedded frame,
  form, style and image retention) stay on the host and must not thin out.
- **Thread layout is a pure function.** Which messages start expanded, how runs
  of collapsed messages bundle, and when the count bubble appears are computed
  from an ordered message list; test them over fixture threads of size 1, 2, 3,
  and a long thread, rather than through DOM assertions.
- **Host migrations are pure functions too.** Retired-tab membership, the
  activity-bar key migration, and the email branch of tag navigation are
  testable with a mocked authenticated fetch — the same shape as the existing
  tag-navigate and file-workspace host tests. Cover: a restored legacy tab never
  triggers a file fetch; a successful tag lookup opens the reader with the
  fetched thread id and account; a failed lookup opens the panel.
- **No new backend tests.** Storage, service, and API layers are unchanged; the
  existing tag-carrier storage test keeps covering the email resolver, and it is
  the regression guard for story 36.
- **Parity is checked against the story list**, not against a diff: each
  reading-parity story is a checkable item before host deploy B.

## Out of Scope

- **Moving `email` / `email_account` to module ownership.** Blocked by the
  host-side tag resolver; revisit only with a deliberate host capability design.
- **A module API or CLI half.** New owner-bound `email_*` backend capabilities
  and their contract bump are explicitly deferred; `y email` stays a built-in
  group.
- **Any mailbox mutation.** Send, reply, forward, archive, star, label, mark
  read, and delete are all out. The existing decorative affordances stay
  decorative.
- **Broadening Gmail access.** Still IMAP with app passwords over starred
  threads; no Gmail API, no OAuth mailbox scopes, no additional folders.
- **Scheduled or automatic sync.** `y email sync-gmail` stays manual.
- **Real read/unread or starred state**, and any notification surface.
- **A public demo surface or anonymous access** to the domain.
- **Treating every registered account address as "me"** in the recipients line;
  parity keeps the signed-in address only.
- **An email deep-link route.** Module detail surfaces restore as persisted
  tabs; no URL contract is added.
- **Attachments, richer threading than Gmail's thread id, and search ranking
  improvements.**
- **The module system's own mechanics.** Versioning, loading, integrity, publish
  gating, and rollback rules stay owned by [module-system](module-system.md);
  the browser runtime contract stays owned by
  [ui-dynamic-artifacts](ui-dynamic-artifacts.md). This PRD owns only the email
  domain's requirements and its ownership boundary.
- **Other reserved host tabs.** `link.md`, `entity.md`, and the rest keep their
  current shape; only the email tab is retired here.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3270 | Migrated email presentation to the versioned `email` UI module while retaining host tables / HTTP / CLI / tag carrier; retired the `email.md` tab, host selection state, and legacy host surface after live parity approval. | - | `pages/plan-3270-email-module.md` | - | `pages/review-3270-email-host-prerequisites.md`; `pages/review-3270-email-module.md`; `pages/review-3270-email-host-retirement.md` | reviewed; deploy pending |
