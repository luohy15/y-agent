import { useCallback, useEffect, useRef, useState } from "react";
import { useUserPreference } from "./useUserPreference";
import { applyTheme, DEFAULT_THEME, isTheme, loadTheme, type Theme } from "../utils/theme";

export function useTheme(isLoggedIn: boolean) {
  const [theme, setCurrentTheme] = useState<Theme>(loadTheme);
  const preference = useUserPreference<Theme>("theme", { enabled: isLoggedIn });
  const userTouchedRef = useRef(false);
  const reconciledRef = useRef(false);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (!isLoggedIn) {
      userTouchedRef.current = false;
      reconciledRef.current = false;
    }
  }, [isLoggedIn]);

  useEffect(() => {
    if (!isLoggedIn || !preference.loaded || reconciledRef.current) return;
    reconciledRef.current = true;

    if (isTheme(preference.serverValue)) {
      if (userTouchedRef.current) return;
      setCurrentTheme(preference.serverValue);
      try {
        window.localStorage.setItem("theme", preference.serverValue);
      } catch {}
    } else if (theme !== DEFAULT_THEME) {
      preference.setValue(theme);
    }
  }, [isLoggedIn, preference.loaded, preference.serverValue]);

  const setTheme = useCallback((nextTheme: Theme) => {
    userTouchedRef.current = true;
    setCurrentTheme(nextTheme);
    try {
      window.localStorage.setItem("theme", nextTheme);
    } catch {}
    if (isLoggedIn) preference.setValue(nextTheme);
  }, [isLoggedIn, preference]);

  return { theme, setTheme };
}
