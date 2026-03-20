import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import useSWRInfinite from "swr/infinite";
import useSWR from "swr";
import { API, authFetch, clearToken, getToken } from "../api";
import MessageList, { type Message, extractContent } from "./MessageList";

interface TraceChat {
  chat_id: string;
  title: string;
  skill: string;
  created_at: string;
  updated_at: string;
}

interface TraceListItem {
  trace_id: string;
  updated_at: string;
}

interface TraceViewProps {
  isLoggedIn: boolean;
  initialTraceId?: string;
}

const PAGE_SIZE = 50;

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

// Extended message with trace_id for filtering
interface TracedMessage extends Message {
  traceId?: string;
}

// Skill color mapping
const SKILL_COLORS: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  "dev-manager": { bg: "bg-sol-blue/10", border: "border-sol-blue/30", text: "text-sol-blue", dot: "bg-sol-blue" },
  "dev": { bg: "bg-sol-green/10", border: "border-sol-green/30", text: "text-sol-green", dot: "bg-sol-green" },
  "git": { bg: "bg-sol-yellow/10", border: "border-sol-yellow/30", text: "text-sol-yellow", dot: "bg-sol-yellow" },
  "default": { bg: "bg-sol-cyan/10", border: "border-sol-cyan/30", text: "text-sol-cyan", dot: "bg-sol-cyan" },
};

function getSkillColors(skill: string) {
  return SKILL_COLORS[skill] || SKILL_COLORS["default"];
}

// Sub-component: load messages for a chat, filtered by trace_id
function ParticipantChat({ chatId, traceId, isLoggedIn }: { chatId: string; traceId: string; isLoggedIn: boolean }) {
  const [messages, setMessages] = useState<TracedMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!isLoggedIn || !chatId) return;
    setMessages([]);
    setLoading(true);

    const token = getToken();
    const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
    const es = new EventSource(`${API}/api/chat/messages?chat_id=${chatId}&last_index=0${tokenParam}`);
    esRef.current = es;

    // Track current trace_id context: user messages carry trace_id,
    // subsequent assistant/tool messages inherit it until next user message
    let currentTraceId: string | undefined;

    const handleMessage = (raw: string) => {
      try {
        const evt = JSON.parse(raw);
        const msg = evt.data || evt;
        const role = msg.role || "assistant";
        const content = extractContent(msg.content);
        const timestamp = msg.timestamp;
        const msgTraceId = msg.trace_id as string | undefined;

        if (role === "user" && msgTraceId) {
          currentTraceId = msgTraceId;
        }

        const effectiveTraceId = role === "user" ? msgTraceId : currentTraceId;

        if (role === "user") {
          setMessages((prev) => [...prev, { role: "user", content, timestamp, traceId: effectiveTraceId }]);
        } else if (role === "assistant" && msg.tool_calls) {
          if (content.trim()) {
            setMessages((prev) => [...prev, { role: "assistant", content, timestamp, traceId: effectiveTraceId }]);
          }
          for (const tc of msg.tool_calls) {
            const func = tc.function || {};
            let toolArgs: Record<string, unknown> = {};
            try { toolArgs = JSON.parse(func.arguments || "{}"); } catch {}
            setMessages((prev) => [...prev, { role: "tool_pending", content: "", toolName: func.name, arguments: toolArgs, toolCallId: tc.id, timestamp, traceId: effectiveTraceId }]);
          }
        } else if (role === "tool") {
          const tcId = msg.tool_call_id;
          const denied = typeof content === "string" && content.startsWith("ERROR: User denied");
          if (tcId) {
            setMessages((prev) => prev.map((m) =>
              m.toolCallId === tcId ? { ...m, role: denied ? "tool_denied" : "tool_result", content } : m
            ));
          } else {
            setMessages((prev) => [...prev, { role: denied ? "tool_denied" : "tool_result", content, toolName: msg.tool, arguments: msg.arguments, timestamp, traceId: effectiveTraceId }]);
          }
        } else {
          setMessages((prev) => [...prev, { role: "assistant", content, timestamp, traceId: effectiveTraceId }]);
        }
      } catch {}
    };

    es.addEventListener("message", (e) => handleMessage(e.data));
    for (const t of ["text", "tool_use", "tool_result"]) {
      es.addEventListener(t, (e) => handleMessage((e as MessageEvent).data));
    }
    es.addEventListener("done", () => {
      setLoading(false);
      es.close();
    });
    es.addEventListener("error", () => {
      setLoading(false);
      es.close();
    });

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [chatId, isLoggedIn]);

  const filteredMessages = useMemo(() => {
    return messages.filter((m) => m.traceId === traceId);
  }, [messages, traceId]);

  return (
    <div className="max-h-[60vh] overflow-y-auto">
      {loading && messages.length === 0 && (
        <p className="text-sol-base01 italic p-2 text-xs">Loading messages...</p>
      )}
      <MessageList messages={filteredMessages} running={loading} showProgress={false} />
    </div>
  );
}

