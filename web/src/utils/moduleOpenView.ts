// Host command `module.openView` (todo 3816, browser contract v24).
// Decides where a Modules-sidebar row goes. Domain record rows are not this
// command. Hidden activity-bar icons stay hidden: visibility is not a gate
// and this module never writes it. Nothing here enables or publishes a module.
//
// Browser location, new tabs, and Back/Forward are unchanged. A row is not a
// link; middle-click and open-in-new-tab are unsupported.

import { artifactPanelKey, artifactTabKey } from "../host/artifacts";

/** Enabled UI whose detail needs a record picked from that module's sidebar. */
export const MODULE_OPEN_VIEW_SELECTION_SLUGS = ["email", "entity", "english", "link", "mcp", "rss"] as const;

/** Enabled UI with no detail export. Files is separate: it has a per-file detail and must never open `ui:file`. */
export const MODULE_OPEN_VIEW_PANEL_SLUGS = ["note", "reminder", "routine"] as const;

export const MODULE_OPEN_VIEW_EXPLANATION = {
  disabled: "This module is disabled, so its version history is open instead of a full view.",
  unpublished: "This module is unpublished, so module management is open instead of a full view.",
  "api-only": "This module has no interface, so its version history is open instead of a full view.",
} as const;

export type ModuleOpenViewReason = keyof typeof MODULE_OPEN_VIEW_EXPLANATION;

export interface ModuleOpenViewRow {
  module_id: string;
  slug: string;
  enabled: boolean;
  active_version: { ui_sha256?: string | null } | null;
}

export type ModuleOpenViewDecision =
  | { kind: "none" }
  | {
      kind: "view";
      mode: "detail" | "detail-and-sidebar" | "sidebar";
      slug: string;
      tab: `ui:${string}` | null;
      sidebar: `artifact:${string}` | null;
    }
  | {
      kind: "management";
      slug: string;
      moduleId: string;
      reason: ModuleOpenViewReason;
      explanation: string;
      tab: "ui:module";
      sidebar: "artifact:module";
    };

export interface ModuleOpenViewIntent {
  moduleId: string;
  slug: string;
  reason: ModuleOpenViewReason;
  explanation: string;
  nonce: number;
}

export function resolveModuleOpenView(input: {
  payload: unknown;
  modules: readonly ModuleOpenViewRow[];
  listLoaded: boolean;
  /** Accepted so the caller passes the preference in. Never read as a gate. */
  hiddenSlugs?: readonly string[];
}): ModuleOpenViewDecision {
  void input.hiddenSlugs;
  if (!input.listLoaded) return { kind: "none" };
  if (!input.payload || typeof input.payload !== "object") return { kind: "none" };
  const raw = (input.payload as { slug?: unknown }).slug;
  if (typeof raw !== "string") return { kind: "none" };
  const slug = raw.trim();
  if (!slug) return { kind: "none" };
  const row = input.modules.find((module) => module.slug === slug);
  if (!row || typeof row.module_id !== "string" || !row.module_id) return { kind: "none" };

  if (row.enabled !== true) return management(row, "disabled");
  if (!row.active_version) return management(row, "unpublished");
  const uiSha = row.active_version.ui_sha256;
  if (typeof uiSha !== "string" || uiSha.length === 0) return management(row, "api-only");

  if (slug === "file" || (MODULE_OPEN_VIEW_PANEL_SLUGS as readonly string[]).includes(slug)) {
    return { kind: "view", mode: "sidebar", slug, tab: null, sidebar: artifactPanelKey(slug) };
  }
  if ((MODULE_OPEN_VIEW_SELECTION_SLUGS as readonly string[]).includes(slug)) {
    return {
      kind: "view",
      mode: "detail-and-sidebar",
      slug,
      tab: artifactTabKey(slug),
      sidebar: artifactPanelKey(slug),
    };
  }
  return { kind: "view", mode: "detail", slug, tab: artifactTabKey(slug), sidebar: null };
}

function management(row: ModuleOpenViewRow, reason: ModuleOpenViewReason): ModuleOpenViewDecision {
  return {
    kind: "management",
    slug: row.slug,
    moduleId: row.module_id,
    reason,
    explanation: MODULE_OPEN_VIEW_EXPLANATION[reason],
    tab: "ui:module",
    sidebar: "artifact:module",
  };
}

