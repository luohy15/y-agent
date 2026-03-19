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
  | { type: "process_summary"; toolCounts: Record<string, number>; assistantCount: number; index: number; roundMessages: Message[]; roundStartIndex: number };

// Collect tool call stats for a range of messages
function collectProcessStats(messages: Message[], from: number, to: number): { toolCounts: Record<string, number>; assistantCount: number } {
  const toolCounts: Record<string, number> = {};
  let assistantCount = 0;
  for (let i = from; i < to; i++) {
    const m = messages[i];
    if (isToolMessage(m) && m.toolName) {
      const label = getToolLabel(m.toolName);
      toolCounts[label] = (toolCounts[label] || 0) + 1;
    } else if (m.role === "assistant") {
      assistantCount++;
    }
  }
  return { toolCounts, assistantCount };
}

function getToolLabel(toolName: string): string {
  const n = toolName.toLowerCase();
  if (n === "bash") return "Bash";
  if (n === "read" || n === "file_read") return "Read";
  if (n === "write" || n === "file_write") return "Write";
  if (n === "edit" || n === "file_edit") return "Edit";
  if (n === "grep") return "Grep";
  if (n === "glob") return "Glob";
  if (n === "agent") return "Agent";
  if (n === "websearch" || n === "webfetch") return toolName;
  if (n === "todowrite") return "Todo";
  return toolName;
}

// Level 0: user + last assistant per round (between user messages) + process summary
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
    // Add process summary if there are tool calls or multiple assistants in this round
    const stats = collectProcessStats(messages, start + 1, end);
    const totalTools = Object.values(stats.toolCounts).reduce((a, b) => a + b, 0);
    if (totalTools > 0) {
      const roundMsgs = messages.slice(start + 1, end);
      items.push({ type: "process_summary", toolCounts: stats.toolCounts, assistantCount: stats.assistantCount, index: start + 1, roundMessages: roundMsgs, roundStartIndex: start + 1 });
    }
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


