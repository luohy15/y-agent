---
title: Public Homepage Admission
type: prd
project: y-agent
feature: public-homepage-admission
status: active
---

# Public Homepage Admission

## Problem Statement

The y-agent homepage is publicly reachable, but it presents no sign-in and
decides access in two weak ways. A new email is checked against the
`SIGNUP_ALLOWLIST` environment value, while any email that already has a user
row is admitted automatically. The environment value is not queryable, not
auditable, and not durable across deploys. The user row rule confuses "this
identity was seen before" with "an operator approved this identity".

Two consequences follow. First, the operator cannot open the homepage to a
controlled group without silently admitting every historical account. Second,
a token issued before enforcement remains usable against the API, so gating
the login screen alone is not a gate at all. An account that was never
approved can still call protected routes directly, and the same bound account
can still reach the agent through Telegram.

There is also no way for an unapproved visitor to express interest, and no
reliable signal to the operator when one does. A person who tries to sign in
sees only a generic failure, and the operator learns about a request only if
that person finds another channel.

The product needs one durable admission record, a visible sign-in on the
public homepage, an explicit waitlist, one private notice on first application,
and a maintainer-only approval action. The rollout must be auditable: it starts
from an inventory of existing access, and it never treats a historical user row
as consent.

## Solution

Admission becomes a durable, per-verified-email record that is the single
authority for access. Google identity remains the only sign-in mechanism, and
the verified email is the identity key.

The public homepage gains a visible "Sign in" action and an explicit "Request
access" action. Sign-in succeeds only for the configured maintainer or an
approved email. An unapproved visitor can request access, which records a
pending waitlist entry, deduplicated by verified email, and sends the
maintainer one private Telegram message the first time that identity applies.
The notice is retried if Telegram delivery fails. A repeat request, or an
ordinary sign-in attempt, never sends another notice.

Approval is maintainer-only. The maintainer lists applications and approves a
pending applicant through a small CLI and its API. Approval is recorded with
actor and time, is idempotent, and makes the applicant's next sign-in succeed.
Approved is bound to the verified email, not to a Google account subject, so a
different identity cannot inherit an approval.

Enforcement is server-side at both boundaries: the login endpoint issues no
token unless admission passes, and every protected request re-checks admission.
That closes direct API use with an old token and makes approval or refusal
effective on the next request. Public share pages, health checks, the Telegram
webhook transport and the launch-scoped MCP runtime grant keep their existing
public or grant-based authentication; the bound user behind a Telegram message
still has to be admitted.

The rollout is inventory-first. Existing users are enumerated read-only and
recorded, but only the configured maintainer and the explicitly named account
(user 59, `roy.luo@alphavantage.co`) are admitted up front. Every other
historical row stays out until an explicit, recorded approval. `SIGNUP_ALLOWLIST`
is retired as an authority.

## User Stories

1. As a visitor, I want a visible "Sign in" button on the public homepage, so I
   do not have to guess a URL.
2. As a visitor with an approved Google account, I want sign-in to use the
   existing verified identity flow, so I receive the same token and enter the
   same app as today.
3. As an unapproved visitor, I want a refused sign-in to explain that this is a
   private deployment, so I know the app is working and I am not approved.
4. As an unapproved visitor, I want an explicit "Request access" action, so I
   can ask to be admitted without finding the operator out of band.
5. As an applicant, I want my application tied to my verified Google email, so
   nobody can apply on my behalf and an unverified address is never accepted.
6. As an applicant, I want a repeat request recognized as the same application,
   so I do not create duplicates or generate repeated notices.
7. As an applicant, I want the page to show that my request is pending, so I
   know what to expect and can stop retrying.
8. As an approved applicant, I want my next sign-in to succeed without a second
   application, so approval has a clear, immediate effect.
9. As the maintainer, I want one private Telegram message on the first
   successful application, so I learn about it without polling.
10. As the maintainer, I want no Telegram message for ordinary sign-in attempts,
    so the channel stays signal.
11. As the maintainer, I want no second Telegram message for a repeat
    application from the same identity, so retries and impatience do not spam me.
12. As the maintainer, I want the notice to contain the applicant email, the
    request time and the approval command, so I can act directly from it.
13. As the maintainer, I want an application to survive a Telegram delivery
    failure and the notice to be retried, so a transient outage does not lose a
    request.
14. As the maintainer, I want to list pending and approved applications, so I
    can review the queue and its notification state.
