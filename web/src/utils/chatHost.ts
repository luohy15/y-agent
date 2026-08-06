// Host-side chat control-plane gestures for the future modules/chat UI
// (plan P2, pages/plan-3042-control-plane.md). Pure helpers so App.tsx can
// wire host commands / selected-chat intent without bloating the shell, and so
// the verify unit tests can exercise shell-state movement without mounting App.
import { useEffect } from "react";
import { setArtifactIntent } from "../host/intents";

export interface OpenChatDeps {
  selectedChatId?: string | null;
  setSelectedChatId: (id: string | null) => void;
  setChatHide: (hide: boolean) => void;
  setChatListOpen: (open: boolean) => void;
  /** Bump when the same chat is re-selected (mirrors handleSelectChat). */
  bumpChatRefresh?: () => void;
}

/** Select a chat and unhide the chat column (FileViewer onSelectChat body). */
export function openChat(chatId: string | null, deps: OpenChatDeps): void {
  if (chatId && chatId === deps.selectedChatId) deps.bumpChatRefresh?.();
  deps.setSelectedChatId(chatId);
  deps.setChatListOpen(false);
  deps.setChatHide(false);
}

/** Filter the host chat list by trace/todo id (`chatListTraceId`). */
export function setChatTraceFilter(
  traceId: string | null,
  setChatListTraceId: (id: string | null) => void,
): void {
  setChatListTraceId(traceId);
}

/** Host -> chat artifact focus intent published whenever selectedChatId changes. */
export function publishSelectedChatIntent(chatId: string | null): void {
  setArtifactIntent("chat", { kind: "selected", chatId, nonce: Date.now() });
}

/** Publish the selected-chat intent on every selectedChatId change (including null). */
export function usePublishSelectedChatIntent(selectedChatId: string | null): void {
  useEffect(() => {
    publishSelectedChatIntent(selectedChatId);
  }, [selectedChatId]);
}

/** Parse `{ chatId }` from a host-command payload; undefined means malformed. */
export function chatIdFromPayload(payload: unknown): string | null | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const { chatId } = payload as { chatId?: unknown };
  if (chatId === null) return null;
  if (typeof chatId === "string") return chatId;
  return undefined;
}

/** Parse `{ traceId }` from a host-command payload; undefined means malformed. */
export function traceIdFromPayload(payload: unknown): string | null | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const { traceId } = payload as { traceId?: unknown };
  if (traceId === null) return null;
  if (typeof traceId === "string") return traceId;
  return undefined;
}
