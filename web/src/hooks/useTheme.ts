import { useCallback, useEffect, useRef, useState } from "react";
import { useUserPreference } from "./useUserPreference";
import {
  applyPrefs,
  DEFAULT_PREFS,
  isLegacyTheme,
  isThemePrefs,
  loadPrefs,
  migrateLegacyTheme,
  type Mode,
  type ThemePrefs,
} from "../utils/theme";

function prefsEqual(a: ThemePrefs, b: ThemePrefs): boolean {
  return a.mode === b.mode;
}

export function useTheme(isLoggedIn: boolean) {
  const [prefs, setCurrentPrefs] = useState<ThemePrefs>(loadPrefs);
  const preference = useUserPreference<ThemePrefs>("themePrefs", { enabled: isLoggedIn });
  const legacyPreference = useUserPreference<string>("theme", { enabled: isLoggedIn });
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
    if (!isLoggedIn || reconciledRef.current) return;

    const currentReadSucceeded = preference.loaded && preference.status === "idle";
    const legacyReadSucceeded = legacyPreference.loaded && legacyPreference.status === "idle";

    // A valid current value is authoritative and does not need the legacy read.
    if (currentReadSucceeded && isThemePrefs(preference.serverValue)) {
      reconciledRef.current = true;
      if (userTouchedRef.current) return;
      const normalized: ThemePrefs = { mode: preference.serverValue.mode };
      setCurrentPrefs(normalized);
      try {
        window.localStorage.setItem("themePrefs", JSON.stringify(normalized));
      } catch {}
      // Old-shape payload (extra lightVariant/darkVariant) — write the normalized
      // { mode } shape back so subsequent reads no longer see a removed palette.
      if (Object.keys(preference.serverValue).length > 1) preference.setValue(normalized);
      return;
    }

    // An absent current value can only be reconciled after both reads succeeded.
    // A failed or offline read is unknown, not confirmed absence.
    if (!currentReadSucceeded || !legacyReadSucceeded) return;
    reconciledRef.current = true;

    if (isLegacyTheme(legacyPreference.serverValue)) {
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
  }, [
    isLoggedIn,
    preference.loaded,
    preference.serverValue,
    preference.status,
    legacyPreference.loaded,
    legacyPreference.serverValue,
    legacyPreference.status,
  ]);

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

  const setMode = useCallback((mode: Mode) => persist({ mode }), [persist]);

  return { prefs, setMode };
}
