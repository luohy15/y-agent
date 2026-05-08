import { useState } from "react";
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

interface TraceTodoDetailProps {
  todoInfo: TodoInfo;
  open: boolean;
  setOpen: (v: boolean) => void;
  historyOpen: boolean;
  setHistoryOpen: (v: boolean) => void;
  /** When provided, the Progress field renders as an editable textarea + Save button.
   *  When undefined, Progress is read-only (share / public view). */
  onSaveProgress?: (newProgress: string | null) => Promise<void>;
}

export default function TraceTodoDetail({
  todoInfo,
  open,
  setOpen,
  historyOpen,
  setHistoryOpen,
  onSaveProgress,
}: TraceTodoDetailProps) {
  const editable = !!onSaveProgress;
  // Editing state uses an undefined sentinel: when undefined, the prop is the source
  // of truth (textarea reflects todoInfo.progress, no dirty marker). On first edit
  // we capture into a string draft. On save success we release back to undefined so
  // a subsequent SWR revalidation flows straight through.
  const [draft, setDraft] = useState<string | undefined>(undefined);
  const [saving, setSaving] = useState(false);
  const propValue = todoInfo.progress || "";
  const effectiveValue = draft ?? propValue;
  const dirty = editable && draft !== undefined && draft !== propValue;

  const handleSave = async () => {
    if (!onSaveProgress || draft === undefined) return;
    setSaving(true);
    const valueToSave = draft.trim() ? draft : null;
    try {
      await onSaveProgress(valueToSave);
      setDraft(undefined);
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
            {editable ? (
              <>
                <span className="text-sol-base01 pt-1">Progress</span>
                <div className="min-w-0 flex flex-col gap-1">
                  <textarea
                    value={effectiveValue}
                    onChange={(e) => setDraft(e.target.value)}
                    rows={2}
                    placeholder="Add progress note..."
                    className="w-full bg-sol-base03 text-sol-base1 border border-sol-base01/30 rounded px-2 py-1 text-xs outline-none focus:border-sol-blue resize-none"
                    style={{ fieldSizing: "content" } as React.CSSProperties}
                  />
                  {dirty && (
                    <div className="flex justify-end">
                      <button
                        onClick={handleSave}
                        disabled={saving}
                        className="px-2 py-0.5 rounded text-[0.65rem] bg-sol-blue text-sol-base03 hover:opacity-90 cursor-pointer disabled:opacity-50"
                      >
                        {saving ? "Saving..." : "Save"}
                      </button>
                    </div>
                  )}
                </div>
              </>
            ) : todoInfo.progress ? (
              <>
                <span className="text-sol-base01">Progress</span>
                <span className="text-sol-base0 whitespace-pre-wrap">{todoInfo.progress}</span>
              </>
            ) : null}
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
