import { useMemo, useState } from "react";
import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";

interface Entity {
  entity_id: string;
  name: string;
  type: string;
  front_matter?: Record<string, unknown> | null;
}

interface EntityListProps {
  isLoggedIn: boolean;
  selectedEntityId?: string | null;
  onSelectEntity?: (entityId: string) => void;
}

export default function EntityList({ isLoggedIn, selectedEntityId, onSelectEntity }: EntityListProps) {
  const [typeFilter, setTypeFilter] = useState<string>(() => localStorage.getItem("entityListType") || "");
  const [search, setSearch] = useState("");
  const [spinning, setSpinning] = useState(false);

  const swrKey = isLoggedIn ? `${API}/api/entity/list?limit=500` : null;
  const { data, isLoading, error, mutate } = useSWR<Entity[]>(swrKey, fetcher, { revalidateOnFocus: false });

  const types = useMemo(() => {
    if (!data) return [];
    const set = new Set<string>();
    for (const e of data) set.add(e.type);
    return [...set].sort();
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    return data.filter((e) => {
      if (typeFilter && e.type !== typeFilter) return false;
      if (q && !e.name.toLowerCase().includes(q) && !e.type.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [data, typeFilter, search]);

  const handleTypeChange = (t: string) => {
    setTypeFilter(t);
    if (t) localStorage.setItem("entityListType", t);
    else localStorage.removeItem("entityListType");
  };

  const pillClass = (active: boolean) =>
    `px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer ${active ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"}`;

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <div className="flex gap-1.5">
          <input
            type="text"
            placeholder="Search entities..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 min-w-0 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
          />
          <button
            onClick={() => { mutate(); setSpinning(true); setTimeout(() => setSpinning(false), 600); }}
            className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
            title="Refresh"
          >
            <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
        </div>
        {types.length > 0 && (
          <div className="flex gap-1 flex-wrap">
            <button onClick={() => handleTypeChange("")} className={pillClass(!typeFilter)}>All</button>
            {types.map((t) => (
              <button key={t} onClick={() => handleTypeChange(t)} className={pillClass(typeFilter === t)}>{t}</button>
            ))}
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view entities</p>
        ) : isLoading ? (
          <p className="text-sol-base01 italic p-2">Loading...</p>
        ) : error ? (
          <p className="text-sol-base01 italic p-2">Error loading entities</p>
        ) : filtered.length === 0 ? (
          <p className="text-sol-base01 italic p-2">No entities found</p>
        ) : (
          <div className="space-y-0">
            {filtered.map((e) => {
              const isSelected = selectedEntityId === e.entity_id;
              return (
                <button
                  key={e.entity_id}
                  onClick={() => onSelectEntity?.(e.entity_id)}
                  className={`w-full text-left flex items-center gap-1.5 py-1 px-1 rounded cursor-pointer ${
                    isSelected ? "bg-sol-base02" : "hover:bg-sol-base02/50"
                  }`}
                >
                  <div className="min-w-0 flex-1 flex flex-col">
                    <div className="flex items-center gap-1 min-w-0">
                      <span
                        className={`text-left truncate text-[0.7rem] ${isSelected ? "text-sol-blue" : "text-sol-base0"}`}
                        title={e.name}
                      >
                        {e.name}
                      </span>
                    </div>
                  </div>
                  <span
                    className="shrink-0 px-1 py-0 bg-sol-base02 rounded text-sol-base01 text-[0.55rem] font-medium leading-tight"
                    title={e.type}
                  >
                    {e.type}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
