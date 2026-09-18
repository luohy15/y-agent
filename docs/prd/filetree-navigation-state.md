---
title: File Tree Navigation State
type: prd
project: y-agent
feature: filetree-navigation-state
status: active
---

# File Tree Navigation State

## Problem Statement

The Files sidebar is a working context, not a disposable directory listing. A
user may have several nested directories expanded, one or more entries selected,
loaded branches available for instant reopening, and the tree scrolled to the
part of the workspace they are using. Losing that context when switching
activities, refreshing the page, restarting the browser, or opening y-agent on
another device forces the user to reconstruct their place and repeats directory
requests whose results were already known.

The first delivery of this feature retained that context only in the File
module's browser memory. It solved activity-switch unmounts but deliberately
reset on refresh, restart, and another device. The accepted requirement now
extends the same behavior across those boundaries. Browser-only state is no
longer sufficient.

Persisting a tree introduces two constraints that the browser-memory version
could defer. Filesystem paths and directory entries are potentially sensitive
and must never cross authenticated user boundaries. They are also observations,
not durable filesystem truth: another process or device may rename, move,
delete, replace, or make an entry inaccessible after a snapshot was saved. A
persisted snapshot must therefore preserve useful navigation intent without
turning stale data, errors, or concurrent writes into destructive state changes.

## Solution

Persist each authenticated user's File tree navigation snapshots in the existing
owner-scoped backend preference store. The File module owns a versioned document
shape and its reconciliation rules; the host continues to own the generic
preference transport and authenticated storage. This reuses the same established
backend-persistence mechanism as the host-owned File workspace and requires no
File-specific table, database migration, module API endpoint, or backend host
contract addition.

A snapshot remains isolated by the full tree context: panel location, VM, and
work directory. It contains expanded paths, selected paths and range anchor,
loaded directory branches, and vertical scroll position. A local in-memory copy
is the immediate rendering and interaction authority. The backend document is
the durable authenticated replica used to hydrate that copy after refresh,
browser restart, or on another device.

Hydration renders a valid persisted snapshot without first re-listing every
branch. Uncached directories are fetched on demand. Explicit refreshes and
successful create, rename, move, delete, upload, and reveal operations reconcile
the same state and then persist the result. Only a successful directory listing
may establish that an entry disappeared or changed type. Authentication,
permission, network, malformed-response, and other listing failures retain the
last known navigation intent rather than masquerading as an empty directory.

Persistence is asynchronous and coalesced so tree interaction and scrolling do
not wait on a network round trip. The backend preference is last-write-wins for
concurrent edits to the same tree context. Before writing, the client merges its
changed context into the latest known document so unrelated left/right,
VM, and work-directory contexts are not discarded. A newer remote same-context
snapshot may replace local state on the next hydration; live multi-device
collaborative merging is not part of this feature.

## User Stories

1. As an authenticated user, I want an expanded File tree to survive switching
   to another activity and back, so that panel navigation does not reset my
   workspace.
2. As an authenticated user, I want an expanded File tree to survive a page
   refresh, so that reloading y-agent does not erase my place.
3. As an authenticated user, I want File tree state to survive a browser
   restart, so that returning later restores my working context.
4. As an authenticated user, I want File tree state to follow my account to
   another device, so that I can continue from the same filesystem location.
5. As an authenticated user, I want left and right Files panels to retain
   independent state, so that using both panels does not make one overwrite the
   other.
6. As an authenticated user, I want each VM and work-directory combination to
   retain independent state, so that navigation in one filesystem root cannot
   appear in another.
7. As an authenticated user, I want expanded directories restored, so that the
   same branches are visible after hydration.
8. As an authenticated user, I want selected entries and the range-selection
   anchor restored, so that multi-entry operations retain their context.
9. As an authenticated user, I want the tree's vertical scroll position
   restored, so that I return to the visible region I was using.
10. As an authenticated user, I want loaded directory branches restored, so
    that revisiting known branches does not issue duplicate list requests merely
    because the page or device changed.
11. As an authenticated user, I want a valid persisted tree to render before
    filesystem revalidation, so that backend persistence improves continuity
    instead of replacing one startup request with many VM requests.
12. As an authenticated user, I want opening an uncached directory to fetch it
    once and add it to the same persisted snapshot, so that the cache grows from
    actual navigation.
13. As an authenticated user, I want Collapse All to clear expansion while
    retaining loaded branches, so that reopening a directory remains immediate.
14. As an authenticated user, I want explicit Refresh to re-list the root and
    expanded directories without collapsing them or resetting scroll, so that I
    can request fresh filesystem truth without losing navigation intent.
15. As an authenticated user, I want a successful listing that no longer
    contains an entry to prune that entry's cached descendants, expansion,
    selection, and anchor, so that deleted or externally moved paths do not stay
    actionable forever.
