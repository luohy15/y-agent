---
title: Design Language
type: prd
project: y-agent
feature: design-language
status: active
---

# Design Language

## Problem Statement

The y-agent interface has a real, recognizable Solarized visual foundation, but
its design decisions were scattered across host and module source. A person
making a UI change could not inspect the established palette, density, component
patterns, and exceptions in one place. Visually similar controls drifted (for
example the calendar all-day checkbox in todo 3109) while the intended system
stayed implicit.

## Solution

Maintain a self-contained, previewable design-language page that documents the
y-agent UI and serves as the approved visual reference for host and module work.
It presents both Solarized Light and Solarized Dark, the recurring layout and
component patterns, and the settled control conventions (radius, elevation,
checkbox, input). The page is a conversation surface: Roy can open it in
y-agent, preview it without a build, and request iterative visual edits. Todo
3115 applied those conventions in source; this PRD records the durable
decisions and the additive host→module CSS contract.

## User Stories

1. As Roy, I want one previewable document for y-agent's current visual
   language, so that I can assess the system without starting the application.
2. As Roy, I want to inspect Solarized Light and Solarized Dark together, so
   that a visual decision works across the only supported polarities.
3. As a UI contributor, I want the exact in-use color roles and Solarized token
   values documented, so that new work uses host-provided tokens rather than
   inventing a parallel palette.
4. As a UI contributor, I want the prevalent typography scale and monospace
   metadata treatment shown in context, so that information density remains
   compatible with the app.
5. As a UI contributor, I want the recurring spacing, border, radius, and
   elevation treatments shown, so that panels and controls fit their
   surroundings.
6. As a UI contributor, I want examples of buttons, inputs, checkboxes, tabs,
   tables, list rows, panels, and tags, so that I can choose a proven pattern
   before writing UI.
7. As a UI contributor, I want settled control conventions and deliberate
   exceptions named explicitly, so that new work reuses the host classes and
   tokens instead of inventing parallel treatments.
8. As Roy, I want to refine the document in a file preview loop, so that it
   becomes a useful visual reference through direct feedback rather than an
   unreviewed specification.

## Implementation Decisions

- The durable feature key is `design-language`. It is adjacent to, but does not
  replace, the `theming` feature record. Theming owns palette selection,
  persistence, and the host-to-module color-token contract; this feature owns
  the human-facing reference and the control-level CSS contract (radius,
  elevation, checkbox, field) that consumes those tokens.
- The reference is a single static HTML file, `docs/prd/design-language.html`,
  living next to this PRD in the y-agent repo (moved from `pages/design-3112.html`
  in todo 3115; that path is now a short pointer stub kept for historical note
  associations), with inline CSS and no build-time or application dependency.
  Its metadata identifies this PRD, project, and design status. The filename is
  stable and non-todo-oriented while the page functions as the living visual
  reference; later control deliveries update it in place rather than spawning a
  parallel design file.
- Solarized Light and Solarized Dark are the only documented themes. The base
  palette's semantic color values are stable across the two polarities, while
  the eight neutral roles invert as implemented by the host.
- The page uses a compact desktop reference-sheet layout and an inline polarity
  switch. This is documentation presentation only, not a proposal for
  application navigation or a reusable React component library.
- **Radius (D1 / D2).** Host `web/src/style.css` declares `@theme { --radius:
  4px; }`; SDK `cli/src/yagent/sdk/theme.css` declares the same key under
  `@theme reference` so bare `rounded` resolves to `var(--radius)` on the host
  and `var(--radius, 4px)` in module bundles. 4px is absolute on purpose (root
  font is 110%, so `0.25rem` would be 4.4px). Sized radius utilities
  (`rounded-sm` / `md` / `lg` / `xs`) are not used. `rounded-full` survives for
  genuinely round objects: status dots, chart legend swatches, avatars/initials,
  the routine toggle track and knob, progress bars and tracks, circular icon
  buttons and FABs, and count pills.
- **Floating elevation (D3 / D4).** Host defines
  `--sol-shadow-float` per polarity and `@theme { --shadow-float:
  var(--sol-shadow-float); }` so the utility flips at runtime; a plain
  `@theme { --shadow-float: <literal> }` was rejected because Tailwind inlines
  shadow literals at build time. Role, not legacy class name, decides elevation:
  menus, dropdowns, popovers, tooltips, dialogs, mobile drawers, toasts, and
  FABs use `shadow-float`; everything else loses its shadow. Deliberate
  exceptions: `ImageLightbox` keeps its black-scrim `shadow-lg shadow-black/50`,
  and `chat/ui/sources-sidebar.tsx` keeps `sm:shadow-none` next to
  `shadow-float`.
- **Host-owned control classes (D5).** Checkbox and input treatments ship as
  two host CSS classes, `.y-check` and `.y-field`, in `web/src/style.css`
  inside `@layer components` so ordinary utilities can still override them per
  site. Host and module UI both apply them. Rejected alternatives: repeating a
  long `color-mix(...)` utility string across dozens of sites, and exporting
  React primitives on `@y/host` (browser-contract bump plus republish for every
  tweak). **This is an additive host→module CSS contract**: the class names
  `.y-check` and `.y-field`, plus theme keys `--radius`, `--shadow-float`,
  `--font-sans`, and `--font-mono`, are append-only and must never be renamed
  while older module versions stay rollback-reachable. They are independent of
  the `@y/host` browser contract version.
