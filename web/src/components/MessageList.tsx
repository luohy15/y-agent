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

function isToolMessage(m: Message): boolean {
  return m.role === "tool_pending" || m.role === "tool_result" || m.role === "tool_denied";
}

function fileToolKind(m: Message): string | null {
  if (m.role !== "tool_result" && m.role !== "tool_denied") return null;
  const name = m.toolName?.toLowerCase();
  if (name === "file_read" || name === "read") return "Read";
  if (name === "file_write" || name === "write") return "Write";
  if (name === "file_edit" || name === "edit") return "Edit";
  return null;
}

// Display items for rendering
type DisplayItem =
  | { type: "message"; message: Message; index: number }
  | { type: "tool_summary"; count: number; index: number }
  | { type: "file_tools"; kind: string; messages: Message[]; startIndex: number };

// Level 0: user + last assistant per round (between user messages)
function filterLevel0(messages: Message[]): DisplayItem[] {
  const items: DisplayItem[] = [];
  // Split into rounds: each round starts at a user message
  const roundStarts: number[] = [];
  for (let i = 0; i < messages.length; i++) {
    if (messages[i].role === "user") roundStarts.push(i);
  }
  // Handle messages before first user message
  if (roundStarts.length === 0 || roundStarts[0] > 0) {
    const end = roundStarts.length > 0 ? roundStarts[0] : messages.length;
    const lastAssistantIdx = findLastAssistant(messages, 0, end);
    if (lastAssistantIdx >= 0) {
      items.push({ type: "message", message: messages[lastAssistantIdx], index: lastAssistantIdx });
    }
  }
  for (let r = 0; r < roundStarts.length; r++) {
    const start = roundStarts[r];
    const end = r + 1 < roundStarts.length ? roundStarts[r + 1] : messages.length;
    // Add user message
    items.push({ type: "message", message: messages[start], index: start });
    // Add last assistant in this round
    const lastAssistantIdx = findLastAssistant(messages, start + 1, end);
    if (lastAssistantIdx >= 0) {
      items.push({ type: "message", message: messages[lastAssistantIdx], index: lastAssistantIdx });
    }
  }
  return items;
}

function findLastAssistant(messages: Message[], from: number, to: number): number {
  for (let i = to - 1; i >= from; i--) {
    if (messages[i].role === "assistant") return i;
  }
  return -1;
}

// Level 1: user + all assistants + tool summaries (consecutive tools → "N tools")
function filterLevel1(messages: Message[]): DisplayItem[] {
  const items: DisplayItem[] = [];
  let toolCount = 0;
  let toolStartIdx = 0;
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (isToolMessage(m)) {
      if (toolCount === 0) toolStartIdx = i;
      toolCount++;
    } else {
      if (toolCount > 0) {
        items.push({ type: "tool_summary", count: toolCount, index: toolStartIdx });
        toolCount = 0;
      }
      items.push({ type: "message", message: m, index: i });
    }
  }
  if (toolCount > 0) {
    items.push({ type: "tool_summary", count: toolCount, index: toolStartIdx });
  }
  return items;
}

// Level 2: all messages with file tool grouping (same kind grouped together)
function filterLevel2(messages: Message[]): DisplayItem[] {
  const items: DisplayItem[] = [];
  let i = 0;
  while (i < messages.length) {
    const kind = fileToolKind(messages[i]);
    if (kind) {
      const batch: Message[] = [];
      const startIndex = i;
      while (i < messages.length && fileToolKind(messages[i]) === kind) {
        batch.push(messages[i]);
        i++;
      }
      if (batch.length >= 2) {
        items.push({ type: "file_tools", kind, messages: batch, startIndex });
      } else {
        items.push({ type: "message", message: batch[0], index: startIndex });
      }
    } else {
      items.push({ type: "message", message: messages[i], index: i });
      i++;
    }
  }
  return items;
}

function FileToolGroup({ kind, messages, startIndex }: { kind: string; messages: Message[]; startIndex: number }) {
  const [expanded, setExpanded] = useState(false);
  const paths = messages.map((m) => String(m.arguments?.path || m.arguments?.file_path || "")).filter(Boolean);
  return (
    <div>
      <div
        className="text-[0.8rem] font-mono text-sol-cyan cursor-pointer flex items-center gap-1"
        onClick={() => setExpanded((v) => !v)}
      >
        <span>$ {kind} {messages.length} files</span>
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

function ToolSummary({ count }: { count: number }) {
  return (
    <div className="text-[0.775rem] font-mono text-sol-base01">
      called {count} tool{count > 1 ? "s" : ""}
    </div>
  );
}

interface MessageListProps {
  messages: Message[];
  running?: boolean;
  centered?: boolean;
  showProcess: boolean;
  showDetail: boolean;
}

export default function MessageList({ messages, running, centered, showProcess, showDetail }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages]);

  const items = showDetail ? filterLevel2(messages) : showProcess ? filterLevel1(messages) : filterLevel0(messages);

  const innerClass = centered ? "max-w-3xl mx-auto w-full flex flex-col gap-3" : "flex flex-col gap-3";

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto px-6 py-4 text-xs">
      <div className={innerClass}>
      {items.map((item) => {
        if (item.type === "tool_summary") {
          return <ToolSummary key={`ts-${item.index}`} count={item.count} />;
        }
        if (item.type === "file_tools") {
          return <FileToolGroup key={`fr-${item.startIndex}`} kind={item.kind} messages={item.messages} startIndex={item.startIndex} />;
        }
        return (
          <MessageBubble key={item.index} role={item.message.role} content={item.message.content} toolName={item.message.toolName} arguments={item.message.arguments} timestamp={item.message.timestamp} />
        );
      })}
      {running && (
        <div className="flex">
          <span className="inline-block w-2.5 h-5 bg-sol-base1" />
        </div>
      )}
      </div>
    </div>
  );
}
