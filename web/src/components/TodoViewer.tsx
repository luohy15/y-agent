import { useState, useEffect, useRef, Fragment, DragEvent } from "react";
import useSWR, { mutate } from "swr";
import { API, authFetch, clearToken } from "../api";

interface Todo {
  todo_id: string;
  name: string;
  desc?: string;
  tags?: string[];
  due_date?: string;
  priority?: string;
  status: string;
  progress?: string;
  completed_at?: string;
  updated_at?: string;
  created_at_unix?: number;
  updated_at_unix?: number;
  history?: { timestamp: string; unix_timestamp: number; action: string; note?: string }[];
}

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

const priorityColor: Record<string, string> = {
  high: "text-sol-red",
  medium: "text-sol-yellow",
  low: "text-sol-green",
};

const statusColor: Record<string, string> = {
  active: "bg-sol-blue text-sol-base03",
  pending: "bg-sol-yellow text-sol-base03",
  completed: "bg-sol-green text-sol-base03",
};

function KanbanCard({ t, className, draggable, onDragStart, onClickName }: { t: Todo; className?: string; draggable?: boolean; onDragStart?: (e: DragEvent) => void; onClickName?: () => void }) {
  return (
    <div
      className={`bg-sol-base02 rounded p-2 border border-sol-base01/20 ${className || ""}`}
      draggable={draggable}
      onDragStart={onDragStart}
    >
      <div className="flex items-start justify-between">
        <span className="text-sol-base1 text-sm sm:text-xs font-medium leading-tight">
          <span className="text-sol-base01 mr-1 cursor-pointer hover:text-sol-blue" onClick={() => navigator.clipboard.writeText(t.todo_id)} title="Copy ID">#{t.todo_id}</span>
          {onClickName ? (
            <span className="cursor-pointer hover:text-sol-blue" onClick={onClickName}>{t.name}</span>
          ) : t.name}
        </span>
        {t.priority && (
          <span className={`text-xs shrink-0 ml-2 ${priorityColor[t.priority] || "text-sol-base0"}`}>
            {t.priority}
          </span>
        )}
      </div>
      {t.desc && (
        <p className="text-sol-base01 text-xs mt-1 line-clamp-2">{t.desc}</p>
      )}
    </div>
  );
}

