import { useMemo, useState } from "react";
import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";
import { formatDateTime } from "../utils/formatTime";

interface Reminder {
  reminder_id: string;
  title: string;
  remind_at: string;
  description?: string | null;
  todo_id?: string | null;
  calendar_event_id?: string | null;
  status: string;
  sent_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

interface ReminderListProps {
  isLoggedIn: boolean;
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatDayHeader(key: string): string {
  const today = dayKey(new Date());
  const tomorrowDate = new Date();
  tomorrowDate.setDate(tomorrowDate.getDate() + 1);
  const tomorrow = dayKey(tomorrowDate);
  if (key === today) return "Today";
  if (key === tomorrow) return "Tomorrow";
  const d = new Date(key + "T00:00:00");
  const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })} - ${days[d.getDay()]}`;
}

function groupByDay(reminders: Reminder[]): [string, Reminder[]][] {
  const groups = new Map<string, Reminder[]>();
  for (const r of reminders) {
    const d = new Date(r.remind_at);
    if (isNaN(d.getTime())) continue;
    const key = dayKey(d);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(r);
  }
  return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

export default function ReminderList({ isLoggedIn }: ReminderListProps) {
  const [spinning, setSpinning] = useState(false);

  const key = isLoggedIn ? `${API}/api/reminder/list?status=pending&limit=100` : null;
  const { data, isLoading, error, mutate } = useSWR<Reminder[]>(key, fetcher, { revalidateOnFocus: false });

  const groups = useMemo(() => groupByDay(data || []), [data]);

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 flex items-center gap-1">
        <span className="text-sol-base01 text-[0.7rem]">Pending reminders</span>
        <button
          onClick={() => { mutate(); setSpinning(true); setTimeout(() => setSpinning(false), 600); }}
          className="ml-auto px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
          title="Refresh"
        >
          <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view reminders</p>
        ) : isLoading ? (
          <p className="text-sol-base01 italic p-2">Loading...</p>
        ) : error ? (
          <p className="text-sol-base01 italic p-2">Error loading reminders</p>
        ) : groups.length === 0 ? (
          <p className="text-sol-base01 italic p-2">No pending reminders</p>
        ) : (
          groups.map(([day, items]) => (
            <div key={day} className="mb-2">
              <div className="text-sol-base01 text-[0.6rem] font-medium mb-1 px-1 sticky top-0 bg-sol-base03 py-0.5 z-[5] border-b border-sol-base02">
                {formatDayHeader(day)}
              </div>
              <div className="space-y-0">
                {items.map((r) => {
                  const d = new Date(r.remind_at);
                  const { time } = formatDateTime(d);
                  return (
                    <div
                      key={r.reminder_id}
                      className="w-full flex items-center gap-1.5 py-1 px-1 rounded text-sol-base0 text-[0.7rem]"
                      title={r.description || r.title}
                    >
                      <span className="truncate flex-1">{r.title}</span>
                      <span className="text-sol-base01 text-[0.6rem] shrink-0">{time}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
