import { useEffect, useRef, useState, type RefObject } from "react";

/** Hold duration before a touch drag arms, matching a long-press gesture. */
const ARM_MS = 500;
/** Movement tolerance (CSS px) before an unarmed hold is treated as a scroll. */
const JITTER_PX = 8;

/** Splice `keys` moving the element at `fromIdx` to `toIdx`. Shared by mouse
 * HTML5 DnD and touch long-press reorder so both commit identically. */
export function reorderKeys(keys: string[], fromIdx: number, toIdx: number): string[] {
  const result = [...keys];
  const [moved] = result.splice(fromIdx, 1);
  result.splice(toIdx, 0, moved);
  return result;
}

export interface TabTouchReorderState {
  /** Attach to the scrollable tab row; touch listeners are delegated from here. */
  containerRef: RefObject<HTMLDivElement | null>;
  /** Key of the tab currently touch-tracked (from touchstart through reset);
   * used to force `draggable=false` and suppress native callout/selection on
   * that tab for the duration, ahead of the arm timer. */
  touchKey: string | null;
  /** True once the hold has armed (500ms elapsed without cancellation). */
  armed: boolean;
  /** Key of the tab currently under the finger, once armed. */
  dropKey: string | null;
}

/**
 * Long-press-then-drag touch reordering for FileTabStrip, layered beside the
 * existing HTML5 mouse/pen drag-and-drop without replacing it. See
 * pages/plan-3396-fileviewer-tab-touch-reorder.md for the gesture contract.
 */
