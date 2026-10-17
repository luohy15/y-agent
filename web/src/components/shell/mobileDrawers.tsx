import { forwardRef, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode, type Ref } from "react";
import { drawerMode } from "./mobileSurface";

export const CONTENT_DRAWER_CLASS = "y-content-drawer";
export const CONTENT_DRAWER_BODY_CLASS = "y-content-drawer-body";

export function useViewportWidth(): number {
  const [width, setWidth] = useState(() => (typeof window === "undefined" ? 1024 : window.innerWidth));
  useEffect(() => {
    const read = () => setWidth(window.innerWidth);
    window.addEventListener("resize", read);
    const mql = window.matchMedia?.("(max-width: 767px)");
    mql?.addEventListener?.("change", read);
    read();
    return () => {
      window.removeEventListener("resize", read);
      mql?.removeEventListener?.("change", read);
    };
  }, []);
  return width;
}

/**
 * Mobile-only focus entry, Escape dismissal, and background scroll/interaction
 * isolation. Cleanup runs on close, unmount, and when the surface becomes null
 * (including a resize to desktop).
 *
 * Escape ownership is a snapshot, not a focus check. A module menu can be an
 * unmarked fixed body portal whose document listener runs during this event and
 * may leave focus inside the drawer. Window capture records whether another
 * body branch already holds an interactive overlay. Window bubble closes the
 * drawer only when that same event had no overlay and nothing else consumed it.
 * The host never stops the event or removes the overlay.
 */
export function useContentDrawerLifecycle(opts: {
  surface: "left" | "right" | null;
  onClose: () => void;
}) {
  const onCloseRef = useRef(opts.onClose);
  onCloseRef.current = opts.onClose;
  const surface = opts.surface;
  useEffect(() => {
    if (!surface) return;
    const drawer = document.querySelector<HTMLElement>(`[data-content-drawer="${surface}"]`);
    const backgrounds = Array.from(document.querySelectorAll<HTMLElement>("[data-drawer-background]"));
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    for (const node of backgrounds) node.inert = true;
    drawer?.querySelector<HTMLElement>("[data-drawer-close]")?.focus();
    const overlayAtCapture = new WeakMap<Event, boolean>();
    const onCapture = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      overlayAtCapture.set(event, externalInteractiveOverlay(drawer));
    };
    const onBubble = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (overlayAtCapture.get(event)) return;
      onCloseRef.current();
    };
    window.addEventListener("keydown", onCapture, true);
    window.addEventListener("keydown", onBubble);
    return () => {
      document.body.style.overflow = previousOverflow;
      for (const node of backgrounds) node.inert = false;
      window.removeEventListener("keydown", onCapture, true);
      window.removeEventListener("keydown", onBubble);
      if (previouslyFocused && document.contains(previouslyFocused)) previouslyFocused.focus();
    };
  }, [surface]);
}

const INTERACTIVE = "button, a[href], input, select, textarea, [role='menuitem'], [role='menu'], [role='dialog']";

function concealed(node: Element): boolean {
  for (let current: Element | null = node; current; current = current.parentElement) {
    if ((current instanceof HTMLElement && current.inert) || current.getAttribute("aria-hidden") === "true") return true;
    if (current instanceof HTMLElement && current.hidden) return true;
    const style = window.getComputedStyle(current);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") return true;
  }
  return false;
}

function interactiveControl(node: Element): boolean {
  const candidates = node.matches(INTERACTIVE) ? [node] : Array.from(node.querySelectorAll(INTERACTIVE));
  return candidates.some((candidate) => {
    if (concealed(candidate)) return false;
    if (candidate instanceof HTMLButtonElement || candidate instanceof HTMLInputElement || candidate instanceof HTMLSelectElement || candidate instanceof HTMLTextAreaElement) {
      return !candidate.disabled;
    }
    return true;
  });
}

/** A visible interactive overlay in a body branch other than the one holding the drawer. */
export function externalInteractiveOverlay(drawer: HTMLElement | null): boolean {
  const appBranch = drawer ? bodyBranch(drawer) : null;
  for (const branch of Array.from(document.body.children)) {
    if (branch === appBranch || branch instanceof HTMLScriptElement || branch instanceof HTMLStyleElement) continue;
    if (concealed(branch)) continue;
    const positioned = positionedNodes(branch);
    if (positioned.some((node) => interactiveControl(node))) return true;
  }
  return false;
}

function bodyBranch(node: Element): Element | null {
  let current: Element | null = node;
  while (current?.parentElement && current.parentElement !== document.body) current = current.parentElement;
  return current;
}

function positionedNodes(branch: Element): Element[] {
  const nodes = [branch, ...Array.from(branch.querySelectorAll("*"))];
  return nodes.filter((node) => {
    if (!(node instanceof HTMLElement)) return false;
    const position = window.getComputedStyle(node).position;
    return position === "fixed" || position === "absolute";
  });
}

export function mobileContentSurface(width: number, leftOpen: boolean, rightOpen: boolean): "left" | "right" | null {
  if (drawerMode(width) !== "mobile") return null;
  if (leftOpen) return "left";
  if (rightOpen) return "right";
  return null;
}

export const LeftContentDrawer = forwardRef(function LeftContentDrawer(
  props: {
    open: boolean;
    desktopOpen: boolean;
    width: number;
    onClose: () => void;
    onResizePointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
    children: ReactNode;
  },
  ref: Ref<HTMLDivElement>,
) {
  const { open, desktopOpen, width, onClose, onResizePointerDown, children } = props;
  return (
    <div
      ref={ref}
      data-content-drawer="left"
      className={[
        "fixed inset-y-0 left-0 z-30 flex flex-col h-full transform transition-transform duration-200 md:relative md:z-auto shrink-0 border-r border-sol-base02 bg-sol-base03 overflow-hidden",
        CONTENT_DRAWER_CLASS,
        open ? "translate-x-0" : "-translate-x-full hidden",
        desktopOpen ? "md:translate-x-0 md:flex" : "md:-translate-x-full md:hidden",
      ].join(" ")}
      style={{ width }}
    >
      <div className="md:hidden shrink-0 flex items-center border-b border-sol-base02 px-2 py-1">
        <button
          type="button"
          data-drawer-close=""
          aria-label="Close"
          onClick={onClose}
          className="h-8 px-2 text-sm text-sol-base01 hover:text-sol-base1 cursor-pointer rounded"
        >
          Close
        </button>
      </div>
      <div className={`flex-1 min-h-0 overflow-auto flex flex-col ${CONTENT_DRAWER_BODY_CLASS}`}>
        {children}
      </div>
      <div
        data-sidebar-resize=""
        className="hidden md:block absolute top-0 -right-2 w-4 lg:w-1 lg:right-0 h-full cursor-col-resize z-10 group"
        onPointerDown={onResizePointerDown}
      >
        <div className="absolute top-0 right-2 lg:right-0 w-1 h-full hover:bg-sol-blue/40 active:bg-sol-blue/60" />
      </div>
    </div>
  );
});

export const RightContentDrawer = forwardRef(function RightContentDrawer(
  props: {
    open: boolean;
    width: number;
    children: ReactNode;
  },
  ref: Ref<HTMLDivElement>,
) {
  return (
    <div
      ref={ref}
      data-content-drawer="right"
      className={[
        "fixed inset-y-0 right-0 z-30 transform transition-transform duration-200 md:hidden shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden flex flex-col h-full",
        CONTENT_DRAWER_CLASS,
        props.open ? "translate-x-0" : "translate-x-full hidden",
      ].join(" ")}
      style={{ width: props.width }}
    >
      {props.children}
    </div>
  );
});
