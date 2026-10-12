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

An `email` module owning the domain's presentation and local-source CLI: the
Email panel as its `panel` surface and the thread reader as its `detail` surface
are published and rolled back independently of the host. `y email` resolves
lazily from the module's `cli.py`; CLI source is local and unversioned, not part
of a published module artifact.

The host keeps what it must keep: the `email` and `email_account` tables, the
`/api/email/*` HTTP surface, app-password custody, the per-account sync route,
and the tag carrier and resolver. Email is a **UI + CLI module over host-owned
domain state**, not a data move. The CLI calls the existing host routes.

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

28. As the owner, I want the module CLI's `y email sync-gmail` to keep fanning
    out over every registered account and importing starred threads exactly as
    it does now through the host routes, so that ingestion is unaffected by the
    migration.
29. As the owner, I want app passwords to stay in host custody, never rendered
    after entry and never returned to the browsing surface, so that the
    migration does not widen credential exposure.
30. As the owner, I want Gmail ingestion to stay read-only over starred threads
    with an IMAP app password, so that the CLI move adds no ingestion permission.
    Explicit SMTP sending is the separate opt-in exception in "Sending (CLI)".
31. As the owner, I want the module CLI's `y email list`, `get`, `account`, and
    `tag` to keep working unchanged through the host routes, so that agents and
    scripts that read mail are unaffected.
32. As the owner, I want mail to stay owner-scoped on every read path, so that
    no surface can serve another account's mail.
32a. As a user, I want a per-account sync action in the account manager that
     runs the existing host Gmail sync for that address only, so that new starred
     mail appears without leaving the UI or mixing accounts. Duplicate clicks
     while that account is already syncing are rejected; other accounts stay
     independent.

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

### Boundary: a UI + CLI module over host-owned domain state

The module declares `ui` and `cli` parts, with `panel` and `detail` UI surfaces.
Tables, HTTP, credentials custody, and the tag carrier stay host-owned. The
local-source `y email` CLI calls the existing host routes; no module API or
backend contract bump is needed. Three facts drive this:

- **The host reads email rows in process.** `email` is a direct tag carrier and
  the host registers a batch resolver that hydrates tag results with each
  email's subject or sender. Modules may not be read by the host, so the tables
  must stay host-owned; without the resolver, tag results fall back to bare ids
  (story 36).
- **A module HTTP half would buy nothing.** It would mean new owner-bound
  `email_*` backend capabilities and a backend contract bump purely to re-expose
  the queries the host already serves owner-scoped. The domain has no
  module-specific business logic to relocate.
- **Credential custody stays in the host.** The account credential route serves
  the local sync and send CLI, never the browsing surface. The module CLI reads
  those credentials at runtime; plaintext app passwords are not embedded in a
  per-version published artifact. CLI discovery uses local source regardless of
  the published UI's enabled state or version, so disabling or rolling back the
  UI leaves ingestion and CLI working (stories 29, 34).

The module UI calls the existing host routes with the SDK's authenticated fetch,
exactly as the Todo and Calendar modules call their host routes.

### Explicit per-account sync stays host-owned

The Email module has no API half. Browser code must not call
`/api/email/account/credentials` and must not speak IMAP or SMTP. A host-owned
`POST /api/email/account/{address}/sync` validates that the address is
registered for the caller, acquires an owner-and-account lock, runs
`y email sync-gmail --account <address> --json` through VM execution, and
returns a bounded `{status, address, count, summary}` envelope. Failures map to
non-2xx with a safe message. Credentials, internal integer user ids, and the
raw command log are never returned.

This is an explicit manual UI action, not scheduled or automatic sync. The CLI
fan-out over every registered account is unchanged; `--json` is an additive
result mode around the same `_sync_account` pipeline.

A representative per-account run of `luohycs@gmail.com` on 2026-08-25 completed
in 10.33s (24 starred threads / 42 messages). CloudFront's custom origin read
timeout defaults to 30s and is not overridden in `template.yaml`. The route
stays synchronous: it probes `is_vm_asleep` (read-only, never starts the
instance) before acquiring the lock and returns 503 when the VM is stopped, so
`ssh_exec` never runs the unbounded `ensure_and_touch_vm` cold-boot prelude.
The VM command then runs with `wake=False` and a 26s timeout (30s minus 4s of
lock/probe/response overhead). If a later measured run exceeds that remaining
budget, replace the route with an asynchronous job rather than raising the
timeout past CloudFront.

`pipeline_lock.try_acquire_lock` fails open and is not atomic, so this route
uses `try_acquire_exclusive_lock` keyed by `email-sync:{user_id}:{address}`.
The lock TTL (60s) is longer than the command timeout as a stale-lock backstop.

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
remains so. The reader adds no mailbox mutation or scope change. Explicit
plain-text sending is a separate module CLI action, not a reader affordance.

### Sending (CLI)

