import { useState, useCallback, useRef, useEffect } from "react";
import useSWRInfinite from "swr/infinite";
import { API, authFetch, clearToken, getToken } from "../api";
import MessageList, { type Message, extractContent } from "./MessageList";

interface TraceParticipant {
  chat_id: string;
  skill: string;
  work_dir?: string;
  message_ids?: string[];
}

interface TraceSummary {
  trace_id: string;
  participants: TraceParticipant[];
  created_at?: string;
  updated_at?: string;
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

// Extended message with original ID for range filtering
interface TracedMessage extends Message {
  msgId?: string;
}

// Sub-component: expandable chat messages for a participant
function ParticipantChat({ chatId, messageIds, isLoggedIn }: { chatId: string; messageIds?: string[]; isLoggedIn: boolean }) {
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

    const handleMessage = (raw: string) => {
      try {
        const evt = JSON.parse(raw);
        const msg = evt.data || evt;
        const role = msg.role || "assistant";
        const content = extractContent(msg.content);
        const timestamp = msg.timestamp;
        const msgId = msg.id as string | undefined;

        if (role === "user") {
          setMessages((prev) => [...prev, { role: "user", content, timestamp, msgId }]);
        } else if (role === "assistant" && msg.tool_calls) {
          if (content.trim()) {
            setMessages((prev) => [...prev, { role: "assistant", content, timestamp, msgId }]);
          }
          for (const tc of msg.tool_calls) {
            const func = tc.function || {};
            let toolArgs: Record<string, unknown> = {};
            try { toolArgs = JSON.parse(func.arguments || "{}"); } catch {}
            setMessages((prev) => [...prev, { role: "tool_pending", content: "", toolName: func.name, arguments: toolArgs, toolCallId: tc.id, timestamp, msgId }]);
          }
        } else if (role === "tool") {
          const tcId = msg.tool_call_id;
          const denied = typeof content === "string" && content.startsWith("ERROR: User denied");
          if (tcId) {
            setMessages((prev) => prev.map((m) =>
              m.toolCallId === tcId ? { ...m, role: denied ? "tool_denied" : "tool_result", content } : m
            ));
          } else {
            setMessages((prev) => [...prev, { role: denied ? "tool_denied" : "tool_result", content, toolName: msg.tool, arguments: msg.arguments, timestamp, msgId }]);
          }
        } else {
          setMessages((prev) => [...prev, { role: "assistant", content, timestamp, msgId }]);
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

  // Filter messages by message_ids range
  const filteredMessages = (() => {
    if (!messageIds || messageIds.length === 0) return messages;
    const startId = messageIds[0];
    const endId = messageIds.length > 1 ? messageIds[1] : undefined;

    // Find start index: first message with matching msgId
    let startIdx = messages.findIndex((m) => m.msgId === startId);
    if (startIdx < 0) startIdx = 0;

    // Find end index: last message with matching msgId (inclusive)
    let endIdx = messages.length;
    if (endId) {
      const found = messages.findIndex((m) => m.msgId === endId);
      if (found >= 0) endIdx = found + 1;
    }

    return messages.slice(startIdx, endIdx);
  })();

  return (
    <div className="max-h-[60vh] overflow-y-auto">
      {loading && messages.length === 0 && (
        <p className="text-sol-base01 italic p-2 text-xs">Loading messages...</p>
      )}
      <MessageList messages={filteredMessages} running={loading} showProgress={false} />
    </div>
  );
}

// Skill color mapping
const SKILL_COLORS: Record<string, string> = {
  "dev-manager": "text-sol-blue",
  "dev": "text-sol-green",
  "git": "text-sol-yellow",
  "default": "text-sol-cyan",
};

function getSkillColor(skill: string): string {
  return SKILL_COLORS[skill] || SKILL_COLORS["default"];
}

export default function TraceView({ isLoggedIn, initialTraceId }: TraceViewProps) {
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(initialTraceId || null);
  const [expandedChats, setExpandedChats] = useState<Set<string>>(new Set());
  const [directTrace, setDirectTrace] = useState<TraceSummary | null>(null);

  // Fetch trace directly when initialTraceId is provided
  useEffect(() => {
    if (!initialTraceId || !isLoggedIn) return;
    authFetch(`${API}/api/trace?trace_id=${encodeURIComponent(initialTraceId)}`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data) setDirectTrace(data); })
      .catch(() => {});
  }, [initialTraceId, isLoggedIn]);

  // Trace list with infinite scroll
  const getKey = (pageIndex: number, previousPageData: TraceSummary[] | null) => {
    if (!isLoggedIn) return null;
    if (previousPageData && previousPageData.length < PAGE_SIZE) return null;
    return `${API}/api/trace/list?offset=${pageIndex * PAGE_SIZE}&limit=${PAGE_SIZE}`;
  };

  const { data, error, isLoading, size, setSize, isValidating } = useSWRInfinite<TraceSummary[]>(getKey, fetcher);

  const listTraces = data ? data.flat() : [];
  // Merge directTrace if it's not already in the paginated list
  const traces = directTrace && !listTraces.some((t) => t.trace_id === directTrace.trace_id)
    ? [directTrace, ...listTraces]
    : listTraces;
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

  const selectedTrace = traces.find((t) => t.trace_id === selectedTraceId);

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
      <div className="w-56 shrink-0 border-r border-sol-base02 bg-sol-base03 flex flex-col text-xs overflow-hidden">
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
                const dt = t.updated_at || t.created_at ? new Date(t.updated_at || t.created_at!) : null;
                const date = dt ? dt.toLocaleDateString([], { year: "numeric", month: "2-digit", day: "2-digit" }) : "";
                const time = dt ? dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
                const skills = t.participants.map((p) => p.skill).join(" → ");
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
                    <div className="truncate text-sol-base0">{skills || t.trace_id}</div>
                    <div className="text-[0.6rem] text-sol-base01 mt-0.5">{date} {time}</div>
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

      {/* Right: Timeline detail */}
      <div className="flex-1 min-w-0 overflow-y-auto bg-sol-base03 p-3">
        {!selectedTrace ? (
          <div className="flex items-center justify-center h-full text-sol-base01 italic text-sm">
            Select a trace to view details
          </div>
        ) : (
          <div className="space-y-2">
            <div className="text-sol-base1 text-xs font-mono mb-3">
              Trace: {selectedTrace.trace_id.slice(0, 12)}...
            </div>
            {/* Timeline */}
            <div className="relative pl-4 border-l-2 border-sol-base02 space-y-3">
              {selectedTrace.participants.map((p, i) => {
                const isExpanded = expandedChats.has(p.chat_id);
                return (
                  <div key={p.chat_id} className="relative">
                    {/* Timeline dot */}
                    <div className={`absolute -left-[1.3rem] top-1.5 w-2.5 h-2.5 rounded-full border-2 border-sol-base03 ${getSkillColor(p.skill).replace("text-", "bg-")}`} />
                    {/* Participant card */}
                    <div className="bg-sol-base02/50 rounded-lg overflow-hidden">
                      <button
                        onClick={() => toggleChat(p.chat_id)}
                        className="w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-sol-base02 transition-colors cursor-pointer"
                      >
                        <svg
                          className={`w-3 h-3 shrink-0 text-sol-base01 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                          viewBox="0 0 12 12"
                          fill="currentColor"
                        >
                          <path d="M4 2l4 4-4 4z" />
                        </svg>
                        <span className={`text-xs font-semibold ${getSkillColor(p.skill)}`}>
                          {p.skill}
                        </span>
                        <span className="text-[0.6rem] text-sol-base01 font-mono truncate">
                          {p.chat_id.slice(0, 10)}
                        </span>
                        {p.work_dir && (
                          <span className="text-[0.6rem] text-sol-base01 truncate ml-auto" title={p.work_dir}>
                            {p.work_dir}
                          </span>
                        )}
                        <span className="text-[0.55rem] text-sol-base01 ml-auto shrink-0">
                          #{i + 1}
                        </span>
                      </button>
                      {isExpanded && (
                        <div className="border-t border-sol-base02 px-1">
                          <ParticipantChat chatId={p.chat_id} messageIds={p.message_ids} isLoggedIn={isLoggedIn} />
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
