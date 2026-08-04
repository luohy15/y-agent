import type { ArtifactVersionRef } from "./loader";

export interface Module extends Record<string, unknown> {
  module_id: string;
  slug: string;
  active_version_id: string | null;
  enabled: boolean;
  active_version: (ArtifactVersionRef & {
    label?: string | null;
    icon?: string | null;
  }) | null;
}

export type MountableModule = Module & {
  active_version: NonNullable<Module["active_version"]>;
};

export function modulesFromPayload(payload: unknown): Module[] {
  return Array.isArray(payload) ? payload : [];
}

export function mountableUiArtifacts(artifacts: unknown): MountableModule[] {
  return modulesFromPayload(artifacts).filter(
    (artifact): artifact is MountableModule =>
      artifact.enabled && !!artifact.active_version?.ui_sha256,
  );
}

export function artifactPanelKey(slug: string): `artifact:${string}` {
  return `artifact:${slug}`;
}

export function artifactTabKey(slug: string): `ui:${string}` {
  return `ui:${slug}`;
}

export function artifactSlugFromPanel(panel: string): string | null {
  return panel.startsWith("artifact:") ? panel.slice("artifact:".length) : null;
}

export function artifactSlugFromTab(path: string): string | null {
  return path.startsWith("ui:") ? path.slice("ui:".length) : null;
}

// `artifact:` (inline chat chart) tabs hold their content only in an
// in-memory map, so a restored tab would be dead; `ui:` tabs are fully
// reconstructible from their slug, so they are safe to persist.
export function isPersistableTab(path: string): boolean {
  return !path.startsWith("artifact:");
}

export function artifactLabel(artifact: MountableModule): string {
  return artifact.active_version.label?.trim() || artifact.slug;
}
