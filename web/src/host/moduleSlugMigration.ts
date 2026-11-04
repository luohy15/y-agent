import { modulesFromPayload } from "./artifacts";

export function hasEnabledFood(modules: unknown): boolean {
  return modulesFromPayload(modules).some((module) => module.slug === "food" && module.enabled);
}

export function migrateFoodTabs<T extends { openTabs: string[]; active: string | null; preview: string | null }>(
  snapshot: T,
  modules: unknown,
): T {
  if (!hasEnabledFood(modules)) return snapshot;
  const rename = (path: string | null) => path === "ui:eat" ? "ui:food" : path;
  if (!snapshot.openTabs.includes("ui:eat") && snapshot.active !== "ui:eat" && snapshot.preview !== "ui:eat") return snapshot;
  return {
    ...snapshot,
    openTabs: [...new Set(snapshot.openTabs.map((path) => path === "ui:eat" ? "ui:food" : path))],
    active: rename(snapshot.active),
    preview: rename(snapshot.preview),
  };
}
