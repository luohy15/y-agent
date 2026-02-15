import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type BubbleRole = "user" | "assistant" | "tool_pending" | "tool_result" | "tool_denied" | "system";

interface MessageBubbleProps {
  role: BubbleRole;
  content: string;
  toolName?: string;
  arguments?: Record<string, unknown>;
  timestamp?: string;
}

function truncate(s: string, n: number): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n) + "..." : s;
}

function formatToolCall(toolName: string, args?: Record<string, unknown>, approved = true): string {
  if (!args) return toolName;
  if (toolName === "bash") {
    const prefix = approved ? "$" : "#";
    return `${prefix} ${truncate(args.command as string || "", 200)}`;
  }
  if (toolName === "file_read") {
    const prefix = approved ? "$" : "#";
    return `${prefix} cat ${args.path || ""}`;
  }
  if (toolName === "file_write") {
    const prefix = approved ? "$" : "#";
    return `${prefix} tee ${args.path || ""}`;
  }
  if (toolName === "file_edit") {
    const prefix = approved ? "$" : "#";
    return `${prefix} edit ${args.path || ""}`;
  }
  try {
    const argsStr = JSON.stringify(args, null, 0);
    return `${toolName}(${truncate(argsStr, 200)})`;
  } catch {
    return toolName;
  }
}

function formatDateTime(ts?: string): string {
  if (!ts) return "";
  try {
    const dt = new Date(ts);
    const date = dt.toLocaleDateString([], { year: "numeric", month: "2-digit", day: "2-digit" });
    const time = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    return `${date} ${time}`;
  } catch {
    return "";
  }
}

function TimestampLine({ timestamp }: { timestamp?: string }) {
  const formatted = formatDateTime(timestamp);
  if (!formatted) return null;
  return <div className="text-[0.65rem] text-sol-base01 mb-1">{formatted}</div>;
}

function ExpandableResult({ content, color }: { content: string; color: string }) {
  const [expanded, setExpanded] = useState(false);
  const oneLine = content.replace(/\n/g, " ").slice(0, 80);
  const isLong = content.length > 80;

  return (
    <div
      className={`text-[0.75rem] font-mono break-all ${color} ${isLong ? "cursor-pointer" : ""}`}
      onClick={() => isLong && setExpanded((v) => !v)}
    >
      <span>{oneLine}{isLong && "..."}{isLong && <span className="text-sol-base01 text-[0.65rem] ml-1">{expanded ? "▲" : "▼"}</span>}</span>
      {expanded && <pre className="whitespace-pre-wrap break-all">{content}</pre>}
    </div>
  );
}

export default function MessageBubble({ role, content, toolName, arguments: args, timestamp }: MessageBubbleProps) {
  if (role === "system") {
    return <div className="self-center text-sol-base01 text-[0.7rem] py-1">{content}</div>;
  }

  // Tool pending: show tool call with # prefix (blue) + pulsing dot
  if (role === "tool_pending" && toolName) {
    return (
      <div className="text-[0.775rem] font-mono text-sol-blue flex items-center gap-2 break-all">
        <span className="min-w-0">{formatToolCall(toolName, args, false)}</span>
        <span className="animate-pulse">●</span>
      </div>
    );
  }

  // Tool denied: show tool call with # prefix (grey) + expandable denied result
  if (role === "tool_denied" && toolName) {
    return (
      <div>
        <div className="text-[0.775rem] font-mono text-sol-base01 break-all">
          {formatToolCall(toolName, args, false)}
        </div>
        <ExpandableResult content={content} color="text-sol-base01" />
      </div>
    );
  }

  // Tool result: tool name + args on first line, expandable result on second line
  if (role === "tool_result" && toolName) {
    return (
      <div>
        <div className="text-[0.775rem] font-mono text-sol-cyan break-all">
          {formatToolCall(toolName, args)}
        </div>
        <ExpandableResult content={content} color="text-sol-blue" />
      </div>
    );
  }

  // User message: terminal input style with > prompt and grey background
  if (role === "user") {
    return (
      <div>
        <TimestampLine timestamp={timestamp} />
        <div className="bg-sol-base02 rounded px-2 py-1.5 -mx-2">
          <div className="flex items-baseline">
            <span className="text-sol-base01 font-mono text-[0.775rem] mr-2 select-none shrink-0">&gt;</span>
            <div className="text-[0.775rem] text-sol-base1 whitespace-pre-wrap break-words min-w-0">
              {content}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Assistant message: rendered markdown like CLI
  return (
    <div>
      <TimestampLine timestamp={timestamp} />
      <div className="text-[0.775rem] text-sol-base0 prose prose-sm max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    </div>
  );
}

export type { BubbleRole };
