---
title: Public Module Demos
type: prd
project: y-agent
feature: public-module-demos
status: active
---

# Public Module Demos

## Problem Statement

y-agent's Getting Started guide explains its four showcased capabilities with
static screenshots: Chat, Todo & Trace, Note, and Link. The screenshots are easy
to view, but they cannot demonstrate the interactions that make the product
useful. They also become stale whenever a module is published, which creates a
second documentation surface that must be recaptured and maintained by hand.

Letting a visitor interact with the real application is not an acceptable
shortcut. The normal module surfaces are authenticated and connected to the
owner's chats, todos, notes, links, credentials, and backend capabilities. A
public preview that reuses those data paths could expose private state even if
its visible controls appeared read-only. A copied public implementation would
avoid that immediate risk but would recreate the screenshot problem in code:
the demo and production UI would drift on separate release clocks.

The user needs public interactive examples that remain visually and
behaviorally current with the production module versions while having no path
to real user data or mutation.

## Solution

Provide four stable, unauthenticated demo pages for Chat, Todo & Trace, Note,
and Link. Each page loads the active public UI bundle for the corresponding
production surface and mounts a demo entrypoint that reuses the same production
components and interaction logic. The only substituted layer is the data and
command boundary: demo mode receives deterministic fictional sample data and
an in-memory, read-only command adapter instead of authenticated APIs, user
state, or persistent storage.

The module's active UI version is the sole rendering authority for both normal
and demo use. There is no separately published demo bundle and no copied demo
component tree. Publishing a new active version therefore updates the public
demo with the same bytes. If an active version is not explicitly public, does
not provide a demo entrypoint, or is incompatible with the running host, the
demo fails closed to a generic unavailable state rather than loading an older
version or falling through to production data.

Public delivery exposes UI bytes only. Anonymous visitors may resolve and fetch
an explicitly public module UI bundle, but they may not dispatch the module's
backend, call authenticated domain routes, or acquire a request owner. Demo
data is bundled deterministic content or an equivalently static public asset;
it is never projected, sampled, anonymized, or generated from production
records.

Getting Started replaces or supersedes each screenshot with a clear launch or
sandboxed embed of its matching demo. Every page carries a quiet but persistent
"Demo data" indicator, preserves the normal visual hierarchy, and makes
unsupported mutating actions either visibly unavailable or locally simulated
without network or persistence.

## User Stories

### Discovery and access

1. As a prospective user, I want to open each showcased capability without an
   account, so that I can understand y-agent before signing in.
2. As a documentation reader, I want Chat, Todo & Trace, Note, and Link to each
   have a stable public URL, so that documentation and external references do
   not depend on transient share identifiers.
3. As a documentation reader, I want each Getting Started walkthrough to launch
   or embed its corresponding interactive demo, so that the example is adjacent
   to the explanation it illustrates.
4. As a visitor, I want a demo link to open directly to the named capability, so
   that I do not have to navigate an authenticated home screen.
5. As a visitor on a phone, tablet, or desktop, I want the demo to use the same
   responsive behavior as the normal surface, so that the preview represents
   the actual product.
6. As a visitor, I want the page to identify itself as demo data without a large
   blocking banner, so that I do not mistake fictional records for a live
   account while the product remains the focus.
7. As a visitor, I want a broken or unavailable demo to show a clear generic
   state, so that I am not redirected to sign-in or shown a partially working
   authenticated surface.

### Production fidelity

8. As a prospective user, I want the demo to look like the corresponding module
   on the normal home page, so that it is a truthful preview rather than a
   marketing mockup.
9. As a prospective user, I want representative controls, navigation, expanded
   states, filters, and detail views to work, so that I can learn the product by
   interacting with it.
10. As a maintainer, I want production and demo mode to render through the same
    component authority, so that fixes and visual changes are not implemented
    twice.
11. As a maintainer, I want the active production UI bundle to be the demo
    bundle, so that publishing a module updates its demo without recapturing a
    screenshot or publishing a second artifact.
12. As a maintainer, I want sample data and behavior adapters to be the only
    demo-specific layer, so that the demo does not become a parallel frontend.
13. As a maintainer, I want every showcased surface to meet the same reuse rule,
    even if a surface is not module-owned when implementation begins, so that a
    demo-only clone is never accepted as a shortcut.
14. As a maintainer, I want a module version to opt in explicitly to public UI
    delivery, so that ordinary private or administrative modules are not made
    public by convention.
