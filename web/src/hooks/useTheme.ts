import { useCallback, useEffect, useRef, useState } from "react";
import { useUserPreference } from "./useUserPreference";
import {
  applyPrefs,
  DEFAULT_PREFS,
  isTheme,
  isThemePrefs,
  loadPrefs,
  migrateLegacyTheme,
  type DarkVariant,
  type LightVariant,
  type Mode,
  type Theme,
  type ThemePrefs,
} from "../utils/theme";

function prefsEqual(a: ThemePrefs, b: ThemePrefs): boolean {
  return a.mode === b.mode && a.lightVariant === b.lightVariant && a.darkVariant === b.darkVariant;
}

export function useTheme(isLoggedIn: boolean) {
  const [prefs, setCurrentPrefs] = useState<ThemePrefs>(loadPrefs);
  const preference = useUserPreference<ThemePrefs>("themePrefs", { enabled: isLoggedIn });
  const legacyPreference = useUserPreference<Theme>("theme", { enabled: isLoggedIn });
  const userTouchedRef = useRef(false);
  const reconciledRef = useRef(false);
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;

  useEffect(() => {
    applyPrefs(prefs);
  }, [prefs]);

  useEffect(() => {
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => applyPrefs(prefsRef.current);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  useEffect(() => {
    if (!isLoggedIn) {
      userTouchedRef.current = false;
      reconciledRef.current = false;
    }
  }, [isLoggedIn]);

  useEffect(() => {
    if (!isLoggedIn || !preference.loaded || !legacyPreference.loaded || reconciledRef.current) return;
    reconciledRef.current = true;

    if (isThemePrefs(preference.serverValue)) {
      if (userTouchedRef.current) return;
      setCurrentPrefs(preference.serverValue);
      try {
        window.localStorage.setItem("themePrefs", JSON.stringify(preference.serverValue));
      } catch {}
    } else if (isTheme(legacyPreference.serverValue)) {
      if (userTouchedRef.current) return;
      const migrated = migrateLegacyTheme(legacyPreference.serverValue);
      setCurrentPrefs(migrated);
      try {
        window.localStorage.setItem("themePrefs", JSON.stringify(migrated));
      } catch {}
      preference.setValue(migrated);
    } else if (!prefsEqual(prefsRef.current, DEFAULT_PREFS)) {
      preference.setValue(prefsRef.current);
    }
  }, [isLoggedIn, preference.loaded, preference.serverValue, legacyPreference.loaded, legacyPreference.serverValue]);

  const persist = useCallback(
    (next: ThemePrefs) => {
      userTouchedRef.current = true;
      setCurrentPrefs(next);
      try {
        window.localStorage.setItem("themePrefs", JSON.stringify(next));
      } catch {}
      if (isLoggedIn) preference.setValue(next);
    },
    [isLoggedIn, preference],
  );

  const setMode = useCallback(
    (mode: Mode) => persist({ ...prefsRef.current, mode }),
    [persist],
  );

  const setLightVariant = useCallback(
    (lightVariant: LightVariant) => persist({ ...prefsRef.current, lightVariant }),
    [persist],
  );

  const setDarkVariant = useCallback(
    (darkVariant: DarkVariant) => persist({ ...prefsRef.current, darkVariant }),
    [persist],
  );

  return { prefs, setMode, setLightVariant, setDarkVariant };
}
