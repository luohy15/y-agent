---
title: Bot Config Detail Modal
type: prd
project: y-agent
feature: bot-config-detail-modal
status: active
---

# Bot Config Detail Modal

## Problem Statement

In the Bot viewer Config tab, opening a bot's full editor used to expand an
inline table row. That layout made the table hard to scan, mixed selection state
with row rendering, and did not match the repository's other dialog patterns.
After the detail moved into a modal, a second problem appeared: detail-only
fields such as Weight, Max Tokens, and API Path sometimes rendered empty or
stale. The form seeded once from incomplete list data or from a never-invalidated
detail cache, so a cold open or a post-save reopen could show values that were
not the bot's saved config.

## Solution

Config-tab detail editing opens in a single modal dialog instead of an expanded
table row. The modal reuses the existing detail editor behavior (fetch full
config, edit/save, enable/disable, delete non-default bots, show today's model
usage) and supports standard close interactions. Inside that modal, the
editable form mounts only after the authoritative per-bot config payload has
loaded, and every successful write invalidates that detail cache so the next
open always reflects the saved values.

## User Stories

1. As an admin, I want clicking a Config-tab bot row to open that bot's detail
   editor in a modal, so that the table stays one row per bot while I edit.
2. As an admin, I want the modal title to include the bot name, so that I always
   know which config I am editing.
3. As an admin, I want the modal to expose the same detail content as before
   (fields, enable/disable, delete for non-default bots, today's model usage,
   Save), so that presentation changes do not remove capabilities.
4. As an admin, I want an explicit close control on the modal, so that I can
   dismiss it deliberately.
5. As an admin, I want clicking the dim backdrop to close the modal, so that
   dismissal matches other dialogs in the app.
6. As an admin, I want pressing Escape to close the open bot-detail modal, so
   that keyboard dismissal works without a mouse.
7. As an admin, I want Escape while the detail modal is open not to close an
   unrelated create-bot form, so that each overlay owns its own dismissal.
8. As an admin, I want clicking inside the dialog panel not to dismiss it, so
   that editing is not interrupted by accidental overlay handling.
9. As an admin, I want the status-dot enabled toggle on a Config row to remain a
   quick in-place action that does not open the modal, so that I can flip
   enabled state without entering the editor.
10. As an admin, I want the modal to stay open after a successful Save, so that
    I can keep editing or verify the saved values without reopening.
11. As an admin, I want a successful Delete to close the modal, so that the UI
    does not leave me on a deleted bot's editor.
12. As an admin, I want closing via close button, backdrop, or Escape to discard
    unsaved local edits without a confirmation prompt, so that dismissal stays
    as lightweight as the previous inline panel.
13. As an admin, I want the modal body to scroll when content is tall, so that
    the dialog remains usable on short viewports without overflowing the screen.
14. As an admin, I want the dialog to remain usable on narrow screens with
    horizontal margin, so that the editor is not clipped on small widths.
15. As an admin, I want the dialog to expose standard accessibility semantics
    (`role="dialog"`, `aria-modal`, labelled title), so that assistive tech can
    treat it as a modal.
16. As an admin, I want every open of the detail modal to show the opened bot's
    saved config for all editable fields, so that I never act on empty or stale
    values.
17. As an admin, I want Weight to reflect the saved `route_weight` on cold open
    and after a prior save of that bot, so that routing weight edits are
    trustworthy.
18. As an admin, I want Max Tokens and API Path to populate from the full config
    even when the list payload omits those fields, so that detail-only fields
    are never left blank after a cold open.
19. As an admin, I want a brief loading state in the modal body while the full
    config is fetching, so that the form never seeds from incomplete list data.
20. As an admin, I want a successful Save or enable/disable toggle to refresh the
    per-bot config cache as well as the bot list, so that reopening the same bot
    shows the just-written values.
21. As an admin, I want the form not to clobber in-progress edits when background
    list or usage revalidation occurs, so that typing is not overwritten mid-
    edit.
22. As a developer, I want focused interaction tests for open, dialog semantics,
    inside-click persistence, each close path, and status-dot isolation, so that
    the modal contract does not regress.
23. As a developer, I want focused tests that cold-open seeds detail-only fields
    from the config endpoint and that save invalidates the config detail cache,
    so that the authoritative-load contract stays covered.

## Implementation Decisions

### Modal interaction (todo 2865)

- Replace expansion-oriented selection state with a selected-bot/config name.
  Render exactly one detail modal outside the table. The Config table body is
  one row per bot; no expanded detail row or colspan remains.
- The modal wrapper owns presentation and dismissal. The existing detail editor
  owns data fetching and save / enable / disable / delete / usage behavior.
