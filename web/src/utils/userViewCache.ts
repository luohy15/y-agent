// Browser-local view/selection caches owned by one signed-in account
// (todo 4468 privacy rule). Logout and revoked access must not leave User A's
// chat ids, file tabs, todo selection or paths paintable by User B in the same
// browser.

import {
  HOST_FILE_DESCRIPTORS_KEY,
  HOST_WORKSPACE_OWNER_KEY,
} from "./fileWorkspace";
import { clearViewSelectionCaches, LEGACY_VIEW_SELECTION_KEYS } from "./viewSelection";

/** Keys holding the authenticated user's restored file workspace. */
export const WORKSPACE_CACHE_KEYS = [
  "openFiles",
  "activeFile",
  "previewFile",
  HOST_FILE_DESCRIPTORS_KEY,
  HOST_WORKSPACE_OWNER_KEY,
] as const;

/** Legacy per-module selection keys the y-module surfaces still read once. */
export const MODULE_LEGACY_SELECTION_KEYS = ["todoDetailId"] as const;

/**
 * y-module localStorage caches: the shared `user-preference` engine
 * (`userPrefCache:<key>`, tagged with the email inside the value) and the
 * pre-4468 view-tab cache it replaced.
 */
export const MODULE_CACHE_PREFIXES = ["userPrefCache:", "viewTabsCache:"] as const;

function removeKeys(keys: readonly string[]): void {
  for (const key of keys) {
    try {
      localStorage.removeItem(key);
    } catch {
      // Storage unavailable; there is nothing cached to leak.
    }
  }
}

function removePrefixedKeys(prefixes: readonly string[]): void {
  let keys: string[];
  try {
    keys = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key && prefixes.some((prefix) => key.startsWith(prefix))) keys.push(key);
    }
  } catch {
    return;
  }
  removeKeys(keys);
}

export function clearUserViewCaches(): void {
  removeKeys([
    ...LEGACY_VIEW_SELECTION_KEYS,
    ...WORKSPACE_CACHE_KEYS,
    ...MODULE_LEGACY_SELECTION_KEYS,
  ]);
  removePrefixedKeys(MODULE_CACHE_PREFIXES);
  clearViewSelectionCaches();
}
