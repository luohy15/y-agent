import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import MobileToc from "./MobileToc";
import type { TocItem } from "./DocsToc";

// jsdom has no IntersectionObserver; useActiveTocId only needs a no-op stub.
class StubIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

const items: TocItem[] = [
  { id: "overview", text: "Overview", level: 2 },
  { id: "layout", text: "Layout breakpoints", level: 2 },
  { id: "content-width", text: "Content width", level: 3 },
];

describe("MobileToc", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    (globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver = StubIntersectionObserver;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("renders nothing when there are fewer than 2 headings (graceful degradation)", () => {
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(MobileToc, { items: [items[0]] }));
    });
    expect(container.querySelector("button")).toBeNull();

    act(() => {
      root.render(React.createElement(MobileToc, { items: [] }));
    });
    expect(container.querySelector("button")).toBeNull();

    act(() => root.unmount());
    container.remove();
  });

  it("opens a dropdown listing every heading, closes on link click, and exposes aria-expanded", () => {
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(MobileToc, { items }));
    });

    const button = container.querySelector("button") as HTMLButtonElement;
    expect(button).not.toBeNull();
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(container.querySelector("nav[aria-label='On this page']")).toBeNull();

    act(() => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(button.getAttribute("aria-expanded")).toBe("true");
    const nav = container.querySelector("nav[aria-label='On this page']");
    expect(nav).not.toBeNull();
    const links = nav!.querySelectorAll("a");
    expect(links).toHaveLength(items.length);
    expect(links[0].textContent).toBe("Overview");

    act(() => {
      links[1].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    expect(container.querySelector("nav[aria-label='On this page']")).toBeNull();

    act(() => root.unmount());
    container.remove();
  });

  it("closes the dropdown on Escape", () => {
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(MobileToc, { items }));
    });

    const button = container.querySelector("button") as HTMLButtonElement;
    act(() => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector("nav[aria-label='On this page']")).not.toBeNull();

    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(container.querySelector("nav[aria-label='On this page']")).toBeNull();

    act(() => root.unmount());
    container.remove();
  });
});
