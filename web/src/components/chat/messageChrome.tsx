import { useEffect, useRef, useState, type ReactNode } from "react";
import { CHAT_BADGE, TRACE_BADGE, topicBadgeClass } from "../badges";

export interface TraceInfo {
  traceId: string;
  fromSkill?: string;
  toSkill?: string;
  fromChatId?: string;
  toChatId?: string;
  cleanContent: string;
}

export function parseTracePrefix(content: string): TraceInfo | null {
  const match = content.match(/^\[trace:(\S+)((?:\s+\w+:\S+)*)\]\n?/);
  if (!match) return null;
  const rest = match[2];
  const get = (key: string): string | undefined => {
    const found = rest.match(new RegExp(`\\s${key}:(\\S+)`));
    return found ? found[1] : undefined;
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

function formatDateTime(timestamp?: string): string {
  if (!timestamp) return "";
  try {
    const dt = new Date(timestamp);
    const date = dt.toLocaleDateString([], { year: "numeric", month: "2-digit", day: "2-digit" });
    const time = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    return `${date} ${time}`;
  } catch {
    return "";
  }
}

async function writeClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
    } finally {
      document.body.removeChild(area);
    }
  }
}

export function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<number | null>(null);
  useEffect(() => () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
  }, []);
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        writeClipboard(text).then(() => {
          setCopied(true);
          if (timerRef.current !== null) window.clearTimeout(timerRef.current);
          timerRef.current = window.setTimeout(() => setCopied(false), 1200);
        });
      }}
      title={copied ? "Copied" : "Copy"}
      aria-label={copied ? "Copied" : "Copy message"}
      className={`inline-flex items-center justify-center rounded border border-sol-base02 bg-sol-base03/80 p-1 text-sol-base01 transition-colors hover:border-sol-blue hover:text-sol-blue focus:opacity-100 ${copied ? "text-sol-green border-sol-green/60" : ""} ${className ?? ""}`}
    >
      {copied ? (
        <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
      ) : (
        <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
      )}
    </button>
  );
}

export function TimestampLine({
  timestamp,
  traceId,
  fromSkill,
  toSkill,
  fromChatId,
  toChatId,
  onSelectChat,
  onSelectTrace,
}: {
  timestamp?: string;
  traceId?: string;
  fromSkill?: string;
  toSkill?: string;
  fromChatId?: string;
  toChatId?: string;
  onSelectChat?: (chatId: string) => void;
  onSelectTrace?: (traceId: string) => void;
}) {
  const formatted = formatDateTime(timestamp);
  const hasAny = formatted || traceId || fromSkill || toSkill || fromChatId || toChatId;
  if (!hasAny) return null;
  const hasFrom = fromSkill || fromChatId;
  const hasTo = toSkill || toChatId;
  const chatClass = (chatId: string, handler?: (chatId: string) => void) => (
    <span
      className={`ml-1 text-[0.6rem] ${CHAT_BADGE}${handler ? " hover:bg-sol-blue/30 cursor-pointer" : ""}`}
      onClick={handler ? () => handler(chatId) : undefined}
    >
      {chatId}
    </span>
  );
  return (
    <div className="text-xs sm:text-[0.65rem] text-sol-base01 mb-1 flex items-center" data-testid="message-timestamp">
      {formatted && <span>{formatted}</span>}
      {traceId && (
        <span
          className={`ml-1.5 text-[0.6rem] ${TRACE_BADGE}${onSelectTrace ? " hover:bg-sol-base01/30 cursor-pointer" : ""}`}
          onClick={onSelectTrace ? () => onSelectTrace(traceId) : undefined}
        >
          #{traceId}
        </span>
      )}
      {fromSkill && <span className={`ml-1.5 text-[0.6rem] ${topicBadgeClass(fromSkill)}`}>{fromSkill}</span>}
      {fromChatId && chatClass(fromChatId, onSelectChat)}
      {hasFrom && hasTo && <span className="ml-1 text-sol-base01">→</span>}
      {toSkill && <span className={`ml-1 text-[0.6rem] ${topicBadgeClass(toSkill)}`}>{toSkill}</span>}
      {toChatId && chatClass(toChatId, onSelectChat)}
    </div>
  );
}

export function nodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  return "";
}
