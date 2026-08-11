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
| `y-host.d.ts` | Type declarations for `@y/host`, handed to artifact authors, plus the artifact module shape (`panel` + optional `detail` + optional `shell`, see `pages/decision-2412-module-shape.md` and `docs/prd/module-system.md`). Must match `web/src/host/sdk.ts`'s actual export list — the registry is what exists at runtime, so a d.ts name with no runtime binding fails silently (esbuild does not typecheck) until an artifact calls it. |
| `templates/starter.{tsx,json}` | Scaffold written by `y module create`. The `.tsx` is the canonical example of the module shape: `export const panel` (required), `export const detail` (optional), `export const shell` (optional). |

If `contract.json`'s values ever diverge from what `web/src/host/registry.ts`
actually registers, that is the D6 single-source-of-truth invariant breaking
— fix by pointing the drifted side at this file rather than hand-copying
values.

## Surfaces

A module UI declares up to three surfaces, and `module.json`'s `surfaces` list is
what the published version records as `ui_surfaces`:

| Export | Slot | Notes |
|--------|------|-------|
| `panel` | ~280px sidebar column | Required. Introspected from the bundle; a module always gets a sidebar entry. |
| `detail` | full-width centre tab, opened from the panel header | Optional. Introspected from the bundle; unmounted when the tab is closed. |
| `shell` | the persistent centre column (the live chat area) | Optional. **Enforced from `ui_surfaces`**, because the host must pick the claimant before fetching any bundle. At most one module may claim it (lowest slug among enabled claimants wins); when nobody claims it the host renders its own fallback. |

None of the three receives props. Host state reaches a surface through
`useArtifactIntent`, and a surface asks the host to act through `runHostCommand`.
A `shell` module owns everything that decides what the centre column looks like;
the host keeps the leaves whose dependencies are measured in megabytes
(`ArtifactView`, `PatchDiff`, `ImageLightbox`, `CodeEditor`, `exportElementToPng`)
and exports them on `@y/host`. See `docs/prd/module-system.md`, *The `shell`
surface and the renderer seam*, before bundling anything heavy into a module.

## Multi-file module UI

The UI entry point is `code/y-module/<slug>/ui/index.tsx`. Once it gets
too large to maintain, split it into sibling modules under `ui/` and import them
with relative specifiers (`./parts/foo`). `build.mjs` bundles relative imports
normally (esbuild `bundle: true`), so the entry still only needs to re-export the
surfaces (`panel`, optional `detail`, optional `shell`).

`build.mjs` scans `ui/**/*.{tsx,ts}` for Tailwind classes and includes every
`.tsx` and `.ts` file in that tree in `source_digest`, so edits to a sibling file
change the manifest as well as the output bundle.

No `contract.json` change is needed for this. It is a build-recipe change, not
a change to what the host provides.