- **Typography roles (D9 / todo 3236).** App UI keeps a mono-everywhere texture:
  the body uses `font-mono`, and ordinary prose inherits it. Host `@theme` owns
  `--font-sans` / `--font-mono`. Preference order (zero payload; absent names are
  skipped): locally installed Adobe Source faces first (`Source Code Pro` on
  mono; `Source Sans 3` then legacy `Source Sans Pro` on sans), then the usual
  platform Latin faces, then an explicit Simplified Chinese chain with
  `Source Han Sans SC` / `Source Han Sans CN` ahead of `Microsoft YaHei UI` /
  `Microsoft YaHei`, followed by `PingFang SC`, `Hiragino Sans GB`,
  `Noto Sans CJK SC`, `Noto Sans SC`, then the generic family. Emoji faces stay
  on the sans stack. SDK `theme.css` mirrors both stacks under
  `@theme reference` so independently built module utilities keep a valid
  fallback. CodeMirror consumes `var(--font-mono)` and must not keep a divergent
  hard-coded family list. Host `:root` also sets
  `--diffs-font-family: var(--font-mono)` so `@pierre/diffs` PatchDiff chrome
  (DiffViewer / HostMessageView) prefers the host mono contract over the
  package's Latin-only `--diffs-font-fallback`; keep that bridge on any
  `@pierre/diffs` upgrade. A proportional Han face inside a mono run is
  deliberate: glyph coverage beats Chinese column alignment. Strategy: system /
  already-installed fonts only (no `@font-face`, no remote font CDN, no bundled
  CJK payload, no per-component Chinese overrides, no runtime OS detection).
  `html lang="en"` stays; Windows intermediate weights (500/600) may synthesize.
  Visual comparison: `pages/design-3236.html` (strategy A). Role detail:
  `pages/decision-3236-typography-roles.md`.
- **Checkbox (D6).** Spec for `.y-check`: `appearance:none`, 14px square,
  `border-radius:3px` (documented exception to the 4px radius token), 1px
  `color-mix(base01 40%)` border on a `base03` fill; hover raises the border to
  `base01`; `:checked` turns border and fill blue with
  `inset 0 0 0 3px base03`; `:focus-visible` draws a 2px blue outline at
  `outline-offset:2px` (closes the checked-focus gap from todo 3109);
  disabled is `opacity:.55; cursor:not-allowed`. Browser-native checkbox
  appearance is not permitted. The low-contrast unchecked hairline is accepted
  as designed.
- **Input (D7).** Spec for `.y-field`: fill
  `color-mix(base02 62%, base03)`, border `color-mix(base01 48%, transparent)`,
  `outline:none`; hover (`:not(:disabled)`) raises the border to 70%; focus
  border `sol-blue`, fill back to `base03`, and
  `box-shadow: 0 0 0 2px color-mix(blue 18%)`. The class owns fill, border, and
  focus only; size, padding, width, and font stay per-site utilities. Applies to
  `input` / `textarea` / `select` that previously used the
  `bg-sol-base02 border border-sol-base01 … focus:border-sol-blue` pattern.
- **Sidebar record actions (todo 3852).** A module left-sidebar record row does not carry secondary inline action buttons. Those actions live in one shared row menu (`y-module/shared/ui/row-menu.tsx`): mouse right-click, a 500ms touch hold (cancelled by movement, scroll, pointer up/cancel, or unmount), the Context Menu key, and Shift+F10. The menu is keyboard-operable and returns focus to the row. Primary row navigation, metadata badges, and form or header controls stay inline. Touch hold is the mobile equivalent; there is no extra mobile overflow control. Affected action bundles: `module`, `email`, `link` (sidebar variant only; the RSS detail surface keeps inline link controls), `reminder`, `routine`, and `english` (unknown-word list). Email tag editing stays available from that row menu (`Edit tags`) in a focus-managed dialog, not as a second line on the row. Out of the action convention: chat, todo, file, note, and rss menus that already existed, plus their metadata badges; centre-detail actions; public lists; host runtime and the module contract.
- **Single-line sidebar rows (todo 3852).** Every textual record row in a module left sidebar is one non-wrapping line: the title truncates, secondary metadata is compact and bounded, and essential state stays visible (not tooltip-only). Chat applies this only on the left; its right layout stays stacked. Todo is the exception: left, right, and centre Todo rows stay fully displayed on the stacked layout (name, status, priority, due date, timestamp, and wakeup or release indicators), not one truncated line. Email shows sender, subject, tag count, and date on that line. Photo stays a thumbnail grid. Summary blocks, headings, forms, and scan chips are not record rows. Layout bundles: `chat`, `module`, `email`, `routine`, `english`, `note`, `rss`, `mcp`, `finance`.
- **Delivery order (D8).** y-agent (host CSS + SDK `theme.css`) lands and merges
  first so the editable CLI install resolves the updated SDK; only then do
  y-module source changes merge and modules republish when a module must pick up
  a new inlined fallback or a TSX class change. For `--font-*` specifically,
  published module CSS emits `font-family: var(--font-mono, <fallback>)` (and
  the same pattern for sans), so a host token update retints live modules
  without republish; republish only refreshes the unused fallback string or
  ships role-audit class edits.