export function useTabTouchReorder(
  tabKeys: string[],
  onReorder: ((keys: string[]) => void) | undefined,
): TabTouchReorderState {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [touchKey, setTouchKey] = useState<string | null>(null);
  const [armed, setArmed] = useState(false);
  const [dropKey, setDropKey] = useState<string | null>(null);

  const keysRef = useRef(tabKeys);
  keysRef.current = tabKeys;
  const onReorderRef = useRef(onReorder);
  onReorderRef.current = onReorder;

  const touchIdRef = useRef<number | null>(null);
  const startXRef = useRef(0);
  const startYRef = useRef(0);
  const sourceKeyRef = useRef<string | null>(null);
  const sourceElRef = useRef<HTMLElement | null>(null);
  const armedRef = useRef(false);
  const armTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dropKeyRef = useRef<string | null>(null);
  const suppressClickKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !onReorder) return;

    const reset = () => {
      if (armTimerRef.current !== null) {
        clearTimeout(armTimerRef.current);
        armTimerRef.current = null;
      }
      // Restore native draggability on the source element directly, rather
      // than relying solely on the next React render to re-apply it (e.g. a
      // touchstart+touchend landing in the same commit would otherwise leave
      // `draggable=false` stuck until an unrelated re-render).
      if (sourceElRef.current) sourceElRef.current.draggable = !!onReorderRef.current;
      sourceElRef.current = null;
      touchIdRef.current = null;
      sourceKeyRef.current = null;
      armedRef.current = false;
      dropKeyRef.current = null;
      setTouchKey(null);
      setArmed(false);
      setDropKey(null);
    };

    const findTab = (target: EventTarget | null): { key: string; el: HTMLElement } | null => {
      if (!(target instanceof Element)) return null;
      const el = target.closest<HTMLElement>("[data-tab-key]");
      if (!el || !container.contains(el)) return null;
      const key = el.getAttribute("data-tab-key");
      return key ? { key, el } : null;
    };

    const isControl = (target: EventTarget | null): boolean =>
      target instanceof Element && !!target.closest("button");

    const onTouchStart = (e: TouchEvent) => {
      // A prior gesture's suppressed click only ever applies to the click
      // that immediately follows it; a fresh touch starts a clean slate.
      suppressClickKeyRef.current = null;
      if (e.touches.length !== 1) {
        reset();
        return;
      }
      if (isControl(e.target)) return;
      const hit = findTab(e.target);
      if (!hit) return;
      // Disable native draggability synchronously, before WebKit's long-press
      // gesture recognition can claim this touch as an HTML5 drag image.
      hit.el.draggable = false;
      const touch = e.touches[0];
      touchIdRef.current = touch.identifier;
      startXRef.current = touch.clientX;
      startYRef.current = touch.clientY;
      sourceKeyRef.current = hit.key;
      sourceElRef.current = hit.el;
      armedRef.current = false;
      setTouchKey(hit.key);
      armTimerRef.current = setTimeout(() => {
        armTimerRef.current = null;
        if (touchIdRef.current === null) return;
        armedRef.current = true;
        setArmed(true);
      }, ARM_MS);
    };

    const onTouchMove = (e: TouchEvent) => {
      if (touchIdRef.current === null) return;
      if (e.touches.length !== 1) {
        reset();
        return;
      }
      const touch = Array.from(e.touches).find((t) => t.identifier === touchIdRef.current);
      if (!touch) return;
      if (!armedRef.current) {
        // Pre-arm: never prevent default, so native scrolling stays possible.
        const dx = touch.clientX - startXRef.current;
        const dy = touch.clientY - startYRef.current;
        if (Math.hypot(dx, dy) > JITTER_PX) reset();
        return;
      }
      if (!e.cancelable) {
        // Scrolling already took ownership of this gesture; back off.
        reset();
        return;
      }
      e.preventDefault();
      const target = document.elementFromPoint(touch.clientX, touch.clientY);
      const hit = findTab(target);
      const nextDrop = hit ? hit.key : null;
      if (nextDrop !== dropKeyRef.current) {
        dropKeyRef.current = nextDrop;
        setDropKey(nextDrop);
      }
    };

    const onTouchEnd = (e: TouchEvent) => {
      if (touchIdRef.current === null) return;
      const ended = Array.from(e.changedTouches).some((t) => t.identifier === touchIdRef.current);
      if (!ended) return;
      const wasArmed = armedRef.current;
      const source = sourceKeyRef.current;
      const target = dropKeyRef.current;
      if (wasArmed && source) suppressClickKeyRef.current = source;
      reset();
      if (wasArmed && source && target && source !== target) {
        const keys = keysRef.current;
        const fromIdx = keys.indexOf(source);
        const toIdx = keys.indexOf(target);
        if (fromIdx !== -1 && toIdx !== -1) {
          onReorderRef.current?.(reorderKeys(keys, fromIdx, toIdx));
        }
      }
    };

    const onTouchCancel = (e: TouchEvent) => {
      if (touchIdRef.current === null) return;
      const cancelled =
        e.touches.length === 0 ||
        Array.from(e.changedTouches).some((t) => t.identifier === touchIdRef.current);
      if (cancelled) reset();
    };

    const onPointerDown = (e: PointerEvent) => {
      // Hybrid device: a real pointing device follows, so restore desktop
      // dragging by dropping any in-flight touch state.
      if (e.pointerType === "mouse" || e.pointerType === "pen") reset();
    };

    const onContextMenu = (e: Event) => {
      // Prevent for the whole tracked hold, not just once armed: the native
      // long-press context menu / selection loupe can otherwise win the race
      // against our arm timer, which fires around the same ~500ms mark.
      if (touchIdRef.current !== null) e.preventDefault();
    };

    const onClickCapture = (e: MouseEvent) => {
      if (e.detail === 0) return; // keyboard-activated click; never suppress
      if (suppressClickKeyRef.current === null) return;
      e.stopPropagation();
      e.preventDefault();
      suppressClickKeyRef.current = null;
    };

    const onDblClickCapture = (e: MouseEvent) => {
      if (e.detail === 0) return;
      if (suppressClickKeyRef.current === null) return;
      e.stopPropagation();
      e.preventDefault();
      suppressClickKeyRef.current = null;
    };

    const onWindowBlur = () => reset();
    const onVisibilityChange = () => {
      if (document.hidden) reset();
    };

    container.addEventListener("touchstart", onTouchStart, { passive: true });
    container.addEventListener("touchmove", onTouchMove, { passive: false });
    container.addEventListener("touchend", onTouchEnd, { passive: true });
    container.addEventListener("touchcancel", onTouchCancel, { passive: true });
    container.addEventListener("pointerdown", onPointerDown, { passive: true });
    container.addEventListener("contextmenu", onContextMenu, { capture: true });
    container.addEventListener("click", onClickCapture, { capture: true });
    container.addEventListener("dblclick", onDblClickCapture, { capture: true });
    window.addEventListener("blur", onWindowBlur);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      reset();
      container.removeEventListener("touchstart", onTouchStart);
      container.removeEventListener("touchmove", onTouchMove);
      container.removeEventListener("touchend", onTouchEnd);
      container.removeEventListener("touchcancel", onTouchCancel);
      container.removeEventListener("pointerdown", onPointerDown);
      container.removeEventListener("contextmenu", onContextMenu, { capture: true });
      container.removeEventListener("click", onClickCapture, { capture: true });
      container.removeEventListener("dblclick", onDblClickCapture, { capture: true });
      window.removeEventListener("blur", onWindowBlur);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
    // Re-attach (and reset any in-flight gesture) when the tab-key sequence or
    // the presence of onReorder changes, per the plan's reset contract.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabKeys.join(" "), !!onReorder]);

  return { containerRef, touchKey, armed, dropKey };
}
