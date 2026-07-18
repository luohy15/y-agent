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