16. As an authenticated user, I want an entry whose type changed to invalidate
    its old subtree state, so that a file replacing a directory cannot retain
    impossible descendants.
17. As an authenticated user, I want a failed, unauthorized, or malformed
    listing to preserve the prior snapshot, so that an unavailable branch is not
    mistaken for an empty branch.
18. As an authenticated user, I want successful create and upload operations to
    refresh the destination and persist the resulting tree, so that new entries
    appear without resetting surrounding state.
19. As an authenticated user, I want a newly created entry revealed and selected
    through the shared tree state, so that reveal does not become a second
    expansion authority.
20. As an authenticated user, I want successful rename and move operations to
    remap matching path prefixes in cached branches, expansion, selection, and
    anchor before persisting, so that a directory subtree follows its new path.
21. As an authenticated user, I want successful delete operations to remove the
    deleted path and all descendant state before persisting, so that the backend
    does not resurrect deleted navigation state.
22. As an authenticated user, I want failed filesystem actions to leave
    persisted navigation state unchanged, so that an unsuccessful command does
    not manufacture a filesystem transition.
23. As an authenticated user, I want tree interactions to remain responsive
    while state is saved, so that expansion, selection, and scrolling never wait
    on backend persistence.
24. As an authenticated user, I want rapid scroll and selection changes to be
    coalesced, so that preserving state does not generate a write for every
    browser event.
25. As an authenticated user, I want changes to one tree context to preserve all
    other persisted contexts, so that a write from one panel or device does not
    erase unrelated navigation.
26. As an authenticated user, I accept last-write-wins behavior when two devices
    edit the same tree context concurrently, so that this feature can stay a
    preference store rather than become a collaborative state service.
27. As an authenticated user, I want a missing, invalid, oversized, or newer
    unsupported persisted document to fail safely to an empty tree for only the
    affected state, so that corrupt preference data cannot break the Files panel.
28. As an authenticated user, I want persisted filesystem state accessible only
    through my authenticated account, so that another user can never discover my
    paths, selections, or cached directory entries.
29. As a signed-out visitor, I want no File tree state fetched or written, so
    that persistence cannot create an anonymous or shared browser data channel.
30. As a module maintainer, I want the browser-memory and backend-persisted paths
    to use one tree snapshot model, so that create, rename, move, delete, upload,
    refresh, reveal, hydration, and ordinary navigation cannot drift into
    separate authorities.

## Implementation Decisions

### Feature ownership and persistence boundary

- `filetree-navigation-state` is the canonical feature key. This PRD replaces
  the promoted lightweight feature record as the authoritative requirement
  source.
- The File module owns the tree snapshot schema, versioning, validation,
  context identity, path transforms, reconciliation, hydration, write
  coalescing, and UI behavior.
- The host owns the existing authenticated user-preference endpoint and
  owner-scoped storage. The File UI uses that generic endpoint under a dedicated
  preference key. It does not add a File-specific persistence route or expose a
  generic host-table capability to module Python.
- No new database table or migration is warranted. The existing preference
  value is JSON and already keyed uniquely by authenticated owner and preference
  key.
- Persisted paths and directory entries are account-private state. They are not
  included in module metadata, public demos, public shares, trace payloads, or
  unauthenticated routes.

### Snapshot identity and document shape

- The durable document is explicitly versioned. Unknown future versions are not
  interpreted as the current shape.
- A context identity is the unambiguous tuple of panel location, VM name, and
  work directory. `null` and empty string remain distinct where the existing
  File location contract distinguishes them.
- Every context stores the same state categories as the current in-memory
  authority: directory entries by listed directory, expanded paths, selected
  paths, range anchor, and scroll offset.
- Transient request state is not persisted: loading flags, errors, dialogs,
  drag state, clipboard feedback, upload progress, and one-shot reveal commands
  remain mount-local.
- The persisted payload is bounded and validated before use. Planning must set a
  concrete size/entry bound and deterministic eviction rule. Eviction removes
  least-recently-used cached contexts or branches, never silently mixes contexts
  or drops the currently active context merely to satisfy the bound.

### Hydration and local authority

- The in-memory snapshot is the synchronous render and interaction authority.
  Backend reads hydrate it; backend writes replicate it. React state and the
  persisted document are not separate tree models.
- An authenticated mount fetches the preference once for hydration. A valid
  persisted context renders its cached root and expanded children and restores
  scroll without first issuing duplicate directory-list requests.
- Hydration must not overwrite interaction that occurred after the read began.
  The implementation needs an explicit dirty/revision guard for late responses.
- A context absent from the backend starts empty and follows the ordinary root
  load path. An invalid affected context is discarded without invalidating
  valid sibling contexts.
- Persisted directory entries are cached observations, not asserted filesystem
  truth. Fresh truth enters only through successful listing or action responses.

### Writes and multi-device behavior