// Waterfall row for a single chat participant
function WaterfallRow({
  chat,
  traceId,
  isExpanded,
  onToggle,
  isLoggedIn,
}: {
  chat: TraceChat;
  traceId: string;
  isExpanded: boolean;
  onToggle: () => void;
  isLoggedIn: boolean;
}) {
  const colors = getSkillColors(chat.skill);

  return (
    <div className="group">
      <div className="flex items-center gap-0 min-h-[2rem]">
        <button
          onClick={onToggle}
          className="w-28 shrink-0 flex items-center gap-1.5 px-2 py-1 text-left hover:bg-sol-base02/50 rounded transition-colors cursor-pointer"
        >
          <div className={`w-2 h-2 rounded-full shrink-0 ${colors.dot}`} />
          <span className={`text-xs font-semibold truncate ${colors.text}`}>{chat.skill || "unknown"}</span>
          <svg
            className={`w-2.5 h-2.5 shrink-0 text-sol-base01 transition-transform ml-auto ${isExpanded ? "rotate-90" : ""}`}
            viewBox="0 0 12 12"
            fill="currentColor"
          >
            <path d="M4 2l4 4-4 4z" />
          </svg>
        </button>
        <div className="flex-1 min-w-0 h-6 relative flex items-center px-1">
          <div className={`h-4 rounded ${colors.bg} border ${colors.border} min-w-[2rem] w-full flex items-center px-2`}>
            <span className="text-[0.6rem] text-sol-base01 font-mono truncate">
              {chat.chat_id.slice(0, 8)}
            </span>
            {chat.title && (
              <span className="text-[0.55rem] text-sol-base01 ml-auto truncate hidden sm:inline" title={chat.title}>
                {chat.title.slice(0, 40)}
              </span>
            )}
          </div>
        </div>
      </div>
      {isExpanded && (
        <div className="ml-28 border-l-2 border-sol-base02 pl-2 mb-2">
          <ParticipantChat chatId={chat.chat_id} traceId={traceId} isLoggedIn={isLoggedIn} />
        </div>
      )}
    </div>
  );
}

