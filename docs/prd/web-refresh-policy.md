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

**Explicit refresh is generic host-owned tab chrome.** The centre tab's
breadcrumb row carries at most one refresh control, in the same place with the
same icon and the same spinner for every tab kind, and a module does nothing to
get it. For the host's own special tabs the host refreshes its data directly.
For every module detail tab the host runs one generic two-stage refresh: it
revalidates every SWR key that tab's subtree currently subscribes to, then
remounts that tab's subtree. Stage 1 reaches shared cached data without
discarding anything; stage 2 reaches state no cache write can reach, such as a
surface that fetches in a plain effect. Refresh therefore works in every
internal view of every module, including views nobody thought to wire up. A
module owns only two things: whether it has an unsaved draft the remount would
discard, and any *domain* action (an upstream sync, a ledger re-read) that is
not a view refresh and keeps its own control. Per-module view-refresh buttons
that duplicate the tab affordance are retired.

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
17. As a web user, I want the control present and working on every module tab
    by default, whether or not that module did anything to enable it, so that
    refresh is a property of the app rather than a per-module feature I have to
    discover the absence of.
18. As a web user, I want visible spinner feedback for the duration of the
    refresh, with a minimum visible spin, so that a fast refresh still reads as
    having happened.
19. As a web user, I want one predictable hover title - "Refresh" on a module
    tab, "Refresh file" on a host special tab - because refresh now means the
    same thing on every module tab and a per-surface wording would imply a
    per-surface behavior that no longer exists.
20. As a module author, I want to ship no refresh code at all - no hook call,
    no handler, no button, no spin state - and still have my tab refresh
    correctly, so that a new module surface cannot ship without the affordance.
21. As a module author, I want refresh scoped to the refreshed tab's own
    subtree: only the keys that tab subscribes to are refetched, and my hidden
    but still-mounted surface is neither refreshed nor able to hijack the
    active tab's control. A tab that happens to share a key with the refreshed
    one receives the fresh data without issuing a second request.
22. As a module author, I want the host to drop a tab's refresh state when the
    tab closes, so that reopening it starts clean.
23. As a module author, I want the mechanism inert where the host renders no
    tab chrome - a panel surface, a mount with no registry - so that one
    component can be used in both places.
24. As a module author, I want the host to own the spinner - across the
    revalidation and the remount it schedules, though not across network work
    my remounted surface starts afterwards, which my own loading states already
    show - so that I delete my local spin state and timers instead of
    reimplementing them.
25. As a web user on the Tag detail tab, I want refresh to keep revalidating the
    tag's results, with the module's own button and its hook call removed.
26. As a web user on the Todo tab, I want refresh to revalidate the list
    including every already-loaded page, without losing mode, filters,
    selection, or sort, and to ask me first when an open detail edit would be
    discarded.
27. As a web user on the Bot tab, I want refresh to work in *every* Bot view,
    including configuration and providers, not only Usage - that was the
    original complaint about a per-view opt-in.
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
    contract to refuse to mount on an older host rather than render a surface
    whose draft guard silently does nothing, relying on the existing
    contract-floor check instead of an in-module fallback.
32. As a maintainer, I want a module that consumes the new hook to be published
    only with the matching contract floor stamped on it, because a module
    bundle stamped with the older floor still mounts on an older host and then
    crashes at render instead of showing the clean version-skew card that story
    31 relies on.
33. As a maintainer, I want the rollback hazard stated: rolling the host web
    bundle back below the contract version an active module version requires
    disables those tabs at once. Rollback is therefore per module, and each
    module's active version is recorded before publishing. The host keeps
    exporting the superseded registration hook as a no-op precisely so the
    module versions that still call it stay rollback-reachable.
34. As a web user, I want the control to actually refetch every time I click it,
    including immediately after a failed read and including a second click a
    moment after the first, because "it looks like it did nothing" is the whole
    reason I clicked.
35. As a web user, I want refresh to also reach a surface that does not use the
    shared cache at all, so that a view built on a plain effect fetch is not
    quietly unrefreshable.
36. As a web user, I want to know what a refresh costs me: my persisted view
    choice, sort, filters and navigation survive it, every other open tab is
    untouched, and what a refresh does discard is limited to that tab's
    transient in-component state - scroll position, expand/collapse, and any
    unsaved draft.
37. As a web user with an unsaved draft in the refreshed tab, I want to be asked
    before anything happens, not between the two stages, because fresh data can
    itself replace the editor holding my draft. Cancelling must leave the tab
    exactly as it was, with neither stage started.
