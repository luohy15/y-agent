import type { TabRefreshEntry } from "../../host/tabRefresh";

/** Map update for one tab's registration. `storedTitle` is the title this map
 * last accepted for `path`: the hook mutates `entry.title` before publishing,
 * so `prev[path].title` is already the new value and cannot detect the change. */
export function nextTabRefreshMap(
  prev: Record<string, TabRefreshEntry>,
  path: string,
  entry: TabRefreshEntry | null,
  storedTitle: Record<string, string | undefined>,
): Record<string, TabRefreshEntry> {
  if (entry) {
    if (prev[path] === entry && storedTitle[path] === entry.title) return prev;
    storedTitle[path] = entry.title;
    return { ...prev, [path]: entry };
  }
  if (!(path in prev)) return prev;
  delete storedTitle[path];
  const next = { ...prev };
  delete next[path];
  return next;
}

/** Whether the host breadcrumb should offer refresh for the active tab.
 * Legacy special tabs always can. A module tab can only when it registered. */
export function tabRefreshVisible(
  hostRefreshable: boolean,
  registered: TabRefreshEntry | undefined,
): boolean {
  return hostRefreshable || !!registered;
}

/** The handler the control should call, or null when there is nothing to do. */
export function tabRefreshAction(
  registered: TabRefreshEntry | undefined,
  hostRefresh: (() => void) | null,
): (() => void | Promise<void>) | null {
  if (registered) return registered.handler;
  return hostRefresh;
}

/** Hover text. A registration's title wins. Legacy special tabs keep "Refresh file". */
export function tabRefreshTitle(
  registered: TabRefreshEntry | undefined,
  hostRefreshable: boolean,
): string {
  if (registered?.title) return registered.title;
  if (hostRefreshable) return "Refresh file";
  return "Refresh";
}

export const TAB_REFRESH_MIN_SPIN_MS = 600;

/** Run a refresh and report done only after the handler settles and the spin
 * has been visible for at least TAB_REFRESH_MIN_SPIN_MS. */
export function runTabRefresh(
  run: () => void | Promise<void>,
  onDone: () => void,
): void {
  const started = Date.now();
  Promise.resolve()
    .then(() => run())
    .catch(() => {})
    .finally(() => {
      const wait = Math.max(0, TAB_REFRESH_MIN_SPIN_MS - (Date.now() - started));
      setTimeout(onDone, wait);
    });
}
