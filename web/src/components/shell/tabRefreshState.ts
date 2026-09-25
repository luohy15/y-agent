import type { TabRefreshRegistry } from "../../host/tabRefresh";

/** Whether the host breadcrumb offers refresh for the active tab. Module tabs
 * always can (contract v18: refresh is generic host logic, not a module opt-in);
 * legacy special tabs keep their own targeted mechanism. Inline `artifact:`
 * tabs render a static spec and have nothing to refetch. */
export function tabRefreshVisible(hostRefreshable: boolean, isModuleTab: boolean): boolean {
  return hostRefreshable || isModuleTab;
}

/** Hover text. Legacy special tabs keep "Refresh file". */
export function tabRefreshTitle(hostRefreshable: boolean): string {
  return hostRefreshable ? "Refresh file" : "Refresh";
}

export const TAB_REFRESH_DIRTY_CONFIRM =
  "This tab has unsaved changes. Refreshing discards them. Refresh anyway?";

/** The generic module-tab refresh: revalidate everything this tab subscribes
 * to, then remount it.
 *
 * The draft guard runs **before** either stage, not between them. Revalidation
 * is not inherently lossless: a refreshed payload that no longer contains the
 * edited record makes the surface swap the editor for its unavailable branch,
 * which destroys the draft and clears the dirty report - so a confirm asked
 * afterwards is either too late or never shown. Cancelling therefore leaves
 * both stages unstarted.
 *
 * After acceptance the remount still waits for stage 1 to settle, because the
 * root abort middleware cancels in-flight fetches on unmount. `confirm` is
 * injected so tests need no window stub. */
export async function scopedTabRefresh(
  registry: TabRefreshRegistry | undefined,
  remount: () => void,
  confirm: (message: string) => boolean = (message) => window.confirm(message),
): Promise<void> {
  if (!registry) return;
  if (registry.isDirty() && !confirm(TAB_REFRESH_DIRTY_CONFIRM)) return;
  await registry.revalidateAll();
  remount();
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
