import { useState, useCallback, useRef, useEffect } from "react";
import useSWRInfinite from "swr/infinite";
import { API, authFetch, clearToken } from "../api";

interface Chat {
  chat_id: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
}

interface ChatListProps {
  isLoggedIn: boolean;
  selectedChatId: string | null;
  onSelectChat: (id: string | null) => void;
  refreshKey?: number;
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

export default function ChatList({ isLoggedIn, selectedChatId, onSelectChat, refreshKey }: ChatListProps) {
  const [search, setSearch] = useState("");
  const queryParam = search.trim() ? `&query=${encodeURIComponent(search.trim())}` : "";

  const getKey = (pageIndex: number, previousPageData: Chat[] | null) => {
    if (!isLoggedIn) return null;
    if (previousPageData && previousPageData.length < PAGE_SIZE) return null; // reached end
    return `${API}/api/chat/list?offset=${pageIndex * PAGE_SIZE}&limit=${PAGE_SIZE}${queryParam}`;
  };

  const { data, error, isLoading, size, setSize, isValidating, mutate } = useSWRInfinite<Chat[]>(getKey, fetcher);

  const chats = data ? data.flat() : [];
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

  // Reset pagination when search changes
  useEffect(() => {
    setSize(1);
  }, [search, setSize]);

  // Revalidate when parent signals a chat completed
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    mutate();
  }, [refreshKey, mutate]);

  const handleClick = (id: string) => {
    onSelectChat(selectedChatId === id ? null : id);
  };

  return (
    <div className="h-full bg-sol-base03 flex flex-col text-xs sm:text-[0.65rem]">
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <input
          type="text"
          placeholder="Search tasks..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
        />
      </div>
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
              const date = dt ? dt.toLocaleDateString([], { year: "numeric", month: "2-digit", day: "2-digit" }) : "";
              const time = dt ? dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
              return (
                <div
                  key={c.chat_id}
                  onClick={() => handleClick(c.chat_id)}
                  className={`flex items-center gap-1.5 px-2 py-1.5 rounded-md cursor-pointer hover:bg-sol-base02 transition-colors ${
                    sel ? "ring-1 ring-sol-blue bg-sol-base02/50" : ""
                  }`}
                >
                  <span className="flex-1 truncate">{c.title || ""}</span>
                  <span className="text-[0.65rem] sm:text-[0.5rem] text-sol-base01 shrink-0 text-right">{date}<br/>{time}</span>
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
