---
title: Web Refresh / Revalidation Policy
type: prd
project: y-agent
feature: web-refresh-policy
status: active
---

# Web Refresh / Revalidation Policy

## Problem Statement

The authenticated web app is a multi-panel SPA whose centre tabs stay mounted
while hidden, and whose host chrome and hot-loadable module UI share one SWR
instance and one cache. Two distinct problems follow from that, and both are
invisible in the code until something misbehaves.

**Nobody owns automatic revalidation.** A surface the user cannot see keeps
polling on its interval, keeps revalidating on window focus and network
reconnect, and keeps retrying failed reads. For ordinary lists that is merely
wasteful; for reads that cost provider quota or wake a VM it is expensive, and
the user pays it for data they are not looking at. Sharing the cache does not
make ownership shared: when two components subscribe to the same resource, the
first subscriber's options decide whether a focus event refetches, so a hidden
component can silently starve a visible one.

**Explicit refresh has no home.** Every surface that wants a manual refresh
ships its own button. They appear in different rows, with different icons and
different spin behavior, and one of them performs a side-effecting upstream sync
rather than a refetch. The user has to learn where "refresh" lives per tab, and
each new module surface either reinvents the control or ships without one. The
user's complaint was exactly this: one refresh at the tab level would be
simpler than each module carrying its own.

A single tempting fix - a generic host-side gate that transparently parks every
hidden surface's reads - was investigated and rejected. It cannot preserve
resource identity, mutation semantics, and infinite-list state at the same
time without becoming a custom cache adapter, and it demonstrably broke
data-dependent surfaces.

## Solution

One durable policy with two halves, split along who knows what.

**Automatic revalidation is surface-scoped and module-owned.** The host tells a
mounted detail surface whether it is the active tab; combined with document
visibility, that gives a module the one fact it cannot determine for itself.
A module then opts a specific resource in: while the owning surface is hidden,
its interval polling, focus revalidation, reconnect revalidation, and automatic
error retry are suppressed; when the surface becomes visible again, the owner
refreshes that resource once. Real keys, cached data, errors, and mutations are
never substituted, so nothing on the surface is lost by hiding it. Adoption is
per resource and per module, never a blanket host promise.

**Explicit refresh is host-owned tab chrome.** The centre tab's breadcrumb row
carries at most one refresh control, in the same place with the same icon and
the same spinner for every tab kind. For the host's own special tabs the host
refreshes its data directly. For a module detail tab, the module registers a
refresh handler through the `@y/host` browser contract and the host renders the
control only if a handler was registered - so the button exists exactly when it
works. The host owns placement, icon, spinner and invocation; the module owns
what refresh means and supplies the hover title. Per-module refresh buttons that
duplicate this affordance are retired.

The two halves are deliberately separate mechanisms: one is about not fetching
data nobody is reading, the other is about fetching on demand. They share only
this document.

## User Stories

### Automatic revalidation while hidden

1. As a web user, I want a centre tab that is open but not the active tab to
   stop polling its data, so that a background surface does not spend requests
   on data I am not reading.
2. As a web user, I want the same suppression when the browser tab or window
   itself is hidden, so that leaving the app open in another window does not
   keep polling.
3. As a web user, I want window focus not to trigger a refetch for a surface I
   cannot see, so that alt-tabbing back does not fan out reads across every
   open tab.
4. As a web user, I want network reconnect not to trigger a refetch for a
   hidden surface, for the same reason.
5. As a web user, I want automatic error retry to stop while a surface is
   hidden, and a retry that was already scheduled to check current visibility
   when it fires, so that a failing hidden read does not retry in a loop
   forever.
6. As a web user, I want an explicit single refresh of a resource when its
   surface becomes visible again, so that returning to a tab never shows me a
   number that stopped updating while I was away.
7. As a web user, I want everything on a hidden surface preserved - loaded
   data, unsaved drafts, selections, expanded rows, scroll position - so that
   hiding a tab is never destructive.
