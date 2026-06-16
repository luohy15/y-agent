import { Children, isValidElement, useState, useRef, useEffect, type ReactNode } from "react";
import { API, authFetch, getToken } from "../api";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkStripComments from "../utils/remarkStripComments";
import { PatchDiff } from "@pierre/diffs/react";
import { TRACE_BADGE, CHAT_BADGE, topicBadgeClass } from "./badges";
import { parseLocalFileReference } from "../utils/localFileLinks";
import { citationDomain, citationHostname } from "./citationDomain";
import { normalizeLinks, type NormalizedCitationLink } from "./citationLinks";
import type { CitationLink } from "./MessageList";
import ArtifactView, { type ArtifactMode, type ArtifactType } from "./ArtifactView";

type BubbleRole = "user" | "assistant" | "tool_pending" | "tool_result" | "tool_denied" | "system";

interface HastNode {
  type?: string;
  tagName?: string;
  value?: string;
  properties?: { className?: string | string[]; [key: string]: unknown };
  children?: HastNode[];
}

interface MessageBubbleProps {
  role: BubbleRole;
  content: string;
  toolName?: string;
  arguments?: Record<string, unknown>;
  timestamp?: string;
  images?: string[];
  links?: CitationLink[];
  dimmed?: boolean;
  onOpenFile?: (path: string, line?: number) => void;
  onShowSources?: (links: CitationLink[]) => void;
  onSelectChat?: (chatId: string) => void;
  onSelectTrace?: (traceId: string) => void;
  onOpenArtifact?: (type: ArtifactType, spec: string) => void;
}

function parseCitationHref(href?: string): number[] | null {
  if (!href?.startsWith("cite://")) return null;
  const indices = href
    .slice("cite://".length)
    .split(",")
    .map((part) => Number.parseInt(part, 10))
    .filter((n) => Number.isFinite(n) && n > 0);
  return indices.length > 0 ? indices : null;
}

const CITATION_RUN_RE = /(\[\d+\])+/g;
const CITATION_INDEX_RE = /\[(\d+)\]/g;

function preprocessCitationLinks(content: string, links?: CitationLink[]): string {
  if (!links?.length) return content;
  return content.replace(CITATION_RUN_RE, (match) => {
    const indices = Array.from(match.matchAll(CITATION_INDEX_RE), (m) => m[1]);
    return indices.length ? `[cite](cite://${indices.join(",")})` : match;
  });
}

function citationFallback(children: ReactNode): string {
  return typeof children === "string" ? children : "";
}

function CitationChip({ citationIndices, citationLinks, fallback }: { citationIndices: number[]; citationLinks: NormalizedCitationLink[]; fallback: ReactNode }) {
  const [open, setOpen] = useState(false);
  const closeTimerRef = useRef<number | null>(null);
  const citedLinks = citationIndices.map((n) => citationLinks[n - 1]).filter((link): link is NormalizedCitationLink => Boolean(link?.url));
  const firstLink = citedLinks[0];

  useEffect(() => () => {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
  }, []);

  if (!firstLink || citedLinks.length !== citationIndices.length) return <>{fallback}</>;

  const show = () => {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    setOpen(true);
  };
  const hide = () => {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    closeTimerRef.current = window.setTimeout(() => setOpen(false), 120);
  };
  const label = citationIndices.length === 1
    ? citationDomain(firstLink.url)
    : `${citationDomain(firstLink.url)} +${citationIndices.length - 1}`;

  return (
    <span className="relative inline-flex align-baseline" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      <button
        type="button"
        onClick={() => window.open(firstLink.url, "_blank", "noopener,noreferrer")}
        className="mx-0.5 inline-flex cursor-pointer items-center rounded-full border border-sol-base01/40 bg-sol-base02 px-1.5 py-0.5 align-baseline font-mono text-[0.65rem] font-semibold leading-none text-sol-cyan hover:border-sol-cyan hover:bg-sol-base01/20"
      >
        {label}
      </button>
      {open && (
        <span
          className="absolute left-0 top-full z-30 mt-1 block max-w-xs rounded border border-sol-base01/30 bg-sol-base02 p-2 text-[0.65rem] leading-snug text-sol-base0 shadow-xl"
          onMouseEnter={show}
          onMouseLeave={hide}
        >
          {citedLinks.map((link, index) => {
            const citationNumber = citationIndices[index];
            const hostname = citationHostname(link.url);
            return (
              <a
                key={`${link.url}-${citationNumber}`}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block min-w-0 truncate rounded px-1 py-0.5 text-sol-blue hover:bg-sol-base01/20 hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                <span className="font-mono text-sol-base01">[{citationNumber}]</span> {link.title || hostname}
              </a>
            );
          })}
        </span>
      )}
    </span>
  );
}

