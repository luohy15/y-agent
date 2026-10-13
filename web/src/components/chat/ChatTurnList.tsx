import { createElement, useEffect, useRef, useState, type ReactNode } from "react";
import type { ArtifactType } from "../ArtifactView";
import { ChatImageScope } from "../ChatImage";
import ChatMessagePresentation, {
  type ChatMessagePresentationProps,
  type GetPresentedContent,
  type LoadPresentedContent,
  type PresentedCitationLink,
  type ResolveFileReference,
} from "./ChatMessagePresentation";
import { defaultToolIcon, expandProcess, groupTurns, toolIconMap, type GroupableMessage } from "./turnGrouping";

// Shared turn list (todo 3892 round 2): grouping, process summary row and
// expanded process are identical on share, fallback and authenticated chat.
// Pure presentation: no fetch/auth/commands; every control is a capability prop.
export interface ChatTurnMessage extends GroupableMessage {
  content: string;
  arguments?: Record<string, unknown>;
  toolCallId?: string;
  timestamp?: string;
  images?: string[];
  links?: PresentedCitationLink[];
  contentTruncated?: boolean;
  contentLength?: number;
}

export interface ChatTurnListProps {
  messages: ChatTurnMessage[];
  scopeId: string;
  running?: boolean;
  centered?: boolean;
  inline?: boolean;
  allowLocalAttachments?: boolean;
  showProgress?: boolean;
  scrollContainerRef?: { current: HTMLDivElement | null };
  selectMode?: boolean;
  selectedIndices?: Set<number>;
  onToggleSelect?: (index: number) => void;
  resolveFileReference?: ResolveFileReference;
  onOpenFile?: (path: string, line?: number) => void;
  onShowSources?: (links: PresentedCitationLink[], messageIndex?: number) => void;
  onSelectChat?: (chatId: string) => void;
  onSelectTrace?: (traceId: string) => void;
  onOpenArtifact?: (type: ArtifactType, spec: string) => void;
  onLoadFullContent?: LoadPresentedContent;
  getFullContent?: GetPresentedContent;
}

type Capabilities = Pick<ChatTurnListProps, "resolveFileReference" | "onOpenFile" | "onSelectChat" | "onSelectTrace" | "onOpenArtifact" | "onLoadFullContent" | "getFullContent">;

function Bubble({ message, caps, dimmed, onShowSources }: { message: ChatTurnMessage; caps: Capabilities; dimmed?: boolean; onShowSources?: ChatMessagePresentationProps["onShowSources"] }) {
  return <ChatMessagePresentation role={message.role} content={message.content} images={message.images} links={message.links} toolName={message.toolName} arguments={message.arguments} timestamp={message.timestamp} dimmed={dimmed} toolCallId={message.toolCallId} contentTruncated={message.contentTruncated} contentLength={message.contentLength} onShowSources={onShowSources} {...caps} />;
}

