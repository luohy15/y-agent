import { useState, useEffect, useMemo, useCallback } from "react";
import useSWR from "swr";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { ListEmpty, ListError, ListLoading } from "./ListStates";
import { emailSnippet, formatEmailDate } from "../utils/email";

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
  account?: string;
}

interface EmailAccount {
  address: string;
}

const LIMIT = 50;

interface EmailListProps {
  isLoggedIn: boolean;
  selectedThreadId?: string | null;
  onSelectEmail: (email: Email) => void;
  refreshKey?: number;
}

function ManageAccountsModal({ accounts, onClose, onChanged }: {
  accounts: EmailAccount[];
  onClose: () => void;
  onChanged: () => Promise<unknown>;
}) {
  const [address, setAddress] = useState("");
  const [appPassword, setAppPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleAdd = useCallback(async () => {
    const addr = address.trim();
    const pwd = appPassword.trim();
    if (!addr || !pwd) return;
    setSubmitting(true);
    setErr(null);
    try {
      const res = await authFetch(`${API}/api/email/account`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: addr, app_password: pwd }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      setAddress("");
      setAppPassword("");
      await onChanged();
    } catch (e: any) {
      setErr(e?.message || "Failed to add account");
    } finally {
      setSubmitting(false);
    }
  }, [address, appPassword, onChanged]);

  const handleRemove = useCallback(async (addr: string) => {
    if (!window.confirm(`Remove account ${addr}? Synced emails are kept.`)) return;
    setErr(null);
    try {
      const res = await authFetch(`${API}/api/email/account/${encodeURIComponent(addr)}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await onChanged();
    } catch (e: any) {
      setErr(e?.message || "Failed to remove account");
    }
  }, [onChanged]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="w-80 max-w-[90vw] bg-sol-base03 border border-sol-base01 rounded-lg p-3 text-xs flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <span className="text-sol-base1 font-medium">Gmail accounts</span>
          <button onClick={onClose} className="text-sol-base01 hover:text-sol-base0 cursor-pointer" title="Close">✕</button>
        </div>
        {accounts.length === 0 ? (
          <p className="text-sol-base01 italic">No accounts registered</p>
        ) : (
          <div className="flex flex-col">
            {accounts.map((a) => (
              <div key={a.address} className="flex items-center gap-1.5 py-1 border-b border-sol-base02">
                <span className="flex-1 truncate text-sol-base0">{a.address}</span>
                <button
                  onClick={() => handleRemove(a.address)}
                  className="shrink-0 text-sol-base01 hover:text-sol-red cursor-pointer"
                  title="Remove account"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
        <input
          type="text"
          placeholder="Gmail address"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          className="px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
        />
        <input
          type="password"
          placeholder="App password"
          value={appPassword}
          onChange={(e) => setAppPassword(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
          className="px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
        />
        {err && <p className="text-sol-red break-words">{err}</p>}
        <button
          onClick={handleAdd}
          disabled={submitting || !address.trim() || !appPassword.trim()}
          className="px-2 py-1 bg-sol-blue text-sol-base03 rounded-md font-medium cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed hover:bg-sol-cyan"
        >
          {submitting ? "Adding..." : "Add account"}
        </button>
      </div>
    </div>
  );
}

export default function EmailList({ isLoggedIn, selectedThreadId, onSelectEmail, refreshKey }: EmailListProps) {
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [account, setAccount] = useState("");
  const [manageOpen, setManageOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const [allEmails, setAllEmails] = useState<Email[]>([]);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [spinning, setSpinning] = useState(false);

  const { data: accounts, mutate: mutateAccounts } = useSWR<EmailAccount[]>(
    isLoggedIn ? `${API}/api/email/account/list` : null, fetcher, { revalidateOnFocus: false },
  );

  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (account) params.set("account", account);
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

  const handleAccountChange = useCallback((value: string) => {
    setAccount(value);
    setOffset(0);
    setAllEmails([]);
    setLoadedOnce(false);
  }, []);

  // Clear the filter if the selected account was removed.
  useEffect(() => {
    if (account && accounts && !accounts.some((a) => a.address === account)) {
      handleAccountChange("");
    }
  }, [account, accounts, handleAccountChange]);

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
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <div className="flex gap-1.5">
          <input
            type="text"
            placeholder="Search emails..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
            className="flex-1 min-w-0 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
          />
          <button
            onClick={() => { mutate(); setSpinning(true); setTimeout(() => setSpinning(false), 600); }}
            className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
            title="Refresh"
          >
            <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
          <button
            onClick={() => setManageOpen(true)}
            className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
            title="Manage accounts"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>
        </div>
        {accounts && accounts.length > 1 && (
          <select
            value={account}
            onChange={(e) => handleAccountChange(e.target.value)}
            className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue text-[0.7rem]"
            title="Filter by account"
          >
            <option value="">All accounts</option>
            {accounts.map((a) => (
              <option key={a.address} value={a.address}>{a.address}</option>
            ))}
          </select>
        )}
      </div>
      {manageOpen && (
        <ManageAccountsModal
          accounts={accounts || []}
          onClose={() => setManageOpen(false)}
          onChanged={mutateAccounts}
        />
      )}
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
              const snippet = emailSnippet(email.content);
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
