// Synthetic Module catalog entries for the demo rails (todo 3158 H6).
// The rails need icons/labels from the production panelCatalog path; the real
// public projection deliberately returns no label/icon inventory. These
// entries are host-owned chrome only — they are never used to load a bundle.
import type { Module } from "../host/artifacts";
import type { PublicDemoRef } from "./lookup";

const SHOWCASE: Array<{ key: string; slug: string; label: string; icon: string }> = [
  { key: "todo", slug: "todo", label: "Todo", icon: "todo" },
  { key: "chat", slug: "chat", label: "Chat", icon: "message" },
  { key: "note", slug: "note", label: "Notes", icon: "file-text" },
];

/** Build mountable-looking Module rows for ActivityBar / RightActivityBar icons.
 * version_id / ui_sha256 are placeholders when a public projection is missing;
 * DemoMount still uses the real PublicDemoRef for loading. */
export function buildDemoModules(demos: Map<string, PublicDemoRef | null>): Module[] {
  return SHOWCASE.map(({ key, slug, label, icon }) => {
    const ref = demos.get(key);
    return {
      module_id: `demo-${slug}`,
      slug,
      active_version_id: ref?.version_id ?? `demo-${slug}-v0`,
      enabled: true,
      active_version: {
        version_id: ref?.version_id ?? `demo-${slug}-v0`,
        version_no: ref?.version_no ?? 0,
        ui_sha256: ref?.ui_sha256 ?? "0".repeat(64),
        min_host_version: ref?.min_host_version ?? 9,
        label,
        icon,
        ui_surfaces: slug === "chat" ? "panel,shell,detail" : "panel,detail",
      },
    } satisfies Module;
  });
}
