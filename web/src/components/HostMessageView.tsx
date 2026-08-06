import { useEffect, useRef, useState } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { PatchDiff } from "@pierre/diffs/react";
import { API, authFetch, getToken } from "../api";
import ArtifactView, { type ArtifactMode, type ArtifactType } from "./ArtifactView";
import ImageLightbox from "./ImageLightbox";
import remarkStripComments from "../utils/remarkStripComments";
import { parseLocalFileReference } from "../utils/localFileLinks";

export type HostMessageRole = "user" | "assistant" | "tool_pending" | "tool_result" | "tool_denied" | "system";
export type HostCitationLink = string | { url: string; title?: string; snippet?: string; last_updated?: string };
export interface HostMessage {
  role: HostMessageRole;
  content: string;
  toolName?: string;
  arguments?: Record<string, unknown>;
  toolCallId?: string;
  timestamp?: string;
  images?: string[];
  links?: HostCitationLink[];
}

interface ContentPart { type: string; text?: string }
interface HastNode { type?: string; tagName?: string; value?: string; properties?: { className?: string | string[] }; children?: HastNode[] }

function stripInvisible(value: string): string {
  // eslint-disable-next-line no-control-regex
  return value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\u200B-\u200F\u2028-\u202F\u2060-\u206F\uFEFF\uFFF9-\uFFFC]/g, "");
}

export function extractContent(content?: string | ContentPart[]): string {
  if (!content) return "";
  if (typeof content === "string") return stripInvisible(content);
  return content.map((part) => {
    if (typeof part === "string") return stripInvisible(part);
    if (part.type === "text") return stripInvisible(part.text || "");
    if (part.type === "image") return "[image]";
    return "";
  }).join("");
}

export function filterTrailingEmptyAssistantMessages(messages: HostMessage[]): HostMessage[] {
  const result: HostMessage[] = [];
  let turnStart = 0;
  const flush = (end: number) => {
    let lastContent = -1;
    for (let i = end - 1; i >= turnStart; i -= 1) {
      if (messages[i].role === "assistant" && messages[i].content.trim()) { lastContent = i; break; }
    }
    for (let i = turnStart; i < end; i += 1) {
      const message = messages[i];
      if (lastContent >= 0 && i > lastContent && message.role === "assistant" && !message.content.trim() && !message.images?.length && !message.links?.length) continue;
      result.push(message);
    }
  };
  for (let i = 0; i < messages.length; i += 1) {
    if (messages[i].role === "user" && i > turnStart) { flush(i); turnStart = i; }
  }
  flush(messages.length);
  return result;
}

export function mergeToolArguments(start?: Record<string, unknown>, result?: Record<string, unknown>): Record<string, unknown> | undefined {
  const merged = { ...(start || {}), ...(result || {}) };
  return Object.keys(merged).length ? merged : undefined;
}

export function mergeToolResult(pending: HostMessage, result: HostMessage): HostMessage {
  return { ...pending, role: result.role, content: result.content, ...(result.toolName ? { toolName: result.toolName } : {}), ...(result.arguments ? { arguments: result.arguments } : {}) };
}

export function parseRawChatMessage(event: any): HostMessage[] {
  const message = event.data || event;
  const role = message.role || "assistant";
  const content = extractContent(message.content);
  const common = { timestamp: message.timestamp, images: message.images, links: message.links };
  if (role === "user") return [{ role, content, ...common }];
  if (role === "assistant" && message.tool_calls) {
    const result: HostMessage[] = content.trim() ? [{ role: "assistant", content, ...common }] : [];
    for (const call of message.tool_calls) {
      let args = {};
      try { args = JSON.parse(call.function?.arguments || "{}"); } catch {}
      result.push({ role: "tool_pending", content: "", toolName: call.function?.name, arguments: args, toolCallId: call.id, timestamp: message.timestamp });
    }
    return result;
  }
  if (role === "tool") return [{ role: content.startsWith("ERROR: User denied") ? "tool_denied" : "tool_result", content, toolCallId: message.tool_call_id, toolName: message.tool, arguments: message.arguments, timestamp: message.timestamp }];
  return [{ role: "assistant", content, ...common }];
}

export function parseChatMessages(rawMessages: unknown[]): HostMessage[] {
  const messages: HostMessage[] = [];
  for (const raw of rawMessages) {
    for (const message of parseRawChatMessage(raw)) {
      const pending = message.toolCallId && (message.role === "tool_result" || message.role === "tool_denied")
        ? messages.findIndex((item) => item.toolCallId === message.toolCallId && item.role === "tool_pending") : -1;
      if (pending >= 0) messages[pending] = mergeToolResult(messages[pending], message);
      else messages.push(message);
    }
  }
  return filterTrailingEmptyAssistantMessages(messages);
}

