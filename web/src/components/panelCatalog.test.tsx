import { describe, expect, it } from "vitest";
import { buildActivityPanelItems, BUILT_IN_PANEL_ITEMS } from "./ActivityBar";
import { buildChatPanelItem, buildFilePanelItem, buildModulePanelItems, resolveRightPanel, restoreRightPanel } from "./panelCatalog";
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

  // R1/W2 (plan-3046-right-sidebar.md) + C1 (plan-3068): the right catalog
  // resolves only chat and file modules, not arbitrary enabled modules.
  it("resolves only the chat and file modules for the right catalog, not arbitrary enabled modules", () => {
    const artifacts = [
      artifact("chat", true),
      artifact("file", true),
      artifact("enabled", true),
      artifact("disabled", false),
    ];
    expect(buildChatPanelItem(artifacts).map((item) => item.key)).toEqual(["artifact:chat"]);
    expect(buildFilePanelItem(artifacts).map((item) => item.key)).toEqual(["artifact:file"]);
    expect(buildChatPanelItem(artifacts)).toHaveLength(1);
    expect(buildFilePanelItem(artifacts)).toHaveLength(1);
  });

  it("resolves no chat/file entry when the module is unavailable (disabled, unpublished, or absent)", () => {
    expect(buildChatPanelItem([artifact("chat", false)])).toEqual([]);
    expect(buildChatPanelItem([artifact("chat", true, false)])).toEqual([]);
    expect(buildChatPanelItem([artifact("enabled", true)])).toEqual([]);
    expect(buildChatPanelItem([])).toEqual([]);
    expect(buildFilePanelItem([artifact("file", false)])).toEqual([]);
    expect(buildFilePanelItem([artifact("file", true, false)])).toEqual([]);
    expect(buildFilePanelItem([artifact("enabled", true)])).toEqual([]);
    expect(buildFilePanelItem([])).toEqual([]);
  });

  it("migrates legacy persisted keys, including files -> artifact:file", () => {
    expect(restoreRightPanel("git")).toBe("diff");
    expect(restoreRightPanel("chats")).toBe("artifact:chat");
    expect(restoreRightPanel("files")).toBe("artifact:file");
    expect(restoreRightPanel("links")).toBe("notes");
    expect(restoreRightPanel("artifact:chat")).toBe("artifact:chat");
    expect(restoreRightPanel("artifact:file")).toBe("artifact:file");
    expect(restoreRightPanel(null)).toBe("notes");
  });

  it("retains a cold-loading chat/file selection, resolves it once loaded, and falls back only after loading", () => {
    const items = [
      { key: "notes", label: "Notes", icon: null },
      ...buildChatPanelItem([artifact("chat", true), artifact("file", true), artifact("enabled", true)]),
      ...buildFilePanelItem([artifact("chat", true), artifact("file", true), artifact("enabled", true)]),
    ];

    expect(resolveRightPanel("artifact:chat", items, false)).toBe("artifact:chat");
    expect(resolveRightPanel("artifact:chat", items, true)).toBe("artifact:chat");
    expect(resolveRightPanel("artifact:file", items, false)).toBe("artifact:file");
    expect(resolveRightPanel("artifact:file", items, true)).toBe("artifact:file");
    expect(resolveRightPanel("artifact:removed", items, true)).toBe("notes");
    expect(items.filter((item) => item.key === "artifact:chat")).toHaveLength(1);
    expect(items.filter((item) => item.key === "artifact:file")).toHaveLength(1);
  });

  it("falls back off a removed/disabled chat only once modules have finished loading", () => {
    // Chat was selected but is now unavailable (disabled/rolled back/removed).
    const items = [{ key: "notes", label: "Notes", icon: null }, ...buildChatPanelItem([artifact("chat", false)])];
    expect(resolveRightPanel("artifact:chat", items, false)).toBe("artifact:chat");
    expect(resolveRightPanel("artifact:chat", items, true)).toBe("notes");
  });
});
