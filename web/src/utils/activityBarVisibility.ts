// Per-user activity-bar visibility (todo 3676). Presentation only: a slug in
// this set hides its left-rail icon. It does not disable the module, drop it
// from discovery, or change activityBarOrder. Absence/null means nothing hidden.

export const ACTIVITY_BAR_HIDDEN_MODULES_KEY = "activityBarHiddenModules";

export interface ActivityBarVisibilityState {
  hiddenSlugs: string[];
  loaded: boolean;
  saving: boolean;
  error: string | null;
}

export function normalizeHiddenSlugs(value: unknown): string[] {
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

/** Drop `artifact:<slug>` keys whose slug is hidden. Non-module keys stay. */
export function projectActivityBarOrder(order: readonly string[], hiddenSlugs: readonly string[]): string[] {
  if (hiddenSlugs.length === 0) return order.slice();
  const hidden = new Set(hiddenSlugs);
  return order.filter((key) => {
    if (!key.startsWith("artifact:")) return true;
    return !hidden.has(key.slice("artifact:".length));
  });
}

export function sameHiddenSlugs(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((slug, index) => slug === b[index]);
}

export function withSlugVisibility(hiddenSlugs: readonly string[], slug: string, visible: boolean): string[] {
  const next = hiddenSlugs.filter((item) => item !== slug);
  if (!visible) next.push(slug);
  return next;
}
