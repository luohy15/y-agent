// Per-user activity-bar pins (todo 3869, supersedes the 3676 deny-list).
// Presentation only: a pinned slug shows its left-rail icon. It does not enable
// or disable the module, drop it from discovery, or change activityBarOrder.
// Absence/null means nothing pinned (no seeding). The legacy
// 3676 deny-list row is never read or written, so a host rollback
// restores the old rail exactly.

export const ACTIVITY_BAR_PINNED_MODULES_KEY = "activityBarPinnedModules";
/** The Modules manager is always on the rail so recovery never depends on a pin. */
export const ALWAYS_PINNED_SLUG = "module";

export interface ActivityBarVisibilityState {
  pinnedSlugs: string[];
  /** Derived for module <= v15: authorized - pinned - `module`. */
  hiddenSlugs: string[];
  loaded: boolean;
  saving: boolean;
  error: string | null;
}

export function normalizePinnedSlugs(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of value) {
    if (typeof item !== "string") continue;
    const slug = item.trim();
    if (!slug || seen.has(slug)) continue;
    seen.add(slug);
    result.push(slug);
  }
  return result;
}

/** Keep `artifact:<slug>` keys only for pinned slugs (and `module`). Non-module keys stay. */
export function projectActivityBarOrder(order: readonly string[], pinnedSlugs: readonly string[]): string[] {
  const pinned = new Set(pinnedSlugs);
  return order.filter((key) => {
    if (!key.startsWith("artifact:")) return true;
    const slug = key.slice("artifact:".length);
    return slug === ALWAYS_PINNED_SLUG || pinned.has(slug);
  });
}

export function samePinnedSlugs(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((slug, index) => slug === b[index]);
}

export function withSlugPinned(pinnedSlugs: readonly string[], slug: string, pinned: boolean): string[] {
  const next = pinnedSlugs.filter((item) => item !== slug);
  if (pinned) next.push(slug);
  return next;
}

export function deriveHiddenSlugs(authorizedSlugs: Iterable<string>, pinnedSlugs: readonly string[]): string[] {
  const pinned = new Set(pinnedSlugs);
  return Array.from(authorizedSlugs).filter((slug) => slug !== ALWAYS_PINNED_SLUG && !pinned.has(slug));
}
