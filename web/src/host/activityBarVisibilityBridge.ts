// Host side of the todo 3676 module bridge (pin semantics since todo 3869). The module list never calls the
// preference API itself: it reads `activityBarVisibility` off the latched
// `module` intent and sends a desired-state command back.

import { registerHostCommand } from "./commands";
import { getArtifactIntent, setArtifactIntent } from "./intents";
import { ALWAYS_PINNED_SLUG, samePinnedSlugs, type ActivityBarVisibilityState } from "../utils/activityBarVisibility";

export interface ActivityBarVisibilityCommandTarget {
  pinnedSlugs: readonly string[];
  loaded: boolean;
  saving: boolean;
  error: string | null;
  setSlugVisible: (slug: string, visible: boolean) => void;
  retry: () => void;
}

function visibilityOf(intent: unknown): ActivityBarVisibilityState | null {
  if (!intent || typeof intent !== "object" || !("activityBarVisibility" in intent)) return null;
  const value = (intent as { activityBarVisibility?: unknown }).activityBarVisibility;
  if (!value || typeof value !== "object") return null;
  const state = value as Partial<ActivityBarVisibilityState>;
  if (!Array.isArray(state.pinnedSlugs) || !Array.isArray(state.hiddenSlugs) || typeof state.loaded !== "boolean" || typeof state.saving !== "boolean") return null;
  return {
    pinnedSlugs: state.pinnedSlugs.filter((slug): slug is string => typeof slug === "string"),
    hiddenSlugs: state.hiddenSlugs.filter((slug): slug is string => typeof slug === "string"),
    loaded: state.loaded,
    saving: state.saving,
    error: typeof state.error === "string" ? state.error : null,
  };
}

export function publishActivityBarVisibility(state: ActivityBarVisibilityState): void {
  const previous = getArtifactIntent("module");
  const current = visibilityOf(previous);
  if (
    current
    && samePinnedSlugs(current.pinnedSlugs, state.pinnedSlugs)
    && samePinnedSlugs(current.hiddenSlugs, state.hiddenSlugs)
    && current.loaded === state.loaded
    && current.saving === state.saving
    && current.error === state.error
  ) return;
  const base = previous && typeof previous === "object" ? { ...(previous as Record<string, unknown>) } : {};
  setArtifactIntent("module", {
    ...base,
    activityBarVisibility: {
      pinnedSlugs: state.pinnedSlugs,
      hiddenSlugs: state.hiddenSlugs,
      loaded: state.loaded,
      saving: state.saving,
      error: state.error,
    },
  });
}

/** Register the two module commands. `authorizedSlugs` is the caller's current
 * module list (not the mountable subset): a disabled module can still keep a
 * pin for the next time it is enabled. `visible: true` pins; `module` is always
 * on the rail and ignored. */
export function registerActivityBarVisibilityCommands(
  target: ActivityBarVisibilityCommandTarget,
  authorizedSlugs: ReadonlySet<string>,
): () => void {
  const unregisterSet = registerHostCommand("module.setActivityBarVisibility", (payload) => {
    if (!payload || typeof payload !== "object") return;
    const { slug, visible } = payload as { slug?: unknown; visible?: unknown };
    if (typeof slug !== "string" || typeof visible !== "boolean") return;
    if (slug === ALWAYS_PINNED_SLUG || !authorizedSlugs.has(slug)) return;
    target.setSlugVisible(slug, visible);
  });
  const unregisterRetry = registerHostCommand("module.retryActivityBarVisibility", () => {
    target.retry();
  });
  return () => {
    unregisterSet();
    unregisterRetry();
  };
}
