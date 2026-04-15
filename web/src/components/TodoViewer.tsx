import { useState, useEffect, useRef, useCallback, Fragment, DragEvent } from "react";
import useSWR, { mutate } from "swr";
import useSWRInfinite from "swr/infinite";
import { API, authFetch, clearToken } from "../api";
import TodoContextMenu from "./TodoContextMenu";

interface TodoNote {
  note_id: string;
  content_key: string;
  front_matter?: { tags?: string[]; [key: string]: unknown };
  created_at?: string;
  updated_at?: string;
}

interface Todo {
  todo_id: string;
  name: string;
  pinned?: boolean;
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
  notes?: TodoNote[];
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

const actionColor: Record<string, string> = {
  create: "text-sol-green",
  activate: "text-sol-blue",
  finish: "text-sol-green",
  deactivate: "text-sol-yellow",
  update: "text-sol-cyan",
  delete: "text-sol-red",
};

function ActivityHistory({ todos, collapsed, onToggle }: { todos: Todo[]; collapsed: boolean; onToggle: () => void }) {
  const entries = todos.flatMap((t) =>
    (t.history || []).map((h) => ({ ...h, todoName: t.name, todoId: t.todo_id }))
  ).sort((a, b) => (b.unix_timestamp || 0) - (a.unix_timestamp || 0));

  return (
    <div className={`flex flex-col bg-sol-base03 border-l border-sol-base02 shrink-0 transition-all ${collapsed ? "w-8" : "w-72"}`}>
      <button
        onClick={onToggle}
        className="px-2 py-1.5 text-xs text-sol-base01 hover:text-sol-base1 cursor-pointer flex items-center gap-1 border-b border-sol-base02 shrink-0"
        title={collapsed ? "Show activity" : "Hide activity"}
      >
        {collapsed ? "◀" : "▶"}
        {!collapsed && <span className="font-medium text-sol-base1">Activity</span>}
      </button>
      {!collapsed && (
        <div className="flex-1 overflow-y-auto px-2 py-1.5 space-y-1">
          {entries.length === 0 ? (
            <p className="text-sol-base01 text-xs italic">No activity</p>
          ) : entries.map((e, i) => (
            <div key={i} className="text-xs border-b border-sol-base02/50 pb-1">
              <div className="flex items-center gap-1.5">
                <span className="text-sol-base01 shrink-0">{new Date(e.timestamp).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
                <span className={`shrink-0 ${actionColor[e.action] || "text-sol-base0"}`}>{e.action}</span>
              </div>
              <div className="text-sol-base1 truncate" title={e.todoName}>
                #{e.todoId} {e.todoName}
              </div>
              {e.note && <div className="text-sol-base01 truncate" title={e.note}>{e.note}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function KanbanCard({ t, className, draggable, onDragStart, onClickName, onContextMenu }: { t: Todo; className?: string; draggable?: boolean; onDragStart?: (e: DragEvent) => void; onClickName?: () => void; onContextMenu?: (e: React.MouseEvent) => void }) {
  return (
    <div
      className={`bg-sol-base02 rounded p-2 border ${t.pinned ? "border-sol-yellow/40" : "border-sol-base01/20"} ${className || ""}`}
      draggable={draggable}
      onDragStart={onDragStart}
      onContextMenu={onContextMenu}
    >
      <div className="flex items-start justify-between">
        <span className="text-sol-base1 text-sm sm:text-xs font-medium leading-tight">
          {t.pinned && <span className="text-sol-yellow mr-0.5" title="Pinned">{"\u{1F4CC}"}</span>}
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
      {t.due_date && (
        <span className="text-sol-base01 text-xs mt-1">{t.due_date}</span>
      )}
      {t.desc && (
        <p className="text-sol-base01 text-xs mt-0.5 line-clamp-2">{t.desc}</p>
      )}
    </div>
  );
}

async function togglePin(todoId: string, pinned: boolean): Promise<boolean> {
  const res = await authFetch(`${API}/api/todo/pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ todo_id: todoId, pinned }),
  });
  return res.ok;
}

function TodoDetail({ t, onClose, onSaved }: { t: Todo; onClose: () => void; onSaved: () => void }) {
  const { data: detail } = useSWR<Todo>(`${API}/api/todo/detail?todo_id=${t.todo_id}`, fetcher);
  const notes = detail?.notes || t.notes || [];
  const [name, setName] = useState(t.name);
  const [desc, setDesc] = useState(t.desc || "");
  const [dueDate, setDueDate] = useState(t.due_date || "");
  const [priority, setPriority] = useState(t.priority || "");
  const [tags, setTags] = useState(t.tags?.join(", ") || "");
  const [progress, setProgress] = useState(t.progress || "");
  const [saving, setSaving] = useState(false);
  const [pinning, setPinning] = useState(false);

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
    <div className="bg-sol-base02 rounded p-3 border border-sol-base01/20 relative flex flex-col h-full" data-todo-card>

      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 items-start text-xs shrink-0">
        <label className="text-sol-base01 pt-1">Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />

        <label className="text-sol-base01 pt-1">Desc</label>
        <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={2} className={`${inputClass} resize-none`} style={{ fieldSizing: "content" } as React.CSSProperties} />

        <label className="text-sol-base01 pt-1">Progress</label>
        <textarea value={progress} onChange={(e) => setProgress(e.target.value)} rows={2} className={`${inputClass} resize-none`} style={{ fieldSizing: "content" } as React.CSSProperties} />

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
          <button
            onClick={async () => { setPinning(true); const ok = await togglePin(t.todo_id, !t.pinned); setPinning(false); if (ok) onSaved(); }}
            disabled={pinning}
            className={`px-1.5 py-0.5 rounded text-xs cursor-pointer border ${t.pinned ? "bg-sol-yellow/20 text-sol-yellow border-sol-yellow/30" : "bg-sol-base02 text-sol-base01 border-sol-base01/30 hover:text-sol-base0"}`}
            title={t.pinned ? "Unpin" : "Pin"}
          >
            {pinning ? "..." : t.pinned ? "\u{1F4CC} Pinned" : "Pin"}
          </button>
          {t.updated_at && <span className="text-sol-base01 text-xs">updated {new Date(t.updated_at).toLocaleString()}</span>}
        </div>
      </div>

      {dirty && (
        <div className="mt-2 flex justify-end shrink-0">
          <button onClick={handleSave} disabled={saving} className="px-3 py-1 rounded text-xs bg-sol-blue text-sol-base03 hover:opacity-90 cursor-pointer disabled:opacity-50">
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      )}

      {notes.length > 0 && (
        <div className="border-t border-sol-base01/20 pt-2 mt-2 space-y-1 overflow-y-auto max-h-40" style={{ scrollbarColor: "#586e75 transparent" }}>
          <span className="text-xs text-sol-base01 font-medium">Notes</span>
          {notes.map((n) => (
            <div key={n.note_id} className="text-xs bg-sol-base03 rounded px-2 py-1 border border-sol-base01/10">
              <div className="flex items-center gap-1.5">
                <span className="text-sol-base01">#{n.note_id}</span>
                {n.front_matter?.tags?.map((tag) => (
                  <span key={tag} className="bg-sol-base02 text-sol-base0 px-1 rounded">{tag}</span>
                ))}
              </div>
              <p className="text-sol-base1 whitespace-pre-wrap mt-0.5">{n.content_key}</p>
            </div>
          ))}
        </div>
      )}

      {t.history && t.history.length > 0 && (
        <div className="border-t border-sol-base01/20 pt-2 mt-2 space-y-0.5 overflow-y-auto max-h-40" style={{ scrollbarColor: "#586e75 transparent" }}>
          {[...t.history].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()).map((h, i) => (
            <div key={i} className="text-xs text-sol-base01 flex gap-1.5">
              <span className="shrink-0">{new Date(h.timestamp).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
              <span className="text-sol-base0 shrink-0">{h.action}</span>
              {h.note && <span className="text-sol-base01">{h.note}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type BottomFilter = "pending" | "active" | "completed" | "all";

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
  const res = await authFetch(`${API}/api/todo/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ todo_id: todoId, status: toStatus }),
  });
  return res.ok;
}

function KanbanBoard({ todos, onMoved }: { todos: Todo[]; onMoved: () => void }) {
  const [dragOverCol, setDragOverCol] = useState<string | null>(null);
  const [moving, setMoving] = useState<string | null>(null);
  const [modalTodo, setModalTodo] = useState<Todo | null>(null);
  const [contextMenu, setContextMenu] = useState<{ todo: { todo_id: string; status: string }; x: number; y: number } | null>(null);

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
                onContextMenu={(e) => { e.preventDefault(); setContextMenu({ todo: { todo_id: t.todo_id, status: t.status }, x: e.clientX, y: e.clientY }); }}
                className={`cursor-grab active:cursor-grabbing ${moving === t.todo_id ? "opacity-50" : ""}`}
              />
            ))}
          </div>
        </div>
      ))}
      {modalTodo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setModalTodo(null)}>
          <div className="absolute inset-0 bg-black/50" />
          <div className="relative w-full max-w-lg mx-4" onClick={(e) => e.stopPropagation()}>
            <TodoDetail t={modalTodo} onClose={() => setModalTodo(null)} onSaved={() => { setModalTodo(null); onMoved(); }} />
          </div>
        </div>
      )}
      {contextMenu && (
        <TodoContextMenu
          todo={contextMenu.todo}
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          onAction={onMoved}
        />
      )}
    </div>
  );
}

