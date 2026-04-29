import { useEffect, useState } from "react";
import useSWR from "swr";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { formatDateTime } from "../utils/formatTime";

interface Routine {
  routine_id: string;
  name: string;
  schedule: string;
  message: string;
  description?: string | null;
  target_topic?: string | null;
  target_skill?: string | null;
  work_dir?: string | null;
  backend?: string | null;
  enabled: boolean;
  last_run_at?: string | null;
  last_run_status?: string | null;
  last_chat_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

type EnabledFilter = "all" | "enabled" | "disabled";

interface RoutineFormState {
  name: string;
  schedule: string;
  message: string;
  description: string;
  target_topic: string;
  target_skill: string;
  work_dir: string;
  backend: string;
  enabled: boolean;
}

const EMPTY_FORM: RoutineFormState = {
  name: "",
  schedule: "",
  message: "",
  description: "",
  target_topic: "",
  target_skill: "",
  work_dir: "",
  backend: "",
  enabled: true,
};

interface RoutineListProps {
  isLoggedIn: boolean;
  onShowChats?: (routineId: string) => void;
}

function targetLabel(r: Routine): string {
  if (r.target_topic) return `topic=${r.target_topic}`;
  if (r.target_skill) return `skill=${r.target_skill}`;
  return "—";
}

function lastRunBadgeClass(status?: string | null): string {
  if (!status) return "text-sol-base01";
  if (status === "ok") return "text-sol-green";
  return "text-sol-red";
}

function formatLastRun(ts?: string | null): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  const { date, time } = formatDateTime(d);
  return `${date} ${time}`;
}

function fromRoutine(r: Routine): RoutineFormState {
  return {
    name: r.name || "",
    schedule: r.schedule || "",
    message: r.message || "",
    description: r.description || "",
    target_topic: r.target_topic || "",
    target_skill: r.target_skill || "",
    work_dir: r.work_dir || "",
    backend: r.backend || "",
    enabled: !!r.enabled,
  };
}

interface FormDialogProps {
  open: boolean;
  title: string;
  initial: RoutineFormState;
  isEdit: boolean;
  onCancel: () => void;
  onSubmit: (form: RoutineFormState) => Promise<void>;
}

