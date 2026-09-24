# `cli/src/yagent/sdk/` — artifact build-time SDK (todo 2412)

The recipe `y module publish` runs esbuild/Tailwind against when compiling a
user's `.tsx` artifact source into a loadable bundle. Lifted from the
validated spike in `y-agent-ui-spike-2412`'s `spike-2412/sdk/` — see
`pages/decision-2412-runtime-contract.md` for the evidence.

This is the single physical copy (decision D6, ruled in
`pages/review-2412-web-host-sdk.md`): the CLI's editable install
(`uv tool install --force -e ./cli`) resolves this directory relative to the
installed module, so the files must live under `cli/src/yagent/` rather than
under `web/`. The web host reads only `contract.json` from here, at build
time, via a relative import from `web/src/host/contract.ts`
(`../../../cli/src/yagent/sdk/contract.json`) — `shims/*.cjs` and
`theme.css` have no consumer on the web side; they are pure build inputs for
`y module publish` on the VM.

| Path | Role |
|------|------|
| `contract.json` | Single source of truth (decision D6) for the externals list and the `@y/host` contract version. Read by the web host at build time (`web/src/host/contract.ts`) and by `y module publish`'s esbuild `alias` config; a `min_host_version` mismatch against this value is what S6's loader gates on. |
| `shims/*.cjs` | One CommonJS shim per external in `contract.json`. esbuild `alias` maps each bare specifier onto its shim, so the built artifact bundle has zero import statements (decision D1) — required because a `blob:` module has no base URL to resolve bare specifiers against. Each shim reads `globalThis.__Y_HOST__`, populated at app startup by `web/src/host/registry.ts`. |
| `theme.css` | `@theme reference` block registering the host's `sol-*` color names plus host-resolved `--radius` and `--shadow-float` for Tailwind, without emitting a `:root` value block (decision D3). Utilities emit `var(...)` and inherit whatever the host set at runtime. Host-owned control classes `.y-check` / `.y-field` live in host `web/src/style.css` (append-only CSS contract; not redeclared here) and are applied by class name from module TSX. An artifact's CSS entry imports this alongside `tailwindcss/theme.css` (see the spike's `artifact/demo.css` for the exact three-line recipe). |
| `y-host.d.ts` | Type declarations for `@y/host`, handed to artifact authors, plus the artifact module shape (`panel` + optional `detail` + optional `shell` + optional `demo`, see `pages/decision-2412-module-shape.md`, `docs/prd/module-system.md`, and `docs/prd/public-module-demos.md`). Must match `web/src/host/sdk.ts`'s actual export list — the registry is what exists at runtime, so a d.ts name with no runtime binding fails silently (esbuild does not typecheck) until an artifact calls it. |
| `templates/starter.{tsx,json}` | Scaffold written by `y module create`. The `.tsx` is the canonical example of the module shape: `export const panel` (required), `export const detail` (optional), `export const shell` (optional). Public-showcase modules also export `demo`. |
| `package.json` | Also pins the Node-side renderer deps (`react`, `react-dom`, `react-markdown`, `remark-gfm`) that a module's Node driver script runs with real `node_modules` (not the browser's alias-to-shim path) — see *Runtime dependencies* below. |

If `contract.json`'s values ever diverge from what `web/src/host/registry.ts`
actually registers, that is the D6 single-source-of-truth invariant breaking
— fix by pointing the drifted side at this file rather than hand-copying
values.

## Runtime dependencies

`package.json` pins `react`, `react-dom`, `react-markdown`, `remark-gfm` to the
exact versions in `web/package-lock.json` (todo 3371). A CLI Node-side markdown
export driver, e.g. `code/y-module/file/scripts/export-node.mjs`, runs with
these as real installed packages via `NODE_PATH=.sdk/node_modules`, since the
browser bundle's esbuild `alias` → `shims/*.cjs` substitution only applies to
`y module publish`'s browser build. **Lockstep rule**: when
`web/package-lock.json` bumps the pinned version of any of these four
packages, bump the matching entry in this `package.json` in the same change.
`_ensure_npm_install` in `cli/src/yagent/commands/module/_sdk.py` checks for
`node_modules/react-markdown/package.json` (in addition to the `tailwindcss` /
`esbuild` binaries) so an existing `.sdk` install picks up these deps.

