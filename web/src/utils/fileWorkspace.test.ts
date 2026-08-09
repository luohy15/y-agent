import { describe, expect, it } from "vitest";
import { isHostWorkspaceTab, isOrdinaryFilePath } from "./fileHost";
import {
  FILE_AGGREGATE_TAB,
  FILE_WORKSPACE_STORAGE_KEY,
  HOST_FILE_TABS_MIGRATION_KEY,
  closeWorkspaceTabKey,
  collapseOrdinaryTabsToAggregate,
  fileDirtyPayload,
  fileRemapPayload,
  fileRemovePayload,
  fileTabId,
  makeFileTab,
  mergeModuleWorkspaceIntoHost,
  migrateHostWorkspaceOnLoad,
  openOrdinaryWorkspaceTab,
  persistHostWorkspace,
  remapOrdinaryTabs,
  removeOrdinaryTabs,
  restoreHostWorkspaceWithoutMigration,
  sanitizeModuleWorkspace,
} from "./fileWorkspace";

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

describe("sanitizeModuleWorkspace / merge migration (H1)", () => {
  it("sanitizes module workspace, dedupes by full identity, and keeps active/preview", () => {
    const a = makeFileTab("pages/a.md", "prod", "/home");
    const b = makeFileTab("pages/a.md", null, "/other");
    const state = sanitizeModuleWorkspace({
      tabs: [a, a, b, { path: "ui:file" }, "trace.md"],
      active: b.id,
      preview: a.id,
    });
    expect(state?.tabs.map((t) => t.id)).toEqual([a.id, b.id]);
    expect(state?.active).toBe(b.id);
    expect(state?.preview).toBe(a.id);
  });

  it("merges module tabs at the ui:file position when the aggregate is active", () => {
    const a = makeFileTab("pages/a.md", "prod", "/home");
    const b = makeFileTab("pages/b.md", "prod", "/home");
    const merged = mergeModuleWorkspaceIntoHost(
      ["trace.md", FILE_AGGREGATE_TAB, "entity.md"],
      FILE_AGGREGATE_TAB,
      null,
      {},
      { tabs: [a, b], active: b.id, preview: a.id },
    );
    expect(merged.openTabs).toEqual(["trace.md", a.id, b.id, "entity.md"]);
    expect(merged.active).toBe(b.id);
    expect(merged.preview).toBe(a.id);
    expect(merged.files[a.id]?.path).toBe("pages/a.md");
  });

  it("appends migrated tabs when ui:file is absent and leaves special active", () => {
    const a = makeFileTab("pages/a.md", null, null);
    const merged = mergeModuleWorkspaceIntoHost(
      ["trace.md", "entity.md"],
      "entity.md",
      null,
      {},
      { tabs: [a], active: a.id, preview: null },
    );
    expect(merged.openTabs).toEqual(["trace.md", "entity.md", a.id]);
    expect(merged.active).toBe("entity.md");
  });

  it("corrupt/missing module state only removes ui:file", () => {
    const merged = mergeModuleWorkspaceIntoHost(
      ["trace.md", FILE_AGGREGATE_TAB, "entity.md"],
      FILE_AGGREGATE_TAB,
      null,
      {},
      null,
    );
    expect(merged.openTabs).toEqual(["trace.md", "entity.md"]);
    expect(merged.active).toBe("trace.md");
  });

  it("keeps same-path different-context tabs distinct", () => {
    const left = makeFileTab("notes/x.md", "a", "/a");
    const right = makeFileTab("notes/x.md", "b", "/b");
    expect(left.id).not.toBe(right.id);
    const merged = mergeModuleWorkspaceIntoHost(
      [FILE_AGGREGATE_TAB],
      FILE_AGGREGATE_TAB,
      null,
      {},
      { tabs: [left, right], active: right.id, preview: left.id },
    );
    expect(merged.openTabs).toEqual([left.id, right.id]);
    expect(merged.files[left.id].vmName).toBe("a");
    expect(merged.files[right.id].vmName).toBe("b");
  });

  it("restoreHostWorkspaceWithoutMigration keeps ui:file and skips ordinary tabs before cutover", () => {
    const a = makeFileTab("pages/a.md", null, null);
    const restored = restoreHostWorkspaceWithoutMigration(
      ["trace.md", FILE_AGGREGATE_TAB, a.id],
      FILE_AGGREGATE_TAB,
      a.id,
      { [a.id]: a },
      isSpecial,
      isPersistable,
      false,
    );
    expect(restored.openTabs).toEqual(["trace.md", FILE_AGGREGATE_TAB]);
    expect(restored.active).toBe(FILE_AGGREGATE_TAB);
    expect(restored.files).toEqual({});
  });

  it("restoreHostWorkspaceWithoutMigration keeps ui:file when collapsed after migration", () => {
    const a = makeFileTab("pages/a.md", null, null);
    const restored = restoreHostWorkspaceWithoutMigration(
      ["trace.md", FILE_AGGREGATE_TAB, a.id],
      FILE_AGGREGATE_TAB,
      null,
      { [a.id]: a },
      isSpecial,
      isPersistable,
      true,
      true,
    );
    expect(restored.openTabs).toEqual(["trace.md", FILE_AGGREGATE_TAB]);
    expect(restored.active).toBe(FILE_AGGREGATE_TAB);
    expect(restored.files).toEqual({});
  });

  it("restoreHostWorkspaceWithoutMigration keeps ui:file when collapsed after migration", () => {
    const a = makeFileTab("pages/a.md", null, null);
    const restored = restoreHostWorkspaceWithoutMigration(
      ["trace.md", FILE_AGGREGATE_TAB, a.id],
      FILE_AGGREGATE_TAB,
      null,
      { [a.id]: a },
      isSpecial,
      isPersistable,
      true,
      true,
    );
    expect(restored.openTabs).toEqual(["trace.md", FILE_AGGREGATE_TAB]);
    expect(restored.active).toBe(FILE_AGGREGATE_TAB);
    expect(restored.files).toEqual({});
  });

  it("collapseOrdinaryTabsToAggregate collapses ordinary descriptors to one ui:file", () => {
    const a = makeFileTab("pages/a.md", null, null);
    const b = makeFileTab("pages/b.md", null, null);
    const collapsed = collapseOrdinaryTabsToAggregate({
      openTabs: ["trace.md", a.id, b.id, "entity.md"],
      active: b.id,
      preview: a.id,
      files: { [a.id]: a, [b.id]: b },
    });
    expect(collapsed.openTabs).toEqual(["trace.md", "entity.md", FILE_AGGREGATE_TAB]);
    expect(collapsed.active).toBe(FILE_AGGREGATE_TAB);
    expect(collapsed.preview).toBeNull();
    expect(collapsed.files).toEqual({});
  });

  it("migrateHostWorkspaceOnLoad is retry-safe when persist fails before the marker", () => {
    const a = makeFileTab("pages/a.md", null, null);
    const storage = memStorage({
      openFiles: JSON.stringify(["trace.md", FILE_AGGREGATE_TAB]),
      activeFile: FILE_AGGREGATE_TAB,
      [FILE_WORKSPACE_STORAGE_KEY]: JSON.stringify({ tabs: [a], active: a.id, preview: null }),
    });
    const first = migrateHostWorkspaceOnLoad(
      storage,
      ["trace.md", FILE_AGGREGATE_TAB],
      FILE_AGGREGATE_TAB,
      null,
      {},
      isSpecial,
      isPersistable,
    );
    expect(first.shouldPersistMigration).toBe(true);
    expect(first.snapshot.openTabs).toEqual(["trace.md", a.id]);

    // Simulate failed write: marker not set, retry yields the same merge.
    const second = migrateHostWorkspaceOnLoad(
      storage,
      ["trace.md", FILE_AGGREGATE_TAB],
      FILE_AGGREGATE_TAB,
      null,
      {},
      isSpecial,
      isPersistable,
    );
    expect(second.shouldPersistMigration).toBe(true);
    expect(second.snapshot.openTabs).toEqual(["trace.md", a.id]);

    expect(persistHostWorkspace(storage, second.snapshot, true)).toBe(true);
    expect(storage.getItem(HOST_FILE_TABS_MIGRATION_KEY)).toBe("true");
    const third = migrateHostWorkspaceOnLoad(
      storage,
      second.snapshot.openTabs,
      second.snapshot.active,
      second.snapshot.preview,
      second.snapshot.files,
      isSpecial,
      isPersistable,
    );
    expect(third.shouldPersistMigration).toBe(false);
  });
});