15. As the maintainer, I want to approve a pending applicant, so that person's
    next sign-in works.
16. As the maintainer, I want approval to be idempotent and recorded with the
    deciding identity and time, so repeated or concurrent approvals are safe
    and auditable.
17. As the maintainer, I want no other account to list or approve applications,
    so admission stays under my control.
18. As the maintainer, I want my own account always admitted, so a bad seed or
    an empty table cannot lock me out.
19. As the operator, I want the explicitly admitted account (internal user 59,
    `roy.luo@alphavantage.co`) preserved, so this known exception keeps working.
20. As the operator, I want a read-only inventory of existing accounts and their
    admission status before enforcement, so I can see exactly who is affected.
21. As the operator, I want no automatic approval from historical user rows, so
    past existence is never mistaken for consent.
22. As the operator, I want the inventory to distinguish maintainer, approved,
    pending and absent records, so the rollout baseline is unambiguous.
23. As the operator, I want a denied identity not to create a new user row, so
    the user table remains a record of admitted accounts rather than attempts.
24. As an unapproved user holding a token from before enforcement, I want the
    app to return me to the access screen cleanly, so I do not see broken panels
    or an empty shell.
25. As an unapproved API caller, I want a direct request with a valid token
    refused, so the web UI is not the only gate.
26. As a user of a public share link, I want the share to keep working without
    an account, so sharing is unaffected by admission.
27. As a Telegram user, I want an unapproved bound account to be refused in the
    bot as well, so the bot is not a side door around admission.
28. As an approved user, I want CLI login and existing scripts to keep working,
    so admission does not break automation.
29. As an unapproved CLI user, I want a clear denial message instead of a hung
    callback, so I know login will not complete.
30. As the maintainer, I want an approval made before the notice is sent to
    cancel that stale notice, so I am not alerted about something already done.
31. As the maintainer, I want failed notifications visible in the application
    list, so a delivery problem is not silent.
32. As an auditor, I want a recorded trail for every admission (source, request
    count, decision time and decider), so access can be explained later.
33. As an auditor, I want denied logins and admission changes logged without
    storing credentials or Google tokens, so incidents can be reconstructed.
34. As the operator, I want the old environment allowlist retired as an access
    authority, so there is exactly one place to inspect and change admission.
35. As the operator, I want the rollout to be reversible without data loss, so a
    problem can be fixed by redeploying the previous API and web build.
36. As an approved user, I want approval bound to my verified email, so another
    Google identity cannot inherit it.
37. As a pending applicant who lost the page, I want requesting again to show my
    current status, so I can re-check without creating a new request.
38. As the maintainer, I want a failed notification to stop retrying after a
    bounded number of attempts, so a permanently missing target does not create
    endless background work.

## Implementation Decisions

### Identity and admission state

- The identity key is the verified Google email from the ID token. It is
  normalized by trimming surrounding whitespace and lowercasing before any
  comparison or write. The token must carry `email_verified: true`; otherwise
  the request is treated as unauthenticated.
- A new host-owned table, `user_access`, is the admission record. One row per
  normalized email.
- Row shape:
  - `email` (normalized, unique index)
  - `status`: `pending` or `approved`
  - `source`: `waitlist` or `rollout`
  - `first_requested_at`, `last_requested_at`, `request_count`
  - `decided_at`, `decided_by` (the maintainer's public user id; `rollout` for
    seeded rows)
  - notification state: `notification_status` (`pending`, `sending`, `sent`,
    `skipped`, `failed`), `notification_attempts`, `notified_at`,
    `notification_claimed_at`, `last_notification_attempt_at`,
    `last_notification_error`
  - created and updated timestamps
- There is no `denied` status and no deletion in v1. A pending row is the
  waitlist. An approved row is a durable grant. Rows are never removed by the
  application, so the record remains auditable.
- Admission precedence for a verified email:
  1. The configured maintainer is always admitted.
  2. An `approved` `user_access` row admits.
  3. Everything else is refused. A `pending` row produces the pending denial
     state; no row produces the "request access" state.
- The maintainer is the account named by
  `Y_AGENT_MODULE_MAINTAINER_USER_ID`. It is resolved to an email through its
  user row, or directly when the configured value is already an email. If the
  value is unset or cannot be resolved to an email, there is no implicit
  maintainer and maintainer-only actions are refused for everyone. This is the
  deliberate break-glass exception, not a general allowlist.
