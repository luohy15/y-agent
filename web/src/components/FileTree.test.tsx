import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// FileTree pulls its data through `authFetch`; stub it to a single-file listing
// so the tree renders one node we can drive pointer events against.
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

// A pointer event carrying an explicit `pointerType` (touch / mouse / pen). The
// node re-derives its draggability from this value on every pointerdown.
function pointerEvent(type: string, pointerType: string, extra: Record<string, unknown> = {}) {
  const ev = new Event(type, { bubbles: true });
  Object.assign(ev, { pointerType, clientX: 4, clientY: 4, ...extra });
  return ev;
}

const touchEvent = (type: string, extra: Record<string, unknown> = {}) =>
  pointerEvent(type, "touch", extra);

// Find the file node without relying on the `draggable` attribute (which the
// fix flips per interaction).
function fileNode(container: HTMLElement): HTMLElement {
  const node = Array.from(container.querySelectorAll("div")).find(
    (d) => d.className.includes("cursor-pointer") && (d.textContent ?? "").includes("a.txt"),
  ) as HTMLElement | undefined;
  expect(node).toBeTruthy();
  return node as HTMLElement;
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
    const node = fileNode(container);
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

  // The real-device failure: the node was `draggable`, so a stationary
  // long-press was hijacked by WebKit's native drag gesture (which fires
  // `pointercancel`, aborting the timer, and surfaces the native
  // selection/callout). The fix drops draggability *for the touch gesture* —
  // decided from the live pointer type, so it works on hybrid devices and
  // never goes stale.
  describe("per-interaction draggability (hybrid devices)", () => {
    it("keeps the node draggable for a mouse interaction so desktop DnD is preserved", async () => {
      const { root, container, node } = await mountTree(vi.fn());

      // Initial render is draggable (desktop default).
      expect(node.getAttribute("draggable")).toBe("true");
      // A mouse pointerdown keeps it draggable and starts no long-press timer.
      await act(async () => {
        node.dispatchEvent(pointerEvent("pointerdown", "mouse"));
      });
      expect(node.getAttribute("draggable")).toBe("true");

      act(() => root.unmount());
      container.remove();
    });

    it("drops draggability for a touch gesture so native drag cannot hijack the long-press", async () => {
      const onSelectFile = vi.fn();
      const { root, container, node } = await mountTree(onSelectFile);

      await act(async () => {
        node.dispatchEvent(touchEvent("pointerdown"));
      });
      // Native HTML5 drag disabled for this gesture: WebKit won't claim it.
      expect(node.getAttribute("draggable")).toBe("false");

      // The long-press still completes into a selection without opening.
      await act(async () => {
        vi.advanceTimersByTime(600);
      });
      expect(node.className).toContain("text-sol-base1");
      await act(async () => {
        node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });
      expect(onSelectFile).not.toHaveBeenCalled();

      act(() => root.unmount());
      container.remove();
    });

    it("does not swallow a later mouse click when a touch long-press emitted no trailing click", async () => {
      const onSelectFile = vi.fn();
      const { root, container, node } = await mountTree(onSelectFile);

      // Completed touch long-press arms the click-suppression flag...
      await act(async () => {
        node.dispatchEvent(touchEvent("pointerdown"));
      });
      await act(async () => {
        vi.advanceTimersByTime(600);
      });
      expect(node.className).toContain("text-sol-base1"); // selected
      // ...but iOS/WebKit emits NO trailing click here, leaving the flag armed.

      // A subsequent mouse interaction must clear the stale flag on pointerdown
      // so its click opens the file instead of being swallowed.
      await act(async () => {
        node.dispatchEvent(pointerEvent("pointerdown", "mouse"));
      });
      await act(async () => {
        node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });
      expect(onSelectFile).toHaveBeenCalledWith("./a.txt");

      act(() => root.unmount());
      container.remove();
    });

    it("re-derives draggability from each gesture (touch then mouse) with no stale state", async () => {
      const { root, container, node } = await mountTree(vi.fn());

      // Touch gesture -> not draggable.
      await act(async () => {
        node.dispatchEvent(touchEvent("pointerdown"));
        node.dispatchEvent(touchEvent("pointerup"));
      });
      expect(node.getAttribute("draggable")).toBe("false");

      // A subsequent mouse gesture on the SAME node restores draggability.
      await act(async () => {
        node.dispatchEvent(pointerEvent("pointerdown", "mouse"));
      });
      expect(node.getAttribute("draggable")).toBe("true");

      // And back to touch drops it again — capability tracks the live input.
      await act(async () => {
        node.dispatchEvent(touchEvent("pointerdown"));
      });
      expect(node.getAttribute("draggable")).toBe("false");

      act(() => root.unmount());
      container.remove();
    });
  });
});
