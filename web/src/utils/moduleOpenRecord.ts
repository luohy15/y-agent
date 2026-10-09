// Host command `module.openRecord` (todo 3838, browser contract v25).
// Opens one record in a module's existing detail tab and latches an in-memory
// intent. The generic command checks only the current catalog (enabled, has a
// detail UI) and bounded type/id; it needs no tag carrier or title. The
// `tag.open` adapter below adds the hydrated-title and declared-carrier rules.
// Nothing here persists the id or bypasses the module's own API authorization.

import { artifactTabKey } from "../host/artifacts";
import { getArtifactIntent, setArtifactIntent } from "../host/intents";

export interface ModuleCatalogRow {
  slug: string;
  enabled: boolean;
  hasDetail: boolean;
  carriers?: readonly string[];
}

export interface ModuleRecordTarget {
  slug: string;
  type: string;
  id: string;
  tab: `ui:${string}`;
}

const ID_LIMIT = 128;

export function resolveModuleOpenRecord(input: {
  slug: unknown;
  type: unknown;
  id: unknown;
  catalog: readonly ModuleCatalogRow[];
}): ModuleRecordTarget | null {
  if (typeof input.slug !== "string" || !input.slug.trim()) return null;
  if (typeof input.type !== "string" || !input.type.trim() || input.type.length > 32) return null;
  if (typeof input.id !== "string" || !input.id.trim() || input.id.length > ID_LIMIT) return null;
  const slug = input.slug.trim();
  const row = input.catalog.find((item) => item.slug === slug);
  if (!row || row.enabled !== true || row.hasDetail !== true) return null;
  return {
    slug: row.slug,
    type: input.type.trim(),
    id: input.id,
    tab: artifactTabKey(row.slug),
  };
}

export function resolveTagOpenRecord(input: {
  entityType: string;
  id: unknown;
  title: unknown;
  catalog: readonly ModuleCatalogRow[];
}): ModuleRecordTarget | null {
  if (typeof input.title !== "string" || !input.title.trim()) return null;
  const owner = input.catalog.find(
    (row) => row.enabled === true && row.hasDetail === true && (row.carriers || []).includes(input.entityType),
  );
  if (!owner) return null;
  return resolveModuleOpenRecord({
    slug: owner.slug,
    type: input.entityType,
    id: input.id,
    catalog: input.catalog,
  });
}

export function latchModuleOpenRecord(
  target: ModuleRecordTarget,
  now: () => number = Date.now,
): void {
  const previous = getArtifactIntent(target.slug);
  const base = previous && typeof previous === "object" ? { ...(previous as Record<string, unknown>) } : {};
  setArtifactIntent(target.slug, {
    ...base,
    openRecord: { type: target.type, id: target.id, nonce: now() },
  });
}

/** The registered `module.openRecord` handler: validate, latch, open. */
export function runModuleOpenRecord(
  payload: unknown,
  catalog: readonly ModuleCatalogRow[],
  openTab: (tab: `ui:${string}`) => void,
): boolean {
  if (!payload || typeof payload !== "object") return false;
  const raw = payload as { slug?: unknown; type?: unknown; id?: unknown };
  const target = resolveModuleOpenRecord({ slug: raw.slug, type: raw.type, id: raw.id, catalog });
  if (!target) return false;
  latchModuleOpenRecord(target);
  openTab(target.tab);
  return true;
}