function classNameString(className?: string | string[]): string {
  return Array.isArray(className) ? className.join(" ") : className ?? "";
}

function artifactTypeFromClassName(className?: string): ArtifactType | null {
  if (!className) return null;
  if (/\blanguage-mermaid\b/.test(className)) return "mermaid";
  if (/\blanguage-vega-lite\b/.test(className)) return "vega-lite";
  if (/\blanguage-artifact-svg\b/.test(className)) return "artifact-svg";
  return null;
}

function artifactTypeFromHastNode(node?: HastNode): ArtifactType | null {
  return artifactTypeFromClassName(classNameString(node?.properties?.className));
}

function artifactKey(type: ArtifactType, spec: string): string {
  const input = spec.slice(0, 200);
  let hash = 0;
  for (let i = 0; i < input.length; i += 1) {
    hash = ((hash << 5) - hash + input.charCodeAt(i)) | 0;
  }
  return `${type}:${Math.abs(hash).toString(36)}`;
}

function nodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  return "";
}

function hastText(node: HastNode): string {
  if (typeof node.value === "string") return node.value;
  return node.children?.map(hastText).join("") ?? "";
}

function artifactFromPreNode(node?: HastNode): { type: ArtifactType; spec: string } | null {
  const codeNode = node?.children?.find((child) => child.type === "element" && child.tagName === "code");
  const type = artifactTypeFromHastNode(codeNode);
  if (!type || !codeNode) return null;
  return { type, spec: hastText(codeNode).replace(/\n$/, "") };
}

function artifactFromPreChildren(children: ReactNode): { type: ArtifactType; spec: string } | null {
  const child = Children.toArray(children).find((item) => isValidElement(item) && item.type === "code");
  if (!isValidElement<{ className?: string; children?: ReactNode }>(child)) return null;
  const type = artifactTypeFromClassName(child.props.className);
  if (!type) return null;
  return { type, spec: nodeText(child.props.children).replace(/\n$/, "") };
}

function pickImageSrc(imagePath: string): string | null {
  if (imagePath.startsWith("http://") || imagePath.startsWith("https://")) return imagePath;
  if (!imagePath.startsWith("s3://")) return null;

  const match = imagePath.match(/^s3:\/\/([^/]+)\/(.+)$/);
  if (!match) return null;
  const [, bucket, key] = match;
  if (bucket !== "luohy15") return null;
  return `https://cdn.luohy15.com/${key}`;
}

function isS3ImagePath(imagePath: string): boolean {
  return imagePath.startsWith("s3://");
}

function MessageImages({ images }: { images?: string[] }) {
  const [urls, setUrls] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!images?.length) {
      setUrls({});
      return;
    }
    let cancelled = false;
    const createdBlobUrls: string[] = [];
    const directEntries: [string, string][] = [];
    const localImages: string[] = [];

    // Local (EC2) images need an authed /api/file/raw fetch. Anonymous viewers (public
    // trace projection) have no token, so we skip the fetch entirely (graceful-degrade)
    // to keep the public page off all /api/file/* endpoints. Direct http(s)/CDN srcs
    // still render.
    const loggedIn = !!getToken();
    images.forEach((imagePath) => {
      const src = pickImageSrc(imagePath);
      if (src) {
        directEntries.push([imagePath, src]);
      } else if (isS3ImagePath(imagePath)) {
        console.warn(`Skipping unsupported image source: ${imagePath}`);
      } else if (loggedIn) {
        localImages.push(imagePath);
      }
    });

    Promise.all(localImages.map(async (imagePath) => {
      const res = await authFetch(`${API}/api/file/raw?path=${encodeURIComponent(imagePath)}`);
      if (!res.ok) throw new Error(`failed to load image: ${imagePath}`);
      const url = URL.createObjectURL(await res.blob());
      createdBlobUrls.push(url);
      return [imagePath, url] as const;
    })).then((entries) => {
      if (cancelled) {
        entries.forEach(([, url]) => URL.revokeObjectURL(url));
        return;
      }
      setUrls(Object.fromEntries([...directEntries, ...entries]));
    }).catch(() => {
      createdBlobUrls.forEach((url) => URL.revokeObjectURL(url));
    });
    return () => {
      cancelled = true;
      createdBlobUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [images]);

  if (!images?.length) return null;
  const loggedIn = !!getToken();
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {images.map((imagePath) => {
        if (isS3ImagePath(imagePath) && !pickImageSrc(imagePath)) return null;
        const url = urls[imagePath];
        if (url) {
          return (
            <button key={imagePath} type="button" onClick={() => window.open(url, "_blank", "noopener,noreferrer")} className="block cursor-zoom-in">
              <img src={url} alt={imagePath.split("/").pop() || "attached image"} className="max-h-64 max-w-full rounded border border-sol-base02 object-contain" />
            </button>
          );
        }
        // Anonymous viewer + local EC2 image: not fetchable, show a static fallback.
        if (!loggedIn && !pickImageSrc(imagePath)) {
          return (
            <div key={imagePath} className="h-24 w-24 rounded border border-sol-base02 bg-sol-base02 flex items-center justify-center text-sol-base01" title={imagePath.split("/").pop() || "image"}>
              <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            </div>
          );
        }
        return <div key={imagePath} className="h-24 w-24 rounded border border-sol-base02 bg-sol-base02 animate-pulse" />;
      })}
    </div>
  );
}