- Historical user rows are not admission records. No migration, login, or
  background job derives approval from row existence. The only seeded approvals
  are the configured maintainer and internal user 59, recorded explicitly with
  source `rollout`.
- Approval binds the verified email. A changed Google email is a new identity
  and needs a new application and approval. Storing a Google subject id is not
  part of v1.

### Enforcement points

- `POST /api/auth/google` verifies the Google token, normalizes the email, and
  evaluates admission before any user write. It returns a token only when
  admission passes. A refusal is `403` with a machine-readable code:
  `access_pending` when a pending row exists, `access_required` when no row
  exists, and `access_not_approved` for a token-based refusal.
- The login endpoint does not create or update a user row for a refused
  identity. An approved identity with no user row gets its row created only
  after admission passes.
- Every protected API request re-checks admission in the authentication
  middleware. The check uses the token's verified email claim, falling back to
  the user row's email for legacy tokens without an email claim. A missing or
  unresolvable identity is refused. An admission lookup error fails closed.
- The maintainer is checked first by internal user id, so the maintainer does
  not depend on a table row. Other requests pay one indexed lookup by normalized
  email. No cache is introduced in v1; correctness is preferred until
  measurements justify one.
- Refusals are `403`, not `401`, because the token is valid and the identity is
  known. `401` stays reserved for a missing, malformed, or invalid token.
- The existing public routes keep their status: `/api/auth/*`, the Telegram
  webhook transport, `/api/health`, docs, the public share GET routes, and the
  launch-scoped `/api/mcp/runtime/<launch_id>` grant route. Module routes under
  `/api/module/*` are protected by the same middleware and therefore covered.
- The web client treats an `access_not_approved` refusal on any protected
  request as a terminal admission failure: it clears the stored token and
  email, drops the authenticated shell, and renders the access screen with the
  appropriate pending or request-access state. It must not retry in a loop.
- The Telegram surface is not a side door. `/bind` accepts only an admitted
  identity, and message dispatch for a bound account re-checks admission. An
  unapproved bound account receives a short refusal message and no agent run is
  started.
- Public share reads stay anonymous. Admission controls use of the service, not
  the viewing of a deliberately shared artifact.

### Waitlist application

- A public `POST /api/access/request` endpoint accepts only a Google ID token.
  It uses the same audience and verification as login. No email address is
  accepted from the client.
- A first request creates a `pending` `user_access` row with source `waitlist`,
  `request_count = 1`, and the current request time, then attempts the first
  notification. A repeat request returns the existing status, updates
  `last_requested_at` and increments `request_count`, and never creates a second
  row or a second notification.
- If the identity is already `approved`, the endpoint returns `approved` and
  the client signs the person in with the same credential.
- The endpoint never creates a user row. The response reports `status` and
  whether this call created the application, so the landing page can render
  "pending" versus "already pending" without exposing other applicants.
- A request for an identity with no application does not reveal whether any
  other email is approved.

### Notification to the maintainer

- A new application triggers exactly one private Telegram direct message to the
  configured maintainer. Ordinary login attempts, repeat applications and
  approval actions never trigger another application notice for the same row.
- The message contains the applicant email, the request time, and the exact
  approval command (`y access approve <email>`). It contains no token, password
  or other secret.
- Delivery is attempt-once-then-outbox. The application is committed before the
  send. The sender atomically claims the row by moving `notification_status`
  from `pending` to `sending`; exactly one sender can hold that claim. On
  success the row becomes `sent`. On failure it returns to `pending`, increments
  `notification_attempts`, and records the sanitized error and attempt time.
  The application response does not fail because Telegram failed.
- A scheduled admin action retries rows still `pending` at a bounded cadence
  (every five minutes), with a minimum gap between attempts and a bounded
  attempt count (ten). A row that exhausts attempts becomes `failed`. A stale
  `sending` claim older than the send timeout is reclaimable.
- Approving a row whose notice is still `pending` sets `notification_status` to
  `skipped`, because the maintainer has already acted. A send already in flight
  may still arrive once; that is acceptable and is the only duplicate case.
- If the maintainer has no Telegram binding or the bot token is unset, the
  application still succeeds, the notice stays pending and then failed, and the
  state is visible in the application list. Retries never block the API request.
- The admin Lambda needs the maintainer identity configured so the retry job can
  resolve the recipient. The existing Telegram bot token is reused; no new
  secret is introduced.

### Maintainer approval

