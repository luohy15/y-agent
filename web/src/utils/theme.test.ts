import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  applyPrefs,
  isPublicSharePath,
  PUBLIC_SHARE_THEME,
  resolveTheme,
  type ThemePrefs,
} from "./theme";

const lightPrefs: ThemePrefs = {
  mode: "light",
  lightVariant: "light",
  darkVariant: "dark",
};

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
    expect(document.documentElement.dataset.theme).toBe("light");

    window.history.pushState({}, "", "/docs");
    applyPrefs({ mode: "dark", lightVariant: "light", darkVariant: "dark" });
    expect(document.documentElement.dataset.theme).toBe("dark");

    window.history.pushState({}, "", "/trace/3042");
    applyPrefs({
      mode: "dark",
      lightVariant: "light",
      darkVariant: "solarized-dark",
    });
    expect(document.documentElement.dataset.theme).toBe("solarized-dark");
  });

  it("does not persist the forced share theme into prefs resolution helpers", () => {
    expect(resolveTheme(lightPrefs, false)).toBe("light");
    expect(PUBLIC_SHARE_THEME).toBe("solarized-dark");
  });
});
