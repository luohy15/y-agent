import { useState, useCallback, useRef, useMemo } from "react";
import useSWRInfinite from "swr/infinite";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";

interface Segment {
  start_unix: number;
  end_unix: number;
}

interface TraceChat {
  chat_id: string;
  title: string;
  skill: string;
  segments: Segment[];
}

interface TraceListItem {
  trace_id: string;
  updated_at: string;
  todo_name: string | null;
  todo_status: string | null;
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

// Waterfall chart component
function WaterfallChart({ chats, traceId }: { chats: TraceChat[]; traceId: string }) {
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
                      className={`absolute top-0.5 h-4 rounded-sm ${colors.bar} hover:brightness-125 transition-all cursor-default`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                      title={`${c.title || c.chat_id}\n${formatTime(seg.start_unix)} → ${formatTime(seg.end_unix)}`}
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

export default function TraceView({ isLoggedIn, initialTraceId }: TraceViewProps) {
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(initialTraceId || null);

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

  // Find the selected trace item for display
  const selectedTrace = useMemo(() => traces.find((t) => t.trace_id === selectedTraceId), [traces, selectedTraceId]);

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
                const dt = t.updated_at ? new Date(t.updated_at) : null;
                const date = dt ? dt.toLocaleDateString([], { month: "2-digit", day: "2-digit" }) : "";
                const time = dt ? dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
                return (
                  <div
                    key={t.trace_id}
                    onClick={() => setSelectedTraceId(sel ? null : t.trace_id)}
                    className={`px-2 py-1.5 rounded-md cursor-pointer hover:bg-sol-base02 transition-colors ${
                      sel ? "ring-1 ring-sol-blue bg-sol-base02/50" : ""
                    }`}
                  >
                    <div className="truncate text-sol-base0 text-[0.7rem]">
                      {t.todo_name || t.trace_id.slice(0, 16)}
                    </div>
                    <div className="flex items-center gap-1.5 text-[0.6rem] text-sol-base01">
                      <span>{date} {time}</span>
                      {t.todo_status && (
                        <span className={`px-1 rounded ${
                          t.todo_status === "completed" ? "bg-sol-green/20 text-sol-green" :
                          t.todo_status === "active" ? "bg-sol-blue/20 text-sol-blue" :
                          "bg-sol-base02 text-sol-base01"
                        }`}>
                          {t.todo_status}
                        </span>
                      )}
                    </div>
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
            {/* Header */}
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sol-base1 text-sm font-medium">
                {selectedTrace?.todo_name || selectedTraceId}
              </span>
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

            {/* Waterfall chart */}
            <WaterfallChart chats={traceChats} traceId={selectedTraceId} />
          </div>
        )}
      </div>
    </div>
  );
}
