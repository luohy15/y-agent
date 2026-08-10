export type Theme = "solarized-light" | "solarized-dark";

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  const themeColor = getComputedStyle(document.documentElement)
    .getPropertyValue("--color-sol-base03")
    .trim();
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", themeColor);
}

export type Mode = "system" | "light" | "dark";

export interface ThemePrefs {
  mode: Mode;
}

export const DEFAULT_PREFS: ThemePrefs = { mode: "system" };

export const MODES: { value: Mode; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

function isMode(value: unknown): value is Mode {
  return value === "system" || value === "light" || value === "dark";
}

// Tolerant on purpose: old-shape ThemePrefs objects (with now-dropped
// lightVariant/darkVariant) still carry a valid mode, so validating mode
// alone migrates every stored object for free.
export function isThemePrefs(value: unknown): value is ThemePrefs {
  if (!value || typeof value !== "object") return false;
  const prefs = value as Record<string, unknown>;
  return isMode(prefs.mode);
}

export function prefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

export function resolveTheme(prefs: ThemePrefs, osPrefersDark: boolean): Theme {
  const effective = prefs.mode === "system" ? (osPrefersDark ? "dark" : "light") : prefs.mode;
  return effective === "dark" ? "solarized-dark" : "solarized-light";
}

// Public share surfaces (/t, /s, /share, /n) always render Solarized Dark so chrome
// and hardcoded solarized-dark leaves (e.g. HostMessageView diffs) agree. Keep the
// predicate in lockstep with the no-flash bootstrap in web/index.html.
export const PUBLIC_SHARE_THEME: Theme = "solarized-dark";

export function isPublicSharePath(pathname: string): boolean {
  return /^\/(?:t|s|share|n)\/[^/]+/.test(pathname);
}

export function applyPrefs(prefs: ThemePrefs): void {
  if (isPublicSharePath(window.location.pathname)) {
    applyTheme(PUBLIC_SHARE_THEME);
    return;
  }
  applyTheme(resolveTheme(prefs, prefersDark()));
}

// Legacy single-string preference ("theme" key, web and server): maps each of
// the four now-removed names to the mode of the same polarity.
const LEGACY_THEME_MODE: Record<string, Mode> = {
  light: "light",
  "solarized-light": "light",
  dark: "dark",
  "solarized-dark": "dark",
};

export function isLegacyTheme(value: unknown): value is string {
  return (
    typeof value === "string" && Object.prototype.hasOwnProperty.call(LEGACY_THEME_MODE, value)
  );
}

export function migrateLegacyTheme(theme: string): ThemePrefs {
  return { mode: LEGACY_THEME_MODE[theme] };
}

export function loadPrefs(): ThemePrefs {
  try {
    const stored = window.localStorage.getItem("themePrefs");
    if (stored) {
      const parsed = JSON.parse(stored);
      if (isThemePrefs(parsed)) return parsed;
    }
  } catch {}
  try {
    const legacy = window.localStorage.getItem("theme");
    if (isLegacyTheme(legacy)) return migrateLegacyTheme(legacy);
  } catch {}
  return DEFAULT_PREFS;
}
