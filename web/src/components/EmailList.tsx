import { useState, useEffect, useMemo, useCallback } from "react";
import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";
import { ListEmpty, ListError, ListLoading } from "./ListStates";
import { formatEmailDate, splitOwnAndQuoted } from "../utils/email";

interface Email {
  email_id: string;
  from_addr: string;
  date: number; // unix ms
  subject?: string;
  to_addrs?: string[];
  cc_addrs?: string[];
  content?: string;
  thread_id?: string;
  thread_count?: number;
}

const LIMIT = 50;

interface EmailListProps {
  isLoggedIn: boolean;
  selectedThreadId?: string | null;
  onSelectEmail: (email: Email) => void;
  refreshKey?: number;
}

export default function EmailList({ isLoggedIn, selectedThreadId, onSelectEmail, refreshKey }: EmailListProps) {
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [allEmails, setAllEmails] = useState<Email[]>([]);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [spinning, setSpinning] = useState(false);

  const params = new URLSearchParams();
  if (query) params.set("query", query);
  params.set("limit", String(LIMIT));
  params.set("offset", String(offset));

  const swrKey = isLoggedIn ? `${API}/api/email/threads?${params.toString()}` : null;

  const { data, isLoading, isValidating, error, mutate } = useSWR<Email[]>(swrKey, fetcher, {
    onSuccess: (newData) => {
      if (offset === 0) {
        setAllEmails(newData);
      } else {
        setAllEmails((prev) => [...prev, ...newData]);
      }
      setLoadedOnce(true);
    },
    revalidateOnFocus: false,
  });

  const hasMore = data && data.length === LIMIT;

  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    if (offset === 0) {
      mutate();
      return;
    }
    setOffset(0);
    setAllEmails([]);
    setLoadedOnce(false);
  }, [refreshKey, offset, mutate]);

  const handleSearch = useCallback(() => {
    setQuery(searchInput);
    setOffset(0);
    setAllEmails([]);
    setLoadedOnce(false);
  }, [searchInput]);

  const handleLoadMore = useCallback(() => {
    setOffset((prev) => prev + LIMIT);
  }, []);

  const sortedEmails = useMemo(() => {
    const sorted = [...allEmails];
    sorted.sort((a, b) => b.date - a.date);
    return sorted;
  }, [allEmails]);

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 flex gap-1.5">
        <input
          type="text"
          placeholder="Search emails..."
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
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
      <div className="flex-1 overflow-y-auto">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view emails</p>
        ) : (isLoading || isValidating) && !loadedOnce ? (
          <ListLoading />
        ) : error && allEmails.length === 0 ? (
          <ListError error={error} />
        ) : allEmails.length === 0 ? (
          <ListEmpty label="emails" />
        ) : (
          <>
            {sortedEmails.map((email) => {
              const snippet = splitOwnAndQuoted(email.content).own.replace(/\n+/g, " ").trim();
              const threadKey = email.thread_id || email.email_id;
              const active = threadKey === selectedThreadId;
              const count = email.thread_count || 0;
              return (
                <button
                  key={threadKey}
                  onClick={() => onSelectEmail(email)}
                  className={`w-full text-left flex flex-col gap-0.5 px-2 py-1.5 border-b border-sol-base02 cursor-pointer ${active ? "bg-sol-base02" : "hover:bg-sol-base02/50"}`}
                  title={email.subject || email.from_addr}
                >
                  <div className="flex items-center gap-1.5">
                    <span className={`truncate flex-1 text-[0.7rem] ${active ? "text-sol-base1" : "text-sol-base0"}`}>{email.from_addr}</span>
                    <span className="shrink-0 text-sol-base01 text-[0.6rem]">{formatEmailDate(email.date)}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className={`truncate flex-1 text-[0.7rem] font-medium ${active ? "text-sol-base1" : "text-sol-base0"}`}>{email.subject || "(no subject)"}</span>
                    {count > 1 && <span className="shrink-0 px-1 rounded-full bg-sol-base01 text-sol-base03 text-[0.55rem] font-medium">{count}</span>}
                  </div>
                  {snippet && <span className="truncate text-sol-base01 text-[0.65rem]">{snippet}</span>}
                </button>
              );
            })}
            {hasMore && (
              <button
                onClick={handleLoadMore}
                disabled={isLoading}
                className="w-full py-1.5 text-center text-[0.6rem] rounded bg-sol-base02 text-sol-base0 hover:text-sol-base1 cursor-pointer disabled:opacity-50 my-1.5"
              >
                {isLoading ? "Loading..." : "Load more"}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export type { Email };