function truncate(s: string, n: number): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n) + "..." : s;
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
  if (n === "todowrite")
    return { icon: "\u2713", label: "Todo", color: "text-sol-green", iconBg: "bg-sol-green/15" };
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
  // Bash: show truncated command
  if (n === "bash") return truncate(String(args?.command || ""), 60);
  // Grep: show pattern
  if (n === "grep") return truncate(String(args?.pattern || ""), 40);
  // Glob: show pattern
  if (n === "glob") return truncate(String(args?.pattern || ""), 40);
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

interface TraceInfo {
  traceId: string;
  fromSkill?: string;
  toSkill?: string;
  fromChatId?: string;
  toChatId?: string;
  cleanContent: string;
}

// Permissive parser: only `trace:` is required; `from`, `to`, `from_chat`, `to_chat` are
// independently optional and may appear in any order.
function parseTracePrefix(content: string): TraceInfo | null {
  const match = content.match(/^\[trace:(\S+)((?:\s+\w+:\S+)*)\]\n?/);
  if (!match) return null;
  const rest = match[2];
  const get = (k: string): string | undefined => {
    const r = rest.match(new RegExp(`\\s${k}:(\\S+)`));
    return r ? r[1] : undefined;
  };
  return {
    traceId: match[1],
    fromSkill: get("from"),
    toSkill: get("to"),
    fromChatId: get("from_chat"),
    toChatId: get("to_chat"),
    cleanContent: content.slice(match[0].length),
  };
}

