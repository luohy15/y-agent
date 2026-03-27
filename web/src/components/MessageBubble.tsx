import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PatchDiff } from "@pierre/diffs/react";
import { TRACE_BADGE, CHAT_BADGE, skillBadgeClass } from "./badges";

type BubbleRole = "user" | "assistant" | "tool_pending" | "tool_result" | "tool_denied" | "system";

interface MessageBubbleProps {
  role: BubbleRole;
  content: string;
  toolName?: string;
  arguments?: Record<string, unknown>;
  timestamp?: string;
  dimmed?: boolean;
  onOpenFile?: (path: string) => void;
  onSelectChat?: (chatId: string) => void;
  onSelectTrace?: (traceId: string) => void;
}

function truncate(s: string, n: number): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n) + "..." : s;
}

function looksLikeFilePath(s: string): boolean {
  if (s.includes(" ") || s.includes("\n")) return false;
  if (s.startsWith("http://") || s.startsWith("https://")) return false;
  return s.includes("/");
}

// --- Tool icon & color mapping ---
interface ToolMeta {
  icon: string;
  label: string;
  color: string;       // tailwind text color for icon+label
  iconBg: string;      // tailwind bg for icon circle
}

function getToolMeta(toolName: string): ToolMeta {
  const n = toolName.toLowerCase();
  if (n === "bash")
    return { icon: ">_", label: "Bash", color: "text-sol-blue", iconBg: "bg-sol-blue/15" };
  if (n === "read" || n === "file_read")
    return { icon: "\u2193", label: "Read", color: "text-sol-cyan", iconBg: "bg-sol-cyan/15" };
  if (n === "write" || n === "file_write")
    return { icon: "\u2191", label: "Write", color: "text-sol-green", iconBg: "bg-sol-green/15" };
  if (n === "edit" || n === "file_edit")
    return { icon: "\u0394", label: "Edit", color: "text-sol-yellow", iconBg: "bg-sol-yellow/15" };
  if (n === "grep")
    return { icon: "/", label: "Grep", color: "text-sol-violet", iconBg: "bg-sol-violet/15" };
  if (n === "glob")
    return { icon: "*", label: "Glob", color: "text-sol-violet", iconBg: "bg-sol-violet/15" };
  if (n === "agent")
    return { icon: "\u25C8", label: "Agent", color: "text-sol-magenta", iconBg: "bg-sol-magenta/15" };
  if (n === "websearch" || n === "webfetch")
    return { icon: "\u25CE", label: toolName, color: "text-sol-orange", iconBg: "bg-sol-orange/15" };
  if (n === "todowrite")
    return { icon: "\u2713", label: "Todo", color: "text-sol-green", iconBg: "bg-sol-green/15" };
  if (n === "askuserquestion")
    return { icon: "?", label: "Question", color: "text-sol-cyan", iconBg: "bg-sol-cyan/15" };
  return { icon: "\u25C6", label: toolName, color: "text-sol-base01", iconBg: "bg-sol-base01/15" };
}

// --- Extract display info from tool args ---
function getFilePath(toolName: string, args?: Record<string, unknown>): string | null {
  const n = toolName.toLowerCase();
  if (["file_read", "read", "file_write", "write", "file_edit", "edit"].includes(n)) {
    const p = String(args?.path || args?.file_path || "");
    return p || null;
  }
  return null;
}

function shortPath(fullPath: string): string {
  const parts = fullPath.split("/");
  if (parts.length <= 3) return fullPath;
  return parts.slice(-3).join("/");
}

function getBadgeText(toolName: string, args?: Record<string, unknown>): string | null {
  const n = toolName.toLowerCase();
  // File tools: show path
  const fp = getFilePath(toolName, args);
  if (fp) return shortPath(fp);
  // TodoWrite: show summary counts
  if (n === "todowrite" && Array.isArray(args?.todos)) {
    const todos = args.todos as { status?: string }[];
    const done = todos.filter((t) => t.status === "completed").length;
    const active = todos.filter((t) => t.status === "in_progress").length;
    const pending = todos.length - done - active;
    const parts: string[] = [];
    if (done) parts.push(`${done} done`);
    if (active) parts.push(`${active} active`);
    if (pending) parts.push(`${pending} pending`);
    return parts.join(", ") || `${todos.length} items`;
  }
  // AskUserQuestion: show first question header or text
  if (n === "askuserquestion" && Array.isArray(args?.questions)) {
    const q = args.questions as { header?: string; question?: string }[];
    if (q.length > 0) return truncate(String(q[0].header || q[0].question || ""), 40);
  }
  // Bash: show truncated command
  if (n === "bash") return truncate(String(args?.command || ""), 60);
  // Grep: show pattern
  if (n === "grep") return truncate(String(args?.pattern || ""), 40);
  // Glob: show pattern
  if (n === "glob") return truncate(String(args?.pattern || ""), 40);
  // Agent: show description
  if (n === "agent") return truncate(String(args?.description || args?.prompt || ""), 50);
  // Skill: show skill name
  if (n === "skill") return truncate(String(args?.skill || ""), 40);
  return null;
}

