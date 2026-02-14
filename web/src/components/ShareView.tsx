import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router";
import { API, getToken } from "../api";
import MessageBubble, { type BubbleRole } from "./MessageBubble";

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

function parseMessages(rawMessages: any[]): Message[] {
  // Build tool_call_id → {name, args} map from assistant messages
  const toolCallInfo: Record<string, { name: string; args: Record<string, unknown> }> = {};
  for (const msg of rawMessages) {
    if (msg.role === "assistant" && msg.tool_calls) {
      for (const tc of msg.tool_calls) {
        const func = tc.function || {};
        let toolArgs: Record<string, unknown> = {};
        try { toolArgs = JSON.parse(func.arguments || "{}"); } catch {}
        toolCallInfo[tc.id] = { name: func.name, args: toolArgs };
      }
    }
  }

  const result: Message[] = [];
  for (const msg of rawMessages) {
    const role = msg.role || "assistant";
    const content = extractContent(msg.content);

    if (role === "user") {
      result.push({ role: "user", content, timestamp: msg.timestamp });
    } else if (role === "assistant" && msg.tool_calls) {
      if (content.trim()) {
        result.push({ role: "assistant", content, timestamp: msg.timestamp });
      }
      // Skip tool_pending — tool_result will show the command
    } else if (role === "tool") {
      const info = toolCallInfo[msg.tool_call_id];
      const toolName = info?.name || msg.tool;
      const toolArgs = info?.args || msg.arguments;
      const denied = typeof content === "string" && content.startsWith("ERROR: User denied");
      result.push({ role: denied ? "tool_denied" : "tool_result", content, toolName, arguments: toolArgs, timestamp: msg.timestamp });
    } else {
      result.push({ role: "assistant", content, timestamp: msg.timestamp });
    }
  }
  return result;
}

export default function ShareView() {
  const { shareId } = useParams<{ shareId: string }>();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isLoggedIn = !!getToken();

  useEffect(() => {
    if (!shareId) return;
    setLoading(true);
    setError(null);
    fetch(`${API}/api/chat/share?share_id=${encodeURIComponent(shareId)}`)
      .then((r) => {
        if (!r.ok) throw new Error("Shared chat not found");
        return r.json();
      })
      .then((data) => {
        setMessages(parseMessages(data.messages || []));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [shareId]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <span className="text-sol-base01 text-sm">Loading...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center">
        <span className="text-sol-red text-sm">{error}</span>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-2 border-b border-sol-base02 shrink-0">
        <span className="text-xs text-sol-base01">Shared conversation</span>
      </div>
      <div ref={containerRef} className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-3">
        {messages.map((m, i) => (
          <MessageBubble key={i} role={m.role} content={m.content} toolName={m.toolName} arguments={m.arguments} timestamp={m.timestamp} />
        ))}
      </div>
      <div className="px-6 py-3 border-t border-sol-base02 shrink-0 flex justify-center">
        <button
          onClick={() => navigate(isLoggedIn ? "/" : "/")}
          className="px-4 py-2 bg-sol-blue text-sol-base03 rounded-md text-sm font-semibold cursor-pointer"
        >
          {isLoggedIn ? "Continue chatting" : "Login to continue"}
        </button>
      </div>
    </div>
  );
}