function TimestampLine({ timestamp, traceId, fromSkill, toSkill, fromChatId, toChatId, onSelectChat, onSelectTrace }: { timestamp?: string; traceId?: string; fromSkill?: string; toSkill?: string; fromChatId?: string; toChatId?: string; onSelectChat?: (chatId: string) => void; onSelectTrace?: (traceId: string) => void }) {
  const formatted = formatDateTime(timestamp);
  const hasAny = formatted || traceId || fromSkill || toSkill || fromChatId || toChatId;
  if (!hasAny) return null;
  const hasFrom = fromSkill || fromChatId;
  const hasTo = toSkill || toChatId;
  return (
    <div className="text-xs sm:text-[0.65rem] text-sol-base01 mb-1 flex items-center">
      {formatted && <span>{formatted}</span>}
      {traceId && <span className={`ml-1.5 text-[0.6rem] ${TRACE_BADGE} ${onSelectTrace ? "hover:bg-sol-base01/30 cursor-pointer" : ""}`} onClick={() => onSelectTrace?.(traceId)}>#{traceId}</span>}
      {fromSkill && <span className={`ml-1.5 text-[0.6rem] ${topicBadgeClass(fromSkill)}`}>{fromSkill}</span>}
      {fromChatId && <span className={`ml-1 text-[0.6rem] ${CHAT_BADGE} hover:bg-sol-blue/30 cursor-pointer`} onClick={() => onSelectChat?.(fromChatId)}>{fromChatId}</span>}
      {hasFrom && hasTo && <span className="ml-1 text-sol-base01">→</span>}
      {toSkill && <span className={`ml-1 text-[0.6rem] ${topicBadgeClass(toSkill)}`}>{toSkill}</span>}
      {toChatId && <span className={`ml-1 text-[0.6rem] ${CHAT_BADGE} hover:bg-sol-blue/30 cursor-pointer`} onClick={() => onSelectChat?.(toChatId)}>{toChatId}</span>}
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
  onOpenFile?: (path: string, line?: number) => void;
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

  const isBash = n === "bash";
  const bashCommand = isBash ? String(args?.command || "") : "";
  const expandContent = isBash && bashCommand ? (bashCommand + (content ? "\n" + content : "")) : content;
  // For Edit, we show a diff view from old_string/new_string
  const isEdit = n === "edit" || n === "file_edit";
  const editOld = isEdit ? String(args?.old_string || "") : "";
  const editNew = isEdit ? String(args?.new_string || "") : "";
  const hasDiff = isEdit && (editOld || editNew);
  const isSkill = n === "skill";
  const hasContent = !isSkill && (expandContent.length > 0 || hasDiff || (todoItems && todoItems.length > 0));

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
        todoItems && todoItems.length > 0 ? (
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

function UserMessage({ content, images, timestamp, onSelectChat, onSelectTrace }: { content: string; images?: string[]; timestamp?: string; onSelectChat?: (chatId: string) => void; onSelectTrace?: (traceId: string) => void }) {
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
      <TimestampLine
        timestamp={timestamp}
        traceId={traceInfo?.traceId}
        fromSkill={traceInfo?.fromSkill}
        toSkill={traceInfo?.toSkill}
        fromChatId={traceInfo?.fromChatId}
        toChatId={traceInfo?.toChatId}
        onSelectChat={onSelectChat}
        onSelectTrace={onSelectTrace}
      />
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
            <MessageImages images={images} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MessageBubble({ role, content, images, links, toolName, arguments: args, timestamp, dimmed, onOpenFile, onShowSources, onSelectChat, onSelectTrace, onOpenArtifact }: MessageBubbleProps) {
  const [artifactMode, setArtifactMode] = useState<Record<string, ArtifactMode>>({});

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
    return <UserMessage content={content} images={images} timestamp={timestamp} onSelectChat={onSelectChat} onSelectTrace={onSelectTrace} />;
  }

  const markdownContent = preprocessCitationLinks(content, links);
  const citationLinks = normalizeLinks(links);

  // Assistant message: rendered markdown like CLI
  return (
    <div>
      {!dimmed && <TimestampLine timestamp={timestamp} />}
      <div className={`text-sm sm:text-[0.775rem] prose prose-sm max-w-none ${dimmed ? "text-sol-base01" : "text-sol-base0"}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkStripComments]}
          urlTransform={(url) => url.startsWith("cite://") ? url : defaultUrlTransform(url)}
          components={{
            pre({ children, node }) {
              const artifact = artifactFromPreNode(node as HastNode | undefined) ?? artifactFromPreChildren(children);
              if (artifact) {
                const key = artifactKey(artifact.type, artifact.spec);
                return (
                  <ArtifactView
                    type={artifact.type}
                    spec={artifact.spec}
                    mode={artifactMode[key] ?? "preview"}
                    onModeChange={(mode) => setArtifactMode((prev) => ({ ...prev, [key]: mode }))}
                    onOpenInTab={onOpenArtifact ? () => onOpenArtifact(artifact.type, artifact.spec) : undefined}
                    variant="inline"
                  />
                );
              }
              return <pre>{children}</pre>;
            },
            a({ href, children, node, ...props }) {
              const rawHref = href || (node as { url?: string } | undefined)?.url;
              const citationIndices = parseCitationHref(rawHref);
              if (citationIndices) {
                return <CitationChip citationIndices={citationIndices} citationLinks={citationLinks} fallback={citationFallback(children)} />;
              }
              const fileRef = parseLocalFileReference(rawHref);
              if (fileRef && onOpenFile) {
                return (
                  <a
                    href={rawHref}
                    onClick={(e) => {
                      e.preventDefault();
                      onOpenFile(fileRef.path, fileRef.line);
                    }}
                    {...props}
                  >
                    {children}
                  </a>
                );
              }
              return <a href={href} {...props}>{children}</a>;
            },
            code({ children, className, ...props }) {
              const text = String(children).replace(/\n$/, "");
              const isInline = !className;
              const fileRef = isInline ? parseLocalFileReference(text, { allowRelative: true }) : null;
              if (fileRef && onOpenFile) {
                return (
                  <code
                    {...props}
                    className="cursor-pointer text-sol-cyan hover:underline"
                    onClick={() => onOpenFile(fileRef.path, fileRef.line)}
                  >
                    {children}
                  </code>
                );
              }
              return <code className={className} {...props}>{children}</code>;
            },
          }}
        >{markdownContent}</ReactMarkdown>
        {citationLinks.length ? (
          <button
            type="button"
            onClick={() => onShowSources?.(normalizeLinks(links))}
            className="mt-2 inline-flex items-center rounded-full border border-sol-base02 px-2 py-1 font-mono text-xs font-semibold text-sol-base01 hover:border-sol-blue hover:text-sol-blue"
          >
            {citationLinks.length} source{citationLinks.length === 1 ? "" : "s"}
          </button>
        ) : null}
        <MessageImages images={images} />
      </div>
    </div>
  );
}

export { pickImageSrc };
export { artifactTypeFromClassName };
export { artifactFromPreNode };
export { preprocessCitationLinks };
export type { BubbleRole };
