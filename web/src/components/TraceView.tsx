import { useMemo, useRef } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";
import TraceList from "./TraceList";
import MessageList, { type Message, extractContent } from "./MessageList";

interface Segment {
  start_unix: number;
  end_unix: number;
}

interface RawMessage {
  role?: string;
  content?: string | { type: string; text?: string }[];
  tool_calls?: { id: string; function?: { name?: string; arguments?: string } }[];
  tool_call_id?: string;
  tool?: string;
  arguments?: Record<string, unknown>;
  timestamp?: string;
}

interface TraceChat {
  chat_id: string;
  title: string;
  skill: string;
  segments: Segment[];
  messages?: RawMessage[];
}

interface TraceViewProps {
  isLoggedIn: boolean;
  selectedTraceId: string | null;
  onSelectTrace: (traceId: string | null) => void;
}

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

// Skill color mapping
const SKILL_COLORS: Record<string, { bg: string; border: string; text: string; dot: string; bar: string }> = {
  "dev-manager": { bg: "bg-sol-blue/10", border: "border-sol-blue/30", text: "text-sol-blue", dot: "bg-sol-blue", bar: "bg-sol-blue/60" },
  "dev": { bg: "bg-sol-green/10", border: "border-sol-green/30", text: "text-sol-green", dot: "bg-sol-green", bar: "bg-sol-green/60" },
  "git": { bg: "bg-sol-yellow/10", border: "border-sol-yellow/30", text: "text-sol-yellow", dot: "bg-sol-yellow", bar: "bg-sol-yellow/60" },
  "default": { bg: "bg-sol-cyan/10", border: "border-sol-cyan/30", text: "text-sol-cyan", dot: "bg-sol-cyan", bar: "bg-sol-cyan/60" },
};

function getSkillColors(skill: string) {
  return SKILL_COLORS[skill] || SKILL_COLORS["default"];
}

// Format time for axis labels
function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Generate time axis ticks between min and max
function generateTicks(minTs: number, maxTs: number): number[] {
  const range = maxTs - minTs;
  if (range <= 0) return [minTs];

  // Pick interval: 5m, 10m, 15m, 30m, 1h, 2h, 4h
  const intervals = [5 * 60000, 10 * 60000, 15 * 60000, 30 * 60000, 60 * 60000, 2 * 60 * 60000, 4 * 60 * 60000];
  let interval = intervals[0];
  for (const iv of intervals) {
    if (range / iv <= 10) { interval = iv; break; }
    interval = iv;
  }

  const first = Math.ceil(minTs / interval) * interval;
  const ticks: number[] = [];
  for (let t = first; t <= maxTs; t += interval) {
    ticks.push(t);
  }
  return ticks;
}

// Convert raw backend messages to MessageList format (same logic as ChatView SSE handler)
function parseRawMessages(rawMessages: RawMessage[]): Message[] {
  const result: Message[] = [];
  // Track pending tool calls by ID for later resolution
  const pendingTools = new Map<string, number>(); // toolCallId -> index in result

  for (const msg of rawMessages) {
    const role = msg.role || "assistant";
    const content = extractContent(msg.content as string);
    const timestamp = msg.timestamp;

    if (role === "user") {
      result.push({ role: "user", content, timestamp });
    } else if (role === "assistant" && msg.tool_calls) {
      if (content.trim()) {
        result.push({ role: "assistant", content, timestamp });
      }
      for (const tc of msg.tool_calls) {
        const func = tc.function || {};
        let toolArgs: Record<string, unknown> = {};
        try { toolArgs = JSON.parse(func.arguments || "{}"); } catch {}
        const idx = result.length;
        result.push({ role: "tool_pending", content: "", toolName: func.name, arguments: toolArgs, toolCallId: tc.id, timestamp });
        pendingTools.set(tc.id, idx);
      }
    } else if (role === "tool") {
      const tcId = msg.tool_call_id;
      const denied = typeof content === "string" && content.startsWith("ERROR: User denied");
      const newRole = denied ? "tool_denied" as const : "tool_result" as const;
      if (tcId && pendingTools.has(tcId)) {
        const idx = pendingTools.get(tcId)!;
        result[idx] = { ...result[idx], role: newRole, content };
        pendingTools.delete(tcId);
      } else {
        result.push({ role: newRole, content, toolName: msg.tool, arguments: msg.arguments, timestamp });
      }
    } else {
      result.push({ role: "assistant", content, timestamp });
    }
  }
  return result;
}

