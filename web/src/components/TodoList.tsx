import { useState, useEffect } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";

interface Todo {
  todo_id: string;
  name: string;
  status: string;
  priority?: string;
  due_date?: string;
  tags?: string[];
}

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

const statusColor: Record<string, string> = {
  active: "bg-sol-blue/20 text-sol-blue",
  pending: "bg-sol-base02 text-sol-base01",
  completed: "bg-sol-green/20 text-sol-green",
};

const priorityColor: Record<string, string> = {
  high: "text-sol-red",
  medium: "text-sol-yellow",
  low: "text-sol-green",
};

type StatusFilter = "pending" | "active" | "completed" | "all";

interface TodoListProps {
  isLoggedIn: boolean;
  onSelectTodo: (todoId: string) => void;
  onSelectTrace?: (traceId: string) => void;
}

export default function TodoList({ isLoggedIn, onSelectTodo, onSelectTrace }: TodoListProps) {
  const [search, setSearch] = useState("");
  const [spinning, setSpinning] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => {
    const saved = localStorage.getItem("todoListStatusFilter");
    return (saved === "pending" || saved === "active" || saved === "completed" || saved === "all") ? saved : "pending";
  });
  useEffect(() => { localStorage.setItem("todoListStatusFilter", statusFilter); }, [statusFilter]);

  const statusParam = statusFilter === "all" ? "" : `?status=${statusFilter}`;
  const { data: todos, isLoading, error, mutate } = useSWR<Todo[]>(
    isLoggedIn ? `${API}/api/todo/list${statusParam}` : null,
    fetcher,
  );

  const filtered = todos?.filter(
    (t) => !search || t.name.toLowerCase().includes(search.toLowerCase()) || t.todo_id.includes(search),
  );

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <div className="flex gap-1.5">
          <input
            type="text"
            placeholder="Search todos..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
          />
          <button
            onClick={() => { mutate(); setSpinning(true); setTimeout(() => setSpinning(false), 600); }}
            className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
            title="Refresh"
          >
            <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
        </div>
        <div className="flex gap-1">
          {(["pending", "active", "completed", "all"] as const).map((f) => (
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
      <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view todos</p>
        ) : isLoading ? (
          <p className="text-sol-base01 italic p-2">Loading...</p>
        ) : error ? (
          <p className="text-sol-base01 italic p-2">Error loading todos</p>
        ) : !filtered || filtered.length === 0 ? (
          <p className="text-sol-base01 italic p-2">No todos</p>
        ) : (
          filtered.map((t) => (
            <div
              key={t.todo_id}
              onClick={() => onSelectTodo(t.todo_id)}
              className="px-2 py-1.5 rounded-md cursor-pointer hover:bg-sol-base02 transition-colors"
            >
              <div className="flex items-center gap-1.5 mb-0.5">
                <button
                  onClick={(e) => { e.stopPropagation(); if (onSelectTrace) onSelectTrace(t.todo_id); else navigator.clipboard.writeText(t.todo_id); }}
                  className="inline-flex items-center px-1 rounded bg-sol-base02 text-sol-base01 hover:text-sol-base0 text-[0.6rem] font-mono cursor-pointer shrink-0"
                  title="View trace"
                >
                  #{t.todo_id}
                </button>
                <span className="truncate text-sol-base0 text-[0.7rem]">{t.name}</span>
              </div>
              <div className="flex items-center gap-1.5 text-[0.6rem] text-sol-base01">
                <span className={`px-1 rounded ${statusColor[t.status] || "bg-sol-base02 text-sol-base01"}`}>
                  {t.status}
                </span>
                {t.priority && (
                  <span className={priorityColor[t.priority] || "text-sol-base0"}>{t.priority}</span>
                )}
                {t.due_date && <span>{t.due_date}</span>}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