38. As a web user, I want a domain action that is not a view refresh - the Bot
    spend sync from the relay, the Finance ledger re-read, the Bot limit-window
    retry - to stay its own control with its own wording, because collapsing it
    into the tab refresh would either hide it or make every refresh
    side-effecting.

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

### Explicit refresh: scoped revalidation, then a scoped remount

The control is unconditional, and what it runs is generic host logic:

- The host owns one **refresh registry** and one **remount nonce** per open
  module tab, keyed by tab key because every open tab's detail mount stays
  mounted while hidden. Both are dropped when the tab closes.
- Each detail mount is wrapped in that registry plus a nested SWR config that
  appends one host middleware. The middleware records each SWR hook's *bound*
  `mutate` for as long as that hook is mounted inside the tab. No module code
  participates, and the nested config passes no cache provider, so the
  persisted cache and cross-panel `mutate` are inherited unchanged.
- **Stage 1** awaits every recorded mutate. A bound mutate is the only thing
  that reliably refetches: SWR's mount-time revalidation is dedupe-gated and is
  skipped outright while a request for that key is still registered - which, in
  the installed version, lasts for the whole deduping interval *after* the
  request resolves - and is not attempted at all when the key holds an error and
  another subscriber is still mounted. That error case is exactly the state a
  user clicks refresh in. Mutation-driven revalidation bypasses both gates.
- **Stage 2** bumps the tab's nonce, remounting that tab's subtree. This is what
  reaches a surface that fetches in a plain effect and holds no cache key.
- Ordering is load-bearing twice over. The draft guard runs **before either
  stage**, because stage 1 is not inherently lossless: a refreshed payload that
  no longer contains the edited record makes the surface swap its editor for an
  unavailable branch, destroying the draft and clearing the dirty report, so a
  confirm asked between the stages is either too late or never shown at all.
  Cancelling therefore starts neither stage. Once accepted, the remount still
  waits for stage 1 to settle, because the root abort middleware aborts
  in-flight fetches on unmount and remounting first would cancel the
  revalidation it just started.
- Recording bound mutates rather than keys avoids serializing function keys and
  is what makes `useSWRInfinite` work: the host middleware sits outside SWR's
  own infinite middleware, so the recorded mutate is the infinite-bound one for
  the whole list rather than one per page.
- The nonce keys the render boundary *inside* the mount, never the mount
  itself, so the verified bundle is not re-fetched or re-hashed and the injected
  scoped `<style>` does not churn. A surface that crashed while rendering is
  reloaded through the loader's promise cache on the same bump, so refresh can
  recover it.
- Two rejected alternatives. Registration (the superseded v17 design) made
  refresh a per-module opt-in, which is the requirement this revision exists to
  fix. Remount alone is not a refresh: within the deduping interval it issues
  zero requests, it does nothing after a failed read, and modules that set
  `revalidateIfStale: false` or a long deduping interval would be unrefreshable
  for as long as that interval lasts.
- One control, two mechanisms behind it: the host's legacy special tabs keep
  their existing targeted invalidation; module tabs get the two-stage refresh.
  Inline artifact tabs render a static spec and get no control.
- The host owns a minimum visible spin duration and awaits stage 1 plus the
  scheduling of the nonce. It does not await network work a remounted surface
  starts afterwards; that surface's own loading states communicate it. Modules
  delete their local spin state and timers.
- The control lives in the breadcrumb row's trailing slot beside Copy path,
  reusing the existing refresh icon and adding no new tab-strip slot. That row
  is visually the row the File module's own detail header occupies, so
  placement is consistent across tab kinds.

### What a refresh preserves, and what it costs

A refresh discards in-component state for the refreshed tab only, so the cost is
stated rather than discovered. Both stages can do it: stage 2 unconditionally,
and stage 1 whenever the fresh payload makes the surface render something other
than the editor that held the state.

- **Preserved**: anything persisted outside the component (`localStorage` view
  selectors, sort and filter state; server-side user preferences such as Todo
  navigation and the file workspace), module-level stores, host intents, and
  every other open tab.
- **Lost**: unsaved drafts, scroll position, transient expand/collapse, and any
  view selector a module chose not to persist.
- Losing a draft silently would contradict behavior the app already treats as
  worth a confirm, so the contract adds `useTabDirty(dirty)`. While the active
  tab reports a draft the host confirms before it starts a refresh at all;
  cancelling leaves both stages unstarted, so the user keeps their draft and the
  data they were already looking at. The hook is a guard, not a capability gate:
  refresh works on a module that never calls it.
