import ReactDefault from "react";
import { describe, expect, it } from "vitest";
import { EXTERNALS } from "./contract";
import "./registry";

describe("host runtime registry", () => {
  it("publishes every specifier in the externals list", () => {
    const registry = globalThis.__Y_HOST__;
    expect(registry).toBeDefined();
    for (const specifier of EXTERNALS) {
      expect(registry!.modules[specifier]).toBeDefined();
    }
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
