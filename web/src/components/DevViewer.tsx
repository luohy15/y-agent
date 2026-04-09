import { useState, useEffect, Fragment } from "react";
import useSWR, { mutate } from "swr";
import { API, authFetch, clearToken } from "../api";

interface HistoryEntry {
  timestamp: string;
  unix_timestamp: number;
  action: string;
  note?: string;
}

interface DevWorktree {
  worktree_id: string;
  name: string;
  project_path: string;
  worktree_path: string;
  branch: string;
  status: string;
  todo_id?: string;
  server_state?: {
    frontend?: { pid?: string; port?: string };
    ngrok_frontend?: { pid?: string; domain?: string; url?: string };
    backend?: { pid?: string; port?: string };
    ngrok_backend?: { pid?: string; domain?: string; url?: string };
  };
  history: HistoryEntry[];
  created_at: string;
  updated_at: string;
  created_at_unix: number;
  updated_at_unix: number;
}

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

const statusColor: Record<string, string> = {
  active: "bg-sol-blue text-sol-base03",
  serving: "bg-sol-green text-sol-base03",
  removed: "bg-sol-red text-sol-base03",
};

const actionColor: Record<string, string> = {
  create: "text-sol-green",
  submit: "text-sol-blue",
  commit: "text-sol-cyan",
  remove: "text-sol-red",
  update: "text-sol-yellow",
};

