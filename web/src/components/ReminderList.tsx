import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { formatDateTime } from "../utils/formatTime";
import { ListEmpty, ListError, ListLoading } from "./ListStates";

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

type StatusFilter = "pending" | "sent" | "cancelled" | "all";

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

function groupByDay(reminders: Reminder[], direction: "asc" | "desc"): [string, Reminder[]][] {
  const groups = new Map<string, Reminder[]>();
  for (const r of reminders) {
    const d = new Date(r.remind_at);
    if (isNaN(d.getTime())) continue;
    const key = dayKey(d);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(r);
  }
  return [...groups.entries()].sort((a, b) =>
    direction === "asc" ? a[0].localeCompare(b[0]) : b[0].localeCompare(a[0]),
  );
}

function formatLocalInput(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day}T${hh}:${mm}`;
}

function toLocalInputValue(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return formatLocalInput(d);
}

function defaultRemindAt(): string {
  const d = new Date();
  d.setMinutes(d.getMinutes() + 60);
  d.setSeconds(0);
  d.setMilliseconds(0);
  return formatLocalInput(d);
}

const STATUS_COLOR: Record<string, string> = {
  pending: "bg-sol-base02 text-sol-base01",
  sent: "bg-sol-green/20 text-sol-green",
  cancelled: "bg-sol-base02 text-sol-base01/60 line-through",
};

function statusBadgeClass(status: string): string {
  return STATUS_COLOR[status] || "bg-sol-base02 text-sol-base01";
}

interface FormState {
  reminder_id: string | null;
  title: string;
  remind_at: string;
  description: string;
  todo_id: string;
  calendar_event_id: string;
}

function emptyForm(): FormState {
  return {
    reminder_id: null,
    title: "",
    remind_at: defaultRemindAt(),
    description: "",
    todo_id: "",
    calendar_event_id: "",
  };
}

function formFromReminder(r: Reminder): FormState {
  return {
    reminder_id: r.reminder_id,
    title: r.title,
    remind_at: toLocalInputValue(r.remind_at),
    description: r.description || "",
    todo_id: r.todo_id || "",
    calendar_event_id: r.calendar_event_id || "",
  };
}

interface ReminderFormProps {
  form: FormState;
  setForm: (f: FormState) => void;
  onSave: () => void;
  onCancel: () => void;
  onDelete?: () => void;
  busy: boolean;
  error: string | null;
}

function ReminderForm({ form, setForm, onSave, onCancel, onDelete, busy, error }: ReminderFormProps) {
  const isEdit = !!form.reminder_id;
  const canSave = form.title.trim().length > 0 && form.remind_at.length > 0 && !busy;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden text-xs"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-4 py-3 border-b border-sol-base02 flex items-center justify-between">
          <div className="text-sol-base1 text-sm font-semibold">{isEdit ? "Edit reminder" : "New reminder"}</div>
          <button
            onClick={onCancel}
            className="text-sol-base01 hover:text-sol-base1 cursor-pointer text-sm leading-none"
            title="Close"
          >&times;</button>
        </div>
        {error && (
          <div className="px-4 py-2 text-xs text-sol-red border-b border-sol-base02">{error}</div>
        )}
        <div className="flex flex-col gap-2 px-4 py-3">
          <label className="flex flex-col gap-1">
            <span className="text-sol-base01 text-[0.65rem] uppercase tracking-wide">Title *</span>
            <input
              type="text"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="What to remind"
              autoFocus
              className="px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-sol-base01 text-[0.65rem] uppercase tracking-wide">Remind at *</span>
            <input
              type="datetime-local"
              value={form.remind_at}
              onChange={(e) => setForm({ ...form, remind_at: e.target.value })}
              className="px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-sol-base01 text-[0.65rem] uppercase tracking-wide">Description</span>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={3}
              className="px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue resize-y"
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1">
              <span className="text-sol-base01 text-[0.65rem] uppercase tracking-wide">Todo ID</span>
              <input
                type="text"
                value={form.todo_id}
                onChange={(e) => setForm({ ...form, todo_id: e.target.value })}
                placeholder="optional"
                className="px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-sol-base01 text-[0.65rem] uppercase tracking-wide">Event ID</span>
              <input
                type="text"
                value={form.calendar_event_id}
                onChange={(e) => setForm({ ...form, calendar_event_id: e.target.value })}
                placeholder="optional"
                className="px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
              />
            </label>
          </div>
        </div>
        <div className="flex items-center gap-2 px-4 py-3 border-t border-sol-base02">
          {isEdit && onDelete && (
            <button
              onClick={onDelete}
              disabled={busy}
              className="px-3 py-1.5 rounded text-xs bg-sol-red/20 text-sol-red hover:bg-sol-red/30 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border border-sol-red/40"
            >
              Delete
            </button>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={onCancel}
              disabled={busy}
              className="px-3 py-1.5 rounded text-xs text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={onSave}
              disabled={!canSave}
              className="px-3 py-1.5 rounded text-xs bg-sol-blue/20 text-sol-blue hover:bg-sol-blue/30 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border border-sol-blue/40"
            >
              {busy ? "Saving..." : isEdit ? "Save" : "Create"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ReminderList({ isLoggedIn }: ReminderListProps) {
  const [spinning, setSpinning] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => {
    const saved = localStorage.getItem("reminderListStatusFilter");
    return saved === "pending" || saved === "sent" || saved === "cancelled" || saved === "all" ? saved : "all";
  });
  const [form, setForm] = useState<FormState | null>(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    localStorage.setItem("reminderListStatusFilter", statusFilter);
  }, [statusFilter]);

  const statusParam = statusFilter === "all" ? "" : `&status=${statusFilter}`;
  const key = isLoggedIn ? `${API}/api/reminder/list?limit=100${statusParam}` : null;
  const { data, isLoading, isValidating, error, mutate } = useSWR<Reminder[]>(key, fetcher, { revalidateOnFocus: false });

  const sortDirection: "asc" | "desc" = statusFilter === "pending" ? "asc" : "desc";

  const sortedReminders = useMemo(() => {
    if (!data) return [];
    return [...data].sort((a, b) =>
      sortDirection === "asc"
        ? a.remind_at.localeCompare(b.remind_at)
        : b.remind_at.localeCompare(a.remind_at),
    );
  }, [data, sortDirection]);

  const groups = useMemo(() => groupByDay(sortedReminders, sortDirection), [sortedReminders, sortDirection]);

  const openCreate = () => {
    setFormError(null);
    setForm(emptyForm());
  };

  const openEdit = (r: Reminder) => {
    setFormError(null);
    setForm(formFromReminder(r));
  };

  const closeForm = () => {
    if (busy) return;
    setForm(null);
    setFormError(null);
  };

  const handleSave = async () => {
    if (!form) return;
    const title = form.title.trim();
    if (!title || !form.remind_at) {
      setFormError("Title and remind time are required");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      if (form.reminder_id) {
        const body: Record<string, string> = {
          reminder_id: form.reminder_id,
          title,
          remind_at: form.remind_at,
          description: form.description.trim(),
          todo_id: form.todo_id.trim(),
          calendar_event_id: form.calendar_event_id.trim(),
        };
        const res = await authFetch(`${API}/api/reminder/update`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const msg = await res.text();
          throw new Error(msg || `Update failed (${res.status})`);
        }
      } else {
        const body: Record<string, string> = {
          title,
          remind_at: form.remind_at,
        };
        if (form.description.trim()) body.description = form.description.trim();
        if (form.todo_id.trim()) body.todo_id = form.todo_id.trim();
        if (form.calendar_event_id.trim()) body.calendar_event_id = form.calendar_event_id.trim();
        const res = await authFetch(`${API}/api/reminder`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const msg = await res.text();
          throw new Error(msg || `Create failed (${res.status})`);
        }
      }
      await mutate();
      setForm(null);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (r: { reminder_id: string; title: string }) => {
    if (!window.confirm(`Cancel reminder "${r.title}"?`)) return;
    setBusy(true);
    setFormError(null);
    try {
      const res = await authFetch(`${API}/api/reminder/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reminder_id: r.reminder_id }),
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || `Delete failed (${res.status})`);
      }
      await mutate();
      setForm(null);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const filterPills: StatusFilter[] = ["pending", "sent", "cancelled", "all"];

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <div className="flex items-center gap-1">
          <span className="text-sol-base01 text-[0.7rem]">Reminders</span>
          <button
            onClick={openCreate}
            disabled={!isLoggedIn}
            className="ml-auto px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            title="New reminder"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
          <button
            onClick={() => { mutate(); setSpinning(true); setTimeout(() => setSpinning(false), 600); }}
            className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
            title="Refresh"
          >
            <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
        </div>
        <div className="flex gap-1 items-center">
          {filterPills.map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={`px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer ${
                statusFilter === f
                  ? "bg-sol-blue text-sol-base03"
                  : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view reminders</p>
        ) : isLoading || isValidating ? (
          <ListLoading />
        ) : error && !data ? (
          <ListError error={error} />
        ) : groups.length === 0 ? (
          <ListEmpty label="reminders" />
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
                      className="group w-full flex items-center gap-1.5 py-1 px-1 rounded text-sol-base0 text-[0.7rem] hover:bg-sol-base02/50 cursor-pointer"
                      title={r.description || r.title}
                      onClick={() => openEdit(r)}
                    >
                      <span className="truncate flex-1">{r.title}</span>
                      {r.status !== "pending" && (
                        <span className={`shrink-0 text-[0.55rem] px-1 rounded ${statusBadgeClass(r.status)}`}>
                          {r.status}
                        </span>
                      )}
                      <span className="text-sol-base01 text-[0.6rem] shrink-0">{time}</span>
                      {r.status === "pending" && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDelete(r); }}
                          className="shrink-0 text-sol-base01 hover:text-sol-red opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                          title="Cancel reminder"
                        >
                          <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>
      {form && (
        <ReminderForm
          form={form}
          setForm={setForm}
          onSave={handleSave}
          onCancel={closeForm}
          onDelete={form.reminder_id ? () => handleDelete({ reminder_id: form.reminder_id!, title: form.title }) : undefined}
          busy={busy}
          error={formError}
        />
      )}
    </div>
  );
}
