// Externals shim (decision D1): esbuild `alias` maps the bare specifier onto
// this file and bundles it in, so the built artifact has ZERO import statements.
// A blob: module has no base URL to resolve bare specifiers against.
//
// CommonJS on purpose. esbuild's CJS->ESM interop turns any named import the
// artifact writes into a property read on this object, so the shim never has to
// enumerate the module's exports (recharts alone has ~70). The host registers
// each entry with `__esModule: true` + an explicit `default`, which makes
// esbuild's `__toESM()` a pass-through and keeps default/named imports honest.

const registry = globalThis.__Y_HOST__;
if (!registry) {
  throw new Error("[y-artifact] host registry missing: globalThis.__Y_HOST__ is not set");
}
const mod = registry.modules["react"];
if (!mod) {
  throw new Error("[y-artifact] host registry has no module 'react'");
}
module.exports = mod;
