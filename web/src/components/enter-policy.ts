// Chat composer Return policy (todo 3860). Kept in lockstep with the chat
// module copy; the host suite asserts the two files stay identical.
//
// Missing browser globals mean desktop. Every call re-reads the signals.
// An explicit iPad / iPhone / iPod / Android user agent, or a Mac-style
// platform with maxTouchPoints > 1 (iPad desktop-site mode), always inserts
// a newline, even if a mouse or keyboard is attached later. Otherwise a
// newline is used only when the primary pointer is coarse AND hover is none.
// Viewport width and a touch-point count alone do not qualify. A desktop
// user agent with a fine, hovering pointer (including a touch laptop) keeps
// desktop Enter. A Windows tablet that reports that same desktop shape is
// indistinguishable and stays on desktop Enter.

export interface EnterSignals {
  userAgent: string;
  platform: string;
  maxTouchPoints: number;
  pointerCoarse: boolean;
  hoverNone: boolean;
}

export function readEnterSignals(): EnterSignals {
  const nav = typeof navigator === "undefined" ? undefined : navigator;
  let pointerCoarse = false;
  let hoverNone = false;
  if (typeof matchMedia === "function") {
    pointerCoarse = matchMedia("(pointer: coarse)").matches;
    hoverNone = matchMedia("(hover: none)").matches;
  }
  return {
    userAgent: nav?.userAgent ?? "",
    platform: nav?.platform ?? "",
    maxTouchPoints: nav?.maxTouchPoints ?? 0,
    pointerCoarse,
    hoverNone,
  };
}

export function newlineEnterFromSignals(signals: EnterSignals): boolean {
  if (/iPad|iPhone|iPod|Android/i.test(signals.userAgent)) return true;
  if (/Mac/i.test(signals.platform) && signals.maxTouchPoints > 1) return true;
  return signals.pointerCoarse && signals.hoverNone;
}

export function usesNewlineOnEnter(): boolean {
  return newlineEnterFromSignals(readEnterSignals());
}

export function enterIsImeConfirm(
  event: {
    isComposing?: boolean;
    keyCode?: number;
    nativeEvent?: { isComposing?: boolean; keyCode?: number };
  },
  composing: boolean,
): boolean {
  if (composing) return true;
  const native = event.nativeEvent;
  if (event.isComposing || native?.isComposing) return true;
  const keyCode = native?.keyCode ?? event.keyCode;
  return keyCode === 229;
}