`y email send` (todo 3866) sends one plain-text message, with optional
attachments, from a registered account over Gmail SMTP. It is module CLI only:
the module has no send UI, no API route, and no contract change. Safety rules:
without `--confirm <fingerprint>` (or with `--dry-run`) it only prints a
preview; the fingerprint hashes sender, recipients, subject, body, and
attachment digests, so any edit forces a fresh confirmation. A send is
attempted once and never retried. A per-machine ledger
(`~/.y-agent/email-send-ledger.jsonl`, under the OS user's home, no bodies or
passwords) records an attempted send before connecting and refuses an identical
message unless `--allow-resend`. Reservation uses an `fcntl` lock so concurrent
attempts cannot bypass the duplicate check. Passwords are never echoed.

- As the owner, I want a preview and fingerprint before anything is sent, so
  that only the content I reviewed goes out.
- As the owner, I want a failed send never retried automatically, so that a
  flaky connection cannot spam a recipient.
- As the owner, I want an identical message refused the second time, so that a
  re-run cannot double-send.

The module CLI source must land before the host removes its built-in email
group, which otherwise shadows the module. CLI changes need neither module
publish nor a deployment. A host rollback restores that built-in shadow.

### No public demo surface

Email is personal correspondence. The module adds no public demo surface, and
no anonymous path can reach the domain.

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
- **A module API half.** New owner-bound `email_*` backend capabilities and
  their contract bump are explicitly deferred; the module CLI uses host routes.
- **Any mailbox mutation beyond plain sending.** Reply, forward, archive, star,
  label, mark read, and delete are all out (plain sending is the CLI-only
  exception in "Sending (CLI)"). The existing decorative affordances stay
  decorative. No HTML, reply, or scheduled send and no web compose UI.
- **Broadening Gmail ingestion.** Still IMAP with app passwords over starred
  threads; no Gmail API, no OAuth mailbox scopes, no additional folders. Explicit
  sending uses Gmail SMTP with the registered account's existing app password.
- **Scheduled or automatic sync.** `y email sync-gmail` stays a manual CLI, and
  the UI action is an explicit per-account trigger of that same command. No
  background schedule, all-account UI sync, progress streaming, or cancellation.
- **Real read/unread or starred state**, and any notification surface.
- **A public demo surface or anonymous access** to the domain.
- **Treating every registered account address as "me"** in the recipients line;
  parity keeps the signed-in address only.
- **An email deep-link route.** Module detail surfaces restore as persisted
  tabs; no URL contract is added.
- **Reading attachments, richer threading than Gmail's thread id, and search
  ranking improvements.** Sending optional attachments is the CLI-only exception.
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
| 3866 | Moved the local-source `y email` CLI into the email module and added Gmail SMTP send: preview + exact fingerprint confirmation, single attempt, local duplicate ledger. Host retains tables, routes, credentials custody, sync route, and tag carrier. | - | `pages/plan-3866-email-send.md` | - | `pages/review-3866-email-send.md` | implemented, local |
| 3270 | Migrated email presentation to the versioned `email` UI module while retaining host tables / HTTP / CLI / tag carrier; retired the `email.md` tab, host selection state, and legacy host surface after live parity approval. | - | `pages/plan-3270-email-module.md` | - | `pages/review-3270-email-host-prerequisites.md`; `pages/review-3270-email-module.md`; `pages/review-3270-email-host-retirement.md` | shipped |
| 3287 | Host per-account sync route (`POST /api/email/account/{address}/sync`) with exclusive compare-and-set lock, sleeping-VM 503 probe, and `y email sync-gmail --json`; SDK build scans/hashes `code/y-module/shared/ui`. Module half adds per-account sync controls in the account manager and copy-thread-id buttons on thread rows + detail title, via the shared `shared/ui/copy-button.tsx` leaf also adopted by Tag. Shipped as email v2 / tag v11. | - | `pages/plan-3287-email-sync-copy-thread-id.md` | - | `pages/review-3287-email-sync-host.md`; `pages/review-3287-email-module-ui.md` | shipped |
| 3292 | Moved the email tag carrier from `email_id` to the canonical thread key `COALESCE(thread_id, email_id)`; per-message tagging dropped entirely rather than kept as a second level. Host adds `/api/email/thread/{thread_id}/tags` (GET / POST / POST `remove`), `?tag=` on `/api/email/threads`, `y email tag list/add/rm`, thread-keyed filtering + hydration, and routes generic email tag writes through the same thread and vocabulary validation. Module half adds one shared `ThreadTags` editor on panel rows and the detail header (no per-message controls) and maps `/api/module/tag/add|remove` host errors to 404/400. Data migration `migration/3292_email_thread_tags.sql` is maintainer-applied. Shipped as host `b72fab7` + email v3 / tag v13. | - | `pages/plan-3292-email-thread-tag-carrier.md` | - | `pages/review-3292-email-thread-tag-carrier.md`; `pages/review-3292-email-tag-module.md` | shipped |