8. As a web user, I want an explicit action I started - a Retry click, a save,
   any mutation - to complete and write the real cache even if I switch tabs
   before it resolves, so that switching away never silently discards my own
   action.
9. As a web user, I accept that a surface's first read on mount, and a request
   already in flight when the surface hides, may still complete. The contract
   suppresses automatic recurring and event-driven reads, not every possible
   request while hidden.
10. As a web user, I want each gated resource to have exactly one subscriber
    inside the surface, so that a hidden duplicate subscription cannot suppress
    the visible one's focus or reconnect refresh.
11. As a web user, I want sub-view granularity: a metadata read that does not
    need a poll must not start one merely because its parent view is open, and
    a live sub-view's poll must stop when a different sub-view is shown.
12. As a web user, I want a resource shared with a separately mounted panel to
    keep fetching regardless of detail-tab visibility, so that gating a detail
    surface never breaks the sidebar reading the same list.
13. As a web user, I want surfaces whose module has not adopted this policy to
    keep their previous behavior unchanged, so that adoption is verifiable per
    resource rather than claimed globally.
14. As a web user, I want global revalidation defaults, awaiting-todo
    freshness, chat discovery, the live SSE message path, and module-registry
    discovery left alone by this feature, so that the live conversation surface
    and the inbox keep behaving as they do today.

### Explicit tab-level refresh

15. As a web user, I want one refresh control in the centre tab's chrome, in the
    same position with the same icon for every tab that has refreshable data,
    so that I stop learning a per-tab location for the same action.
16. As a web user, I want the control absent on a tab with nothing to refresh -
    an inline chart, diagram, or SVG artifact tab - so that the chrome does not
    offer a meaningless action.
17. As a web user, I want the control absent on a module tab whose surface has
    not registered a refresh handler, so that I never click a button that does
    nothing.
18. As a web user, I want visible spinner feedback for the duration of the
    refresh, with a minimum visible spin, so that a fast refresh still reads as
    having happened.
19. As a web user, I want the control's hover title to say what this tab's
    refresh actually does, supplied by the surface when its semantics are
    specific rather than a generic "refresh".
20. As a module author, I want to register a refresh handler from my detail
    surface and have the host render the control, so that I stop shipping and
    styling my own button.
21. As a module author, I want registration scoped to my tab, so that my hidden
    but still-mounted surface cannot hijack the active tab's refresh control.
22. As a module author, I want my registration removed when my surface
    unmounts, so that closing the tab removes the control with it.
23. As a module author, I want the registration hook to be a safe no-op where
    the host renders no tab chrome - a panel surface, the demo shell without
    the channel - so that one component can be used in both places.
24. As a module author, I want the host to own the spinner by awaiting my
    handler's promise, so that I delete my local spin state and timers instead
    of reimplementing them.
25. As a web user on the Tag detail tab, I want its refresh to move to the tab
    chrome with unchanged behavior: revalidate the tag's results.
26. As a web user on the Todo tab, I want the list refresh to move to the tab
    chrome with unchanged behavior: revalidate the list without losing mode,
    filters, selection, sort, or already-loaded pages.
27. As a web user on the Bot usage view, I want the tab-chrome control to keep
    performing the existing spend sync from the relay and then revalidate, with
    a title that says so, and to be offered only while the usage view is the
    shown view.
28. As a web user on the Bot usage view, I want the separate limit-window retry
    control to stay where it is, because subscription limit status is a
    different read from spend data and must be refreshable independently.
29. As a web user on an ordinary file tab, I want the File viewer's own refresh
    in its own header to stay as it is, because those tabs render no host
    breadcrumb row.
30. As a visitor to the public demo, I want the showcased detail surfaces to
    offer the same refresh control as the signed-in app, so that the demo does
    not silently lose an affordance.
