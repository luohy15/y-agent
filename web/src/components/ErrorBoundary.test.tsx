import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ErrorBoundary from "./ErrorBoundary";

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

function Boom(): React.ReactElement {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    // React logs the caught error to console.error via componentDidCatch and via
    // its own dev-mode logging; silence both so the test output stays clean.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a fallback instead of unmounting the tree when a child throws", () => {
    const { container, root } = renderClient();

    expect(() => {
      act(() => {
        root.render(
          React.createElement(
            "div",
            null,
            React.createElement("span", null, "sibling stays mounted"),
            React.createElement(ErrorBoundary, { label: "Panel" }, React.createElement(Boom)),
          ),
        );
      });
    }).not.toThrow();

    expect(container.textContent).toContain("sibling stays mounted");
    expect(container.textContent).toContain("Panel crashed.");
    expect(container.textContent).toContain("boom");

    act(() => root.unmount());
    container.remove();
  });

  it("renders children unchanged when nothing throws", () => {
    const { container, root } = renderClient();
    act(() => {
      root.render(
        React.createElement(ErrorBoundary, null, React.createElement("span", null, "all good")),
      );
    });

    expect(container.textContent).toBe("all good");

    act(() => root.unmount());
    container.remove();
  });
});
