import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createTabRefreshRegistry, type TabRefreshRegistry } from "../../host/tabRefresh";
import { runTabRefresh, scopedTabRefresh } from "./tabRefreshState";

/** Per-key refresh chrome state, shared by every host-owned refresh control
 * (todo 3674 centre tabs, todo 3680 sidebar panels, and the demo shell's
 * single detail slot). One registry + remount nonce + spin flag per key, with
 * one timer/in-flight authority per key so a second click inside the same
 * refresh is a no-op rather than a second concurrent run. Registries and
 * nonces for a key that drops out of `activeKeys` are dropped on the next
 * render, never on a refresh click. */
export interface TabRefreshChrome {
  registryFor(key: string): TabRefreshRegistry;
  nonceFor(key: string): number;
  isRefreshing(key: string): boolean;
  /** Run an arbitrary refresh action for `key` (a legacy special tab's own
   * targeted invalidation), tracked the same way as `triggerScoped`. */
  trigger(key: string, run: () => void | Promise<void>): void;
  /** The generic two-stage refresh for `key`: revalidate everything its
   * registry recorded, then bump its nonce to remount the subtree. Guarded by
   * the same dirty-draft confirm as the centre-tab mechanism. Appropriate for
   * a module mount, which may opt into the guard via `useTabDirty`. */
  triggerScoped(key: string, confirm?: (message: string) => boolean): void;
  /** Stage 1 only: revalidate everything `key`'s registry recorded, with no
   * remount. For a host-owned surface whose local React state (filters,
   * pagination, an open form) a remount would destroy, and which has no way
   * to call the module-facing `useTabDirty` guard. */
  triggerRevalidateOnly(key: string): void;
}

function pruneStale<T>(prev: Record<string, T>, open: ReadonlySet<string>): Record<string, T> {
  const stale = Object.keys(prev).filter((key) => !open.has(key));
  if (stale.length === 0) return prev;
  const next = { ...prev };
  for (const key of stale) delete next[key];
  return next;
}

export function useTabRefreshChrome(activeKeys: readonly string[]): TabRefreshChrome {
  const registries = useRef<Map<string, TabRefreshRegistry>>(new Map());
  const [nonces, setNonces] = useState<Record<string, number>>({});
  const [refreshing, setRefreshing] = useState<Record<string, boolean>>({});
  const refreshingRef = useRef(refreshing);
  refreshingRef.current = refreshing;

  // Keyed on a stable signature: an array literal re-created every render
  // would otherwise re-run the prune effect (and its state updates) each
  // time. "\n" cannot occur inside a key derived from a VM path or panel id,
  // unlike a plain space.
  const keySignature = activeKeys.join("\n");
  useEffect(() => {
    const open = new Set(activeKeys);
    for (const key of registries.current.keys()) {
      if (!open.has(key)) registries.current.delete(key);
    }
    setNonces((prev) => pruneStale(prev, open));
    setRefreshing((prev) => pruneStale(prev, open));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keySignature]);

  const registryFor = useCallback((key: string): TabRefreshRegistry => {
    let registry = registries.current.get(key);
    if (!registry) {
      registry = createTabRefreshRegistry();
      registries.current.set(key, registry);
    }
    return registry;
  }, []);

  const trigger = useCallback((key: string, run: () => void | Promise<void>) => {
    if (refreshingRef.current[key]) return;
    setRefreshing((prev) => ({ ...prev, [key]: true }));
    runTabRefresh(run, () => {
      setRefreshing((prev) => {
        if (!prev[key]) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      });
    });
  }, []);

  const triggerScoped = useCallback(
    (key: string, confirm?: (message: string) => boolean) => {
      trigger(key, () =>
        scopedTabRefresh(
          registries.current.get(key),
          () => setNonces((prev) => ({ ...prev, [key]: (prev[key] ?? 0) + 1 })),
          confirm,
        ),
      );
    },
    [trigger],
  );

  const triggerRevalidateOnly = useCallback(
    (key: string) => {
      // `run`'s return type is `void | Promise<void>`, so a missing registry
      // (nothing has mounted under this key yet) resolving to `undefined`
      // needs no `?? Promise.resolve()` fallback.
      trigger(key, () => registries.current.get(key)?.revalidateAll());
    },
    [trigger],
  );

  const nonceFor = useCallback((key: string) => nonces[key] ?? 0, [nonces]);
  const isRefreshing = useCallback((key: string) => !!refreshing[key], [refreshing]);

  return useMemo(
    () => ({ registryFor, nonceFor, isRefreshing, trigger, triggerScoped, triggerRevalidateOnly }),
    [registryFor, nonceFor, isRefreshing, trigger, triggerScoped, triggerRevalidateOnly],
  );
}
