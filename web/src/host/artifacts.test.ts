import { describe, expect, it } from "vitest";
import { isPersistableTab, modulesFromPayload, mountableUiArtifacts } from "./artifacts";

describe("module payload handling", () => {
  it("returns no modules or mountable artifacts for a non-array API payload", () => {
    const payload = { detail: "Service Unavailable" };
    expect(modulesFromPayload(payload)).toEqual([]);
    expect(mountableUiArtifacts(payload)).toEqual([]);
  });

  it("keeps enabled modules with an active UI bundle", () => {
    const module = {
      module_id: "mod_1",
      slug: "todo",
      active_version_id: "ver_1",
      enabled: true,
      active_version: { ui_sha256: "abc" },
    };
    expect(mountableUiArtifacts([module])).toEqual([module]);
  });
});

describe("isPersistableTab", () => {
  it("persists ui: artifact tabs", () => {
    expect(isPersistableTab("ui:finance")).toBe(true);
  });

  it("persists ordinary file tabs", () => {
    expect(isPersistableTab("notes/x.md")).toBe(true);
  });

  it("excludes artifact: inline chart tabs", () => {
    expect(isPersistableTab("artifact:ab12.mermaid")).toBe(false);
  });
});
