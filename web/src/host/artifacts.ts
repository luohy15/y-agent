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

/** File module is contextual (todo 3084) when its active UI requires host contract
 * v8+ (`useDetailContext`). Aggregate file v7/v10 ignore detailContext and must
 * keep mounting once at `ui:file` until such a version is active. */
export function isContextualFileModule(artifact: MountableModule | null | undefined): boolean {
  if (!artifact?.active_version) return false;
  return (artifact.active_version.min_host_version ?? 1) >= 8;
}

// `ui_surfaces` is a comma list; absent (older host response, or a version
// published before V1) means the pre-existing panel-only default.
export function hasSurface(module: MountableModule, surface: string): boolean {
  const raw = module.active_version.ui_surfaces ?? "panel";
  return raw.split(",").map((s) => s.trim()).includes(surface);
}

// The lowest-slug enabled module claiming `shell` (D1a, todo 3042 V1). Only
// one module may occupy the shell slot at a time; a rollback to a pre-shell
// version simply drops out of this filter and releases it.
export function shellClaimant(artifacts: MountableModule[]): MountableModule | null {
  const claimants = artifacts.filter((a) => hasSurface(a, "shell"));
  if (claimants.length === 0) return null;
  return claimants.reduce((lowest, a) => (a.slug < lowest.slug ? a : lowest));
}

// Shell-slot precedence (plan-3042-chatview.md V4 + review F2):
//   0. logged-out → host always (GoogleSignInButton stays host-owned; never
//      mount a shell module or wait on the module list, even if a claimant is
//      somehow present from cache/preload)
//   1. logged-in + cold/loading module list → wait (do not mount the fallback
//      with a real chatId and open a wasted SSE before the module replaces it)
//   2. enabled shell claimant → mount the module
//   3. otherwise → ChatFallbackView
export type ShellSlotKind = "loading" | "module" | "host";

export function resolveShellSlot(opts: {
  isLoggedIn: boolean;
  uiArtifactsLoading: boolean;
  hasShellClaimant: boolean;
}): ShellSlotKind {
  if (!opts.isLoggedIn) return "host";
  if (opts.uiArtifactsLoading) return "loading";
  if (opts.hasShellClaimant) return "module";
  return "host";
}
