import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// FileTree pulls its data through `authFetch`; stub it to a single-file listing
// so the tree renders one draggable node we can drive touch events against.
const { authFetchMock } = vi.hoisted(() => ({ authFetchMock: vi.fn() }));
vi.mock("../api", () => ({ API: "", authFetch: authFetchMock }));

import FileTree from "./FileTree";

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

// Let the loadRoot() fetch chain (authFetch -> res.json -> setState) settle.
async function flushMicrotasks() {
  for (let i = 0; i < 6; i++) await Promise.resolve();
}

function touchEvent(type: string, extra: Record<string, unknown> = {}) {
  const ev = new Event(type, { bubbles: true });
  Object.assign(ev, { pointerType: "touch", clientX: 4, clientY: 4, ...extra });
  return ev;
}

describe("FileTree mobile long-press selection", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    authFetchMock.mockReset();
    authFetchMock.mockImplementation(async () => ({
      ok: true,
      json: async () => ({ entries: [{ name: "a.txt", type: "file" }] }),
    }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function mountTree(onSelectFile: (p: string) => void) {
    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(FileTree, { isLoggedIn: true, onSelectFile }));
    });
    await act(async () => {
      await flushMicrotasks();
    });
    const node = container.querySelector('div[draggable="true"]') as HTMLElement;
    expect(node).toBeTruthy();
    expect(node.textContent).toContain("a.txt");
    return { container, root, node };
  }

  it("selects the item on a completed long-press and swallows the trailing click", async () => {
    const onSelectFile = vi.fn();
    const { root, container, node } = await mountTree(onSelectFile);

    await act(async () => {
      node.dispatchEvent(touchEvent("pointerdown"));
    });
    // Hold past the 500ms long-press threshold.
    await act(async () => {
      vi.advanceTimersByTime(600);
    });

    // `text-sol-base1` is only applied to a selected node.
    expect(node.className).toContain("text-sol-base1");
    // The long-press must not open the file; the trailing click is suppressed.
    await act(async () => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onSelectFile).not.toHaveBeenCalled();

    act(() => root.unmount());
    container.remove();
  });

  it("still opens the file on a plain tap (short press, no long-press fired)", async () => {
    const onSelectFile = vi.fn();
    const { root, container, node } = await mountTree(onSelectFile);

    await act(async () => {
      node.dispatchEvent(touchEvent("pointerdown"));
      node.dispatchEvent(touchEvent("pointerup")); // releases before threshold -> cancels timer
    });
    await act(async () => {
      vi.advanceTimersByTime(600); // timer was cancelled; nothing fires
    });
    await act(async () => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onSelectFile).toHaveBeenCalledWith("./a.txt");

    act(() => root.unmount());
    container.remove();
  });
});
