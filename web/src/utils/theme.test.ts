import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  applyPrefs,
  DEFAULT_PREFS,
  isLegacyTheme,
  isPublicSharePath,
  loadPrefs,
  migrateLegacyTheme,
  PUBLIC_SHARE_THEME,
  resolveTheme,
  type ThemePrefs,
} from "./theme";

const lightPrefs: ThemePrefs = { mode: "light" };
const darkPrefs: ThemePrefs = { mode: "dark" };

describe("isPublicSharePath", () => {
  it.each([
    ["/t/share-abc", true],
    ["/s/share-abc", true],
    ["/share/share-abc", true],
    ["/n/share-abc", true],
    ["/t/share-abc/extra", true],
    ["/t/", false],
    ["/t", false],
    ["/s", false],
    ["/share", false],
    ["/n", false],
    ["/", false],
    ["/docs", false],
    ["/docs/intro", false],
    ["/trace/3042", false],
    ["/showcase", false],
    ["/ui/foo", false],
    ["/todo", false],
  ])("%s → %s", (pathname, expected) => {
    expect(isPublicSharePath(pathname)).toBe(expected);
  });
});

describe("applyPrefs", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    document.documentElement.removeAttribute("data-theme");
    window.history.pushState({}, "", "/");
  });

  it("forces solarized-dark on public share paths regardless of prefs", () => {
    window.history.pushState({}, "", "/t/share-abc");
    applyPrefs(lightPrefs);
    expect(document.documentElement.dataset.theme).toBe(PUBLIC_SHARE_THEME);

    window.history.pushState({}, "", "/s/share-abc");
    applyPrefs(lightPrefs);
    expect(document.documentElement.dataset.theme).toBe(PUBLIC_SHARE_THEME);

    window.history.pushState({}, "", "/share/share-abc");
    applyPrefs(lightPrefs);
    expect(document.documentElement.dataset.theme).toBe(PUBLIC_SHARE_THEME);

    window.history.pushState({}, "", "/n/share-abc");
    applyPrefs(lightPrefs);
    expect(document.documentElement.dataset.theme).toBe(PUBLIC_SHARE_THEME);
  });

  it("applies resolved prefs on non-share paths", () => {
    window.history.pushState({}, "", "/");
    applyPrefs(lightPrefs);
    expect(document.documentElement.dataset.theme).toBe("solarized-light");

    window.history.pushState({}, "", "/docs");
    applyPrefs(darkPrefs);
    expect(document.documentElement.dataset.theme).toBe("solarized-dark");
  });

  it("does not persist the forced share theme into prefs resolution helpers", () => {
    expect(resolveTheme(lightPrefs, false)).toBe("solarized-light");
    expect(PUBLIC_SHARE_THEME).toBe("solarized-dark");
  });
});

describe("resolveTheme", () => {
  it("resolves system mode from the OS preference", () => {
    expect(resolveTheme({ mode: "system" }, false)).toBe("solarized-light");
    expect(resolveTheme({ mode: "system" }, true)).toBe("solarized-dark");
  });

  it("resolves explicit modes to the matching Solarized variant", () => {
    expect(resolveTheme(lightPrefs, true)).toBe("solarized-light");
    expect(resolveTheme(darkPrefs, false)).toBe("solarized-dark");
  });
});

describe("loadPrefs", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("reads a current-shape stored ThemePrefs object", () => {
    window.localStorage.setItem("themePrefs", JSON.stringify(darkPrefs));
    expect(loadPrefs()).toEqual(darkPrefs);
  });

  it("migrates an old-shape themePrefs object (extra lightVariant/darkVariant) by mode alone", () => {
    window.localStorage.setItem(
      "themePrefs",
      JSON.stringify({ mode: "light", lightVariant: "light", darkVariant: "dark" }),
    );
    const prefs = loadPrefs();
    expect(prefs.mode).toBe("light");
    expect(resolveTheme(prefs, false)).toBe("solarized-light");
  });

  it("maps legacy theme:'light' to solarized-light", () => {
    window.localStorage.setItem("theme", "light");
    expect(loadPrefs()).toEqual({ mode: "light" });
    expect(resolveTheme(loadPrefs(), false)).toBe("solarized-light");
  });

  it("maps legacy theme:'dark' to solarized-dark", () => {
    window.localStorage.setItem("theme", "dark");
    expect(loadPrefs()).toEqual({ mode: "dark" });
    expect(resolveTheme(loadPrefs(), false)).toBe("solarized-dark");
  });

  it("maps legacy theme:'solarized-light' / 'solarized-dark' to the same-polarity mode", () => {
    window.localStorage.setItem("theme", "solarized-light");
    expect(loadPrefs()).toEqual({ mode: "light" });

    window.localStorage.setItem("theme", "solarized-dark");
    expect(loadPrefs()).toEqual({ mode: "dark" });
  });

  it("falls back to DEFAULT_PREFS for garbage input", () => {
    window.localStorage.setItem("themePrefs", "not json");
    expect(loadPrefs()).toEqual(DEFAULT_PREFS);

    window.localStorage.clear();
    window.localStorage.setItem("theme", "nonsense");
    expect(loadPrefs()).toEqual(DEFAULT_PREFS);

    window.localStorage.clear();
    expect(loadPrefs()).toEqual(DEFAULT_PREFS);
  });
});

describe("migrateLegacyTheme", () => {
  it("maps each of the four removed names to its polarity's mode", () => {
    expect(migrateLegacyTheme("light")).toEqual({ mode: "light" });
    expect(migrateLegacyTheme("solarized-light")).toEqual({ mode: "light" });
    expect(migrateLegacyTheme("dark")).toEqual({ mode: "dark" });
    expect(migrateLegacyTheme("solarized-dark")).toEqual({ mode: "dark" });
  });
});

describe("isLegacyTheme", () => {
  it("accepts only the four removed theme names", () => {
    expect(isLegacyTheme("light")).toBe(true);
    expect(isLegacyTheme("solarized-light")).toBe(true);
    expect(isLegacyTheme("dark")).toBe(true);
    expect(isLegacyTheme("solarized-dark")).toBe(true);
    expect(isLegacyTheme("nonsense")).toBe(false);
    expect(isLegacyTheme(null)).toBe(false);
    expect(isLegacyTheme(undefined)).toBe(false);
  });

  it("does not walk the prototype chain (Object.prototype keys are not legacy themes)", () => {
    expect(isLegacyTheme("toString")).toBe(false);
    expect(isLegacyTheme("constructor")).toBe(false);
    expect(isLegacyTheme("hasOwnProperty")).toBe(false);
  });
});

describe("loadPrefs (prototype-pollution hardening)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("falls back to DEFAULT_PREFS for a legacy theme value that only matches via the prototype chain", () => {
    window.localStorage.setItem("theme", "toString");
    expect(loadPrefs()).toEqual(DEFAULT_PREFS);

    window.localStorage.clear();
    window.localStorage.setItem("theme", "constructor");
    expect(loadPrefs()).toEqual(DEFAULT_PREFS);
  });
});
