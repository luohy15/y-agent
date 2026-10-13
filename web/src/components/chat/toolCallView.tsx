import { useState } from "react";
import { PatchDiff } from "@pierre/diffs/react";

export interface PresentedContentState {
  status: "loading" | "loaded" | "error";
  content?: string;
  error?: string;
}

export type LoadPresentedContent = (toolCallId: string) => void;
export type GetPresentedContent = (toolCallId: string) => PresentedContentState | undefined;

interface ToolMeta {
  icon: string;
  label: string;
  color: string;
  iconBg: string;
}

function truncate(value: string, limit: number): string {
  if (!value) return "";
  return value.length > limit ? value.slice(0, limit) + "..." : value;
}

function getToolMeta(toolName: string): ToolMeta {
  const name = toolName.toLowerCase();
  if (name === "bash") return { icon: ">_", label: "Bash", color: "text-sol-blue", iconBg: "bg-sol-blue/15" };
  if (name === "read" || name === "file_read") return { icon: "↓", label: "Read", color: "text-sol-cyan", iconBg: "bg-sol-cyan/15" };
  if (name === "write" || name === "file_write") return { icon: "↑", label: "Write", color: "text-sol-green", iconBg: "bg-sol-green/15" };
  if (name === "edit" || name === "file_edit") return { icon: "Δ", label: "Edit", color: "text-sol-yellow", iconBg: "bg-sol-yellow/15" };
  if (name === "grep") return { icon: "/", label: "Grep", color: "text-sol-violet", iconBg: "bg-sol-violet/15" };
  if (name === "glob") return { icon: "*", label: "Glob", color: "text-sol-violet", iconBg: "bg-sol-violet/15" };
  if (name === "todowrite") return { icon: "✓", label: "Todo", color: "text-sol-green", iconBg: "bg-sol-green/15" };
  return { icon: "◆", label: toolName || "tool", color: "text-sol-base01", iconBg: "bg-sol-base01/15" };
}

function getFilePath(toolName: string, args?: Record<string, unknown>): string | null {
  const name = toolName.toLowerCase();
  if (["file_read", "read", "file_write", "write", "file_edit", "edit"].includes(name)) {
    const path = String(args?.path || args?.file_path || "");
    return path || null;
  }
  return null;
}

function shortPath(fullPath: string): string {
  const parts = fullPath.split("/");
  if (parts.length <= 3) return fullPath;
  return parts.slice(-3).join("/");
}

const SPECIALIZED_TOOLS = new Set([
  "bash", "read", "file_read", "write", "file_write", "edit", "file_edit",
  "grep", "glob", "todowrite", "skill",
]);

function isGenericTool(toolName: string): boolean {
  return !SPECIALIZED_TOOLS.has(toolName.toLowerCase());
}

function hasArgs(args?: Record<string, unknown>): args is Record<string, unknown> {
  return Boolean(args) && typeof args === "object" && Object.keys(args).length > 0;
}

