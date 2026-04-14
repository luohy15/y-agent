import { useState, useMemo, useCallback, useEffect } from "react";
import { createPortal } from "react-dom";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";

interface FileEntry {
  name: string;
  type: string;
  atime?: number | null;
}

interface NoteListProps {
  isLoggedIn: boolean;
  vmName?: string | null;
  workDir?: string | null;
  onOpenFile: (path: string) => void;
}

type NoteTab = "journals" | "pages";

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

function formatMonth(dateStr: string): string {
  // dateStr like "2026-04-12.md" → extract YYYY-MM
  const match = dateStr.match(/^(\d{4})-(\d{2})/);
  if (!match) return "Other";
  const d = new Date(parseInt(match[1]), parseInt(match[2]) - 1, 1);
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function formatAtime(ts: number): string {
  const d = new Date(ts * 1000);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  const yy = String(d.getFullYear()).slice(2);
  return `${yy}-${mm}-${dd} ${hh}:${min}`;
}

function groupByMonth(files: string[]): [string, string[]][] {
  const groups = new Map<string, string[]>();
  for (const f of files) {
    const match = f.match(/^(\d{4}-\d{2})/);
    const key = match ? match[1] : "other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(f);
  }
  // Sort months descending, "other" always last
  return [...groups.entries()].sort((a, b) => {
    if (a[0] === "other") return 1;
    if (b[0] === "other") return -1;
    return b[0].localeCompare(a[0]);
  });
}

export default function NoteList({ isLoggedIn, vmName, workDir, onOpenFile }: NoteListProps) {
  const [tab, setTab] = useState<NoteTab>(() => {
    const saved = localStorage.getItem("noteListTab");
    return saved === "journals" || saved === "pages" ? saved : "journals";
  });
  const [searchInput, setSearchInput] = useState("");
  const [journalYear, setJournalYear] = useState<string>(() => localStorage.getItem("noteListJournalYear") || "");
  const [journalMonth, setJournalMonth] = useState<string>(() => localStorage.getItem("noteListJournalMonth") || "");

  const handleTabChange = useCallback((t: NoteTab) => {
    setTab(t);
    localStorage.setItem("noteListTab", t);
  }, []);

  const journalsParams = new URLSearchParams();
  journalsParams.set("path", "journals");
  if (vmName) journalsParams.set("vm_name", vmName);

  const pagesParams = new URLSearchParams();
  pagesParams.set("path", "pages");
  pagesParams.set("sort", "atime");
  if (vmName) pagesParams.set("vm_name", vmName);

  const journalsKey = isLoggedIn && tab === "journals" ? `${API}/api/file/list?${journalsParams.toString()}` : null;
  const pagesKey = isLoggedIn && tab === "pages" ? `${API}/api/file/list?${pagesParams.toString()}` : null;

  const { data: journalsData, isLoading: journalsLoading, error: journalsError, mutate: mutateJournals } = useSWR<{ path: string; entries: FileEntry[] }>(journalsKey, fetcher, { revalidateOnFocus: false });
  const { data: pagesData, isLoading: pagesLoading, error: pagesError, mutate: mutatePages } = useSWR<{ path: string; entries: FileEntry[] }>(pagesKey, fetcher, { revalidateOnFocus: false });
  const [spinning, setSpinning] = useState(false);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; path: string } | null>(null);

  const dismissCtxMenu = useCallback(() => setCtxMenu(null), []);

  const copyPath = useCallback(() => {
    if (!ctxMenu) return;
    navigator.clipboard.writeText(ctxMenu.path);
    setCtxMenu(null);
  }, [ctxMenu]);

  useEffect(() => {
    if (!ctxMenu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setCtxMenu(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [ctxMenu]);

  // Journals: filter .md files, sort by name descending
  const journalFiles = useMemo(() => {
    if (!journalsData?.entries) return [];
    return journalsData.entries
      .filter((e) => e.type === "file" && e.name.endsWith(".md"))
      .map((e) => e.name)
      .sort((a, b) => b.localeCompare(a));
  }, [journalsData]);

  // Extract unique years from journal filenames, sorted descending
  const journalYears = useMemo(() => {
    const years = new Set<string>();
    for (const f of journalFiles) {
      const match = f.match(/^(\d{4})-/);
      if (match) years.add(match[1]);
    }
    return [...years].sort((a, b) => b.localeCompare(a));
  }, [journalFiles]);

  // Extract months that have entries for the selected year
  const journalMonths = useMemo(() => {
    if (!journalYear) return [];
    const months = new Set<string>();
    for (const f of journalFiles) {
      const match = f.match(/^(\d{4})-(\d{2})/);
      if (match && match[1] === journalYear) months.add(match[2]);
    }
    return [...months].sort();
  }, [journalFiles, journalYear]);

  const handleYearChange = useCallback((y: string) => {
    setJournalYear(y);
    localStorage.setItem("noteListJournalYear", y);
    // Reset month when year changes
    setJournalMonth("");
    localStorage.setItem("noteListJournalMonth", "");
  }, []);

  const handleMonthChange = useCallback((m: string) => {
    setJournalMonth(m);
    localStorage.setItem("noteListJournalMonth", m);
  }, []);

  // Filter journals by year/month before grouping
  const filteredJournalFiles = useMemo(() => {
    if (!journalYear) return journalFiles;
    return journalFiles.filter((f) => {
      const match = f.match(/^(\d{4})-(\d{2})/);
      if (!match) return false;
      if (match[1] !== journalYear) return false;
      if (journalMonth && match[2] !== journalMonth) return false;
      return true;
    });
  }, [journalFiles, journalYear, journalMonth]);

  const journalGroups = useMemo(() => groupByMonth(filteredJournalFiles), [filteredJournalFiles]);

  // Pages: filter .md files, apply search, preserve FileEntry for atime
  const pageFiles = useMemo(() => {
    if (!pagesData?.entries) return [];
    let files = pagesData.entries.filter((e) => e.type === "file" && e.name.endsWith(".md"));
    if (searchInput) {
      const q = searchInput.toLowerCase();
      files = files.filter((f) => f.name.toLowerCase().includes(q));
    }
    return files;
  }, [pagesData, searchInput]);

  const tabClass = (active: boolean) =>
    `px-2 py-0.5 rounded text-[0.65rem] cursor-pointer ${active ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"}`;

  const pillClass = (active: boolean) =>
    `px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer ${active ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"}`;

  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <div className="flex gap-1 items-center">
          <button onClick={() => handleTabChange("journals")} className={tabClass(tab === "journals")}>Journals</button>
          <button onClick={() => handleTabChange("pages")} className={tabClass(tab === "pages")}>Pages</button>
          <button
            onClick={() => { if (tab === "journals") mutateJournals(); else mutatePages(); setSpinning(true); setTimeout(() => setSpinning(false), 600); }}
            className="ml-auto px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
            title="Refresh"
          >
            <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
        </div>
        {tab === "journals" && journalYears.length > 0 && (
          <>
            <div className="flex gap-1 flex-wrap">
              <button onClick={() => handleYearChange("")} className={pillClass(!journalYear)}>All</button>
              {journalYears.map((y) => (
                <button key={y} onClick={() => handleYearChange(y)} className={pillClass(journalYear === y)}>{y}</button>
              ))}
            </div>
            {journalYear && journalMonths.length > 0 && (
              <div className="flex gap-1 flex-wrap">
                <button onClick={() => handleMonthChange("")} className={pillClass(!journalMonth)}>All</button>
                {journalMonths.map((m) => (
                  <button key={m} onClick={() => handleMonthChange(m)} className={pillClass(journalMonth === m)}>{monthNames[parseInt(m) - 1]}</button>
                ))}
              </div>
            )}
          </>
        )}
        {tab === "pages" && (
          <input
            type="text"
            placeholder="Search pages..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="flex-1 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
          />
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view notes</p>
        ) : tab === "journals" ? (
          journalsLoading ? (
            <p className="text-sol-base01 italic p-2">Loading...</p>
          ) : journalsError ? (
            <p className="text-sol-base01 italic p-2">Error loading journals</p>
          ) : journalGroups.length === 0 ? (
            <p className="text-sol-base01 italic p-2">No journals found</p>
          ) : (
            journalGroups.map(([monthKey, files]) => (
              <div key={monthKey} className="mb-2">
                <div className="text-sol-base01 text-[0.6rem] font-medium mb-1 px-1 sticky top-0 bg-sol-base03 py-0.5 z-[5] border-b border-sol-base02">
                  {formatMonth(files[0])}
                </div>
                <div className="space-y-0">
                  {files.map((file) => (
                    <button
                      key={file}
                      onClick={() => onOpenFile(workDir ? `${workDir}/journals/${file}` : `journals/${file}`)}
                      onContextMenu={(e) => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, path: workDir ? `${workDir}/journals/${file}` : `journals/${file}` }); }}
                      className="w-full text-left flex items-center gap-1.5 py-0.5 px-1 rounded hover:bg-sol-base02/50 text-sol-base0 hover:text-sol-blue text-[0.7rem] cursor-pointer"
                    >
                      {(() => {
                        const name = file.replace(/\.md$/, "");
                        const m = name.match(/^(\d{4})-(\d{2})-(\d{2})$/);
                        if (!m) return name;
                        const d = new Date(parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3]));
                        const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
                        return `${name}  ${days[d.getDay()]}`;
                      })()}
                    </button>
                  ))}
                </div>
              </div>
            ))
          )
        ) : (
          pagesLoading ? (
            <p className="text-sol-base01 italic p-2">Loading...</p>
          ) : pagesError ? (
            <p className="text-sol-base01 italic p-2">Error loading pages</p>
          ) : pageFiles.length === 0 ? (
            <p className="text-sol-base01 italic p-2">No pages found</p>
          ) : (
            <div className="space-y-0">
              {pageFiles.map((file) => (
                <button
                  key={file.name}
                  onClick={() => {
                    const path = `pages/${file.name}`;
                    onOpenFile(workDir ? `${workDir}/${path}` : path);
                    const params = new URLSearchParams();
                    if (vmName) params.set("vm_name", vmName);
                    authFetch(`${API}/api/file/touch?${params}`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ path }),
                    }).then(() => mutatePages()).catch(() => {});
                  }}
                  onContextMenu={(e) => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, path: workDir ? `${workDir}/pages/${file.name}` : `pages/${file.name}` }); }}
                  className="w-full text-left flex items-center gap-1.5 py-0.5 px-1 rounded hover:bg-sol-base02/50 text-sol-base0 hover:text-sol-blue text-[0.7rem] cursor-pointer"
                >
                  <span className="truncate flex-1">{file.name.replace(/\.md$/, "")}</span>
                  {file.atime && <span className="text-sol-base01 text-[0.6rem] shrink-0">{formatAtime(file.atime)}</span>}
                </button>
              ))}
            </div>
          )
        )}
      </div>
      {ctxMenu && createPortal(
        <>
          <div className="fixed inset-0 z-40" onClick={dismissCtxMenu} onContextMenu={(e) => { e.preventDefault(); dismissCtxMenu(); }} />
          <div
            className="fixed z-50 bg-sol-base02 border border-sol-base01 rounded shadow-lg py-1 min-w-[120px]"
            style={{ left: ctxMenu.x, top: ctxMenu.y }}
          >
            <button
              className="w-full text-left px-3 py-1 text-xs text-sol-base1 hover:bg-sol-base03 cursor-pointer"
              onClick={copyPath}
            >
              Copy Path
            </button>
          </div>
        </>,
        document.body
      )}
    </div>
  );
}
