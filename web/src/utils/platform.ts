/** True for macOS / iOS user agents. Used only for shortcut labels. */
export function isApplePlatform(
  navigatorLike: Pick<Navigator, "userAgent" | "platform"> = navigator,
): boolean {
  return /Mac|iPhone|iPad|iPod/i.test(navigatorLike.platform)
    || /Mac OS X|iPhone|iPad|iPod/i.test(navigatorLike.userAgent);
}

/** Platform label for the in-app close-tab shortcut (Alt+W / ⌥W). */
export function closeTabShortcutLabel(
  navigatorLike: Pick<Navigator, "userAgent" | "platform"> = navigator,
): string {
  return isApplePlatform(navigatorLike) ? "⌥W" : "Alt+W";
}
