import { useState, useMemo, useEffect, useRef } from "react";
import useSWR from "swr";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { ListError, ListLoading } from "./ListStates";

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
const SNAP_MIN = 15; // drag-resize snap increment (minutes)

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

// Format a Date as a `datetime-local` value (YYYY-MM-DDTHH:MM) in browser-local components.
function fmtLocal(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// Prefill a `datetime-local` input from a stored UTC ISO string.
function toDatetimeLocal(iso: string): string {
  return fmtLocal(new Date(iso));
}

interface EventForm {
  summary: string;
  start: string; // datetime-local
  end: string; // datetime-local or ""
  description: string;
  all_day: boolean;
  todo_id: string;
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
  const [mode, setMode] = useState<"read" | "edit" | "create">("read");
  const [form, setForm] = useState<EventForm | null>(null);
  const [saving, setSaving] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Live drag preview state (null when not dragging). `key` encodes the event +
  // day column so multi-instance events stay isolated. `mode` is the gesture:
  // top/bottom border resize, or whole-event move.
  const [dragState, setDragState] = useState<
    { key: string; mode: "top" | "bottom" | "move"; newStartMs: number; newEndMs: number } | null
  >(null);
  // Set true on a drag pointerup that actually moved, so the synthetic click that
  // follows is suppressed (a plain click leaves it unset and still opens read).
  const justDraggedRef = useRef(false);

  const jumpTo = (d: Date) => {
    setSelectedDate(d);
    const currentWeekStart = getMonday(new Date());
    const targetWeekStart = getMonday(d);
    if (currentWeekStart.getTime() === targetWeekStart.getTime()) {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, toISODate(d));
    }
  };

  const fromDate = toISODate(weekStart);
  const toDate = toISODate(addDays(weekStart, 6));

  const { data: events, isLoading, error, mutate } = useSWR<CalendarEvent[]>(
    `${API}/api/calendar/list?from=${fromDate}&to=${toDate}`,
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
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const tick = () => setNow(new Date());
    const id = setInterval(tick, 60 * 1000);
    return () => clearInterval(id);
  }, []);

  // Find which day column index today falls on (if in current week)
  const todayColIdx = days.findIndex((d) => isSameDay(d, now));
  const nowTop = todayColIdx >= 0
    ? ((now.getHours() + now.getMinutes() / 60) - HOUR_START) * HOUR_HEIGHT
    : null;

  const hasScrolled = useRef(false);
  useEffect(() => {
    if (!isLoading && scrollRef.current && todayColIdx >= 0 && !hasScrolled.current) {
      hasScrolled.current = true;
      const currentHour = new Date().getHours();
      scrollRef.current.scrollTop = Math.max(0, (currentHour - 1) * HOUR_HEIGHT);
    }
  }, [isLoading, todayColIdx]);

  const closePopover = () => {
    setSelectedEvent(null);
    setForm(null);
    setMode("read");
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePopover();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const openCreate = (start: Date) => {
    const end = new Date(start.getTime() + 60 * 60 * 1000);
    setSelectedEvent(null);
    setForm({
      summary: "",
      start: fmtLocal(start),
      end: fmtLocal(end),
      description: "",
      all_day: false,
      todo_id: "",
    });
    setMode("create");
  };

  const openNewDefault = () => {
    const start = new Date();
    start.setMinutes(0, 0, 0);
    start.setHours(start.getHours() + 1);
    openCreate(start);
  };

  const openRead = (ev: CalendarEvent) => {
    setSelectedEvent(ev);
    setForm(null);
    setMode("read");
  };

  const openEdit = (ev: CalendarEvent) => {
    setSelectedEvent(ev);
    setForm({
      summary: ev.summary,
      start: ev.start_time ? toDatetimeLocal(ev.start_time) : "",
      end: ev.end_time ? toDatetimeLocal(ev.end_time) : "",
      description: ev.description || "",
      all_day: ev.all_day,
      todo_id: ev.todo_id || "",
    });
    setMode("edit");
  };

  const saveCreate = async () => {
    if (!form || !form.summary.trim() || !form.start) return;
    const body: Record<string, unknown> = {
      summary: form.summary.trim(),
      start: form.start,
      description: form.description,
      all_day: form.all_day,
    };
    if (form.end) body.end = form.end;
    if (form.todo_id.trim()) body.todo_id = form.todo_id.trim();
    setSaving(true);
    const res = await authFetch(`${API}/api/calendar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setSaving(false);
    if (res.ok) {
      await mutate();
      closePopover();
    }
  };

  const saveEdit = async () => {
    if (!form || !selectedEvent || !form.summary.trim() || !form.start) return;
    const ev = selectedEvent;
    const fields: Record<string, unknown> = { event_id: ev.event_id };
    if (form.summary.trim() !== ev.summary) fields.summary = form.summary.trim();
    if (form.start !== (ev.start_time ? toDatetimeLocal(ev.start_time) : "")) {
      fields.start_time = form.start;
    }
    // Only send a non-empty end; clearing end via /update is not supported.
    const origEnd = ev.end_time ? toDatetimeLocal(ev.end_time) : "";
    if (form.end && form.end !== origEnd) fields.end_time = form.end;
    if (form.description !== (ev.description || "")) fields.description = form.description;
    if (form.todo_id.trim() !== (ev.todo_id || "")) fields.todo_id = form.todo_id.trim();
    if (Object.keys(fields).length <= 1) {
      closePopover();
      return;
    }
    setSaving(true);
    const res = await authFetch(`${API}/api/calendar/update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
    setSaving(false);
    if (res.ok) {
      await mutate();
      closePopover();
    }
  };

  // Persist a resized edge. Sends only the changed field (start_time / end_time),
  // formatted the same way saveEdit does, then revalidates via SWR.
  const persistResize = async (ev: CalendarEvent, edge: "top" | "bottom", startMs: number, endMs: number) => {
    const fields: Record<string, unknown> = { event_id: ev.event_id };
    if (edge === "top") fields.start_time = fmtLocal(new Date(startMs));
    else fields.end_time = fmtLocal(new Date(endMs));
    const res = await authFetch(`${API}/api/calendar/update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
    if (res.ok) await mutate();
  };

  // Begin a top/bottom border drag-resize. Delta-based: anchor on pointerdown
  // clientY, snap to SNAP_MIN, clamp to a 15-min min duration / no edge crossing.
  const startResize = (
    e: React.PointerEvent,
    ev: CalendarEvent,
    key: string,
    edge: "top" | "bottom",
    origStartMs: number,
    origEndMs: number,
  ) => {
    e.stopPropagation();
    e.preventDefault();
    const anchorY = e.clientY;
    let curStartMs = origStartMs;
    let curEndMs = origEndMs;
    const snapMs = SNAP_MIN * 60000;

    const onMove = (me: PointerEvent) => {
      const deltaMin = Math.round((((me.clientY - anchorY) / HOUR_HEIGHT) * 60) / SNAP_MIN) * SNAP_MIN;
      if (edge === "top") {
        const maxStart = origEndMs - snapMs;
        curStartMs = Math.min(origStartMs + deltaMin * 60000, maxStart);
        setDragState({ key, mode: edge, newStartMs: curStartMs, newEndMs: origEndMs });
      } else {
        const minEnd = origStartMs + snapMs;
        curEndMs = Math.max(origEndMs + deltaMin * 60000, minEnd);
        setDragState({ key, mode: edge, newStartMs: origStartMs, newEndMs: curEndMs });
      }
    };

    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      justDraggedRef.current = true;
      setDragState(null);
      const changed = edge === "top" ? curStartMs !== origStartMs : curEndMs !== origEndMs;
      if (changed) persistResize(ev, edge, curStartMs, curEndMs);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  // Persist a moved event. Sends both start_time and end_time (duration is
  // preserved), formatted like saveEdit, then revalidates via SWR.
  const persistMove = async (ev: CalendarEvent, startMs: number, endMs: number) => {
    const res = await authFetch(`${API}/api/calendar/update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_id: ev.event_id,
        start_time: fmtLocal(new Date(startMs)),
        end_time: fmtLocal(new Date(endMs)),
      }),
    });
    if (res.ok) await mutate();
  };

  // Begin a whole-event body drag-move. Delta-based and duration-preserving:
  // shift both bounds by the same snapped delta, clamped to keep the block inside
  // its day column (no cross-midnight). A plain click (no snapped movement) is
  // left to bubble through to openRead.
  const startMove = (
    e: React.PointerEvent,
    ev: CalendarEvent,
    key: string,
    origStartMs: number,
    origEndMs: number,
    dayStartMs: number,
    dayEndMs: number,
  ) => {
    e.preventDefault();
    const anchorY = e.clientY;
    let curStartMs = origStartMs;
    let curEndMs = origEndMs;
    let moved = false;
    const minDelta = dayStartMs - origStartMs;
    const maxDelta = dayEndMs - origEndMs;

    const onMove = (me: PointerEvent) => {
      const deltaMin = Math.round((((me.clientY - anchorY) / HOUR_HEIGHT) * 60) / SNAP_MIN) * SNAP_MIN;
      // Clamp the delta (not each bound) so the block stays inside the day and
      // keeps its duration.
      const deltaMs = Math.min(Math.max(deltaMin * 60000, minDelta), maxDelta);
      curStartMs = origStartMs + deltaMs;
      curEndMs = origEndMs + deltaMs;
      if (deltaMs !== 0) moved = true;
      setDragState({ key, mode: "move", newStartMs: curStartMs, newEndMs: curEndMs });
    };

    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      setDragState(null);
      if (moved) {
        justDraggedRef.current = true;
        persistMove(ev, curStartMs, curEndMs);
      }
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const deleteEvent = async () => {
    if (!selectedEvent) return;
    if (!window.confirm(`Delete "${selectedEvent.summary}"?`)) return;
    setSaving(true);
    const res = await authFetch(`${API}/api/calendar/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_id: selectedEvent.event_id }),
    });
    setSaving(false);
    if (res.ok) {
      await mutate();
      closePopover();
    }
  };

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
        <button
          onClick={openNewDefault}
          className="px-2 py-0.5 rounded bg-sol-blue/80 text-sol-base03 hover:bg-sol-blue cursor-pointer ml-auto"
        >+ New</button>
      </div>

      {isLoading ? (
        <ListLoading className="p-3" />
      ) : error ? (
        <ListError error={error} className="p-3" />
      ) : (
        <div className="flex-1 min-h-0 relative">
          {(!events || events.length === 0) && (
            <div className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none">
              <span className="px-2 py-1 rounded bg-sol-base02/80 text-sol-base01">No events this week</span>
            </div>
          )}
          <div ref={scrollRef} className="h-full overflow-auto" onClick={closePopover}>
          {/* Event detail popover (read mode) */}
          {selectedEvent && mode === "read" && (
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
                  {selectedEvent.todo_id && (
                    <span
                      className="text-sol-green mt-0.5 inline-block ml-2 cursor-pointer hover:underline"
                      onClick={() => {
                        localStorage.setItem("todoExpandId", selectedEvent.todo_id!);
                        onOpenFile?.("todo.md");
                      }}
                    >Todo: #{selectedEvent.todo_id}</span>
                  )}
                </div>
                <div className="flex items-center gap-2 ml-2 shrink-0">
                  <button
                    onClick={() => openEdit(selectedEvent)}
                    className="px-2 py-0.5 rounded bg-sol-base01/30 text-sol-base0 hover:text-sol-base1 cursor-pointer"
                  >Edit</button>
                  <button
                    onClick={deleteEvent}
                    disabled={saving}
                    className="px-2 py-0.5 rounded bg-sol-red/70 text-sol-base03 hover:bg-sol-red cursor-pointer disabled:opacity-50"
                  >Delete</button>
                  <button
                    onClick={closePopover}
                    className="text-sol-base01 hover:text-sol-base1 cursor-pointer text-sm"
                  >&times;</button>
                </div>
              </div>
            </div>
          )}

          {/* Event form popover (edit / create mode) */}
          {form && (mode === "edit" || mode === "create") && (
            <div className="sticky top-0 z-20 bg-sol-base02 border-b border-sol-base01/30 px-3 py-2" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sol-base1 text-sm font-medium">{mode === "create" ? "New event" : "Edit event"}</span>
                <button
                  onClick={closePopover}
                  className="text-sol-base01 hover:text-sol-base1 cursor-pointer text-sm"
                >&times;</button>
              </div>
              <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 items-center">
                <label className="text-sol-base01">Title</label>
                <input
                  value={form.summary}
                  onChange={(e) => setForm({ ...form, summary: e.target.value })}
                  placeholder="Summary"
                  className="w-full bg-sol-base03 text-sol-base1 border border-sol-base01/30 rounded px-2 py-1 text-xs outline-none focus:border-sol-blue"
                />
                <label className="text-sol-base01">Start</label>
                <input
                  type="datetime-local"
                  value={form.start}
                  onChange={(e) => setForm({ ...form, start: e.target.value })}
                  className="w-full bg-sol-base03 text-sol-base1 border border-sol-base01/30 rounded px-2 py-1 text-xs outline-none focus:border-sol-blue"
                />
                <label className="text-sol-base01">End</label>
                <input
                  type="datetime-local"
                  value={form.end}
                  onChange={(e) => setForm({ ...form, end: e.target.value })}
                  className="w-full bg-sol-base03 text-sol-base1 border border-sol-base01/30 rounded px-2 py-1 text-xs outline-none focus:border-sol-blue"
                />
                <label className="text-sol-base01 self-start pt-1">Description</label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  rows={2}
                  className="w-full bg-sol-base03 text-sol-base1 border border-sol-base01/30 rounded px-2 py-1 text-xs outline-none focus:border-sol-blue resize-none"
                />
                <label className="text-sol-base01">Todo</label>
                <input
                  value={form.todo_id}
                  onChange={(e) => setForm({ ...form, todo_id: e.target.value })}
                  placeholder="todo id (optional)"
                  className="w-full bg-sol-base03 text-sol-base1 border border-sol-base01/30 rounded px-2 py-1 text-xs outline-none focus:border-sol-blue"
                />
                {mode === "create" && (
                  <>
                    <label className="text-sol-base01">All day</label>
                    <input
                      type="checkbox"
                      checked={form.all_day}
                      onChange={(e) => setForm({ ...form, all_day: e.target.checked })}
                      className="justify-self-start cursor-pointer"
                    />
                  </>
                )}
                {mode === "edit" && selectedEvent && (selectedEvent.all_day || selectedEvent.source || selectedEvent.status) && (
                  <>
                    <span className="text-sol-base01">Info</span>
                    <span className="text-sol-base01 text-[11px]">
                      {selectedEvent.all_day && "all-day "}
                      {selectedEvent.source && `· ${selectedEvent.source} `}
                      {selectedEvent.status && `· ${selectedEvent.status}`}
                    </span>
                  </>
                )}
              </div>
              <div className="flex items-center justify-end gap-2 mt-2">
                <button
                  onClick={closePopover}
                  className="px-2 py-0.5 rounded bg-sol-base01/30 text-sol-base0 hover:text-sol-base1 cursor-pointer"
                >Cancel</button>
                <button
                  onClick={mode === "create" ? saveCreate : saveEdit}
                  disabled={saving || !form.summary.trim() || !form.start}
                  className="px-2 py-0.5 rounded bg-sol-blue/80 text-sol-base03 hover:bg-sol-blue cursor-pointer disabled:opacity-50"
                >Save</button>
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
                    onClick={(e) => { e.stopPropagation(); openRead(ev); }}
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
                  <div
                    key={dayIdx}
                    className="relative border-r border-sol-base02"
                    onClick={(e) => {
                      e.stopPropagation();
                      // A drag whose synthetic click lands on empty column space
                      // must not open create; also clears the stale flag.
                      if (justDraggedRef.current) { justDraggedRef.current = false; return; }
                      const rect = e.currentTarget.getBoundingClientRect();
                      const hour = Math.min(23, Math.max(0, Math.floor((e.clientY - rect.top) / HOUR_HEIGHT)));
                      const start = new Date(days[dayIdx]);
                      start.setHours(HOUR_START + hour, 0, 0, 0);
                      openCreate(start);
                    }}
                  >
                    {/* Current time ticker */}
                    {nowTop !== null && dayIdx === todayColIdx && (
                      <div
                        className="absolute left-0 right-0 z-10 pointer-events-none"
                        style={{ top: nowTop }}
                      >
                        <div className="relative flex items-center">
                          <div className="w-2 h-2 rounded-full bg-sol-red shrink-0 -ml-1" />
                          <div className="flex-1 h-px bg-sol-red" />
                          <span className="text-sol-red text-xs px-1 bg-sol-base03 shrink-0">
                            {String(now.getHours()).padStart(2, "0")}:{String(now.getMinutes()).padStart(2, "0")}
                          </span>
                        </div>
                      </div>
                    )}
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
                        return { ev, evStart, evEnd, clippedStart, clippedEnd, startHour, endHour, dayStart, dayEnd };
                      });
                      const layout = layoutOverlaps(evData.map(d => ({ start: d.startHour, end: d.endHour })));
                      return evData.map((d, idx) => {
                        const { ev, evStart, evEnd, clippedStart, clippedEnd, startHour, endHour, dayStart, dayEnd } = d;
                        const { col, totalCols } = layout[idx];
                        const key = `${ev.event_id}-${dayIdx}`;
                        // Live preview: while resizing this block, re-derive the
                        // visible bounds from the dragged ms (clipped to the day).
                        let topHour = startHour;
                        let botHour = endHour;
                        const dragging = dragState?.key === key;
                        if (dragging) {
                          const cs = Math.max(dragState.newStartMs, dayStart.getTime());
                          const ce = Math.min(dragState.newEndMs, dayEnd.getTime());
                          const csD = new Date(cs);
                          const ceD = new Date(ce);
                          topHour = csD.getHours() + csD.getMinutes() / 60;
                          botHour = ceD.getHours() + ceD.getMinutes() / 60 || 24;
                        }
                        const top = Math.max(0, (topHour - HOUR_START)) * HOUR_HEIGHT;
                        const height = Math.max(HOUR_HEIGHT / 4, (botHour - topHour) * HOUR_HEIGHT - 4);
                        const gap = 2;
                        const widthPct = (100 - gap * totalCols) / totalCols;
                        const leftPct = col * (widthPct + gap);
                        // Only offer a handle on an edge that is the event's real
                        // edge (not clipped to the day boundary on a multi-day span).
                        const showTopHandle = clippedStart.getTime() === evStart.getTime();
                        const showBottomHandle = clippedEnd.getTime() === evEnd.getTime();
                        // Body move is only offered on events fully contained in
                        // this day column (both edges are real, not day-clipped).
                        const canMove = showTopHandle && showBottomHandle;
                        // In-block label times track the live drag preview, so the
                        // user sees the resulting range update as they drag.
                        const dispStart = new Date(dragging ? dragState.newStartMs : evStart.getTime());
                        const dispEnd = new Date(dragging ? dragState.newEndMs : evEnd.getTime());
                        return (
                          <div
                            key={key}
                            onClickCapture={(e) => {
                              // Suppress the synthetic click that follows a real
                              // drag so it doesn't open the read popover.
                              if (justDraggedRef.current) {
                                e.stopPropagation();
                                justDraggedRef.current = false;
                              }
                            }}
                            onClick={(e) => { e.stopPropagation(); openRead(ev); }}
                            onPointerDown={canMove ? (e) => startMove(e, ev, key, evStart.getTime(), evEnd.getTime(), dayStart.getTime(), dayEnd.getTime()) : undefined}
                            className={`absolute rounded px-1 py-0.5 text-sol-base03 overflow-hidden ${canMove ? "cursor-move" : "cursor-pointer"} ${
                              getSourceColor(ev.source, sourceColorMap)
                            }`}
                            style={{ top, height, left: `${leftPct}%`, width: `${widthPct}%` }}
                            title={ev.summary}
                        >
                          {dragging || (clippedEnd.getTime() - clippedStart.getTime()) >= 60 * 60 * 1000 ? (
                            <>
                              <div className="truncate font-medium">{ev.summary}</div>
                              <div className={`truncate ${dragging ? "text-sol-base03" : "text-sol-base03/70"}`}>
                                {`${String(dispStart.getHours()).padStart(2, "0")}:${String(dispStart.getMinutes()).padStart(2, "0")}–${String(dispEnd.getHours()).padStart(2, "0")}:${String(dispEnd.getMinutes()).padStart(2, "0")}`}
                              </div>
                            </>
                          ) : (
                            <div className="truncate font-medium">
                              {ev.summary} <span className="font-normal text-sol-base03/70">{`${String(dispStart.getHours()).padStart(2, "0")}:${String(dispStart.getMinutes()).padStart(2, "0")}`}</span>
                            </div>
                          )}
                          {showTopHandle && (
                            <div
                              onPointerDown={(e) => startResize(e, ev, key, "top", evStart.getTime(), evEnd.getTime())}
                              className="absolute left-0 right-0 top-0 h-1.5 cursor-ns-resize hover:bg-sol-base03/30"
                            />
                          )}
                          {showBottomHandle && (
                            <div
                              onPointerDown={(e) => startResize(e, ev, key, "bottom", evStart.getTime(), evEnd.getTime())}
                              className="absolute left-0 right-0 bottom-0 h-1.5 cursor-ns-resize hover:bg-sol-base03/30"
                            />
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
        </div>
      )}
    </div>
  );
}
