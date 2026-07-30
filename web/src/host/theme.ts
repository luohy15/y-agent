import { useEffect, useState } from "react";

// Utilities emit `var(--color-sol-*)` and follow the host theme for free
// (decision D3), but a library that takes literal color values instead of CSS
// vars (e.g. recharts' `fill`/`stroke` props) needs the resolved string.
// Mirrors the `readThemeColors`/`useThemeColors` helpers the `finance` dynamic
// UI artifact uses to feed hex colors to non-CSS-var chart libraries.
export interface ThemeColors {
  base03: string;
  base02: string;
  base01: string;
  base0: string;
  base1: string;
  blue: string;
  red: string;
  green: string;
  yellow: string;
  cyan: string;
  magenta: string;
  violet: string;
  orange: string;
}

export function readThemeColors(): ThemeColors {
  const style = getComputedStyle(document.documentElement);
  const v = (name: string) => style.getPropertyValue(`--color-sol-${name}`).trim();
  return {
    base03: v("base03"), base02: v("base02"), base01: v("base01"), base0: v("base0"), base1: v("base1"),
    blue: v("blue"), red: v("red"), green: v("green"), yellow: v("yellow"), cyan: v("cyan"),
    magenta: v("magenta"), violet: v("violet"), orange: v("orange"),
  };
}

let current: ThemeColors = readThemeColors();
const listeners = new Set<() => void>();
new MutationObserver(() => {
  current = readThemeColors();
  listeners.forEach((listener) => listener());
}).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

// Re-renders the calling component whenever the host theme changes, so an
// artifact reading resolved colors (not just CSS vars) stays in sync with a
// theme toggle with no reload.
export function useThemeColors(): ThemeColors {
  const [colors, setColors] = useState(current);
  useEffect(() => {
    const listener = () => setColors(current);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return colors;
}