export default function TraceView({ isLoggedIn, initialTraceId }: TraceViewProps) {
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(initialTraceId || null);
  const [expandedChats, setExpandedChats] = useState<Set<string>>(new Set());

  // Trace list with infinite scroll
  const getKey = (pageIndex: number, previousPageData: TraceListItem[] | null) => {
    if (!isLoggedIn) return null;
    if (previousPageData && previousPageData.length < PAGE_SIZE) return null;
    return `${API}/api/trace/list?offset=${pageIndex * PAGE_SIZE}&limit=${PAGE_SIZE}`;
  };

  const { data, error, isLoading, size, setSize, isValidating } = useSWRInfinite<TraceListItem[]>(getKey, fetcher);

  const traces = data ? data.flat() : [];
  const isLoadingMore = isLoading || (size > 0 && data && typeof data[size - 1] === "undefined");
  const isEmpty = data?.[0]?.length === 0;
  const isReachingEnd = isEmpty || (data && data[data.length - 1]?.length < PAGE_SIZE);

  const observer = useRef<IntersectionObserver | null>(null);
  const sentinelRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (isValidating) return;
      if (observer.current) observer.current.disconnect();
      observer.current = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && !isReachingEnd) {
          setSize((s) => s + 1);
        }
      });
      if (node) observer.current.observe(node);
    },
    [isValidating, isReachingEnd, setSize],
  );

  // Fetch chats for selected trace
  const { data: traceChats } = useSWR<TraceChat[]>(
    selectedTraceId && isLoggedIn ? `${API}/api/trace/chats?trace_id=${encodeURIComponent(selectedTraceId)}` : null,
    fetcher,
  );

  const toggleChat = (chatId: string) => {
    setExpandedChats((prev) => {
      const next = new Set(prev);
      if (next.has(chatId)) next.delete(chatId);
      else next.add(chatId);
      return next;
    });
  };

  return (
    <div className="flex h-full min-h-0">
      {/* Left: Trace list */}
      <div className="w-48 shrink-0 border-r border-sol-base02 bg-sol-base03 flex flex-col text-xs overflow-hidden">
        <div className="p-2 border-b border-sol-base02 text-sol-base1 font-semibold text-xs">
          Traces
        </div>
        <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
          {!isLoggedIn ? (
            <p className="text-sol-base01 italic p-2">Sign in to view traces</p>
          ) : isLoading ? (
            <p className="text-sol-base01 italic p-2">Loading...</p>
          ) : error ? (
            <p className="text-sol-base01 italic p-2">Error loading traces</p>
          ) : traces.length === 0 ? (
            <p className="text-sol-base01 italic p-2">No traces yet</p>
          ) : (
            <>
              {traces.map((t) => {
                const sel = t.trace_id === selectedTraceId;
                const dt = t.updated_at ? new Date(t.updated_at) : null;
                const date = dt ? dt.toLocaleDateString([], { month: "2-digit", day: "2-digit" }) : "";
                const time = dt ? dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
                return (
                  <div
                    key={t.trace_id}
                    onClick={() => {
                      setSelectedTraceId(sel ? null : t.trace_id);
                      setExpandedChats(new Set());
                    }}
                    className={`px-2 py-1.5 rounded-md cursor-pointer hover:bg-sol-base02 transition-colors ${
                      sel ? "ring-1 ring-sol-blue bg-sol-base02/50" : ""
                    }`}
                  >
                    <div className="truncate text-sol-base0 font-mono text-[0.65rem]">{t.trace_id.slice(0, 16)}</div>
                    <div className="text-[0.6rem] text-sol-base01">{date} {time}</div>
                  </div>
                );
              })}
              {!isReachingEnd && (
                <div ref={sentinelRef} className="py-2 text-center text-sol-base01 italic">
                  {isLoadingMore ? "Loading..." : ""}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Right: Waterfall view */}
      <div className="flex-1 min-w-0 overflow-y-auto bg-sol-base03 p-3">
        {!selectedTraceId ? (
          <div className="flex items-center justify-center h-full text-sol-base01 italic text-sm">
            Select a trace to view details
          </div>
        ) : !traceChats ? (
          <div className="flex items-center justify-center h-full text-sol-base01 italic text-sm">
            Loading...
          </div>
        ) : traceChats.length === 0 ? (
          <div className="flex items-center justify-center h-full text-sol-base01 italic text-sm">
            No chats found for this trace
          </div>
        ) : (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="text-sol-base1 text-xs font-mono">{selectedTraceId}</span>
              {/* Skill badges */}
              <div className="flex flex-wrap gap-0.5">
                {[...new Set(traceChats.map((c) => c.skill).filter(Boolean))].map((s) => (
                  <span key={s} className={`text-[0.6rem] px-1 rounded ${getSkillColors(s).bg} ${getSkillColors(s).text}`}>
                    {s}
                  </span>
                ))}
              </div>
            </div>
            <div className="space-y-0.5">
              {traceChats.map((c) => (
                <WaterfallRow
                  key={c.chat_id}
                  chat={c}
                  traceId={selectedTraceId}
                  isExpanded={expandedChats.has(c.chat_id)}
                  onToggle={() => toggleChat(c.chat_id)}
                  isLoggedIn={isLoggedIn}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