15. As a maintainer, I want a version without a compatible demo entrypoint to
    fail closed, so that the host never guesses that a normal authenticated
    surface is safe to mount publicly.
16. As a maintainer, I want the demo pointer to follow the active module version
    rather than retain a stale last-known-good demo version, so that the page
    never silently misrepresents what is live.

### Demo data and interactions

17. As a visitor, I want realistic fictional records, so that lists, metadata,
    empty states, detail views, and relationships are understandable.
18. As a visitor, I want the same sample data on every fresh load, so that the
    walkthrough is reproducible and support can refer to specific examples.
19. As a maintainer, I want sample records to be handcrafted or generated from a
    fixed safe seed, so that their provenance is inspectable and independent of
    production.
20. As a maintainer, I want demo identifiers, names, paths, URLs, timestamps,
    and content to be fictional, so that no real user's metadata leaks through a
    seemingly harmless field.
21. As a visitor, I want representative read interactions to work locally, so
    that I can open records, switch views, search, filter, expand details, and
    follow relationships.
22. As a visitor, I want safe state-changing gestures to be simulated locally
    when they are important to understanding the interface, so that I can try
    the interaction without changing server state.
23. As a visitor, I want destructive, credentialed, external, or misleading
    actions to be disabled with a concise demo explanation, so that a control
    never appears to have changed a real system.
24. As a visitor, I want simulated changes to reset on reload, so that the demo
    has no durable state and always returns to the documented baseline.
25. As a visitor, I want links and host commands inside the demo to remain
    within allowlisted demo navigation or safe public documentation, so that an
    interaction cannot open private resources.
26. As a visitor, I want Chat to demonstrate representative conversation
    rendering, process disclosure, rich content, and local selection or export
    behavior without creating, steering, stopping, or sharing a real chat.
27. As a visitor, I want Todo & Trace to demonstrate list or kanban navigation,
    todo details, and a fictional trace relationship without reading or updating
    a real todo or trace.
28. As a visitor, I want Note to demonstrate its categories, list behavior, and
    content preview using fictional files and metadata without resolving a real
    content path.
29. As a visitor, I want Link to demonstrate archive browsing, filtering, and a
    fictional content preview without fetching a URL, browser history, cookies,
    or stored link content.

### Privacy and security

30. As the owner, I want demo mode selected explicitly before module code mounts,
    so that missing authentication or a failed production request can never be
    interpreted as demo mode.
31. As the owner, I want the production data adapter to remain uninitialized in
    demo mode, so that rendering the demo cannot accidentally start an
    authenticated fetch, stream, subscription, or background refresh.
32. As the owner, I want anonymous delivery limited to an allowlisted public
    manifest and content-addressed UI bundle, so that it does not expose module
    inventory, source storage keys, backend hashes, or management operations.
33. As the owner, I want module backend dispatch to remain authenticated, so
    that public demos cannot execute Python under the API's database or AWS
    identity.
34. As the owner, I want demo mode to have no user identity, access token,
    credential, VM configuration, or production identifier, so that there is
    nothing private for module code to consume.
35. As the owner, I want authenticated and domain API requests to fail closed in
    the public demo runtime, so that an accidental production code path cannot
    reach real data.
36. As the owner, I want mutation attempts to perform no server request and no
    durable browser write, so that read-only is an enforced boundary rather than
    explanatory text.
37. As the owner, I want public route selection restricted to the four intended
    showcase demos, so that visitors cannot use the demo shell to probe arbitrary
    installed modules.
38. As the owner, I want unknown, disabled, non-public, incompatible, or
    hash-invalid module versions rejected without executing their UI, so that
    failure cannot widen access.
39. As a maintainer, I want automated tests to inspect anonymous requests and
    attempted mutations, so that a visual read-only state is not mistaken for
    actual isolation.
40. As a maintainer, I want fixture provenance reviewable in source, so that
    production-derived content cannot enter the demo unnoticed.

## Implementation Decisions

### Feature boundary

This PRD owns the public showcase experience: stable demo routes, the public
demo mount, the demo-mode data and command boundary, the four fictional
datasets, and the Getting Started integration. The Module System PRD continues
to own module identity, active-version resolution, bundle integrity, UI
contract versioning, and the distinction between public UI delivery and backend
dispatch.

The four canonical demos are:

| Demo | Stable route | Representative scope |
|------|--------------|----------------------|
| Chat | `/demo/chat` | Conversation rendering, process detail, rich content, and safe local selection/export behavior. |
| Todo & Trace | `/demo/todo` | Todo list or kanban, details, status relationships, and a fictional trace. |
| Note | `/demo/note` | Note categories, list navigation, metadata, and fictional content preview. |
| Link | `/demo/link` | Archive browsing, filters, metadata, and fictional saved-content preview. |

