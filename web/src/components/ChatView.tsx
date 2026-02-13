import { useState, useEffect, useRef, useCallback } from "react";
import { useSWRConfig } from "swr";
import { API, getToken } from "../api";
import MessageBubble, { type BubbleRole } from "./MessageBubble";
import ApprovalBar from "./ApprovalBar";

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

export default function ChatView({ chatId }: ChatViewProps) {
  const { mutate } = useSWRConfig();
  const [messages, setMessages] = useState<Message[]>([]);
  const [showApproval, setShowApproval] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

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

    const token = getToken();
    const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
    const es = new EventSource(`${API}/api/chat/messages?chat_id=${chatId}&last_index=0${tokenParam}`);

    const handleMessage = (raw: string) => {
      try {
        const evt = JSON.parse(raw);
        const msg = evt.data || evt;
        const role = msg.role || "assistant";
        const content = extractContent(msg.content);
        const tool = msg.tool;
        const timestamp = msg.timestamp;

        if (role === "user") {
          addMessage({ role: "user", content, timestamp });
        } else if (role === "assistant" && tool) {
          addMessage({ role: "tool_call", content, toolName: tool, arguments: msg.arguments, timestamp });
        } else if (role === "tool") {
          addMessage({ role: "tool_result", content, toolName: tool, timestamp });
        } else {
          addMessage({ role: "assistant", content, timestamp });
        }
      } catch {}
    };

    const handleAsk = (raw: string) => {
      try {
        const evt = JSON.parse(raw);
        const data = evt.data || evt;
        const toolName = data.tool_name || "";
        const args = data.tool_args || {};
        addMessage({ role: "tool_call", content: "", toolName, arguments: args });
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
      <div className="flex-1 flex items-center justify-center text-sol-base01 text-sm">
        Select a chat to view its conversation
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div ref={containerRef} className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-3">
        {messages.map((m, i) => (
          <MessageBubble key={i} role={m.role} content={m.content} toolName={m.toolName} arguments={m.arguments} timestamp={m.timestamp} />
        ))}
      </div>
      <ApprovalBar
        chatId={chatId}
        visible={showApproval}
        onApproved={() => {
          setShowApproval(false);
          mutate(`${API}/api/chat/list`);
        }}
      />
    </div>
  );
}
