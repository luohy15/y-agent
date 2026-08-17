---
title: Todo Detail View
type: prd
project: y-agent
feature: todo-detail-view
status: active
---

# Todo Detail View

## Problem Statement

The Todo full view shows todos as a table or a kanban board. Opening one todo's
detail is a different surface entirely: the reserved `trace.md` workspace tab,
which renders the host trace view (todo metadata and inline editing, activity
history, associated notes, links, calendar events, the chat waterfall, and trace
sharing) from host-owned selected-trace state.

That split has three costs for the user:

- **Navigation leaves the list.** Opening a todo swaps the whole centre area to a
  separate tab whose relationship to the list the user was reading is invisible.
  Coming back is a tab gesture, not a "back" gesture, and nothing guarantees the
  list is still in the mode, filter, sort, page, and scroll position it was in.
- **The detail is reachable only through a reserved special tab.** `trace.md` is
  not a real file, has no place in the module the domain belongs to, and behaves
  unlike every other detail drill-down in the product.
- **The Todo module's full view cannot show a todo.** Finance already solved the
  same shape: its full view drills into Ticker Detail in place and offers an
  explicit way back. Todo has no equivalent, so the one module whose domain is
  todos cannot present a todo.

The obvious shortcut, reimplementing the trace presentation inside the Todo
module, would create a second copy of the todo detail on a different release
clock. The Todo module already carries one deliberate duplicate for the public
demo's fictional trace; a second one on the authenticated path would mean the
real todo detail diverges depending on how it was opened.

## Solution

Give the Todo full view an in-place Todo Detail viewer, following the established
Finance full-view versus Ticker Detail pattern. Selecting or opening a todo
switches the centre area from the list to that todo's detail/trace view; an
explicit back affordance returns to the list the user came from, with its view
mode, filters, sort, page, and scroll or selection context intact where
practical. The selected todo survives a reload, so refreshing lands back on the
same detail rather than the list.

The detail keeps the current trace experience: todo metadata and its permitted
edits, progress, activity history, the trace tree of chats, associated notes,
links, and calendar events, plus existing actions with unchanged permissions. It
does this by reusing **one authoritative implementation** of the todo detail
rather than a second copy inside the module.

Once the in-place viewer reaches parity and every entry point (deep links, host
navigation commands, tag navigation, and the header trace affordance) opens it,
the standalone `trace.md` tab is retired from the authenticated application and
its entry points are migrated intentionally rather than left as dead paths.

## User Stories

### Opening a todo

1. As a user reading the Todo full view in table mode, I want clicking a todo to
   open its detail in the same centre area, so that I stay in one place instead
   of switching to a separate tab.
2. As a user in kanban mode, I want opening a card to reach the same detail view
   as the table, so that the detail does not depend on how I was browsing.
3. As a user, I want the detail to open for the todo I selected and to show that
   todo's identity in its header, so that I can confirm I am looking at the right
   one.
4. As a user who opened a todo from somewhere else in the app (a tag drill-down,
   a chat's trace affordance, the header trace chip), I want to land on the same
   Todo Detail view, so that there is one place a todo detail exists.
5. As a user following a deep link to a specific todo, I want the application to
   open that todo's detail directly, so that shared or bookmarked URLs keep
   working.
6. As a user, I want opening a todo detail to work whether or not the Todo full
   view was already open, so that navigation never depends on prior UI state.

### Returning to the list

7. As a user, I want an explicit, always-visible way back from the detail to the
   Todo list, so that I never have to close a tab to resume browsing.
8. As a user, I want going back to restore the view mode (table or kanban) I was
   using, so that the list looks the way I left it.
9. As a user, I want my status filter, name filter, sort key and direction
   preserved across the detail round trip, so that I do not re-apply them each
   time.
10. As a user browsing a long list, I want my page and scroll or selection
    context preserved on return where practical, so that I can continue down the
    list I was working through.
11. As a user, I want the detail's own scroll and expansion state to be that
    view's concern, so that returning to the list is not affected by how far I
    scrolled inside a detail.

### Staying on a todo

12. As a user who reloads the page while a todo detail is open, I want to land
    back on that same detail, so that a refresh is not a navigation.
13. As a user, I want the same restoration behavior on the todo detail that
    Finance already gives the ticker drill-down, so that the two full views
    behave alike.
14. As a user who explicitly goes back to the list, I want a later reload to
    land on the list, so that restoration follows my last intent rather than the
    last todo I happened to view.

### Detail content and actions

15. As a user, I want the todo's metadata (name, status, priority, due date,
    tags, description, progress) shown in the detail, so that it remains the
    single place a todo is understood.
16. As a user, I want the todo's editable fields to stay editable with the same
    permissions as today, so that moving the view does not change what I can
    change.
17. As a user with unsaved edits, I want the existing unsaved-changes guard to
    still apply when I navigate away, so that I do not silently lose edits.
18. As a user, I want the trace tree of chats and their timing shown, so that I
    can see how the work was carried out and open the chat I care about.
