import { useState, useMemo, useEffect } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";

interface CalendarEvent {
  event_id: string;
  summary: string;
  start_time: string;
  end_time?: string;
  description?: string;
  all_day: boolean;
  status: string;
  source?: string;
  todo_id?: number;
  linked_todo_id?: string;
}

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

const SOURCE_COLORS = [
  "bg-sol-blue/80",
  "bg-sol-green/80",
  "bg-sol-cyan/80",
  "bg-sol-magenta/80",
  "bg-sol-violet/80",
  "bg-sol-yellow/80",
  "bg-sol-orange/80",
  "bg-sol-red/80",
];
const DEFAULT_COLOR = "bg-sol-base01";

function getSourceColor(source: string | undefined, map: Map<string, string>): string {
  if (!source) return DEFAULT_COLOR;
  const existing = map.get(source);
  if (existing) return existing;
  const color = SOURCE_COLORS[map.size % SOURCE_COLORS.length];
  map.set(source, color);
  return color;
}

const HOUR_START = 0;
const HOUR_END = 24;
const HOUR_HEIGHT = 48; // px per hour

function getMonday(d: Date): Date {
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  const mon = new Date(d);
  mon.setDate(diff);
  mon.setHours(0, 0, 0, 0);
  return mon;
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function formatWeekLabel(mon: Date): string {
  const sun = addDays(mon, 6);
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  const end = sun.getMonth() === mon.getMonth()
    ? sun.getDate().toString()
    : sun.toLocaleDateString(undefined, opts);
  return `${mon.toLocaleDateString(undefined, opts)} – ${end}, ${mon.getFullYear()}`;
}

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

interface LayoutInfo {
  col: number;
  totalCols: number;
}

function layoutOverlaps(events: { start: number; end: number }[]): LayoutInfo[] {
  const sorted = events.map((e, i) => ({ ...e, idx: i })).sort((a, b) => a.start - b.start || a.end - b.end);
  const result: LayoutInfo[] = new Array(events.length);
  const groups: { start: number; end: number; members: { idx: number; col: number }[] }[] = [];

  for (const ev of sorted) {
    // Find or create a group
    let group = groups.find(g => ev.start < g.end);
    if (!group) {
      group = { start: ev.start, end: ev.end, members: [] };
      groups.push(group);
    }
    group.end = Math.max(group.end, ev.end);
    // Assign column: find first free column
    const usedCols = new Set(group.members.filter(m => events[m.idx] && m.col >= 0).map(m => m.col));
    let col = 0;
    while (usedCols.has(col)) col++;
    group.members.push({ idx: ev.idx, col });
  }

  for (const group of groups) {
    const totalCols = Math.max(...group.members.map(m => m.col)) + 1;
    for (const m of group.members) {
      result[m.idx] = { col: m.col, totalCols };
    }
  }
  return result;
}

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const STORAGE_KEY = "calendarViewerDate";

interface CalendarViewerProps {
  onOpenFile?: (path: string) => void;
}

export default function CalendarViewer({ onOpenFile }: CalendarViewerProps) {
  const [selectedDate, setSelectedDate] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? new Date(saved + "T00:00:00") : new Date();
  });
  const weekStart = useMemo(() => getMonday(selectedDate), [selectedDate.getTime()]);
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);

  const jumpTo = (d: Date) => {
    setSelectedDate(d);
    localStorage.setItem(STORAGE_KEY, toISODate(d));
  };

  const weekEnd = addDays(weekStart, 7);
  const startISO = weekStart.toISOString();
  const endISO = weekEnd.toISOString();

  const { data: events, isLoading, error } = useSWR<CalendarEvent[]>(
    `${API}/api/calendar/list?start=${encodeURIComponent(startISO)}&end=${encodeURIComponent(endISO)}`,
    fetcher,
  );

  const days = useMemo(() => {
    return Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
  }, [weekStart.getTime()]);

  const { allDayByDay, timedByDay } = useMemo(() => {
    const allDay: Record<number, CalendarEvent[]> = {};
    const timed: Record<number, CalendarEvent[]> = {};
    for (let i = 0; i < 7; i++) { allDay[i] = []; timed[i] = []; }
    if (!events) return { allDayByDay: allDay, timedByDay: timed };
    for (const ev of events) {
      if (ev.all_day) {
        const start = new Date(ev.start_time);
        for (let i = 0; i < 7; i++) {
          if (isSameDay(start, days[i])) { allDay[i].push(ev); break; }
        }
      } else {
        const evStart = new Date(ev.start_time);
        const evEnd = ev.end_time ? new Date(ev.end_time) : new Date(evStart.getTime() + 60 * 60 * 1000);
        for (let i = 0; i < 7; i++) {
          const dayStart = new Date(days[i]);
          dayStart.setHours(0, 0, 0, 0);
          const dayEnd = new Date(days[i]);
          dayEnd.setHours(24, 0, 0, 0);
          // Event overlaps this day if it starts before day ends and ends after day starts
          if (evStart < dayEnd && evEnd > dayStart) {
            timed[i].push(ev);
          }
        }
      }
    }
    return { allDayByDay: allDay, timedByDay: timed };
  }, [events, days]);

  const sourceColorMap = useMemo(() => {
    const map = new Map<string, string>();
    if (events) {
      for (const ev of events) {
        if (ev.source) getSourceColor(ev.source, map);
      }
    }
    return map;
  }, [events]);

  const today = new Date();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelectedEvent(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <div className="h-full flex flex-col bg-sol-base03 text-xs">
      {/* Navigation */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-sol-base02 shrink-0">
        <button
          onClick={() => jumpTo(addDays(selectedDate, -7))}
          className="px-2 py-0.5 rounded bg-sol-base02 text-sol-base0 hover:text-sol-base1 cursor-pointer"
        >&lt; Prev</button>
        <button
          onClick={() => jumpTo(new Date())}
          className="px-2 py-0.5 rounded bg-sol-base02 text-sol-base0 hover:text-sol-base1 cursor-pointer"
        >Today</button>
        <button
          onClick={() => jumpTo(addDays(selectedDate, 7))}
          className="px-2 py-0.5 rounded bg-sol-base02 text-sol-base0 hover:text-sol-base1 cursor-pointer"
        >Next &gt;</button>
        <input
          type="date"
          value={toISODate(selectedDate)}
          onChange={(e) => {
            if (e.target.value) jumpTo(new Date(e.target.value + "T00:00:00"));
          }}
          className="px-2 py-0.5 rounded bg-sol-base02 text-sol-base0 border border-sol-base01/30 text-xs cursor-pointer ml-1"
        />
        <span className="text-sol-base1 text-sm font-medium ml-2">{formatWeekLabel(weekStart)}</span>
      </div>

      {isLoading ? (
        <p className="text-sol-base01 italic p-3">Loading...</p>
      ) : error ? (
        <p className="text-sol-red p-3">Error loading events</p>
      ) : (
        <div className="flex-1 min-h-0 overflow-auto" onClick={() => setSelectedEvent(null)}>
          {/* Event detail popover */}
          {selectedEvent && (
            <div className="sticky top-0 z-20 bg-sol-base02 border-b border-sol-base01/30 px-3 py-2" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sol-base1 text-sm font-medium">{selectedEvent.summary}</div>
                  <div className="text-sol-base01 mt-0.5">
                    {new Date(selectedEvent.start_time).toLocaleString()}
                    {selectedEvent.end_time && ` – ${new Date(selectedEvent.end_time).toLocaleString()}`}
                  </div>
                  {selectedEvent.description && (
                    <p className="text-sol-base0 mt-1 whitespace-pre-wrap">{selectedEvent.description}</p>
                  )}
                  {selectedEvent.source && (
                    <span className="text-sol-cyan mt-0.5 inline-block">Source: {selectedEvent.source}</span>
                  )}
                  {selectedEvent.linked_todo_id && (
                    <span
                      className="text-sol-green mt-0.5 inline-block ml-2 cursor-pointer hover:underline"
                      onClick={() => {
                        localStorage.setItem("todoExpandId", selectedEvent.linked_todo_id!);
                        onOpenFile?.("todo.md");
                      }}
                    >Todo: #{selectedEvent.linked_todo_id}</span>
                  )}
                </div>
                <button
                  onClick={() => setSelectedEvent(null)}
                  className="text-sol-base01 hover:text-sol-base1 cursor-pointer ml-2 text-sm"
                >&times;</button>
              </div>
            </div>
          )}

          <div className="grid grid-cols-[50px_repeat(7,1fr)]">
            {/* Day headers */}
            <div className="border-b border-r border-sol-base02 sticky top-0 z-10 bg-sol-base03" />
            {days.map((d, i) => (
              <div
                key={i}
                className={`text-center py-1 border-b border-r border-sol-base02 sticky top-0 z-10 bg-sol-base03 ${
                  isSameDay(d, selectedDate) ? "text-sol-green font-bold" : isSameDay(d, today) ? "text-sol-blue font-bold" : "text-sol-base0"
                }`}
              >
                <div>{DAY_LABELS[i]} <span className="text-sm">{d.getDate()}</span></div>
                {allDayByDay[i].map((ev) => (
                  <div
                    key={ev.event_id}
                    onClick={(e) => { e.stopPropagation(); setSelectedEvent(ev); }}
                    className={`px-1 py-0.5 rounded text-sol-base03 truncate cursor-pointer mb-0.5 border-l-0 text-left ${
                      getSourceColor(ev.source, sourceColorMap)
                    }`}
                  >
                    {ev.summary}
                  </div>
                ))}
              </div>
            ))}

            {/* Time grid */}
            <div className="col-span-8">
              <div className="grid grid-cols-[50px_repeat(7,1fr)]" style={{ height: (HOUR_END - HOUR_START) * HOUR_HEIGHT }}>
                {/* Hour labels */}
                <div className="relative border-r border-sol-base02">
                  {Array.from({ length: HOUR_END - HOUR_START }, (_, i) => (
                    <div
                      key={i}
                      className="absolute w-full text-right pr-1 text-sol-base01 border-t border-sol-base02"
                      style={{ top: i * HOUR_HEIGHT, height: HOUR_HEIGHT }}
                    >
                      {(HOUR_START + i).toString().padStart(2, "0")}:00
                    </div>
                  ))}
                </div>

                {/* Day columns */}
                {days.map((_, dayIdx) => (
                  <div key={dayIdx} className="relative border-r border-sol-base02">
                    {/* Hour grid lines */}
                    {Array.from({ length: HOUR_END - HOUR_START }, (_, i) => (
                      <div
                        key={i}
                        className="absolute w-full border-t border-sol-base02"
                        style={{ top: i * HOUR_HEIGHT, height: HOUR_HEIGHT }}
                      />
                    ))}
                    {/* Events */}
                    {(() => {
                      const evData = timedByDay[dayIdx].map((ev) => {
                        const evStart = new Date(ev.start_time);
                        const evEnd = ev.end_time ? new Date(ev.end_time) : new Date(evStart.getTime() + 60 * 60 * 1000);
                        const dayStart = new Date(days[dayIdx]);
                        dayStart.setHours(0, 0, 0, 0);
                        const dayEnd = new Date(days[dayIdx]);
                        dayEnd.setHours(24, 0, 0, 0);
                        const clippedStart = evStart < dayStart ? dayStart : evStart;
                        const clippedEnd = evEnd > dayEnd ? dayEnd : evEnd;
                        const startHour = clippedStart.getHours() + clippedStart.getMinutes() / 60;
                        const endHour = clippedEnd.getHours() + clippedEnd.getMinutes() / 60 || 24;
                        return { ev, evStart, evEnd, clippedStart, clippedEnd, startHour, endHour };
                      });
                      const layout = layoutOverlaps(evData.map(d => ({ start: d.startHour, end: d.endHour })));
                      return evData.map((d, idx) => {
                        const { ev, evStart, evEnd, clippedStart, clippedEnd, startHour, endHour } = d;
                        const { col, totalCols } = layout[idx];
                        const top = Math.max(0, (startHour - HOUR_START)) * HOUR_HEIGHT;
                        const height = Math.max(HOUR_HEIGHT / 4, (endHour - startHour) * HOUR_HEIGHT - 4);
                        const gap = 2;
                        const widthPct = (100 - gap * totalCols) / totalCols;
                        const leftPct = col * (widthPct + gap);
                        return (
                          <div
                            key={`${ev.event_id}-${dayIdx}`}
                            onClick={(e) => { e.stopPropagation(); setSelectedEvent(ev); }}
                            className={`absolute rounded px-1 py-0.5 text-sol-base03 overflow-hidden cursor-pointer ${
                              getSourceColor(ev.source, sourceColorMap)
                            }`}
                            style={{ top, height, left: `${leftPct}%`, width: `${widthPct}%` }}
                            title={ev.summary}
                        >
                          {(clippedEnd.getTime() - clippedStart.getTime()) < 60 * 60 * 1000 ? (
                            <div className="truncate font-medium">
                              {ev.summary} <span className="font-normal text-sol-base03/70">{`${String(evStart.getHours()).padStart(2, "0")}:${String(evStart.getMinutes()).padStart(2, "0")}`}</span>
                            </div>
                          ) : (
                            <>
                              <div className="truncate font-medium">{ev.summary}</div>
                              <div className="truncate text-sol-base03/70">
                                {`${String(evStart.getHours()).padStart(2, "0")}:${String(evStart.getMinutes()).padStart(2, "0")}–${String(evEnd.getHours()).padStart(2, "0")}:${String(evEnd.getMinutes()).padStart(2, "0")}`}
                              </div>
                            </>
                          )}
                          </div>
                        );
                      });
                    })()}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
