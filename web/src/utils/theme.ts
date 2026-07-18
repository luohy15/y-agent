export const THEMES = [
  { value: "light", label: "Light", themeColor: "#ffffff" },
  { value: "dark", label: "Dark", themeColor: "#0d1117" },
  { value: "solarized-dark", label: "Solarized Dark", themeColor: "#002b36" },
  { value: "solarized-light", label: "Solarized Light", themeColor: "#fdf6e3" },
] as const;

export type Theme = (typeof THEMES)[number]["value"];

export const DEFAULT_THEME: Theme = "light";

const themeColors: Record<Theme, string> = Object.fromEntries(
  THEMES.map(({ value, themeColor }) => [value, themeColor]),
) as Record<Theme, string>;

export function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && THEMES.some((theme) => theme.value === value);
}

export function isDark(theme: Theme): boolean {
  return theme === "dark" || theme === "solarized-dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", themeColors[theme]);
}

export function loadTheme(): Theme {
  try {
    const stored = window.localStorage.getItem("theme");
    return isTheme(stored) ? stored : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}
