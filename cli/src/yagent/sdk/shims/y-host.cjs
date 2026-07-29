// Externals shim (decision D1). See react.cjs for the full rationale.

const registry = globalThis.__Y_HOST__;
if (!registry) {
  throw new Error("[y-artifact] host registry missing: globalThis.__Y_HOST__ is not set");
}
const mod = registry.modules["@y/host"];
if (!mod) {
  throw new Error("[y-artifact] host registry has no module '@y/host'");
}
module.exports = mod;
