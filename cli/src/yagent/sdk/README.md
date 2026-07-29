# `cli/src/yagent/sdk/` — artifact build-time SDK (todo 2412)

The recipe `y ui publish` runs esbuild/Tailwind against when compiling a
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
`y ui publish` on the VM.

| Path | Role |
|------|------|
| `contract.json` | Single source of truth (decision D6) for the externals list and the `@y/host` contract version. Read by the web host at build time (`web/src/host/contract.ts`) and by `y ui publish`'s esbuild `alias` config; a `min_host_version` mismatch against this value is what S6's loader gates on. |
| `shims/*.cjs` | One CommonJS shim per external in `contract.json`. esbuild `alias` maps each bare specifier onto its shim, so the built artifact bundle has zero import statements (decision D1) — required because a `blob:` module has no base URL to resolve bare specifiers against. Each shim reads `globalThis.__Y_HOST__`, populated at app startup by `web/src/host/registry.ts`. |
| `theme.css` | `@theme reference` block registering the host's `sol-*` color names for Tailwind, without emitting a `:root` value block (decision D3). An artifact's CSS entry imports this alongside `tailwindcss/theme.css` (see the spike's `artifact/demo.css` for the exact three-line recipe). |
| `y-host.d.ts` | Type declarations for `@y/host`, handed to artifact authors. Must match `web/src/host/sdk.ts`'s actual export list — the registry is what exists at runtime, so a d.ts name with no runtime binding fails silently (esbuild does not typecheck) until an artifact calls it. |

If `contract.json`'s values ever diverge from what `web/src/host/registry.ts`
actually registers, that is the D6 single-source-of-truth invariant breaking
— fix by pointing the drifted side at this file rather than hand-copying
values.