19. As a user, I want associated notes, links, and calendar events listed with
    their existing open behavior, so that the detail remains the hub of a todo's
    artifacts.
20. As a user, I want the todo's activity history available in the detail, so
    that I can see how it progressed.
21. As a user, I want existing sharing actions to keep their current behavior and
    permissions, so that the migration does not widen or narrow what is
    shareable.
22. As a user on a narrow screen, I want the detail to remain usable and
    responsive, so that the todo detail works on mobile as the list does.

### Degraded and edge states

23. As a user opening a todo that no longer exists or was deleted, I want a clear
    unavailable state with a path back to the list, so that I am never stranded
    on a broken view.
24. As a user whose persisted detail selection points at a todo that has since
    disappeared, I want the view to fall back to the list rather than fail to
    render, so that a stale stored selection cannot break the surface.
25. As a user viewing a todo with no chats, no notes, and no links, I want an
    honest empty presentation rather than a loading state that never resolves.
26. As a user viewing a todo with a large trace, many notes, or long progress
    text, I want the detail to remain readable and navigable.

### Retiring the standalone tab

27. As a user, I want every existing route to a todo's trace to end up in the
    Todo Detail viewer once it is at parity, so that the old tab is not a second
    way to see the same thing.
28. As a user, I want the standalone `trace.md` tab removed from the
    authenticated application only after parity, deep links, and navigation are
    verified, so that retiring it never costs me a capability.
29. As a user with a previously persisted `trace.md` workspace tab, I want it to
    disappear or resolve into the new viewer after the cut rather than restore as
    a broken tab, so that saved workspace state stays coherent.
30. As a visitor to a public trace share, I want that page to keep working
    exactly as before, so that shared links are unaffected by an internal
    navigation change.
31. As the maintainer, I want no orphaned host commands, URL handlers, or tab
    classifications left behind after the cut, so that the retirement is a
    migration rather than an accumulation.

## Implementation Decisions

**The pattern is Finance's, and it is deliberate.** The Finance `detail` surface
holds the drill-down target in module state, persists it so a reload restores the
same drill-down, renders the drill-down view with a back affordance when set, and
renders the full view otherwise. Todo Detail adopts the same shape: a selected
todo id held by the Todo `detail` surface, persisted, with the list rendered when
it is absent. Todo differs from Finance in one way that matters: the list already
persists view mode, status filter, sort state, and history-rail collapse, so the
round trip preserves those by construction; page and scroll or selection context
are the parts that need explicit attention.

**Reuse of the authoritative detail is a hard requirement, and its seam is a
plan-phase decision.** The authenticated todo detail today is host-owned
(`TraceView` and its todo-detail, waterfall, and share parts) and is rendered by
the host under the reserved `trace.md` tab from host `selectedTraceId` state. The
`@y/host` browser contract (currently v9) exports no trace or todo-detail
component, so the module cannot render it as things stand. Copying it into the
module is explicitly rejected by this feature. The candidate seams, in the order
they should be evaluated:

1. **Export the host trace view as a versioned `@y/host` leaf** and have the Todo
   `detail` surface mount it for the selected todo. This is the smallest change
   and matches the precedent already set by `ArtifactView`, `PatchDiff`, and
   `CodeEditor`: one physical implementation, host-owned, reached by the module
   through the contract. It costs a browser-contract bump and a `min_ui`-style
   floor for the Todo module, and it leaves rendering of the todo detail on the
   host deploy clock.
2. **Move the todo detail presentation into the Todo module** and leave the host
   with the data and the public projection. This puts the presentation on the
   publish clock, which is where the module system generally wants it, but the
   public trace projection renders the same view from an injected payload, so
   this seam must keep the public page working from one implementation and is
   correspondingly larger.
3. **Keep the detail host-rendered inside the Todo full view** through a
   host-provided mount. This is only viable if the host can place its own view
   inside the module's surface without the module owning the composition; the
   existing per-detail-mount context channel carries data, not components.

The plan phase picks one and records the choice; whichever is picked, the
outcome must be that exactly one implementation of the authenticated todo detail
exists.

**Selection is module state, not a new host intent.** The artifact surfaces
receive no props, so the selected todo cannot be handed in as a prop. Existing
host navigation commands already carry a todo id to the host; the migration
retargets them at the Todo full view rather than at the reserved tab, using the
existing artifact intent or host-command channels rather than inventing a
todo-specific host state field.

**Entry points are migrated, not duplicated.** The authenticated entry points
that resolve to the todo detail today are: the `/trace/:traceId` URL route, the
`todo.openTrace` and `chat.openTrace` host commands, the shared open-todo
navigation used by the Todo panel and by tag drill-down (which lands on the
latest chat when there is one and on the todo detail otherwise), and the header
trace chip. Each must open the Todo Detail viewer after the cut. The reserved-tab
classification used for workspace restore and filtering must stop treating
`trace.md` as a live tab, and any persisted workspace entry for it must not
restore as a broken tab.