- Modal conventions follow existing repository dialogs: full-screen overlay at
  the common stacking level, dim backdrop, bounded max width and max height,
  internal scrolling, header close control, `role="dialog"`, `aria-modal`,
  labelled title with the bot name, stop propagation on the panel, Escape
  listener installed only while open.
- Escape scoping is local to the bot-detail modal and must not share an
  ambiguous global branch with the create-bot form overlay.
- After save, revalidate the bot list and leave the modal open. After successful
  delete, close the detail surface.
- No shared modal framework and no focus trapping in this feature. Unsaved-
  change confirmation is intentionally absent, matching the previous inline
  dismiss behavior.
- The Config-row status-dot keeps independent click handling with propagation
  stopped so it never opens the modal.

### Authoritative config load and cache invalidation (todo 2868)

Two client defects caused intermittent wrong fields:

1. Form state was seeded once from `detail || bot` via mount-time local state.
   The list payload is a partial view of a bot config (it omits some detail-only
   fields). On a cold open the first paint therefore seeded incomplete values
   and never resynced when the full detail arrived.
2. Successful writes revalidated only the bot list cache key. The per-bot
   config detail key retained the pre-save payload, so a warm reopen after Save
   showed stale Weight and other fields.

Settled contract:

- The list endpoint remains a summary payload for the table. The detail modal
  treats the per-bot config endpoint as the single authoritative source for
  form seeding. Do not expand the list payload solely to paper over client
  seeding bugs.
- Split the detail surface into an outer gate and an inner form. The outer gate
  fetches the full config for the selected name. While that detail is not yet
  present, render a small loading state inside the modal body. Mount the
  editable form only after the complete detail is available so mount-time field
  state seeds from the full payload.
- Never seed editable fields from the list-row fallback once the modal path is
  in use. Detail-only fields (including max tokens, custom API path, and route
  weight) always come from the config detail response.
- On successful save and enable/disable, invalidate/revalidate the per-bot
  config detail cache key in addition to the existing list revalidation. Delete
  continues to close the modal; list revalidation remains required.
- Prefer the load-gate over a naive "resync all fields whenever detail changes"
  effect. An unconditional resync would clobber in-progress edits on background
  revalidation; the gate avoids that class of bug without a fragile dirty guard.
- A brief loading state on cold open is acceptable. Flash-free open with list
  seeding plus guarded resync is an explicit alternative that was rejected for
  this feature.

### Boundaries

- Adjacent but distinct from [bot-routing](bot-routing.md): routing owns how
  dispatch chooses among bot configs (tiers, filters, weights). This PRD owns
  how an admin opens and edits a single bot config in the Bot viewer UI, and how
  that editor loads/refreshes authoritative field values.
- Adjacent but distinct from [bot-usage](bot-usage.md): usage owns spend and
  subscription visibility. The detail modal may display today's model usage for
  the opened bot, but usage analytics themselves are out of this PRD's scope.

## Testing Decisions

- Prefer behavior tests over implementation-structure assertions: open from a
  Config row, assert one dialog with the bot name, assert close paths, assert
  status-dot isolation, assert field values after cold open and after save +
  reopen.
- Keep coverage in the focused Bot viewer config-modal test suite with mocked
  list and config endpoints so cold vs warm cache conditions are deterministic.
- Required regression cases for the load contract:
  - Cold open: list payload lacks or differs on detail-only fields; after the
    config response resolves, Weight / Max Tokens / API Path match the config
    payload, not the list fallback.
  - Write path: after editing Weight and saving, the config detail cache is
    invalidated/refetched; reopening the same bot shows the new value.
- Frontend production build must stay green for the Bot viewer change set.
- Runtime smoke (Playwright against a running viewer with seeded list/config
  fixtures) is the preferred way to confirm cold-open and post-save-reopen
  field values when a delivery needs visual evidence.

## Out of Scope

- Shared modal component extraction across the repository.
- Focus trapping or unsaved-change confirmation dialogs.
- Redesigning the New bot create form, or changing its fields/layout.
- Changing bot-config API request/response shapes, validation rules, or
  server-side save/delete semantics.
- Expanding `/api/bot/list` with detail-only fields to avoid client gating.
- Bot dispatch / tier routing policy (see bot-routing).
- Bot usage analytics and subscription limit windows (see bot-usage).
- Opportunistic cleanup of orphan presentation attributes left after the inline
  expansion removal, unless a delivery chooses to include it.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 2865 | Config-tab detail opens in a modal with standard close interactions; row status-dot stays independent | - | `pages/plan-2865-bot-config-detail-modal.md` | - | `pages/review-2865-bot-config-modal.md` | shipped |
| 2868 | Modal form seeds only from loaded config detail; save/toggle invalidates config cache so Weight and other fields never show stale/empty values | - | `pages/plan-2868-bot-config-modal-weight-load.md` | - | `pages/review-2868-bot-config-modal-weight-load.md` | shipped |