function artifactFromNode(node?: HastNode): { type: ArtifactType; spec: string } | null {
  const code = node?.children?.find((child) => child.tagName === "code");
  const classes = Array.isArray(code?.properties?.className) ? code.properties.className.join(" ") : code?.properties?.className || "";
  const type = /\blanguage-mermaid\b/.test(classes) ? "mermaid" : /\blanguage-vega-lite\b/.test(classes) ? "vega-lite" : /\blanguage-artifact-svg\b/.test(classes) ? "artifact-svg" : null;
  if (!type || !code) return null;
  const text = (part: HastNode): string => typeof part.value === "string" ? part.value : part.children?.map(text).join("") || "";
  return { type, spec: text(code).replace(/\n$/, "") };
}

function buildDiff(path: string, oldText: string, newText: string): string {
  const oldLines = oldText ? oldText.split("\n") : [];
  const newLines = newText ? newText.split("\n") : [];
  return `--- a/${path}\n+++ b/${path}\n@@ -1,${oldLines.length} +1,${newLines.length} @@\n${oldLines.map((line) => `-${line}`).join("\n")}\n${newLines.map((line) => `+${line}`).join("\n")}`;
}

function MessageImages({ images }: { images?: string[] }) {
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [lightbox, setLightbox] = useState(-1);
  useEffect(() => {
    let cancelled = false;
    const blobs: string[] = [];
    const load = async () => {
      const entries: [string, string][] = [];
      for (const path of images || []) {
        if (/^https?:\/\//.test(path)) entries.push([path, path]);
        else if (path.startsWith("s3://luohy15/")) entries.push([path, `https://cdn.luohy15.com/${path.slice(13)}`]);
        else if (getToken()) {
          const response = await authFetch(`${API}/api/module/file/raw?path=${encodeURIComponent(path)}`);
          if (response.ok) { const url = URL.createObjectURL(await response.blob()); blobs.push(url); entries.push([path, url]); }
        }
      }
      if (!cancelled) setUrls(Object.fromEntries(entries));
    };
    void load();
    return () => { cancelled = true; blobs.forEach(URL.revokeObjectURL); };
  }, [images]);
  if (!images?.length) return null;
  const resolved = images.map((path) => urls[path]).filter(Boolean);
  return <div className="mt-2 flex flex-wrap gap-2">
    {images.map((path) => urls[path] ? <button key={path} type="button" onClick={() => setLightbox(resolved.indexOf(urls[path]))} className="block cursor-zoom-in"><img src={urls[path]} alt={path.split("/").pop() || "attached image"} className="max-h-64 max-w-full rounded border border-sol-base02 object-contain" /></button> : <div key={path} className="h-24 w-24 rounded border border-sol-base02 bg-sol-base02" />)}
    <ImageLightbox images={resolved} index={lightbox} onClose={() => setLightbox(-1)} onNext={() => setLightbox((i) => (i + 1) % resolved.length)} onPrev={() => setLightbox((i) => (i - 1 + resolved.length) % resolved.length)} />
  </div>;
}

export interface HostTurnItem { key: string; message?: HostMessage; process?: HostMessage[] }

// Compact a flat message stream into one item per user/final-assistant pair,
// folding intervening assistant narration and tool activity into a single
// disclosure item so a long agentic turn doesn't render as a wall of text.
export function buildTurnDisplay(messages: HostMessage[]): HostTurnItem[] {
  const items: HostTurnItem[] = [];
  const userStarts: number[] = [];
  for (let i = 0; i < messages.length; i += 1) if (messages[i].role === "user") userStarts.push(i);
  const rounds: Array<{ start: number; contentStart: number; end: number; hasUser: boolean }> = [];
  if (userStarts.length === 0 || userStarts[0] > 0) {
    rounds.push({ start: 0, contentStart: 0, end: userStarts.length ? userStarts[0] : messages.length, hasUser: false });
  }
  for (let r = 0; r < userStarts.length; r += 1) {
    const start = userStarts[r];
    const end = r + 1 < userStarts.length ? userStarts[r + 1] : messages.length;
    rounds.push({ start, contentStart: start + 1, end, hasUser: true });
  }
  for (const round of rounds) {
    if (round.hasUser) items.push({ key: `m${round.start}`, message: messages[round.start] });
    let lastAssistant = -1;
    for (let i = round.end - 1; i >= round.contentStart; i -= 1) {
      if (messages[i].role === "assistant") { lastAssistant = i; break; }
    }
    const process: HostMessage[] = [];
    for (let i = round.contentStart; i < round.end; i += 1) if (i !== lastAssistant) process.push(messages[i]);
    if (process.length) items.push({ key: `p${round.contentStart}`, process });
    if (lastAssistant >= 0) items.push({ key: `m${lastAssistant}`, message: messages[lastAssistant] });
  }
  return items;
}

const TOOL_LABELS: Record<string, string> = { bash: "Bash", read: "Read", file_read: "Read", write: "Write", file_write: "Write", edit: "Edit", file_edit: "Edit", grep: "Grep", glob: "Glob", agent: "Agent", todowrite: "Todo" };

function toolLabel(name?: string): string {
  if (!name) return "tool";
  return TOOL_LABELS[name.toLowerCase()] || name;
}

function summarizeProcess(messages: HostMessage[]): string {
  const counts: Record<string, number> = {};
  let notes = 0;
  for (const message of messages) {
    if (message.role === "assistant") { notes += 1; continue; }
    if (message.role === "tool_pending" || message.role === "tool_result" || message.role === "tool_denied") {
      const label = toolLabel(message.toolName);
      counts[label] = (counts[label] || 0) + 1;
    }
  }
  const parts = Object.entries(counts).map(([label, count]) => (count > 1 ? `${label} ×${count}` : label));
  if (notes) parts.push(notes > 1 ? `${notes} notes` : "note");
  return parts.length ? parts.join(", ") : `${messages.length} steps`;
}

function ProcessSummary({ messages }: { messages: HostMessage[] }) {
  return <details className="font-mono text-xs text-sol-base01">
    <summary className="cursor-pointer" data-testid="process-summary">{summarizeProcess(messages)}</summary>
    <div className="mt-1 flex flex-col gap-2">{messages.map((message, index) => <HostBubble key={index} message={message} />)}</div>
  </details>;
}

function HostBubble({ message }: { message: HostMessage }) {
  const [modes, setModes] = useState<Record<string, ArtifactMode>>({});
  if (message.role === "user") return <div className="rounded bg-sol-base02 px-2 py-1.5 text-sm text-sol-base1 whitespace-pre-wrap break-words"><span className="mr-2 font-mono text-sol-base01">&gt;</span>{message.content}<MessageImages images={message.images} /></div>;
  if (message.role === "tool_pending") return <div className="font-mono text-xs text-sol-blue">● {message.toolName || "tool"}</div>;
  if (message.role === "tool_result" || message.role === "tool_denied") {
    const args = message.arguments || {};
    const edit = ["edit", "file_edit"].includes((message.toolName || "").toLowerCase());
    return <details className="font-mono text-xs text-sol-base01"><summary className="cursor-pointer">{message.toolName || "tool"}{message.role === "tool_denied" ? " denied" : ""}</summary>{edit ? <PatchDiff patch={buildDiff(String(args.file_path || args.path || "file"), String(args.old_string || ""), String(args.new_string || ""))} options={{ theme: "solarized-dark" }} /> : <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded bg-sol-base02 p-2 text-sol-base0">{message.content}</pre>}</details>;
  }
  if (message.role === "system") return <div className="text-center text-xs text-sol-base01">{message.content}</div>;
  return <div className="text-sm sm:text-[0.775rem] prose prose-sm max-w-none text-sol-base0">
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkStripComments]}
      urlTransform={(url) => url.startsWith("cite://") ? url : defaultUrlTransform(url)}
      components={{
        pre({ children, node }) {
          const artifact = artifactFromNode(node as HastNode);
          if (!artifact) return <pre>{children}</pre>;
          const key = `${artifact.type}:${artifact.spec.slice(0, 80)}`;
          return <ArtifactView type={artifact.type} spec={artifact.spec} mode={modes[key] || "preview"} onModeChange={(mode) => setModes((previous) => ({ ...previous, [key]: mode }))} variant="inline" />;
        },
        a({ href, children, ...props }) {
          const file = parseLocalFileReference(href);
          return file ? <a href={href} title={file.path} {...props}>{children}</a> : <a href={href} {...props}>{children}</a>;
        },
      }}
    >{message.content}</ReactMarkdown>
    <MessageImages images={message.images} />
  </div>;
}

export default function HostMessageView({ messages, running = false, centered = false, scrollContainerRef }: { messages: HostMessage[]; running?: boolean; centered?: boolean; scrollContainerRef?: React.RefObject<HTMLDivElement | null> }) {
  const ownRef = useRef<HTMLDivElement>(null);
  const ref = scrollContainerRef || ownRef;
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [messages, ref]);
  const items = buildTurnDisplay(messages);
  return <div ref={ref} className="flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable] px-6 py-4 text-xs"><div className={`${centered ? "max-w-3xl mx-auto w-full " : ""}flex flex-col gap-3`}>{items.map((item) => item.message ? <HostBubble key={item.key} message={item.message} /> : <ProcessSummary key={item.key} messages={item.process!} />)}{running && <span className="inline-block h-5 w-2.5 bg-sol-base1" />}</div></div>;
}