function FormDialog({ open, title, initial, isEdit, onCancel, onSubmit }: FormDialogProps) {
  const [form, setForm] = useState<RoutineFormState>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setForm(initial);
      setBusy(false);
      setError(null);
    }
  }, [open, initial]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, busy, onCancel]);

  if (!open) return null;

  const update = <K extends keyof RoutineFormState>(k: K, v: RoutineFormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    if (!form.name.trim()) { setError("Name is required"); return; }
    if (!form.schedule.trim()) { setError("Schedule (cron) is required"); return; }
    if (!form.message.trim()) { setError("Message is required"); return; }
    setBusy(true);
    setError(null);
    try {
      await onSubmit(form);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={() => { if (!busy) onCancel(); }}
    >
      <form
        onSubmit={handleSubmit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
      >
        <div className="px-4 py-3 border-b border-sol-base02 text-sol-base1 text-sm font-semibold shrink-0">
          {title}
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 text-xs">
          <Field label="Name" required>
            <input
              type="text"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
              autoFocus
            />
          </Field>
          <Field label="Schedule (cron)" required hint="e.g. 0 9 * * * — evaluated in Y_AGENT_TIMEZONE">
            <input
              type="text"
              value={form.schedule}
              onChange={(e) => update("schedule", e.target.value)}
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 font-mono outline-none focus:border-sol-blue"
              placeholder="0 9 * * *"
            />
          </Field>
          <Field label="Message" required>
            <textarea
              value={form.message}
              onChange={(e) => update("message", e.target.value)}
              rows={3}
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue resize-y"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Target topic" hint="optional, e.g. manager">
              <input
                type="text"
                value={form.target_topic}
                onChange={(e) => update("target_topic", e.target.value)}
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
              />
            </Field>
            <Field label="Target skill" hint="optional">
              <input
                type="text"
                value={form.target_skill}
                onChange={(e) => update("target_skill", e.target.value)}
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
              />
            </Field>
          </div>
          <Field label="Work dir" hint="optional, absolute path on the target VM">
            <input
              type="text"
              value={form.work_dir}
              onChange={(e) => update("work_dir", e.target.value)}
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
            />
          </Field>
          <Field label="Backend" hint="optional: claude_code | codex">
            <select
              value={form.backend}
              onChange={(e) => update("backend", e.target.value)}
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
            >
              <option value="">(default)</option>
              <option value="claude_code">claude_code</option>
              <option value="codex">codex</option>
            </select>
          </Field>
          <Field label="Description" hint="optional">
            <textarea
              value={form.description}
              onChange={(e) => update("description", e.target.value)}
              rows={2}
              className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue resize-y"
            />
          </Field>
          {!isEdit && (
            <label className="flex items-center gap-2 text-sol-base0">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => update("enabled", e.target.checked)}
              />
              Enabled
            </label>
          )}
          {error && <div className="text-sol-red text-xs">{error}</div>}
        </div>
        <div className="px-4 py-3 border-t border-sol-base02 flex justify-end gap-2 shrink-0">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-3 py-1.5 rounded text-xs text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 disabled:opacity-50 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="px-3 py-1.5 rounded text-xs bg-sol-blue/20 text-sol-blue border border-sol-blue/40 hover:bg-sol-blue/30 disabled:opacity-50 cursor-pointer"
          >
            {busy ? "Saving..." : isEdit ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({ label, hint, required, children }: { label: string; hint?: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-sol-base01 text-[0.65rem]">
          {label}
          {required && <span className="text-sol-red ml-0.5">*</span>}
        </span>
        {hint && <span className="text-sol-base01 text-[0.55rem] italic truncate">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

export default function RoutineList({ isLoggedIn, onShowChats }: RoutineListProps) {
  const [enabledFilter, setEnabledFilter] = useState<EnabledFilter>(() => {
    const saved = localStorage.getItem("routineListEnabledFilter") as EnabledFilter | null;
    return saved === "enabled" || saved === "disabled" || saved === "all" ? saved : "all";
  });
  useEffect(() => { localStorage.setItem("routineListEnabledFilter", enabledFilter); }, [enabledFilter]);

  const [spinning, setSpinning] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Routine | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const enabledQuery = enabledFilter === "all" ? "" : `?enabled=${enabledFilter === "enabled" ? "true" : "false"}`;
  const key = isLoggedIn ? `${API}/api/routine/list${enabledQuery}` : null;
  const { data, isLoading, error, mutate } = useSWR<Routine[]>(key, fetcher, { revalidateOnFocus: false });

  const refresh = () => {
    mutate();
    setSpinning(true);
    setTimeout(() => setSpinning(false), 600);
  };

  const showError = (e: unknown) => {
    setActionError(e instanceof Error ? e.message : String(e));
    setTimeout(() => setActionError(null), 4000);
  };

  const apiPost = async (path: string, body: any): Promise<any> => {
    const res = await authFetch(`${API}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const text = await res.text();
    let parsed: any = null;
    try { parsed = text ? JSON.parse(text) : null; } catch { /* ignore */ }
    if (!res.ok) {
      const msg = parsed && typeof parsed === "object" && parsed.detail ? parsed.detail : text || res.statusText;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return parsed;
  };

  const handleCreate = async (form: RoutineFormState) => {
    const body: Record<string, any> = {
      name: form.name.trim(),
      schedule: form.schedule.trim(),
      message: form.message,
      enabled: form.enabled,
    };
    if (form.description.trim()) body.description = form.description;
    if (form.target_topic.trim()) body.target_topic = form.target_topic.trim();
    if (form.target_skill.trim()) body.target_skill = form.target_skill.trim();
    if (form.work_dir.trim()) body.work_dir = form.work_dir.trim();
    if (form.backend) body.backend = form.backend;
    await apiPost("/api/routine", body);
    setCreating(false);
    mutate();
  };

  const handleUpdate = async (form: RoutineFormState) => {
    if (!editing) return;
    const body: Record<string, any> = { routine_id: editing.routine_id };
    body.name = form.name.trim();
    body.schedule = form.schedule.trim();
    body.message = form.message;
    body.description = form.description;
    body.target_topic = form.target_topic.trim();
    body.target_skill = form.target_skill.trim();
    body.work_dir = form.work_dir.trim();
    body.backend = form.backend;
    await apiPost("/api/routine/update", body);
    setEditing(null);
    mutate();
  };

  const handleToggle = async (r: Routine) => {
    setBusyId(r.routine_id);
    try {
      const path = r.enabled ? "/api/routine/disable" : "/api/routine/enable";
      await apiPost(path, { routine_id: r.routine_id });
      mutate();
    } catch (e) {
      showError(e);
    } finally {
      setBusyId(null);
    }
  };

  const handleRunNow = async (r: Routine) => {
    if (!window.confirm(`Run routine "${r.name}" now?`)) return;
    setBusyId(r.routine_id);
    try {
      await apiPost("/api/routine/run", { routine_id: r.routine_id });
      mutate();
    } catch (e) {
      showError(e);
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (r: Routine) => {
    if (!window.confirm(`Delete routine "${r.name}"? This cannot be undone.`)) return;
    setBusyId(r.routine_id);
    try {
      await apiPost("/api/routine/delete", { routine_id: r.routine_id });
      mutate();
    } catch (e) {
      showError(e);
    } finally {
      setBusyId(null);
    }
  };

  const pillClass = (active: boolean) =>
    `px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer ${active ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"}`;

  const routines = data || [];

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <div className="flex gap-1.5 items-center">
          <span className="text-sol-base01 text-[0.7rem]">Routines</span>
          <button
            onClick={() => setCreating(true)}
            className="ml-auto px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
            title="New routine"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
          <button
            onClick={refresh}
            className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
            title="Refresh"
          >
            <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
        </div>
        <div className="flex gap-1 items-center">
          {(["all", "enabled", "disabled"] as const).map((f) => (
            <button key={f} onClick={() => setEnabledFilter(f)} className={pillClass(enabledFilter === f)}>{f}</button>
          ))}
        </div>
      </div>
      {actionError && (
        <div className="px-2 py-1 text-[0.65rem] text-sol-red border-b border-sol-base02 break-words">
          {actionError}
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view routines</p>
        ) : isLoading ? (
          <p className="text-sol-base01 italic p-2">Loading...</p>
        ) : error ? (
          <p className="text-sol-base01 italic p-2">Error loading routines</p>
        ) : routines.length === 0 ? (
          <p className="text-sol-base01 italic p-2">No routines yet</p>
        ) : (
          routines.map((r) => {
            const busy = busyId === r.routine_id;
            return (
              <div
                key={r.routine_id}
                className={`px-2 py-1.5 rounded-md hover:bg-sol-base02 transition-colors ${r.enabled ? "" : "opacity-60"}`}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <button
                    onClick={() => navigator.clipboard.writeText(r.routine_id)}
                    className="text-[0.55rem] font-mono text-sol-base01 hover:text-sol-base1 cursor-pointer shrink-0"
                    title="Copy routine ID"
                  >
                    {r.routine_id.slice(0, 8)}
                  </button>
                  <span className="truncate flex-1 text-sol-base0 text-[0.7rem] font-medium">{r.name}</span>
                  <button
                    onClick={() => handleToggle(r)}
                    disabled={busy}
                    className={`shrink-0 w-7 h-3.5 rounded-full relative transition-colors cursor-pointer disabled:opacity-50 ${r.enabled ? "bg-sol-blue" : "bg-sol-base01/40"}`}
                    title={r.enabled ? "Disable" : "Enable"}
                  >
                    <span
                      className={`absolute top-0.5 w-2.5 h-2.5 rounded-full bg-sol-base03 transition-all ${r.enabled ? "left-3.5" : "left-0.5"}`}
                    />
                  </button>
                </div>
                <div className="flex items-center gap-1.5 text-[0.6rem] text-sol-base01 mb-0.5">
                  <span className="font-mono shrink-0" title="Cron schedule">{r.schedule}</span>
                  <span className="truncate" title={r.target_topic ? `topic=${r.target_topic}` : r.target_skill ? `skill=${r.target_skill}` : "no target"}>
                    {targetLabel(r)}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 text-[0.6rem]">
                  <span className="text-sol-base01">last:</span>
                  <span className="font-mono text-sol-base01 truncate">{formatLastRun(r.last_run_at)}</span>
                  <span className={`shrink-0 ${lastRunBadgeClass(r.last_run_status)}`} title={r.last_run_status || "never run"}>
                    {r.last_run_status ? (r.last_run_status.length > 12 ? r.last_run_status.slice(0, 12) + "…" : r.last_run_status) : "—"}
                  </span>
                </div>
                <div className="flex items-center gap-1 mt-1 text-[0.6rem]">
                  <button
                    onClick={() => handleRunNow(r)}
                    disabled={busy}
                    className="px-1.5 py-0.5 rounded bg-sol-base02 text-sol-base01 hover:text-sol-blue cursor-pointer disabled:opacity-50"
                    title="Run now"
                  >
                    Run
                  </button>
                  <button
                    onClick={() => setEditing(r)}
                    disabled={busy}
                    className="px-1.5 py-0.5 rounded bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer disabled:opacity-50"
                    title="Edit"
                  >
                    Edit
                  </button>
                  {onShowChats && (
                    <button
                      onClick={() => onShowChats(r.routine_id)}
                      className="px-1.5 py-0.5 rounded bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer"
                      title="See chats triggered by this routine"
                    >
                      Chats
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(r)}
                    disabled={busy}
                    className="ml-auto px-1.5 py-0.5 rounded text-sol-base01 hover:text-sol-red cursor-pointer disabled:opacity-50"
                    title="Delete"
                  >
                    Delete
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
      <FormDialog
        open={creating}
        title="New routine"
        initial={EMPTY_FORM}
        isEdit={false}
        onCancel={() => setCreating(false)}
        onSubmit={handleCreate}
      />
      <FormDialog
        open={!!editing}
        title={editing ? `Edit routine: ${editing.name}` : ""}
        initial={editing ? fromRoutine(editing) : EMPTY_FORM}
        isEdit
        onCancel={() => setEditing(null)}
        onSubmit={handleUpdate}
      />
    </div>
  );
}
