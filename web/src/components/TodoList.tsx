import { useState, useEffect, useCallback, useRef } from "react";
import useSWRInfinite from "swr/infinite";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { TRACE_BADGE, statusBadgeClass, priorityColorClass } from "./badges";
import { formatDateTime } from "../utils/formatTime";
import { ListEmpty, ListError, ListLoading } from "./ListStates";
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

const BULK_STATUS_OPTIONS = ["pending", "active", "completed", "deleted"] as const;
const BULK_PRIORITY_OPTIONS = ["high", "medium", "low", "none"] as const;
const BULK_STATUS_COLOR: Record<string, string> = {
  pending: "text-sol-base0",
  active: "text-sol-blue",
  completed: "text-sol-green",
  deleted: "text-sol-red",
};

interface TodoListProps {
  isLoggedIn: boolean;
  onSelectTodo: (todoId: string) => void;
  onSelectTrace?: (traceId: string) => void;
  onChatListRefresh?: () => void;
}

export default function TodoList({ isLoggedIn, onSelectTodo, onSelectTrace, onChatListRefresh }: TodoListProps) {
  const [search, setSearch] = useState("");
  const [spinning, setSpinning] = useState(false);
  const [readAllBusy, setReadAllBusy] = useState(false);
  const [bulkReadBusy, setBulkReadBusy] = useState(false);
  const [bulkActionBusy, setBulkActionBusy] = useState(false);
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const actionMenuRef = useRef<HTMLDivElement>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedTodoIds, setSelectedTodoIds] = useState<Set<string>>(() => new Set());
  const [contextMenu, setContextMenu] = useState<{ todo: { todo_id: string; status: string; priority?: string; pinned?: boolean; has_unread?: boolean }; x: number; y: number } | null>(null);
  const longPressTimerRef = useRef<number | null>(null);
  const longPressTriggeredRef = useRef(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => {
    const saved = localStorage.getItem("todoListStatusFilter");
    return (saved === "pending" || saved === "active" || saved === "completed" || saved === "all") ? saved : "pending";
  });
  const [unreadFilter, setUnreadFilter] = useState<boolean>(() => localStorage.getItem("todoListUnreadFilter") === "true");
  useEffect(() => { localStorage.setItem("todoListStatusFilter", statusFilter); }, [statusFilter]);

  const statusParam = statusFilter === "all" ? "" : `&status=${statusFilter}`;
  const queryParam = search.trim() ? `&query=${encodeURIComponent(search.trim())}` : "";
  const unreadParam = unreadFilter ? `&unread=true` : "";

  const getKey = (pageIndex: number, previousPageData: Todo[] | null) => {
    if (!isLoggedIn) return null;
    if (previousPageData && previousPageData.length < PAGE_SIZE) return null;
    return `${API}/api/todo/list?offset=${pageIndex * PAGE_SIZE}&limit=${PAGE_SIZE}${statusParam}${queryParam}${unreadParam}`;
  };

  const { data, isLoading, error, size, setSize, isValidating, mutate } = useSWRInfinite<Todo[]>(getKey, fetcher);

  const todos = data ? data.flat() : [];
  const isReachingEnd = data && data[data.length - 1]?.length < PAGE_SIZE;
  const selectedCount = selectedTodoIds.size;

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
    setSelectedTodoIds(new Set());
  }, [statusFilter, search, unreadFilter, setSize]);

  const exitSelectMode = useCallback(() => {
    setSelectMode(false);
    setSelectedTodoIds(new Set());
  }, []);

  const toggleTodoSelection = useCallback((todoId: string) => {
    setSelectedTodoIds((current) => {
      const next = new Set(current);
      if (next.has(todoId)) next.delete(todoId);
      else next.add(todoId);
      return next;
    });
  }, []);

  const handleReadAll = async () => {
    if (readAllBusy) return;
    setReadAllBusy(true);
    try {
      const body: { status?: string; query?: string; unread?: boolean } = {};
      if (statusFilter !== "all") body.status = statusFilter;
      const q = search.trim();
      if (q) body.query = q;
      if (unreadFilter) body.unread = true;
      const res = await authFetch(`${API}/api/chat/trace/read_all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        await mutate();
        onChatListRefresh?.();
      }
    } finally {
      setReadAllBusy(false);
    }
  };

  const handleBulkMarkRead = async () => {
    if (bulkReadBusy || selectedTodoIds.size === 0) return;
    setBulkReadBusy(true);
    try {
      const res = await authFetch(`${API}/api/chat/trace/read_bulk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trace_ids: Array.from(selectedTodoIds) }),
      });
      if (res.ok) {
        await mutate();
        onChatListRefresh?.();
        exitSelectMode();
      }
    } finally {
      setBulkReadBusy(false);
    }
  };

  const bulkUpdate = async (payload: { status?: string; priority?: string; pinned?: boolean }) => {
    if (bulkActionBusy || selectedTodoIds.size === 0) return;
    if (payload.status === "deleted" && !window.confirm(`Delete ${selectedTodoIds.size} todos?`)) return;
    setBulkActionBusy(true);
    try {
      const res = await authFetch(`${API}/api/todo/bulk_update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ todo_ids: Array.from(selectedTodoIds), ...payload }),
      });
      if (res.ok) {
        await mutate();
        exitSelectMode();
      }
    } finally {
      setBulkActionBusy(false);
      setActionMenuOpen(false);
    }
  };

  useEffect(() => {
    if (!actionMenuOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (actionMenuRef.current && !actionMenuRef.current.contains(e.target as Node)) setActionMenuOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") setActionMenuOpen(false); };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [actionMenuOpen]);

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
        <div className="flex gap-1 items-center">
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
          {selectMode ? (
            <>
              <span className="ml-auto px-1.5 py-0.5 text-[0.6rem] text-sol-base01">
                {selectedCount} selected
              </span>
              <button
                onClick={handleBulkMarkRead}
                disabled={bulkReadBusy || selectedCount === 0}
                className={`px-1.5 py-0.5 rounded text-[0.6rem] transition-colors ${bulkReadBusy || selectedCount === 0 ? "bg-sol-base02 text-sol-base01 opacity-60 cursor-default" : "bg-sol-blue text-sol-base03 cursor-pointer"}`}
              >
                mark read
              </button>
              <div ref={actionMenuRef} className="relative">
                <button
                  onClick={() => setActionMenuOpen((o) => !o)}
                  disabled={selectedCount === 0 || bulkActionBusy}
                  className={`px-1.5 py-0.5 rounded text-[0.6rem] transition-colors ${selectedCount === 0 || bulkActionBusy ? "bg-sol-base02 text-sol-base01 opacity-60 cursor-default" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer"}`}
                >
                  actions {"▾"}
                </button>
                {actionMenuOpen && (
                  <div className="absolute right-0 top-full mt-1 z-50 bg-sol-base02 border border-sol-base01 rounded shadow-lg py-1 min-w-[8rem]">
                    <div className="px-2 py-0.5 text-[0.55rem] uppercase tracking-wide text-sol-base01">Status</div>
                    {BULK_STATUS_OPTIONS.map((s) => (
                      <button
                        key={s}
                        onClick={() => bulkUpdate({ status: s })}
                        className={`w-full text-left px-2.5 py-0.5 text-xs hover:bg-sol-base01/30 cursor-pointer ${BULK_STATUS_COLOR[s] || "text-sol-base0"}`}
                      >
                        {s}
                      </button>
                    ))}
                    <div className="border-t border-sol-base01/30 my-0.5" />
                    <div className="px-2 py-0.5 text-[0.55rem] uppercase tracking-wide text-sol-base01">Priority</div>
                    {BULK_PRIORITY_OPTIONS.map((p) => (
                      <button
                        key={p}
                        onClick={() => bulkUpdate({ priority: p })}
                        className={`w-full text-left px-2.5 py-0.5 text-xs hover:bg-sol-base01/30 cursor-pointer ${priorityColorClass(p)}`}
                      >
                        {p}
                      </button>
                    ))}
                    <div className="border-t border-sol-base01/30 my-0.5" />
                    <button
                      onClick={() => bulkUpdate({ pinned: true })}
                      className="w-full text-left px-2.5 py-0.5 text-xs text-sol-base0 hover:bg-sol-base01/30 cursor-pointer"
                    >
                      Pin all
                    </button>
                    <button
                      onClick={() => bulkUpdate({ pinned: false })}
                      className="w-full text-left px-2.5 py-0.5 text-xs text-sol-base0 hover:bg-sol-base01/30 cursor-pointer"
                    >
                      Unpin all
                    </button>
                  </div>
                )}
              </div>
              <button
                onClick={() => setSelectedTodoIds(new Set())}
                disabled={selectedCount === 0}
                className={`px-1.5 py-0.5 rounded text-[0.6rem] transition-colors ${selectedCount === 0 ? "bg-sol-base02 text-sol-base01 opacity-60 cursor-default" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer"}`}
              >
                clear
              </button>
              <button
                onClick={exitSelectMode}
                className="px-1.5 py-0.5 rounded text-[0.6rem] bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer transition-colors"
              >
                cancel
              </button>
            </>
          ) : (
            <>
              <button
                onClick={handleReadAll}
                disabled={readAllBusy}
                title="Mark all matching todos as read"
                className={`ml-auto px-1.5 py-0.5 rounded text-[0.6rem] transition-colors ${readAllBusy ? "bg-sol-base02 text-sol-base01 opacity-60 cursor-default" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer"}`}
              >
                read all
              </button>
              <button
                onClick={() => { const v = !unreadFilter; setUnreadFilter(v); localStorage.setItem("todoListUnreadFilter", String(v)); }}
                className={`px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer transition-colors ${unreadFilter ? "bg-sol-blue/30 text-sol-blue" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"}`}
              >
                unread
              </button>
              <button
                onClick={() => setSelectMode(true)}
                className="px-1.5 py-0.5 rounded text-[0.6rem] bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer transition-colors"
              >
                select
              </button>
            </>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view todos</p>
        ) : isLoading || isValidating ? (
          <ListLoading />
        ) : error && todos.length === 0 ? (
          <ListError error={error} />
        ) : todos.length === 0 ? (
          <ListEmpty label="todos" />
        ) : (
          <>
            {todos.map((t) => {
              const isSelected = selectedTodoIds.has(t.todo_id);
              const cancelLongPress = () => {
                if (longPressTimerRef.current !== null) {
                  window.clearTimeout(longPressTimerRef.current);
                  longPressTimerRef.current = null;
                }
              };
              return (
              <div
                key={t.todo_id}
                onClick={() => {
                  if (longPressTriggeredRef.current) {
                    longPressTriggeredRef.current = false;
                    return;
                  }
                  if (selectMode) {
                    toggleTodoSelection(t.todo_id);
                    return;
                  }
                  onSelectTodo(t.todo_id);
                }}
                onContextMenu={(e) => { e.preventDefault(); setContextMenu({ todo: { todo_id: t.todo_id, status: t.status, priority: t.priority, pinned: t.pinned, has_unread: t.has_unread }, x: e.clientX, y: e.clientY }); }}
                onPointerDown={(e) => {
                  if (e.pointerType !== "touch") return;
                  longPressTriggeredRef.current = false;
                  cancelLongPress();
                  const x = e.clientX;
                  const y = e.clientY;
                  longPressTimerRef.current = window.setTimeout(() => {
                    longPressTriggeredRef.current = true;
                    setContextMenu({ todo: { todo_id: t.todo_id, status: t.status, priority: t.priority, pinned: t.pinned, has_unread: t.has_unread }, x, y });
                  }, 500);
                }}
                onPointerMove={(e) => { if (e.pointerType === "touch") cancelLongPress(); }}
                onPointerUp={(e) => { if (e.pointerType === "touch") cancelLongPress(); }}
                onPointerCancel={cancelLongPress}
                className={`px-2 py-2 rounded-md cursor-pointer hover:bg-sol-base02 transition-colors select-none [-webkit-touch-callout:none] ${isSelected ? "bg-sol-base02 ring-1 ring-sol-blue/40" : ""}`}
              >
                <div className="flex items-center gap-1.5 mb-0.5">
                  {selectMode && (
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleTodoSelection(t.todo_id)}
                      onClick={(e) => e.stopPropagation()}
                      className="w-3 h-3 accent-sol-blue cursor-pointer shrink-0"
                      aria-label={`Select todo ${t.todo_id}`}
                    />
                  )}
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
              );
            })}
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
          onChatListRefresh={onChatListRefresh}
        />
      )}
    </div>
  );
}
