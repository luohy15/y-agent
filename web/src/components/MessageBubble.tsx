import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type BubbleRole = "user" | "assistant" | "tool_call" | "tool_result" | "system";

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

function formatToolCall(toolName: string, args?: Record<string, unknown>): string {
  if (!args) return toolName;
  if (toolName === "bash") {
    return `$ ${truncate(args.command as string || "", 200)}`;
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

  // Tool call: compact one-liner like CLI
  if (role === "tool_call" && toolName) {
    return (
      <div className="text-[0.8rem] font-mono text-sol-cyan">
        {formatToolCall(toolName, args)}
      </div>
    );
  }

  // Tool result: single-line truncated output like CLI
  if (role === "tool_result") {
    const result = content.replace(/\n/g, " ");
    return (
      <div className="text-[0.75rem] font-mono text-sol-blue">
        {truncate(result, 80)}
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
