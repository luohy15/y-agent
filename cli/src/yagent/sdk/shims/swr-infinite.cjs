// Externals shim (decision D1). See react.cjs for the full rationale.
// Subpath external for `swr/infinite` (contract v4) — same pattern as
// react-dom/client.cjs.

const registry = globalThis.__Y_HOST__;
if (!registry) {
  throw new Error("[y-artifact] host registry missing: globalThis.__Y_HOST__ is not set");
}
const mod = registry.modules["swr/infinite"];
if (!mod) {
  throw new Error("[y-artifact] host registry has no module 'swr/infinite'");
}
module.exports = mod;
