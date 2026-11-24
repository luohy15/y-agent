import { useEffect, useState } from "react";
import { API, authFetch } from "../api";
import ChatSnapshotView from "./ChatSnapshotView";
import MarkdownPreview from "./shell/MarkdownPreview";
import {
  parseSharedItemBody,
  type SharedChatBody,
  type SharedItemKind,
  type SharedNoteBody,
} from "../utils/sharedItemTabs";

export const SHARE_UNAVAILABLE = "Couldn’t open this todo. It may no longer be shared with you.";

export function SharedNoteView({ title, content }: { title: string; content: string | null }) {
  return (
    <div className="h-full overflow-auto">
      <p className="px-3 pt-3 text-sm font-medium text-sol-base1">{title}</p>
      {content === null ? (
        <p role="status" className="p-3 text-sm text-sol-base01">Note snapshot unavailable.</p>
      ) : (
        <MarkdownPreview content={content} />
      )}
    </div>
  );
}

export function SharedChatView({ title, chatId, messages }: { title: string; chatId: string; messages: unknown[] }) {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <p className="px-3 pt-3 text-sm font-medium text-sol-base1">{title}</p>
      <ChatSnapshotView chatId={chatId} messages={messages} />
    </div>
  );
}

export async function fetchSharedItem(
  shareId: string,
  kind: SharedItemKind,
  refId: string,
): Promise<SharedNoteBody | SharedChatBody> {
  const params = new URLSearchParams({ share_id: shareId, kind, ref_id: refId });
  const res = await authFetch(`${API}/api/todo/shared/item?${params}`);
  if (!res.ok) throw new Error(SHARE_UNAVAILABLE);
  const body = parseSharedItemBody(kind, refId, await res.json());
  if (!body) throw new Error(SHARE_UNAVAILABLE);
  return body;
}

export function SharedItemPane({
  kind,
  shareId,
  refId,
  title,
  nonce,
}: {
  kind: SharedItemKind;
  shareId: string;
  refId: string;
  title: string;
  nonce: number;
}) {
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [note, setNote] = useState<SharedNoteBody | null>(null);
  const [chat, setChat] = useState<SharedChatBody | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setNote(null);
    setChat(null);
    fetchSharedItem(shareId, kind, refId)
      .then((body) => {
        if (cancelled) return;
        if (body.kind === "note") setNote(body);
        else setChat(body);
        setPhase("ready");
      })
      .catch(() => {
        if (!cancelled) setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, [kind, shareId, refId, nonce]);

  if (phase === "error") {
    return <p role="status" className="p-3 text-sm text-sol-base01">{SHARE_UNAVAILABLE}</p>;
  }
  if (phase !== "ready") {
    return <p className="p-3 text-sm italic text-sol-base01">Loading...</p>;
  }
  if (note) {
    return <SharedNoteView title={note.title.trim() || title} content={note.content} />;
  }
  if (chat) {
    return <SharedChatView title={chat.title.trim() || title} chatId={refId} messages={chat.messages} />;
  }
  return <p role="status" className="p-3 text-sm text-sol-base01">{SHARE_UNAVAILABLE}</p>;
}
