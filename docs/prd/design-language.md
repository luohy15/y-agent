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
its design decisions are scattered across host and module source. A person
making a UI change cannot inspect the established palette, density, component
patterns, and known exceptions in one place. As a result, visually similar
controls can drift, such as the calendar all-day checkbox described in todo
3109, while the intended system remains implicit.

## Solution

Maintain a self-contained, previewable design-language page that documents the
current y-agent UI rather than proposing a replacement. It presents both
Solarized Light and Solarized Dark, the recurring layout and component
patterns, and an explicit list of observed inconsistencies. The page is a
conversation surface: Roy can open it in y-agent, preview it without a build,
and request iterative visual edits before it becomes the reference for later
UI work.

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
7. As a UI contributor, I want exceptions and inconsistent variants called out
   rather than normalized away, so that the document reveals maintenance work
   instead of hiding it.
8. As Roy, I want to refine the document in a file preview loop, so that it
   becomes a useful visual reference through direct feedback rather than an
   unreviewed specification.

## Implementation Decisions

- The durable feature key is `design-language`. It is adjacent to, but does not
  replace, the `theming` feature record. Theming owns palette selection,
  persistence, and the host-to-module token contract; this feature owns the
  human-facing reference for the UI patterns that consume those tokens.
- The reference is a single static HTML file under `pages/`, with inline CSS
  and no build-time or application dependency. Its metadata identifies this
  PRD, todo, project, and draft/approval status.
- The document represents the current UI. It may recommend no hidden
  normalization where source patterns conflict. Each observed variant is
  labelled as an inconsistency.
- Solarized Light and Solarized Dark are the only documented themes. The base
  palette's semantic color values are stable across the two polarities, while
  the eight neutral roles invert as implemented by the host.
- The initial page uses a compact desktop reference-sheet layout and an inline
  polarity switch. This is documentation presentation only, not a proposal for
  application navigation or a reusable UI library.
- Checkboxes use one custom, token-aware visual primitive. Browser-native
  checkbox appearance is not permitted: the 14px square has a 3px radius, a
  muted neutral border and canvas fill when unchecked, a blue fill with an
  inset canvas mark when checked, and a blue focus halo. Calendar's styled
  checkbox is directionally correct but should converge on this exact shape;
  host trace-sharing and routine controls must adopt it when changed.
- All interface corners use one 4px radius. Floating surfaces (menus, popovers,
  and dialogs) use a single `shadow-float` elevation token; ordinary panels,
  cards, rows, and controls use borders without shadows. Scrollbars follow the
  host FileViewer pattern: thin 8px tracks in the canvas color, muted neutral
  thumbs, and a muted-border hover state.
- Text inputs use a quieter base02/base03 blended fill and a translucent base01
  border rather than a fully opaque neutral outline. Hover increases the
  neutral border contrast. Focus restores the canvas fill, changes the border
  to blue, and adds a restrained blue 2px halo.

## Testing Decisions

- Open the HTML through the y-agent FileViewer Preview and verify it renders
  without local assets, app imports, or a build step.
- Verify the polarity switch makes both documented neutral palettes legible and
  preserves the semantic accent samples.
- Compare every documented token and component claim against current host or
  module source before adding it to the reference.
- Treat a documented inconsistency as correct only when the page shows the
  competing current variants and identifies why it is not a canonical pattern.

## Out of Scope

- Rebuilding y-agent's UI around a component library or applying a global
  visual restyle.
- Changing source components merely to make the reference page look uniform.
- Reintroducing plain light or dark themes removed by todo 3106.
- Defining runtime theme persistence, public-share theme rules, or the module
  token API. Those remain the theming feature's responsibility.
- Implementing fixes for items listed as inconsistencies. Each needs its own
  delivery todo.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3112 | Current UI design-language reference | `pages/design-3112.html` | - | - | - | design draft |