- Persistence is best-effort, asynchronous, and coalesced. Ordinary UI behavior
  succeeds even when a preference write fails; the latest in-memory state stays
  usable and a later change may retry.
- Scroll events must not write once per event. Selection, expansion, and action
  bursts may share the same coalescing window.
- Before an update, the client preserves sibling contexts from the latest known
  document and replaces only its changed context. This prevents routine writes
  from one panel or filesystem root from erasing unrelated contexts.
- The same context uses last-write-wins across concurrent devices. There is no
  field-level CRDT, websocket synchronization, lock, or conflict dialog.
- A successful write becomes the durable state for future hydrations. A failed
  write does not roll back local UI or claim success through a destructive empty
  replacement.

### Filesystem reconciliation

- Only a successful, well-formed directory listing may reconcile absence or a
  type change. Non-2xx, permission-denied, malformed, timeout, and network
  outcomes retain prior navigation state.
- Reconciliation removes exact and descendant cache, expansion, selection, and
  anchor state when a child disappeared or changed type. Scroll falls back to
  normal browser clamping when content shrinks.
- Create, rename, move, delete, upload, refresh, and reveal update the same
  context snapshot only after their filesystem action succeeds, then schedule a
  durable write.
- Rename and move remap exact-or-descendant prefixes. Delete prunes them. Create
  and upload refresh their destination. Explicit Refresh keeps expansion and
  scroll while re-listing root and expanded paths ancestor-first.
- Collapse All is a durable user action on expansion only; loaded branch data is
  retained.

### Relationship to File workspace persistence

The host-owned File workspace and the module-owned File tree are adjacent but
separate state:

- File workspace persistence owns open ordinary-file tabs, active/preview tab,
  and file descriptors.
- File tree persistence owns sidebar expansion, selection, loaded branches, and
  scroll per panel/VM/work-directory context.
- They reuse the same generic authenticated preference mechanism but have
  separate keys and document schemas. Neither embeds or rewrites the other.

## Testing Decisions

Tests should assert observable state transitions and authenticated persistence,
not React hook structure or a particular debounce implementation.

- Extend the existing pure tree-state coverage for context isolation, snapshot
  serialization/validation, version rejection, path pruning, prefix remapping,
  successful-list reconciliation, and deterministic payload bounding.
- Test hydration behavior with the persistence client: valid cached branches
  render without duplicate list calls; a missing context follows the root-load
  path; invalid data affects only its own context; a late hydration response
  cannot overwrite newer local interaction.
- Test write behavior with a fake preference transport: rapid changes coalesce,
  one context update preserves sibling contexts, failed writes retain local
  state, and a later successful write stores the latest snapshot.
- Test filesystem outcomes at the File panel boundary: 200-empty prunes stale
  paths; permission, network, malformed, and non-2xx responses preserve them;
  successful create/rename/move/delete/upload update and persist the shared
  snapshot; failed actions do neither.
- Test owner isolation at the generic preference API boundary. One authenticated
  user's tree document must not be readable or writable by another user, and an
  unauthenticated request must not reach it.
- Test reload/cross-device semantics by creating a snapshot through one client
  instance and hydrating a fresh client instance for the same owner. A different
  owner and a different context must start from their own data.
- Keep tests local-only under the repository policy unless an existing product
  test suite is intentionally tracked. Static module build and TypeScript gates
  remain required; browser-driven UI verification remains for the user unless
  explicitly requested.

## Out of Scope

- Live synchronization of an already-mounted tree when another device writes.
- Conflict dialogs, locks, per-field merges, CRDTs, or collaborative filesystem
  navigation. Concurrent same-context edits are last-write-wins.
- Treating persisted directory listings as authoritative filesystem state or
  adding filesystem watchers/push invalidation.
- Automatically re-listing every persisted branch on every mount. Explicit
  refresh, uncached expansion, and successful filesystem actions provide fresh
  observations.
- Persisting transient dialogs, loading/error state, drag state, clipboard
  feedback, upload progress, or reveal commands.
- Unauthenticated tree persistence, sharing tree snapshots, public demo data,
  or exposing path state in trace/share payloads.
- Combining File tree navigation with the host-owned open-file workspace
  document.
- Adding a File-owned persistence table, a File-specific backend endpoint, a
  module-host preference capability, or a database migration while the existing
  authenticated preference store satisfies the requirement.
- Hardening unrelated File operation contracts, including the existing move
  route's note-pointer hazard.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3200 | Preserve per-context Files sidebar expansion, selection, loaded branch cache, and scroll through authenticated backend persistence across activity switches, refreshes, browser restarts, and devices | - | `pages/plan-3200-filetree-navigation-state.md` | This PRD | `pages/review-3200-user-preference-cas.md`; `pages/review-3200-filetree-persistence.md` | shipped; user verification pending |