- Maintainer-only API routes:
  - `GET /api/access/applications` lists applications, optionally filtered by
    status, with notification state.
  - `POST /api/access/applications/approve` approves by normalized email.
  - `GET /api/access/inventory` returns existing user rows joined to admission
    state for the rollout audit.
- These routes compare the authenticated internal user id with the configured
  maintainer id. Anyone else gets `403`, including an otherwise approved user.
  If the maintainer is unconfigured, everyone is refused.
- Approval requires an existing application row. It is idempotent: approving an
  already approved row returns the same state without changing the recorded
  decision. It sets `status = approved`, `decided_at`, and `decided_by`, and
  applies the notification cancellation rule. Concurrent approvals converge on
  one recorded decision.
- Approval takes effect on the applicant's next request because both login and
  the middleware consult the row. No token or session is created by approval
  itself.
- The maintainer surface is a built-in `y access` CLI group over these routes:
  - `y access list [--status pending|approved]`
  - `y access approve <email>`
  - `y access inventory`
  A web approval panel is not part of v1. Because the manager session runs as
  the maintainer, the approval command is also usable from the normal chat.

### Public homepage

- The landing page keeps its current public content, theme control, changelog
  and GitHub links, and gains two visible actions in the header and hero:
  "Sign in" and "Request access". Both use the existing Google identity flow
  and the existing preview-domain behavior. No second identity provider is
  added.
- The line "Private deployment. No public sign-up yet." is replaced with copy
  that reflects approval-based access rather than claiming there is no way in.
- Sign-in states:
  - approved: the app mounts as today.
  - pending: an inline "Your access request is pending approval" message.
  - no application: an inline explanation plus a "Request access" button.
  - invalid or failed identity verification: a generic retry message; no token
    is stored.
- The "Request access" action verifies identity first, then calls the request
  endpoint. It shows "request received", "already pending" or "approved" as
  appropriate. The credential is kept only in component memory so a follow-up
  approval action can reuse it without a second popup; it is never persisted.
- A previously stored token that is now refused is cleared and the visitor sees
  the same access screen. The landing page makes no protected API calls, so it
  cannot loop.
- The UI works in both Solarized themes and at the existing responsive
  breakpoints.

### Data, migration and audit

- The schema change is additive: create `user_access` and its unique index. It
  does not alter the `user` table and does not backfill from it.
- The rollout seed is an explicit, idempotent insert for two identities:
  - the configured maintainer (recorded for audit, although admission is also
    implicit)
  - internal user 59, `roy.luo@alphavantage.co`
  Both seeded rows use source `rollout`, an explicit decision time, and
  `decided_by = rollout`.
