import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { useSWRMock } = vi.hoisted(() => ({ useSWRMock: vi.fn() }));
vi.mock("swr", () => ({ default: useSWRMock }));
vi.mock("../api", () => ({ API: "", authFetch: vi.fn(), jsonFetcher: vi.fn() }));

import TagList from "./TagList";

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

function findButtonByText(container: HTMLElement, text: string): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll("button")).find((b) => (b.textContent ?? "").trim() === text);
  expect(btn, `button "${text}" should be rendered`).toBeTruthy();
  return btn as HTMLButtonElement;
}

// Vocabulary rows are clickable <div>s (not <button>s, to allow a nested
// disabled ⋯ <button> inside), located by exact tag text.
function findTagRow(container: HTMLElement, tag: string): HTMLElement {
  const row = Array.from(container.querySelectorAll("div.cursor-pointer")).find((d) => (d.textContent ?? "").trim().startsWith(tag));
  expect(row, `tag row "${tag}" should be rendered`).toBeTruthy();
  return row as HTMLElement;
}

function click(el: HTMLElement) {
  el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

// Mocks both the vocabulary (`/api/tag/list`) and drill-down (`/api/tag?tag=`)
// SWR keys off the URL shape TagList builds; stateless per-render.
function mockUseSWR(opts: {
  vocab?: { data?: unknown; isLoading?: boolean; error?: unknown };
  results?: { data?: unknown; isLoading?: boolean; error?: unknown };
}) {
  useSWRMock.mockImplementation((key: string | null) => {
    const mutate = vi.fn();
    if (typeof key === "string" && key.includes("/api/tag/list")) {
      const v = opts.vocab ?? {};
      return { data: v.data, isLoading: v.isLoading ?? false, error: v.error, mutate };
    }
    if (typeof key === "string" && key.includes("/api/tag?tag=")) {
      const r = opts.results ?? {};
      return { data: r.data, isLoading: r.isLoading ?? false, error: r.error, mutate };
    }
    return { data: undefined, isLoading: false, error: undefined, mutate };
  });
}

describe("TagList", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    useSWRMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a loading state on first fetch", () => {
    mockUseSWR({ vocab: { isLoading: true } });
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(TagList, { isLoggedIn: true, onNavigate: () => {} }));
    });
    expect(container.textContent).toContain("Loading");
    act(() => root.unmount());
    container.remove();
  });

  it("shows the empty state with create-by-first-use copy and no create affordance", () => {
    mockUseSWR({ vocab: { data: [] } });
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(TagList, { isLoggedIn: true, onNavigate: () => {} }));
    });
    expect(container.textContent).toContain("No tags found");
    expect(container.textContent).toContain("There is no bare tag to create");
    expect(Array.from(container.querySelectorAll("button")).some((b) => (b.textContent ?? "").trim() === "Create")).toBe(false);
    act(() => root.unmount());
    container.remove();
  });

  it("shows an error state when the vocabulary fetch fails", () => {
    mockUseSWR({ vocab: { error: new Error("network down") } });
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(TagList, { isLoggedIn: true, onNavigate: () => {} }));
    });
    expect(container.textContent).toContain("Error");
    expect(container.textContent).toContain("network down");
    act(() => root.unmount());
    container.remove();
  });

  it("renders tag counts, roll-up totals, and grouped tree/other split", () => {
    mockUseSWR({
      vocab: {
        data: [
          { tag: "meta/systems", count: 3 },
          { tag: "meta/decisions", count: 2 },
          { tag: "design", count: 6 },
        ],
      },
    });
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(TagList, { isLoggedIn: true, onNavigate: () => {} }));
    });
    // header summary: 3 distinct tags, 11 total uses
    expect(container.textContent).toContain("3 tags · 11 uses");
    // "meta/" group row shows the roll-up count (3 + 2 = 5)
    expect(container.textContent).toContain("meta/");
    expect(container.textContent).toMatch(/meta\/[\s\S]*5/);
    // bare tag "design" (no slash) renders under the "other" bucket with its own count
    expect(container.textContent).toContain("other");
    expect(container.textContent).toContain("design");
    act(() => root.unmount());
    container.remove();
  });

  it("filters the vocabulary by search substring", () => {
    mockUseSWR({
      vocab: {
        data: [
          { tag: "work/personal/y-agent", count: 37 },
          { tag: "life/travel", count: 4 },
        ],
      },
    });
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(TagList, { isLoggedIn: true, onNavigate: () => {} }));
    });
    const input = container.querySelector("input[placeholder='Search tags...']") as HTMLInputElement;
    expect(input).toBeTruthy();
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
    act(() => {
      setter.call(input, "travel");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(container.textContent).toContain("life/travel");
    expect(container.textContent).not.toContain("work/personal/y-agent");
    act(() => root.unmount());
    container.remove();
  });

  it("selects a tag, renders type-grouped drill-down results, and navigates on row click", () => {
    mockUseSWR({
      vocab: { data: [{ tag: "work/personal/y-agent", count: 2 }] },
      results: {
        data: {
          todo: [{ id: "2854", title: "Frontend tag management" }],
          note: [{ id: "n1", title: "pages/plan-2854-tag-management-ui.md" }],
        },
      },
    });
    const onNavigate = vi.fn();
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(TagList, { isLoggedIn: true, onNavigate }));
    });

    // Switch to flat mode so the full tag string is a single clickable row.
    act(() => click(findButtonByText(container, "flat")));
    act(() => click(findTagRow(container, "work/personal/y-agent")));

    // Drill-down header + type-grouped rows.
    expect(container.textContent).toContain("2 items");
    expect(container.textContent).toContain("todo");
    expect(container.textContent).toContain("note");
    expect(container.textContent).toContain("Frontend tag management");
    expect(container.textContent).toContain("plan-2854-tag-management-ui");

    const todoRow = Array.from(container.querySelectorAll("button")).find((b) => (b.textContent ?? "").includes("Frontend tag management"));
    expect(todoRow).toBeTruthy();
    act(() => click(todoRow as HTMLButtonElement));
    expect(onNavigate).toHaveBeenCalledWith("todo", { id: "2854", title: "Frontend tag management" });

    // Back button returns to the vocabulary state.
    const backBtn = container.querySelector("button[title='Back to all tags']") as HTMLButtonElement;
    expect(backBtn).toBeTruthy();
    act(() => click(backBtn));
    expect(container.querySelector("input[placeholder='Search tags...']")).toBeTruthy();

    act(() => root.unmount());
    container.remove();
  });

  it("shows the empty drill-down state when a selected tag has no results", () => {
    mockUseSWR({
      vocab: { data: [{ tag: "work/log", count: 1 }] },
      results: { data: {} },
    });
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(TagList, { isLoggedIn: true, onNavigate: () => {} }));
    });
    act(() => click(findButtonByText(container, "flat")));
    act(() => click(findTagRow(container, "work/log")));
    expect(container.textContent).toContain("No items found");
    act(() => root.unmount());
    container.remove();
  });

  it("locks the read-only contract: Rename/Merge/Delete are disabled and inert in the drill-down toolbar", () => {
    mockUseSWR({
      vocab: { data: [{ tag: "work/log", count: 1 }] },
      results: { data: { todo: [{ id: "1", title: "x" }] } },
    });
    const { container, root } = renderClient();
    act(() => {
      root.render(React.createElement(TagList, { isLoggedIn: true, onNavigate: () => {} }));
    });
    act(() => click(findButtonByText(container, "flat")));
    act(() => click(findTagRow(container, "work/log")));

    for (const label of ["Rename", "Merge", "Delete"]) {
      const btn = findButtonByText(container, label);
      expect(btn.disabled).toBe(true);
      // No action carries the enabled/high-chroma red styling reserved for S4.
      expect(btn.className).not.toContain("text-sol-red");
    }
    act(() => root.unmount());
    container.remove();
  });
});
