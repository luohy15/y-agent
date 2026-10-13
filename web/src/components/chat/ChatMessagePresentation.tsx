import { useEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import ArtifactView, { type ArtifactMode, type ArtifactType } from "../ArtifactView";
import { ChatImage, ChatMessageImages } from "../ChatImage";
import { citationDomain, citationHostname } from "../citationDomain";
import { normalizeLinks, type NormalizedCitationLink } from "../citationLinks";
import remarkStripComments from "../../utils/remarkStripComments";
import { CopyButton, TimestampLine, nodeText, parseTracePrefix } from "./messageChrome";
import { ToolCallView, type GetPresentedContent, type LoadPresentedContent, type PresentedContentState } from "./toolCallView";

export type ChatMessageRole = "user" | "assistant" | "tool_pending" | "tool_result" | "tool_denied" | "system";

export type PresentedCitationLink = string | {
  url: string;
  title?: string;
  snippet?: string;
  last_updated?: string;
};

export interface PresentedFileReference {
  path: string;
  line?: number;
}

export type ResolveFileReference = (
  href?: string | null,
  options?: { allowRelative?: boolean },
) => PresentedFileReference | null;

export interface ChatMessagePresentationProps {
  role: ChatMessageRole;
  content: string;
  toolName?: string;
  arguments?: Record<string, unknown>;
  timestamp?: string;
  images?: string[];
  links?: PresentedCitationLink[];
  dimmed?: boolean;
  toolCallId?: string;
  contentTruncated?: boolean;
  contentLength?: number;
  onLoadFullContent?: LoadPresentedContent;
  getFullContent?: GetPresentedContent;
  onOpenFile?: (path: string, line?: number) => void;
  onShowSources?: (links: PresentedCitationLink[]) => void;
  onSelectChat?: (chatId: string) => void;
  onSelectTrace?: (traceId: string) => void;
  onOpenArtifact?: (type: ArtifactType, spec: string) => void;
  resolveFileReference?: ResolveFileReference;
}

export type { PresentedContentState, LoadPresentedContent, GetPresentedContent };

interface HastNode {
  type?: string;
  tagName?: string;
  value?: string;
  properties?: { className?: string | string[]; [key: string]: unknown };
  children?: HastNode[];
}

function parseCitationHref(href?: string): number[] | null {
  if (!href?.startsWith("cite://")) return null;
  const indices = href.slice("cite://".length).split(",").map((part) => Number.parseInt(part, 10)).filter((n) => Number.isFinite(n) && n > 0);
  return indices.length > 0 ? indices : null;
}

const CITATION_RUN_RE = /(\[\d+\])+/g;
const CITATION_INDEX_RE = /\[(\d+)\]/g;

export function preprocessCitationLinks(content: string, links?: PresentedCitationLink[]): string {
  if (!links?.length) return content;
  return content.replace(CITATION_RUN_RE, (match) => {
    const indices = Array.from(match.matchAll(CITATION_INDEX_RE), (item) => item[1]);
    return indices.length ? `[cite](cite://${indices.join(",")})` : match;
  });
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
  const label = citationIndices.length === 1 ? citationDomain(firstLink.url) : `${citationDomain(firstLink.url)} +${citationIndices.length - 1}`;
  return (
    <span className="relative inline-flex align-baseline" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide} data-testid="citation-chip">
      <button type="button" onClick={() => window.open(firstLink.url, "_blank", "noopener,noreferrer")} className="mx-0.5 inline-flex cursor-pointer items-center rounded-full border border-sol-base01/40 bg-sol-base02 px-1.5 py-0.5 align-baseline font-mono text-[0.65rem] font-semibold leading-none text-sol-cyan hover:border-sol-cyan hover:bg-sol-base01/20">{label}</button>
      {open && (
        <span className="absolute left-0 top-full z-30 mt-1 block max-w-xs rounded border border-sol-base01/30 bg-sol-base02 p-2 text-[0.65rem] leading-snug text-sol-base0 shadow-float" onMouseEnter={show} onMouseLeave={hide}>
          {citedLinks.map((link, index) => (
            <a key={`${link.url}-${citationIndices[index]}`} href={link.url} target="_blank" rel="noopener noreferrer" className="block min-w-0 truncate rounded px-1 py-0.5 text-sol-blue hover:bg-sol-base01/20 hover:underline" onClick={(event) => event.stopPropagation()}>
              <span className="font-mono text-sol-base01">[{citationIndices[index]}]</span> {link.title || citationHostname(link.url)}
            </a>
          ))}
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

function hastText(node: HastNode): string {
  if (typeof node.value === "string") return node.value;
  return node.children?.map(hastText).join("") ?? "";
}

function artifactFromPreNode(node?: HastNode): { type: ArtifactType; spec: string } | null {
  const codeNode = node?.children?.find((child) => child.type === "element" && child.tagName === "code");
  const type = artifactTypeFromClassName(classNameString(codeNode?.properties?.className));
  if (!type || !codeNode) return null;
  return { type, spec: hastText(codeNode).replace(/\n$/, "") };
}

function artifactFromPreChildren(children: ReactNode): { type: ArtifactType; spec: string } | null {
  const items: ReactNode[] = Array.isArray(children) ? children : [children];
  const child = items.find((item) => Boolean(item) && typeof item === "object" && (item as { type?: unknown }).type === "code") as { props?: { className?: string; children?: ReactNode } } | undefined;
  const type = artifactTypeFromClassName(child?.props?.className);
  if (!type) return null;
  return { type, spec: nodeText(child?.props?.children).replace(/\n$/, "") };
}

function artifactKey(type: ArtifactType, spec: string): string {
  const input = spec.slice(0, 200);
  let hash = 0;
  for (let i = 0; i < input.length; i += 1) hash = ((hash << 5) - hash + input.charCodeAt(i)) | 0;
  return `${type}:${Math.abs(hash).toString(36)}`;
}

const USER_MSG_MAX_LINES = 3;

function UserMessage({ content, images, timestamp, onSelectChat, onSelectTrace }: Pick<ChatMessagePresentationProps, "content" | "images" | "timestamp" | "onSelectChat" | "onSelectTrace">) {
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [clamped, setClamped] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const traceInfo = parseTracePrefix(content);
  const displayContent = traceInfo ? traceInfo.cleanContent : content;
  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 16;
    setClamped(el.scrollHeight > lineHeight * USER_MSG_MAX_LINES + 1);
  }, [displayContent]);
  return (
    <div data-testid="message-user">
      <TimestampLine timestamp={timestamp} traceId={traceInfo?.traceId} fromSkill={traceInfo?.fromSkill} toSkill={traceInfo?.toSkill} fromChatId={traceInfo?.fromChatId} toChatId={traceInfo?.toChatId} onSelectChat={onSelectChat} onSelectTrace={onSelectTrace} />
      <div className="group relative bg-sol-base02 rounded px-2 py-1.5 -mx-2">
        <CopyButton text={displayContent} className="absolute right-1 top-1 opacity-0 transition-opacity group-hover:opacity-100" />
        <div className="flex items-baseline">
          <span className="text-sol-base01 font-mono y-chat-prompt-text mr-2 select-none shrink-0">&gt;</span>
          <div className="min-w-0 flex-1">
            <div ref={contentRef} className={`y-chat-message-text text-sol-base1 whitespace-pre-wrap break-words min-w-0${!expanded && clamped ? " line-clamp-3" : ""}`}>{displayContent}</div>
            {clamped && <button type="button" onClick={() => setExpanded(!expanded)} className="text-sol-blue text-xs mt-0.5 hover:underline cursor-pointer">{expanded ? "Show less" : "Show more"}</button>}
            <ChatMessageImages images={images} />
          </div>
        </div>
      </div>
    </div>
  );
}

function SourceDisclosure({ links, onShowSources, rawLinks }: { links: NormalizedCitationLink[]; onShowSources?: (links: PresentedCitationLink[]) => void; rawLinks?: PresentedCitationLink[] }) {
  if (!links.length) return null;
  if (onShowSources) {
    return (
      <button type="button" data-testid="sources-button" onClick={() => onShowSources(rawLinks || links)} className="mt-2 inline-flex items-center rounded-full border border-sol-base02 px-2 py-1 font-mono text-xs font-semibold text-sol-base01 hover:border-sol-blue hover:text-sol-blue">
        {links.length} source{links.length === 1 ? "" : "s"}
      </button>
    );
  }
  return (
    <details className="mt-2" data-testid="source-disclosure">
      <summary className="inline-flex cursor-pointer items-center rounded-full border border-sol-base02 px-2 py-1 font-mono text-xs font-semibold text-sol-base01">{links.length} source{links.length === 1 ? "" : "s"}</summary>
      <ul className="mt-1 flex flex-col gap-0.5">
        {links.map((link) => (
          <li key={link.url}><a href={link.url} target="_blank" rel="noopener noreferrer" className="text-xs text-sol-blue hover:underline">{link.title || citationHostname(link.url)}</a></li>
        ))}
      </ul>
    </details>
  );
}

export default function ChatMessagePresentation(props: ChatMessagePresentationProps) {
  const {
    role, content, images, links, toolName, arguments: args, timestamp, dimmed, toolCallId,
    contentTruncated, contentLength, onLoadFullContent, getFullContent, onOpenFile, onShowSources,
    onSelectChat, onSelectTrace, onOpenArtifact, resolveFileReference,
  } = props;
  const [artifactMode, setArtifactMode] = useState<Record<string, ArtifactMode>>({});
  if (role === "system") return <div data-testid="message-system" className="self-center text-sol-base01 y-chat-system-text py-1">{content}</div>;
  if (role === "tool_pending" || role === "tool_result" || role === "tool_denied") {
    const status = role === "tool_pending" ? "pending" : role === "tool_denied" ? "denied" : "done";
    return (
      <ToolCallView
        toolName={toolName || "tool"}
        args={args}
        content={role === "tool_pending" ? "" : content}
        status={status}
        toolCallId={toolCallId}
        contentTruncated={contentTruncated}
        contentLength={contentLength}
        onLoadFullContent={onLoadFullContent}
        getFullContent={getFullContent}
        onOpenFile={onOpenFile}
      />
    );
  }
  if (role === "user") return <UserMessage content={content} images={images} timestamp={timestamp} onSelectChat={onSelectChat} onSelectTrace={onSelectTrace} />;

  const markdownContent = preprocessCitationLinks(content, links);
  const citationLinks = normalizeLinks(links);
  return (
    <div className="group relative" data-testid="message-assistant">
      <CopyButton text={content} className="absolute right-0 top-0 z-10 opacity-0 transition-opacity group-hover:opacity-100" />
      {!dimmed && <TimestampLine timestamp={timestamp} />}
      <div className={`y-chat-message-text prose prose-sm max-w-none ${dimmed ? "text-sol-base01" : "text-sol-base0"}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkStripComments]}
          urlTransform={(url: string) => url.startsWith("cite://") ? url : defaultUrlTransform(url)}
          components={{
            img: ChatImage,
            pre({ children, node }: { children?: ReactNode; node?: HastNode }) {
              const artifact = artifactFromPreNode(node) ?? artifactFromPreChildren(children);
              if (!artifact) return <pre>{children}</pre>;
              const key = artifactKey(artifact.type, artifact.spec);
              return (
                <ArtifactView
                  type={artifact.type}
                  spec={artifact.spec}
                  mode={artifactMode[key] ?? "preview"}
                  onModeChange={(mode: ArtifactMode) => setArtifactMode((prev) => ({ ...prev, [key]: mode }))}
                  onOpenInTab={onOpenArtifact ? () => onOpenArtifact(artifact.type, artifact.spec) : undefined}
                  variant="inline"
                />
              );
            },
            a({ href, children, node, ...anchorProps }: { href?: string; children?: ReactNode; node?: { url?: string }; [key: string]: unknown }) {
              const rawHref = href || node?.url;
              const citationIndices = parseCitationHref(rawHref);
              if (citationIndices) return <CitationChip citationIndices={citationIndices} citationLinks={citationLinks} fallback={typeof children === "string" ? children : ""} />;
              const fileRef = resolveFileReference?.(rawHref);
              if (fileRef && onOpenFile) {
                return <a href={rawHref} onClick={(event) => { event.preventDefault(); onOpenFile(fileRef.path, fileRef.line); }} {...anchorProps}>{children}</a>;
              }
              return <a href={href} {...anchorProps}>{children}</a>;
            },
            code({ children, className, ...codeProps }: { children?: ReactNode; className?: string; [key: string]: unknown }) {
              const text = String(children).replace(/\n$/, "");
              const fileRef = !className ? resolveFileReference?.(text, { allowRelative: true }) : null;
              if (fileRef && onOpenFile) {
                return <code {...codeProps} className="cursor-pointer text-sol-cyan hover:underline" onClick={() => onOpenFile(fileRef.path, fileRef.line)}>{children}</code>;
              }
              return <code className={className} {...codeProps}>{children}</code>;
            },
          } as any}
        >{markdownContent}</ReactMarkdown>
        <SourceDisclosure links={citationLinks} onShowSources={onShowSources} rawLinks={links} />
        <ChatMessageImages images={images} />
      </div>
    </div>
  );
}