- Approval records carry `decided_by` (the maintainer's public user id) and
  `decided_at`. Application rows carry `first_requested_at`, `last_requested_at`
  and `request_count`, so repeat requests are visible without implying a new
  decision.
- Server logs record denied logins and token refusals with the normalized email
  and the reason code, and record approval changes with the deciding identity.
  They never log Google ID tokens, JWTs, or Telegram credentials.

### Rollout and auditing

The rollout is ordered so that the maintainer and the named exception are never
locked out, and so the baseline is reviewable before enforcement.

1. Produce the inventory read-only: every non-deleted user row with internal id,
   public user id, email, creation time, maintainer status, and whether an
   admission row exists. Include counts of recent activity where practical.
   Archive the output with the delivery record; it is the audit baseline.
2. Review the inventory against the intended list. The only pre-approved
   identities are the maintainer and internal user 59. Any additional approval
   is a new explicit decision, recorded after the inventory, not an inference.
3. Apply the additive DDL and the explicit seed. Do not derive seeds from a
   `SELECT` over the user table.
4. Deploy the web build with the visible sign-in and request-access actions.
   Until the API is deployed these actions may fail gracefully; the old landing
   remains usable.
5. Deploy the API with enforcement and the access routes. From this point,
   `SIGNUP_ALLOWLIST` is ignored and every protected request checks admission.
6. Verify on the deployed environment:
   - the maintainer can sign in and use a protected route;
   - internal user 59 can sign in;
   - a sampled unapproved existing account is refused at login, is refused on
     a direct protected API call with its old token, and is shown the request
     access state in the web app;
   - a request creates one pending row and one Telegram message;
   - a repeat request sends no second message;
   - approval makes the next login succeed;
   - a public share link still opens without an account;
   - an unapproved bound Telegram account is refused without starting a run.
7. Rollback is redeploying the previous API and web builds. The additive table
   remains and is ignored by the old code. No user row, chat, or admission data
   is deleted. Pending notifications simply stop being retried.
8. Retire `SIGNUP_ALLOWLIST` from configuration and documentation as an access
   authority. Leaving it set has no effect.

### API and error contract

- `POST /api/auth/google`: success unchanged (`token`, `email`). Refusal: `403`
  with `detail` and `code` in `access_pending`, `access_required` or
  `access_not_approved`.
- `POST /api/access/request`: body is the Google ID token only. Success:
  `{status: "pending" | "approved", created: boolean}`. Invalid or unverified
  identity: `401`.
- `GET /api/access/applications`: maintainer-only. Returns email, status,
  source, request times, request count, decision time and decider, notification
  state and attempts. No internal integer ids.
- `POST /api/access/applications/approve`: maintainer-only. Body is the
  normalized email. Returns the approved record. Unknown application: `404`.
- `GET /api/access/inventory`: maintainer-only. Returns existing user rows with
  public user id, email, creation time, maintainer status and admission status.
  Read-only; it never writes an admission row.
- Protected-route refusal: `403` with `code = access_not_approved`. Public routes
  retain their current status codes.

## Testing Decisions

Verification is behavior-level and runs against a deployed test or production
environment. This repository does not commit unit tests and does not run local
database-connected tests; the static checks and the deployed acceptance matrix
below are the contract.

A good check asserts the external effect: HTTP status and machine-readable
code, whether a token or user row was created, the stored admission and
notification state, and what the surfaces show. It does not assert internal
function names or call private helpers.

Acceptance matrix:

| Scenario | Expected effect |
|----------|-----------------|
| Maintainer signs in | Token issued; protected request succeeds |
| User 59 signs in after seed | Token issued |
| Approved email signs in | Token issued |
| Existing unapproved email signs in | `403 access_required`; no token; no new user row |
| Pending email signs in | `403 access_pending`; no token |
| Invalid or unverified Google token | `401`; no row written |
| First request access | One pending row; one Telegram notice; response says created |
| Repeat request access | Same row; `request_count` increases; no second notice |
| Approved email requests access | Response `approved`; sign-in succeeds |
| Unapproved token calls a protected route | `403 access_not_approved` |
| Unapproved token opens app with stored token | Token cleared; access screen shown |
| Public share link | Still opens without a token |
| Non-maintainer lists or approves | `403` |
| Maintainer lists and approves pending | Idempotent approval with decider and time |
| Telegram delivery fails | Application succeeds; notice pending; retry later sends once |
| Approval before notice sent | Notice skipped; no stale alert |
| Notification target permanently absent | Bounded attempts end in `failed`, visible in list |
| Unapproved bound Telegram account | Refusal reply; no agent run |
| Rollout inventory | Lists every existing user with admission state; no writes |

Static verification: `uvx ruff@0.17.3 check` for the Python members and
`npm run build` for the web app. UI checks are against the deployed page in both
themes at the existing breakpoints, including a failed sign-in, a pending
application and a successful approval. Screenshots, if requested, go to the
workspace screenshots directory.

Prior art to preserve: the existing Google ID token verification and CLI
manual-token flow, the owner Telegram notice path, and the existing public
share routes.

## Out of Scope

- Self-serve sign-up, invite codes, invite links, email/password login, and any
  identity provider other than the existing Google flow.
- Applicant-facing email or Telegram notifications. The applicant learns status
  from the page or by requesting again.
- Waitlist ordering, capacity, positions or automatic promotion.
- A denial status, revocation workflow, approval reason field, or a web
  approval panel. V1 has pending and approved only, and approval is CLI/API.
- Token expiry, token-version invalidation, or session revocation beyond the
  per-request admission check.
- Anti-abuse beyond verified-email deduplication, such as IP rate limits,
  captchas, or automated review of bulk applications.
- Changes to tenant isolation, application-layer encryption, data
  classification, or tenant activation. Admission decides who may sign in and
  call the API; it does not change `encryption_eligible`, tenant keys, or the
  hosted-tenant confidentiality model. The tenant confidentiality PRD owns those
  decisions, and both documents preserve the same named accounts through the
  same explicit inventory discipline.
- Backfilling, modifying, or deleting existing user rows, chats, or other data.
  The migration is additive and the rollout inventory is read-only.
- Unrelated bot routing, todo, chat, or module behavior.
