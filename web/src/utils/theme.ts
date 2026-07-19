export const THEMES = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "solarized-dark", label: "Solarized Dark" },
  { value: "solarized-light", label: "Solarized Light" },
] as const;

export type Theme = (typeof THEMES)[number]["value"];

export const DEFAULT_THEME: Theme = "light";

export function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && THEMES.some((theme) => theme.value === value);
}

export function isDark(theme: Theme): boolean {
  return theme === "dark" || theme === "solarized-dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  const themeColor = getComputedStyle(document.documentElement)
    .getPropertyValue("--color-sol-base03")
    .trim();
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", themeColor);
}

export function loadTheme(): Theme {
  try {
    const stored = window.localStorage.getItem("theme");
    return isTheme(stored) ? stored : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

export type Mode = "system" | "light" | "dark";
export type LightVariant = "light" | "solarized-light";
export type DarkVariant = "dark" | "solarized-dark";

export interface ThemePrefs {
  mode: Mode;
  lightVariant: LightVariant;
  darkVariant: DarkVariant;
}

export const DEFAULT_PREFS: ThemePrefs = {
  mode: "system",
  lightVariant: "light",
  darkVariant: "dark",
};

export const MODES: { value: Mode; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export const LIGHT_VARIANTS: { value: LightVariant; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "solarized-light", label: "Solarized Light" },
];

export const DARK_VARIANTS: { value: DarkVariant; label: string }[] = [
  { value: "dark", label: "Dark" },
  { value: "solarized-dark", label: "Solarized Dark" },
];

function isMode(value: unknown): value is Mode {
  return value === "system" || value === "light" || value === "dark";
}

function isLightVariant(value: unknown): value is LightVariant {
  return value === "light" || value === "solarized-light";
}

function isDarkVariant(value: unknown): value is DarkVariant {
  return value === "dark" || value === "solarized-dark";
}

export function isThemePrefs(value: unknown): value is ThemePrefs {
  if (!value || typeof value !== "object") return false;
  const prefs = value as Record<string, unknown>;
  return isMode(prefs.mode) && isLightVariant(prefs.lightVariant) && isDarkVariant(prefs.darkVariant);
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
  return effective === "dark" ? prefs.darkVariant : prefs.lightVariant;
}

export function applyPrefs(prefs: ThemePrefs): void {
  applyTheme(resolveTheme(prefs, prefersDark()));
}

export function migrateLegacyTheme(theme: Theme): ThemePrefs {
  switch (theme) {
    case "light":
      return { mode: "light", lightVariant: "light", darkVariant: "dark" };
    case "solarized-light":
      return { mode: "light", lightVariant: "solarized-light", darkVariant: "dark" };
    case "dark":
      return { mode: "dark", lightVariant: "light", darkVariant: "dark" };
    case "solarized-dark":
      return { mode: "dark", lightVariant: "light", darkVariant: "solarized-dark" };
  }
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
    if (isTheme(legacy)) return migrateLegacyTheme(legacy);
  } catch {}
  return DEFAULT_PREFS;
}
