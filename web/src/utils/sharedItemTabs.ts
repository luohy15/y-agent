export type SharedItemKind = "note" | "chat";

export const SHARED_NOTE_TAB_PREFIX = "shared-note:";
export const SHARED_CHAT_TAB_PREFIX = "shared-chat:";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const TITLE_LIMIT = 200;

export interface OpenSharedItem {
  kind: SharedItemKind;
  shareId: string;
  refId: string;
  key: string;
  label: string;
}

export interface SharedNoteBody {
  kind: "note";
  refId: string;
  title: string;
  content: string | null;
}

export interface SharedChatBody {
  kind: "chat";
  refId: string;
  title: string;
  messages: unknown[];
}

export function isSharedItemTabKey(path: string): boolean {
  return path.startsWith(SHARED_NOTE_TAB_PREFIX) || path.startsWith(SHARED_CHAT_TAB_PREFIX);
}

export function sharedItemLabel(title: string, kind: SharedItemKind): string {
  const trimmed = title.trim();
  if (trimmed) return trimmed;
  return kind === "note" ? "Shared note" : "Shared chat";
}

export function sharedItemTabKey(kind: SharedItemKind, shareId: string, refId: string): string {
  const prefix = kind === "note" ? SHARED_NOTE_TAB_PREFIX : SHARED_CHAT_TAB_PREFIX;
  return `${prefix}${shareId}:${refId}`;
}

function boundedId(value: unknown): string | null {
  if (typeof value !== "string" || !ID_PATTERN.test(value)) return null;
  return value;
}

export function parseSharedItemTab(path: string): { kind: SharedItemKind; shareId: string; refId: string } | null {
  const kind: SharedItemKind | null = path.startsWith(SHARED_NOTE_TAB_PREFIX)
    ? "note"
    : path.startsWith(SHARED_CHAT_TAB_PREFIX)
      ? "chat"
      : null;
  if (!kind) return null;
  const rest = path.slice(kind === "note" ? SHARED_NOTE_TAB_PREFIX.length : SHARED_CHAT_TAB_PREFIX.length);
  const splitAt = rest.indexOf(":");
  if (splitAt <= 0) return null;
  const shareId = boundedId(rest.slice(0, splitAt));
  const refId = boundedId(rest.slice(splitAt + 1));
  if (!shareId || !refId) return null;
  return { kind, shareId, refId };
}

export function parseOpenSharedItem(payload: unknown): OpenSharedItem | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const raw = payload as { kind?: unknown; shareId?: unknown; refId?: unknown; title?: unknown };
  if (raw.kind !== "note" && raw.kind !== "chat") return null;
  const shareId = boundedId(raw.shareId);
  const refId = boundedId(raw.refId);
  if (!shareId || !refId) return null;
  if (raw.title != null && typeof raw.title !== "string") return null;
  if (typeof raw.title === "string" && raw.title.length > TITLE_LIMIT) return null;
  const kind = raw.kind;
  return {
    kind,
    shareId,
    refId,
    key: sharedItemTabKey(kind, shareId, refId),
    label: sharedItemLabel(typeof raw.title === "string" ? raw.title : "", kind),
  };
}

export function parseSharedItemBody(
  kind: SharedItemKind,
  refId: string,
  data: unknown,
): SharedNoteBody | SharedChatBody | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const row = data as { kind?: unknown; ref_id?: unknown; title?: unknown; content?: unknown; messages?: unknown };
  if (row.kind !== kind || row.ref_id !== refId || typeof row.title !== "string") return null;
  if (kind === "note") {
    if (row.content !== null && typeof row.content !== "string") return null;
    return { kind, refId, title: row.title, content: row.content };
  }
  if (!Array.isArray(row.messages)) return null;
  return { kind, refId, title: row.title, messages: row.messages };
}
