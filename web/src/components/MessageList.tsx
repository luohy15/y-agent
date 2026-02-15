import { useState, useEffect, useRef } from "react";
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

// Strip invisible Unicode control characters that Safari renders as boxes
function stripInvisible(s: string): string {
  // Remove BOM, zero-width spaces, and other common invisible characters
  // eslint-disable-next-line no-control-regex
  return s.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\u200B-\u200F\u2028-\u202F\u2060-\u206F\uFEFF\uFFF9-\uFFFC]/g, "");
}

export function extractContent(content?: string | ContentPart[]): string {
  if (!content) return "";
  if (typeof content === "string") return stripInvisible(content);
  if (Array.isArray(content)) {
    return content
      .map((p) => {
        if (typeof p === "string") return stripInvisible(p);
        if (p.type === "text") return stripInvisible(p.text || "");
        if (p.type === "image") return "[image]";
        return "";
      })
      .join("");
  }
  return stripInvisible(String(content));
}

function isFileReadResult(m: Message): boolean {
  return (m.role === "tool_result" || m.role === "tool_denied") && m.toolName === "file_read";
}

type MessageGroup = { type: "single"; message: Message; index: number } | { type: "file_reads"; messages: Message[]; startIndex: number };

function groupMessages(messages: Message[]): MessageGroup[] {
  const groups: MessageGroup[] = [];
  let i = 0;
  while (i < messages.length) {
    if (isFileReadResult(messages[i])) {
      const batch: Message[] = [];
      const startIndex = i;
      while (i < messages.length && isFileReadResult(messages[i])) {
        batch.push(messages[i]);
        i++;
      }
      if (batch.length >= 2) {
        groups.push({ type: "file_reads", messages: batch, startIndex });
      } else {
        groups.push({ type: "single", message: batch[0], index: startIndex });
      }
    } else {
      groups.push({ type: "single", message: messages[i], index: i });
      i++;
    }
  }
  return groups;
}

function FileReadGroup({ messages, startIndex }: { messages: Message[]; startIndex: number }) {
  const [expanded, setExpanded] = useState(false);
  const paths = messages.map((m) => String(m.arguments?.path || "")).filter(Boolean);
  return (
    <div>
      <div
        className="text-[0.8rem] font-mono text-sol-cyan cursor-pointer flex items-center gap-1"
        onClick={() => setExpanded((v) => !v)}
      >
        <span>$ Read {messages.length} files</span>
        <span className="text-sol-base01 text-[0.65rem]">{expanded ? "▲" : "▼"}</span>
      </div>
      {!expanded && paths.length > 0 && (
        <div className="text-[0.65rem] text-sol-base01 font-mono truncate">{paths.join(", ")}</div>
      )}
      {expanded && (
        <div className="flex flex-col gap-2 mt-1">
          {messages.map((m, j) => (
            <MessageBubble key={startIndex + j} role={m.role} content={m.content} toolName={m.toolName} arguments={m.arguments} timestamp={m.timestamp} />
          ))}
        </div>
      )}
    </div>
  );
}

interface MessageListProps {
  messages: Message[];
  running?: boolean;
}

export default function MessageList({ messages, running }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages]);

  const groups = groupMessages(messages);

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-3 text-xs">
      {groups.map((g) =>
        g.type === "file_reads" ? (
          <FileReadGroup key={`fr-${g.startIndex}`} messages={g.messages} startIndex={g.startIndex} />
        ) : (
          <MessageBubble key={g.index} role={g.message.role} content={g.message.content} toolName={g.message.toolName} arguments={g.message.arguments} timestamp={g.message.timestamp} />
        )
      )}
      {running && (
        <div className="flex">
          <span className="inline-block w-2.5 h-5 bg-sol-base1" />
        </div>
      )}
    </div>
  );
}