The route names are documentation contracts. They do not encode a user, share,
module version, or sample-data identifier. The public host uses an explicit
allowlist for these route keys. A generic `/demo/<installed-module>` browser is
not part of the feature.

### One UI bundle, two data environments

The active module UI bundle is the only published rendering artifact. A
public-demo entrypoint is part of that bundle and composes the same production
view components used by the normal panel, detail, or shell. It may add only the
small framing needed for a standalone page and demo disclosure. It must not fork
the production component tree or copy rendered markup into the host.

Production and demo mode differ at an explicit dependency boundary selected
before mount:

- Production mode binds the module's normal API, stream, storage, and host-command
  adapters.
- Demo mode binds a module-owned fictional fixture, in-memory query/state
  behavior, and a restricted command adapter.
- Shared components depend on that boundary rather than deciding between real
  and demo data from authentication state.
- A showcased surface that is not yet backed by a single reusable production UI
  authority must establish one before its demo ships. A host-side or
  documentation-only clone is not an acceptable intermediate architecture.

The boundary is intentionally capability-shaped rather than a mock HTTP server.
A demo does not intercept production URLs and return fixtures. Production
network code is never initialized, which keeps data isolation structural and
makes an unexpected request a test failure rather than part of normal demo
operation.

### Sample-data authority

Each module owns the fixture for its own demo because it owns the domain's UI
contract. Fixtures ship in the same content-addressed UI bundle, or as immutable
public assets identified by that bundle. They contain only handcrafted content
or output from a deterministic fixed-seed generator whose inputs are committed
and reviewable.

Production exports, database snapshots, redacted records, analytics, browser
history, shared-link payloads, and runtime generation from authenticated state
are forbidden inputs. Redaction is not accepted as fixture generation because
it retains provenance and can miss identifiers in nested or free-text fields.

Fixtures should cover enough variation to exercise meaningful states without
trying to mirror a whole account. Dates are fixed or derived from a fixed demo
clock. Locally simulated changes live only in memory and reset on navigation or
reload. The browser must not use localStorage, IndexedDB, cookies, or service
workers to persist demo-domain state.

### Public UI delivery, not public backend dispatch

The existing per-version `ui_public` decision becomes the opt-in for anonymous
UI-byte delivery. A purpose-built anonymous manifest exposes only the fields
needed to identify and integrity-check enabled public UI versions. A
content-addressed public bundle route serves only versions that remain eligible
for public delivery. Neither route exposes API bundle metadata, source digests,
storage keys, ownership, or the maintainer's module inventory.

`dispatch_scope` remains limited to `maintainer` and `authenticated`. The normal
module dispatcher, management routes, authenticated module list, and all module
API handlers remain behind authentication. The demo never obtains a database
session, request owner, VM command capability, or domain backend capability.

The public demo host provides only browser-safe rendering primitives and local
navigation/command capabilities required by the demo entrypoint. Authenticated
fetch helpers and mutating host commands reject use in this environment.
Modules must not issue direct network calls from demo mode. The browser page's
network policy and tests enforce the expected public manifest, bundle, and
static-asset allowlist.

### Version and failure behavior

The demo resolves the currently active version on each page load. It does not
have an independent activation pointer, pin a historical version, or silently
serve the previous public version. This keeps the demo truthful and preserves
atomic updates when production UI changes.

Eligibility is fail-closed. The host renders a generic demo-unavailable state
when the module is unknown, disabled, not `ui_public`, missing its demo
entrypoint, above the browser contract version, unavailable, or fails integrity
or rendering checks. That state contains no rollback or management action and
never mounts the authenticated production surface as a fallback.

The UI bundle is public browser code, not a secret. Integrity verification
continues to detect stale pointers and corrupt storage; it does not claim to
protect against a host origin that serves both a modified hash and modified
bytes.

### Read-only interaction policy

Read interactions operate entirely over the fixture. A state-changing control
uses one of two explicit treatments:

1. **Local simulation** when the gesture is central to understanding the UI and
   its result can be represented honestly in memory. The page labels or otherwise
   makes clear that the change is temporary demo state.
2. **Disabled action** when it would create external effects, require secrets or
   identity, imply a durable result, navigate to private state, or add little
   explanatory value. The control remains visually consistent and gives a short
   demo-specific reason.