**The public trace projection keeps its own path.** The unauthenticated
`/t/:shareId` page renders the trace view read-only from an injected payload with
its own permanent tab and its own share/permission rules. Retiring the
authenticated `trace.md` tab must not change that page's behavior; if the chosen
seam moves the implementation, the public projection follows it and stays
read-only.

**Cutover is staged.** Add the in-place viewer first and verify parity, deep
links, and navigation against the existing tab; retire the tab and migrate entry
points as a second, explicit step. The Todo module ships through
`y module publish` with the previous version as the rollback target; a
host-contract change lands as a host deploy before any module version that
depends on it, per the module system's two-deploy cutover rule.

**Payload boundaries apply.** The detail consumes trace and todo payloads that
may be stale or malformed against a persisted selection, so it degrades to an
unavailable or empty state rather than throwing during render, consistent with
the module UI payload boundary rules already in force for this module.

## Testing Decisions

Test observable behavior at the surface boundary, not the internal state shape:

- **Round-trip behavior**: opening a todo renders the detail, going back renders
  the list, and the list's mode, filter, sort, and page survive the round trip.
  These are assertable through the module's own surface without a host build.
- **Restoration**: a persisted selection renders the detail on mount, an explicit
  back clears it, and a persisted selection that no longer resolves falls back to
  the list instead of throwing.
- **Degraded payloads**: stale, empty, and malformed trace/todo payloads render an
  unavailable or empty state. The module's existing payload-boundary tests are the
  prior art and the place these belong.
- **Entry-point dispatch** is host-side and unit-testable the way tag navigation
  already is: each entry point resolves to the Todo Detail viewer for the right
  todo id. Prior art is the existing host navigation dispatch tests.
- **Parity is verified by hand before the cut**, not by a snapshot test: direct and
  deep-linked opening, list-to-detail switching, back navigation, refresh
  restoration, stale/deleted todos, and a representative rich trace (many chats,
  notes, links, calendar events).
- Public trace share behavior is covered by its existing tests and must stay
  green through the cut.

## Out of Scope

- **Redesigning the todo detail.** This feature relocates and unifies an existing
  presentation; a new look for the todo detail is separate work with its own
  design phase.
- **Redesigning the Todo list.** Table and kanban modes, their filters, sorting,
  and the activity rail are unchanged apart from what the detail round trip
  requires.
- **New todo actions or permission changes.** Existing actions carry over with
  identical permissions; nothing is added, widened, or narrowed.
- **The public demo's fictional trace view.** The Todo module's demo keeps its
  module-local fictional trace presentation by the explicit todo 3158 scope
  exception; it is not the authority for authenticated traces and is not the
  duplicate this feature removes. Boundary with
  [public-module-demos](public-module-demos.md).
- **Changing the public trace share page's own contract.** Its token-scoped,
  read-only projection and share/password rules stay owned by their existing
  feature.
- **Other reserved host tabs.** `link.md`, `entity.md`, `email.md`, and the rest
  keep their current shape; only the todo/trace tab is retired here.
- **The browser and backend contract mechanism itself.** If this feature needs a
  `@y/host` addition, the versioning, loader, and rollback rules governing it stay
  owned by [module-system](module-system.md) and
  [ui-dynamic-artifacts](ui-dynamic-artifacts.md); this PRD owns only the
  requirement that one authoritative detail implementation exists.
- **A todo detail URL of its own.** Artifact detail surfaces restore as persisted
  tabs and have no dedicated route; the existing trace deep link is the only URL
  contract in scope.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3179 | In-place Todo Detail viewer in the Todo full view (Finance full-view / Ticker Detail pattern), reusing one authoritative todo-detail implementation, then retiring the standalone `trace.md` tab and migrating its entry points. Spans y-module `todo/ui` and y-agent host navigation. No design phase: the change reuses existing trace rendering and an established pattern. | - | `pages/plan-3179-todo-detail-view.md` | Seam 1: export the host `TraceView` as a versioned `@y/host` leaf (browser contract v10) instead of copying trace rendering into y-module; keep the list subtree mounted-but-hidden rather than relying on persistence alone; retiring authenticated `trace.md` is in scope for this todo, while the public `/t/:shareId` permanent tab is a non-regression boundary; staged release (host deploy A → publish module → parity → host deploy B) because `build.mjs` stamps `min_host_version` from `contract.json` | `pages/review-3179-host-traceview-export.md`, `pages/review-3179-todo-module-detail.md`, `pages/review-3179-host-entry-points.md`, `pages/review-3179-host-trace-tab-retirement.md` | shipped: host contract v10 (`8b4daae`) + todo module v10 (ui `dea4803a2a6e`) in deploy A; entry-point migration (`bcda402`) and authenticated `trace.md` retirement (`4a95123`) in deploy B. Public `/t/:shareId` and its permanent `trace.md` tab unchanged. Rollback: revert the host commits and redeploy, and/or `y module activate todo 9` (v9 predates the detail view) |
