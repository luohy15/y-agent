import type { Cache } from "swr";

// v2 adds { savedAt, entries } + a per-entry size cap; v1 was a bare
// JSON-encoded entries array with no cap, which let a single multi-MB entry
// (see DENYLIST_SUBSTRINGS) blow the localStorage quota and freeze every
// later flush behind a silent QuotaExceededError.
const STORAGE_KEY = "y-agent-swr-cache-v2";
const LEGACY_STORAGE_KEY = "y-agent-swr-cache-v1";

// Large/streaming payloads that should never be persisted (checked by
// substring so new paths under these prefixes are covered automatically).
const DENYLIST_SUBSTRINGS = ["/api/chat/messages", "/api/file/", "/api/trace/chats"];

// Durable guard against the denylist drifting again: skip any entry whose
// serialized form exceeds this, regardless of path. Comfortably above a
// several-page todo/email list aggregate (~100-200 KB), well below the
// ~5 MB per-origin quota.
const MAX_ENTRY_BYTES = 512 * 1024;

// A frozen/abandoned snapshot is served forever with no staleness bound
// otherwise; discard on seed past this age.
const SNAPSHOT_TTL_MS = 24 * 60 * 60 * 1000;

interface Snapshot {
  savedAt: number;
  entries: Array<[string, unknown]>;
}

function isDenylisted(key: string): boolean {
  return DENYLIST_SUBSTRINGS.some((s) => key.includes(s));
}

function loadEntries(): Iterable<[string, unknown]> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Partial<Snapshot> | null;
    if (typeof parsed?.savedAt !== "number" || !Array.isArray(parsed.entries)) return [];
    if (Date.now() - parsed.savedAt > SNAPSHOT_TTL_MS) return [];
    return parsed.entries;
  } catch {
    return [];
  }
}

function flush(map: Map<string, unknown>): void {
  const fragments: string[] = [];
  for (const [key, state] of map.entries()) {
    if (isDenylisted(key)) continue;
    const data = (state as { data?: unknown } | undefined)?.data;
    if (data === undefined) continue;

    let fragment: string;
    try {
      fragment = JSON.stringify([key, state]);
    } catch {
      continue; // non-serializable value snuck in — skip just this entry
    }
    if (fragment.length > MAX_ENTRY_BYTES) continue;
    fragments.push(fragment);
  }

  // Build the payload from the already-serialized fragments instead of
  // JSON.stringify-ing the assembled array again.
  const payload = `{"savedAt":${Date.now()},"entries":[${fragments.join(",")}]}`;
  try {
    localStorage.setItem(STORAGE_KEY, payload);
  } catch {
    // Still over quota — self-heal by dropping the persisted snapshot
    // instead of freezing on a stale one (matches pre-pilot behavior).
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    console.warn("swrPersistedCache: flush exceeded storage quota, cleared persisted cache");
  }
}

// SWR's documented localStorage cache recipe: seed a Map synchronously so the
// first render already has last-known-good data, then flush it back before
// the tab goes away.
export function localStorageProvider(): Cache {
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    // ignore
  }

  const map = new Map<string, unknown>(loadEntries());

  const onFlush = () => flush(map);
  window.addEventListener("beforeunload", onFlush);
  window.addEventListener("pagehide", onFlush);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") onFlush();
  });

  return map as unknown as Cache;
}

export const __test__ = { STORAGE_KEY, LEGACY_STORAGE_KEY, MAX_ENTRY_BYTES, SNAPSHOT_TTL_MS, loadEntries, flush };