31. As a maintainer, I want a module published against the newer browser
    contract to refuse to mount on an older host rather than render a dead
    control, relying on the existing contract-floor check instead of an
    in-module fallback.
32. As a maintainer, I want a module that consumes the new hook to be published
    only with the matching contract floor stamped on it, because a module
    bundle stamped with the older floor still mounts on an older host and then
    crashes at render instead of showing the clean version-skew card that story
    31 relies on.
33. As a maintainer, I want the rollback hazard stated: rolling the host web
    bundle back below the contract version that introduces the registration
    hook, while module versions that require it are active, disables those tabs
    at once. Rollback is therefore per module, and each module's active version
    is recorded before publishing.

## Implementation Decisions

### Visibility signal: reuse the detail-context channel

The host already passes a per-tab object into a mounted detail surface through
the browser contract's detail-context channel. The active-tab signal rides that
existing channel as `{ active: <boolean> }`; ordinary file tabs keep their own
richer detail context unchanged. A consumer reads it as
`useDetailContext<{ active?: boolean }>()?.active ?? true`, so a module built
before the signal existed, or mounted where no host supplies it, behaves exactly
as it does today. No new export and no contract bump were needed for this half.

### Visibility policy: module-owned, per resource, single owner

The gated behavior lives in the owning module, not in host middleware:

- The module reads surface-active AND document-visible as one boolean.
- While false: `refreshInterval` is 0, focus and reconnect revalidation are
  off, and automatic error retry is suppressed. A retry callback scheduled
  before hiding re-checks current visibility when it fires.
- SWR's own `isPaused` / `isVisible` are not used, the key is never swapped for
  a null or dummy key, `keepPreviousData` is not forced, and no snapshot
  adapter, cache fork, or private subscriber-table edit exists.
- On a false→true transition the owner explicitly revalidates the real key
  once. A request already in flight may incur one extra revalidation; this is
  accepted, and the contract is not an exactly-once network guarantee.
- Each gated resource has exactly one subscriber in the surface, and child
  components receive that owner's response and callbacks as props rather than
  subscribing again. Consolidation is the fix for first-subscriber starvation,
  not coordination between two subscribers.
- The policy is written for the normal one-tab-per-module-slug identity. It must
  not be applied blindly to a resource shared with a separately mounted panel,
  nor generalized to hypothetical duplicate independently visible copies of the
  same detail surface.

### Why not a generic host gate

The rejected alternative parked every hidden detail surface's reads behind a
host SWR middleware. The installed SWR does not expose a read-only cache
subscription and an automatic-revalidation subscription separately for one
hook, so the mechanism had to choose: stay on the real key and remain the first
revalidator (starving visible subscribers), or leave the real key and change the
identity that reads and mutations target (redirecting delayed completions,
emptying data-dependent subtrees, and breaking infinite-list page metadata).
Making it correct meant reimplementing hidden cache updates, loading/error
fallbacks, argument-count-sensitive mutations, and infinite `setSize` - a custom
adapter, not a visibility option. The middleware was removed from production
source; its regression evidence is retained locally as history, not as a
pending requirement.

### Explicit refresh: registration, not a broadcast

The host renders the tab refresh control from a registration, not from a
broadcast signal:

- A host-internal provider wraps each mounted detail surface; the browser
  contract exports a `useTabRefresh(handler, { title })` hook. The handler is
  held in a ref so an inline arrow function does not re-register on every
  render, and registration is cleared on unmount.
- The host keys registrations by tab key, because every open tab's detail mount
  stays mounted while hidden. Entries for closed tabs are dropped.
- The rejected alternative was pushing a refresh nonce through the existing
  detail-context channel: no contract bump, but the host then cannot know which
  module tabs honour it, so most tabs would show a dead control, and a host-side
  blanket `mutate` fallback reproduces a previously shipped failure mode where
  wildcard cache writes emptied a rendered list.