export default function TodoViewer({ viewMode = "table" }: { viewMode?: ViewMode }) {

  const [historyCollapsed, setHistoryCollapsed] = useState(() => localStorage.getItem("todoHistoryCollapsed") !== "false");
  useEffect(() => { localStorage.setItem("todoHistoryCollapsed", String(historyCollapsed)); }, [historyCollapsed]);

  const [bottomFilter, setBottomFilter] = useState<BottomFilter>(() => {
    const saved = localStorage.getItem("todoFilter");
    return saved === "all" ? "all" : saved === "completed" ? "completed" : saved === "active" ? "active" : "pending";
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
    const defaults = { pending: { key: "due_date" as SortKey, dir: "asc" as SortDir }, active: { key: "due_date" as SortKey, dir: "asc" as SortDir }, completed: { key: "updated_at" as SortKey, dir: "desc" as SortDir }, all: { key: "updated_at" as SortKey, dir: "desc" as SortDir } };
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

  const [nameFilter, setNameFilter] = useState("");

  const TABLE_PAGE_SIZE = 50;
  const bottomStatusParam = bottomFilter === "all" ? "" : `&status=${bottomFilter}`;
  const nameQueryParam = nameFilter.trim() ? `&query=${encodeURIComponent(nameFilter.trim())}` : "";
  const getTableKey = (pageIndex: number, previousPageData: Todo[] | null) => {
    if (previousPageData && previousPageData.length < TABLE_PAGE_SIZE) return null;
    return `${API}/api/todo/list?offset=${pageIndex * TABLE_PAGE_SIZE}&limit=${TABLE_PAGE_SIZE}${bottomStatusParam}${nameQueryParam}`;
  };
  const { data: bottomPages, isLoading, error, size: tableSize, setSize: setTableSize, isValidating: tableValidating, mutate: mutateTable } = useSWRInfinite<Todo[]>(getTableKey, fetcher);
  const bottomTodos = bottomPages ? bottomPages.flat() : undefined;
  const tableReachingEnd = bottomPages && bottomPages[bottomPages.length - 1]?.length < TABLE_PAGE_SIZE;

  const tableObserver = useRef<IntersectionObserver | null>(null);
  const tableSentinelRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (tableValidating) return;
      if (tableObserver.current) tableObserver.current.disconnect();
      tableObserver.current = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && !tableReachingEnd) {
          setTableSize((s) => s + 1);
        }
      });
      if (node) tableObserver.current.observe(node);
    },
    [tableValidating, tableReachingEnd, setTableSize],
  );

  useEffect(() => {
    setTableSize(1);
  }, [bottomFilter, nameFilter, setTableSize]);

  // Kanban fetches all non-deleted todos (high limit per status)
  const kanbanQueryParam = nameFilter.trim() ? `&query=${encodeURIComponent(nameFilter.trim())}` : "";
  const { data: kanbanPending } = useSWR<Todo[]>(
    viewMode === "kanban" ? `${API}/api/todo/list?status=pending&limit=500${kanbanQueryParam}` : null,
    fetcher,
  );
  const { data: kanbanActive } = useSWR<Todo[]>(
    viewMode === "kanban" ? `${API}/api/todo/list?status=active&limit=500${kanbanQueryParam}` : null,
    fetcher,
  );
  const { data: kanbanCompleted } = useSWR<Todo[]>(
    viewMode === "kanban" ? `${API}/api/todo/list?status=completed&limit=500${kanbanQueryParam}` : null,
    fetcher,
  );
  const kanbanTodos = viewMode === "kanban"
    ? [...(kanbanPending || []), ...(kanbanActive || []), ...(kanbanCompleted || [])]
    : [];

  const revalidateTodos = () => {
    mutateTable();
    mutate((key: string) => typeof key === "string" && key.includes("/api/todo/"), undefined, { revalidate: true });
  };

  const sortedTodos = bottomTodos ? sortTodos(bottomTodos, sortKey, sortDir) : undefined;

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
  const [contextMenu, setContextMenu] = useState<{ todo: { todo_id: string; status: string }; x: number; y: number } | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (contextMenu) setContextMenu(null);
        else if (modalTodo) setModalTodo(null);
        else setExpandedId(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [modalTodo]);

  const extraColClass = "hidden md:table-cell";
  const colCount = 7;

  const filteredKanbanTodos = kanbanTodos;

  // Collect all loaded todos for activity history
  const allTodosForHistory = viewMode === "kanban" ? kanbanTodos : (bottomTodos || []);

  if (viewMode === "kanban") {
    return (
      <div className="h-full flex bg-sol-base03 text-sm sm:text-xs">
        <div className="flex-1 flex flex-col min-w-0">
          <div className="px-3 pt-2 pb-1">
            <input
              type="text"
              value={nameFilter}
              onChange={(e) => setNameFilter(e.target.value)}
              placeholder="filter by name..."
              className="px-2 py-0.5 rounded text-xs bg-sol-base02 text-sol-base1 border border-sol-base01/20 outline-none focus:border-sol-blue placeholder:text-sol-base01"
            />
          </div>
          <div className="flex-1 overflow-hidden">
            <KanbanBoard todos={filteredKanbanTodos} onMoved={revalidateTodos} />
          </div>
        </div>
        <ActivityHistory todos={allTodosForHistory} collapsed={historyCollapsed} onToggle={() => setHistoryCollapsed((c) => !c)} />
      </div>
    );
  }

  return (
    <div className="h-full flex bg-sol-base03 text-sm sm:text-xs">
    <div className="flex-1 overflow-y-auto overflow-x-hidden min-w-0" onClick={(e) => { if (expandedId && !(e.target as HTMLElement).closest('[data-todo-card]')) setExpandedId(null); }}>
      {/* Todo table */}
      <div className="px-3 pt-2">
        <div className="flex items-center gap-1.5 mb-1">
          {(["pending", "active", "completed", "all"] as const).map((f) => (
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
                    className={`border-b border-sol-base02 ${expandedId === t.todo_id ? "bg-sol-base02/50" : ""} ${t.pinned ? "border-l-2 border-l-sol-yellow" : ""}`}
                    onContextMenu={(e) => { e.preventDefault(); setContextMenu({ todo: { todo_id: t.todo_id, status: t.status }, x: e.clientX, y: e.clientY }); }}
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
                    >{t.pinned && <span className="text-sol-yellow mr-1" title="Pinned">{"\u{1F4CC}"}</span>}{t.name}</td>
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
        {sortedTodos && sortedTodos.length > 0 && !tableReachingEnd && (
          <div ref={tableSentinelRef} className="py-2 text-center text-sol-base01 italic text-xs">
            {tableValidating ? "Loading..." : ""}
          </div>
        )}
      </div>
      {modalTodo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setModalTodo(null)}>
          <div className="absolute inset-0 bg-black/50" />
          <div className="relative w-full max-w-lg mx-4" onClick={(e) => e.stopPropagation()}>
            <TodoDetail t={modalTodo} onClose={() => setModalTodo(null)} onSaved={() => { setModalTodo(null); revalidateTodos(); }} />
          </div>
        </div>
      )}
      {contextMenu && (
        <TodoContextMenu
          todo={contextMenu.todo}
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          onAction={revalidateTodos}
        />
      )}
    </div>
    <ActivityHistory todos={allTodosForHistory} collapsed={historyCollapsed} onToggle={() => setHistoryCollapsed((c) => !c)} />
    </div>
  );
}
