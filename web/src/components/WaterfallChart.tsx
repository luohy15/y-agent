import { useMemo, useRef } from "react";
import { getSkillChartColors } from "./badges";

export interface Segment {
  start_unix: number;
  end_unix: number;
}

export interface TraceChat {
  chat_id: string;
  title: string;
  skill: string;
  backend?: string;
  segments: Segment[];
  messages?: unknown[];
}

export function getSkillColors(skill: string) {
  return getSkillChartColors(skill);
}

// Format time for axis labels
function formatTime(ts: number, showDate = false): string {
  const d = new Date(ts);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (showDate) {
    const date = d.toLocaleDateString([], { month: "short", day: "numeric" });
    return `${date} ${time}`;
  }
  return time;
}

// Check if two timestamps fall on different calendar days
function spansMultipleDays(minTs: number, maxTs: number): boolean {
  const a = new Date(minTs);
  const b = new Date(maxTs);
  return a.getFullYear() !== b.getFullYear() || a.getMonth() !== b.getMonth() || a.getDate() !== b.getDate();
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

export default function WaterfallChart({ chats, onClickSkill }: { chats: TraceChat[]; onClickSkill?: (chatId: string) => void }) {
  const timelineRef = useRef<HTMLDivElement>(null);

  // Group chats by skill+backend, preserving order of first appearance
  const skillGroups = useMemo(() => {
    const groups: Record<string, TraceChat[]> = {};
    const order: string[] = [];
    for (const c of chats) {
      const skill = c.skill || "unknown";
      const backend = c.backend || "";
      const key = backend ? `${skill}:${backend}` : skill;
      if (!groups[key]) {
        groups[key] = [];
        order.push(key);
      }
      groups[key].push(c);
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
  const multiDay = useMemo(() => spansMultipleDays(minTs, maxTs), [minTs, maxTs]);

  const LABEL_W = 96; // px for skill label column

  return (
    <div className="mt-2 relative">
      {/* Date label row (single day) or integrated date+time axis */}
      <div className="flex">
        <div style={{ width: LABEL_W }} className="shrink-0" />
        {!multiDay && (
          <div className="flex-1 relative h-4">
            <span className="text-[0.55rem] text-sol-base01 font-mono">
              {new Date(minTs).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
            </span>
          </div>
        )}
      </div>
      {/* Time axis */}
      <div className="flex">
        <div style={{ width: LABEL_W }} className="shrink-0" />
        <div className={`flex-1 relative ${multiDay ? "h-7" : "h-5"} border-b border-sol-base02`}>
          {/* Full ticks — hidden on small screens */}
          {ticks.map((t) => {
            const pct = ((t - minTs) / range) * 100;
            return (
              <div
                key={t}
                className="absolute text-[0.55rem] text-sol-base01 font-mono -translate-x-1/2 hidden sm:block"
                style={{ left: `${pct}%` }}
              >
                {formatTime(t, multiDay)}
              </div>
            );
          })}
          {/* Mobile: start & end only */}
          <div className="sm:hidden absolute left-0 text-[0.55rem] text-sol-base01 font-mono">
            {formatTime(minTs, multiDay)}
          </div>
          <div className="sm:hidden absolute right-0 text-[0.55rem] text-sol-base01 font-mono">
            {formatTime(maxTs, multiDay)}
          </div>
        </div>
      </div>

      {/* Skill rows */}
      <div className="flex">
        {/* Skill labels column */}
        <div style={{ width: LABEL_W }} className="shrink-0">
          {skillGroups.order.map((key) => {
            const [skill, backend] = key.includes(":") ? [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)] : [key, ""];
            const colors = getSkillColors(skill);
            const firstChat = skillGroups.groups[key][0];
            return (
              <div
                key={key}
                className="flex items-center min-h-[1.75rem] px-2 gap-1 cursor-pointer hover:bg-sol-base02/50 rounded"
                onClick={() => firstChat && onClickSkill?.(firstChat.chat_id)}
              >
                <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors.dot}`} />
                <span className={`text-[0.65rem] font-semibold truncate ${colors.text}`}>{skill}</span>
                {backend && <span className="text-[0.55rem] text-sol-base01 font-mono truncate">{backend}</span>}
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
          {skillGroups.order.map((key) => {
            const skill = key.includes(":") ? key.slice(0, key.indexOf(":")) : key;
            const colors = getSkillColors(skill);
            const skillChats = skillGroups.groups[key];
            return (
              <div key={key} className="relative h-[1.75rem]">
                {/* Grid lines */}
                {ticks.map((t) => {
                  const pct = ((t - minTs) / range) * 100;
                  return (
                    <div
                      key={`${key}-tick-${t}`}
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
                        className={`absolute top-1 h-4 rounded-sm cursor-pointer ${colors.bar}`}
                        style={{ left: `${left}%`, width: `${width}%` }}
                        title={`${c.title || c.chat_id}\n${formatTime(seg.start_unix, multiDay)} → ${formatTime(seg.end_unix, multiDay)}`}
                        onClick={() => onClickSkill?.(c.chat_id)}
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
