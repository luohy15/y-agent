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
- The reference is a single static HTML file under `pages/`
  (`pages/design-3112.html`), with inline CSS and no build-time or application
  dependency. Its metadata identifies this PRD, project, and design status.
  The filename remains todo-oriented (3112) while the page functions as the
  living visual reference; later control deliveries update it in place rather
  than spawning a parallel design file.
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
  `.y-check` and `.y-field`, plus theme keys `--radius` and `--shadow-float`,
  are append-only and must never be renamed while older module versions stay
  rollback-reachable. They are independent of the `@y/host` browser contract
  version.
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
- **Delivery order (D8).** y-agent (host CSS + SDK `theme.css`) lands and merges
  first so the editable CLI install resolves the updated SDK; only then do
  y-module source changes merge and modules republish. Every module is
  republished when the SDK tokens change, including modules whose TSX is
  unchanged, because the CSS every bundle emits depends on those tokens.

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

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3112 | Current UI design-language reference | `pages/design-3112.html` | - | - | - | approved |
| 3115 | Converge host and module controls on the design language | `pages/design-3112.html` | `pages/plan-3115-design-language-convergence.md` | - | `pages/review-3115-host-design-language-convergence.md`, `pages/review-3115-module-design-language-convergence.md` | reviewed |
