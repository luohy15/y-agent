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
 * Call `installHostRegistry()` once, before the app renders (see main.tsx).
 * The public demo page installs the same externals with a restricted
 * `@y/host` instead (todo 3158 H3, web/src/demo/runtime.ts), which is why the
 * SDK object is a parameter rather than a hardwired import.
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

// Every external except `@y/host`: rendering libraries are identical in both
// environments (a demo must render through the same React instance as any
// other mount), so only the host SDK differs.
const renderingExternals: Record<string, unknown> = {
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
};

/** Publish the externals into `globalThis.__Y_HOST__`. `sdk` is what an
 * artifact receives as `@y/host`: the full authenticated surface in the app,
 * the restricted demo surface on the `/demo` page. */
export function installHostRegistry(sdk: object = hostSdk): void {
  const modules: Record<string, unknown> = {
    ...renderingExternals,
    "@y/host": { ...sdk, __esModule: true, default: sdk },
  };

  // Guards against `contract.json` drifting from what is actually registered
  // above (e.g. a new external added to one but not the other).
  const missing = EXTERNALS.filter((specifier) => !(specifier in modules));
  if (missing.length) {
    throw new Error(`[host-registry] no module registered for externals: ${missing.join(", ")}`);
  }

  globalThis.__Y_HOST__ = { version: HOST_CONTRACT_VERSION, modules };
}
