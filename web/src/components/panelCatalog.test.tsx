import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { buildActivityPanelItems, BUILT_IN_PANEL_ITEMS } from "./ActivityBar";
import { buildChatPanelItem, buildFilePanelItem, buildModulePanelItems, buildNotePanelItem, DEFAULT_MODULE_ICON, MODULE_ICONS, resolveRightPanel, restoreRightPanel } from "./panelCatalog";
import type { Module } from "../host/artifacts";
import { MODULE_ICON_KEYS } from "../host/contract";

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
  it("keeps every shared icon key backed by a distinct registry entry", () => {
    const markup = Object.entries(MODULE_ICONS)
      .filter(([key]) => key !== "box")
      .map(([, icon]) => renderToStaticMarkup(icon));

    expect(MODULE_ICON_KEYS.every((key) => key in MODULE_ICONS)).toBe(true);
    // `box` intentionally shares DEFAULT_MODULE_ICON: it is both the scaffold
    // default and the honest rendering fallback for an unknown persisted key.
    expect(new Set(markup).size).toBe(markup.length);
    for (const key of ["file", "file-text", "package", "list", "chart", "bot", "todo", "calendar"]) {
      expect(MODULE_ICONS[key]).not.toBe(DEFAULT_MODULE_ICON);
    }
  });

  it("derives identical module keys, labels, and icons for the left activity bar's arbitrary modules", () => {
    const artifacts = [artifact("enabled", true), artifact("disabled", false), artifact("unpublished", true, false)];
    const leftModules = buildActivityPanelItems(artifacts).slice(BUILT_IN_PANEL_ITEMS.length);
    const rightModules = buildModulePanelItems(artifacts);

    expect(leftModules.map(({ key, label, icon }) => ({ key, label, icon }))).toEqual(
      rightModules.map(({ key, label, icon }) => ({ key, label, icon })),
    );
    expect(rightModules.map((item) => item.key)).toEqual(["artifact:enabled"]);
  });

  // R1/W2 (plan-3046-right-sidebar.md) + module cuts: the right catalog
  // resolves only chat, note, and file modules, not arbitrary enabled modules.
  it("resolves only the chat, note, and file modules for the right catalog", () => {
    const artifacts = [
      artifact("chat", true),
      artifact("note", true),
      artifact("file", true),
      artifact("enabled", true),
      artifact("disabled", false),
    ];
    expect(buildChatPanelItem(artifacts).map((item) => item.key)).toEqual(["artifact:chat"]);
    expect(buildNotePanelItem(artifacts).map((item) => item.key)).toEqual(["artifact:note"]);
    expect(buildFilePanelItem(artifacts).map((item) => item.key)).toEqual(["artifact:file"]);
  });

  it("resolves no chat/note/file entry when the module is unavailable (disabled, unpublished, or absent)", () => {
    expect(buildChatPanelItem([artifact("chat", false)])).toEqual([]);
    expect(buildChatPanelItem([artifact("chat", true, false)])).toEqual([]);
    expect(buildChatPanelItem([artifact("enabled", true)])).toEqual([]);
    expect(buildChatPanelItem([])).toEqual([]);
    expect(buildNotePanelItem([artifact("note", false)])).toEqual([]);
    expect(buildNotePanelItem([artifact("note", true, false)])).toEqual([]);
    expect(buildNotePanelItem([artifact("enabled", true)])).toEqual([]);
    expect(buildNotePanelItem([])).toEqual([]);
    expect(buildFilePanelItem([artifact("file", false)])).toEqual([]);
    expect(buildFilePanelItem([artifact("file", true, false)])).toEqual([]);
    expect(buildFilePanelItem([artifact("enabled", true)])).toEqual([]);
    expect(buildFilePanelItem([])).toEqual([]);
  });

  it("migrates legacy persisted keys onto module panels", () => {
    expect(restoreRightPanel("git")).toBe("diff");
    expect(restoreRightPanel("chats")).toBe("artifact:chat");
    expect(restoreRightPanel("notes")).toBe("artifact:note");
    expect(restoreRightPanel("links")).toBe("artifact:note");
    expect(restoreRightPanel("files")).toBe("artifact:file");
    expect(restoreRightPanel("artifact:chat")).toBe("artifact:chat");
    expect(restoreRightPanel("artifact:note")).toBe("artifact:note");
    expect(restoreRightPanel("artifact:file")).toBe("artifact:file");
    expect(restoreRightPanel(null)).toBe("artifact:note");
  });

  it("retains module selections while loading and falls back to note after loading", () => {
    const artifacts = [artifact("chat", true), artifact("note", true), artifact("file", true), artifact("enabled", true)];
    const items = [
      ...buildChatPanelItem(artifacts),
      ...buildNotePanelItem(artifacts),
      ...buildFilePanelItem(artifacts),
    ];

    expect(resolveRightPanel("artifact:chat", items, false)).toBe("artifact:chat");
    expect(resolveRightPanel("artifact:chat", items, true)).toBe("artifact:chat");
    expect(resolveRightPanel("artifact:file", items, true)).toBe("artifact:file");
    expect(resolveRightPanel("artifact:note", items, true)).toBe("artifact:note");
    expect(resolveRightPanel("artifact:removed", items, true)).toBe("artifact:note");
  });

  it("falls back off a removed chat only once modules have finished loading", () => {
    const items = buildNotePanelItem([artifact("note", true)]);
    expect(resolveRightPanel("artifact:chat", items, false)).toBe("artifact:chat");
    expect(resolveRightPanel("artifact:chat", items, true)).toBe("artifact:note");
  });
});
