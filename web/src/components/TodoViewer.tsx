import { useState, useEffect, useRef, Fragment } from "react";
import useSWR from "swr";
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

function TodoCard({ t, onClose }: { t: Todo; onClose?: () => void }) {
  return (
    <div className="bg-sol-base02 rounded p-2 border border-sol-base01/20 relative" data-todo-card>
      {onClose && (
        <button onClick={onClose} className="absolute top-1 right-1 text-sol-base01 hover:text-sol-base1 cursor-pointer text-xs">&times;</button>
      )}
      <div className="flex items-start justify-between pr-3">
        <span className="text-sol-base1 text-xs font-medium leading-tight">
          <span className="text-sol-base01 mr-1">#{t.todo_id}</span>
          {t.name}
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
      {t.progress && (
        <p className="text-sol-cyan text-xs mt-1 whitespace-pre-wrap line-clamp-3">{t.progress}</p>
      )}
      <div className="flex items-center gap-1.5 flex-wrap mt-1">
        <span className={`px-1.5 py-0.5 rounded text-xs ${statusColor[t.status] || "bg-sol-base02 text-sol-base0"}`}>
          {t.status}
        </span>
        {t.due_date && (
          <span className="text-xs text-sol-base01">{t.due_date}</span>
        )}
        {t.tags?.map((tag) => (
          <span key={tag} className="text-xs bg-sol-base03 text-sol-base0 px-1 py-0.5 rounded">
            {tag}
          </span>
        ))}
      </div>
      {t.history && t.history.length > 0 && (
        <div className="border-t border-sol-base01/20 pt-1 mt-1 space-y-0.5">
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
  const tiebreakers: SortKey[] = ["due_date", "priority", "todo_id"];
  return [...todos].sort((a, b) => {
    const primary = compareTodos(a, b, key);
    if (primary !== 0) return dir === "asc" ? primary : -primary;
    for (const tk of tiebreakers) {
      if (tk === key) continue;
      const cmp = compareTodos(a, b, tk);
      if (cmp !== 0) return cmp;
    }
    return 0;
  });
}

export default function TodoViewer() {
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

  const colCount = 7;

  return (
    <div className="h-full overflow-auto bg-sol-base03 text-xs" onClick={(e) => { if (expandedId && !(e.target as HTMLElement).closest('[data-todo-card]')) setExpandedId(null); }}>
      {/* Active tasks as cards */}
      {activeCards.length > 0 && (
        <div className="px-3 pt-2 pb-1 border-b border-sol-base02">
          <div className="flex flex-wrap gap-2">
            {activeCards.map((t) => (
              <TodoCard key={t.todo_id} t={t} />
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
              className={`px-2 py-0.5 rounded text-xs cursor-pointer ${
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
                {([["todo_id", "ID"], ["due_date", "Due"], ["name", "Name"], ["status", "Status"], ["priority", "Priority"], ["updated_at", "Updated"], ["tags", "Tags"]] as const).map(([key, label]) => (
                  <th
                    key={key}
                    className="py-1 px-1.5 cursor-pointer select-none hover:text-sol-base1"
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
                    <td className={`py-1 px-1.5 ${priorityColor[t.priority || ""] || "text-sol-base0"}`}>
                      {t.priority || "-"}
                    </td>
                    <td className="py-1 px-1.5 text-sol-base01">{t.updated_at ? new Date(t.updated_at).toLocaleString() : "-"}</td>
                    <td className="py-1 px-1.5">
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
                        <TodoCard t={t} onClose={() => setExpandedId(null)} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
