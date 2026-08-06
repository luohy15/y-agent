import ReactDefault from "react";
import { describe, expect, it } from "vitest";
import { EXTERNALS, HOST_CONTRACT_VERSION } from "./contract";
import "./registry";

describe("host runtime registry", () => {
  it("publishes every specifier in the externals list", () => {
    const registry = globalThis.__Y_HOST__;
    expect(registry).toBeDefined();
    for (const specifier of EXTERNALS) {
      expect(registry!.modules[specifier]).toBeDefined();
    }
  });

  it("registers a module for every contract external, including lightweight-charts", () => {
    const registry = globalThis.__Y_HOST__!;
    expect(EXTERNALS.every((specifier) => specifier in registry.modules)).toBe(true);
  });

  it("bumps the host contract version to 5 for the R2 renderer leaves + react-markdown/remark-gfm externals", () => {
    expect(HOST_CONTRACT_VERSION).toBe(5);
  });

  it("registers the swr/infinite subpath external", () => {
    const registry = globalThis.__Y_HOST__!;
    expect(registry.modules["swr/infinite"]).toBeDefined();
  });

  it("registers a react whose default export is reference-identical to the app's own react import", () => {
    const registry = globalThis.__Y_HOST__!;
    const registeredReact = registry.modules["react"] as { default: unknown };
    expect(registeredReact.default).toBe(ReactDefault);
  });

  it("normalizes every module with __esModule + an explicit default", () => {
    const registry = globalThis.__Y_HOST__!;
    for (const specifier of EXTERNALS) {
      const mod = registry.modules[specifier] as { __esModule?: boolean; default?: unknown };
      expect(mod.__esModule).toBe(true);
      expect(mod.default).toBeDefined();
    }
  });
});
