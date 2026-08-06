import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { authFetchMock, getTokenMock } = vi.hoisted(() => ({
  authFetchMock: vi.fn(),
  getTokenMock: vi.fn(() => null),
}));

vi.mock("../api", () => ({
  API: "http://test.local",
  authFetch: authFetchMock,
  getToken: getTokenMock,
}));

const { artifactViewMock, patchDiffMock, imageLightboxMock } = vi.hoisted(() => ({
  artifactViewMock: vi.fn((_props: Record<string, unknown>) => React.createElement("div", { "data-testid": "artifact-view-mock" })),
  patchDiffMock: vi.fn((_props: Record<string, unknown>) => React.createElement("div", { "data-testid": "patch-diff-mock" })),
  imageLightboxMock: vi.fn((_props: Record<string, unknown>) => null),
}));

vi.mock("./ArtifactView", () => ({ default: artifactViewMock }));
vi.mock("@pierre/diffs/react", () => ({ PatchDiff: patchDiffMock }));
vi.mock("./ImageLightbox", () => ({ default: imageLightboxMock }));

import HostMessageView, { buildTurnDisplay, type HostMessage } from "./HostMessageView";

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

async function flush() {
  for (let i = 0; i < 20; i += 1) await Promise.resolve();
}

describe("buildTurnDisplay", () => {
  it("collapses intermediate assistant/tool activity into one process item per turn", () => {
    const messages: HostMessage[] = [
      { role: "user", content: "do the thing" },
      { role: "assistant", content: "starting" },
      { role: "tool_result", content: "ok", toolName: "bash" },
      { role: "assistant", content: "final answer" },
    ];
    const items = buildTurnDisplay(messages);
    expect(items).toHaveLength(3);
    expect(items[0].message).toBe(messages[0]);
    expect(items[1].process).toEqual([messages[1], messages[2]]);
    expect(items[2].message).toBe(messages[3]);
  });

  it("keeps a preamble's final assistant message when there is no leading user turn", () => {
    const messages: HostMessage[] = [
      { role: "tool_result", content: "ok", toolName: "read" },
      { role: "assistant", content: "preamble answer" },
    ];
    const items = buildTurnDisplay(messages);
    expect(items).toHaveLength(2);
    expect(items[0].process).toEqual([messages[0]]);
    expect(items[1].message).toBe(messages[1]);
  });

  it("keeps trailing tool activity after the round's only assistant message instead of dropping it", () => {
    const messages: HostMessage[] = [
      { role: "user", content: "run it" },
      { role: "assistant", content: "kicking off" },
      { role: "tool_result", content: "done", toolName: "bash" },
    ];
    const items = buildTurnDisplay(messages);
    expect(items).toHaveLength(3);
    expect(items[0].message).toBe(messages[0]);
    expect(items[1].process).toEqual([messages[2]]);
    expect(items[2].message).toBe(messages[1]);
  });

  it("keeps a tool-only turn (no assistant message yet) as a process item, preserving the running cursor case", () => {
    const messages: HostMessage[] = [
      { role: "user", content: "run it" },
      { role: "tool_pending", content: "", toolName: "bash" },
    ];
    const items = buildTurnDisplay(messages);
    expect(items).toHaveLength(2);
    expect(items[0].message).toBe(messages[0]);
    expect(items[1].process).toEqual([messages[1]]);
  });
});

describe("HostMessageView", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    authFetchMock.mockReset();
    getTokenMock.mockReset();
    getTokenMock.mockReturnValue(null);
    artifactViewMock.mockClear();
    patchDiffMock.mockClear();
    imageLightboxMock.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the user and only the final assistant at top level, with a collapsed-by-default process disclosure that expands", async () => {
    const messages: HostMessage[] = [
      { role: "user", content: "do the thing" },
      { role: "assistant", content: "narrating progress" },
      { role: "tool_result", content: "tool output here", toolName: "bash" },
      { role: "assistant", content: "the final answer" },
    ];

    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(HostMessageView, { messages }));
      await flush();
    });

    const turnRow = container.querySelector(".flex.flex-col.gap-3") as HTMLElement;
    expect(turnRow).toBeTruthy();
    expect(turnRow.children).toHaveLength(3);

    const [userItem, processItem, finalItem] = Array.from(turnRow.children);
    expect(userItem.textContent).toContain("do the thing");
    expect(finalItem.textContent).toContain("the final answer");
    expect(finalItem.textContent).not.toContain("narrating progress");
    expect(finalItem.textContent).not.toContain("tool output here");

    expect(processItem.tagName.toLowerCase()).toBe("details");
    const details = processItem as HTMLDetailsElement;
    expect(details.open).toBe(false);
    // Collapsed process content still renders the existing HostBubble output
    // (nothing is discarded), it is only hidden until the summary is toggled.
    expect(details.textContent).toContain("narrating progress");
    expect(details.textContent).toContain("tool output here");

    const summary = details.querySelector('[data-testid="process-summary"]') as HTMLElement;
    expect(summary).toBeTruthy();

    await act(async () => {
      summary.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await flush();
    });

    expect(details.open).toBe(true);

    act(() => root.unmount());
    container.remove();
  });

  it("pins the shared-leaf contract: mermaid fence, edit tool result, and image reach their existing host leaves with the expected inputs", async () => {
    const messages: HostMessage[] = [
      { role: "user", content: "show me" },
      { role: "assistant", content: "```mermaid\ngraph TD; A-->B;\n```" },
      {
        role: "tool_result",
        content: "edited",
        toolName: "edit",
        arguments: { file_path: "src/foo.ts", old_string: "a", new_string: "b" },
      },
      { role: "assistant", content: "final", images: ["https://cdn.example.com/pic.png"] },
    ];

    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(HostMessageView, { messages }));
      await flush();
    });

    // The mermaid fence lives on the intermediate assistant message, which is
    // folded into the process disclosure, not the top-level final assistant.
    expect(artifactViewMock).toHaveBeenCalled();
    const artifactProps = artifactViewMock.mock.calls[0][0];
    expect(artifactProps.type).toBe("mermaid");
    expect(artifactProps.spec).toContain("graph TD");

    expect(patchDiffMock).toHaveBeenCalled();
    const diffProps = patchDiffMock.mock.calls[0][0];
    expect(diffProps.patch).toContain("src/foo.ts");
    expect(diffProps.patch).toContain("-a");
    expect(diffProps.patch).toContain("+b");

    expect(imageLightboxMock).toHaveBeenCalled();
    const imageCalls = imageLightboxMock.mock.calls;
    const imageProps = imageCalls[imageCalls.length - 1][0];
    expect(imageProps.images).toEqual(["https://cdn.example.com/pic.png"]);

    const turnRow = container.querySelector(".flex.flex-col.gap-3") as HTMLElement;
    const finalItem = turnRow.children[turnRow.children.length - 1];
    expect(finalItem.textContent).toContain("final");
    expect(finalItem.querySelector("details")).toBeNull();

    act(() => root.unmount());
    container.remove();
  });
});
