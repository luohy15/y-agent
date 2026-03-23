import { useMemo, useRef, useState, useEffect, useCallback } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";
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

// A block of consecutive messages from the same chat
interface TimeBlock {
  chatId: string;
  skill: string;
  title: string;
  messages: Message[];
  startTimestamp: number; // unix ms for sorting
}

// Merge all chat messages into chronological blocks
function buildTimeBlocks(chats: TraceChat[], chatMessages: Map<string, Message[]>): TimeBlock[] {
  // Flatten: each message tagged with its chat info
  const tagged: { chatId: string; skill: string; title: string; message: Message; ts: number }[] = [];

  for (const chat of chats) {
    const msgs = chatMessages.get(chat.chat_id);
    if (!msgs) continue;
    for (const m of msgs) {
      const ts = m.timestamp ? new Date(m.timestamp).getTime() : 0;
      tagged.push({ chatId: chat.chat_id, skill: chat.skill, title: chat.title, message: m, ts });
    }
  }

  // Sort by timestamp (stable sort preserves order for same-ts messages)
  tagged.sort((a, b) => a.ts - b.ts);

  // Group consecutive same-chat messages into blocks
  const blocks: TimeBlock[] = [];
  for (const item of tagged) {
    const last = blocks[blocks.length - 1];
    if (last && last.chatId === item.chatId) {
      last.messages.push(item.message);
    } else {
      blocks.push({
        chatId: item.chatId,
        skill: item.skill,
        title: item.title,
        messages: [item.message],
        startTimestamp: item.ts,
      });
    }
  }

  return blocks;
}

