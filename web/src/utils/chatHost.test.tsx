import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { registerHostCommand, runHostCommand } from "../host/commands";
import {
  chatIdFromPayload,
  openChat,
  publishSelectedChatIntent,
  setChatTraceFilter,
  traceIdFromPayload,
  usePublishSelectedChatIntent,
} from "./chatHost";

const { setArtifactIntentMock } = vi.hoisted(() => ({ setArtifactIntentMock: vi.fn() }));
vi.mock("../host/intents", () => ({ setArtifactIntent: setArtifactIntentMock }));

function renderClient() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

function IntentProbe({ chatId, botName, traceId }: { chatId: string | null; botName?: string | null; traceId?: string | null }) {
  usePublishSelectedChatIntent(chatId, botName, traceId);
  return null;
}

describe("openChat / setChatTraceFilter", () => {
  it("openChat selects the chat, closes the list, and unhides the chat column", () => {
    const deps = {
      selectedChatId: null as string | null,
      setSelectedChatId: vi.fn(),
      setChatHide: vi.fn(),
      setChatListOpen: vi.fn(),
      bumpChatRefresh: vi.fn(),
    };
    openChat("chat-abc", deps);
    expect(deps.setSelectedChatId).toHaveBeenCalledWith("chat-abc");
    expect(deps.setChatListOpen).toHaveBeenCalledWith(false);
    expect(deps.setChatHide).toHaveBeenCalledWith(false);
    expect(deps.bumpChatRefresh).not.toHaveBeenCalled();
  });

  it("openChat bumps refresh when the same chat is re-selected", () => {
    const deps = {
      selectedChatId: "chat-abc",
      setSelectedChatId: vi.fn(),
      setChatHide: vi.fn(),
      setChatListOpen: vi.fn(),
      bumpChatRefresh: vi.fn(),
    };
    openChat("chat-abc", deps);
    expect(deps.bumpChatRefresh).toHaveBeenCalledTimes(1);
    expect(deps.setSelectedChatId).toHaveBeenCalledWith("chat-abc");
  });

  it("setChatTraceFilter updates the chat-list trace filter", () => {
    const setChatListTraceId = vi.fn();
    setChatTraceFilter("3042", setChatListTraceId);
    expect(setChatListTraceId).toHaveBeenCalledWith("3042");
    setChatTraceFilter(null, setChatListTraceId);
    expect(setChatListTraceId).toHaveBeenCalledWith(null);
  });
});

describe("runHostCommand chat.open moves shell state", () => {
  const cleanups: Array<() => void> = [];
  afterEach(() => {
    while (cleanups.length) cleanups.pop()!();
  });

  it("registers chat.open so runHostCommand selects the chat and unhides the column", () => {
    const setSelectedChatId = vi.fn();
    const setChatHide = vi.fn();
    const setChatListOpen = vi.fn();
    cleanups.push(
      registerHostCommand("chat.open", (payload) => {
        const chatId = chatIdFromPayload(payload);
        if (chatId === undefined) return;
        openChat(chatId, { setSelectedChatId, setChatHide, setChatListOpen });
      }),
    );

    runHostCommand("chat.open", { chatId: "chat-open-1" });

    expect(setSelectedChatId).toHaveBeenCalledWith("chat-open-1");
    expect(setChatListOpen).toHaveBeenCalledWith(false);
    expect(setChatHide).toHaveBeenCalledWith(false);
  });

  it("registers chat.setTraceFilter so runHostCommand updates the filter", () => {
    const setChatListTraceId = vi.fn();
    cleanups.push(
      registerHostCommand("chat.setTraceFilter", (payload) => {
        const traceId = traceIdFromPayload(payload);
        if (traceId === undefined) return;
        setChatTraceFilter(traceId, setChatListTraceId);
      }),
    );

    runHostCommand("chat.setTraceFilter", { traceId: "todo-99" });
    expect(setChatListTraceId).toHaveBeenCalledWith("todo-99");
  });
});

describe("selected-chat artifact intent", () => {
  beforeEach(() => {
    setArtifactIntentMock.mockReset();
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("publishSelectedChatIntent publishes kind=selected with chatId + nonce", () => {
    publishSelectedChatIntent("chat-xyz");
    expect(setArtifactIntentMock).toHaveBeenCalledTimes(1);
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ kind: "selected", chatId: "chat-xyz", botName: null, nonce: expect.any(Number) }),
    );
  });

  it("publishSelectedChatIntent carries botName when given (D-C)", () => {
    publishSelectedChatIntent("chat-xyz", "gpt-5");
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ kind: "selected", chatId: "chat-xyz", botName: "gpt-5" }),
    );
  });

  it("publishSelectedChatIntent carries traceId when given, and defaults it to null (R7)", () => {
    publishSelectedChatIntent("chat-xyz", "gpt-5", "todo-99");
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ kind: "selected", chatId: "chat-xyz", botName: "gpt-5", traceId: "todo-99" }),
    );

    setArtifactIntentMock.mockClear();
    publishSelectedChatIntent("chat-xyz");
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ traceId: null }),
    );
  });

  it("fires the selected intent whenever selectedChatId changes", () => {
    const { root } = renderClient();
    act(() => {
      root.render(React.createElement(IntentProbe, { chatId: "chat-1" }));
    });
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ kind: "selected", chatId: "chat-1" }),
    );

    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(React.createElement(IntentProbe, { chatId: "chat-2" }));
    });
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ kind: "selected", chatId: "chat-2" }),
    );

    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(React.createElement(IntentProbe, { chatId: null }));
    });
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ kind: "selected", chatId: null }),
    );
    root.unmount();
  });

  // R7 (plan-3046-right-sidebar.md): the retained intent must widen to carry
  // the host trace filter so the right chat panel can consume it (W3 gates
  // which mount actually applies it, but the payload itself is global).
  it("fires the selected intent whenever the trace filter is set, changed, or cleared", () => {
    const { root } = renderClient();
    act(() => {
      root.render(React.createElement(IntentProbe, { chatId: "chat-1", traceId: null }));
    });
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ chatId: "chat-1", traceId: null }),
    );

    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(React.createElement(IntentProbe, { chatId: "chat-1", traceId: "todo-99" }));
    });
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ chatId: "chat-1", traceId: "todo-99" }),
    );

    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(React.createElement(IntentProbe, { chatId: "chat-1", traceId: "todo-100" }));
    });
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ chatId: "chat-1", traceId: "todo-100" }),
    );

    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(React.createElement(IntentProbe, { chatId: "chat-1", traceId: null }));
    });
    expect(setArtifactIntentMock).toHaveBeenCalledWith(
      "chat",
      expect.objectContaining({ chatId: "chat-1", traceId: null }),
    );

    // chatId/botName-only re-renders (older call sites) remain green: no
    // traceId argument still publishes traceId: null, never undefined.
    setArtifactIntentMock.mockClear();
    act(() => {
      root.render(React.createElement(IntentProbe, { chatId: "chat-1" }));
    });
    expect(setArtifactIntentMock).not.toHaveBeenCalled();

    root.unmount();
  });
});