- One control, two sources: for the host's legacy special tabs it calls the
  host's own refresh; for a module detail tab it calls the registered handler.
  Inline artifact tabs register nothing and get no control.
- The host awaits the handler's returned promise and owns a minimum visible
  spin duration. Modules delete their local spin state and timers.
- The control lives in the breadcrumb row's trailing slot beside Copy path,
  reusing the existing refresh icon and adding no new tab-strip slot. That row
  is visually the row the File module's own detail header occupies, so
  placement is consistent across tab kinds.

### Module semantics are preserved, not genericised

Retiring a per-module button relocates the affordance; it never redefines what
refresh does. The Bot usage control keeps performing its upstream spend sync
before revalidating and is registered only while the usage view is shown. The
Bot limit-window retry stays a separate control. Ordinary file tabs keep the
File module's header refresh, because giving them a host breadcrumb row they
deliberately do not have would be a larger change than the problem warrants.

### Contract and delivery shape

- The registration hook bumps the `@y/host` browser contract from 16 to **17**
  (v16 is the already-shipped activity-bar visibility bridge and has no refresh
  hook):
  the contract JSON, the generated type declaration, the host SDK export
  surface, the SDK README, and the demo runtime's allowlist of keys safe to
  expose to unauthenticated demo code. The hook is pure registration with no
  network access, so it is demo-safe; omitting it from the allowlist would make
  the public demo throw once a module published against v17 loads there.
- The version ledger that narrates each browser-contract bump stays in
  `docs/prd/module-system.md`. This PRD states which version introduces the
  hook and does not duplicate the ledger.
- No backend contract change, no API route change, and no database migration.
  The host half ships through the web bundle deploy only.
- Sequencing, and what actually depends on what. The module bundler resolves
  `@y/host` to a runtime shim rather than compiling against the SDK's types, so
  module source that calls a not-yet-existing host export still builds. Module
  implementation is therefore *not* blocked on the host bump. Two things are:
  the module typecheck against the generated declaration, and the
  `min_host_version` floor, which the build stamps from the locally materialized
  SDK's contract version and the publish path reuses. The local SDK
  re-materializes automatically from the installed CLI once the bump reaches the
  canonical host checkout; neither force-installing a worktree CLI nor
  hand-editing the materialized contract is an acceptable shortcut, since the
  first pins every CLI command to a directory that will be deleted and the
  second stamps a floor the host does not implement.
- Ordering that must hold: host source integrates to the canonical checkout,
  then the host web bundle deploys and the live host reports the new contract
  version, and only then are the modules published one at a time, each build
  asserting the expected stamped floor. Publishing before the host bundle is
  live leaves those tabs on a version-skew failure card; publishing with a
  stale stamped floor is worse, because the module mounts and crashes instead.
- The contract floor is enforced client-side by the module loader, so a module
  requiring v17 on an older host refuses to mount. No in-module fallback button
  is needed or possible.
- Each module's currently active version is recorded immediately before its
  publish, because rollback is per module and another trace may have moved a
  pointer in the meantime.

## Testing Decisions

Verification is non-browser by default, matching this project's standing
speed-over-runtime-acceptance tradeoff. Runtime UI acceptance in a real browser
is the user's step, not an agent's.

- **Test external behavior, not internals.** For the visibility half, assert
  fetch counts across hide/show transitions, that cached data and the real key
  survive hiding, that a delayed explicit retry writes the real cache rather
  than a synthetic entry, that a pending automatic retry does not fire while
  hidden, that polling resumes on activation, and that a non-polling metadata
  read never acquires an interval. For the refresh-control half, assert that a
  module tab with no registration renders no control, that a registered tab
  renders one and clicking it invokes the handler exactly once, and that
  unmounting clears the registration.
- **Integrate against real module source.** The 3519 slice was verified by
  mounting the actual module detail component with real SWR under jsdom, with
  only fetch and host presentation dependencies mocked, and a local Vitest
  config resolving the module's React and SWR to the host's copies. That is the
  prior art for any future cross-repository slice of this feature: a host-only
  unit test cannot prove a module-owned policy.