No action may fall back to a real endpoint, sign-in flow, module management
operation, public share creation, URL fetch, VM command, or external write.

### Documentation integration

Getting Started remains the narrative authority for the four showcased
capabilities. Its screenshots are replaced or clearly superseded by links or
sandboxed embeds to the stable demo routes. The surrounding prose explains what
to try in each demo and distinguishes demo-only limitations from authenticated
product behavior.

Whether a capability is linked or embedded is a presentation decision based on
available space and responsive usability. An embed must use the same stable page
and isolation boundary as a direct visit, not a second rendering mode. The
Capabilities reference is updated to describe the walkthroughs as interactive
demos rather than screenshots.

## Testing Decisions

Tests target the public contract and isolation boundary, not fixture component
internals.

- **Anonymous availability:** each stable demo route loads in a clean browser
  profile with no token, cookie, localStorage identity, or prior service worker.
- **Route allowlist:** the four canonical routes resolve; unknown demo keys and
  non-public, disabled, or incompatible module versions fail closed without
  mounting module UI.
- **Public bundle gate:** anonymous callers can resolve and fetch only eligible
  public UI bundles. Authenticated module listing, module management, ordinary
  bundles, module dispatch, and domain API routes remain denied.
- **Network isolation:** after the public manifest, UI bundle, and required
  static assets load, representative interactions issue no authenticated,
  domain, stream, share-creation, VM, or mutation request. Unexpected requests
  fail the test.
- **No ambient identity:** the demo runtime exposes no auth token, request owner,
  user or VM identifier, credential, production base-data adapter, or private
  host command.
- **Mutation resistance:** exercise every visible mutating control. Disabled
  controls remain inert; simulated controls change only in-memory fixture state,
  produce no request or durable browser write, and reset after reload.
- **Fixture provenance:** fixture source is reviewed for fixed fictional values
  or deterministic safe-generation inputs. Tests reject accidental imports of
  production export paths or runtime fixture fetches.
- **Version coupling:** activating a new eligible UI version changes the demo's
  resolved hash and rendering; removing public eligibility makes the demo
  unavailable rather than leaving the prior version live.
- **Integrity and render failure:** hash mismatch, bundle fetch failure, missing
  demo export, and render exceptions produce the generic unavailable state and
  do not invoke an authenticated fallback.
- **Representative behavior:** Chat expands process/rich-content states; Todo
  opens and filters sample work plus its fictional trace; Note switches sections
  and previews content; Link filters and previews saved content. Assertions
  focus on user-visible behavior shared with production.
- **Responsive behavior:** each demo is checked at representative phone, tablet,
  and desktop widths for reachable navigation, readable detail content, and no
  dependence on the authenticated app shell.
- **Documentation links:** generated Getting Started and Capabilities pages point
  to the four stable routes, and any embeds are sandboxed and resolve the same
  pages used by direct navigation.

Tests should use synthetic fixtures exclusively. A test environment must not
need production credentials or a production database to prove the demo works.

## Out of Scope

- Public or unauthenticated module backend dispatch. This feature consumes
  public UI bytes only; anonymous Python execution remains prohibited by the
  Module System contract.
- Public access to real, anonymized, redacted, sampled, shared, or generated-from-
  production user data. Existing chat/trace/note share pages retain their own
  token-scoped contracts and are not demo data sources.
- A generic public gallery for every installed module, module marketplace, or
  public discovery of the maintainer's module inventory.
- A second demo bundle, a host-owned copy of module UI, screenshot automation as
  the primary experience, or long-lived screenshots that must track releases.
- Durable demo accounts, server-side demo tenants, seeded production rows, demo
  login credentials, or reset jobs.
- Persisting visitor changes between page loads or devices.
- Executing real sends, shares, fetches, imports, edits, status transitions,
  deletes, VM commands, credential checks, or external navigation that carries
  private context.
- Replacing the authenticated home screen or changing the normal module data
  contracts beyond the dependency seam required to share the production UI.
- Moving existing public chat or trace share pages into modules. Their
  token-scoped real-data renderer and fallback policy remain separate from
  deterministic showcase demos.
- Redesigning the four production capabilities. Demo-specific framing should be
  minimal; visual changes to the underlying surfaces belong to their own
  features.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3158 | Replace or supersede the four Getting Started screenshots with stable, unauthenticated, read-only interactive demos backed by active production module UI and deterministic fictional data. | - | - | `pages/decision-3042-public-dispatch-scope.md` | - | requirements captured; planning pending |