function TodoDetail({ t, onClose, onSaved }: { t: Todo; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(t.name);
  const [desc, setDesc] = useState(t.desc || "");
  const [dueDate, setDueDate] = useState(t.due_date || "");
  const [priority, setPriority] = useState(t.priority || "");
  const [tags, setTags] = useState(t.tags?.join(", ") || "");
  const [progress, setProgress] = useState(t.progress || "");
  const [saving, setSaving] = useState(false);

  const dirty = name !== t.name || desc !== (t.desc || "") || dueDate !== (t.due_date || "") || priority !== (t.priority || "") || tags !== (t.tags?.join(", ") || "") || progress !== (t.progress || "");

  const handleSave = async () => {
    const fields: Record<string, unknown> = { todo_id: t.todo_id };
    if (name !== t.name) fields.name = name;
    if (desc !== (t.desc || "")) fields.desc = desc || null;
    if (dueDate !== (t.due_date || "")) fields.due_date = dueDate || null;
    if (priority !== (t.priority || "")) fields.priority = priority || null;
    if (progress !== (t.progress || "")) fields.progress = progress || null;
    const newTags = tags.split(",").map((s) => s.trim()).filter(Boolean);
    const oldTags = t.tags || [];
    if (JSON.stringify(newTags) !== JSON.stringify(oldTags)) fields.tags = newTags.length ? newTags : null;

    if (Object.keys(fields).length <= 1) return; // only todo_id
    setSaving(true);
    const res = await authFetch(`${API}/api/todo/update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
    setSaving(false);
    if (res.ok) onSaved();
  };

  const inputClass = "w-full bg-sol-base03 text-sol-base1 border border-sol-base01/30 rounded px-2 py-1 text-xs outline-none focus:border-sol-blue";

  return (
    <div className="bg-sol-base02 rounded p-3 border border-sol-base01/20 relative" data-todo-card>
      <button onClick={onClose} className="absolute top-2 right-2 text-sol-base01 hover:text-sol-base1 cursor-pointer text-xs">&times;</button>

      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 items-start text-xs">
        <label className="text-sol-base01 pt-1">Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />

        <label className="text-sol-base01 pt-1">Desc</label>
        <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={2} className={`${inputClass} resize-y`} />

        <label className="text-sol-base01 pt-1">Progress</label>
        <textarea value={progress} onChange={(e) => setProgress(e.target.value)} rows={2} className={`${inputClass} resize-y`} />

        <label className="text-sol-base01 pt-1">Due</label>
        <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className={inputClass} />

        <label className="text-sol-base01 pt-1">Priority</label>
        <select value={priority} onChange={(e) => setPriority(e.target.value)} className={inputClass}>
          <option value="">none</option>
          <option value="high">high</option>
          <option value="medium">medium</option>
          <option value="low">low</option>
        </select>

        <label className="text-sol-base01 pt-1">Tags</label>
        <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="comma separated" className={inputClass} />

        <label className="text-sol-base01 pt-1">Status</label>
        <div className="flex items-center gap-1.5">
          <span className={`px-1.5 py-0.5 rounded text-xs ${statusColor[t.status] || "bg-sol-base02 text-sol-base0"}`}>{t.status}</span>
          {t.updated_at && <span className="text-sol-base01 text-xs">updated {new Date(t.updated_at).toLocaleString()}</span>}
        </div>
      </div>

      {dirty && (
        <div className="mt-2 flex justify-end">
          <button onClick={handleSave} disabled={saving} className="px-3 py-1 rounded text-xs bg-sol-blue text-sol-base03 hover:opacity-90 cursor-pointer disabled:opacity-50">
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      )}

      {t.history && t.history.length > 0 && (
        <div className="border-t border-sol-base01/20 pt-2 mt-2 space-y-0.5">
          {[...t.history].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()).map((h, i) => (
            <div key={i} className="text-xs text-sol-base01 flex gap-1.5">
              <span className="shrink-0">{new Date(h.timestamp).toLocaleDateString()}</span>
              <span className="text-sol-base0">{h.action}</span>
              {h.note && <span className="text-sol-base01 truncate">{h.note}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type BottomFilter = "pending" | "completed" | "all";

type SortKey = "todo_id" | "due_date" | "name" | "status" | "priority" | "updated_at" | "tags";
type SortDir = "asc" | "desc";

const priorityOrder: Record<string, number> = { high: 0, medium: 1, low: 2 };

function compareTodos(a: Todo, b: Todo, key: SortKey): number {
  switch (key) {
    case "todo_id": return a.todo_id.localeCompare(b.todo_id, undefined, { numeric: true });
    case "name": return (a.name || "").localeCompare(b.name || "");
    case "status": return (a.status || "").localeCompare(b.status || "");
    case "priority": return (priorityOrder[a.priority || ""] ?? 3) - (priorityOrder[b.priority || ""] ?? 3);
    case "due_date": return (a.due_date || "9999").localeCompare(b.due_date || "9999");
    case "updated_at": return (a.updated_at || "").localeCompare(b.updated_at || "");
    case "tags": return (a.tags?.join(",") || "").localeCompare(b.tags?.join(",") || "");
  }
}

function sortTodos(todos: Todo[], key: SortKey, dir: SortDir): Todo[] {
  const tiebreakers: SortKey[] = ["due_date", "priority", "updated_at"];
  return [...todos].sort((a, b) => {
    const primary = compareTodos(a, b, key);
    if (primary !== 0) return dir === "asc" ? primary : -primary;
    for (const tk of tiebreakers) {
      if (tk === key) continue;
      const cmp = compareTodos(a, b, tk);
      if (cmp !== 0) return tk === "updated_at" ? -cmp : cmp;
    }
    return 0;
  });
}

type ViewMode = "table" | "kanban";

const KANBAN_COLUMNS: { status: string; label: string; color: string }[] = [
  { status: "pending", label: "Pending", color: "border-sol-yellow" },
  { status: "active", label: "Active", color: "border-sol-blue" },
  { status: "completed", label: "Completed", color: "border-sol-green" },
];

async function moveTodoToStatus(todoId: string, fromStatus: string, toStatus: string): Promise<boolean> {
  if (fromStatus === toStatus) return false;

  let endpoint: string;
  if (toStatus === "active") {
    endpoint = `${API}/api/todo/activate`;
  } else if (toStatus === "completed") {
    endpoint = `${API}/api/todo/finish`;
  } else if (toStatus === "pending") {
    if (fromStatus === "active") {
      endpoint = `${API}/api/todo/deactivate`;
    } else {
      endpoint = `${API}/api/todo/deactivate`;
    }
  } else {
    return false;
  }

  const res = await authFetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ todo_id: todoId }),
  });
  return res.ok;
}

function KanbanBoard({ todos, onMoved }: { todos: Todo[]; onMoved: () => void }) {
  const [dragOverCol, setDragOverCol] = useState<string | null>(null);
  const [moving, setMoving] = useState<string | null>(null);
  const [modalTodo, setModalTodo] = useState<Todo | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && modalTodo) setModalTodo(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [modalTodo]);

  const handleDragStart = (e: DragEvent, todo: Todo) => {
    e.dataTransfer.setData("text/plain", JSON.stringify({ todo_id: todo.todo_id, status: todo.status }));
    e.dataTransfer.effectAllowed = "move";
  };

  const handleDragOver = (e: DragEvent, status: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverCol(status);
  };

  const handleDragLeave = () => {
    setDragOverCol(null);
  };

  const handleDrop = async (e: DragEvent, targetStatus: string) => {
    e.preventDefault();
    setDragOverCol(null);
    try {
      const data = JSON.parse(e.dataTransfer.getData("text/plain"));
      if (data.status === targetStatus) return;
      setMoving(data.todo_id);
      const ok = await moveTodoToStatus(data.todo_id, data.status, targetStatus);
      if (ok) onMoved();
    } catch { /* ignore */ }
    setMoving(null);
  };

  const grouped: Record<string, Todo[]> = { pending: [], active: [], completed: [] };
  for (const t of todos) {
    if (grouped[t.status]) grouped[t.status].push(t);
  }

  return (
    <div className="flex gap-3 h-full overflow-x-auto p-3">
      {KANBAN_COLUMNS.map((col) => (
        <div
          key={col.status}
          className={`flex flex-col min-w-56 flex-1 rounded border-t-2 ${col.color} ${dragOverCol === col.status ? "bg-sol-base02/50" : "bg-sol-base03"}`}
          onDragOver={(e) => handleDragOver(e, col.status)}
          onDragLeave={handleDragLeave}
          onDrop={(e) => handleDrop(e, col.status)}
        >
          <div className="flex items-center justify-between px-2 py-1.5">
            <span className="text-sol-base1 text-xs font-medium">{col.label}</span>
            <span className="text-sol-base01 text-xs">{grouped[col.status].length}</span>
          </div>
          <div className="flex-1 overflow-y-auto space-y-1.5 px-1.5 pb-1.5">
            {grouped[col.status].map((t) => (
              <KanbanCard
                key={t.todo_id}
                t={t}
                draggable
                onDragStart={(e) => handleDragStart(e, t)}
                onClickName={() => setModalTodo(t)}
                className={`cursor-grab active:cursor-grabbing ${moving === t.todo_id ? "opacity-50" : ""}`}
              />
            ))}
          </div>
        </div>
      ))}
      {modalTodo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setModalTodo(null)}>
          <div className="absolute inset-0 bg-black/50" />
          <div className="relative w-full max-w-lg max-h-[80vh] overflow-y-auto mx-4" onClick={(e) => e.stopPropagation()}>
            <TodoDetail t={modalTodo} onClose={() => setModalTodo(null)} onSaved={() => { setModalTodo(null); onMoved(); }} />
          </div>
        </div>
      )}
    </div>
  );
}

export default function TodoViewer({ viewMode = "table" }: { viewMode?: ViewMode }) {

  const [bottomFilter, setBottomFilter] = useState<BottomFilter>(() => {
    const saved = localStorage.getItem("todoFilter");
    return saved === "all" ? "all" : saved === "completed" ? "completed" : "pending";
  });
  useEffect(() => { localStorage.setItem("todoFilter", bottomFilter); }, [bottomFilter]);
  const scrollToId = useRef<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(() => {
    const saved = localStorage.getItem("todoExpandId");
    if (saved) {
      localStorage.removeItem("todoExpandId");
      setBottomFilter("all");
      scrollToId.current = saved;
      return saved;
    }
    return null;
  });
  const [sortState, setSortState] = useState<Record<BottomFilter, { key: SortKey; dir: SortDir }>>(() => {
    const defaults = { pending: { key: "due_date" as SortKey, dir: "asc" as SortDir }, completed: { key: "updated_at" as SortKey, dir: "desc" as SortDir }, all: { key: "updated_at" as SortKey, dir: "desc" as SortDir } };
    try {
      const saved = JSON.parse(localStorage.getItem("todoSortState") || "");
      return { ...defaults, ...saved };
    } catch {
      return defaults;
    }
  });
  useEffect(() => { localStorage.setItem("todoSortState", JSON.stringify(sortState)); }, [sortState]);
  const sortKey = sortState[bottomFilter].key;
  const sortDir = sortState[bottomFilter].dir;

  const { data: activeTodos } = useSWR<Todo[]>(
    `${API}/api/todo/list?status=active`,
    fetcher,
  );

  const bottomParam = bottomFilter === "all" ? "" : `?status=${bottomFilter}`;
  const { data: bottomTodos, isLoading, error } = useSWR<Todo[]>(
    `${API}/api/todo/list${bottomParam}`,
    fetcher,
  );

  // Kanban fetches all non-deleted todos
  const { data: kanbanPending } = useSWR<Todo[]>(
    viewMode === "kanban" ? `${API}/api/todo/list?status=pending` : null,
    fetcher,
  );
  const { data: kanbanCompleted } = useSWR<Todo[]>(
    viewMode === "kanban" ? `${API}/api/todo/list?status=completed` : null,
    fetcher,
  );
  const kanbanTodos = viewMode === "kanban"
    ? [...(kanbanPending || []), ...(activeTodos || []), ...(kanbanCompleted || [])]
    : [];

  const revalidateTodos = () => {
    mutate((key: string) => typeof key === "string" && key.includes("/api/todo/"), undefined, { revalidate: true });
  };

  const [nameFilter, setNameFilter] = useState("");
  const activeCards = (activeTodos || []).slice(0, 3);
  const filteredTodos = bottomTodos?.filter((t) => !nameFilter || t.name.toLowerCase().includes(nameFilter.toLowerCase()));
  const sortedTodos = filteredTodos ? sortTodos(filteredTodos, sortKey, sortDir) : undefined;

  useEffect(() => {
    if (scrollToId.current && sortedTodos) {
      const id = scrollToId.current;
      scrollToId.current = null;
      requestAnimationFrame(() => {
        document.getElementById(`todo-row-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
  }, [sortedTodos]);

  const handleSort = (key: SortKey) => {
    setSortState((prev) => ({
      ...prev,
      [bottomFilter]: sortKey === key
        ? { key, dir: sortDir === "asc" ? "desc" as SortDir : "asc" as SortDir }
        : { key, dir: "asc" as SortDir },
    }));
  };

  const [modalTodo, setModalTodo] = useState<Todo | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (modalTodo) setModalTodo(null);
        else setExpandedId(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [modalTodo]);

  const extraColClass = "hidden md:table-cell";
  const colCount = 7;

  if (viewMode === "kanban") {
    return (
      <div className="h-full flex flex-col bg-sol-base03 text-sm sm:text-xs">
        <div className="flex-1 overflow-hidden">
          <KanbanBoard todos={kanbanTodos} onMoved={revalidateTodos} />
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto overflow-x-hidden bg-sol-base03 text-sm sm:text-xs" onClick={(e) => { if (expandedId && !(e.target as HTMLElement).closest('[data-todo-card]')) setExpandedId(null); }}>
      {/* Active tasks as cards */}
      {activeCards.length > 0 && (
        <div className="px-3 pt-2 pb-1 border-b border-sol-base02">
          <div className="flex flex-col sm:flex-row gap-2">
            {activeCards.map((t) => (
              <div key={t.todo_id} className="sm:w-52 sm:shrink-0">
                <KanbanCard t={t} className="h-full" onClickName={() => setModalTodo(t)} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pending / All table */}
      <div className="px-3 pt-2">
        <div className="flex items-center gap-1.5 mb-1">
          {(["pending", "completed", "all"] as const).map((f) => (
            <button
              key={f}
              onClick={() => { setBottomFilter(f); setExpandedId(null); }}
              className={`px-2.5 py-1 sm:px-2 sm:py-0.5 rounded text-sm sm:text-xs cursor-pointer ${
                bottomFilter === f
                  ? "bg-sol-blue text-sol-base03"
                  : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"
              }`}
            >
              {f}
            </button>
          ))}
          <input
            type="text"
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            placeholder="filter by name..."
            className="px-2 py-0.5 rounded text-xs bg-sol-base02 text-sol-base1 border border-sol-base01/20 outline-none focus:border-sol-blue placeholder:text-sol-base01"
          />
        </div>

        {isLoading ? (
          <p className="text-sol-base01 italic">Loading...</p>
        ) : error ? (
          <p className="text-sol-red">Error loading todos</p>
        ) : !sortedTodos || sortedTodos.length === 0 ? (
          <p className="text-sol-base01 italic">No todos</p>
        ) : (
          <table className="w-full border-collapse">
            <thead className="sticky top-0 bg-sol-base03">
              <tr className="text-sol-base01 text-left text-xs border-b border-sol-base02">
                {([["todo_id", "ID", false], ["due_date", "Due", false], ["name", "Name", false], ["status", "Status", false], ["priority", "Priority", true], ["updated_at", "Updated", true], ["tags", "Tags", true]] as [SortKey, string, boolean][]).map(([key, label, extra]) => (
                  <th
                    key={key}
                    className={`py-1 px-1.5 cursor-pointer select-none hover:text-sol-base1 ${extra ? extraColClass : ""}`}
                    onClick={() => handleSort(key)}
                  >
                    {label}{sortKey === key ? (sortDir === "asc" ? " \u2191" : " \u2193") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedTodos.map((t) => (
                <Fragment key={t.todo_id}>
                  <tr
                    id={`todo-row-${t.todo_id}`}
                    className={`border-b border-sol-base02 ${expandedId === t.todo_id ? "bg-sol-base02/50" : ""}`}
                  >
                    <td
                      className="py-1 px-1.5 text-sol-base01 cursor-pointer hover:text-sol-blue"
                      onClick={() => { navigator.clipboard.writeText(t.todo_id); }}
                      title="Copy ID"
                    >#{t.todo_id}</td>
                    <td className="py-1 px-1.5 text-sol-base01">{t.due_date || "-"}</td>
                    <td
                      className="py-1 px-1.5 text-sol-base0 cursor-pointer hover:text-sol-blue"
                      onClick={() => setExpandedId(expandedId === t.todo_id ? null : t.todo_id)}
                    >{t.name}</td>
                    <td className="py-1 px-1.5">
                      <span className={`px-2 py-0.5 rounded text-xs ${statusColor[t.status] || "bg-sol-base02 text-sol-base0"}`}>
                        {t.status}
                      </span>
                    </td>
                    <td className={`py-1 px-1.5 ${priorityColor[t.priority || ""] || "text-sol-base0"} ${extraColClass}`}>
                      {t.priority || "-"}
                    </td>
                    <td className={`py-1 px-1.5 text-sol-base01 ${extraColClass}`}>{t.updated_at ? new Date(t.updated_at).toLocaleString() : "-"}</td>
                    <td className={`py-1 px-1.5 ${extraColClass}`}>
                      {t.tags?.map((tag) => (
                        <span key={tag} className="inline-block bg-sol-base02 text-sol-base0 text-xs px-1.5 py-0.5 rounded mr-1">
                          {tag}
                        </span>
                      ))}
                    </td>
                  </tr>
                  {expandedId === t.todo_id && (
                    <tr key={`${t.todo_id}-expand`} className="border-b border-sol-base02">
                      <td colSpan={colCount} className="p-2">
                        <TodoDetail t={t} onClose={() => setExpandedId(null)} onSaved={revalidateTodos} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {modalTodo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setModalTodo(null)}>
          <div className="absolute inset-0 bg-black/50" />
          <div className="relative w-full max-w-lg max-h-[80vh] overflow-y-auto mx-4" onClick={(e) => e.stopPropagation()}>
            <TodoDetail t={modalTodo} onClose={() => setModalTodo(null)} onSaved={() => { setModalTodo(null); revalidateTodos(); }} />
          </div>
        </div>
      )}
    </div>
  );
}
