import { useState, useMemo, useCallback } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";

interface FileEntry {
  name: string;
  type: string;
}

interface NoteListProps {
  isLoggedIn: boolean;
  vmName?: string | null;
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

function groupByMonth(files: string[]): [string, string[]][] {
  const groups = new Map<string, string[]>();
  for (const f of files) {
    const match = f.match(/^(\d{4}-\d{2})/);
    const key = match ? match[1] : "other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(f);
  }
  // Sort months descending
  return [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
}

export default function NoteList({ isLoggedIn, vmName, onOpenFile }: NoteListProps) {
  const [tab, setTab] = useState<NoteTab>(() => {
    const saved = localStorage.getItem("noteListTab");
    return saved === "journals" || saved === "pages" ? saved : "journals";
  });
  const [searchInput, setSearchInput] = useState("");

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

  const { data: journalsData, isLoading: journalsLoading, error: journalsError } = useSWR<{ path: string; entries: FileEntry[] }>(journalsKey, fetcher, { revalidateOnFocus: false });
  const { data: pagesData, isLoading: pagesLoading, error: pagesError } = useSWR<{ path: string; entries: FileEntry[] }>(pagesKey, fetcher, { revalidateOnFocus: false });

  // Journals: filter .md files, sort by name descending
  const journalFiles = useMemo(() => {
    if (!journalsData?.entries) return [];
    return journalsData.entries
      .filter((e) => e.type === "file" && e.name.endsWith(".md"))
      .map((e) => e.name)
      .sort((a, b) => b.localeCompare(a));
  }, [journalsData]);

  const journalGroups = useMemo(() => groupByMonth(journalFiles), [journalFiles]);

  // Pages: filter .md files, apply search
  const pageFiles = useMemo(() => {
    if (!pagesData?.entries) return [];
    let files = pagesData.entries
      .filter((e) => e.type === "file" && e.name.endsWith(".md"))
      .map((e) => e.name);
    if (searchInput) {
      const q = searchInput.toLowerCase();
      files = files.filter((f) => f.toLowerCase().includes(q));
    }
    return files;
  }, [pagesData, searchInput]);

  const tabClass = (active: boolean) =>
    `px-2 py-0.5 rounded text-[0.65rem] cursor-pointer ${active ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"}`;

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <div className="flex gap-1">
          <button onClick={() => handleTabChange("journals")} className={tabClass(tab === "journals")}>Journals</button>
          <button onClick={() => handleTabChange("pages")} className={tabClass(tab === "pages")}>Pages</button>
        </div>
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
                      onClick={() => onOpenFile(`journals/${file}`)}
                      className="w-full text-left flex items-center gap-1.5 py-0.5 px-1 rounded hover:bg-sol-base02/50 text-sol-base0 hover:text-sol-blue text-[0.7rem] cursor-pointer"
                    >
                      {file.replace(/\.md$/, "").slice(5)}
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
                  key={file}
                  onClick={() => onOpenFile(`pages/${file}`)}
                  className="w-full text-left flex items-center gap-1.5 py-0.5 px-1 rounded hover:bg-sol-base02/50 text-sol-base0 hover:text-sol-blue text-[0.7rem] cursor-pointer"
                >
                  {file.replace(/\.md$/, "")}
                </button>
              ))}
            </div>
          )
        )}
      </div>
    </div>
  );
}
