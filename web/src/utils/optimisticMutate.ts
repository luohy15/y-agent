import type { Cache, ScopedMutator } from "swr";

export type CacheKeyMatcher = string | RegExp | ((key: string) => boolean);

// The bound cache + mutator from `useSWRConfig()`. Must come from that hook
// (not the top-level `swr` import): this app configures a custom (persisted
// localStorage) cache provider, and the top-level singletons are bound to
// SWR's separate default in-memory cache that no component actually reads.
export interface SWRCacheHandle {
  cache: Cache;
  mutate: ScopedMutator;
}

function toMatcherFn(matcher: CacheKeyMatcher): (key: string) => boolean {
  if (typeof matcher === "function") return matcher;
  if (matcher instanceof RegExp) return (key) => matcher.test(key);
  return (key) => key.includes(matcher);
}

function patchItem<T>(item: T, idKey: keyof T, id: string, patch: Partial<T>): T {
  return item != null && (item as any)[idKey] === id ? { ...item, ...patch } : item;
}

// Applies `patch` to the item matching `id` across the three cache shapes
// todos (and similar list resources) can be stored under: useSWRInfinite
// pages (T[][]), plain arrays (single-status queries), and a single detail
// object.
export function applyItemPatch<T>(data: unknown, idKey: keyof T, id: string, patch: Partial<T>): unknown {
  if (Array.isArray(data)) {
    if (data.length > 0 && Array.isArray(data[0])) {
      return (data as T[][]).map((page) => page.map((item) => patchItem(item, idKey, id, patch)));
    }
    return (data as T[]).map((item) => patchItem(item, idKey, id, patch));
  }
  if (data && typeof data === "object") {
    return patchItem(data as T, idKey, id, patch);
  }
  return data;
}

/**
 * Optimistic-then-reconcile helper for resources that live in multiple
 * overlapping SWR cache entries (e.g. a todo appears in table pages, kanban
 * per-status queries, and its own detail view simultaneously).
 *
 * 1. Synchronously patches every cache entry whose key matches `matcher`.
 * 2. Fires `request`.
 * 3. Regardless of the outcome, revalidates every matching key so the
 *    eventual server truth corrects any wrong optimistic state.
 *
 * Keys are mutated one-by-one via their exact key rather than SWR's
 * filter-function `mutate(matcherFn, ...)` overload: that overload silently
 * skips `useSWRInfinite`/`useSWRSubscription` cache entries (SWR internal
 * convention), which would make table-view (`useSWRInfinite`) rows never
 * patch. Exact-key mutation has no such exclusion.
 */
export async function optimisticListMutate<T>(
  swr: SWRCacheHandle,
  matcher: CacheKeyMatcher,
  idKey: keyof T,
  id: string,
  patch: Partial<T>,
  request: () => Promise<unknown>,
): Promise<void> {
  const matcherFn = toMatcherFn(matcher);
  const keys = Array.from(swr.cache.keys()).filter(matcherFn);
  const updater = (current: unknown) => (current === undefined ? current : applyItemPatch<T>(current, idKey, id, patch));

  await Promise.all(keys.map((key) => swr.mutate(key, updater, { revalidate: false })));

  try {
    await request();
  } finally {
    keys.forEach((key) => swr.mutate(key, undefined, { revalidate: true }));
  }
}
