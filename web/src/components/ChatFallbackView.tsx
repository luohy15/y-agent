// Degraded host chat surface (plan-3042-chatview.md D1f / V4). Read + send only:
// snapshot + live SSE over host `/api/chat/messages`, MessageList, and a plain
// send box posting `/api/chat/message`. No steer / export / TOC / share / artifacts
// chrome — that stays in the module shell. Used when a shell claimant's bundle
// fails to load (V4) and, from V6, as the no-module shell-slot branch.
import { useCallback, useEffect, useRef, useState } from "react";
import { API, authFetch, getToken } from "../api";
import MessageList, { type Message } from "./MessageList";
import {
  filterTrailingEmptyAssistantMessages,
  parseChatMessages,
  parseRawChatMessage,
} from "./chatMessageParser";

interface ChatFallbackViewProps {
  chatId: string | null;
  vmName?: string | null;
  botName?: string | null;
  onChatCreated?: (chatId: string) => void;
}

export default function ChatFallbackView({
  chatId,
  vmName,
  botName,
  onChatCreated,
}: ChatFallbackViewProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [completed, setCompleted] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const idxRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const displayMessages = filterTrailingEmptyAssistantMessages(messages);

  const addMessage = useCallback((msg: Message) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const updateToolMessage = useCallback((toolCallId: string, updates: Partial<Message>) => {
    setMessages((prev) =>
      prev.map((m) => (m.toolCallId === toolCallId ? { ...m, ...updates } : m)),
    );
  }, []);

  const connectSSE = useCallback(
    (id: string, fromIndex: number) => {
      if (esRef.current) esRef.current.close();
      setCompleted(false);

      const token = getToken();
      const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
      const es = new EventSource(
        `${API}/api/chat/messages?chat_id=${id}&last_index=${fromIndex}${tokenParam}`,
      );
      esRef.current = es;

      const handleMessage = (raw: string) => {
        try {
          const evt = JSON.parse(raw);
          idxRef.current = (evt.index ?? idxRef.current) + 1;
          for (const m of parseRawChatMessage(evt)) {
            if ((m.role === "tool_result" || m.role === "tool_denied") && m.toolCallId) {
              updateToolMessage(m.toolCallId, {
                role: m.role,
                content: m.content,
                ...(m.toolName ? { toolName: m.toolName } : {}),
                ...(m.arguments ? { arguments: m.arguments } : {}),
              });
            } else {
              addMessage(m);
            }
          }
        } catch {
          /* ignore malformed SSE frames */
        }
      };

      es.addEventListener("message", (e) => handleMessage(e.data));
      for (const t of ["text", "tool_use", "tool_result"]) {
        es.addEventListener(t, (e) => handleMessage((e as MessageEvent).data));
      }
      es.addEventListener("done", () => {
        setCompleted(true);
        es.close();
        esRef.current = null;
        authFetch(`${API}/api/chat/messages/snapshot?chat_id=${encodeURIComponent(id)}`)
          .then((r) => r.json())
          .then((data) => {
            const rawMessages = data.messages || [];
            setMessages(parseChatMessages(rawMessages));
            idxRef.current = rawMessages.length;
          })
          .catch(() => {});
      });
      es.addEventListener("error", () => {});
    },
    [addMessage, updateToolMessage],
  );

  useEffect(() => {
    if (!chatId) {
      setMessages([]);
      setCompleted(false);
      idxRef.current = 0;
      return;
    }
    setMessages([]);
    setCompleted(false);
    idxRef.current = 0;
    let cancelled = false;

    authFetch(`${API}/api/chat/messages/snapshot?chat_id=${encodeURIComponent(chatId)}`)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        setMessages(parseChatMessages(data.messages || []));
        idxRef.current = data.messages?.length ?? 0;
        if (data.interrupted) {
          setCompleted(true);
        } else if (data.running) {
          connectSSE(chatId, idxRef.current);
        } else if ((data.messages?.length ?? 0) > 0) {
          setCompleted(true);
        }
      })
      .catch(() => {
        if (!cancelled) connectSSE(chatId, 0);
      });

    return () => {
      cancelled = true;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [chatId, connectSSE]);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      if (!chatId) {
        if (!onChatCreated) return;
        const res = await authFetch(`${API}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            prompt: text,
            ...(vmName ? { vm_name: vmName } : {}),
            ...(botName ? { bot_name: botName } : {}),
          }),
        });
        if (!res.ok) return;
        const data = await res.json();
        setDraft("");
        onChatCreated(data.chat_id);
        return;
      }
      await authFetch(`${API}/api/chat/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: chatId,
          prompt: text,
          ...(vmName ? { vm_name: vmName } : {}),
          ...(botName ? { bot_name: botName } : {}),
        }),
      });
      setDraft("");
      connectSSE(chatId, idxRef.current);
    } finally {
      setSending(false);
    }
  }, [draft, sending, chatId, vmName, botName, onChatCreated, connectSSE]);

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-x-hidden h-full">
      <div className="px-3 py-1 text-[0.65rem] font-mono text-sol-base01 border-b border-sol-base02 bg-sol-base03 shrink-0">
        Degraded chat (module shell unavailable)
      </div>
      {chatId ? (
        <div className="flex-1 flex min-h-0 relative">
          <MessageList
            messages={displayMessages}
            running={!completed}
            showProgress={false}
            scrollContainerRef={scrollRef}
          />
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-sol-base01 text-sm italic px-4 text-center">
          No chat selected. Type below to start one.
        </div>
      )}
      <div className="mx-4 border-t border-sol-base02 shrink-0">
        <div className="flex items-start px-2 py-1.5 border-b border-sol-base02">
          <span className="text-sm sm:text-[0.775rem] text-sol-base01 font-mono mr-2 select-none leading-[1.4]">
            &gt;
          </span>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send();
              }
            }}
            rows={1}
            disabled={sending}
            placeholder={chatId ? "Send a message…" : "Start a chat…"}
            className="flex-1 min-w-0 bg-transparent text-sol-base1 text-sm sm:text-[0.775rem] font-mono outline-none resize-none leading-[1.4] placeholder:text-sol-base01/60 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={sending || !draft.trim()}
            className="ml-2 px-2 py-0.5 bg-sol-cyan text-sol-base03 rounded text-xs font-semibold cursor-pointer disabled:opacity-40 disabled:cursor-default shrink-0"
          >
            {sending ? "…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
