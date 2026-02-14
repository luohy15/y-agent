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
    return `read("${args.path || ""}")`;
  }
  if (toolName === "file_write") {
    return `write("${args.path || ""}")`;
  }
  if (toolName === "file_edit") {
    return `edit("${args.path || ""}")`;
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

export default function MessageBubble({ role, content, toolName, arguments: args, timestamp }: MessageBubbleProps) {
  if (role === "system") {
    return <div className="self-center text-sol-base01 text-[0.7rem] py-1">{content}</div>;
  }

  // Tool pending: show tool call with # prefix (blue) + pulsing dot
  if (role === "tool_pending" && toolName) {
    return (
      <div className="text-[0.8rem] font-mono text-sol-blue flex items-center gap-2">
        <span>{formatToolCall(toolName, args, false)}</span>
        <span className="animate-pulse">●</span>
      </div>
    );
  }

  // Tool denied: show tool call with # prefix (grey) + denied result
  if (role === "tool_denied" && toolName) {
    const result = content.replace(/\n/g, " ");
    return (
      <div>
        <div className="text-[0.8rem] font-mono text-sol-base01">
          {formatToolCall(toolName, args, false)}
        </div>
        <div className="text-[0.75rem] font-mono text-sol-base01">
          {truncate(result, 80)}
        </div>
      </div>
    );
  }

  // Tool result: tool name + args on first line, result on second line (like CLI)
  if (role === "tool_result" && toolName) {
    const result = content.replace(/\n/g, " ");
    return (
      <div>
        <div className="text-[0.8rem] font-mono text-sol-cyan">
          {formatToolCall(toolName, args)}
        </div>
        <div className="text-[0.75rem] font-mono text-sol-blue">
          {truncate(result, 80)}
        </div>
      </div>
    );
  }

  // User message: bordered panel like CLI
  if (role === "user") {
    return (
      <div>
        <TimestampLine timestamp={timestamp} />
        <div className="border border-sol-green rounded-lg px-4 py-3">
          <div className="text-[0.825rem] text-sol-base1 whitespace-pre-wrap break-words prose prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        </div>
      </div>
    );
  }

  // Assistant message: rendered markdown like CLI
  return (
    <div>
      <TimestampLine timestamp={timestamp} />
      <div className="text-[0.825rem] text-sol-base0 prose prose-invert prose-sm max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>
    </div>
  );
}

export type { BubbleRole };
