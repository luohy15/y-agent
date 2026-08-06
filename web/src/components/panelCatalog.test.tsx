import { describe, expect, it } from "vitest";
import { buildActivityPanelItems, BUILT_IN_PANEL_ITEMS } from "./ActivityBar";
import { buildChatPanelItem, buildModulePanelItems, resolveRightPanel, restoreRightPanel } from "./panelCatalog";
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
  it("derives identical module keys, labels, and icons for the left activity bar's arbitrary modules", () => {
    const artifacts = [artifact("enabled", true), artifact("disabled", false), artifact("unpublished", true, false)];
    const leftModules = buildActivityPanelItems(artifacts).slice(BUILT_IN_PANEL_ITEMS.length);
    const rightModules = buildModulePanelItems(artifacts);

    expect(leftModules.map(({ key, label, icon }) => ({ key, label, icon }))).toEqual(
      rightModules.map(({ key, label, icon }) => ({ key, label, icon })),
    );
    expect(rightModules.map((item) => item.key)).toEqual(["artifact:enabled"]);
  });

  // R1/W2 (plan-3046-right-sidebar.md): the right catalog stopped appending
  // every mountable module and now resolves only chat, dynamically.
  it("resolves only the chat module for the right catalog, not arbitrary enabled modules", () => {
    const artifacts = [artifact("chat", true), artifact("enabled", true), artifact("disabled", false)];
    expect(buildChatPanelItem(artifacts).map((item) => item.key)).toEqual(["artifact:chat"]);
    expect(buildChatPanelItem(artifacts)).toHaveLength(1);
  });

  it("resolves no chat entry when the chat module is unavailable (disabled, unpublished, or absent)", () => {
    expect(buildChatPanelItem([artifact("chat", false)])).toEqual([]);
    expect(buildChatPanelItem([artifact("chat", true, false)])).toEqual([]);
    expect(buildChatPanelItem([artifact("enabled", true)])).toEqual([]);
    expect(buildChatPanelItem([])).toEqual([]);
  });

  it("migrates legacy persisted keys, including the new links -> notes migration", () => {
    expect(restoreRightPanel("git")).toBe("diff");
    expect(restoreRightPanel("chats")).toBe("artifact:chat");
    expect(restoreRightPanel("links")).toBe("notes");
    expect(restoreRightPanel("artifact:chat")).toBe("artifact:chat");
    expect(restoreRightPanel(null)).toBe("notes");
  });

  it("retains a cold-loading chat selection, resolves it once loaded, and falls back only after loading", () => {
    const items = [
      { key: "notes", label: "Notes", icon: null },
      ...buildChatPanelItem([artifact("chat", true), artifact("enabled", true)]),
    ];

    expect(resolveRightPanel("artifact:chat", items, false)).toBe("artifact:chat");
    expect(resolveRightPanel("artifact:chat", items, true)).toBe("artifact:chat");
    expect(resolveRightPanel("artifact:removed", items, true)).toBe("notes");
    expect(items.filter((item) => item.key === "artifact:chat")).toHaveLength(1);
  });

  it("falls back off a removed/disabled chat only once modules have finished loading", () => {
    // Chat was selected but is now unavailable (disabled/rolled back/removed).
    const items = [{ key: "notes", label: "Notes", icon: null }, ...buildChatPanelItem([artifact("chat", false)])];
    expect(resolveRightPanel("artifact:chat", items, false)).toBe("artifact:chat");
    expect(resolveRightPanel("artifact:chat", items, true)).toBe("notes");
  });
});
