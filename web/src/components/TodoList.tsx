import { useState, useEffect, useCallback, useRef } from "react";
import useSWRInfinite from "swr/infinite";
import { API, jsonFetcher as fetcher } from "../api";
import { TRACE_BADGE, statusBadgeClass, priorityColorClass } from "./badges";
import { formatDateTime } from "../utils/formatTime";
import TodoContextMenu from "./TodoContextMenu";

interface Todo {
  todo_id: string;
  name: string;
  pinned?: boolean;
  status: string;
  priority?: string;
  due_date?: string;
  tags?: string[];
  updated_at?: string;
  created_at?: string;
  has_running?: boolean;
  has_unread?: boolean;
}

const PAGE_SIZE = 50;

type StatusFilter = "pending" | "active" | "completed" | "all";

interface TodoListProps {
  isLoggedIn: boolean;
  onSelectTodo: (todoId: string) => void;
  onSelectTrace?: (traceId: string) => void;
}

export default function TodoList({ isLoggedIn, onSelectTodo, onSelectTrace }: TodoListProps) {
  const [search, setSearch] = useState("");
  const [spinning, setSpinning] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ todo: { todo_id: string; status: string }; x: number; y: number } | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => {
    const saved = localStorage.getItem("todoListStatusFilter");
    return (saved === "pending" || saved === "active" || saved === "completed" || saved === "all") ? saved : "pending";
  });
  useEffect(() => { localStorage.setItem("todoListStatusFilter", statusFilter); }, [statusFilter]);

  const statusParam = statusFilter === "all" ? "" : `&status=${statusFilter}`;
  const queryParam = search.trim() ? `&query=${encodeURIComponent(search.trim())}` : "";

  const getKey = (pageIndex: number, previousPageData: Todo[] | null) => {
    if (!isLoggedIn) return null;
    if (previousPageData && previousPageData.length < PAGE_SIZE) return null;
    return `${API}/api/todo/list?offset=${pageIndex * PAGE_SIZE}&limit=${PAGE_SIZE}${statusParam}${queryParam}`;
  };

  const { data, isLoading, error, size, setSize, isValidating, mutate } = useSWRInfinite<Todo[]>(getKey, fetcher);

  const todos = data ? data.flat() : [];
  const isReachingEnd = data && data[data.length - 1]?.length < PAGE_SIZE;

  const observer = useRef<IntersectionObserver | null>(null);
  const sentinelRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (isValidating) return;
      if (observer.current) observer.current.disconnect();
      observer.current = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && !isReachingEnd) {
          setSize((s) => s + 1);
        }
      });
      if (node) observer.current.observe(node);
    },
    [isValidating, isReachingEnd, setSize],
  );

  useEffect(() => {
    setSize(1);
  }, [statusFilter, search, setSize]);

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
        ) : todos.length === 0 ? (
          <p className="text-sol-base01 italic p-2">No todos</p>
        ) : (
          <>
            {todos.map((t) => (
              <div
                key={t.todo_id}
                onClick={() => onSelectTodo(t.todo_id)}
                onContextMenu={(e) => { e.preventDefault(); setContextMenu({ todo: { todo_id: t.todo_id, status: t.status }, x: e.clientX, y: e.clientY }); }}
                className="px-2 py-2 rounded-md cursor-pointer hover:bg-sol-base02 transition-colors"
              >
                <div className="flex items-center gap-1.5 mb-0.5">
                  <button
                    onClick={(e) => { e.stopPropagation(); if (onSelectTrace) onSelectTrace(t.todo_id); else navigator.clipboard.writeText(t.todo_id); }}
                    className={`text-[0.6rem] cursor-pointer ${TRACE_BADGE}`}
                    title="View trace"
                  >
                    #{t.todo_id}
                  </button>
                  {t.pinned && <span className="text-sol-yellow text-[0.6rem] shrink-0" title="Pinned">{"\u{1F4CC}"}</span>}
                  {t.has_unread && <span className="w-1.5 h-1.5 rounded-full bg-sol-blue shrink-0" />}
                  {t.has_running && (
                    <svg className="w-3 h-3 text-sol-blue animate-spin shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
                  )}
                  <span className="truncate text-sol-base0 text-[0.7rem]">{t.name}</span>
                </div>
                <div className="flex items-center gap-1.5 text-[0.6rem] text-sol-base01">
                  <span className={`px-1 rounded ${statusBadgeClass(t.status)}`}>
                    {t.status}
                  </span>
                  {t.priority && (
                    <span className={priorityColorClass(t.priority)}>{t.priority}</span>
                  )}
                  {t.due_date && <span>{t.due_date}</span>}
                  {(t.updated_at || t.created_at) && (() => {
                    const { date, time } = formatDateTime(new Date(t.updated_at || t.created_at!));
                    return <span className="ml-auto shrink-0 text-right">{date}<br/>{time}</span>;
                  })()}
                </div>
              </div>
            ))}
            {!isReachingEnd && (
              <div ref={sentinelRef} className="py-2 text-center text-sol-base01 italic">
                {isValidating ? "Loading..." : ""}
              </div>
            )}
          </>
        )}
      </div>
      {contextMenu && (
        <TodoContextMenu
          todo={contextMenu.todo}
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          onAction={() => mutate()}
        />
      )}
    </div>
  );
}
