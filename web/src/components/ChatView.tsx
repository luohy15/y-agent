import { useState, useEffect, useRef, useCallback } from "react";
import { useSWRConfig } from "swr";
import { API, getToken, authFetch } from "../api";
import MessageBubble, { type BubbleRole } from "./MessageBubble";
import ApprovalModal from "./ApprovalBar";
import NewChatInput from "./NewChatInput";

interface Message {
  role: BubbleRole;
  content: string;
  toolName?: string;
  arguments?: Record<string, unknown>;
  timestamp?: string;
}

interface ContentPart {
  type: string;
  text?: string;
}

interface ChatViewProps {
  chatId: string | null;
  onChatCreated?: (chatId: string) => void;
}

function extractContent(content?: string | ContentPart[]): string {
  if (!content) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((p) => {
        if (typeof p === "string") return p;
        if (p.type === "text") return p.text || "";
        if (p.type === "image") return "[image]";
        return "";
      })
      .join("");
  }
  return String(content);
}

export default function ChatView({ chatId, onChatCreated }: ChatViewProps) {
  const { mutate } = useSWRConfig();
  const [messages, setMessages] = useState<Message[]>([]);
  const [showApproval, setShowApproval] = useState(false);
  const [pendingToolCalls, setPendingToolCalls] = useState<Array<{ id: string; function: { name: string; arguments: string }; status?: string }>>([]);
  const [autoApprove, setAutoApprove] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const toggleAutoApprove = useCallback(async () => {
    if (!chatId) return;
    const next = !autoApprove;
    setAutoApprove(next);
    await authFetch(`${API}/api/chat/auto_approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, auto_approve: next }),
    });
  }, [chatId, autoApprove]);

  const scrollToBottom = useCallback(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, []);

  const addMessage = useCallback((msg: Message) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    if (!chatId) return;

    setMessages([]);
    setShowApproval(false);
    setPendingToolCalls([]);
    setAutoApprove(false);

    const token = getToken();
    const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
    const es = new EventSource(`${API}/api/chat/messages?chat_id=${chatId}&last_index=0${tokenParam}`);

    const handleMessage = (raw: string) => {
      try {
        const evt = JSON.parse(raw);
        const msg = evt.data || evt;
        const role = msg.role || "assistant";
        const content = extractContent(msg.content);
        const timestamp = msg.timestamp;

        if (role === "user") {
          addMessage({ role: "user", content, timestamp });
        } else if (role === "assistant" && msg.tool_calls) {
          // Assistant with tool_calls: show content if any, skip tool_calls display
          if (content.trim()) {
            addMessage({ role: "assistant", content, timestamp });
          }
        } else if (role === "tool") {
          // Tool result: combined display with tool name + args + result
          addMessage({ role: "tool_result", content, toolName: msg.tool, arguments: msg.arguments, timestamp });
        } else {
          addMessage({ role: "assistant", content, timestamp });
        }
      } catch {}
    };

    const handleAsk = (raw: string) => {
      try {
        const evt = JSON.parse(raw);
        const data = evt.data || evt;
        const toolCalls = data.tool_calls || [];
        setPendingToolCalls(toolCalls);
        setShowApproval(true);
      } catch {}
    };

    es.addEventListener("message", (e) => handleMessage(e.data));
    for (const t of ["text", "tool_use", "tool_result"]) {
      es.addEventListener(t, (e) => handleMessage((e as MessageEvent).data));
    }
    es.addEventListener("ask", (e) => handleAsk((e as MessageEvent).data));
    es.addEventListener("waiting_approval", (e) => handleAsk((e as MessageEvent).data));
    es.addEventListener("done", () => {
      addMessage({ role: "system", content: "Chat completed" });
      es.close();
      mutate(`${API}/api/chat/list`);
    });
    es.addEventListener("error", () => {});

    return () => {
      es.close();
    };
  }, [chatId, addMessage, mutate]);

  if (!chatId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        {onChatCreated ? (
          <NewChatInput onCreated={onChatCreated} />
        ) : (
          <span className="text-sol-base01 text-sm">Select a chat or start a new one</span>
        )}
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div className="flex items-center px-6 py-2 border-b border-sol-base02 shrink-0">
        <label className="flex items-center gap-2 text-xs text-sol-base1 cursor-pointer select-none">
          <span>Auto-approve</span>
          <button
            onClick={toggleAutoApprove}
            className={`relative w-8 h-4 rounded-full transition-colors ${autoApprove ? "bg-sol-green" : "bg-sol-base02"}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-sol-base3 transition-transform ${autoApprove ? "translate-x-4" : ""}`} />
          </button>
        </label>
      </div>
      <div ref={containerRef} className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-3">
        {messages.map((m, i) => (
          <MessageBubble key={i} role={m.role} content={m.content} toolName={m.toolName} arguments={m.arguments} timestamp={m.timestamp} />
        ))}
      </div>
      <ApprovalModal
        chatId={chatId}
        toolCalls={pendingToolCalls}
        visible={showApproval}
        onApproved={() => {
          setShowApproval(false);
          setPendingToolCalls([]);
          mutate(`${API}/api/chat/list`);
        }}
      />
    </div>
  );
}
