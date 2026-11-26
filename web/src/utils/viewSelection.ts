// Persisted host view selection (todo 4468).
//
// One `viewSelection:host` row in the authenticated `user_preference` store,
// plus a user-scoped localStorage cache so the last centre mode, selected chat
// and trace filter paint instantly on reload and follow the user to a second
// device. The legacy per-key entries (`selectedChatId` / `chatHide` /
// `chatListTraceId`) are a one-time migration source while signed in and stay
// the live cache while signed out.

export const VIEW_SELECTION_KEY = "viewSelection:host";
export const VIEW_SELECTION_VERSION = 1;
export const VIEW_SELECTION_CACHE_PREFIX = "viewSelectionHost:";

export type CentreMode = "chat" | "files";

export interface ViewSelectionValue {
  version: typeof VIEW_SELECTION_VERSION;
  chatId: string | null;
  centreMode: CentreMode;
  traceId: string | null;
}

export const DEFAULT_VIEW_SELECTION: ViewSelectionValue = {
  version: VIEW_SELECTION_VERSION,
  chatId: null,
  centreMode: "chat",
  traceId: null,
};

export const LEGACY_VIEW_SELECTION_KEYS = [
  "selectedChatId",
  "chatHide",
  "chatListTraceId",
] as const;

function asId(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

/** Validated document, or null for anything malformed. */
export function parseViewSelection(raw: unknown): ViewSelectionValue | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  if (record.version !== VIEW_SELECTION_VERSION) return null;
  const centreMode =
    record.centreMode === "files" ? "files" : record.centreMode === "chat" ? "chat" : null;
  if (!centreMode) return null;
  return {
    version: VIEW_SELECTION_VERSION,
    chatId: asId(record.chatId),
    centreMode,
    traceId: asId(record.traceId),
  };
}

export function sameViewSelection(
  left: ViewSelectionValue,
  right: ViewSelectionValue,
): boolean {
  return (
    left.chatId === right.chatId &&
    left.centreMode === right.centreMode &&
    left.traceId === right.traceId
  );
}

/** Cache key for one signed-in account; null while signed out. */
export function viewSelectionCacheKey(email: string | null): string | null {
  return email ? `${VIEW_SELECTION_CACHE_PREFIX}${email}` : null;
}

export function readViewSelectionCache(email: string | null): ViewSelectionValue | null {
  const key = viewSelectionCacheKey(email);
  if (!key) return null;
  try {
    const raw = localStorage.getItem(key);
    return raw == null ? null : parseViewSelection(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function writeViewSelectionCache(
  email: string | null,
  value: ViewSelectionValue,
): void {
  const key = viewSelectionCacheKey(email);
  if (!key) return;
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Private mode or quota: the selection still lives in memory and the backend.
  }
}

export interface LegacyViewSelection {
  value: ViewSelectionValue;
  keys: string[];
}

/** Legacy per-key selection; also the one-time migration source. */
export function readLegacyViewSelection(): LegacyViewSelection | null {
  try {
    const chatId = asId(localStorage.getItem("selectedChatId"));
    const chatHide = localStorage.getItem("chatHide");
    const traceId = asId(localStorage.getItem("chatListTraceId"));
    if (chatId === null && chatHide === null && traceId === null) return null;
    return {
      value: {
        version: VIEW_SELECTION_VERSION,
        chatId,
        centreMode: chatHide === "true" ? "files" : "chat",
        traceId,
      },
      keys: [...LEGACY_VIEW_SELECTION_KEYS],
    };
  } catch {
    return null;
  }
}

/** Signed-out live cache: keep the legacy keys the pre-4468 build used. */
export function writeLegacyViewSelection(value: ViewSelectionValue): void {
  try {
    if (value.chatId) localStorage.setItem("selectedChatId", value.chatId);
    else localStorage.removeItem("selectedChatId");
    localStorage.setItem("chatHide", String(value.centreMode === "files"));
    if (value.traceId) localStorage.setItem("chatListTraceId", value.traceId);
    else localStorage.removeItem("chatListTraceId");
  } catch {
    // Private mode or quota: selection stays in memory.
  }
}

export function removeLegacyViewSelectionKeys(keys: readonly string[]): void {
  for (const key of keys) {
    try {
      localStorage.removeItem(key);
    } catch {
      // Nothing to do.
    }
  }
}

/** Drop every account's cached selection (logout / revoked access). */
export function clearViewSelectionCaches(): void {
  try {
    const keys: string[] = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key && key.startsWith(VIEW_SELECTION_CACHE_PREFIX)) keys.push(key);
    }
    for (const key of keys) localStorage.removeItem(key);
  } catch {
    // Storage unavailable; there is nothing cached to leak.
  }
}
