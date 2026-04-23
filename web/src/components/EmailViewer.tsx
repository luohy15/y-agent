import { useState, useCallback, useEffect, Fragment, useMemo } from "react";
import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";

interface Email {
  email_id: string;
  from_addr: string;
  date: number; // unix ms
  subject?: string;
  to_addrs?: string[];
  cc_addrs?: string[];
  content?: string;
  thread_id?: string;
}

function formatDate(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatDateTime(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function splitOwnAndQuoted(s: string | undefined): { own: string; quoted: string } {
  if (!s) return { own: "", quoted: "" };
  const match = s.search(/^>?\s*On .+wrote:\s*$/m);
  if (match < 0) return { own: s.trim(), quoted: "" };
  return { own: s.slice(0, match).trim(), quoted: s.slice(match).trim() };
}

function QuotedBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="mt-1">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className="text-sol-base01 hover:text-sol-blue text-xs cursor-pointer"
      >
        {open ? "Hide quoted" : "..."}
      </button>
      {open && (
        <pre className="text-sol-base01 text-xs whitespace-pre-wrap break-words mt-1">{text}</pre>
      )}
    </div>
  );
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "..." : s;
}

const LIMIT = 50;

export default function EmailViewer() {
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [allEmails, setAllEmails] = useState<Email[]>([]);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [prefs, setPrefs] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("emailPrefs") || "{}");
      return { sortDir: saved.sortDir || "desc", showTo: saved.showTo ?? true, showSubject: saved.showSubject ?? true };
    } catch { return { sortDir: "desc" as const, showTo: true, showSubject: true }; }
  });
  useEffect(() => { localStorage.setItem("emailPrefs", JSON.stringify(prefs)); }, [prefs]);
  const sortDir = prefs.sortDir as "desc" | "asc";
  const showTo = prefs.showTo;
  const showSubject = prefs.showSubject;
  const visibleCols = 3 + (showTo ? 1 : 0) + (showSubject ? 1 : 0);

  const params = new URLSearchParams();
  if (query) params.set("query", query);
  params.set("limit", String(LIMIT));
  params.set("offset", String(offset));

  const swrKey = `${API}/api/email/list?${params.toString()}`;

  const { data, isLoading, error } = useSWR<Email[]>(swrKey, fetcher, {
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

  const handleSearch = useCallback(() => {
    setQuery(searchInput);
    setOffset(0);
    setAllEmails([]);
    setLoadedOnce(false);
    setExpandedId(null);
  }, [searchInput]);

  const handleLoadMore = useCallback(() => {
    setOffset((prev) => prev + LIMIT);
  }, []);

  const sortedEmails = useMemo(() => {
    const sorted = [...allEmails];
    sorted.sort((a, b) => sortDir === "desc" ? b.date - a.date : a.date - b.date);
    return sorted;
  }, [allEmails, sortDir]);

  const expandedEmail = useMemo(
    () => expandedId ? allEmails.find((e) => e.email_id === expandedId) : null,
    [expandedId, allEmails],
  );

  return (
    <div className="h-full overflow-y-auto bg-sol-base03 text-sm">
      {/* Top bar */}
      <div className="sticky top-0 z-10 bg-sol-base03 border-b border-sol-base02 px-3 py-2 flex items-center gap-2 flex-wrap">
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
          placeholder="Search emails..."
          className="px-2 py-1 rounded text-xs bg-sol-base02 text-sol-base1 border border-sol-base01/20 outline-none focus:border-sol-blue placeholder:text-sol-base01 w-48"
        />
        <button
          onClick={handleSearch}
          className="px-2 py-1 rounded text-xs bg-sol-base02 text-sol-base0 hover:text-sol-base1 cursor-pointer"
        >Search</button>
        <div className="flex gap-1 ml-2">
          {([["To", "showTo", showTo], ["Subject", "showSubject", showSubject]] as const).map(([label, key, on]) => (
            <button
              key={label}
              onClick={() => setPrefs((p) => ({ ...p, [key]: !p[key] }))}
              className={`px-2 py-1 rounded text-xs cursor-pointer ${on ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"}`}
            >{label}</button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="px-3 py-2">
        {isLoading && !loadedOnce ? (
          <p className="text-sol-base01 italic">Loading...</p>
        ) : error ? (
          <p className="text-sol-red">Error loading emails</p>
        ) : allEmails.length === 0 ? (
          <p className="text-sol-base01 italic">No emails found</p>
        ) : (
          <>
            <table className="w-full border-collapse">
              <thead className="sticky top-[41px] bg-sol-base03 z-[5]">
                <tr className="text-sol-base01 text-left text-xs border-b border-sol-base02">
                  <th className="py-1 px-1.5 w-24 cursor-pointer select-none hover:text-sol-base1" onClick={() => setPrefs((p) => ({ ...p, sortDir: p.sortDir === "desc" ? "asc" : "desc" }))}>Date {sortDir === "desc" ? "\u2193" : "\u2191"}</th>
                  <th className="py-1 px-1.5 w-40">From</th>
                  {showTo && <th className="py-1 px-1.5 w-40">To</th>}
                  {showSubject && <th className="py-1 px-1.5 w-60">Subject</th>}
                  <th className="py-1 px-1.5">Content</th>
                </tr>
              </thead>
              <tbody>
                {sortedEmails.map((email) => (
                  <Fragment key={email.email_id}>
                    <tr
                      className={`border-b border-sol-base02 cursor-pointer hover:bg-sol-base02/50 ${expandedId === email.email_id ? "bg-sol-base02/50" : ""}`}
                      onClick={() => setExpandedId(expandedId === email.email_id ? null : email.email_id)}
                    >
                      <td className="py-1 px-1.5 text-sol-base01 text-xs whitespace-nowrap">{formatDate(email.date)}</td>
                      <td className="py-1 px-1.5 text-sol-base0 text-xs truncate max-w-[160px]">{email.from_addr}</td>
                      {showTo && <td className="py-1 px-1.5 text-sol-base0 text-xs truncate max-w-[160px]">{email.to_addrs?.join(", ")}</td>}
                      {showSubject && <td className="py-1 px-1.5 text-sol-base0 text-xs truncate">{truncate(email.subject || "", 80)}</td>}
                      <td className="py-1 px-1.5 text-sol-base0 text-xs">{splitOwnAndQuoted(email.content).own.replace(/\n+/g, " ")}</td>
                    </tr>
                    {expandedId === email.email_id && expandedEmail && (
                      <tr className="border-b border-sol-base02">
                        <td colSpan={visibleCols} className="p-2">
                          <div className="bg-sol-base02 rounded p-3 border border-sol-base01/20 relative">
                            <button
                              onClick={(e) => { e.stopPropagation(); setExpandedId(null); }}
                              className="absolute top-1 right-2 text-sol-base01 hover:text-sol-base1 cursor-pointer text-xs"
                            >&times;</button>
                            <div className="space-y-1 text-xs mb-2">
                              <div><span className="text-sol-base01">From:</span> <span className="text-sol-base0">{expandedEmail.from_addr}</span></div>
                              {expandedEmail.to_addrs && expandedEmail.to_addrs.length > 0 && (
                                <div><span className="text-sol-base01">To:</span> <span className="text-sol-base0">{expandedEmail.to_addrs.join(", ")}</span></div>
                              )}
                              {expandedEmail.cc_addrs && expandedEmail.cc_addrs.length > 0 && (
                                <div><span className="text-sol-base01">Cc:</span> <span className="text-sol-base0">{expandedEmail.cc_addrs.join(", ")}</span></div>
                              )}
                              <div><span className="text-sol-base01">Date:</span> <span className="text-sol-base0">{formatDateTime(expandedEmail.date)}</span></div>
                              {expandedEmail.subject && (
                                <div><span className="text-sol-base01">Subject:</span> <span className="text-sol-base1 font-medium">{expandedEmail.subject}</span></div>
                              )}
                            </div>
                            {expandedEmail.content && (() => {
                              const { own, quoted } = splitOwnAndQuoted(expandedEmail.content);
                              return (
                                <div className="border-t border-sol-base01/20 pt-2">
                                  <pre className="text-sol-base0 text-xs whitespace-pre-wrap break-words">{own}</pre>
                                  <QuotedBlock text={quoted} />
                                </div>
                              );
                            })()}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
            {hasMore && (
              <button
                onClick={handleLoadMore}
                disabled={isLoading}
                className="w-full py-2 text-center text-xs rounded bg-sol-base02 text-sol-base0 hover:text-sol-base1 cursor-pointer disabled:opacity-50 mt-2 mb-4"
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
