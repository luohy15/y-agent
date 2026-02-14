import { useEffect, useRef } from "react";
import MessageBubble, { type BubbleRole } from "./MessageBubble";

export interface Message {
  role: BubbleRole;
  content: string;
  toolName?: string;
  arguments?: Record<string, unknown>;
  toolCallId?: string;
  timestamp?: string;
}

interface ContentPart {
  type: string;
  text?: string;
}

export function extractContent(content?: string | ContentPart[]): string {
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

interface MessageListProps {
  messages: Message[];
}

export default function MessageList({ messages }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-3">
      {messages.map((m, i) => (
        <MessageBubble key={i} role={m.role} content={m.content} toolName={m.toolName} arguments={m.arguments} timestamp={m.timestamp} />
      ))}
    </div>
  );
}
