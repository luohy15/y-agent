/*
 * Runtime registry (decision D1, pages/decision-2412-runtime-contract.md):
 * publishes the externals list into `globalThis.__Y_HOST__` at app startup.
 * `y ui publish`'s esbuild `alias` maps each bare specifier in an artifact
 * bundle onto a CommonJS shim (web/sdk/shims/*.cjs) that reads this object,
 * so a blob-imported artifact module shares exactly these instances instead
 * of bundling its own copies — the structural guarantee behind "one React
 * instance" (plan assumption 1, confirmed in the spike via a host-provided
 * React context resolving inside the blob module).
 *
 * Side-effect module: import it once, before the app renders (see main.tsx).
 */
import * as React from "react";
import * as ReactDOM from "react-dom";
import * as ReactDOMClient from "react-dom/client";
import * as JsxRuntime from "react/jsx-runtime";
import * as SWR from "swr";
import * as SWRInfinite from "swr/infinite";
import * as Recharts from "recharts";
import * as LightweightCharts from "lightweight-charts";
import * as ReactMarkdown from "react-markdown";
import * as RemarkGfm from "remark-gfm";
import { EXTERNALS, HOST_CONTRACT_VERSION } from "./contract";
import { hostSdk } from "./sdk";

export interface HostRegistry {
  version: number;
  modules: Record<string, unknown>;
}

declare global {
  // eslint-disable-next-line no-var
  var __Y_HOST__: HostRegistry | undefined;
}

// Finding F6 (pages/decision-2412-runtime-contract.md): publish the FULL
// namespace for every external, never a curated export list. A curated list
// would break any artifact importing an unlisted export at runtime — exactly
// the "needs a host redeploy" failure this feature exists to remove. The
// ~48KB gzip cost of the full recharts namespace is accepted.
//
// Normalising to `__esModule: true` + explicit `default` makes esbuild's
// `__toESM()` a pass-through in the shim, so `import X from` and
// `import { X } from` both behave the way an artifact author expects.
function asModule(ns: Record<string, unknown>): Record<string, unknown> {
  return { ...ns, __esModule: true, default: ns.default ?? ns };
}

const modules: Record<string, unknown> = {
  react: asModule(React as unknown as Record<string, unknown>),
  "react-dom": asModule(ReactDOM as unknown as Record<string, unknown>),
  "react-dom/client": asModule(ReactDOMClient as unknown as Record<string, unknown>),
  "react/jsx-runtime": asModule(JsxRuntime as unknown as Record<string, unknown>),
  swr: asModule(SWR as unknown as Record<string, unknown>),
  "swr/infinite": asModule(SWRInfinite as unknown as Record<string, unknown>),
  recharts: asModule(Recharts as unknown as Record<string, unknown>),
  "lightweight-charts": asModule(LightweightCharts as unknown as Record<string, unknown>),
  "react-markdown": asModule(ReactMarkdown as unknown as Record<string, unknown>),
  "remark-gfm": asModule(RemarkGfm as unknown as Record<string, unknown>),
  "@y/host": { ...hostSdk, __esModule: true, default: hostSdk },
};

// Guards against `web/sdk/contract.json` drifting from what is actually
// registered below (e.g. a new external added to one but not the other).
const missing = EXTERNALS.filter((specifier) => !(specifier in modules));
if (missing.length) {
  throw new Error(`[host-registry] no module registered for externals: ${missing.join(", ")}`);
}

globalThis.__Y_HOST__ = { version: HOST_CONTRACT_VERSION, modules };