function FileToolGroup({ kind, messages, startIndex, onOpenFile }: { kind: string; messages: Message[]; startIndex: number; onOpenFile?: (path: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const shortPath = (p: string) => { const parts = p.split("/"); return parts.length <= 2 ? p : parts.slice(-2).join("/"); };
  const paths = messages.map((m) => shortPath(String(m.arguments?.path || m.arguments?.file_path || ""))).filter(Boolean);

  const iconMap: Record<string, { icon: string; color: string; bg: string }> = {
    Read: { icon: "\u2193", color: "text-sol-cyan", bg: "bg-sol-cyan/15" },
    Write: { icon: "\u2191", color: "text-sol-green", bg: "bg-sol-green/15" },
    Edit: { icon: "\u0394", color: "text-sol-yellow", bg: "bg-sol-yellow/15" },
  };
  const meta = iconMap[kind] || { icon: "\u25C6", color: "text-sol-base01", bg: "bg-sol-base01/15" };

  return (
    <div>
      <div
        className="font-mono text-[0.775rem] sm:text-[0.725rem] cursor-pointer flex items-center gap-1.5 select-none"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className={`inline-flex items-center justify-center w-5 h-5 rounded text-[0.65rem] font-bold shrink-0 ${meta.bg} ${meta.color}`}>
          {meta.icon}
        </span>
        <span className={`${meta.color} font-semibold shrink-0`}>{kind}</span>
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[0.65rem] bg-sol-base02 text-sol-base0">
          {messages.length} files
        </span>
        <span className="text-sol-base01 text-[0.6rem] ml-auto">{expanded ? "\u25B2" : "\u25BC"}</span>
      </div>
      {!expanded && paths.length > 0 && (
        <div className="text-[0.65rem] text-sol-base01 font-mono truncate ml-6.5">{paths.join(", ")}</div>
      )}
      {expanded && (
        <div className="flex flex-col gap-1.5 mt-1 ml-6.5">
          {messages.map((m, j) => (
            <MessageBubble key={startIndex + j} role={m.role} content={m.content} toolName={m.toolName} arguments={m.arguments} timestamp={m.timestamp} onOpenFile={onOpenFile} />
          ))}
        </div>
      )}
    </div>
  );
}

const toolIconMap: Record<string, { icon: string; color: string; bg: string }> = {
  Bash: { icon: ">_", color: "text-sol-blue", bg: "bg-sol-blue/15" },
  Read: { icon: "\u2193", color: "text-sol-cyan", bg: "bg-sol-cyan/15" },
  Write: { icon: "\u2191", color: "text-sol-green", bg: "bg-sol-green/15" },
  Edit: { icon: "\u0394", color: "text-sol-yellow", bg: "bg-sol-yellow/15" },
  Grep: { icon: "/", color: "text-sol-violet", bg: "bg-sol-violet/15" },
  Glob: { icon: "*", color: "text-sol-violet", bg: "bg-sol-violet/15" },
  Agent: { icon: "\u25C8", color: "text-sol-magenta", bg: "bg-sol-magenta/15" },
  Todo: { icon: "\u2713", color: "text-sol-green", bg: "bg-sol-green/15" },
};
const defaultToolIcon = { icon: "\u25C6", color: "text-sol-base01", bg: "bg-sol-base01/15" };

function ProcessSummary({ toolCounts, roundMessages, roundStartIndex, defaultExpanded, onOpenFile }: { toolCounts: Record<string, number>; assistantCount: number; roundMessages: Message[]; roundStartIndex: number; defaultExpanded?: boolean; onOpenFile?: (path: string) => void }) {
  const [expanded, setExpanded] = useState(defaultExpanded ?? false);
  // Sync with external defaultExpanded changes (e.g. process toggle)
  useEffect(() => { setExpanded(defaultExpanded ?? false); }, [defaultExpanded]);
  const totalTools = Object.values(toolCounts).reduce((a, b) => a + b, 0);
  const entries = Object.entries(toolCounts).sort((a, b) => b[1] - a[1]);

  // Build tool-grouped items for expanded view (reuse ToolGroup logic)
  const expandedItems: ({ type: "single"; message: Message; idx: number; dimmed?: boolean } | { type: "file_group"; kind: string; messages: Message[]; startIdx: number })[] = [];
  // Find last assistant in roundMessages — it's already shown as the main message outside the summary
  const lastAssistantIdx = findLastAssistant(roundMessages, 0, roundMessages.length);
  if (expanded) {
    // Group consecutive tool messages, interleave with assistant messages
    let i = 0;
    while (i < roundMessages.length) {
      const m = roundMessages[i];
      if (isToolMessage(m)) {
        const batch: Message[] = [];
        const batchStart = i;
        while (i < roundMessages.length && isToolMessage(roundMessages[i])) {
          batch.push(roundMessages[i]);
          i++;
        }
        // Sub-group consecutive same-kind file tools
        let j = 0;
        while (j < batch.length) {
          const kind = fileToolKind(batch[j]);
          if (kind) {
            const fileBatch: Message[] = [];
            const fileBatchStart = j;
            while (j < batch.length && fileToolKind(batch[j]) === kind) {
              fileBatch.push(batch[j]);
              j++;
            }
            if (fileBatch.length >= 2) {
              expandedItems.push({ type: "file_group", kind, messages: fileBatch, startIdx: roundStartIndex + batchStart + fileBatchStart });
            } else {
              expandedItems.push({ type: "single", message: fileBatch[0], idx: roundStartIndex + batchStart + fileBatchStart });
            }
          } else {
            expandedItems.push({ type: "single", message: batch[j], idx: roundStartIndex + batchStart + j });
            j++;
          }
        }
      } else if (m.role === "assistant") {
        // Skip last assistant — already shown as the main message below
        if (i !== lastAssistantIdx) {
          expandedItems.push({ type: "single", message: m, idx: roundStartIndex + i, dimmed: true });
        }
        i++;
      } else {
        i++;
      }
    }
  }

  return (
    <div>
      <div
        className="flex items-center gap-2 font-mono text-[0.775rem] sm:text-[0.725rem] cursor-pointer select-none py-0.5 group"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[0.65rem] bg-sol-base02 text-sol-base01">
          {totalTools} tool{totalTools > 1 ? "s" : ""}
        </span>
        <span className="flex items-center gap-1.5 flex-wrap">
          {entries.map(([label, count]) => {
            const meta = toolIconMap[label] || defaultToolIcon;
            return (
              <span key={label} className="inline-flex items-center gap-0.5">
                <span className={`inline-flex items-center justify-center w-4 h-4 rounded text-[0.55rem] font-bold ${meta.bg} ${meta.color}`}>
                  {meta.icon}
                </span>
                <span className="text-sol-base01 text-[0.6rem]">{count}</span>
              </span>
            );
          })}
        </span>
        <span className="text-sol-base01 text-[0.6rem] ml-auto group-hover:text-sol-base0">{expanded ? "\u25B2" : "\u25BC"}</span>
      </div>
      {expanded && (
        <div className="flex flex-col gap-1.5 mt-1 ml-6.5">
          {expandedItems.map((ei) => {
            if (ei.type === "file_group") {
              return <FileToolGroup key={`fg-${ei.startIdx}`} kind={ei.kind} messages={ei.messages} startIndex={ei.startIdx} onOpenFile={onOpenFile} />;
            }
            return (
              <div key={ei.idx}>
                <MessageBubble role={ei.message.role} content={ei.message.content} toolName={ei.message.toolName} arguments={ei.message.arguments} timestamp={ei.message.timestamp} dimmed={ei.dimmed} onOpenFile={onOpenFile} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


interface MessageListProps {
  messages: Message[];
  running?: boolean;
  centered?: boolean;
  showProgress: boolean;
  onOpenFile?: (path: string) => void;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
}

export default function MessageList({ messages, running, centered, showProgress, onOpenFile, scrollContainerRef }: MessageListProps) {
  const internalRef = useRef<HTMLDivElement>(null);
  const containerRef = scrollContainerRef || internalRef;

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages, containerRef]);

  const items = filterLevel0(messages);

  const innerClass = centered ? "max-w-3xl mx-auto w-full flex flex-col gap-3" : "flex flex-col gap-3";

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto px-6 py-4 text-xs">
      <div className={innerClass}>
      {items.map((item) => {
        if (item.type === "process_summary") {
          return <ProcessSummary key={`ps-${item.index}`} toolCounts={item.toolCounts} assistantCount={item.assistantCount} roundMessages={item.roundMessages} roundStartIndex={item.roundStartIndex} defaultExpanded={showProgress} onOpenFile={onOpenFile} />;
        }
        const isUser = item.message.role === "user";
        return (
          <div key={item.index} id={isUser ? `user-msg-${item.index}` : undefined}>
            <MessageBubble role={item.message.role} content={item.message.content} toolName={item.message.toolName} arguments={item.message.arguments} timestamp={item.message.timestamp} onOpenFile={onOpenFile} />
          </div>
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
