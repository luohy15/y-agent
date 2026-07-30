import type { ArtifactVersionRef } from "./loader";

export interface UiArtifact extends Record<string, unknown> {
  artifact_id: string;
  slug: string;
  kind: string;
  active_version_id: string | null;
  enabled: boolean;
  active_version: (ArtifactVersionRef & {
    label?: string | null;
    icon?: string | null;
  }) | null;
}

export type MountableUiArtifact = UiArtifact & {
  active_version: NonNullable<UiArtifact["active_version"]>;
};

export function mountableUiArtifacts(artifacts: UiArtifact[]): MountableUiArtifact[] {
  return artifacts.filter(
    (artifact): artifact is MountableUiArtifact =>
      artifact.enabled && artifact.kind === "panel" && artifact.active_version !== null,
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

export function artifactLabel(artifact: MountableUiArtifact): string {
  return artifact.active_version.label?.trim() || artifact.slug;
}