// Waterfall chart component with time ticker
function WaterfallChart({ chats, currentTime, onDragTime }: { chats: TraceChat[]; currentTime: number | null; onDragTime?: (ts: number) => void }) {
  const timelineRef = useRef<HTMLDivElement>(null);

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

  // Ticker position
  const tickerPct = currentTime != null ? ((currentTime - minTs) / range) * 100 : null;

  // Convert X position in timeline area to timestamp
  const xToTime = useCallback((clientX: number) => {
    const el = timelineRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return minTs + pct * range;
  }, [minTs, range]);

  // Drag handling
  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    const ts = xToTime(e.clientX);
    if (ts != null) onDragTime?.(ts);

    const onMove = (ev: PointerEvent) => {
      const t = xToTime(ev.clientX);
      if (t != null) onDragTime?.(t);
    };
    const onUp = () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
  }, [xToTime, onDragTime]);

  const LABEL_W = 96; // px for skill label column

  return (
    <div className="mt-2 relative">
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

      {/* Skill rows with shared timeline area for ticker overlay */}
      <div className="flex">
        {/* Skill labels column */}
        <div style={{ width: LABEL_W }} className="shrink-0">
          {skillGroups.order.map((skill) => {
            const colors = getSkillColors(skill);
            return (
              <div key={skill} className="flex items-center min-h-[1.75rem] px-2 gap-1.5">
                <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors.dot}`} />
                <span className={`text-[0.65rem] font-semibold truncate ${colors.text}`}>{skill}</span>
              </div>
            );
          })}
        </div>

        {/* Timeline area (single div for unified ticker) */}
        <div
          ref={timelineRef}
          className="flex-1 relative cursor-col-resize"
          onPointerDown={handlePointerDown}
        >
          {/* Skill row bars */}
          {skillGroups.order.map((skill, rowIdx) => {
            const colors = getSkillColors(skill);
            const skillChats = skillGroups.groups[skill];
            return (
              <div key={skill} className="relative h-[1.75rem]">
                {/* Grid lines */}
                {ticks.map((t) => {
                  const pct = ((t - minTs) / range) * 100;
                  return (
                    <div
                      key={`${skill}-tick-${t}`}
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
                        className={`absolute top-1 h-4 rounded-sm ${colors.bar}`}
                        style={{ left: `${left}%`, width: `${width}%` }}
                        title={`${c.title || c.chat_id}\n${formatTime(seg.start_unix)} → ${formatTime(seg.end_unix)}`}
                      />
                    );
                  })
                )}
              </div>
            );
          })}

          {/* Single unified ticker line spanning all rows */}
          {tickerPct != null && tickerPct >= 0 && tickerPct <= 100 && (
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-sol-base1 z-10 pointer-events-none rounded-full"
              style={{ left: `${tickerPct}%` }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

interface TraceChatsResponse {
  chats: TraceChat[];
  todo_name: string | null;
  todo_status: string | null;
}

export default function TraceView({ isLoggedIn, selectedTraceId }: TraceViewProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [currentTime, setCurrentTime] = useState<number | null>(null);
  const isDragging = useRef(false);

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

  // Build chronological time blocks
  const timeBlocks = useMemo(() => {
    if (!traceChats) return [];
    return buildTimeBlocks(traceChats, chatMessages);
  }, [traceChats, chatMessages]);

  // Scroll-spy: track timestamp of topmost visible block
  useEffect(() => {
    const container = scrollRef.current;
    if (!container || timeBlocks.length === 0) return;

    const handleScroll = () => {
      if (isDragging.current) return;
      const containerTop = container.getBoundingClientRect().top;
      let bestTs: number | null = null;

      const blockEls = container.querySelectorAll("[data-block-ts]");
      for (const el of blockEls) {
        const rect = el.getBoundingClientRect();
        const relTop = rect.top - containerTop;
        if (relTop <= 60) {
          bestTs = Number(el.getAttribute("data-block-ts"));
        }
      }
      setCurrentTime(bestTs);
    };

    container.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => container.removeEventListener("scroll", handleScroll);
  }, [timeBlocks]);

  // Drag ticker → scroll messages to matching timestamp
  const scrollToTime = useCallback((ts: number) => {
    isDragging.current = true;
    setCurrentTime(ts);

    const container = scrollRef.current;
    if (!container) return;

    // Find the block element with the closest timestamp <= ts
    const blockEls = container.querySelectorAll("[data-block-ts]");
    let bestEl: Element | null = null;
    let bestTs = -Infinity;
    for (const el of blockEls) {
      const blockTs = Number(el.getAttribute("data-block-ts"));
      if (blockTs <= ts && blockTs > bestTs) {
        bestTs = blockTs;
        bestEl = el;
      }
    }
    // If no block <= ts, pick the first one
    if (!bestEl && blockEls.length > 0) bestEl = blockEls[0];

    if (bestEl) {
      const stickyEl = container.querySelector("[data-sticky-header]");
      const stickyHeight = stickyEl ? stickyEl.getBoundingClientRect().height : 0;
      const elTop = bestEl.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
      container.scrollTo({ top: elTop - stickyHeight - 8 });
    }

    // Release drag lock after a short delay to let scroll event fire
    requestAnimationFrame(() => { isDragging.current = false; });
  }, []);

  // Build TOC items from time blocks - one entry per block showing skill + first user message
  const tocItems = useMemo(() => {
    return timeBlocks.map((block, i) => {
      const firstUser = block.messages.find((m) => m.role === "user");
      const text = firstUser ? extractContent(firstUser.content).split("\n")[0].trim() : block.title;
      const label = text.length > 30 ? text.slice(0, 30) + "..." : text;
      return { index: i, skill: block.skill, label, ts: block.startTimestamp };
    });
  }, [timeBlocks]);

  const scrollToBlock = useCallback((ts: number) => {
    const el = scrollRef.current?.querySelector(`[data-block-ts="${ts}"]`);
    if (el) {
      const stickyEl = scrollRef.current?.querySelector("[data-sticky-header]");
      const stickyHeight = stickyEl ? stickyEl.getBoundingClientRect().height : 0;
      const elTop = el.getBoundingClientRect().top - scrollRef.current!.getBoundingClientRect().top + scrollRef.current!.scrollTop;
      scrollRef.current!.scrollTo({ top: elTop - stickyHeight - 8, behavior: "smooth" });
    }
  }, []);

  return (
    <div className="flex h-full min-h-0">
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
            {/* Sticky header + waterfall */}
            <div data-sticky-header className="sticky -top-3 z-10 bg-sol-base03 -mx-3 px-3 pt-3 pb-2 border-b border-sol-base02 mb-4">
              <div className="flex items-center gap-2 mb-1 pt-1">
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
              <button
                onClick={() => navigator.clipboard.writeText(selectedTraceId)}
                className="inline-flex items-center gap-1 text-[0.6rem] text-sol-base01 hover:text-sol-base0 font-mono mb-1 cursor-pointer"
                title="Copy trace ID"
              >
                <svg className="w-2.5 h-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="5" cy="5" r="2.5"/><circle cx="19" cy="12" r="2.5"/><circle cx="5" cy="19" r="2.5"/><line x1="7.5" y1="6" x2="16.5" y2="11"/><line x1="16.5" y1="13" x2="7.5" y2="18"/></svg>
                {selectedTraceId}
              </button>
              <WaterfallChart chats={traceChats} currentTime={currentTime} onDragTime={scrollToTime} />
            </div>

            {/* Messages in chronological order */}
            {timeBlocks.map((block, i) => {
              const colors = getSkillColors(block.skill);
              return (
                <div key={`${block.chatId}-${i}`} data-block-ts={block.startTimestamp} className="mb-4">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors.dot}`} />
                    <span className={`text-[0.7rem] font-semibold ${colors.text}`}>{block.skill}</span>
                  </div>
                  <MessageList messages={block.messages} showProgress={false} inline />
                </div>
              );
            })}
          </div>
        )}
      </div>
      {/* TOC sidebar */}
      {tocItems.length >= 2 && (
        <div className="hidden md:flex flex-col shrink-0 w-8 hover:w-52 transition-all duration-200 overflow-hidden group border-l border-sol-base02">
          {/* Dot indicators (visible when collapsed) */}
          <div className="flex flex-col items-center gap-1.5 py-2 group-hover:hidden">
            {tocItems.map((item) => {
              const colors = getSkillColors(item.skill);
              return (
                <div
                  key={item.index}
                  className={`w-2 h-2 rounded-full ${colors.dot} hover:opacity-80 cursor-pointer shrink-0`}
                  onClick={() => scrollToBlock(item.ts)}
                />
              );
            })}
          </div>
          {/* Expanded list (visible on hover) */}
          <div className="hidden group-hover:flex flex-col overflow-y-auto py-1">
            {tocItems.map((item) => {
              const colors = getSkillColors(item.skill);
              return (
                <button
                  key={item.index}
                  onClick={() => scrollToBlock(item.ts)}
                  className="flex items-center text-left px-2 h-6 shrink-0 text-[0.65rem] font-mono text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 cursor-pointer truncate gap-1.5"
                >
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors.dot}`} />
                  <span className={`shrink-0 ${colors.text}`}>{item.skill}</span>
                  <span className="truncate">{item.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