describe("ordinary open/close/remap/remove (H3/H4)", () => {
  it("preview open replaces the current preview tab in place", () => {
    const a = makeFileTab("a.md", null, null);
    const b = makeFileTab("b.md", null, null);
    let state = openOrdinaryWorkspaceTab({ openTabs: [], active: null, preview: null, files: {} }, a, true);
    state = openOrdinaryWorkspaceTab(state, b, true);
    expect(state.openTabs).toEqual([b.id]);
    expect(state.preview).toBe(b.id);
    expect(state.files[a.id]).toBeUndefined();
  });

  it("pin open keeps both tabs and clears preview when reopened non-preview", () => {
    const a = makeFileTab("a.md", null, null);
    let state = openOrdinaryWorkspaceTab({ openTabs: [], active: null, preview: null, files: {} }, a, true);
    state = openOrdinaryWorkspaceTab(state, a, false);
    expect(state.openTabs).toEqual([a.id]);
    expect(state.preview).toBeNull();
  });

  it("adjacent close selects the neighbor at the same index", () => {
    const a = makeFileTab("a.md", null, null);
    const b = makeFileTab("b.md", null, null);
    const c = makeFileTab("c.md", null, null);
    let state = { openTabs: [a.id, b.id, c.id], active: b.id as string | null, preview: null as string | null, files: { [a.id]: a, [b.id]: b, [c.id]: c } };
    state = closeWorkspaceTabKey(state, b.id);
    expect(state.openTabs).toEqual([a.id, c.id]);
    expect(state.active).toBe(c.id);
  });

  it("remap is scoped by vm/workDir context", () => {
    const a = makeFileTab("old/x.md", "prod", "/home");
    const b = makeFileTab("old/x.md", "dev", "/tmp");
    const state = {
      openTabs: [a.id, b.id, "trace.md"],
      active: a.id,
      preview: b.id,
      files: { [a.id]: a, [b.id]: b },
    };
    const remapped = remapOrdinaryTabs(state, "old", "new", "prod", "/home");
    const nextA = makeFileTab("new/x.md", "prod", "/home");
    expect(remapped.openTabs).toContain(nextA.id);
    expect(remapped.openTabs).toContain(b.id);
    expect(remapped.openTabs).toContain("trace.md");
    expect(remapped.files[b.id].path).toBe("old/x.md");
    expect(remapped.files[nextA.id].path).toBe("new/x.md");
    expect(remapped.active).toBe(nextA.id);
  });

  it("remove is scoped by vm/workDir context", () => {
    const a = makeFileTab("gone.md", "prod", "/home");
    const b = makeFileTab("gone.md", "dev", "/tmp");
    const state = {
      openTabs: [a.id, b.id],
      active: a.id,
      preview: null as string | null,
      files: { [a.id]: a, [b.id]: b },
    };
    const next = removeOrdinaryTabs(state, "gone.md", "prod", "/home");
    expect(next.openTabs).toEqual([b.id]);
    expect(next.active).toBe(b.id);
  });
});

describe("payload parsers", () => {
  it("parses dirty/remap/remove payloads", () => {
    expect(fileDirtyPayload({ tabId: "t1", dirty: true })).toEqual({ tabId: "t1", dirty: true });
    expect(fileDirtyPayload({ tabId: 1, dirty: true })).toBeUndefined();
    expect(fileRemapPayload({ oldPath: "a", newPath: "b", vmName: "prod" })).toEqual({
      oldPath: "a",
      newPath: "b",
      vmName: "prod",
    });
    expect(fileRemovePayload({ path: "a.md", workDir: "/x" })).toEqual({ path: "a.md", workDir: "/x" });
  });
});

describe("path classification", () => {
  it("treats ordinary paths and host specials correctly; opaque ids are not ordinary paths", () => {
    expect(isOrdinaryFilePath("pages/plan.md")).toBe(true);
    expect(isOrdinaryFilePath("ui:file")).toBe(false);
    expect(isHostWorkspaceTab("ui:file")).toBe(true);
    expect(isOrdinaryFilePath(fileTabId("pages/plan.md", null, null))).toBe(false);
  });
});
