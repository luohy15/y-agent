import { artifactSlugFromTab, artifactTabKey } from "../host/artifacts";

export interface PaletteModule {
  slug: string;
  label: string;
}

export type PaletteEntry =
  | { kind: "tab"; path: string; label: string }
  | { kind: "module"; slug: string; label: string };

export function buildPaletteEntries(
  openFiles: readonly string[],
  modules: readonly PaletteModule[],
  query: string,
): PaletteEntry[] {
  const catalog = new Map(modules.map((module) => [module.slug, module]));
  const openTabs = new Set(openFiles);
  const needle = query.trim().toLowerCase();
  const matches = (label: string, key: string) =>
    label.toLowerCase().includes(needle) || key.toLowerCase().includes(needle);
  const tabs: PaletteEntry[] = openFiles.map((path) => {
    const slug = artifactSlugFromTab(path);
    return { kind: "tab" as const, path, label: slug ? catalog.get(slug)?.label || slug : path };
  }).filter((entry) => matches(entry.label, entry.path));
  const available: PaletteEntry[] = [...catalog.values()]
    .filter((module) => !openTabs.has(artifactTabKey(module.slug)) && matches(module.label, module.slug))
    .sort((a, b) => a.label.localeCompare(b.label) || a.slug.localeCompare(b.slug))
    .map((module) => ({ kind: "module", slug: module.slug, label: module.label }));
  return [...tabs, ...available];
}
