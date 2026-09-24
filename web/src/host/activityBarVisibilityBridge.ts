// Host side of the todo 3676 module bridge. The module list never calls the
// preference API itself: it reads `activityBarVisibility` off the latched
// `module` intent and sends a desired-state command back.

import { registerHostCommand } from "./commands";
import { getArtifactIntent, setArtifactIntent } from "./intents";
import { sameHiddenSlugs, type ActivityBarVisibilityState } from "../utils/activityBarVisibility";

export interface ActivityBarVisibilityCommandTarget {
  hiddenSlugs: readonly string[];
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
  if (!Array.isArray(state.hiddenSlugs) || typeof state.loaded !== "boolean" || typeof state.saving !== "boolean") return null;
  return {
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
    && sameHiddenSlugs(current.hiddenSlugs, state.hiddenSlugs)
    && current.loaded === state.loaded
    && current.saving === state.saving
    && current.error === state.error
  ) return;
  const base = previous && typeof previous === "object" ? { ...(previous as Record<string, unknown>) } : {};
  setArtifactIntent("module", {
    ...base,
    activityBarVisibility: {
      hiddenSlugs: state.hiddenSlugs,
      loaded: state.loaded,
      saving: state.saving,
      error: state.error,
    },
  });
}

/** Register the two module commands. `authorizedSlugs` is the caller's current
 * module list (not the mountable subset): a disabled module can still keep a
 * visibility preference for the next time it is enabled. */
export function registerActivityBarVisibilityCommands(
  target: ActivityBarVisibilityCommandTarget,
  authorizedSlugs: ReadonlySet<string>,
): () => void {
  const unregisterSet = registerHostCommand("module.setActivityBarVisibility", (payload) => {
    if (!payload || typeof payload !== "object") return;
    const { slug, visible } = payload as { slug?: unknown; visible?: unknown };
    if (typeof slug !== "string" || typeof visible !== "boolean") return;
    if (!authorizedSlugs.has(slug)) return;
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