- **Host tests live beside the host units they cover** (`web/src/host/*.test.tsx`
  run by Vitest); module tests are the module's own runner. Test files are
  local-only and untracked in this repository.
- **Build and typecheck evidence is reported honestly.** The host production
  Vite build must exit 0 and the module bundle build must exit 0. Host
  production typecheck carries a known baseline diagnostic unrelated to this
  feature, and the module SDK-scoped typecheck carries a stable set of
  pre-existing diagnostics; a slice is clean when it adds no new diagnostic
  category or count, which is not the same as a clean typecheck.
- **Historical regression tests for the rejected middleware are evidence, not
  acceptance tests.** They still describe the abandoned mechanism and must not
  be presented as a green suite for the delivered policy.

## Out of Scope

- **Generic hidden centre-tab suppression for every resource.** Deferred
  deliberately, not pending. Each additional resource needs its module to
  consolidate subscriptions and validate its own mutation and infinite-list
  semantics. The parked-key proposal is abandoned, not an alternative contract.
- **A global opt-out of focus revalidation**, and any change to global SWR
  defaults.
- **Module bundle or server-side response caching, and payload trimming.**
  Different problem, different feature.
- **Refresh controls on left-rail panel surfaces.** The tab-chrome contract
  reaches centre tabs only.
- **Adopting the remaining detail surfaces that ship their own refresh**
  (monitor, email, eat, calendar, the chat shell), and the File module's own
  header refresh on ordinary file tabs.
- **The browser-contract version ledger** - owned by
  [module-system](module-system.md), which narrates each bump.
- **What Bot spend and limit-window data mean, how they are read, persisted and
  refreshed upstream** - owned by [bot-usage](bot-usage.md). This PRD only
  decides where the controls live and that the two stay separate.
- **Todo detail navigation, list-state preservation, and back behavior** -
  owned by [todo-detail-view](todo-detail-view.md). This PRD relocates that
  surface's refresh control without changing what it revalidates.
- **File sidebar expansion, selection, and its explicit Refresh semantics** -
  owned by [filetree-navigation-state](filetree-navigation-state.md), which is
  about the tree's persisted navigation state rather than centre-tab
  revalidation.
- No follow-up todo is implied or created by anything listed here.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3519 | Host per-tab active signal through the existing detail-context channel, plus a Bot-owned real-key visibility policy for the rate and limit-window reads (suppress polling / focus / reconnect / automatic retry while hidden, one owner per resource, one explicit refresh on activation). No contract bump. | - | `pages/plan-3519-web-refresh-policy.md` (superseded by the decision note; retained as the audit of the rejected generic gate) | `pages/decision-3519-explicit-surface-refresh.md` (approved replacement); `pages/impl-3519-bot-visibility.md` (both-artifact implementation inventory) | `pages/review-3519-surface-visibility.md` (round 4 approve); `pages/investigation-3519-bot-v38-digest.md` (published-byte equivalence of the active Bot version) | shipped: host `369dd50`, Deploy Web run 34733872345 success; Bot module v38 active from `fe26e45` |
| 3674 | Host-owned tab-level refresh control in the centre tab's breadcrumb chrome, backed by a new `@y/host` v17 `useTabRefresh(handler, { title })` registration; retires the Tag detail, Todo list, and Bot usage spend-sync buttons while preserving their semantics. Keeps the Bot limit-window retry and the File module's own header refresh separate. | - | `pages/plan-3674-fileviewer-tab-refresh.md` | This PRD; `pages/impl-3674-host-tab-refresh.md`; `pages/impl-3674-module-tab-refresh.md` | `pages/review-3674-tab-refresh-contract.md` (round 3 approve) | reviewed; local candidate commits authorized; publication pending; host baseline `22fdc78`, module baseline `cfc2f66` |