function ActivityHistory({ worktrees, collapsed, onToggle }: { worktrees: DevWorktree[]; collapsed: boolean; onToggle: () => void }) {
  const entries = worktrees.flatMap((w) =>
    (w.history || []).map((h) => ({ ...h, worktreeName: w.name, worktreeId: w.worktree_id }))
  ).sort((a, b) => (b.unix_timestamp || 0) - (a.unix_timestamp || 0));

  return (
    <div className={`flex flex-col bg-sol-base03 border-l border-sol-base02 shrink-0 transition-all ${collapsed ? "w-8" : "w-72"}`}>
      <button
        onClick={onToggle}
        className="px-2 py-1.5 text-xs text-sol-base01 hover:text-sol-base1 cursor-pointer flex items-center gap-1 border-b border-sol-base02 shrink-0"
        title={collapsed ? "Show activity" : "Hide activity"}
      >
        {collapsed ? "◀" : "▶"}
        {!collapsed && <span className="font-medium text-sol-base1">Activity</span>}
      </button>
      {!collapsed && (
        <div className="flex-1 overflow-y-auto px-2 py-1.5 space-y-1">
          {entries.length === 0 ? (
            <p className="text-sol-base01 text-xs italic">No activity</p>
          ) : entries.map((e, i) => (
            <div key={i} className="text-xs border-b border-sol-base02/50 pb-1">
              <div className="flex items-center gap-1.5">
                <span className="text-sol-base01 shrink-0">{new Date(e.timestamp).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
                <span className={`shrink-0 ${actionColor[e.action] || "text-sol-base0"}`}>{e.action}</span>
              </div>
              <div className="text-sol-base1 truncate" title={e.worktreeName}>
                {e.worktreeName}
              </div>
              {e.note && <div className="text-sol-base01 truncate" title={e.note}>{e.note}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type StatusFilter = "active" | "removed" | "all";

export default function DevViewer() {
  const [historyCollapsed, setHistoryCollapsed] = useState(() => localStorage.getItem("devHistoryCollapsed") !== "false");
  useEffect(() => { localStorage.setItem("devHistoryCollapsed", String(historyCollapsed)); }, [historyCollapsed]);

  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => {
    const saved = localStorage.getItem("devFilter");
    return saved === "removed" ? "removed" : saved === "all" ? "all" : "active";
  });
  useEffect(() => { localStorage.setItem("devFilter", statusFilter); }, [statusFilter]);

  const [expandedId, setExpandedId] = useState<string | null>(null);

  const param = statusFilter === "all" ? "" : `?status=${statusFilter}`;
  const { data: worktrees, isLoading, error } = useSWR<DevWorktree[]>(
    `${API}/api/dev-worktree/list${param}`,
    fetcher,
  );

  const sorted = worktrees ? [...worktrees].sort((a, b) => (b.updated_at_unix || 0) - (a.updated_at_unix || 0)) : undefined;

  return (
    <div className="h-full flex bg-sol-base03 text-sm sm:text-xs">
      <div className="flex-1 overflow-y-auto overflow-x-hidden min-w-0" onClick={(e) => { if (expandedId && !(e.target as HTMLElement).closest('[data-dev-card]')) setExpandedId(null); }}>
        <div className="px-3 pt-2">
          <div className="flex items-center gap-1.5 mb-1">
            {(["active", "removed", "all"] as const).map((f) => (
              <button
                key={f}
                onClick={() => { setStatusFilter(f); setExpandedId(null); }}
                className={`px-2.5 py-1 sm:px-2 sm:py-0.5 rounded text-sm sm:text-xs cursor-pointer ${
                  statusFilter === f
                    ? "bg-sol-blue text-sol-base03"
                    : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"
                }`}
              >
                {f}
              </button>
            ))}
          </div>

          {isLoading ? (
            <p className="text-sol-base01 italic">Loading...</p>
          ) : error ? (
            <p className="text-sol-red">Error loading worktrees</p>
          ) : !sorted || sorted.length === 0 ? (
            <p className="text-sol-base01 italic">No worktrees</p>
          ) : (
            <table className="w-full border-collapse">
              <thead className="sticky top-0 bg-sol-base03">
                <tr className="text-sol-base01 text-left text-xs border-b border-sol-base02">
                  <th className="py-1 px-1.5">Name</th>
                  <th className="py-1 px-1.5">Project</th>
                  <th className="py-1 px-1.5">Branch</th>
                  <th className="py-1 px-1.5">Status</th>
                  <th className="py-1 px-1.5">Todo</th>
                  <th className="py-1 px-1.5 hidden md:table-cell">Updated</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((w) => (
                  <Fragment key={w.worktree_id}>
                    <tr
                      className={`border-b border-sol-base02 cursor-pointer hover:bg-sol-base02/30 ${expandedId === w.worktree_id ? "bg-sol-base02/50" : ""}`}
                      onClick={() => setExpandedId(expandedId === w.worktree_id ? null : w.worktree_id)}
                    >
                      <td className="py-1 px-1.5 text-sol-base1">{w.name}</td>
                      <td className="py-1 px-1.5 text-sol-base0 truncate max-w-[200px]" title={w.project_path}>{w.project_path.split("/").pop()}</td>
                      <td className="py-1 px-1.5 text-sol-cyan">{w.branch}</td>
                      <td className="py-1 px-1.5">
                        <span className={`px-2 py-0.5 rounded text-xs ${statusColor[w.status] || "bg-sol-base02 text-sol-base0"}`}>
                          {w.status}
                        </span>
                      </td>
                      <td className="py-1 px-1.5 text-sol-base01">{w.todo_id || "-"}</td>
                      <td className="py-1 px-1.5 text-sol-base01 hidden md:table-cell">{w.updated_at ? new Date(w.updated_at).toLocaleString() : "-"}</td>
                    </tr>
                    {expandedId === w.worktree_id && (
                      <tr key={`${w.worktree_id}-expand`} className="border-b border-sol-base02">
                        <td colSpan={6} className="p-2">
                          <div className="bg-sol-base02 rounded p-3 border border-sol-base01/20 text-xs space-y-2" data-dev-card>
                            <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                              <span className="text-sol-base01">Path</span>
                              <span className="text-sol-base0 break-all">{w.worktree_path}</span>
                              <span className="text-sol-base01">Created</span>
                              <span className="text-sol-base0">{w.created_at ? new Date(w.created_at).toLocaleString() : "-"}</span>
                              {w.todo_id && (
                                <>
                                  <span className="text-sol-base01">Todo</span>
                                  <span className="text-sol-base0">{w.todo_id}</span>
                                </>
                              )}
                              {w.server_state && (
                                <>
                                  <span className="text-sol-base01">Services</span>
                                  <span className="text-sol-base0">
                                    {[
                                      w.server_state.frontend && `vite:${w.server_state.frontend.port || '?'}`,
                                      w.server_state.ngrok_frontend && w.server_state.ngrok_frontend.url,
                                      w.server_state.backend && `api:${w.server_state.backend.port || '?'}`,
                                      w.server_state.ngrok_backend && w.server_state.ngrok_backend.url,
                                    ].filter(Boolean).join(' · ') || 'none'}
                                  </span>
                                </>
                              )}
                            </div>
                            {w.history && w.history.length > 0 && (
                              <div className="border-t border-sol-base01/20 pt-2 space-y-0.5 overflow-y-auto max-h-40" style={{ scrollbarColor: "#586e75 transparent" }}>
                                {[...w.history].sort((a, b) => (b.unix_timestamp || 0) - (a.unix_timestamp || 0)).map((h, i) => (
                                  <div key={i} className="flex gap-1.5">
                                    <span className="text-sol-base01 shrink-0">{new Date(h.timestamp).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
                                    <span className={`shrink-0 ${actionColor[h.action] || "text-sol-base0"}`}>{h.action}</span>
                                    {h.note && <span className="text-sol-base01 truncate" title={h.note}>{h.note}</span>}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
      <ActivityHistory worktrees={worktrees || []} collapsed={historyCollapsed} onToggle={() => setHistoryCollapsed((c) => !c)} />
    </div>
  );
}
