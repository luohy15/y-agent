import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { registerHostCommand, runHostCommand } from "../host/commands";
import {
  fileOpenPayload,
  fileSearchPayload,
  publishFileContext,
  publishFileOpenAction,
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
function lastPublished(): { left: unknown; right: unknown; action: unknown } {
  const calls = setArtifactIntentMock.mock.calls;
  const [slug, value] = calls[calls.length - 1] as [string, { left: unknown; right: unknown; action: unknown }];
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

describe("runHostCommand file.open / file.close / file.search", () => {
  const cleanups: Array<() => void> = [];
  afterEach(() => {
    while (cleanups.length) cleanups.pop()!();
  });

  it("registers file.open so runHostCommand opens the ui:file tab and publishes the open action", () => {
    const handleOpenFile = vi.fn();
    cleanups.push(
      registerHostCommand("file.open", (payload) => {
        const parsed = fileOpenPayload(payload);
        if (!parsed) return;
        handleOpenFile("ui:file");
        publishFileOpenAction(parsed.path, parsed.vmName, parsed.workDir);
      }),
    );
    setArtifactIntentMock.mockClear();

    runHostCommand("file.open", { path: "notes/a.md", vmName: "prod", workDir: "/home/roy" });

    expect(handleOpenFile).toHaveBeenCalledWith("ui:file");
    expect(lastPublished().action).toEqual(
      expect.objectContaining({ kind: "open", path: "notes/a.md", vmName: "prod", workDir: "/home/roy" }),
    );
  });

  it("file.open is a silent no-op for a malformed payload", () => {
    const handleOpenFile = vi.fn();
    cleanups.push(
      registerHostCommand("file.open", (payload) => {
        const parsed = fileOpenPayload(payload);
        if (!parsed) return;
        handleOpenFile("ui:file");
      }),
    );
    runHostCommand("file.open", {});
    expect(handleOpenFile).not.toHaveBeenCalled();
  });

  it("registers file.close so runHostCommand closes the ui:file tab", () => {
    const handleCloseFile = vi.fn();
    cleanups.push(registerHostCommand("file.close", () => handleCloseFile("ui:file")));
    runHostCommand("file.close");
    expect(handleCloseFile).toHaveBeenCalledWith("ui:file");
  });

  it("registers file.search so runHostCommand opens the ui:file tab and publishes the search action", () => {
    const handleOpenFile = vi.fn();
    cleanups.push(
      registerHostCommand("file.search", (payload) => {
        const { vmName, workDir } = fileSearchPayload(payload);
        handleOpenFile("ui:file");
        publishFileSearchAction(vmName, workDir);
      }),
    );
    setArtifactIntentMock.mockClear();

    runHostCommand("file.search", { vmName: "prod", workDir: "/home/roy" });

    expect(handleOpenFile).toHaveBeenCalledWith("ui:file");
    expect(lastPublished().action).toEqual(
      expect.objectContaining({ kind: "search", vmName: "prod", workDir: "/home/roy" }),
    );
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

    publishFileOpenAction("notes/b.md", null, null);

    const published = lastPublished();
    expect(published.action).toEqual(expect.objectContaining({ kind: "open", path: "notes/b.md" }));
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
});