// --- Build unified diff from old/new strings ---
function buildUnifiedDiff(filePath: string, oldStr: string, newStr: string): string {
  const oldLines = oldStr ? oldStr.split("\n") : [];
  const newLines = newStr ? newStr.split("\n") : [];
  const header = `--- a/${filePath}\n+++ b/${filePath}\n@@ -1,${oldLines.length} +1,${newLines.length} @@`;
  const removed = oldLines.map((l) => `-${l}`);
  const added = newLines.map((l) => `+${l}`);
  return `${header}\n${removed.join("\n")}\n${added.join("\n")}`;
}

// --- Diff stats for Edit tool ---
function getDiffStats(toolName: string, args?: Record<string, unknown>): { added: number; removed: number } | null {
  const n = toolName.toLowerCase();
  if (n !== "edit" && n !== "file_edit") return null;
  const oldStr = String(args?.old_string || "");
  const newStr = String(args?.new_string || "");
  if (!oldStr && !newStr) return null;
  const oldLines = oldStr ? oldStr.split("\n").length : 0;
  const newLines = newStr ? newStr.split("\n").length : 0;
  return { added: newLines, removed: oldLines };
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

function parseTracePrefix(content: string): { traceId: string; fromSkill: string; fromChatId: string; cleanContent: string } | null {
  const match = content.match(/^\[trace:(\S+)\s+from:(\S+)\s+to:\S+\s+from_chat:(\S+)\s+to_chat:\S+\]\n?/);
  if (!match) return null;
  return { traceId: match[1], fromSkill: match[2], fromChatId: match[3], cleanContent: content.slice(match[0].length) };
}

function TimestampLine({ timestamp, traceId, fromSkill, fromChatId, onSelectChat, onSelectTrace }: { timestamp?: string; traceId?: string; fromSkill?: string; fromChatId?: string; onSelectChat?: (chatId: string) => void; onSelectTrace?: (traceId: string) => void }) {
  const formatted = formatDateTime(timestamp);
  if (!formatted && !fromSkill) return null;
  return (
    <div className="text-xs sm:text-[0.65rem] text-sol-base01 mb-1 flex items-center">
      {formatted && <span>{formatted}</span>}
      {traceId && <span className={`ml-1.5 text-[0.6rem] ${TRACE_BADGE} ${onSelectTrace ? "hover:bg-sol-base01/30 cursor-pointer" : ""}`} onClick={() => onSelectTrace?.(traceId)}>#{traceId}</span>}
      {fromSkill && <span className={`ml-1.5 text-[0.6rem] ${skillBadgeClass(fromSkill)}`}>{fromSkill}</span>}
      {fromChatId && <span className={`ml-1 text-[0.6rem] ${CHAT_BADGE} hover:bg-sol-blue/30 cursor-pointer`} onClick={() => onSelectChat?.(fromChatId)}>{fromChatId}</span>}
    </div>
  );
}

// --- Compact tool call display (Claude Code desktop style) ---
function ToolCallCompact({
  toolName,
  args,
  content,
  status,
  onOpenFile,
}: {
  toolName: string;
  args?: Record<string, unknown>;
  content: string;
  status: "pending" | "done" | "denied";
  onOpenFile?: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const meta = getToolMeta(toolName);
  const badge = getBadgeText(toolName, args);
  const diff = getDiffStats(toolName, args);
  const filePath = getFilePath(toolName, args);
  const n = toolName.toLowerCase();
  // For Bash, prepend full command to expandable content
  // For TodoWrite, render structured todo list
  const isTodo = n === "todowrite";
  const todoItems = isTodo && Array.isArray(args?.todos) ? (args.todos as { content?: string; status?: string; activeForm?: string }[]) : null;

  const isQuestion = n === "askuserquestion";
  const questions = isQuestion && Array.isArray(args?.questions) ? (args.questions as { question?: string; header?: string; options?: { label?: string; description?: string }[]; multiSelect?: boolean }[]) : null;

  const isBash = n === "bash";
  const bashCommand = isBash ? String(args?.command || "") : "";
  const expandContent = isBash && bashCommand ? (bashCommand + (content ? "\n" + content : "")) : content;
  // For Edit, we show a diff view from old_string/new_string
  const isEdit = n === "edit" || n === "file_edit";
  const editOld = isEdit ? String(args?.old_string || "") : "";
  const editNew = isEdit ? String(args?.new_string || "") : "";
  const hasDiff = isEdit && (editOld || editNew);
  const isSkill = n === "skill";
  const hasContent = !isSkill && (expandContent.length > 0 || hasDiff || (todoItems && todoItems.length > 0) || (questions && questions.length > 0));

  const isDenied = status === "denied";
  const isPending = status === "pending";
  const headerColor = isDenied ? "text-sol-base01" : meta.color;
  const iconBg = isDenied ? "bg-sol-base01/15" : meta.iconBg;

  return (
    <div>
      {/* Compact one-line header */}
      <div
        className={`flex items-center gap-1.5 font-mono text-[0.775rem] sm:text-[0.725rem] ${hasContent ? "cursor-pointer" : ""} select-none`}
        onClick={() => hasContent && setExpanded((v) => !v)}
      >
        {/* Icon */}
        <span className={`inline-flex items-center justify-center w-5 h-5 rounded text-[0.65rem] font-bold shrink-0 ${iconBg} ${headerColor}`}>
          {meta.icon}
        </span>

        {/* Tool name */}
        <span className={`${headerColor} font-semibold shrink-0`}>{meta.label}</span>

        {/* Badge (file path / command / pattern) */}
        {badge && (
          <span
            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[0.65rem] bg-sol-base02 truncate max-w-[60%] ${
              filePath && onOpenFile ? "cursor-pointer hover:bg-sol-base01/30" : ""
            } ${isDenied ? "text-sol-base01" : "text-sol-base0"}`}
            onClick={filePath && onOpenFile ? (e) => { e.stopPropagation(); onOpenFile(filePath); } : undefined}
            title={filePath || badge}
          >
            {badge}
          </span>
        )}

        {/* Diff stats */}
        {diff && (
          <span className="flex items-center gap-1 text-[0.65rem] shrink-0 ml-0.5">
            <span className="text-sol-green">+{diff.added}</span>
            <span className="text-sol-red">-{diff.removed}</span>
          </span>
        )}

        {/* Pending indicator */}
        {isPending && <span className="animate-pulse text-sol-blue text-[0.6rem] ml-auto shrink-0">●</span>}

        {/* Denied indicator */}
        {isDenied && <span className="text-sol-red text-[0.6rem] shrink-0">denied</span>}

        {/* Expand chevron */}
        {hasContent && !isPending && (
          <span className="text-sol-base01 text-[0.6rem] ml-auto shrink-0">{expanded ? "\u25B2" : "\u25BC"}</span>
        )}
      </div>

      {/* Expandable detail content */}
      {expanded && hasContent && (
        questions && questions.length > 0 ? (
          <div className="mt-1 ml-6.5 max-h-60 overflow-y-auto rounded bg-sol-base02 px-2 py-1.5 text-[0.7rem] font-mono flex flex-col gap-2">
            {questions.map((q, qi) => (
              <div key={qi}>
                {q.header && <div className="text-sol-cyan font-semibold text-[0.65rem] uppercase tracking-wide mb-0.5">{q.header}</div>}
                {q.question && <div className="text-sol-base0 mb-1">{q.question}</div>}
                {Array.isArray(q.options) && (
                  <div className="flex flex-col gap-0.5">
                    {q.options.map((opt, oi) => (
                      <div key={oi} className="flex items-start gap-1.5">
                        <span className="text-sol-base01 shrink-0">○</span>
                        <span className="text-sol-base0">{opt.label}{opt.description ? <span className="text-sol-base01"> — {opt.description}</span> : null}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : todoItems && todoItems.length > 0 ? (
          <div className="mt-1 ml-6.5 max-h-60 overflow-y-auto rounded bg-sol-base02 px-2 py-1.5 text-[0.7rem] font-mono flex flex-col gap-0.5">
            {todoItems.map((t, i) => {
              const st = t.status || "pending";
              const icon = st === "completed" ? "\u2713" : st === "in_progress" ? "\u25B6" : "\u25CB";
              const color = st === "completed" ? "text-sol-green" : st === "in_progress" ? "text-sol-blue" : "text-sol-base01";
              return (
                <div key={i} className="flex items-start gap-1.5">
                  <span className={`${color} shrink-0 w-3.5 text-center`}>{icon}</span>
                  <span className={st === "completed" ? "text-sol-base01 line-through" : "text-sol-base0"}>{t.content || t.activeForm || ""}</span>
                </div>
              );
            })}
          </div>
        ) : hasDiff ? (
          <div className="mt-1 ml-6.5 max-h-60 overflow-auto rounded bg-sol-base02 text-[0.7rem]">
            <PatchDiff patch={buildUnifiedDiff(shortPath(filePath || "file"), editOld, editNew)} options={{ theme: "solarized-dark" }} />
          </div>
        ) : (
          <pre className={`mt-1 ml-6.5 text-[0.7rem] font-mono whitespace-pre-wrap break-all max-h-60 overflow-y-auto rounded px-2 py-1 bg-sol-base02 ${isDenied ? "text-sol-base01" : "text-sol-base0"}`}>
            {expandContent}
          </pre>
        )
      )}


    </div>
  );
}

const USER_MSG_MAX_LINES = 3;

function UserMessage({ content, timestamp, onSelectChat, onSelectTrace }: { content: string; timestamp?: string; onSelectChat?: (chatId: string) => void; onSelectTrace?: (traceId: string) => void }) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [clamped, setClamped] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const traceInfo = parseTracePrefix(content);
  const displayContent = traceInfo ? traceInfo.cleanContent : content;

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    // Compare scrollHeight vs line-height * max lines
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 16;
    setClamped(el.scrollHeight > lineHeight * USER_MSG_MAX_LINES + 1);
  }, [displayContent]);

  return (
    <div>
      <TimestampLine timestamp={timestamp} traceId={traceInfo?.traceId} fromSkill={traceInfo?.fromSkill} fromChatId={traceInfo?.fromChatId} onSelectChat={onSelectChat} onSelectTrace={onSelectTrace} />
      <div className="bg-sol-base02 rounded px-2 py-1.5 -mx-2">
        <div className="flex items-baseline">
          <span className="text-sol-base01 font-mono text-sm sm:text-[0.775rem] mr-2 select-none shrink-0">&gt;</span>
          <div className="min-w-0 flex-1">
            <div
              ref={contentRef}
              className={`text-sm sm:text-[0.775rem] text-sol-base1 whitespace-pre-wrap break-words min-w-0${!expanded && clamped ? " line-clamp-3" : ""}`}
            >
              {displayContent}
            </div>
            {clamped && (
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-sol-blue text-xs mt-0.5 hover:underline cursor-pointer"
              >
                {expanded ? "Show less" : "Show more"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MessageBubble({ role, content, toolName, arguments: args, timestamp, dimmed, onOpenFile, onSelectChat, onSelectTrace }: MessageBubbleProps) {
  if (role === "system") {
    return <div className="self-center text-sol-base01 text-xs sm:text-[0.7rem] py-1">{content}</div>;
  }

  // Tool calls: compact one-line display
  if (role === "tool_pending" && toolName) {
    return <ToolCallCompact toolName={toolName} args={args} content="" status="pending" onOpenFile={onOpenFile} />;
  }
  if (role === "tool_denied" && toolName) {
    return <ToolCallCompact toolName={toolName} args={args} content={content} status="denied" onOpenFile={onOpenFile} />;
  }
  if (role === "tool_result" && toolName) {
    return <ToolCallCompact toolName={toolName} args={args} content={content} status="done" onOpenFile={onOpenFile} />;
  }

  // User message: terminal input style with > prompt and grey background
  if (role === "user") {
    return <UserMessage content={content} timestamp={timestamp} onSelectChat={onSelectChat} onSelectTrace={onSelectTrace} />;
  }

  // Assistant message: rendered markdown like CLI
  return (
    <div>
      {!dimmed && <TimestampLine timestamp={timestamp} />}
      <div className={`text-sm sm:text-[0.775rem] prose prose-sm max-w-none ${dimmed ? "text-sol-base01" : "text-sol-base0"}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({ children, className, ...props }) {
              const text = String(children).replace(/\n$/, "");
              const isInline = !className;
              if (isInline && onOpenFile && looksLikeFilePath(text)) {
                return (
                  <code
                    {...props}
                    className="cursor-pointer text-sol-cyan hover:underline"
                    onClick={() => onOpenFile(text)}
                  >
                    {children}
                  </code>
                );
              }
              return <code className={className} {...props}>{children}</code>;
            },
          }}
        >{content}</ReactMarkdown>
      </div>
    </div>
  );
}

export type { BubbleRole };
