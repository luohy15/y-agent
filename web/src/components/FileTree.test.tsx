import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// FileTree pulls its data through `authFetch`; stub it to a small tree (one
// directory + two files) so we can drive pointer/mouse events against distinct
// nodes and prove the shared menu acts on the exact node that opened it.
const { authFetchMock } = vi.hoisted(() => ({ authFetchMock: vi.fn() }));
vi.mock("../api", () => ({ API: "", authFetch: authFetchMock }));

import FileTree from "./FileTree";

let clipboardWrite: ReturnType<typeof vi.fn>;

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

// A manually-settleable promise, used to hold a clipboard write "in flight"
// while the test dismisses/reopens the menu or unmounts, so we can prove the
// eventual resolution/rejection is treated as stale.
function deferred<T = void>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
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

// Locate a rendered node row by its file/dir name (the row carries the
// `cursor-pointer` class; wrapper divs and child rows don't share the name).
function nodeByName(container: HTMLElement, name: string): HTMLElement {
  const node = Array.from(container.querySelectorAll("div")).find(
    (d) => d.className.includes("cursor-pointer") && (d.textContent ?? "").includes(name),
  ) as HTMLElement | undefined;
  expect(node, `node "${name}" should be rendered`).toBeTruthy();
  return node as HTMLElement;
}

// The context menu renders through a portal on document.body; locate its
// action buttons by label.
function menuButton(label: string): HTMLButtonElement | undefined {
  return Array.from(document.body.querySelectorAll("button")).find(
    (b) => (b.textContent ?? "").trim() === label,
  ) as HTMLButtonElement | undefined;
}

// The floating menu div is the parent of its action buttons; read its anchor.
function menuAnchor(): { left: string; top: string } {
  const menu = menuButton("Copy Path")?.parentElement as HTMLElement;
  expect(menu, "context menu should be open").toBeTruthy();
  return { left: menu.style.left, top: menu.style.top };
}