- An explicit refresh deliberately overrides a module's long automatic-
  revalidation deduping interval (Finance's 30s provider-cost window). Explicit
  user intent beats an automatic-fetch cost policy.

### View refresh is generic; domain actions stay module-owned

Making view refresh generic does not absorb the domain actions that happened to
share a button with it. Bot's spend sync from the relay is an upstream write
followed by a read, so it stays a Bot-owned control in the Usage view with its
own wording; folding it into the tab refresh would make every Bot refresh
side-effecting. The Bot limit-window retry and Finance's ledger re-read stay
separate for the same reason. Ordinary file tabs keep the File module's header
refresh: they render no host breadcrumb row by design, that header already
carries path, copy, history and save, and its refresh clears loaded content
while keeping unsaved edits - strictly better than the generic remount. Giving
those tabs a second chrome row duplicating path and copy would be a larger
change with worse refresh semantics.

### Contract and delivery shape

- The generic mechanism itself needs no contract export: it is host chrome plus
  a host middleware. The draft guard does, so `useTabDirty(dirty)` bumps the
  `@y/host` browser contract from 17 to **18** across the contract JSON, the
  generated type declaration, the host SDK export surface, the SDK README, and
  the demo runtime's allowlist of keys safe to expose to unauthenticated demo
  code. Both it and the superseded `useTabRefresh` no-op are pure state with no
  network access, so both are demo-safe; omitting either from the allowlist
  would make the public demo throw once a module published against them loads
  there.
- v17's `useTabRefresh` is kept as a documented no-op rather than deleted,
  because the module versions that call it (tag v20, todo v26, bot v49) stay
  rollback-reachable. Deleting it is a follow-up for when they are not.
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
  requiring v18 on an older host refuses to mount. No in-module fallback button
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
  read never acquires an interval. For the refresh-control half, the
  claims that must be proved against the real SWR instance are: a module tab
  that registers nothing renders an enabled control; a refresh refetches on a
  *second* click inside the deduping window that a remount is silently skipped
  in; a refresh refetches a key whose cached state is an error while another
  subscriber is mounted; a refresh touches only the keys the refreshed tab
  subscribes to; one `useSWRInfinite` hook contributes exactly one
  infinite-bound mutate; the remount is not issued until the revalidation
  settles; cancelling the draft guard leaves *both* stages unstarted, asserted
  against a mounted dirty editor whose refreshed payload would replace it, not
  only against a stubbed registry; and bumping
  one tab's nonce leaves another tab's mount alone. Asserting the host's own
  helpers in isolation is not enough here, because every one of these claims is
  a claim about SWR's behavior.
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
- **The File module's own header refresh on ordinary file tabs**, and the
  refresh controls on surfaces the tab chrome does not reach (left-rail panels,
  the chat shell). Module view-refresh buttons on centre detail tabs are
  retired by this feature, not deferred.
- **Migrating the host's five legacy special tabs onto the same registry
  mechanism.** They keep their existing targeted invalidation behind the same
  control.
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
| 3674 | Generic host-owned tab refresh on every module detail tab, with no module opt-in: the host wraps each detail mount in a per-tab registry plus an SWR middleware that records each mounted hook's bound `mutate`, then refreshes in two stages (revalidate every key the tab subscribes to, await, then remount that tab's subtree via a nonce on the render boundary). `@y/host` v18 adds `useTabDirty(dirty)` as a draft guard before the remount and reduces v17's `useTabRefresh` to a documented no-op kept for rollback-reachable module versions. Retires the Tag, Todo, Bot, Email and Eat in-tab view-refresh buttons (Household never had one; Finance is documentation-only); keeps the Bot spend sync, the Bot limit-window retry, Finance's ledger re-read and the File module's header refresh as separate domain actions. | - | `pages/plan-3674-fileviewer-tab-refresh.md` (revision 3) | This PRD; `pages/impl-3674-host-tab-refresh.md`; `pages/impl-3674-module-tab-refresh.md` | `pages/review-3674-tab-refresh-contract.md` (round 5 approve for revision 3; rounds 1-3 approved only the superseded v17 candidate) | revision 3 reviewed and approved (round 5); the v17 registration design shipped as `265599a` and was rejected by Roy, so its publication authorization does not carry over; host baseline `265599a`, module baseline `f4d07e1`; candidates frozen, integration, web deploy and the tag/todo/bot/calendar/email/eat module publishes pending |
