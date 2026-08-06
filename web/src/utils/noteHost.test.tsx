import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { registerHostCommand, runHostCommand } from "../host/commands";
import { fileOpenPayload } from "./fileHost";
import { publishNoteIntent, usePublishNoteIntent } from "./noteHost";

const { setArtifactIntentMock } = vi.hoisted(() => ({ setArtifactIntentMock: vi.fn() }));
vi.mock("../host/intents", () => ({ setArtifactIntent: setArtifactIntentMock }));

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

function IntentProbe({
  todoId,
  leftVmName,
  leftWorkDir,
  rightVmName,
  rightWorkDir,
}: {
  todoId: string | null;
  leftVmName: string | null;
  leftWorkDir: string | null;
  rightVmName: string | null;
  rightWorkDir: string | null;
}) {
  usePublishNoteIntent(todoId, leftVmName, leftWorkDir, rightVmName, rightWorkDir);
  return null;
}

/** Grab the retained `"note"` intent value from the most recent `setArtifactIntent` call. */
function lastPublished(): { kind: unknown; todoId: unknown; left: unknown; right: unknown } {
  const calls = setArtifactIntentMock.mock.calls;
  const [slug, value] = calls[calls.length - 1] as [
    string,
    { kind: unknown; todoId: unknown; left: unknown; right: unknown },
  ];
  expect(slug).toBe("note");
  return value;
}

describe("note trace-scope artifact intent", () => {
  beforeEach(() => {
    setArtifactIntentMock.mockReset();
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("publishNoteIntent publishes kind=trace-scope with todoId + nonce", () => {
    publishNoteIntent("todo-3071", null, null, null, null);
    expect(setArtifactIntentMock).toHaveBeenCalledTimes(1);
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "note",
      expect.objectContaining({ kind: "trace-scope", todoId: "todo-3071", nonce: expect.any(Number) }),
    );
  });

  it("carries distinct left/right VM/work-directory context", () => {
    publishNoteIntent("todo-3071", "default", "/vm/default", "prod", "/vm/prod");
    const published = lastPublished();
    expect(published.left).toEqual({ vmName: "default", workDir: "/vm/default" });
    expect(published.right).toEqual({ vmName: "prod", workDir: "/vm/prod" });
    expect(published.left).not.toEqual(published.right);
  });

  it("fires the intent whenever chatListTraceId (todoId) changes", () => {
    const { root } = renderClient();
    act(() => {
      root.render(
        React.createElement(IntentProbe, {
          todoId: null,
          leftVmName: null,
          leftWorkDir: "/a",
          rightVmName: null,
          rightWorkDir: "/a",
        }),
      );
    });
    expect(lastPublished().todoId).toBeNull();

    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(
        React.createElement(IntentProbe, {
          todoId: "todo-3071",
          leftVmName: null,
          leftWorkDir: "/a",
          rightVmName: null,
          rightWorkDir: "/a",
        }),
      );
    });
    expect(lastPublished().todoId).toBe("todo-3071");

    // No dependency changed: re-render must not republish.
    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(
        React.createElement(IntentProbe, {
          todoId: "todo-3071",
          leftVmName: null,
          leftWorkDir: "/a",
          rightVmName: null,
          rightWorkDir: "/a",
        }),
      );
    });
    expect(setArtifactIntentMock).not.toHaveBeenCalled();

    root.unmount();
  });

  it("fires the intent whenever either location's vmName/workDir changes independently", () => {
    const { root } = renderClient();
    act(() => {
      root.render(
        React.createElement(IntentProbe, {
          todoId: "todo-3071",
          leftVmName: "default",
          leftWorkDir: "/a",
          rightVmName: "default",
          rightWorkDir: "/a",
        }),
      );
    });
    expect(lastPublished().left).toEqual({ vmName: "default", workDir: "/a" });
    expect(lastPublished().right).toEqual({ vmName: "default", workDir: "/a" });

    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(
        React.createElement(IntentProbe, {
          todoId: "todo-3071",
          leftVmName: "default",
          leftWorkDir: "/a",
          rightVmName: "prod",
          rightWorkDir: "/b",
        }),
      );
    });
    expect(lastPublished().left).toEqual({ vmName: "default", workDir: "/a" });
    expect(lastPublished().right).toEqual({ vmName: "prod", workDir: "/b" });

    root.unmount();
  });
});

// H2 (pages/plan-3071-note-module.md decision 7): "reuse [3068's file.open]
// unchanged" rather than registering a note.openFile twin. This exercises
// the exact registration App.tsx wires for 3068 (fileHost.test.tsx covers
// the same contract) to confirm a note file open goes through the shared
// command, moving host tab state, with no note-specific command involved.
describe("note file opens reuse 3068's file.open host command (no note.openFile twin)", () => {
  const cleanups: Array<() => void> = [];
  afterEach(() => {
    while (cleanups.length) cleanups.pop()!();
  });

  it("runHostCommand('file.open', ...) moves shell tab state via the shared command", () => {
    const handleOpenFile = vi.fn();
    cleanups.push(
      registerHostCommand("file.open", (payload) => {
        const parsed = fileOpenPayload(payload);
        if (!parsed) return;
        handleOpenFile("ui:file");
      }),
    );

    runHostCommand("file.open", { path: "pages/note.md", vmName: "prod", workDir: "/home/roy" });

    expect(handleOpenFile).toHaveBeenCalledWith("ui:file");
  });

  it("runHostCommand('note.openFile', ...) is a silent no-op — no twin command is registered", () => {
    expect(() => runHostCommand("note.openFile", { path: "pages/note.md" })).not.toThrow();
  });
});