// Waterfall chart component
function WaterfallChart({ chats, traceId, onChatClick }: { chats: TraceChat[]; traceId: string; onChatClick?: (chatId: string) => void }) {
  // Group chats by skill, preserving order of first appearance
  const skillGroups = useMemo(() => {
    const groups: Record<string, TraceChat[]> = {};
    const order: string[] = [];
    for (const c of chats) {
      const skill = c.skill || "unknown";
      if (!groups[skill]) {
        groups[skill] = [];
        order.push(skill);
      }
      groups[skill].push(c);
    }
    return { groups, order };
  }, [chats]);

  // Compute timeline bounds from all segments
  const { minTs, maxTs } = useMemo(() => {
    let min = Infinity, max = -Infinity;
    for (const c of chats) {
      for (const seg of c.segments) {
        if (seg.start_unix) min = Math.min(min, seg.start_unix);
        if (seg.end_unix) max = Math.max(max, seg.end_unix);
      }
    }
    if (!isFinite(min) || !isFinite(max)) return { minTs: 0, maxTs: 1 };
    const pad = Math.max((max - min) * 0.05, 60000); // 5% padding or at least 1 min
    return { minTs: min - pad, maxTs: max + pad };
  }, [chats]);

  const ticks = useMemo(() => generateTicks(minTs, maxTs), [minTs, maxTs]);
  const range = maxTs - minTs || 1;

  const LABEL_W = 96; // px for skill label column

  return (
    <div className="mt-2">
      {/* Time axis */}
      <div className="flex">
        <div style={{ width: LABEL_W }} className="shrink-0" />
        <div className="flex-1 relative h-5 border-b border-sol-base02">
          {ticks.map((t) => {
            const pct = ((t - minTs) / range) * 100;
            return (
              <div
                key={t}
                className="absolute text-[0.55rem] text-sol-base01 font-mono -translate-x-1/2"
                style={{ left: `${pct}%` }}
              >
                {formatTime(t)}
              </div>
            );
          })}
        </div>
      </div>

      {/* Skill rows */}
      {skillGroups.order.map((skill) => {
        const colors = getSkillColors(skill);
        const skillChats = skillGroups.groups[skill];

        return (
          <div key={skill} className="flex items-center min-h-[1.75rem] group">
            {/* Skill label */}
            <div
              style={{ width: LABEL_W }}
              className="shrink-0 flex items-center gap-1.5 px-2"
            >
              <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors.dot}`} />
              <span className={`text-[0.65rem] font-semibold truncate ${colors.text}`}>{skill}</span>
            </div>

            {/* Timeline bar area */}
            <div className="flex-1 relative h-5">
              {/* Grid lines */}
              {ticks.map((t) => {
                const pct = ((t - minTs) / range) * 100;
                return (
                  <div
                    key={t}
                    className="absolute top-0 bottom-0 border-l border-sol-base02/30"
                    style={{ left: `${pct}%` }}
                  />
                );
              })}

              {/* Chat segment bars */}
              {skillChats.flatMap((c) =>
                c.segments.map((seg, i) => {
                  const left = ((seg.start_unix - minTs) / range) * 100;
                  const width = Math.max(((seg.end_unix - seg.start_unix) / range) * 100, 0.5);

                  return (
                    <div
                      key={`${c.chat_id}-${i}`}
                      className={`absolute top-0.5 h-4 rounded-sm ${colors.bar} hover:brightness-125 transition-all cursor-pointer`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                      title={`${c.title || c.chat_id}\n${formatTime(seg.start_unix)} → ${formatTime(seg.end_unix)}`}
                      onClick={() => onChatClick?.(c.chat_id)}
                    />
                  );
                })
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface TraceChatsResponse {
  chats: TraceChat[];
  todo_name: string | null;
  todo_status: string | null;
}

export default function TraceView({ isLoggedIn, selectedTraceId, onSelectTrace }: TraceViewProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Fetch chats for selected trace
  const { data: traceData } = useSWR<TraceChatsResponse>(
    selectedTraceId && isLoggedIn ? `${API}/api/trace/chats?trace_id=${encodeURIComponent(selectedTraceId)}` : null,
    fetcher,
  );

  const traceChats = traceData?.chats;
  const todoName = traceData?.todo_name;
  const todoStatus = traceData?.todo_status;

  // Parse messages for each chat
  const chatMessages = useMemo(() => {
    if (!traceChats) return new Map<string, Message[]>();
    const map = new Map<string, Message[]>();
    for (const chat of traceChats) {
      if (chat.messages && chat.messages.length > 0) {
        map.set(chat.chat_id, parseRawMessages(chat.messages));
      }
    }
    return map;
  }, [traceChats]);

  const scrollToChat = (chatId: string) => {
    const el = scrollRef.current?.querySelector(`#trace-chat-${CSS.escape(chatId)}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="flex h-full min-h-0">
      {/* Left: Trace list (desktop only, mobile uses drawer) */}
      <div className="hidden md:flex w-56 shrink-0 border-r border-sol-base02 bg-sol-base03 flex-col overflow-hidden">
        <TraceList isLoggedIn={isLoggedIn} selectedTraceId={selectedTraceId} onSelectTrace={onSelectTrace} />
      </div>

      {/* Right: Waterfall view + messages */}
      <div ref={scrollRef} className="flex-1 min-w-0 overflow-y-auto bg-sol-base03 p-3">
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
            {/* Header */}
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sol-base1 text-sm font-medium">
                {todoName || selectedTraceId}
              </span>
              {todoStatus && (
                <span className={`text-[0.6rem] px-1 rounded ${
                  todoStatus === "completed" ? "bg-sol-green/20 text-sol-green" :
                  todoStatus === "active" ? "bg-sol-blue/20 text-sol-blue" :
                  "bg-sol-base02 text-sol-base01"
                }`}>
                  {todoStatus}
                </span>
              )}
              {/* Skill badges */}
              <div className="flex flex-wrap gap-0.5">
                {[...new Set(traceChats.map((c) => c.skill).filter(Boolean))].map((s) => (
                  <span key={s} className={`text-[0.6rem] px-1 rounded ${getSkillColors(s).bg} ${getSkillColors(s).text}`}>
                    {s}
                  </span>
                ))}
              </div>
            </div>
            <div className="text-[0.6rem] text-sol-base01 font-mono mb-2">{selectedTraceId}</div>

            {/* Waterfall chart (sticky TOC) */}
            <div className="sticky top-0 z-10 bg-sol-base03 pb-2 border-b border-sol-base02 mb-4">
              <WaterfallChart chats={traceChats} traceId={selectedTraceId} onChatClick={scrollToChat} />
            </div>

            {/* Messages per chat */}
            {traceChats.map((chat) => {
              const messages = chatMessages.get(chat.chat_id);
              if (!messages || messages.length === 0) return null;
              const colors = getSkillColors(chat.skill);
              return (
                <div key={chat.chat_id} id={`trace-chat-${chat.chat_id}`} className="mb-6">
                  {/* Chat header */}
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors.dot}`} />
                    <span className={`text-[0.7rem] font-semibold ${colors.text}`}>{chat.skill}</span>
                    <span className="text-[0.7rem] text-sol-base0 truncate">{chat.title}</span>
                  </div>
                  <MessageList messages={messages} showProgress={true} inline />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
