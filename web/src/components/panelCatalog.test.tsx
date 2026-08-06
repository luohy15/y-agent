import { describe, expect, it } from "vitest";
import { buildActivityPanelItems, BUILT_IN_PANEL_ITEMS } from "./ActivityBar";
import { buildModulePanelItems, resolveRightPanel, restoreRightPanel } from "./panelCatalog";
import type { Module } from "../host/artifacts";

function artifact(slug: string, enabled: boolean, active = true): Module {
  return {
    module_id: `artifact-${slug}`,
    slug,
    active_version_id: active ? `version-${slug}` : null,
    enabled,
    active_version: active ? {
      version_id: `version-${slug}`,
      version_no: 1,
      ui_sha256: "a".repeat(64),
      min_host_version: 1,
      label: `${slug} label`,
      icon: "box",
    } : null,
  };
}

describe("panel catalog", () => {
  it("derives identical module keys, labels, and icons for both rails", () => {
    const artifacts = [artifact("enabled", true), artifact("disabled", false), artifact("unpublished", true, false)];
    const leftModules = buildActivityPanelItems(artifacts).slice(BUILT_IN_PANEL_ITEMS.length);
    const rightModules = buildModulePanelItems(artifacts);

    expect(leftModules.map(({ key, label, icon }) => ({ key, label, icon }))).toEqual(
      rightModules.map(({ key, label, icon }) => ({ key, label, icon })),
    );
    expect(rightModules.map((item) => item.key)).toEqual(["artifact:enabled"]);
  });

  it("retains an artifact while modules are cold, migrates legacy keys, and falls back only after loading", () => {
    const items = [{ key: "notes", label: "Notes", icon: null }, ...buildModulePanelItems([artifact("chat", true), artifact("enabled", true)])];

    expect(restoreRightPanel("git")).toBe("diff");
    expect(restoreRightPanel("chats")).toBe("artifact:chat");
    expect(restoreRightPanel("artifact:enabled")).toBe("artifact:enabled");
    expect(resolveRightPanel("artifact:enabled", items, false)).toBe("artifact:enabled");
    expect(resolveRightPanel("artifact:enabled", items, true)).toBe("artifact:enabled");
    expect(resolveRightPanel("artifact:removed", items, true)).toBe("notes");
    expect(items.filter((item) => item.key === "artifact:chat")).toHaveLength(1);
  });
});