## Surfaces

A module UI declares up to three production surfaces, and `module.json`'s
`surfaces` list is what the published version records as `ui_surfaces`. Public
showcase modules also export a fourth entrypoint used only by `/demo`:

| Export | Slot | Notes |
|--------|------|-------|
| `panel` | ~280px sidebar column | Required. Introspected from the bundle; a module always gets a sidebar entry. |
| `detail` | full-width centre tab, opened from the panel header | Optional. Introspected from the bundle; unmounted when the tab is closed. |
| `shell` | the persistent centre column (the live chat area) | Optional. **Enforced from `ui_surfaces`**, because the host must pick the claimant before fetching any bundle. At most one module may claim it (lowest slug among enabled claimants wins); when nobody claims it the host renders its own fallback. |
| `demo` | public `/demo` shell surface | Optional for ordinary production loading; **required** when the host loads the public bundle for a showcase demo. Introspected from the bundle; never substituted by `panel` / `detail` / `shell`. Publish `ui_public: true` separately to opt the version's UI bytes into anonymous delivery. |

None of the four receives props. Host state reaches a surface through
`useArtifactIntent`, and a surface asks the host to act through `runHostCommand`.
A `shell` module owns everything that decides what the centre column looks like;
the host keeps the leaves whose dependencies are measured in megabytes
(`ArtifactView`, `PatchDiff`, `ImageLightbox`, `CodeEditor`, `exportElementToPng`)
plus the visibility-gated chat image leaves (`ChatImageScope`, `ChatImage`,
`ChatMessageImages`; contract v15) and exports them on `@y/host`. See `docs/prd/module-system.md`, *The `shell`
surface and the renderer seam*, before bundling anything heavy into a module.
Public demo composition and isolation rules live in
`docs/prd/public-module-demos.md`.

## Multi-file module UI

The UI entry point is `code/y-module/<slug>/ui/index.tsx`. Once it gets
too large to maintain, split it into sibling modules under `ui/` and import them
with relative specifiers (`./parts/foo`). `build.mjs` bundles relative imports
normally (esbuild `bundle: true`), so the entry still only needs to re-export the
surfaces (`panel`, optional `detail`, optional `shell`, optional `demo`).

`build.mjs` scans `ui/**/*.{tsx,ts}` for Tailwind classes and includes every
`.tsx` and `.ts` file in that tree in `source_digest`, so edits to a sibling file
change the manifest as well as the output bundle.

When `code/y-module/shared/ui/` exists, the same Tailwind scan and
`source_digest` also cover `shared/ui/**/*.{tsx,ts}`. That directory is for
value-agnostic leaf UI imported by more than one module (for example a copy
button). It is not the `common` module: `common` vendors Python and shared
tables into an API zip. Shared UI is compile-time source only; esbuild still
emits a self-contained per-module bundle, and there is no separately published
shared UI runtime.

## @y/design (todo 3657)

`@y/design` is a build-time input, not a host external. `package.json` pins
`file:./vendor/y-design-0.2.0.tgz`, which ships inside this SDK directory so the
same relative path resolves after `ensure_sdk` copies the tree to
`y-module/.sdk`. The host pins that same tarball. `build.mjs` aliases the
package root to a staged copy of the ESM entry (`.cache/y-design/`, rebuilt from
`node_modules` on every build) so a module under `y-module` does not look the
package up from its own tree and the blob path comment is not the bare
specifier. The library is inlined; React stays on the existing shim. The root
entry is the only one allowed. Do not add `@y/design` to `contract.json`
externals.

Tailwind `@source` points at those staged `*.js` files, and only when the
module UI or `shared/ui` imports `@y/design`. It does not scan `node_modules`.
`source(none)`, `theme(reference)`, and no preflight stay in place. The same
import check feeds `source_digest`, which then also covers the package version,
`package.json`, and the `node_modules` dist JS bytes, keyed by basename so the
digest has no machine path. Modules that do not import it keep the previous
digest inputs. `ensure_sdk` reinstalls when the installed version differs from
the tarball version, because `node_modules` is kept across SDK refreshes.

No `contract.json` change is needed for this. It is a build-recipe change, not
a change to what the host provides.