function FileToolGroup({ kind, messages, startIndex, caps }: { kind: string; messages: ChatTurnMessage[]; startIndex: number; caps: Capabilities }) {
  const [expanded, setExpanded] = useState(false);
  const shortPath = (p: string) => { const parts = p.split("/"); return parts.length <= 2 ? p : parts.slice(-2).join("/"); };
  const paths = messages.map((m) => shortPath(String(m.arguments?.path || m.arguments?.file_path || ""))).filter(Boolean);
  const meta = toolIconMap[kind] || defaultToolIcon;

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
        <span className="text-sol-base01 text-[0.6rem] ml-auto">{expanded ? "▲" : "▼"}</span>
      </div>
      {!expanded && paths.length > 0 && (
        <div className="text-[0.65rem] text-sol-base01 font-mono truncate ml-6.5">{paths.join(", ")}</div>
      )}
      {expanded && (
        <div className="flex flex-col gap-1.5 mt-1 ml-6.5">
          {messages.map((m, j) => (
            <Bubble key={startIndex + j} message={{ ...m, links: undefined }} caps={caps} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProcessSummary({ toolCounts, roundMessages, roundStartIndex, defaultExpanded, caps, onShowSources }: { toolCounts: Record<string, number>; roundMessages: ChatTurnMessage[]; roundStartIndex: number; defaultExpanded?: boolean; caps: Capabilities; onShowSources?: ChatTurnListProps["onShowSources"] }) {
  const [expanded, setExpanded] = useState(defaultExpanded ?? false);
  useEffect(() => { setExpanded(defaultExpanded ?? false); }, [defaultExpanded]);
  const totalTools = Object.values(toolCounts).reduce((a, b) => a + b, 0);
  const entries = Object.entries(toolCounts).sort((a, b) => b[1] - a[1]);
  const expandedItems = expanded ? expandProcess(roundMessages, roundStartIndex) : [];

  return (
    <div>
      <div
        data-testid="process-summary"
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
        <span className="text-sol-base01 text-[0.6rem] ml-auto group-hover:text-sol-base0">{expanded ? "▲" : "▼"}</span>
      </div>
      {expanded && (
        <div className="flex flex-col gap-1.5 mt-1 ml-6.5">
          {expandedItems.map((ei) => {
            if (ei.type === "file_group") {
              return <FileToolGroup key={`fg-${ei.startIdx}`} kind={ei.kind} messages={ei.messages} startIndex={ei.startIdx} caps={caps} />;
            }
            return (
              <div key={ei.idx}>
                <Bubble message={ei.message} caps={caps} dimmed={ei.dimmed} onShowSources={onShowSources ? (links) => onShowSources(links, ei.idx) : undefined} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ChatTurnList({ messages, scopeId, running, centered, inline, allowLocalAttachments, showProgress, scrollContainerRef, selectMode, selectedIndices, onToggleSelect, onShowSources, ...caps }: ChatTurnListProps) {
  const internalRef = useRef<HTMLDivElement | null>(null);
  const containerRef = scrollContainerRef || internalRef;
  const [rootEl, setRootEl] = useState<HTMLDivElement | null>(null);
  const setScroller = (el: HTMLDivElement | null) => {
    containerRef.current = el;
    setRootEl((prev) => (prev === el ? prev : el));
  };
  // Only auto-scroll while pinned to the bottom so a manual scroll-up is never yanked back.
  const atBottomRef = useRef(true);

  useEffect(() => { atBottomRef.current = true; }, [scopeId]);
  useEffect(() => {
    if (inline) return;
    const el = containerRef.current;
    if (!el) return;
    const stick = () => { if (atBottomRef.current) el.scrollTop = el.scrollHeight; };
    const onScroll = () => {
      atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    // Re-stick when async content (mermaid/vega/images) or the container resizes.
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(stick) : null;
    ro?.observe(el);
    const inner = el.firstElementChild;
    if (inner) ro?.observe(inner);
    stick();
    return () => {
      el.removeEventListener("scroll", onScroll);
      ro?.disconnect();
    };
  }, [messages, containerRef, inline]);

  const items = groupTurns(messages);
  const innerClass = centered ? "max-w-3xl mx-auto w-full flex flex-col gap-3" : "flex flex-col gap-3";

  const content: ReactNode = (
    <>
      {items.map((item) => {
        if (item.type === "process_summary") {
          return <div key={`ps-${item.index}`} className={selectMode ? "opacity-40 pointer-events-none" : undefined}><ProcessSummary toolCounts={item.toolCounts} roundMessages={item.roundMessages} roundStartIndex={item.roundStartIndex} defaultExpanded={showProgress} caps={caps} onShowSources={onShowSources} /></div>;
        }
        const isUser = item.message.role === "user";
        const bubble = <Bubble message={item.message} caps={caps} onShowSources={onShowSources ? (links) => onShowSources(links, item.index) : undefined} />;
        if (selectMode) {
          const selected = selectedIndices?.has(item.index) ?? false;
          return (
            <div
              key={item.index}
              id={isUser ? `user-msg-${item.index}` : undefined}
              onClick={() => onToggleSelect?.(item.index)}
              className={`relative cursor-pointer rounded -mx-2 px-2 py-1 transition-colors ${selected ? "bg-sol-cyan/10 ring-1 ring-sol-cyan/50" : "hover:bg-sol-base02/40"}`}
            >
              <span className={`absolute right-1 top-1 z-10 inline-flex h-4 w-4 items-center justify-center rounded-full border text-[0.6rem] font-bold ${selected ? "bg-sol-cyan border-sol-cyan text-sol-base03" : "border-sol-base01 text-transparent"}`}>{"✓"}</span>
              <div className="pointer-events-none">{bubble}</div>
            </div>
          );
        }
        return (
          <div key={item.index} id={isUser ? `user-msg-${item.index}` : undefined}>
            {bubble}
          </div>
        );
      })}
      {running && (
        <div className="flex">
          <span className="inline-block w-2.5 h-5 bg-sol-base1" />
        </div>
      )}
    </>
  );

  if (inline) {
    return <div className={`text-xs ${innerClass}`}>{content}</div>;
  }

  const imageScope = createElement(
    ChatImageScope,
    { key: scopeId, scopeId, root: rootEl, allowLocalAttachments },
    <div className={innerClass}>{content}</div>,
  );

  return (
    <div ref={setScroller} className="flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable] px-6 py-4 text-xs">
      {imageScope}
    </div>
  );
}
