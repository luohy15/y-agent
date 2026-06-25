import { useMemo } from "react";
import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";
import { ListEmpty, ListError, ListLoading } from "./ListStates";

interface CalendarEvent {
  event_id: string;
  summary: string;
  start_time: string;
  end_time?: string;
  description?: string;
  all_day: boolean;
  status: string;
  source?: string;
  todo_id?: string;
}

// Mirror CalendarViewer's per-source color assignment so the agenda dots match the
// week grid.
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

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
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

// HH:MM time-of-day from a stored ISO string (browser-local).
function fmtTimeOfDay(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// Agenda window: from the start of today out 30 days ahead.
const WINDOW_DAYS = 30;

interface ScheduleListProps {
  isLoggedIn: boolean;
  // Open the week view focused on the clicked event's day (App wires this to
  // setCalendarFocus + handleOpenFile("calendar.md")).
  onSelectEvent: (startTime: string) => void;
}

export default function ScheduleList({ isLoggedIn, onSelectEvent }: ScheduleListProps) {
  const today = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  }, []);
  const fromDate = toISODate(today);
  const toDate = toISODate(addDays(today, WINDOW_DAYS));

  const { data: events, isLoading, error } = useSWR<CalendarEvent[]>(
    isLoggedIn ? `${API}/api/calendar/list?from=${fromDate}&to=${toDate}` : null,
    fetcher,
  );

  const sourceColorMap = useMemo(() => {
    const map = new Map<string, string>();
    if (events) {
      for (const ev of events) {
        if (ev.source) getSourceColor(ev.source, map);
      }
    }
    return map;
  }, [events]);

  // Google-Calendar-style Schedule view: group events by their start day, all-day
  // events first then timed sorted by start; days with no events are dropped.
  const scheduleDays = useMemo(() => {
    if (!events) return [];
    const byDay = new Map<string, CalendarEvent[]>();
    for (const ev of events) {
      const key = toISODate(new Date(ev.start_time));
      if (!byDay.has(key)) byDay.set(key, []);
      byDay.get(key)!.push(ev);
    }
    return [...byDay.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([key, evs]) => ({
        date: new Date(key + "T00:00:00"),
        events: [...evs].sort((a, b) => {
          if (a.all_day !== b.all_day) return a.all_day ? -1 : 1;
          return new Date(a.start_time).getTime() - new Date(b.start_time).getTime();
        }),
      }));
  }, [events]);

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="flex-1 overflow-y-auto p-1.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view schedule</p>
        ) : isLoading ? (
          <ListLoading />
        ) : error && !events ? (
          <ListError error={error} />
        ) : scheduleDays.length === 0 ? (
          <ListEmpty label="events" />
        ) : (
          scheduleDays.map(({ date, events: dayEvents }) => (
            <div key={toISODate(date)} className="mb-2">
              <div
                className={`text-[0.6rem] font-medium mb-1 px-1 sticky top-0 bg-sol-base03 py-0.5 z-[5] border-b border-sol-base02 ${
                  isSameDay(date, today) ? "text-sol-blue" : "text-sol-base01"
                }`}
              >
                {date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
              </div>
              <div className="space-y-0">
                {dayEvents.map((ev) => (
                  <button
                    key={ev.event_id}
                    onClick={() => onSelectEvent(ev.start_time)}
                    className="w-full text-left flex items-start gap-1.5 py-0.5 px-1 rounded hover:bg-sol-base02/50 text-[0.7rem] cursor-pointer"
                    title={ev.summary}
                  >
                    <span className="text-sol-base01 tabular-nums shrink-0 w-9">
                      {ev.all_day ? "all" : fmtTimeOfDay(ev.start_time)}
                    </span>
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 mt-1 ${getSourceColor(ev.source, sourceColorMap)}`} />
                    <span className="text-sol-base0 truncate flex-1">{ev.summary}</span>
                  </button>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
