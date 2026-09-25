// Universal host-owned tab refresh (browser contract v18, todo 3674).
//
// Every `ui:<slug>` detail tab gets a refresh control with no module
// cooperation: the host wraps the mount in a per-tab registry plus a nested
// `<SWRConfig use={[trackTabRefreshTargets]}>`, and refresh runs two stages.
//
// Stage 1 -- revalidate. The middleware records each SWR hook's *bound*
// `mutate` while that hook is mounted inside this tab. Refresh awaits all of
// them. A bound mutate is the only escape hatch that actually refetches:
// mount-time revalidation is `revalidate(WITH_DEDUPE)` and is skipped outright
// while `FETCH[key]` is set (swr 2.4.0 `dist/index/index.mjs:534,568-580`), and
// is not even attempted when the key holds an error and another subscriber is
// still mounted (`:314`) -- which is exactly the state a user clicks refresh
// in. MUTATE_EVENT calls `revalidate()` with no opts (`:553`), so
// `shouldStartNewRequest` is true regardless of dedupe (`:340`). Recording the
// bound mutate rather than the key also covers `useSWRInfinite`, whose bound
// mutate revalidates every loaded page.
//
// Stage 2 -- remount. Surfaces that fetch in a plain `useEffect` hold no SWR
// key at all, so the host bumps the tab's nonce and the detail subtree
// remounts. Stage 2 runs *after* stage 1 settles: the root `abortMiddleware`
// aborts in-flight fetches on unmount, so remounting first would cancel the
// revalidation it just started.
//
// Neither stage is lossless, so `useTabDirty` is asked before *both* of them
// (see `scopedTabRefresh`): a revalidation whose fresh payload no longer
// contains the edited record makes the surface swap the editor out, which
// destroys the draft before any confirm could have run.
//
// Scope is the tab subtree: only keys this tab subscribed to are revalidated.
import { createContext, createElement, useContext, useEffect, useRef, type ReactNode } from "react";
import type { Middleware, SWRConfiguration } from "swr";

/** Per-tab collection of what a refresh has to touch. One instance per open
 * detail tab, owned by the host tab chrome (FileViewer / DemoShell). */
export interface TabRefreshRegistry {
  /** Record a bound `mutate` for the life of one mounted SWR hook. */
  registerMutate: (mutate: () => unknown) => () => void;
  /** Record a draft reader for the life of one mounted `useTabDirty` call. */
  registerDirty: (read: () => boolean) => () => void;
  /** Stage 1: refetch every key this tab currently subscribes to. */
  revalidateAll: () => Promise<void>;
  /** Whether any mounted surface in this tab reports an unsaved draft. */
  isDirty: () => boolean;
}

export function createTabRefreshRegistry(): TabRefreshRegistry {
  const mutates = new Set<() => unknown>();
  const dirtyReaders = new Set<() => boolean>();
  return {
    registerMutate(mutate) {
      mutates.add(mutate);
      return () => {
        mutates.delete(mutate);
      };
    },
    registerDirty(read) {
      dirtyReaders.add(read);
      return () => {
        dirtyReaders.delete(read);
      };
    },
    async revalidateAll() {
      // Snapshot first: a revalidation can render, mount, or unmount hooks
      // while the set is being iterated. allSettled so one failing key does
      // not abandon the rest, nor the remount that follows.
      await Promise.allSettled(Array.from(mutates, (mutate) => mutate()));
    },
    isDirty() {
      for (const read of dirtyReaders) {
        if (read()) return true;
      }
      return false;
    },
  };
}

const TabRefreshRegistryContext = createContext<TabRefreshRegistry | null>(null);

export function TabRefreshRegistryProvider({
  registry,
  children,
}: {
  registry: TabRefreshRegistry | null;
  children: ReactNode;
}) {
  return createElement(TabRefreshRegistryContext.Provider, { value: registry }, children);
}

/** SWR middleware that records this hook's bound `mutate` with the enclosing
 * tab registry. Installed by the host, never by a module. Outside a registry
 * (panel surfaces, the app shell, tests) it is a pass-through. */
export const trackTabRefreshTargets: Middleware = (useSWRNext) => (key, fetcher, config) => {
  const swr = useSWRNext(key, fetcher, config);
  const registry = useContext(TabRefreshRegistryContext);
  // `swr.mutate` is a plain property on both the base and the infinite
  // response; `data` / `error` are getters, so the object is returned
  // untouched rather than spread.
  const mutateRef = useRef(swr.mutate);
  mutateRef.current = swr.mutate;
  useEffect(() => {
    if (!registry) return;
    return registry.registerMutate(() => mutateRef.current());
  }, [registry]);
  return swr;
};

/** Nested SWR config the host installs around every detail mount. Module-level
 * constant so the `SWRConfig` value identity is stable; no `provider`, so the
 * persisted cache and cross-panel `mutate` are inherited from the root. */
export const TAB_REFRESH_SWR_CONFIG: SWRConfiguration = { use: [trackTabRefreshTargets] };

/** Report an unsaved draft in this detail surface (contract v18). While this
 * is true the host confirms before it starts a refresh at all, and cancelling
 * leaves both the revalidation and the remount unstarted. Not a capability
 * gate: the control renders whether or not a module calls this, and refresh
 * works on a module that never calls it. No-op outside a detail surface. */
export function useTabDirty(dirty: boolean): void {
  const registry = useContext(TabRefreshRegistryContext);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  useEffect(() => {
    if (!registry) return;
    return registry.registerDirty(() => dirtyRef.current);
  }, [registry]);
}

/** Deprecated no-op (contract v17 registration channel, superseded in v18).
 * Refresh is now generic host logic on every module tab, so there is nothing
 * to register. Kept only because tag v20 / todo v26 / bot v49 are still
 * rollback-reachable and call it; removal is a follow-up once they are not. */
export function useTabRefresh(
  handler: (() => void | PromiseLike<unknown>) | null,
  options?: { title?: string },
): void {
  void handler;
  void options;
}