export interface ModuleOpenViewEffects {
  tab: `ui:${string}` | null;
  sidebarPanel: `artifact:${string}` | null;
  mobileSidebar: "open" | "close" | "unchanged";
  desktopSidebar: "open" | "unchanged";
  showCentreFiles: boolean;
  management: ModuleOpenViewIntent | null;
}

export function moduleOpenViewEffects(
  decision: ModuleOpenViewDecision,
  viewport: "mobile" | "desktop",
): ModuleOpenViewEffects {
  const idle: ModuleOpenViewEffects = {
    tab: null,
    sidebarPanel: null,
    mobileSidebar: "unchanged",
    desktopSidebar: "unchanged",
    showCentreFiles: false,
    management: null,
  };
  if (decision.kind === "none") return idle;
  if (decision.kind === "management") {
    return {
      tab: decision.tab,
      sidebarPanel: decision.sidebar,
      mobileSidebar: viewport === "mobile" ? "close" : "unchanged",
      desktopSidebar: "open",
      showCentreFiles: true,
      management: {
        moduleId: decision.moduleId,
        slug: decision.slug,
        reason: decision.reason,
        explanation: decision.explanation,
        nonce: 0,
      },
    };
  }
  if (decision.mode === "sidebar") {
    return {
      ...idle,
      sidebarPanel: decision.sidebar,
      mobileSidebar: viewport === "mobile" ? "open" : "unchanged",
      desktopSidebar: "open",
    };
  }
  if (decision.mode === "detail-and-sidebar") {
    return {
      tab: decision.tab,
      sidebarPanel: decision.sidebar,
      mobileSidebar: viewport === "mobile" ? "open" : "unchanged",
      desktopSidebar: "open",
      showCentreFiles: true,
      management: null,
    };
  }
  return {
    ...idle,
    tab: decision.tab,
    mobileSidebar: viewport === "mobile" ? "close" : "unchanged",
    showCentreFiles: true,
  };
}

/** Append `path` unless it is already open. A second activation reuses the tab. */
export function openTabsAfterModuleView(openTabs: readonly string[], path: string): string[] {
  if (!path || path === "ui:file") return openTabs.slice();
  if (openTabs.includes(path)) return openTabs.slice();
  return [...openTabs, path];
}

/** Tab-list update `App.openHostWorkspaceTab` passes to `setOpenFiles`.
 * `null` means do not change the list (`ui:file` or an empty path). */
export function applyHostWorkspaceOpen(openTabs: readonly string[], path: string): string[] | null {
  const p = path.replace(/^\.\//, "");
  if (!p || p === "ui:file") return null;
  return openTabsAfterModuleView(openTabs, p);
}

export function mergeModuleOpenViewIntent(
  previous: unknown,
  view: ModuleOpenViewIntent,
): Record<string, unknown> {
  const base = previous && typeof previous === "object" ? { ...(previous as Record<string, unknown>) } : {};
  return { ...base, openView: { ...view } };
}

export interface ModuleOpenViewHost {
  openTab(path: string): void;
  setSidebarPanel(panel: `artifact:${string}`): void;
  setMobileSidebarOpen(open: boolean): void;
  setDesktopSidebarOpen(open: boolean): void;
  setCentreFiles(visible: boolean): void;
  latchManagement(view: ModuleOpenViewIntent): void;
  setSlugVisible?(slug: string, visible: boolean): void;
  enableModule?(slug: string): void;
  publishModule?(slug: string): void;
}

export function applyModuleOpenView(
  decision: ModuleOpenViewDecision,
  viewport: "mobile" | "desktop",
  host: ModuleOpenViewHost,
  now: () => number = Date.now,
): void {
  const effects = moduleOpenViewEffects(decision, viewport);
  if (effects.management) host.latchManagement({ ...effects.management, nonce: now() });
  if (effects.sidebarPanel) host.setSidebarPanel(effects.sidebarPanel);
  if (effects.desktopSidebar === "open") host.setDesktopSidebarOpen(true);
  if (effects.showCentreFiles) host.setCentreFiles(true);
  if (effects.tab) host.openTab(effects.tab);
  if (effects.mobileSidebar === "open") host.setMobileSidebarOpen(true);
  else if (effects.mobileSidebar === "close") host.setMobileSidebarOpen(false);
}
