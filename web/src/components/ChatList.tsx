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
    <div className="h-full bg-sol-base03 flex flex-col text-[0.65rem]">
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <button
          onClick={() => onSelectChat(null)}
          disabled={!isLoggedIn}
          className="w-full px-2 py-1 bg-sol-blue text-sol-base03 rounded-md font-semibold cursor-pointer disabled:opacity-40 disabled:cursor-default"
        >
          + New Task
        </button>
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
        ) : !chats || chats.length === 0 ? (
          <p className="text-sol-base01 italic p-2">{search ? "No matching tasks" : "No tasks yet"}</p>
        ) : (
          chats.map((c) => {
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
                <span className="text-[0.5rem] text-sol-base01 shrink-0 text-right">{date}<br/>{time}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
