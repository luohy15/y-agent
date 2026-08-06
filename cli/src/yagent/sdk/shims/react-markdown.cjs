// Externals shim (decision D1). See react.cjs for the full rationale.
// External for `react-markdown` (contract v5, R3): already eager in the host
// main chunk, so the module reusing it costs the main chunk 0 bytes.

const registry = globalThis.__Y_HOST__;
if (!registry) {
  throw new Error("[y-artifact] host registry missing: globalThis.__Y_HOST__ is not set");
}
const mod = registry.modules["react-markdown"];
if (!mod) {
  throw new Error("[y-artifact] host registry has no module 'react-markdown'");
}
module.exports = mod;
