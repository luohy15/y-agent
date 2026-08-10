import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { useUserPreferenceMock, themePrefsSetValue, themeSetValue } = vi.hoisted(() => ({
  useUserPreferenceMock: vi.fn(),
  themePrefsSetValue: vi.fn(),
  themeSetValue: vi.fn(),
}));

vi.mock("./useUserPreference", () => ({
  useUserPreference: useUserPreferenceMock,
}));

import { useTheme } from "./useTheme";

interface MockPreferenceState {
  serverValue: unknown;
  loaded: boolean;
}

function mockPreferences(themePrefsState: MockPreferenceState, themeState: MockPreferenceState) {
  useUserPreferenceMock.mockImplementation((key: string) => {
    if (key === "themePrefs") {
      return {
        serverValue: themePrefsState.serverValue,
        loaded: themePrefsState.loaded,
        status: "idle",
        setValue: themePrefsSetValue,
        flush: vi.fn(),
      };
    }
    return {
      serverValue: themeState.serverValue,
      loaded: themeState.loaded,
      status: "idle",
      setValue: themeSetValue,
      flush: vi.fn(),
    };
  });
}

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

function Harness({
  isLoggedIn,
  onResult,
}: {
  isLoggedIn: boolean;
  onResult: (result: ReturnType<typeof useTheme>) => void;
}) {
  const result = useTheme(isLoggedIn);
  onResult(result);
  return null;
}

// Regression coverage for review-3106-solarized-only-theme.md's blocking finding:
// an old-shape server themePrefs payload (extra lightVariant/darkVariant) must
// normalize to { mode } on read and write that shape back to the server.
describe("useTheme", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    useUserPreferenceMock.mockReset();
    themePrefsSetValue.mockReset();
    themeSetValue.mockReset();
    window.localStorage.clear();
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("normalizes an old-shape server themePrefs payload to {mode} and writes it back", async () => {
    mockPreferences(
      { serverValue: { mode: "dark", lightVariant: "light", darkVariant: "dark" }, loaded: true },
      { serverValue: null, loaded: true },
    );
    const { container, root } = renderClient();
    let latest: ReturnType<typeof useTheme> | undefined;
    await act(async () => {
      root.render(<Harness isLoggedIn={true} onResult={(r) => { latest = r; }} />);
    });

    expect(latest?.prefs).toEqual({ mode: "dark" });
    expect(themePrefsSetValue).toHaveBeenCalledTimes(1);
    expect(themePrefsSetValue).toHaveBeenCalledWith({ mode: "dark" });
    expect(JSON.parse(window.localStorage.getItem("themePrefs") ?? "null")).toEqual({ mode: "dark" });

    root.unmount();
    container.remove();
  });

  it("does not write back a current-shape ({mode}-only) server themePrefs payload", async () => {
    mockPreferences(
      { serverValue: { mode: "light" }, loaded: true },
      { serverValue: null, loaded: true },
    );
    const { container, root } = renderClient();
    let latest: ReturnType<typeof useTheme> | undefined;
    await act(async () => {
      root.render(<Harness isLoggedIn={true} onResult={(r) => { latest = r; }} />);
    });

    expect(latest?.prefs).toEqual({ mode: "light" });
    expect(themePrefsSetValue).not.toHaveBeenCalled();

    root.unmount();
    container.remove();
  });

  it("migrates a legacy theme string and writes back a {mode}-only object", async () => {
    mockPreferences(
      { serverValue: null, loaded: true },
      { serverValue: "solarized-dark", loaded: true },
    );
    const { container, root } = renderClient();
    let latest: ReturnType<typeof useTheme> | undefined;
    await act(async () => {
      root.render(<Harness isLoggedIn={true} onResult={(r) => { latest = r; }} />);
    });

    expect(latest?.prefs).toEqual({ mode: "dark" });
    expect(themePrefsSetValue).toHaveBeenCalledWith({ mode: "dark" });

    root.unmount();
    container.remove();
  });

  it("setMode always persists a mode-only object, never a stale variant-shaped one", async () => {
    mockPreferences(
      { serverValue: null, loaded: true },
      { serverValue: null, loaded: true },
    );
    const { container, root } = renderClient();
    let latest: ReturnType<typeof useTheme> | undefined;
    await act(async () => {
      root.render(<Harness isLoggedIn={true} onResult={(r) => { latest = r; }} />);
    });

    await act(async () => {
      latest?.setMode("dark");
    });

    expect(JSON.parse(window.localStorage.getItem("themePrefs") ?? "null")).toEqual({ mode: "dark" });
    expect(themePrefsSetValue).toHaveBeenCalledWith({ mode: "dark" });

    root.unmount();
    container.remove();
  });
});
