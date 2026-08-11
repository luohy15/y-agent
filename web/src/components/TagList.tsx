import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import useSWR from "swr";
import { API, jsonFetcher as fetcher, type TagResultItem, type TagResults, type TagVocabularyEntry } from "../api";
import { ListEmpty, ListError, ListLoading, StaleBanner } from "./ListStates";

export interface TagListProps {
  isLoggedIn: boolean;
  onNavigate: (entityType: string, item: TagResultItem) => void;
}

type VocabViewMode = "tree" | "flat";

// Mixed-result group order (matches the design mockup footer's fixed type-badge
// color map); unknown/future entity_types are appended after these.
const TYPE_ORDER = [
  "todo", "note", "entity", "chat", "calendar_event",
  "reminder", "routine", "link", "email", "rss_feed",
] as const;

const TYPE_BADGE: Record<string, string> = {
  todo: "bg-sol-blue/20 text-sol-blue",
  note: "bg-sol-cyan/20 text-sol-cyan",
  entity: "bg-sol-violet/20 text-sol-violet",
  chat: "bg-sol-green/20 text-sol-green",
  calendar_event: "bg-sol-orange/20 text-sol-orange",
  reminder: "bg-sol-yellow/20 text-sol-yellow",
  routine: "bg-sol-magenta/20 text-sol-magenta",
  link: "bg-sol-base01/25 text-sol-base01",
  email: "bg-sol-red/20 text-sol-red",
  rss_feed: "bg-sol-orange/20 text-sol-orange",
};

interface TreeNode {
  name: string;
  path: string;
  children: Map<string, TreeNode>;
  entry?: TagVocabularyEntry;
  rollupCount: number;
}

// Splits each tag on "/" into a prefix tree. A node with no children is
// necessarily a terminal segment (a real vocabulary entry); a node with
// children is a prefix group and may *also* carry its own exact entry
// (e.g. both "work" and "work/log" are tagged).
function buildTree(entries: TagVocabularyEntry[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map(), rollupCount: 0 };
  for (const entry of entries) {
    const segments = entry.tag.split("/").filter(Boolean);
    let node = root;
    let path = "";
    for (const seg of segments) {
      path = path ? `${path}/${seg}` : seg;
      let child = node.children.get(seg);
      if (!child) {
        child = { name: seg, path, children: new Map(), rollupCount: 0 };
        node.children.set(seg, child);
      }
      node = child;
    }
    node.entry = entry;
  }
  const compute = (node: TreeNode): number => {
    let sum = node.entry?.count ?? 0;
    for (const child of node.children.values()) sum += compute(child);
    node.rollupCount = sum;
    return sum;
  };
  compute(root);
  return root;
}

// Full ancestor prefix of a node (dim-rendered before its own bright name),
// e.g. for "work/personal/y-agent" this returns "work/personal/". Undefined
// for a top-level node (no ancestors to dim).
function ancestorPrefixOf(node: TreeNode): string | undefined {
  return node.path.length > node.name.length ? node.path.slice(0, node.path.length - node.name.length) : undefined;
}