describe("FileTree context menu (desktop right-click + touch long-press)", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    authFetchMock.mockReset();
    authFetchMock.mockImplementation(async (url: string) => {
      const u = decodeURIComponent(String(url));
      if (u.includes("/api/file/delete")) return { ok: true, json: async () => ({}) };
      if (u.includes("/api/file/list")) {
        if (u.includes("path=./sub")) {
          return { ok: true, json: async () => ({ entries: [{ name: "child.txt", type: "file" }] }) };
        }
        return {
          ok: true,
          json: async () => ({
            entries: [
              { name: "sub", type: "directory" },
              { name: "a.txt", type: "file" },
              { name: "b.txt", type: "file" },
            ],
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });
    clipboardWrite = vi.fn();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: clipboardWrite },
      configurable: true,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function mountTree(onSelectFile: (p: string) => void = vi.fn()) {
    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(FileTree, { isLoggedIn: true, onSelectFile }));
    });
    await act(async () => {
      await flushMicrotasks();
    });
    // All three root entries render.
    expect(container.textContent).toContain("a.txt");
    expect(container.textContent).toContain("b.txt");
    expect(container.textContent).toContain("sub");
    return { container, root, onSelectFile };
  }

  // (1) Desktop right-click and touch long-press must open the SAME menu path,
  // each anchored at its own supplied coordinates.
  it("opens the shared menu at the desktop right-click coordinates", async () => {
    const { container, root } = await mountTree();
    const node = nodeByName(container, "a.txt");

    await act(async () => {
      node.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 100, clientY: 200 }));
    });

    expect(menuButton("Copy Path")).toBeTruthy();
    expect(menuButton("Delete")).toBeTruthy(); // a.txt is a file
    expect(menuAnchor()).toEqual({ left: "100px", top: "200px" });

    act(() => root.unmount());
    container.remove();
  });

  it("opens the shared menu at the touch long-press coordinates", async () => {
    const { container, root } = await mountTree();
    const node = nodeByName(container, "a.txt");

    await act(async () => {
      node.dispatchEvent(touchEvent("pointerdown", { clientX: 42, clientY: 88 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });

    // Identical menu to the desktop path, anchored at the touch point.
    expect(menuButton("Copy Path")).toBeTruthy();
    expect(menuButton("Delete")).toBeTruthy();
    expect(menuAnchor()).toEqual({ left: "42px", top: "88px" });

    act(() => root.unmount());
    container.remove();
  });

  // (2) With two distinct nodes, the menu must act on the exact node that
  // opened it — Copy Path writes that node's path, Delete targets that file.
  it("Copy Path writes the exact path of the node that opened the menu", async () => {
    const { container, root } = await mountTree();

    // Open on a.txt via touch long-press, copy -> writes "a.txt".
    await act(async () => {
      nodeByName(container, "a.txt").dispatchEvent(touchEvent("pointerdown", { clientX: 10, clientY: 10 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    await act(async () => {
      menuButton("Copy Path")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(clipboardWrite).toHaveBeenLastCalledWith("a.txt");

    // Open on b.txt via desktop right-click, copy -> writes "b.txt".
    await act(async () => {
      nodeByName(container, "b.txt").dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 5, clientY: 5 }));
    });
    await act(async () => {
      menuButton("Copy Path")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(clipboardWrite).toHaveBeenLastCalledWith("b.txt");

    act(() => root.unmount());
    container.remove();
  });

  // Touch visual feedback: an immediate pressed state while the finger is
  // down, distinct from desktop hover (which needs no JS state).
  it("shows immediate pressed feedback on Copy Path while the pointer is down, and clears it on release", async () => {
    const { container, root } = await mountTree();
    await act(async () => {
      nodeByName(container, "a.txt").dispatchEvent(touchEvent("pointerdown", { clientX: 10, clientY: 10 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });

    const copyBtn = menuButton("Copy Path")!;
    expect(copyBtn.className.split(" ")).not.toContain("bg-sol-base03");

    await act(async () => {
      copyBtn.dispatchEvent(touchEvent("pointerdown"));
    });
    expect(menuButton("Copy Path")!.className.split(" ")).toContain("bg-sol-base03");

    await act(async () => {
      copyBtn.dispatchEvent(touchEvent("pointerup"));
    });
    expect(menuButton("Copy Path")!.className.split(" ")).not.toContain("bg-sol-base03");

    act(() => root.unmount());
    container.remove();
  });

  // Successful-copy acknowledgement: a brief "Copied" state, then the menu
  // auto-dismisses since the user's task (copying the path) is complete.
  it("shows a brief accessible Copied acknowledgement after a successful copy, then auto-closes the menu", async () => {
    const { container, root } = await mountTree();
    await act(async () => {
      nodeByName(container, "a.txt").dispatchEvent(touchEvent("pointerdown", { clientX: 10, clientY: 10 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });

    await act(async () => {
      menuButton("Copy Path")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await flushMicrotasks();
    });

    const copiedBtn = menuButton("Copied ✓");
    expect(copiedBtn).toBeTruthy();
    expect(copiedBtn!.getAttribute("aria-label")).toBe("Copied path");
    expect(copiedBtn!.getAttribute("aria-live")).toBe("polite");
    expect(copiedBtn!.disabled).toBe(true);

    // Brief window, then the menu closes on its own.
    await act(async () => {
      vi.advanceTimersByTime(700);
    });
    expect(menuButton("Copy Path")).toBeFalsy();
    expect(menuButton("Copied ✓")).toBeFalsy();

    act(() => root.unmount());
    container.remove();
  });

  // Clipboard failure: an accessible "Copy failed" state so the user can see
  // the copy didn't happen, but the menu stays open so they can retry.
  it("shows an accessible Copy failed acknowledgement when the clipboard write rejects, and keeps the menu open to retry", async () => {
    clipboardWrite.mockRejectedValue(new Error("clipboard denied"));
    const { container, root } = await mountTree();
    await act(async () => {
      nodeByName(container, "a.txt").dispatchEvent(touchEvent("pointerdown", { clientX: 10, clientY: 10 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });

    await act(async () => {
      menuButton("Copy Path")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await flushMicrotasks();
    });

    const failedBtn = menuButton("Copy failed");
    expect(failedBtn).toBeTruthy();
    expect(failedBtn!.getAttribute("aria-label")).toBe("Copy path failed");
    expect(failedBtn!.disabled).toBe(true);

    // Resets to the plain label after a brief window; menu never auto-closed.
    await act(async () => {
      vi.advanceTimersByTime(1200);
    });
    expect(menuButton("Copy Path")).toBeTruthy();
    expect(menuButton("Copy failed")).toBeFalsy();

    act(() => root.unmount());
    container.remove();
  });

  // Lifecycle isolation: a clipboard promise from an earlier Copy Path click
  // must not be able to mutate a later, unrelated menu instance.
  it("ignores a stale successful clipboard resolution after the menu is dismissed and reopened on another node", async () => {
    const pending = deferred<void>();
    clipboardWrite.mockImplementationOnce(() => pending.promise);
    const { container, root } = await mountTree();

    // Open on a.txt, click Copy Path -> clipboard write left pending.
    await act(async () => {
      nodeByName(container, "a.txt").dispatchEvent(touchEvent("pointerdown", { clientX: 10, clientY: 10 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    await act(async () => {
      menuButton("Copy Path")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await flushMicrotasks();
    });
    expect(clipboardWrite).toHaveBeenCalledTimes(1);
    expect(menuButton("Copied ✓")).toBeFalsy(); // still pending, no feedback yet

    // Dismiss (Escape) then reopen a fresh menu on b.txt before the a.txt
    // write resolves.
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(menuButton("Copy Path")).toBeFalsy();

    await act(async () => {
      nodeByName(container, "b.txt").dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 5, clientY: 5 }));
    });
    const freshBtn = menuButton("Copy Path");
    expect(freshBtn).toBeTruthy(); // fresh, idle menu for b.txt

    // The stale a.txt write now resolves.
    await act(async () => {
      pending.resolve();
      await flushMicrotasks();
    });

    // b.txt's fresh menu must be unaffected: still idle "Copy Path", never
    // flipped to "Copied", never auto-closed by the stale success.
    expect(menuButton("Copy Path")).toBeTruthy();
    expect(menuButton("Copied ✓")).toBeFalsy();
    await act(async () => {
      vi.advanceTimersByTime(700); // past the would-be auto-close window
    });
    expect(menuButton("Copy Path")).toBeTruthy();

    act(() => root.unmount());
    container.remove();
  });

  it("ignores a stale clipboard rejection after the menu is dismissed and reopened on another node", async () => {
    const pending = deferred<void>();
    clipboardWrite.mockImplementationOnce(() => pending.promise);
    const { container, root } = await mountTree();

    await act(async () => {
      nodeByName(container, "a.txt").dispatchEvent(touchEvent("pointerdown", { clientX: 10, clientY: 10 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    await act(async () => {
      menuButton("Copy Path")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await flushMicrotasks();
    });

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    await act(async () => {
      nodeByName(container, "b.txt").dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 5, clientY: 5 }));
    });
    expect(menuButton("Copy Path")).toBeTruthy();

    // The stale a.txt write now rejects.
    await act(async () => {
      pending.reject(new Error("clipboard denied"));
      await flushMicrotasks();
    });

    // b.txt's fresh menu must stay idle, not show "Copy failed".
    expect(menuButton("Copy Path")).toBeTruthy();
    expect(menuButton("Copy failed")).toBeFalsy();

    act(() => root.unmount());
    container.remove();
  });

  it("clears the pending success auto-close timer on unmount and ignores a clipboard settlement that arrives after", async () => {
    const pending = deferred<void>();
    clipboardWrite.mockImplementationOnce(() => pending.promise);
    const { container, root } = await mountTree();

    await act(async () => {
      nodeByName(container, "a.txt").dispatchEvent(touchEvent("pointerdown", { clientX: 10, clientY: 10 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    const baseline = vi.getTimerCount();

    await act(async () => {
      menuButton("Copy Path")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(clipboardWrite).toHaveBeenCalledTimes(1);
    // Still pending: no auto-close timer scheduled yet (that only happens
    // once the write resolves).
    expect(vi.getTimerCount()).toBe(baseline);

    act(() => root.unmount());
    container.remove();

    // The stale write now resolves after unmount. The isMountedRef/opId
    // guard must block it from touching state or scheduling a new timer;
    // no exception should propagate either.
    await act(async () => {
      pending.resolve();
      await flushMicrotasks();
    });
    expect(vi.getTimerCount()).toBe(baseline);
  });

  it("clears an already-scheduled success auto-close timer on unmount", async () => {
    const { container, root } = await mountTree();

    await act(async () => {
      nodeByName(container, "a.txt").dispatchEvent(touchEvent("pointerdown", { clientX: 10, clientY: 10 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    const baseline = vi.getTimerCount();

    await act(async () => {
      menuButton("Copy Path")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await flushMicrotasks();
    });
    // The clipboard write resolved synchronously (default mock): the 700ms
    // auto-close timer is now armed.
    expect(vi.getTimerCount()).toBe(baseline + 1);

    act(() => root.unmount());
    container.remove();

    // Unmount must clear that armed timer instead of leaving it to fire
    // (and touch state) against an unmounted tree.
    expect(vi.getTimerCount()).toBe(baseline);
  });

  it("Delete opens and acts on the exact file path of the node that opened the menu", async () => {
    const { container, root } = await mountTree();

    // Long-press b.txt -> menu -> Delete opens the confirm dialog for ./b.txt.
    await act(async () => {
      nodeByName(container, "b.txt").dispatchEvent(touchEvent("pointerdown", { clientX: 1, clientY: 1 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    await act(async () => {
      menuButton("Delete")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    // Dialog shows the exact path.
    const dialog = document.querySelector('[role="dialog"]') as HTMLElement;
    expect(dialog).toBeTruthy();
    expect(dialog.textContent).toContain("./b.txt");

    // Confirming issues the delete against that exact path.
    await act(async () => {
      menuButton("Delete")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      await flushMicrotasks();
    });
    const deleteCall = authFetchMock.mock.calls.find((c) => String(c[0]).includes("/api/file/delete"));
    expect(deleteCall).toBeTruthy();
    expect(JSON.parse(deleteCall![1].body)).toEqual({ path: "./b.txt" });

    act(() => root.unmount());
    container.remove();
  });

  // (3) Long-press on a directory must open the desktop-equivalent menu without
  // selecting the row or expanding/toggling the folder.
  it("long-press on a directory opens the menu without selecting or expanding it", async () => {
    const { container, root } = await mountTree();
    const dir = nodeByName(container, "sub");

    await act(async () => {
      dir.dispatchEvent(touchEvent("pointerdown", { clientX: 7, clientY: 7 }));
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });

    // Desktop-equivalent directory menu: Copy Path present, Delete absent (the
    // existing behavior gates Delete to files).
    expect(menuButton("Copy Path")).toBeTruthy();
    expect(menuButton("Delete")).toBeFalsy();

    // Not selected: `text-sol-base1` marks a selected row.
    expect(nodeByName(container, "sub").className).not.toContain("text-sol-base1");
    // Not expanded: children were never fetched and are not in the DOM.
    const subListed = authFetchMock.mock.calls.some((c) =>
      decodeURIComponent(String(c[0])).includes("path=./sub"),
    );
    expect(subListed).toBe(false);
    expect(container.textContent).not.toContain("child.txt");

    // The trailing click stays suppressed, so it still doesn't toggle open.
    await act(async () => {
      nodeByName(container, "sub").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const subListedAfter = authFetchMock.mock.calls.some((c) =>
      decodeURIComponent(String(c[0])).includes("path=./sub"),
    );
    expect(subListedAfter).toBe(false);
    expect(container.textContent).not.toContain("child.txt");

    act(() => root.unmount());
    container.remove();
  });

  // (4) A realistic completed gesture: pointerdown -> timer fires -> pointerup
  // -> trailing click. The click must be suppressed (no open/select).
  it("suppresses the trailing click of a completed pointerdown -> timer -> pointerup gesture", async () => {
    const { container, root, onSelectFile } = await mountTree();
    const node = nodeByName(container, "a.txt");

    await act(async () => {
      node.dispatchEvent(touchEvent("pointerdown"));
    });
    await act(async () => {
      vi.advanceTimersByTime(600); // long-press threshold -> menu opens
    });
    await act(async () => {
      node.dispatchEvent(touchEvent("pointerup")); // finger lifts after the menu
    });
    await act(async () => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true })); // trailing click
    });

    expect(menuButton("Copy Path")).toBeTruthy();
    expect(onSelectFile).not.toHaveBeenCalled();
    expect(nodeByName(container, "a.txt").className).not.toContain("text-sol-base1");

    act(() => root.unmount());
    container.remove();
  });

  it("still opens the file on a plain tap (short press, no long-press fired)", async () => {
    const { container, root, onSelectFile } = await mountTree();
    const node = nodeByName(container, "a.txt");

    await act(async () => {
      node.dispatchEvent(touchEvent("pointerdown"));
      node.dispatchEvent(touchEvent("pointerup")); // releases before threshold -> cancels timer
    });
    await act(async () => {
      vi.advanceTimersByTime(600); // timer was cancelled; nothing fires
    });
    expect(menuButton("Copy Path")).toBeFalsy();
    await act(async () => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onSelectFile).toHaveBeenCalledWith("./a.txt");

    act(() => root.unmount());
    container.remove();
  });

  it("cancels the long-press when the finger moves (scroll) so no menu opens", async () => {
    const { container, root, onSelectFile } = await mountTree();
    const node = nodeByName(container, "a.txt");

    await act(async () => {
      node.dispatchEvent(touchEvent("pointerdown"));
      node.dispatchEvent(touchEvent("pointermove")); // scroll gesture aborts the timer
    });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    expect(menuButton("Copy Path")).toBeFalsy();
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
      const { container, root } = await mountTree();
      const node = nodeByName(container, "a.txt");

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
      const { container, root } = await mountTree();
      const node = nodeByName(container, "a.txt");

      await act(async () => {
        node.dispatchEvent(touchEvent("pointerdown"));
      });
      // Native HTML5 drag disabled for this gesture: WebKit won't claim it.
      expect(node.getAttribute("draggable")).toBe("false");

      // The long-press still completes into the context menu.
      await act(async () => {
        vi.advanceTimersByTime(600);
      });
      expect(menuButton("Copy Path")).toBeTruthy();

      act(() => root.unmount());
      container.remove();
    });

    it("does not swallow a later mouse click when a touch long-press emitted no trailing click", async () => {
      const { container, root, onSelectFile } = await mountTree();
      const node = nodeByName(container, "a.txt");

      // Completed touch long-press arms the click-suppression flag...
      await act(async () => {
        node.dispatchEvent(touchEvent("pointerdown"));
      });
      await act(async () => {
        vi.advanceTimersByTime(600);
      });
      expect(menuButton("Copy Path")).toBeTruthy(); // menu opened
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
      const { container, root } = await mountTree();
      const node = nodeByName(container, "a.txt");

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
