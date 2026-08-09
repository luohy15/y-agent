// Pure host workspace mode transitions for todo 3084 staged rollout.
// Kept out of App.tsx so the contextual ↔ aggregate cutover can be unit-tested
// without mounting the full shell.
import {
  collapseOrdinaryTabsToAggregate,
  FILE_AGGREGATE_TAB,
  HOST_FILE_TABS_COLLAPSED_KEY,
  HOST_FILE_TABS_MIGRATION_KEY,
  migrateHostWorkspaceOnLoad,
  remigrateFromRetainedSources,
  type HostWorkspaceSnapshot,
  type OrdinaryFileTab,
} from "./fileWorkspace";

export type WorkspaceModeTransition =
  | { type: "none" }
  | { type: "migrate"; snapshot: HostWorkspaceSnapshot }
  | { type: "collapse"; snapshot: HostWorkspaceSnapshot }
  | { type: "remigrate"; snapshot: HostWorkspaceSnapshot };

function hasLiveOrdinaryTabs(
  openTabs: string[],
  files: Record<string, OrdinaryFileTab>,
  isHostSpecialTab: (path: string) => boolean,
): boolean {
  if (Object.keys(files).length > 0) return true;
  return openTabs.some((key) => key !== FILE_AGGREGATE_TAB && !isHostSpecialTab(key));
}

/**
 * Decide the host workspace transition when the active file module's
 * contextual capability changes.
 *
 * - contextual true + not yet migrated → one-way migrate from file.workspace.v2
 * - contextual true + migrated + collapsed / no ordinary live tabs → remigrate
 *   from retained host descriptors / file.workspace.v2
 * - contextual false + already migrated + ordinary descriptors present → collapse
 *   to a single ui:file aggregate tab (rollback path). Descriptors remain in
 *   storage for a later re-cutover; file.workspace.v2 stays untouched.
 */
export function resolveFileWorkspaceModeTransition(opts: {
  contextual: boolean;
  modulesKnown: boolean;
  storage: Pick<Storage, "getItem">;
  openTabs: string[];
  active: string | null;
  preview: string | null;
  files: Record<string, OrdinaryFileTab>;
  isHostSpecialTab: (path: string) => boolean;
  isPersistable: (path: string) => boolean;
}): WorkspaceModeTransition {
  if (!opts.modulesKnown) return { type: "none" };
  const migrationDone = opts.storage.getItem(HOST_FILE_TABS_MIGRATION_KEY) === "true";
  const collapsed = opts.storage.getItem(HOST_FILE_TABS_COLLAPSED_KEY) === "true";
  const hasOrdinary = hasLiveOrdinaryTabs(opts.openTabs, opts.files, opts.isHostSpecialTab);

  if (opts.contextual) {
    if (!migrationDone) {
      const { snapshot, shouldPersistMigration } = migrateHostWorkspaceOnLoad(
        opts.storage,
        opts.openTabs,
        opts.active,
        opts.preview,
        opts.files,
        opts.isHostSpecialTab,
        opts.isPersistable,
      );
      if (!shouldPersistMigration) return { type: "none" };
      return { type: "migrate", snapshot };
    }
    // Already migrated. Remigrate when collapsed, or when the live strip has no
    // ordinary tabs (reload mid-collapse / reactivation while still on ui:file).
    if (!collapsed && hasOrdinary) return { type: "none" };
    const snapshot = remigrateFromRetainedSources(
      opts.storage,
      opts.openTabs,
      opts.active,
      opts.preview,
      opts.files,
      opts.isHostSpecialTab,
      opts.isPersistable,
    );
    // Nothing to reconstruct and not marked collapsed → stay put.
    if (!collapsed && Object.keys(snapshot.files).length === 0 && !hasOrdinary) {
      return { type: "none" };
    }
    return { type: "remigrate", snapshot };
  }

  // Aggregate / rolled-back file module.
  if (!migrationDone) return { type: "none" };
  if (!hasOrdinary) return { type: "none" };
  const snapshot = collapseOrdinaryTabsToAggregate({
    openTabs: opts.openTabs,
    active: opts.active,
    preview: opts.preview,
    files: opts.files,
  });
  if (
    snapshot.openTabs.length === opts.openTabs.length
    && snapshot.openTabs.every((key, i) => key === opts.openTabs[i])
    && Object.keys(opts.files).length === 0
  ) {
    return { type: "none" };
  }
  return { type: "collapse", snapshot };
}
