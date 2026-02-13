import { useState } from "react";
import useSWR from "swr";
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
}

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

export default function ChatList({ isLoggedIn, selectedChatId, onSelectChat }: ChatListProps) {
  const [search, setSearch] = useState("");
  const queryParam = search.trim() ? `?query=${encodeURIComponent(search.trim())}` : "";
  const { data: chats, error, isLoading } = useSWR<Chat[]>(
    isLoggedIn ? `${API}/api/chat/list${queryParam}` : null,
    fetcher,
  );

  const handleClick = (id: string) => {
    onSelectChat(selectedChatId === id ? null : id);
  };

  return (
    <div className="w-80 min-w-[260px] border-r border-sol-base02 flex flex-col shrink-0">
      <div className="p-3 border-b border-sol-base02">
        <input
          type="text"
          placeholder="Search chats..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-2.5 py-1.5 bg-sol-base02 border border-sol-base01 rounded-md text-sm text-sol-base0 outline-none focus:border-sol-blue"
          autoFocus
        />
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic text-sm p-3">Sign in to view chats</p>
        ) : isLoading ? (
          <p className="text-sol-base01 italic text-sm p-3">Loading...</p>
        ) : error ? (
          <p className="text-sol-base01 italic text-sm p-3">Error loading chats</p>
        ) : !chats || chats.length === 0 ? (
          <p className="text-sol-base01 italic text-sm p-3">{search ? "No matching chats" : "No chats yet"}</p>
        ) : (
          chats.map((c) => {
            const sel = c.chat_id === selectedChatId;
            const dt = c.updated_at || c.created_at ? new Date(c.updated_at || c.created_at!) : null;
            const date = dt ? dt.toLocaleDateString([], { year: "numeric", month: "2-digit", day: "2-digit" }) : "";
            const time = dt ? dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
            return (
              <div
                key={c.chat_id}
                onClick={() => handleClick(c.chat_id)}
                className={`flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer hover:bg-sol-base02 transition-colors ${
                  sel ? "ring-1 ring-sol-blue bg-sol-base02/50" : ""
                }`}
              >
                <span className="flex-1 truncate text-sm">{c.title || ""}</span>
                <span className="text-[0.65rem] text-sol-base01 shrink-0 text-right">{date}<br/>{time}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