function itemLabel(type: string, item: TagResultItem): string {
  if (type === "note" && item.title) {
    return item.title.replace(/^.*\//, "").replace(/\.md$/, "");
  }
  return item.title || item.id;
}

const sortByTag = (a: TagVocabularyEntry, b: TagVocabularyEntry) => a.tag.localeCompare(b.tag);

export default function TagList({ isLoggedIn, onNavigate }: TagListProps) {
  const [search, setSearch] = useState("");
  const [viewMode, setViewMode] = useState<VocabViewMode>(() => {
    const saved = localStorage.getItem("tagListViewMode");
    return saved === "flat" ? "flat" : "tree";
  });
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [spinning, setSpinning] = useState(false);

  const vocabKey = isLoggedIn ? `${API}/api/tag/list` : null;
  const { data: vocabData, isLoading: vocabLoading, error: vocabError, mutate: mutateVocab } =
    useSWR<TagVocabularyEntry[]>(vocabKey, fetcher, { revalidateOnFocus: false });

  const entries = useMemo(() => vocabData ?? [], [vocabData]);
  const tree = useMemo(() => buildTree(entries), [entries]);
  const totalUses = useMemo(() => entries.reduce((sum, e) => sum + e.count, 0), [entries]);

  // Design state 1 shows the tree pre-expanded (meta/, work/, work/personal/ all
  // open); default to fully expanded on the first successful load, then leave
  // the user's own expand/collapse choices alone across refetches.
  const autoExpandedRef = useRef(false);
  useEffect(() => {
    if (autoExpandedRef.current || entries.length === 0) return;
    autoExpandedRef.current = true;
    const groupPaths: string[] = [];
    const walk = (node: TreeNode) => {
      for (const child of node.children.values()) {
        if (child.children.size > 0) {
          groupPaths.push(child.path);
          walk(child);
        }
      }
    };
    walk(tree);
    setExpanded(new Set(groupPaths));
  }, [entries.length, tree]);

  const filteredEntries = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => e.tag.toLowerCase().includes(q)).sort(sortByTag);
  }, [entries, search]);

  const handleViewModeChange = useCallback((mode: VocabViewMode) => {
    setViewMode(mode);
    localStorage.setItem("tagListViewMode", mode);
  }, []);

  const toggleExpand = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  }, []);

  const selectTag = useCallback((tag: string) => {
    setSelected(tag);
  }, []);

  const resultsKey = isLoggedIn && selected
    ? `${API}/api/tag?tag=${encodeURIComponent(selected)}`
    : null;
  const { data: resultsData, isLoading: resultsLoading, error: resultsError, mutate: mutateResults } =
    useSWR<TagResults>(resultsKey, fetcher, { revalidateOnFocus: false });

  const resultGroups = useMemo(() => {
    if (!resultsData) return [] as [string, TagResultItem[]][];
    const groups: [string, TagResultItem[]][] = [];
    const seen = new Set<string>();
    for (const t of TYPE_ORDER) {
      const items = resultsData[t];
      if (items && items.length > 0) {
        groups.push([t, items]);
        seen.add(t);
      }
    }
    for (const [t, items] of Object.entries(resultsData)) {
      if (!seen.has(t) && items && items.length > 0) groups.push([t, items]);
    }
    return groups;
  }, [resultsData]);

  const resultsTotal = useMemo(() => resultGroups.reduce((sum, [, items]) => sum + items.length, 0), [resultGroups]);

  const refreshVocab = useCallback(() => {
    mutateVocab();
    setSpinning(true);
    setTimeout(() => setSpinning(false), 600);
  }, [mutateVocab]);

  const rowClass = (isSelected: boolean) =>
    `group flex items-center gap-1.5 px-1 py-1 rounded cursor-pointer ${isSelected ? "bg-sol-blue/15 ring-1 ring-sol-blue/40" : "hover:bg-sol-base02/50"}`;

  const manageButton = (isSelected: boolean) => (
    <button
      disabled
      title="Tag rename/merge/delete lands in a later slice"
      onClick={(e) => e.stopPropagation()}
      className={`shrink-0 text-sol-base01 cursor-not-allowed ${isSelected ? "hidden" : "opacity-0 group-hover:opacity-100"}`}
    >
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg>
    </button>
  );

  const renderLeafRow = (entry: TagVocabularyEntry, opts?: { dimPrefix?: string; label?: string }) => {
    const isSelected = selected === entry.tag;
    const label = opts?.label ?? entry.tag;
    return (
      <div key={entry.tag} onClick={() => selectTag(entry.tag)} className={rowClass(isSelected)}>
        <span className={`truncate flex-1 text-[0.7rem] ${isSelected ? "text-sol-blue font-medium" : "text-sol-base0"}`}>
          {opts?.dimPrefix && <span className={isSelected ? "text-sol-blue/70" : "text-sol-base01"}>{opts.dimPrefix}</span>}
          {label}
        </span>
        {manageButton(isSelected)}
        <span className={`text-[0.6rem] px-1 rounded shrink-0 ${isSelected ? "bg-sol-blue/25 text-sol-blue" : "bg-sol-base02 text-sol-base01"}`}>{entry.count}</span>
      </div>
    );
  };

  const renderGroupNode = (node: TreeNode): ReactNode => {
    const isExpanded = expanded.has(node.path);
    const children = [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name));
    const isSelected = !!node.entry && selected === node.entry.tag;
    const ancestorPrefix = ancestorPrefixOf(node);
    return (
      <div key={node.path}>
        <div onClick={() => toggleExpand(node.path)} className="flex items-center gap-1.5 px-1 py-1 rounded text-sol-base01 hover:bg-sol-base02/50 cursor-pointer">
          <svg className={`w-3 h-3 shrink-0 transition-transform ${isExpanded ? "" : "-rotate-90"}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
          <span
            onClick={node.entry ? (e) => { e.stopPropagation(); selectTag(node.entry!.tag); } : undefined}
            className={`font-medium text-[0.7rem] truncate ${isSelected ? "text-sol-blue" : "text-sol-base0"} ${node.entry ? "hover:underline" : ""}`}
          >
            {ancestorPrefix && <span className={isSelected ? "text-sol-blue/70" : "text-sol-base01"}>{ancestorPrefix}</span>}
            {node.name}/
          </span>
          <span className="ml-auto text-[0.6rem] px-1 rounded bg-sol-base02 text-sol-base01 shrink-0">{node.rollupCount}</span>
        </div>
        {isExpanded && (
          <div className="ml-3 border-l border-sol-base02 pl-1.5 space-y-0.5">
            {children.map((c) => c.children.size > 0
              ? renderGroupNode(c)
              : renderLeafRow(c.entry!, { dimPrefix: ancestorPrefixOf(c), label: c.name }))}
          </div>
        )}
      </div>
    );
  };

  const renderVocabulary = () => {
    if (!isLoggedIn) return <p className="text-sol-base01 italic p-2">Sign in to view tags</p>;
    if (vocabLoading) return <ListLoading />;
    if (vocabError && !vocabData) return <ListError error={vocabError} />;
    if (entries.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center gap-1 px-4 py-8 text-center">
          <p className="text-sol-base01 italic">No tags found</p>
          <p className="text-[0.6rem] text-sol-base01/80 leading-relaxed">
            Tags appear here once you add one to an item. There is no bare tag to create.
          </p>
        </div>
      );
    }
    let body: ReactNode;
    if (search.trim()) {
      body = filteredEntries.length === 0
        ? <p className="text-sol-base01 italic p-2">No matching tags</p>
        : <div className="space-y-0">{filteredEntries.map((e) => renderLeafRow(e))}</div>;
    } else if (viewMode === "flat") {
      body = <div className="space-y-0">{[...entries].sort(sortByTag).map((e) => renderLeafRow(e))}</div>;
    } else {
      const rootChildren = [...tree.children.values()].sort((a, b) => a.name.localeCompare(b.name));
      const groups = rootChildren.filter((n) => n.children.size > 0);
      const leaves = rootChildren.filter((n) => n.children.size === 0);
      body = (
        <div className="space-y-0.5">
          {groups.map((n) => renderGroupNode(n))}
          {leaves.length > 0 && (
            <div className="pt-1 mt-1 border-t border-sol-base02">
              <div className="text-sol-base01 text-[0.55rem] uppercase tracking-wide px-1 py-0.5">other</div>
              {leaves.map((n) => renderLeafRow(n.entry!))}
            </div>
          )}
        </div>
      );
    }
    return (
      <>
        <StaleBanner error={vocabError} />
        {body}
      </>
    );
  };

  const renderDrilldown = () => {
    if (resultsLoading) return <ListLoading />;
    if (resultsError && !resultsData) return <ListError error={resultsError} />;
    if (resultGroups.length === 0) return <ListEmpty label="items" />;
    return (
      <div className="space-y-2">
        <StaleBanner error={resultsError} />
        {resultGroups.map(([type, items]) => (
          <div key={type}>
            <div className="flex items-center gap-1.5 px-1 py-0.5 sticky top-0 bg-sol-base03 z-[5]">
              <span className={`text-[0.6rem] px-1 rounded font-medium ${TYPE_BADGE[type] || "bg-sol-base02 text-sol-base01"}`}>{type}</span>
              <span className="text-[0.55rem] text-sol-base01">{items.length}</span>
            </div>
            <div className="space-y-0">
              {items.map((item, idx) => (
                <button
                  key={`${item.id}:${idx}`}
                  onClick={() => onNavigate(type, item)}
                  className="w-full text-left group flex items-center gap-1.5 py-1 px-1 rounded hover:bg-sol-base02/50 cursor-pointer text-sol-base0 hover:text-sol-blue"
                >
                  {(type === "todo" || type === "chat") && (
                    <span className="text-[0.55rem] font-mono px-1 rounded bg-sol-base01/20 text-sol-base01 shrink-0">
                      {type === "todo" ? `#${item.id}` : item.id.slice(0, 6)}
                    </span>
                  )}
                  <span className="truncate flex-1 text-[0.7rem]">{itemLabel(type, item)}</span>
                  <svg className="w-3 h-3 opacity-0 group-hover:opacity-100 text-sol-base01 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6" /></svg>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      {selected ? (
        <div className="p-2 border-b border-sol-base02 flex flex-col gap-2">
          <div className="flex items-center gap-1.5">
            <button onClick={() => setSelected(null)} className="p-0.5 rounded text-sol-base01 hover:text-sol-base0 hover:bg-sol-base02 shrink-0 cursor-pointer" title="Back to all tags">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
            </button>
            <span className="inline-flex items-center gap-1 min-w-0">
              <svg className="w-3 h-3 text-sol-blue shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z" /><path d="M7 7h.01" /></svg>
              <span className="truncate font-mono text-[0.72rem] text-sol-base1">{selected}</span>
            </span>
            <button
              onClick={() => { mutateResults(); setSpinning(true); setTimeout(() => setSpinning(false), 600); }}
              className="text-sol-base01 hover:text-sol-base0 shrink-0 cursor-pointer"
              title="Refresh"
            >
              <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></svg>
            </button>
            <span className="text-[0.6rem] px-1.5 py-0.5 rounded bg-sol-blue/20 text-sol-blue shrink-0">{resultsTotal} items</span>
          </div>
          <div className="flex gap-1">
            <button disabled title="Rename lands in a later slice" className="flex-1 px-1.5 py-1 rounded text-[0.62rem] bg-sol-base02 text-sol-base01/50 cursor-not-allowed flex items-center justify-center gap-1">
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>Rename
            </button>
            <button disabled title="Merge lands in a later slice" className="flex-1 px-1.5 py-1 rounded text-[0.62rem] bg-sol-base02 text-sol-base01/50 cursor-not-allowed flex items-center justify-center gap-1">
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="6" cy="18" r="3" /><circle cx="18" cy="6" r="3" /><path d="M6 15V9a6 6 0 0 1 6-6" /></svg>Merge
            </button>
            <button disabled title="Delete lands in a later slice" className="flex-1 px-1.5 py-1 rounded text-[0.62rem] bg-sol-base02 text-sol-base01/50 cursor-not-allowed flex items-center justify-center gap-1">
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18" /><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /></svg>Delete
            </button>
          </div>
        </div>
      ) : (
        <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
          <div className="flex gap-1.5">
            <input
              type="text"
              placeholder="Search tags..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="y-field flex-1 min-w-0 px-2 py-1 rounded"
            />
            <button
              onClick={refreshVocab}
              className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
              title="Refresh"
            >
              <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></svg>
            </button>
          </div>
          {entries.length > 0 && (
            <div className="flex items-center justify-between text-[0.6rem] text-sol-base01">
              <span>{entries.length} tags · {totalUses} uses</span>
              <div className="flex gap-1">
                <button onClick={() => handleViewModeChange("tree")} className={`px-1.5 py-0.5 rounded cursor-pointer ${viewMode === "tree" ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}>tree</button>
                <button onClick={() => handleViewModeChange("flat")} className={`px-1.5 py-0.5 rounded cursor-pointer ${viewMode === "flat" ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}>flat</button>
              </div>
            </div>
          )}
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-1.5">
        {selected ? renderDrilldown() : renderVocabulary()}
      </div>
    </div>
  );
}
