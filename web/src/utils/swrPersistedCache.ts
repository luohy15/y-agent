import type { Cache } from "swr";

// Bump the suffix to invalidate the persisted cache after a shape change,
// instead of writing migration code.
const STORAGE_KEY = "y-agent-swr-cache-v1";

// Large/streaming payloads that should never be persisted (checked by
// substring so new paths under these prefixes are covered automatically).
const DENYLIST_SUBSTRINGS = ["/api/chat/messages", "/api/file/"];

function isDenylisted(key: string): boolean {
  return DENYLIST_SUBSTRINGS.some((s) => key.includes(s));
}

function loadEntries(): Iterable<[string, unknown]> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function flush(map: Map<string, unknown>): void {
  try {
    const entries = Array.from(map.entries()).filter(([key, state]) => {
      if (isDenylisted(key)) return false;
      const data = (state as { data?: unknown } | undefined)?.data;
      return data !== undefined;
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Quota exceeded or a non-serializable value snuck in — skip this flush,
    // same as today's in-memory-only behavior.
  }
}

// SWR's documented localStorage cache recipe: seed a Map synchronously so the
// first render already has last-known-good data, then flush it back before
// the tab goes away.
export function localStorageProvider(): Cache {
  const map = new Map<string, unknown>(loadEntries());

  const onFlush = () => flush(map);
  window.addEventListener("beforeunload", onFlush);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") onFlush();
  });

  return map as unknown as Cache;
}
