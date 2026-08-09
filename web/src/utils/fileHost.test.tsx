import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { registerHostCommand, runHostCommand } from "../host/commands";
import {
  fileOpenPayload,
  fileSearchPayload,
  isHostWorkspaceTab,
  isOrdinaryFilePath,
  publishFileContext,
  publishFileOpenAction,
  publishFileRefresh,
  publishFileSearchAction,
  usePublishFileContext,
} from "./fileHost";

const { setArtifactIntentMock } = vi.hoisted(() => ({ setArtifactIntentMock: vi.fn() }));
vi.mock("../host/intents", () => ({ setArtifactIntent: setArtifactIntentMock }));

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

function ContextProbe({
  leftVmName,
  leftWorkDir,
  rightVmName,
  rightWorkDir,
}: {
  leftVmName: string | null;
  leftWorkDir: string | null;
  rightVmName: string | null;
  rightWorkDir: string | null;
}) {
  usePublishFileContext(leftVmName, leftWorkDir, rightVmName, rightWorkDir);
  return null;
}

/** Grab the retained `"file"` intent value from the most recent `setArtifactIntent` call. */
function lastPublished(): { left: unknown; right: unknown; action: unknown; nonce?: unknown } {
  const calls = setArtifactIntentMock.mock.calls;
  const [slug, value] = calls[calls.length - 1] as [
    string,
    { left: unknown; right: unknown; action: unknown; nonce?: unknown },
  ];
  expect(slug).toBe("file");
  return value;
}

describe("fileOpenPayload / fileSearchPayload", () => {
  it("fileOpenPayload requires a string path, defaulting vmName/workDir to null", () => {
    expect(fileOpenPayload({ path: "notes/a.md" })).toEqual({ path: "notes/a.md", vmName: null, workDir: null });
    expect(fileOpenPayload({ path: "notes/a.md", vmName: "prod", workDir: "/home/roy" })).toEqual({
      path: "notes/a.md",
      vmName: "prod",
      workDir: "/home/roy",
    });
  });

  it("fileOpenPayload forwards an optional finite line", () => {
    expect(fileOpenPayload({ path: "notes/a.md", line: 42 })).toEqual({
      path: "notes/a.md",
      vmName: null,
      workDir: null,
      line: 42,
    });
    expect(fileOpenPayload({ path: "notes/a.md", line: "42" as unknown as number })).toEqual({
      path: "notes/a.md",
      vmName: null,
      workDir: null,
    });
  });

  it("fileOpenPayload rejects a missing or non-string path", () => {
    expect(fileOpenPayload(undefined)).toBeUndefined();
    expect(fileOpenPayload({})).toBeUndefined();
    expect(fileOpenPayload({ path: 42 })).toBeUndefined();
  });

  it("fileSearchPayload tolerates a missing payload", () => {
    expect(fileSearchPayload(undefined)).toEqual({ vmName: null, workDir: null });
    expect(fileSearchPayload({ vmName: "prod", workDir: "/home/roy" })).toEqual({
      vmName: "prod",
      workDir: "/home/roy",
    });
  });
});

describe("host vs ordinary file path classification (C1)", () => {
  it("keeps special/ui/diff/artifact tabs on the host and ordinary paths off it", () => {
    expect(isHostWorkspaceTab("trace.md")).toBe(true);
    expect(isHostWorkspaceTab("ui:file")).toBe(true);
    expect(isHostWorkspaceTab("diff:src/a.ts")).toBe(true);
    expect(isHostWorkspaceTab("artifact:abc.mermaid")).toBe(true);
    expect(isHostWorkspaceTab("email.md")).toBe(true);
    expect(isHostWorkspaceTab("pages/plan.md")).toBe(false);
    expect(isOrdinaryFilePath("pages/plan.md")).toBe(true);
    expect(isOrdinaryFilePath("ui:file")).toBe(false);
  });
});

describe("runHostCommand file.open / file.close / file.search", () => {
  const cleanups: Array<() => void> = [];
  afterEach(() => {
    while (cleanups.length) cleanups.pop()!();
  });

  it("registers file.open so runHostCommand opens a host ordinary tab and publishes the open action", () => {
    const handleOpenFile = vi.fn();
    cleanups.push(
      registerHostCommand("file.open", (payload) => {
        const parsed = fileOpenPayload(payload);
        if (!parsed) return;
        handleOpenFile(parsed.path, parsed.vmName, parsed.workDir, parsed.line);
        publishFileOpenAction(parsed.path, parsed.vmName, parsed.workDir, parsed.line);
      }),
    );
    setArtifactIntentMock.mockClear();

    runHostCommand("file.open", { path: "notes/a.md", vmName: "prod", workDir: "/home/roy", line: 12 });

    expect(handleOpenFile).toHaveBeenCalledWith("notes/a.md", "prod", "/home/roy", 12);
    expect(lastPublished().action).toEqual(
      expect.objectContaining({ kind: "open", path: "notes/a.md", vmName: "prod", workDir: "/home/roy", line: 12 }),
    );
  });

  it("file.open is a silent no-op for a malformed payload", () => {
    const handleOpenFile = vi.fn();
    cleanups.push(
      registerHostCommand("file.open", (payload) => {
        const parsed = fileOpenPayload(payload);
        if (!parsed) return;
        handleOpenFile(parsed.path);
      }),
    );
    runHostCommand("file.open", {});
    expect(handleOpenFile).not.toHaveBeenCalled();
  });

  it("registers file.close so runHostCommand closes a tab id when provided", () => {
    const handleCloseFile = vi.fn();
    cleanups.push(registerHostCommand("file.close", (payload) => {
      if (payload && typeof payload === "object" && typeof (payload as { tabId?: unknown }).tabId === "string") {
        handleCloseFile((payload as { tabId: string }).tabId);
      }
    }));
    runHostCommand("file.close", { tabId: "tab-1" });
    expect(handleCloseFile).toHaveBeenCalledWith("tab-1");
  });

  it("registers file.search so runHostCommand opens the host search dialog", () => {
    const openSearch = vi.fn();
    cleanups.push(
      registerHostCommand("file.search", (payload) => {
        const { vmName, workDir } = fileSearchPayload(payload);
        void vmName;
        void workDir;
        openSearch();
      }),
    );

    runHostCommand("file.search", { vmName: "prod", workDir: "/home/roy" });

    expect(openSearch).toHaveBeenCalled();
  });
});

