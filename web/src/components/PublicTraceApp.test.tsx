// First-ever unit coverage for logged-out `/t/:shareId` (plan-3042-chatview.md V4).
// Confirms the public projection still hosts ChatSnapshotView for a selected chat
// and never depends on the module shell path.
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { useParamsMock, useSearchParamsMock } = vi.hoisted(() => ({
  useParamsMock: vi.fn(),
  useSearchParamsMock: vi.fn(),
}));

vi.mock("react-router", () => ({
  useParams: useParamsMock,
  useSearchParams: useSearchParamsMock,
}));

// Stub heavy children so the test pins PublicTraceApp's own wiring, not FileViewer.
vi.mock("./FileViewer", () => ({
  default: () => React.createElement("div", { "data-testid": "file-viewer" }, "file-viewer"),
}));
vi.mock("./ChatList", () => ({
  default: () => React.createElement("div", { "data-testid": "chat-list" }, "chat-list"),
}));
vi.mock("./PublicNoteList", () => ({
  default: () => React.createElement("div", { "data-testid": "note-list" }, "note-list"),
}));
vi.mock("./LinkList", () => ({
  default: () => React.createElement("div", { "data-testid": "link-list" }, "link-list"),
}));
vi.mock("./ChatSnapshotView", () => ({
  default: ({ chatId, messages }: { chatId: string; messages: unknown[] }) =>
    React.createElement(
      "div",
      { "data-testid": "chat-snapshot", "data-chat-id": chatId },
      `snapshot:${chatId}:${(messages as Array<{ content?: string }>)[0]?.content ?? ""}`,
    ),
}));

import PublicTraceApp from "./PublicTraceApp";

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

const SHARE = {
  chats: [
    {
      chat_id: "chat-abc",
      topic: "dev",
      skill: "impl",
      messages: [{ role: "user", content: "public hello" }],
    },
  ],
  todo_name: "todo 3042",
  todo_status: "active",
  todo: { todo_id: "3042", name: "chat module", desc: "migrate chat", status: "active" },
  notes: [],
  links: [],
};

describe("PublicTraceApp (logged-out /t/:shareId)", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    useParamsMock.mockReturnValue({ shareId: "share-7ef7c6" });
    useSearchParamsMock.mockReturnValue([new URLSearchParams(), vi.fn()]);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, SHARE)),
    );
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("loads the shared trace and renders ChatSnapshotView for the selected chat", async () => {
    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(PublicTraceApp));
      for (let i = 0; i < 12; i++) await Promise.resolve();
    });

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/trace/share?share_id=share-7ef7c6"),
    );
    // Default center mode is FileViewer (chatHide=true); switch to chat mode.
    const chatModeButton = Array.from(container.querySelectorAll("button")).find(
      (b) => b.getAttribute("title") === "Chat",
    );
    expect(chatModeButton).toBeTruthy();
    await act(async () => {
      chatModeButton!.click();
    });

    const snapshot = container.querySelector('[data-testid="chat-snapshot"]');
    expect(snapshot).toBeTruthy();
    expect(snapshot?.getAttribute("data-chat-id")).toBe("chat-abc");
    expect(container.textContent).toContain("snapshot:chat-abc:public hello");
    expect(container.textContent).toContain("todo 3042");

    act(() => root.unmount());
    container.remove();
  });

  it("shows the password gate when the share returns 401", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(401, { detail: "password required" }));

    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(PublicTraceApp));
      for (let i = 0; i < 12; i++) await Promise.resolve();
    });

    expect(container.textContent).toContain("password-protected");
    expect(container.querySelector('input[type="password"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="chat-snapshot"]')).toBeNull();

    act(() => root.unmount());
    container.remove();
  });
});
