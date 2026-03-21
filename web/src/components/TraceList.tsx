import { useCallback, useRef } from "react";
import useSWRInfinite from "swr/infinite";
import { API, authFetch, clearToken } from "../api";

export interface TraceListItem {
  trace_id: string;
  updated_at: string;
  todo_name: string | null;
  todo_status: string | null;
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

interface TraceListProps {
  isLoggedIn: boolean;
  selectedTraceId: string | null;
  onSelectTrace: (traceId: string | null) => void;
}

export default function TraceList({ isLoggedIn, selectedTraceId, onSelectTrace }: TraceListProps) {
  const getKey = (pageIndex: number, previousPageData: TraceListItem[] | null) => {
    if (!isLoggedIn) return null;
    if (previousPageData && previousPageData.length < PAGE_SIZE) return null;
    return `${API}/api/trace/list?offset=${pageIndex * PAGE_SIZE}&limit=${PAGE_SIZE}`;
  };

  const { data, error, isLoading, size, setSize, isValidating } = useSWRInfinite<TraceListItem[]>(getKey, fetcher);

  const traces = data ? data.flat() : [];
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

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 text-sol-base1 font-semibold text-xs">
        Traces
      </div>
      <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view traces</p>
        ) : isLoading ? (
          <p className="text-sol-base01 italic p-2">Loading...</p>
        ) : error ? (
          <p className="text-sol-base01 italic p-2">Error loading traces</p>
        ) : traces.length === 0 ? (
          <p className="text-sol-base01 italic p-2">No traces yet</p>
        ) : (
          <>
            {traces.map((t) => {
              const sel = t.trace_id === selectedTraceId;
              const dt = t.updated_at ? new Date(t.updated_at) : null;
              const date = dt ? dt.toLocaleDateString([], { month: "2-digit", day: "2-digit" }) : "";
              const time = dt ? dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
              return (
                <div
                  key={t.trace_id}
                  onClick={() => onSelectTrace(sel ? null : t.trace_id)}
                  className={`px-2 py-1.5 rounded-md cursor-pointer hover:bg-sol-base02 transition-colors ${
                    sel ? "ring-1 ring-sol-blue bg-sol-base02/50" : ""
                  }`}
                >
                  <div className="truncate text-sol-base0 text-[0.7rem]">
                    {t.todo_name || t.trace_id.slice(0, 16)}
                  </div>
                  <div className="flex items-center gap-1.5 text-[0.6rem] text-sol-base01">
                    <span>{date} {time}</span>
                    {t.todo_status && (
                      <span className={`px-1 rounded ${
                        t.todo_status === "completed" ? "bg-sol-green/20 text-sol-green" :
                        t.todo_status === "active" ? "bg-sol-blue/20 text-sol-blue" :
                        "bg-sol-base02 text-sol-base01"
                      }`}>
                        {t.todo_status}
                      </span>
                    )}
                  </div>
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