### Analytics surfaces (todo 4152)

These reusable rules first apply to Bot Usage Live. They reuse D1–D9 and the
host mono stack; they do not restyle the shell, other modules, or `@y/design`.
The reference page's bordered sample cards are documentation chrome, not a
requirement to nest cards inside an existing application panel.

- **One canvas, hairline sections (D10).** Analytics sections sit on `base03`
  with one `border-t border-sol-base02 pt-3` separator and 16px gaps. Charts,
  balances and limit rows have no individual card fill, enclosing border or
  elevation. Floating controls retain D3/D4.
- **Section header (D11).** Use `text-xs font-medium uppercase tracking-wide
  text-sol-base1`, with optional right-aligned `text-[11px]` metadata or a quiet
  control. This replaces Bot Usage's one-off 11px/600 header.
- **Four type roles (D12).** Metadata uses `text-[11px]`, body and table rows
  `text-xs`, inputs `text-sm`, and numeric emphasis `text-base`. At the host's
  110% root these are 11 / 13.2 / 15.4 / 17.6px, not new pixel tokens. Use 400
  for normal text, 500 for headers and small labels, 600 for numeric emphasis;
  no 700. Figures use `tabular-nums`. Chart ticks (10px) and donut keys (9px)
  are deliberate chart-mark exceptions, not smaller UI labels.
- **Numeric emphasis (D13).** Balance amounts and donut totals share
  `text-base font-semibold tabular-nums text-sol-base1`. Inline and table
  figures stay `text-xs`; comparable values use the same size and weight.
  Reference-sheet headings are not application KPI sizes.
- **Color jobs (D14).** Outside charts, blue denotes selection or primary
  action; status accents carry text or a titled dot, never decorative provider
  chips. A quiet track switch needs no saturated fill. Limit tracks use
  `base0` below 60%, yellow at 60% and orange at 80%, so green means freshness
  rather than ordinary consumption on the same row. Inside charts and legends,
  Bot's shared categorical order is blue, cyan, violet, magenta, orange, green,
  yellow, red. This is an explicit reuse of existing accents, not a claim that
  status and category palettes are disjoint. Donut and Over-time use the same
  order; labels, tooltips and tables carry identity. Known limitation: this
  Solarized order fails adjacent-pair separation validation (blue/cyan normal
  ΔE 12.4; green/yellow deutan 1.5). It is not colorblind-safe; no new palette
  is introduced by this refit.
- **Narrow analytics order (D15).** Order by the page's question before account
  status. Below the 720px container width, Bot Live puts Model share before
  Account balances, Subscription limits, Today by hour and Models. Balances
  always precede limits. At 720px and above the donut stays right, with balances,
  limits and hourly activity left, then the full-width table. Controls must
  remain reachable at 320px and reset text must not truncate.

The Models table keeps caller-owned sorting, keyboard-reachable headers with
`aria-sort`, right-aligned tabular figures, scrolling and sticky totals. These
are `@y/design` table semantics, not a component migration: its current
0.65rem body / 0.55rem header defaults are smaller than this page's roles and
appended classes cannot reliably override them. Bot keeps its hand-rolled table,
with Model / % / Tokens / Cost always visible, Requests / Sessions / Turns /
Avg / Input / Output revealed at 560px, and Cache (cr/rd) / Cache Hit at 700px
(container widths); totals mirror the same reveals.

## Testing Decisions

- Open the HTML through the y-agent FileViewer Preview and verify it renders
  without local assets, app imports, or a build step.
- Verify the polarity switch makes both documented neutral palettes legible and
  preserves the semantic accent samples.
- Compare every documented token and component claim against current host or
  module source before adding it to the reference.
- For control-convergence deliveries: static gates only by default
  (`npm run build`, standalone module `build.mjs`, grep invariants for radius /
  elevation / `y-check` / `y-field`). Browser UI inspection is opt-in.

## Out of Scope

- Rebuilding y-agent's UI around a component library or applying a global
  visual restyle beyond the settled control conventions.
- Reintroducing plain light or dark themes removed by todo 3106.
- Defining runtime theme persistence, public-share theme rules, or the module
  color-token API. Those remain the theming feature's responsibility.
- Native `<select>` appearance, `type="radio"`, and `type="range"`: no design
  treatment is specified; they keep browser-native chrome.
- CodeMirror radii in `codeEditorTheme.ts`, standalone export HTML in
  `utils/markdownExport.tsx`, and 2px `.diff-del` / `.diff-ins` chips (not app
  chrome).
- Publishing or deploying module versions (delivery step owned by the
  coordinator after docs land).
