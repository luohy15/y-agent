/** True for macOS / iOS user agents. Used for shortcut binding and labels. */
export function isApplePlatform(
  navigatorLike: Pick<Navigator, "userAgent" | "platform"> = navigator,
): boolean {
  return /Mac|iPhone|iPad|iPod/i.test(navigatorLike.platform)
    || /Mac OS X|iPhone|iPad|iPod/i.test(navigatorLike.userAgent);
}

/**
 * Platform label for the in-app close-tab shortcut.
 * Apple keeps the original Cmd/Ctrl+W binding (labelled ⌘W); non-Apple uses Alt+W.
 */
export function closeTabShortcutLabel(
  navigatorLike: Pick<Navigator, "userAgent" | "platform"> = navigator,
): string {
  return isApplePlatform(navigatorLike) ? "⌘W" : "Alt+W";
}
