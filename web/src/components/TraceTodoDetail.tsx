import { useEffect, useState, type KeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { actionBadgeClass, priorityColorClass } from "./badges";

export interface TodoHistoryEntry {
  timestamp: string;
  action: string;
  note?: string;
}

export interface TodoInfo {
  todo_id: string;
  name: string;
  status: string;
  desc?: string;
  tags?: string[];
  priority?: string;
  due_date?: string;
  progress?: string;
  completed_at?: string;
  created_at?: string;
  updated_at?: string;
  history?: TodoHistoryEntry[];
}

export interface TodoPatch {
  name?: string;
  status?: string;
  desc?: string | null;
  tags?: string[] | null;
  priority?: string | null;
  due_date?: string | null;
  progress?: string | null;
}

interface TraceTodoDetailProps {
  todoInfo: TodoInfo;
  open: boolean;
  setOpen: (v: boolean) => void;
  historyOpen: boolean;
  setHistoryOpen: (v: boolean) => void;
  /** When provided, the panel becomes editable; on Save we forward the patch (only dirty
   *  fields). When undefined, the panel is read-only (share / public view). */
  onSave?: (patch: TodoPatch) => Promise<void>;
  /** Notify parent when the dirty state of the patch buffer flips. Used to put a
   *  navigation guard on todo switches. */
  onDirtyChange?: (dirty: boolean) => void;
}

const STATUS_OPTIONS = ["pending", "active", "completed", "deleted"] as const;
const PRIORITY_OPTIONS = ["none", "high", "medium", "low"] as const;

const inputClass = "w-full bg-sol-base03 text-sol-base1 border border-sol-base01/30 rounded px-2 py-1 text-xs outline-none focus:border-sol-blue";

export default function TraceTodoDetail({
  todoInfo,
  open,
  setOpen,
  historyOpen,
  setHistoryOpen,
  onSave,
  onDirtyChange,
}: TraceTodoDetailProps) {
  const editable = !!onSave;
  const [patch, setPatch] = useState<TodoPatch>({});
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [descExpanded, setDescExpanded] = useState(false);
  const [progressExpanded, setProgressExpanded] = useState(false);

  const dirty = Object.keys(patch).length > 0;

  // Drop the patch buffer when we navigate to a different todo. The parent confirms
  // discard-on-switch via onDirtyChange before actually updating todoInfo.todo_id.
  useEffect(() => {
    setPatch({});
    setTagInput("");
  }, [todoInfo.todo_id]);

  // Mirror dirty state to parent so it can install a navigation guard.
  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);

  const handleCancel = () => {
    setPatch({});
    setTagInput("");
  };

  // Effective values: patch overrides server value
  const nameValue = patch.name ?? todoInfo.name ?? "";
  const statusValue = patch.status ?? todoInfo.status ?? "pending";
  const descValue = patch.desc !== undefined ? (patch.desc ?? "") : (todoInfo.desc ?? "");
  const priorityValue = patch.priority !== undefined ? (patch.priority ?? "") : (todoInfo.priority ?? "");
  const dueValue = patch.due_date !== undefined ? (patch.due_date ?? "") : (todoInfo.due_date ?? "");
  const tagsValue: string[] = patch.tags !== undefined ? (patch.tags ?? []) : (todoInfo.tags ?? []);
  const progressValue = patch.progress !== undefined ? (patch.progress ?? "") : (todoInfo.progress ?? "");

  // Set a field on the patch, or drop it if it matches the original server value.
  const setNullableField = (key: "desc" | "priority" | "due_date" | "progress", value: string | null) => {
    setPatch((p) => {
      const next = { ...p };
      const orig = (todoInfo[key] ?? null) as string | null;
      if ((value ?? null) === orig) {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
  };

  const handleName = (v: string) => {
    setPatch((p) => {
      const next = { ...p };
      if (v === todoInfo.name) delete next.name;
      else next.name = v;
      return next;
    });
  };
  const handleStatus = (v: string) => {
    setPatch((p) => {
      const next = { ...p };
      if (v === todoInfo.status) delete next.status;
      else next.status = v;
      return next;
    });
  };
  const handleDesc = (v: string) => setNullableField("desc", v.length ? v : null);
  const handlePriority = (v: string) => setNullableField("priority", v === "none" || v === "" ? null : v);
  const handleDue = (v: string) => setNullableField("due_date", v.length ? v : null);
  const handleProgress = (v: string) => setNullableField("progress", v.length ? v : null);

  const sameTags = (a: string[], b: string[]) => a.length === b.length && a.every((v, i) => v === b[i]);
  const commitTags = (next: string[]) => {
    setPatch((p) => {
      const orig = todoInfo.tags ?? [];
      const stored = next.length ? next : null;
      const np = { ...p };
      if (sameTags(next, orig)) {
        delete np.tags;
      } else {
        np.tags = stored;
      }
      return np;
    });
  };
  const addTag = () => {
    const t = tagInput.trim();
    if (!t) return;
    if (tagsValue.includes(t)) {
      setTagInput("");
      return;
    }
    commitTags([...tagsValue, t]);
    setTagInput("");
  };
  const removeTag = (tag: string) => {
    commitTags(tagsValue.filter((x) => x !== tag));
  };
  const onTagKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addTag();
    } else if (e.key === "Backspace" && tagInput === "" && tagsValue.length > 0) {
      e.preventDefault();
      commitTags(tagsValue.slice(0, -1));
    }
  };

  const handleSave = async () => {
    if (!onSave || !dirty) return;
    setSaving(true);
    try {
      await onSave(patch);
      setPatch({});
      setTagInput("");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-3 border border-sol-base02 rounded">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-2 py-1 text-xs text-sol-base01 hover:text-sol-base0 cursor-pointer"
      >
        <span className="text-[0.6rem]">{open ? "▼" : "▶"}</span>
        <span className="font-medium text-sol-base0">Todo Detail</span>
      </button>
      {open && (
        <>
          <div className="px-2 pb-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
            {editable ? (
              <>
                <span className="text-sol-base01 pt-1">Name</span>
                <input
                  value={nameValue}
                  onChange={(e) => handleName(e.target.value)}
                  className={inputClass}
                />

                <span className="text-sol-base01 pt-1">Status</span>
                <select
                  value={statusValue}
                  onChange={(e) => handleStatus(e.target.value)}
                  className={inputClass}
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>

                <span className="text-sol-base01 pt-1">Desc</span>
                <div className="relative">
                  <textarea
                    value={descValue}
                    onChange={(e) => handleDesc(e.target.value)}
                    rows={3}
                    placeholder="Add description..."
                    className={`${inputClass} resize-none w-full ${descExpanded ? "overflow-y-auto" : "max-h-32 overflow-y-hidden"}`}
                  />
                  <button
                    onClick={() => setDescExpanded(!descExpanded)}
                    className="absolute top-1 right-1 text-[0.6rem] text-sol-base01 hover:text-sol-base0 cursor-pointer bg-sol-base03 px-0.5 leading-none"
                    title={descExpanded ? "Collapse" : "Expand"}
                  >
                    {descExpanded ? "▲" : "▼"}
                  </button>
                </div>

                <span className="text-sol-base01 pt-1">Priority</span>
                <select
                  value={priorityValue || "none"}
                  onChange={(e) => handlePriority(e.target.value)}
                  className={inputClass}
                >
                  {PRIORITY_OPTIONS.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>

                <span className="text-sol-base01 pt-1">Due</span>
                <div className="flex items-center gap-1">
                  <input
                    type="date"
                    value={dueValue}
                    onChange={(e) => handleDue(e.target.value)}
                    className={`${inputClass} flex-1`}
                  />
                  {dueValue && (
                    <button
                      onClick={() => handleDue("")}
                      className="px-1.5 py-0.5 rounded text-[0.6rem] text-sol-base01 hover:text-sol-base0 cursor-pointer"
                      title="Clear"
                    >
                      ×
                    </button>
                  )}
                </div>

                <span className="text-sol-base01 pt-1">Tags</span>
                <div className="flex flex-wrap gap-1 items-center bg-sol-base03 border border-sol-base01/30 rounded px-1.5 py-1 focus-within:border-sol-blue">
                  {tagsValue.map((tag) => (
                    <span key={tag} className="inline-flex items-center gap-0.5 bg-sol-base02 text-sol-base0 pl-1.5 pr-1 py-0.5 rounded text-[0.65rem]">
                      {tag}
                      <button
                        onClick={() => removeTag(tag)}
                        className="text-sol-base01 hover:text-sol-red cursor-pointer leading-none"
                        title="Remove tag"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  <input
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    onKeyDown={onTagKeyDown}
                    onBlur={() => { if (tagInput.trim()) addTag(); }}
                    placeholder={tagsValue.length === 0 ? "Add tags..." : ""}
                    className="flex-1 min-w-[4rem] bg-transparent text-sol-base1 text-xs outline-none"
                  />
                </div>

                <span className="text-sol-base01 pt-1">Progress</span>
                <div className="relative">
                  <textarea
                    value={progressValue}
                    onChange={(e) => handleProgress(e.target.value)}
                    rows={2}
                    placeholder="Add progress note..."
                    className={`${inputClass} resize-none w-full ${progressExpanded ? "overflow-y-auto" : "max-h-32 overflow-y-hidden"}`}
                  />
                  <button
                    onClick={() => setProgressExpanded(!progressExpanded)}
                    className="absolute top-1 right-1 text-[0.6rem] text-sol-base01 hover:text-sol-base0 cursor-pointer bg-sol-base03 px-0.5 leading-none"
                    title={progressExpanded ? "Collapse" : "Expand"}
                  >
                    {progressExpanded ? "▲" : "▼"}
                  </button>
                </div>
              </>
            ) : (
              <>
                {todoInfo.desc && (
                  <>
                    <span className="text-sol-base01">Desc</span>
                    <div className="min-w-0 break-words text-sol-base0 prose prose-sm prose-invert max-w-none [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_pre]:my-1 [&_pre]:overflow-x-auto [&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-xs">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{todoInfo.desc}</ReactMarkdown>
                    </div>
                  </>
                )}
                {todoInfo.priority && (
                  <>
                    <span className="text-sol-base01">Priority</span>
                    <span className={priorityColorClass(todoInfo.priority)}>{todoInfo.priority}</span>
                  </>
                )}
                {todoInfo.due_date && (
                  <>
                    <span className="text-sol-base01">Due</span>
                    <span className="text-sol-base0">{todoInfo.due_date}</span>
                  </>
                )}
                {todoInfo.tags && todoInfo.tags.length > 0 && (
                  <>
                    <span className="text-sol-base01">Tags</span>
                    <div className="flex flex-wrap gap-1">
                      {todoInfo.tags.map((tag) => (
                        <span key={tag} className="bg-sol-base02 text-sol-base0 px-1.5 py-0.5 rounded text-[0.6rem]">{tag}</span>
                      ))}
                    </div>
                  </>
                )}
                {todoInfo.progress && (
                  <>
                    <span className="text-sol-base01">Progress</span>
                    <span className="text-sol-base0 whitespace-pre-wrap">{todoInfo.progress}</span>
                  </>
                )}
              </>
            )}
            {todoInfo.created_at && (
              <>
                <span className="text-sol-base01">Created</span>
                <span className="text-sol-base0 font-mono text-[0.65rem]">{new Date(todoInfo.created_at).toLocaleString()}</span>
              </>
            )}
            {todoInfo.updated_at && (
              <>
                <span className="text-sol-base01">Updated</span>
                <span className="text-sol-base0 font-mono text-[0.65rem]">{new Date(todoInfo.updated_at).toLocaleString()}</span>
              </>
            )}
            {todoInfo.completed_at && (
              <>
                <span className="text-sol-base01">Completed</span>
                <span className="text-sol-green font-mono text-[0.65rem]">{new Date(todoInfo.completed_at).toLocaleString()}</span>
              </>
            )}
          </div>
          {editable && dirty && (
            <div className="px-2 pb-2 flex justify-end gap-1.5">
              <button
                onClick={handleCancel}
                disabled={saving}
                className="px-3 py-0.5 rounded text-[0.65rem] bg-sol-base02 text-sol-base0 hover:opacity-90 cursor-pointer disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-3 py-0.5 rounded text-[0.65rem] bg-sol-blue text-sol-base03 hover:opacity-90 cursor-pointer disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          )}
          {todoInfo.history && todoInfo.history.length > 0 && (
            <div className="px-2 pb-2">
              <button
                onClick={() => setHistoryOpen(!historyOpen)}
                className="flex items-center gap-1.5 text-[0.65rem] text-sol-base01 hover:text-sol-base0 cursor-pointer mb-1"
              >
                <span className="text-[0.55rem]">{historyOpen ? "▼" : "▶"}</span>
                <span>History ({todoInfo.history.length})</span>
              </button>
              {historyOpen && (
                <div className="ml-1 border-l border-sol-base02 pl-2 space-y-1.5">
                  {todoInfo.history.map((h, i) => (
                    <div key={i} className="flex items-start gap-1.5 relative">
                      <div className="absolute -left-[calc(0.5rem+1px)] top-1 w-1.5 h-1.5 rounded-full bg-sol-base01 border border-sol-base02" />
                      <span className="text-[0.6rem] text-sol-base01 font-mono shrink-0">
                        {new Date(h.timestamp).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                      </span>
                      <span className={`text-[0.55rem] px-1 rounded shrink-0 ${actionBadgeClass(h.action)}`}>{h.action}</span>
                      {h.note && <span className="text-[0.6rem] text-sol-base0 break-all">{h.note}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

