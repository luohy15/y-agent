// Mobile content-drawer open/close (todo 3960). One surface is active at a
// time: the activity-bar launcher, the left content drawer, or the right
// content drawer. Opening one closes the others, so a closed drawer cannot
// sit behind the one that replaced it and reappear when that one closes.

export type MobileSurfaceName = "activity" | "left" | "right";

export type MobileSurfaces = Record<MobileSurfaceName, boolean>;

export type MobileSurfaceAction =
  | { type: "toggle" | "open" | "close"; surface: MobileSurfaceName }
  | { type: "close-content" }
  | { type: "close-all" };

const NONE: MobileSurfaces = { activity: false, left: false, right: false };

export function reconcileMobileSurfaces(current: MobileSurfaces, action: MobileSurfaceAction): MobileSurfaces {
  if (action.type === "close-all") return { ...NONE };
  if (action.type === "close-content") return { ...current, left: false, right: false };
  if (action.type === "close") return { ...current, [action.surface]: false };
  if (action.type === "open") return { ...NONE, [action.surface]: true };
  if (current[action.surface]) return { ...current, [action.surface]: false };
  return { ...NONE, [action.surface]: true };
}

/** Content drawers use the existing md boundary. 768 and above is desktop. */
export function drawerMode(width: number): "mobile" | "desktop" {
  return width < 768 ? "mobile" : "desktop";
}

/**
 * The desktop right pane is shown from the existing 640px breakpoint and is
 * covered by the mobile content drawer until 768px. It must not take input
 * while that drawer is open. This does not change either breakpoint.
 */
export function desktopRightBlocked(width: number, mobileRightOpen: boolean): boolean {
  return mobileRightOpen && width >= 640 && width < 768;
}

export type HostNavigationKind =
  | "todo-open"
  | "tag-navigate"
  | "file-preview"
  | "artifact-open"
  | "ordinary-file"
  | "chat-select"
  | "diff-file";

/** Which mobile surface a host navigation closes. Desktop callers still guard on width. */
export function surfaceActionForHostNavigation(kind: HostNavigationKind): MobileSurfaceAction {
  if (kind === "ordinary-file" || kind === "diff-file") return { type: "close-content" };
  if (kind === "chat-select") return { type: "close", surface: "right" };
  return { type: "close", surface: "left" };
}
