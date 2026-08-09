import { describe, expect, it } from "vitest";
import { isHostWorkspaceTab } from "./fileHost";
import {
  FILE_AGGREGATE_TAB,
  FILE_WORKSPACE_STORAGE_KEY,
  HOST_FILE_DESCRIPTORS_KEY,
  HOST_FILE_TABS_COLLAPSED_KEY,
  HOST_FILE_TABS_MIGRATION_KEY,
  makeFileTab,
  persistHostWorkspace,
  restoreHostWorkspaceWithoutMigration,
  type HostWorkspaceSnapshot,
  type OrdinaryFileTab,
} from "./fileWorkspace";
import { resolveFileWorkspaceModeTransition } from "./fileWorkspaceMode";

function memStorage(seed: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(seed));
  return {
    get length() { return map.size; },
    clear() { map.clear(); },
    getItem(key: string) { return map.has(key) ? map.get(key)! : null; },
    key(index: number) { return [...map.keys()][index] ?? null; },
    removeItem(key: string) { map.delete(key); },
    setItem(key: string, value: string) { map.set(key, value); },
  } as Storage;
}

const isSpecial = (path: string) => isHostWorkspaceTab(path);
const isPersistable = (path: string) => !path.startsWith("artifact:");

function applyTransition(
  storage: Storage,
  transition: ReturnType<typeof resolveFileWorkspaceModeTransition>,
  live: HostWorkspaceSnapshot,
): HostWorkspaceSnapshot {
  if (transition.type === "none") return live;
  if (transition.type === "migrate" || transition.type === "remigrate") {
    expect(persistHostWorkspace(storage, transition.snapshot, true)).toBe(true);
    storage.removeItem(HOST_FILE_TABS_COLLAPSED_KEY);
  } else if (transition.type === "collapse") {
    storage.setItem("openFiles", JSON.stringify(transition.snapshot.openTabs));
    if (transition.snapshot.active) storage.setItem("activeFile", transition.snapshot.active);
    else storage.removeItem("activeFile");
    storage.removeItem("previewFile");
    storage.setItem(HOST_FILE_TABS_COLLAPSED_KEY, "true");
    // Descriptors stay in storage for remigrate (App leaves host.fileDescriptors.v1).
  }
  return transition.snapshot;
}

function readLiveFromStorage(storage: Storage): HostWorkspaceSnapshot {
  let openTabs: string[] = [];
  try {
    openTabs = JSON.parse(storage.getItem("openFiles") || "[]") as string[];
  } catch { openTabs = []; }
  const filesRaw = storage.getItem(HOST_FILE_DESCRIPTORS_KEY);
  let files: Record<string, OrdinaryFileTab> = {};
  if (filesRaw) {
    try {
      for (const value of JSON.parse(filesRaw) as unknown[]) {
        const tab = value as OrdinaryFileTab;
        if (tab && typeof tab.id === "string") files[tab.id] = tab;
      }
    } catch { files = {}; }
  }
  const migrationDone = storage.getItem(HOST_FILE_TABS_MIGRATION_KEY) === "true";
  const collapsed = storage.getItem(HOST_FILE_TABS_COLLAPSED_KEY) === "true";
  // Mirror App initial restore.
  return restoreHostWorkspaceWithoutMigration(
    openTabs,
    storage.getItem("activeFile"),
    storage.getItem("previewFile"),
    files,
    isSpecial,
    isPersistable,
    migrationDone,
    collapsed,
  );
}

