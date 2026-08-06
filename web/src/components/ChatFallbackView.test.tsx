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

vi.mock("./HostMessageView", async () => {
  const actual = await vi.importActual<typeof import("./HostMessageView")>("./HostMessageView");
  return {
    ...actual,
    default: ({ messages }: { messages: Array<{ content?: string }> }) =>
      React.createElement(
        "div",
        { "data-testid": "message-list" },
        messages.map((m, i) => React.createElement("div", { key: i }, m.content || "")),
      ),
  };
});

import ChatFallbackView from "./ChatFallbackView";

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

function jsonResponse(body: unknown, ok = true): Response {
  return {
    ok,
    status: ok ? 200 : 500,
    json: async () => body,
  } as unknown as Response;
}

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  closed = false;
  private listeners = new Map<string, Array<(e: MessageEvent) => void>>();
  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, handler: (e: MessageEvent) => void) {
    const list = this.listeners.get(type) ?? [];
    list.push(handler);
    this.listeners.set(type, list);
  }
  close() {
    this.closed = true;
  }
}

async function flush() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

describe("ChatFallbackView", () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    authFetchMock.mockReset();
    getTokenMock.mockReset();
    getTokenMock.mockReturnValue(null);
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("loads a snapshot and renders messages for an existing chat", async () => {
    authFetchMock.mockResolvedValue(
      jsonResponse({
        messages: [{ role: "user", content: "hello from snapshot" }],
        running: false,
        interrupted: false,
      }),
    );

    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(ChatFallbackView, { chatId: "chat-1" }));
      await flush();
    });

    expect(authFetchMock).toHaveBeenCalledWith(
      "http://test.local/api/chat/messages/snapshot?chat_id=chat-1",
    );
    expect(container.textContent).toContain("Degraded chat");
    expect(container.textContent).toContain("hello from snapshot");
    expect(FakeEventSource.instances).toHaveLength(0);

    act(() => root.unmount());
    container.remove();
  });

  it("posts /api/chat/message and reconnects when sending into an existing chat", async () => {
    authFetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          messages: [{ role: "user", content: "prior" }],
          running: false,
          interrupted: false,
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    const { container, root } = renderClient();
    await act(async () => {
      root.render(React.createElement(ChatFallbackView, { chatId: "chat-1", vmName: "dev" }));
      await flush();
    });

    const textarea = container.querySelector("textarea");
    expect(textarea).toBeTruthy();
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      nativeSetter.call(textarea, "follow up");
      textarea!.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const sendButton = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent === "Send",
    );
    expect(sendButton).toBeTruthy();
    await act(async () => {
      sendButton!.click();
      await flush();
    });

    expect(authFetchMock).toHaveBeenCalledWith(
      "http://test.local/api/chat/message",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ chat_id: "chat-1", prompt: "follow up", vm_name: "dev" }),
      }),
    );
    expect(FakeEventSource.instances.length).toBeGreaterThan(0);
    expect(FakeEventSource.instances[0].url).toContain("/api/chat/messages?chat_id=chat-1");

    act(() => root.unmount());
    container.remove();
  });

  it("creates a new chat via POST /api/chat when no chatId is selected", async () => {
    const onChatCreated = vi.fn();
    authFetchMock.mockResolvedValue(jsonResponse({ chat_id: "new-chat" }));

    const { container, root } = renderClient();
    await act(async () => {
      root.render(
        React.createElement(ChatFallbackView, {
          chatId: null,
          botName: "claude",
          onChatCreated,
        }),
      );
    });

    expect(container.textContent).toContain("No chat selected");
    const textarea = container.querySelector("textarea");
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      nativeSetter.call(textarea, "first prompt");
      textarea!.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const sendButton = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent === "Send",
    );
    await act(async () => {
      sendButton!.click();
      await flush();
    });

    expect(authFetchMock).toHaveBeenCalledWith(
      "http://test.local/api/chat",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ prompt: "first prompt", bot_name: "claude" }),
      }),
    );
    expect(onChatCreated).toHaveBeenCalledWith("new-chat");

    act(() => root.unmount());
    container.remove();
  });
});