describe("retained file intent: context and action coexist (review-3068-file-browser-seam.md finding 1)", () => {
  beforeEach(() => {
    setArtifactIntentMock.mockReset();
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("publishFileContext publishes both locations, with action left at its prior value", () => {
    publishFileOpenAction("notes/a.md", "prod", "/home/roy");
    setArtifactIntentMock.mockClear();

    publishFileContext(null, "/vm/default", "prod", "/vm/prod");

    const published = lastPublished();
    expect(published.left).toEqual({ vmName: null, workDir: "/vm/default" });
    expect(published.right).toEqual({ vmName: "prod", workDir: "/vm/prod" });
    // The action published moments earlier is still there: a context update
    // must not clobber an unconsumed open/search action.
    expect(published.action).toEqual(
      expect.objectContaining({ kind: "open", path: "notes/a.md" }),
    );
  });

  it("publishFileOpenAction publishes the action, with left/right left at their prior values", () => {
    publishFileContext(null, "/vm/default", "prod", "/vm/prod");
    setArtifactIntentMock.mockClear();

    publishFileOpenAction("notes/b.md", null, null, 7);

    const published = lastPublished();
    expect(published.action).toEqual(expect.objectContaining({ kind: "open", path: "notes/b.md", line: 7 }));
    // The context published moments earlier is still there: an action must
    // not clobber the last-known per-location context.
    expect(published.left).toEqual({ vmName: null, workDir: "/vm/default" });
    expect(published.right).toEqual({ vmName: "prod", workDir: "/vm/prod" });
  });

  it("publishFileSearchAction likewise leaves left/right untouched", () => {
    publishFileContext("default", "/vm/default", "prod", "/vm/prod");
    setArtifactIntentMock.mockClear();

    publishFileSearchAction("prod", "/vm/prod");

    const published = lastPublished();
    expect(published.action).toEqual(expect.objectContaining({ kind: "search" }));
    expect(published.left).toEqual({ vmName: "default", workDir: "/vm/default" });
    expect(published.right).toEqual({ vmName: "prod", workDir: "/vm/prod" });
  });

  it("fires the context publish whenever either location's vmName/workDir changes", () => {
    const { root } = renderClient();
    act(() => {
      root.render(React.createElement(ContextProbe, { leftVmName: null, leftWorkDir: "/a", rightVmName: null, rightWorkDir: "/a" }));
    });
    expect(lastPublished().left).toEqual({ vmName: null, workDir: "/a" });
    expect(lastPublished().right).toEqual({ vmName: null, workDir: "/a" });

    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(React.createElement(ContextProbe, { leftVmName: null, leftWorkDir: "/a", rightVmName: "prod", rightWorkDir: "/b" }));
    });
    expect(lastPublished().right).toEqual({ vmName: "prod", workDir: "/b" });

    // No dependency changed: re-render must not republish (mirrors chatHost's
    // no-op-on-unchanged-deps behavior).
    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(React.createElement(ContextProbe, { leftVmName: null, leftWorkDir: "/a", rightVmName: "prod", rightWorkDir: "/b" }));
    });
    expect(setArtifactIntentMock).not.toHaveBeenCalled();

    root.unmount();
  });

  // H4 (review-3068-file-panel.md finding 1): shell refresh bumps a top-level
  // `nonce` (note panel convention) without clobbering left/right/action.
  it("publishFileRefresh bumps top-level nonce and leaves left/right/action untouched", () => {
    publishFileContext(null, "/vm/default", "prod", "/vm/prod");
    publishFileOpenAction("notes/a.md", "prod", "/vm/prod");
    setArtifactIntentMock.mockClear();

    publishFileRefresh();

    const published = lastPublished();
    expect(typeof published.nonce).toBe("number");
    expect(published.nonce).toBeGreaterThan(0);
    expect(published.left).toEqual({ vmName: null, workDir: "/vm/default" });
    expect(published.right).toEqual({ vmName: "prod", workDir: "/vm/prod" });
    expect(published.action).toEqual(
      expect.objectContaining({ kind: "open", path: "notes/a.md", vmName: "prod", workDir: "/vm/prod" }),
    );
  });

  it("context and action publishes re-send the last refresh nonce unchanged", () => {
    publishFileRefresh();
    const firstNonce = lastPublished().nonce;
    expect(typeof firstNonce).toBe("number");
    setArtifactIntentMock.mockClear();

    publishFileContext(null, "/a", "prod", "/b");
    expect(lastPublished().nonce).toBe(firstNonce);
    setArtifactIntentMock.mockClear();

    publishFileSearchAction("prod", "/b");
    expect(lastPublished().nonce).toBe(firstNonce);
  });
});