describe("resolveFileWorkspaceModeTransition (round-10/11)", () => {
  it("does nothing while modules are still loading", () => {
    const a = makeFileTab("pages/a.md", null, null);
    const transition = resolveFileWorkspaceModeTransition({
      contextual: true,
      modulesKnown: false,
      storage: memStorage(),
      openTabs: ["trace.md", FILE_AGGREGATE_TAB],
      active: FILE_AGGREGATE_TAB,
      preview: null,
      files: { [a.id]: a },
      isHostSpecialTab: isSpecial,
      isPersistable,
    });
    expect(transition).toEqual({ type: "none" });
  });

  it("migrates once when a contextual file module becomes active", () => {
    const a = makeFileTab("pages/a.md", "prod", "/home");
    const storage = memStorage({
      openFiles: JSON.stringify(["trace.md", FILE_AGGREGATE_TAB]),
      activeFile: FILE_AGGREGATE_TAB,
      [FILE_WORKSPACE_STORAGE_KEY]: JSON.stringify({ tabs: [a], active: a.id, preview: null }),
    });
    const transition = resolveFileWorkspaceModeTransition({
      contextual: true,
      modulesKnown: true,
      storage,
      openTabs: ["trace.md", FILE_AGGREGATE_TAB],
      active: FILE_AGGREGATE_TAB,
      preview: null,
      files: {},
      isHostSpecialTab: isSpecial,
      isPersistable,
    });
    expect(transition.type).toBe("migrate");
    if (transition.type !== "migrate") return;
    expect(transition.snapshot.openTabs).toEqual(["trace.md", a.id]);
    expect(transition.snapshot.active).toBe(a.id);
  });

  it("collapses ordinary host tabs back to ui:file on aggregate rollback after migration", () => {
    const a = makeFileTab("pages/a.md", null, null);
    const b = makeFileTab("pages/b.md", null, null);
    const storage = memStorage({ [HOST_FILE_TABS_MIGRATION_KEY]: "true" });
    const transition = resolveFileWorkspaceModeTransition({
      contextual: false,
      modulesKnown: true,
      storage,
      openTabs: ["trace.md", a.id, b.id, "entity.md"],
      active: b.id,
      preview: a.id,
      files: { [a.id]: a, [b.id]: b },
      isHostSpecialTab: isSpecial,
      isPersistable,
    });
    expect(transition.type).toBe("collapse");
    if (transition.type !== "collapse") return;
    expect(transition.snapshot.openTabs).toEqual(["trace.md", "entity.md", FILE_AGGREGATE_TAB]);
    expect(transition.snapshot.active).toBe(FILE_AGGREGATE_TAB);
    expect(transition.snapshot.files).toEqual({});
    expect(storage.getItem(HOST_FILE_TABS_MIGRATION_KEY)).toBe("true");
    expect(storage.getItem(FILE_WORKSPACE_STORAGE_KEY)).toBeNull();
  });

  it("is a no-op on aggregate mode when already collapsed", () => {
    const storage = memStorage({
      [HOST_FILE_TABS_MIGRATION_KEY]: "true",
      [HOST_FILE_TABS_COLLAPSED_KEY]: "true",
    });
    const transition = resolveFileWorkspaceModeTransition({
      contextual: false,
      modulesKnown: true,
      storage,
      openTabs: ["trace.md", FILE_AGGREGATE_TAB],
      active: FILE_AGGREGATE_TAB,
      preview: null,
      files: {},
      isHostSpecialTab: isSpecial,
      isPersistable,
    });
    expect(transition).toEqual({ type: "none" });
  });

  /** Model App's ordered effects on a contextualFileTabs flip (round-12):
 * 1) persistence filter (must keep ui:file while collapsed)
 * 2) mode transition, preferring live openTabs when they still hold ui:file
 */
function appPersistOpenFiles(
  storage: Storage,
  live: HostWorkspaceSnapshot,
  contextual: boolean,
): void {
  const collapsed = storage.getItem(HOST_FILE_TABS_COLLAPSED_KEY) === "true";
  const dropAggregate = contextual && !collapsed;
  const persistable = live.openTabs
    .filter((key) => isPersistable(key) || !!live.files[key])
    .filter((key) => (dropAggregate ? key !== FILE_AGGREGATE_TAB : true));
  storage.setItem("openFiles", JSON.stringify(persistable));
  if (live.active && (dropAggregate ? live.active !== FILE_AGGREGATE_TAB : true)) {
    storage.setItem("activeFile", live.active);
  }
}

function appModeTransition(
  storage: Storage,
  live: HostWorkspaceSnapshot,
  contextual: boolean,
): { transition: ReturnType<typeof resolveFileWorkspaceModeTransition>; next: HostWorkspaceSnapshot } {
  // Prefer live strip when it still holds ui:file (App remigrate effect).
  let hostOpenTabs = live.openTabs;
  if (!live.openTabs.includes(FILE_AGGREGATE_TAB)) {
    try {
      const stored = JSON.parse(storage.getItem("openFiles") || "[]") as string[];
      if (stored.length) hostOpenTabs = stored;
    } catch { /* keep live */ }
  }
  const transition = resolveFileWorkspaceModeTransition({
    contextual,
    modulesKnown: true,
    storage,
    openTabs: hostOpenTabs,
    active: live.active,
    preview: live.preview,
    files: live.files,
    isHostSpecialTab: isSpecial,
    isPersistable,
  });
  return { transition, next: applyTransition(storage, transition, live) };
}

  it("evolving sequence: migrate → collapse → reload aggregate → remigrate with App effect order", () => {
    const a = makeFileTab("pages/a.md", "prod", "/home");
    const b = makeFileTab("pages/b.md", "prod", "/home");
    const storage = memStorage({
      openFiles: JSON.stringify(["trace.md", FILE_AGGREGATE_TAB, "entity.md"]),
      activeFile: FILE_AGGREGATE_TAB,
      [FILE_WORKSPACE_STORAGE_KEY]: JSON.stringify({
        tabs: [a, b],
        active: b.id,
        preview: a.id,
      }),
    });

    // 1) contextual migrate
    let live: HostWorkspaceSnapshot = {
      openTabs: ["trace.md", FILE_AGGREGATE_TAB, "entity.md"],
      active: FILE_AGGREGATE_TAB,
      preview: null,
      files: {},
    };
    appPersistOpenFiles(storage, live, true);
    let step = appModeTransition(storage, live, true);
    expect(step.transition.type).toBe("migrate");
    live = step.next;
    expect(live.openTabs).toEqual(["trace.md", a.id, b.id, "entity.md"]);
    expect(storage.getItem(HOST_FILE_TABS_MIGRATION_KEY)).toBe("true");
    expect(storage.getItem(HOST_FILE_TABS_COLLAPSED_KEY)).toBeNull();
    expect(storage.getItem(HOST_FILE_DESCRIPTORS_KEY)).toContain("pages/a.md");

    // 2) aggregate rollback collapse (live ordinary present)
    appPersistOpenFiles(storage, live, false);
    step = appModeTransition(storage, live, false);
    expect(step.transition.type).toBe("collapse");
    live = step.next;
    expect(live.openTabs).toEqual(["trace.md", "entity.md", FILE_AGGREGATE_TAB]);
    expect(live.files).toEqual({});
    expect(storage.getItem(HOST_FILE_TABS_COLLAPSED_KEY)).toBe("true");
    expect(storage.getItem(HOST_FILE_TABS_MIGRATION_KEY)).toBe("true");
    expect(storage.getItem(HOST_FILE_DESCRIPTORS_KEY)).toContain("pages/a.md");
    expect(storage.getItem(FILE_WORKSPACE_STORAGE_KEY)).toContain("pages/a.md");

    // 3) reload in aggregate mode: collapsed flag keeps ui:file
    live = readLiveFromStorage(storage);
    expect(live.openTabs).toEqual(["trace.md", "entity.md", FILE_AGGREGATE_TAB]);
    expect(live.active).toBe(FILE_AGGREGATE_TAB);
    expect(live.files).toEqual({});
    appPersistOpenFiles(storage, live, false);
    step = appModeTransition(storage, live, false);
    expect(step.transition).toEqual({ type: "none" });
    expect(JSON.parse(storage.getItem("openFiles") || "[]")).toContain(FILE_AGGREGATE_TAB);

    // 4) contextual reactivation: persistence runs first while collapsed=true, so
    // ui:file must remain in storage; remigrate then replaces that slot in place.
    appPersistOpenFiles(storage, live, true);
    expect(JSON.parse(storage.getItem("openFiles") || "[]")).toEqual([
      "trace.md",
      "entity.md",
      FILE_AGGREGATE_TAB,
    ]);
    step = appModeTransition(storage, live, true);
    expect(step.transition.type).toBe("remigrate");
    live = step.next;
    // Collapse put ui:file after specials; remigrate inserts ordinary tabs there.
    expect(live.openTabs).toEqual(["trace.md", "entity.md", a.id, b.id]);
    expect(live.files[a.id]?.path).toBe("pages/a.md");
    expect(live.files[b.id]?.path).toBe("pages/b.md");
    expect(live.openTabs).not.toContain(FILE_AGGREGATE_TAB);
    expect(storage.getItem(HOST_FILE_TABS_COLLAPSED_KEY)).toBeNull();
    expect(storage.getItem(HOST_FILE_TABS_MIGRATION_KEY)).toBe("true");
  });
});
