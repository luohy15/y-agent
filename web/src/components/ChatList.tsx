import { useState, useCallback, useRef, useEffect } from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import { API, authFetch, clearToken } from "../api";
import { TRACE_BADGE, CHAT_BADGE, topicBadgeClass } from "./badges";
import { formatDateTime } from "../utils/formatTime";

interface Chat {
  chat_id: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
  topic?: string;
  trace_id?: string;
  backend?: string;
  status?: string;
  unread?: boolean;
}

interface ChatListProps {
  isLoggedIn: boolean;
  selectedChatId: string | null;
  onSelectChat: (id: string | null) => void;
  refreshKey?: number;
  traceId?: string | null;
  onClearTraceId?: () => void;
  onSelectTrace?: (traceId: string) => void;
  hideFilters?: boolean;
}

const PAGE_SIZE = 50;

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

export default function ChatList({ isLoggedIn, selectedChatId, onSelectChat, refreshKey, traceId: externalTraceId, onClearTraceId, onSelectTrace, hideFilters }: ChatListProps) {
  const [search, setSearch] = useState("");
  const [spinning, setSpinning] = useState(false);
  const [internalTraceId, setInternalTraceId] = useState("");
  const [topicFilter, setTopicFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>(() => localStorage.getItem("chatStatusFilter") || "");
  const [unreadFilter, setUnreadFilter] = useState<boolean>(() => localStorage.getItem("chatUnreadFilter") === "true");
  const traceId = externalTraceId || internalTraceId;
  const queryParam = search.trim() ? `&query=${encodeURIComponent(search.trim())}` : "";
  const traceIdParam = traceId.trim() ? `&trace_id=${encodeURIComponent(traceId.trim())}` : "";
  const topicParam = topicFilter.trim() ? `&topic=${encodeURIComponent(topicFilter.trim())}` : "";
  const statusParam = statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : "";
  const unreadParam = unreadFilter ? `&unread=true` : "";

  const getKey = (pageIndex: number, previousPageData: Chat[] | null) => {
    if (!isLoggedIn) return null;
    if (previousPageData && previousPageData.length < PAGE_SIZE) return null; // reached end
    return `${API}/api/chat/list?offset=${pageIndex * PAGE_SIZE}&limit=${PAGE_SIZE}${queryParam}${traceIdParam}${topicParam}${statusParam}${unreadParam}`;
  };

  const { data, error, isLoading, size, setSize, isValidating, mutate } = useSWRInfinite<Chat[]>(getKey, fetcher);

  // Separate fetch for pinned manager chat (always visible)
  const { data: pinnedManagerData, mutate: mutatePinnedManager } = useSWR<Chat[]>(
    isLoggedIn ? `${API}/api/chat/list?offset=0&limit=1&role=manager` : null,
    fetcher,
  );
  const pinnedManager = pinnedManagerData?.[0] ?? null;

  const allChats = data ? data.flat() : [];
  const chats = pinnedManager ? allChats.filter((c) => c.chat_id !== pinnedManager.chat_id) : allChats;
  const isLoadingMore = isLoading || (size > 0 && data && typeof data[size - 1] === "undefined");
  const isEmpty = data?.[0]?.length === 0;
  const isReachingEnd = isEmpty || (data && data[data.length - 1]?.length < PAGE_SIZE);

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

  // Reset pagination when search or filter changes
  useEffect(() => {
    setSize(1);
  }, [search, traceId, externalTraceId, topicFilter, statusFilter, unreadFilter, setSize]);

  // Revalidate when parent signals a chat completed
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    mutate();
    mutatePinnedManager();
  }, [refreshKey, mutate, mutatePinnedManager]);

  const handleClick = (id: string) => {
    onSelectChat(id);
    // Optimistically update SWR data
    mutate((pages) => pages?.map((page) => page.map((c) => c.chat_id === id ? { ...c, unread: false } : c)), false);
    mutatePinnedManager((dm) => dm && dm.length > 0 && dm[0].chat_id === id ? [{ ...dm[0], unread: false }] : dm, false);
  };

  return (
    <div className="h-full bg-sol-base03 flex flex-col text-xs sm:text-[0.65rem]">
      {!hideFilters && (
        <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
          <div className="flex gap-1.5">
            <input
              type="text"
              placeholder="Search tasks..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
            />
            <button
              onClick={() => { mutate(); mutatePinnedManager(); setSpinning(true); setTimeout(() => setSpinning(false), 600); }}
              className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
              title="Refresh"
            >
              <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            </button>
          </div>
          <div className="flex gap-1.5">
            <div className="relative flex-1">
              <input
                type="text"
                placeholder="Todo ID..."
                value={traceId}
                onChange={(e) => setInternalTraceId(e.target.value)}
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
                readOnly={!!externalTraceId}
              />
              {(externalTraceId || internalTraceId) && (
                <button
                  onClick={() => { if (onClearTraceId) onClearTraceId(); setInternalTraceId(""); }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-sol-base01 hover:text-sol-base1 cursor-pointer"
                  title="Clear todo filter"
                >
                  ✕
                </button>
              )}
            </div>
            <div className="relative w-24">
              <input
                type="text"
                placeholder="Skill..."
                value={topicFilter}
                onChange={(e) => setTopicFilter(e.target.value)}
                className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
              />
              {topicFilter && (
                <button
                  onClick={() => setTopicFilter("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-sol-base01 hover:text-sol-base1 cursor-pointer"
                  title="Clear skill filter"
                >
                  ✕
                </button>
              )}
            </div>
          </div>
          <div className="flex gap-1">
            <button
              onClick={() => { const v = statusFilter === "running" ? "" : "running"; setStatusFilter(v); localStorage.setItem("chatStatusFilter", v); }}
              className={`px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer transition-colors ${statusFilter === "running" ? "bg-sol-blue/30 text-sol-blue" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"}`}
            >
              running
            </button>
            <button
              onClick={() => { const v = !unreadFilter; setUnreadFilter(v); localStorage.setItem("chatUnreadFilter", String(v)); }}
              className={`px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer transition-colors ${unreadFilter ? "bg-sol-blue/30 text-sol-blue" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"}`}
            >
              unread
            </button>
          </div>
        </div>
      )}
      {pinnedManager && (
        <div className="border-b border-sol-base02 p-1.5">
          <div
            onClick={() => handleClick(pinnedManager.chat_id)}
            className={`px-2 py-1.5 rounded-md cursor-pointer hover:bg-sol-base02 transition-colors border-l-2 border-sol-blue ${
              pinnedManager.chat_id === selectedChatId ? "ring-1 ring-sol-blue bg-sol-base02/50" : ""
            }`}
          >
            <div className="flex items-center gap-1 mb-0.5">
              <span className={`text-[0.55rem] ${topicBadgeClass("manager")}`}>manager</span>
              <button
                onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(pinnedManager.chat_id); }}
                className={`gap-0.5 text-[0.55rem] cursor-pointer ${CHAT_BADGE}`}
                title="Copy chat ID"
              >
                <svg className="w-2.5 h-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                {pinnedManager.chat_id.slice(0, 8)}
              </button>
            </div>
            <div className="flex items-center gap-1.5">
              {pinnedManager.unread && <span className="w-1.5 h-1.5 rounded-full bg-sol-blue shrink-0" />}
              {pinnedManager.status === "running" && (
                <svg className="w-3 h-3 text-sol-blue animate-spin shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
              )}
              {pinnedManager.status === "interrupted" && (
                <svg className="w-3 h-3 text-sol-orange shrink-0" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></svg>
              )}
              <span className="flex-1 truncate">{(pinnedManager.title || "").replace(/^\[.*?\]\s*/, "")}</span>
              {(() => {
                const dt = pinnedManager.updated_at || pinnedManager.created_at ? new Date(pinnedManager.updated_at || pinnedManager.created_at!) : null;
                if (!dt) return null;
                const { date, time } = formatDateTime(dt);
                return <span className="text-[0.65rem] sm:text-[0.5rem] text-sol-base01 shrink-0 text-right">{date}<br/>{time}</span>;
              })()}
            </div>
          </div>
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view tasks</p>
        ) : isLoading ? (
          <p className="text-sol-base01 italic p-2">Loading...</p>
        ) : error ? (
          <p className="text-sol-base01 italic p-2">Error loading tasks</p>
        ) : chats.length === 0 ? (
          <p className="text-sol-base01 italic p-2">{search ? "No matching tasks" : "No tasks yet"}</p>
        ) : (
          <>
            {chats.map((c) => {
              const sel = c.chat_id === selectedChatId;
              const dt = c.updated_at || c.created_at ? new Date(c.updated_at || c.created_at!) : null;
              const { date, time } = dt ? formatDateTime(dt) : { date: "", time: "" };
              const displayTitle = (c.title || "").replace(/^\[.*?\]\s*/, "");
              const firstTraceId = c.trace_id;
              return (
                <div
                  key={c.chat_id}
                  onClick={() => handleClick(c.chat_id)}
                  className={`px-2 py-1.5 rounded-md cursor-pointer hover:bg-sol-base02 transition-colors ${
                    sel ? "ring-1 ring-sol-blue bg-sol-base02/50" : ""
                  }`}
                >
                  {(firstTraceId || c.chat_id || c.topic) && (
                    <div className="flex items-center gap-1 mb-0.5">
                      {firstTraceId && (
                        <button
                          onClick={(e) => { e.stopPropagation(); if (onSelectTrace) onSelectTrace(firstTraceId); else navigator.clipboard.writeText(firstTraceId); }}
                          className={`text-[0.55rem] cursor-pointer ${TRACE_BADGE}`}
                          title="View trace"
                        >
                          #{firstTraceId.slice(0, 8)}
                        </button>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(c.chat_id); }}
                        className={`gap-0.5 text-[0.55rem] cursor-pointer ${CHAT_BADGE}`}
                        title="Copy chat ID"
                      >
                        <svg className="w-2.5 h-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                        {c.chat_id.slice(0, 8)}
                      </button>
                      {c.topic && <span className={`text-[0.55rem] truncate ${topicBadgeClass(c.topic)}`}>{c.topic}</span>}
                      {c.backend && <span className="inline-flex items-center px-1 py-0.5 rounded font-mono font-medium shrink-0 text-[0.55rem] bg-sol-base01/20 text-sol-base01">{c.backend}</span>}
                    </div>
                  )}
                  <div className="flex items-center gap-1.5">
                    {c.unread && <span className="w-1.5 h-1.5 rounded-full bg-sol-blue shrink-0" />}
                    {c.status === "running" && (
                      <svg className="w-3 h-3 text-sol-blue animate-spin shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
                    )}
                    {c.status === "interrupted" && (
                      <svg className="w-3 h-3 text-sol-orange shrink-0" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></svg>
                    )}
                    <span className="flex-1 truncate">{displayTitle}</span>
                    <span className="text-[0.65rem] sm:text-[0.5rem] text-sol-base01 shrink-0 text-right">{date}<br/>{time}</span>
                  </div>
                </div>
              );
            })}
            {!isReachingEnd && (
              <div ref={sentinelRef} className="py-2 text-center text-sol-base01 italic">
                {isLoadingMore ? "Loading..." : ""}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