function getArgsBadge(args?: Record<string, unknown>): string | null {
  if (!hasArgs(args)) return null;
  const text = Object.entries(args)
    .map(([key, value]) => `${key}=${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(", ");
  return truncate(text, 60);
}

function getBadgeText(toolName: string, args?: Record<string, unknown>): string | null {
  const name = toolName.toLowerCase();
  const path = getFilePath(toolName, args);
  if (path) return shortPath(path);
  if (name === "todowrite" && Array.isArray(args?.todos)) {
    const todos = args.todos as { status?: string }[];
    const done = todos.filter((item) => item.status === "completed").length;
    const active = todos.filter((item) => item.status === "in_progress").length;
    const pending = todos.length - done - active;
    const parts: string[] = [];
    if (done) parts.push(`${done} done`);
    if (active) parts.push(`${active} active`);
    if (pending) parts.push(`${pending} pending`);
    return parts.join(", ") || `${todos.length} items`;
  }
  if (name === "bash") return truncate(String(args?.command || ""), 60);
  if (name === "grep") return truncate(String(args?.pattern || ""), 40);
  if (name === "glob") return truncate(String(args?.pattern || ""), 40);
  if (name === "skill") return truncate(String(args?.skill || ""), 40);
  if (isGenericTool(toolName)) return getArgsBadge(args);
  return null;
}

function buildUnifiedDiff(filePath: string, oldStr: string, newStr: string): string {
  const oldLines = oldStr ? oldStr.split("\n") : [];
  const newLines = newStr ? newStr.split("\n") : [];
  const header = `--- a/${filePath}\n+++ b/${filePath}\n@@ -1,${oldLines.length} +1,${newLines.length} @@`;
  return `${header}\n${oldLines.map((line) => `-${line}`).join("\n")}\n${newLines.map((line) => `+${line}`).join("\n")}`;
}

function getDiffStats(toolName: string, args?: Record<string, unknown>): { added: number; removed: number } | null {
  const name = toolName.toLowerCase();
  if (name !== "edit" && name !== "file_edit") return null;
  const oldStr = String(args?.old_string || "");
  const newStr = String(args?.new_string || "");
  if (!oldStr && !newStr) return null;
  return { added: newStr ? newStr.split("\n").length : 0, removed: oldStr ? oldStr.split("\n").length : 0 };
}

export function ToolCallView({
  toolName,
  args,
  content,
  status,
  toolCallId,
  contentTruncated,
  contentLength,
  onLoadFullContent,
  getFullContent,
  onOpenFile,
}: {
  toolName: string;
  args?: Record<string, unknown>;
  content: string;
  status: "pending" | "done" | "denied";
  toolCallId?: string;
  contentTruncated?: boolean;
  contentLength?: number;
  onLoadFullContent?: LoadPresentedContent;
  getFullContent?: GetPresentedContent;
  onOpenFile?: (path: string, line?: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const remote = toolCallId ? getFullContent?.(toolCallId) : undefined;
  const loaded = remote?.status === "loaded" ? remote : undefined;
  const loadingFull = remote?.status === "loading";
  const loadError = remote?.status === "error" ? remote.error ?? "Failed to load" : null;
  const effectiveContent = loaded?.content ?? content;
  const effectiveTruncated = !loaded && Boolean(contentTruncated);
  const meta = getToolMeta(toolName);
  const badge = getBadgeText(toolName, args);
  const diff = getDiffStats(toolName, args);
  const filePath = getFilePath(toolName, args);
  const name = toolName.toLowerCase();
  const isTodo = name === "todowrite";
  const todoItems = isTodo && Array.isArray(args?.todos) ? (args.todos as { content?: string; status?: string; activeForm?: string }[]) : null;
  const isBash = name === "bash";
  const bashCommand = isBash ? String(args?.command || "") : "";
  const expandContent = isBash && bashCommand ? (bashCommand + (effectiveContent ? "\n" + effectiveContent : "")) : effectiveContent;
  const isEdit = name === "edit" || name === "file_edit";
  const editOld = isEdit ? String(args?.old_string || "") : "";
  const editNew = isEdit ? String(args?.new_string || "") : "";
  const showTodo = Boolean(todoItems && todoItems.length > 0);
  const showDiff = !showTodo && Boolean(isEdit && (editOld || editNew));
  const isSkill = name === "skill";
  const rawAvailable = expandContent.length > 0 || Boolean(contentTruncated) || Boolean(loaded);
  const isGeneric = isGenericTool(toolName);
  const hasContent = ((showTodo || showDiff || rawAvailable || (isGeneric && hasArgs(args)))) && (!isSkill || Boolean(contentTruncated) || Boolean(loaded));
  const showRawDisclosure = Boolean(toolCallId) && Boolean(onLoadFullContent) && (effectiveTruncated || ((showTodo || showDiff) && Boolean(loaded)));
  const isDenied = status === "denied";
  const isPending = status === "pending";
  const headerColor = isDenied ? "text-sol-base01" : meta.color;
  const iconBg = isDenied ? "bg-sol-base01/15" : meta.iconBg;

  return (
    <div data-testid={`tool-${status}`}>
      <div
        className={`flex items-center gap-1.5 font-mono text-[0.775rem] sm:text-[0.725rem] ${hasContent ? "cursor-pointer" : ""} select-none`}
        onClick={() => hasContent && setExpanded((value) => !value)}
      >
        <span className={`inline-flex items-center justify-center w-5 h-5 rounded text-[0.65rem] font-bold shrink-0 ${iconBg} ${headerColor}`}>{meta.icon}</span>
        <span className={`${headerColor} font-semibold shrink-0`}>{meta.label}</span>
        {badge && (
          <span
            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[0.65rem] bg-sol-base02 truncate max-w-[60%] ${filePath && onOpenFile ? "cursor-pointer hover:bg-sol-base01/30" : ""} ${isDenied ? "text-sol-base01" : "text-sol-base0"}`}
            onClick={filePath && onOpenFile ? (event) => { event.stopPropagation(); onOpenFile(filePath); } : undefined}
            title={filePath || badge}
          >
            {badge}
          </span>
        )}
        {diff && (
          <span className="flex items-center gap-1 text-[0.65rem] shrink-0 ml-0.5">
            <span className="text-sol-green">+{diff.added}</span>
            <span className="text-sol-red">-{diff.removed}</span>
          </span>
        )}
        {isPending && <span className="animate-pulse text-sol-blue text-[0.6rem] ml-auto shrink-0">●</span>}
        {isDenied && <span className="text-sol-red text-[0.6rem] shrink-0">denied</span>}
        {hasContent && !isPending && <span className="text-sol-base01 text-[0.6rem] ml-auto shrink-0">{expanded ? "▲" : "▼"}</span>}
      </div>
      {expanded && hasContent && (
        <>
          {isGeneric && (
            <>
              <div className="mt-1 ml-6.5 text-[0.6rem] font-mono uppercase text-sol-base01">Input</div>
              <pre className="mt-0.5 ml-6.5 text-[0.7rem] font-mono whitespace-pre-wrap break-all max-h-60 overflow-y-auto rounded px-2 py-1 bg-sol-base02 text-sol-base0">{hasArgs(args) ? JSON.stringify(args, null, 2) : "(no arguments)"}</pre>
              {rawAvailable && <div className="mt-1 ml-6.5 text-[0.6rem] font-mono uppercase text-sol-base01">Output</div>}
            </>
          )}
          {showTodo && (
            <div className="mt-1 ml-6.5 max-h-60 overflow-y-auto rounded bg-sol-base02 px-2 py-1.5 text-[0.7rem] font-mono flex flex-col gap-0.5">
              {todoItems!.map((item, index) => {
                const itemStatus = item.status || "pending";
                const icon = itemStatus === "completed" ? "✓" : itemStatus === "in_progress" ? "▶" : "○";
                const color = itemStatus === "completed" ? "text-sol-green" : itemStatus === "in_progress" ? "text-sol-blue" : "text-sol-base01";
                return (
                  <div key={index} className="flex items-start gap-1.5">
                    <span className={`${color} shrink-0 w-3.5 text-center`}>{icon}</span>
                    <span className={itemStatus === "completed" ? "text-sol-base01 line-through" : "text-sol-base0"}>{item.content || item.activeForm || ""}</span>
                  </div>
                );
              })}
            </div>
          )}
          {showDiff && (
            <div className="mt-1 ml-6.5 max-h-60 overflow-auto rounded bg-sol-base02 text-[0.7rem]">
              <PatchDiff patch={buildUnifiedDiff(shortPath(filePath || "file"), editOld, editNew)} options={{ theme: "solarized-dark" }} />
            </div>
          )}
          {!showTodo && !showDiff && !(isGeneric && !rawAvailable) && (
            <pre className={`mt-1 ml-6.5 text-[0.7rem] font-mono whitespace-pre-wrap break-all max-h-60 overflow-y-auto rounded px-2 py-1 bg-sol-base02 ${isDenied ? "text-sol-base01" : "text-sol-base0"}`}>{expandContent}</pre>
          )}
          {showRawDisclosure && (
            <div className="mt-1 ml-6.5 flex flex-col gap-1 text-[0.65rem]">
              {(showTodo || showDiff) && loaded && (
                <pre className="max-h-60 overflow-y-auto rounded px-2 py-1 bg-sol-base02 text-sol-base0 whitespace-pre-wrap break-all font-mono">{loaded.content}</pre>
              )}
              {effectiveTruncated && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      if (!toolCallId || !onLoadFullContent || loadingFull) return;
                      onLoadFullContent(toolCallId);
                    }}
                    disabled={loadingFull}
                    className="self-start font-mono px-1.5 py-0.5 rounded bg-sol-base02 text-sol-blue cursor-pointer hover:bg-sol-base01/30 disabled:opacity-50 disabled:cursor-default"
                  >
                    {loadingFull ? "Loading…" : `Load full output (${contentLength ?? effectiveContent.length} characters)`}
                  </button>
                  {loadError && <span className="text-sol-red">{loadError}</span>}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
