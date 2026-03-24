import { useMemo, useRef, useCallback } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";

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
  onSelectChat?: (chatId: string) => void;
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

// Waterfall chart component
function WaterfallChart({ chats, onClickSkill }: { chats: TraceChat[]; onClickSkill?: (chatId: string) => void }) {
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

      {/* Skill rows */}
      <div className="flex">
        {/* Skill labels column */}
        <div style={{ width: LABEL_W }} className="shrink-0">
          {skillGroups.order.map((skill) => {
            const colors = getSkillColors(skill);
            const firstChat = skillGroups.groups[skill][0];
            return (
              <div
                key={skill}
                className="flex items-center min-h-[1.75rem] px-2 gap-1.5 cursor-pointer hover:bg-sol-base02/50 rounded"
                onClick={() => firstChat && onClickSkill?.(firstChat.chat_id)}
              >
                <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors.dot}`} />
                <span className={`text-[0.65rem] font-semibold truncate ${colors.text}`}>{skill}</span>
              </div>
            );
          })}
        </div>

        {/* Timeline area */}
        <div
          ref={timelineRef}
          className="flex-1 relative"
        >
          {/* Skill row bars */}
          {skillGroups.order.map((skill) => {
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

export default function TraceView({ isLoggedIn, selectedTraceId, onSelectChat }: TraceViewProps) {
  // Fetch chats for selected trace
  const { data: traceData } = useSWR<TraceChatsResponse>(
    selectedTraceId && isLoggedIn ? `${API}/api/trace/chats?trace_id=${encodeURIComponent(selectedTraceId)}` : null,
    fetcher,
  );

  const traceChats = traceData?.chats;
  const todoName = traceData?.todo_name;
  const todoStatus = traceData?.todo_status;

  return (
    <div className="h-full overflow-y-auto bg-sol-base03 p-3">
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
          {/* Header + waterfall */}
          <div className="mb-4">
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
            <WaterfallChart chats={traceChats} onClickSkill={onSelectChat} />
          </div>
        </div>
      )}
    </div>
  );
}
