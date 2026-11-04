import type { ArtifactVersionRef } from "./loader";

export interface Module extends Record<string, unknown> {
  module_id: string;
  slug: string;
  active_version_id: string | null;
  enabled: boolean;
  active_version: (ArtifactVersionRef & {
    label?: string | null;
    icon?: string | null;
    tag_carriers?: string[] | null;
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

// Last successful enabled-module list. A restored `ui:` tab can render before
// that list resolves (logged out, cold load, or a failed fetch). Live label
// still wins; the slug remains the last resort when nothing was ever cached.
const UI_MODULE_LABELS_KEY = "uiModuleLabels.v1";
const UI_MODULE_LABEL_CACHE_CAP = 200;

function labelRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

export function readUiModuleLabelCache(): Record<string, string> {
  try {
    const raw = localStorage.getItem(UI_MODULE_LABELS_KEY);
    if (!raw) return {};
    const parsed = labelRecord(JSON.parse(raw));
    if (!parsed) return {};
    const out: Record<string, string> = {};
    for (const [slug, label] of Object.entries(parsed)) {
      if (Object.keys(out).length >= UI_MODULE_LABEL_CACHE_CAP) break;
      if (!slug.trim() || typeof label !== "string") continue;
      const trimmed = label.trim();
      if (!trimmed) continue;
      out[slug] = trimmed;
    }
    return out;
  } catch {
    return {};
  }
}

export function rememberUiModuleLabels(artifacts: unknown): void {
  const labels: Record<string, string> = {};
  for (const artifact of mountableUiArtifacts(artifacts)) {
    if (Object.keys(labels).length >= UI_MODULE_LABEL_CACHE_CAP) break;
    const slug = artifact.slug.trim();
    const label = artifact.active_version.label?.trim() ?? "";
    if (!slug || !label) continue;
    labels[slug] = label;
  }
  if (modulesFromPayload(artifacts).some((artifact) => artifact.slug === "food" && artifact.enabled)) {
    delete labels.eat;
  }
  try {
    localStorage.setItem(UI_MODULE_LABELS_KEY, JSON.stringify(labels));
  } catch {
    // Private mode or a full quota. The live label still renders this session.
  }
}

export function resolveArtifactTabLabel(
  path: string,
  artifacts: readonly MountableModule[],
  cached: Record<string, string>,
): string {
  const slug = artifactSlugFromTab(path);
  if (!slug) return "ui";
  const live = artifacts.find((item) => item.slug === slug)?.active_version.label?.trim();
  if (live) return live;
  const cachedLabel = cached[slug]?.trim();
  if (cachedLabel) return cachedLabel;
  return slug;
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
