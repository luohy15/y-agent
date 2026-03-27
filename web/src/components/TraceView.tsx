import { useState } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";
import WaterfallChart, { type TraceChat } from "./WaterfallChart";
import { skillBadgeClass, statusBadgeClass, priorityColorClass, actionBadgeClass } from "./badges";

interface TraceViewProps {
  isLoggedIn: boolean;
  selectedTraceId: string | null;
  onSelectChat?: (chatId: string) => void;
}

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

interface TodoHistoryEntry {
  timestamp: string;
  action: string;
  note?: string;
}

interface TodoInfo {
  todo_id: string;
  name: string;
  status: string;
  desc?: string;
  tags?: string[];
  priority?: string;
  due_date?: string;
  progress?: string;
  completed_at?: string;
  created_at?: string;
  updated_at?: string;
  history?: TodoHistoryEntry[];
}

interface TraceChatsResponse {
  chats: TraceChat[];
  todo_name: string | null;
  todo_status: string | null;
  todo: TodoInfo | null;
}

export default function TraceView({ isLoggedIn, selectedTraceId, onSelectChat }: TraceViewProps) {
  // Fetch chats for selected trace
  const { data: traceData } = useSWR<TraceChatsResponse>(
    selectedTraceId && isLoggedIn ? `${API}/api/trace/chats?trace_id=${encodeURIComponent(selectedTraceId)}` : null,
    fetcher,
  );

  const traceChats = traceData?.chats;
  const todoName = traceData?.todo_name;
  const todoStatus = traceData?.todo_status;
  const todoInfo = traceData?.todo;
  const [todoDetailOpen, setTodoDetailOpen] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [shareLabel, setShareLabel] = useState("share");

  const handleShare = async () => {
    if (!selectedTraceId) return;
    setShareLabel("...");
    try {
      const res = await authFetch(`${API}/api/trace/share`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trace_id: selectedTraceId }),
      });
      if (!res.ok) throw new Error();
      const { share_id } = await res.json();
      const url = `${window.location.origin}/t/${share_id}`;
      await navigator.clipboard.writeText(url);
      setShareLabel("copied!");
    } catch {
      setShareLabel("error");
    }
    setTimeout(() => setShareLabel("share"), 1500);
  };

  return (
    <div className="h-full overflow-y-auto bg-sol-base03 p-3">
      {!selectedTraceId ? (
        <div className="flex items-center justify-center h-full text-sol-base01 italic text-sm">
          Select a todo to view details
        </div>
      ) : !traceChats ? (
        <div className="flex items-center justify-center h-full text-sol-base01 italic text-sm">
          Loading...
        </div>
      ) : (
        <div>
          {/* Header */}
          <div className="mb-4">
            <div className="flex items-center gap-2 mb-1 pt-1">
              <span className="text-sol-base1 text-sm font-medium">
                {todoName || selectedTraceId}
              </span>
              {todoStatus && (
                <span className={`text-[0.6rem] px-1 rounded ${statusBadgeClass(todoStatus)}`}>
                  {todoStatus}
                </span>
              )}
              {/* Skill badges */}
              {traceChats.length > 0 && (
                <div className="flex flex-wrap gap-0.5">
                  {[...new Set(traceChats.map((c) => c.skill).filter(Boolean))].map((s) => (
                    <span key={s} className={`text-[0.6rem] ${skillBadgeClass(s)}`}>
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 mb-1">
              <button
                onClick={() => navigator.clipboard.writeText(selectedTraceId)}
                className="inline-flex items-center text-[0.6rem] text-sol-base01 hover:text-sol-base0 font-mono cursor-pointer"
                title="Copy todo ID"
              >
                #{selectedTraceId}
              </button>
              <button
                onClick={handleShare}
                className={`text-[0.6rem] font-mono px-1.5 py-0.5 rounded cursor-pointer ${
                  shareLabel === "copied!" ? "bg-sol-green/20 text-sol-green" :
                  shareLabel === "error" ? "bg-sol-red/20 text-sol-red" :
                  "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
                }`}
              >
                {shareLabel}
              </button>
            </div>

            {/* Todo detail section */}
            {todoInfo && (
              <div className="mb-3 border border-sol-base02 rounded">
                <button
                  onClick={() => setTodoDetailOpen((v) => !v)}
                  className="w-full flex items-center gap-2 px-2 py-1 text-xs text-sol-base01 hover:text-sol-base0 cursor-pointer"
                >
                  <span className="text-[0.6rem]">{todoDetailOpen ? "▼" : "▶"}</span>
                  <span className="font-medium text-sol-base0">Todo Detail</span>
                </button>
                {todoDetailOpen && (<>
                  <div className="px-2 pb-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    {todoInfo.desc && (
                      <>
                        <span className="text-sol-base01">Desc</span>
                        <span className="text-sol-base0">{todoInfo.desc}</span>
                      </>
                    )}
                    {todoInfo.priority && (
                      <>
                        <span className="text-sol-base01">Priority</span>
                        <span className={priorityColorClass(todoInfo.priority)}>{todoInfo.priority}</span>
                      </>
                    )}
                    {todoInfo.due_date && (
                      <>
                        <span className="text-sol-base01">Due</span>
                        <span className="text-sol-base0">{todoInfo.due_date}</span>
                      </>
                    )}
                    {todoInfo.tags && todoInfo.tags.length > 0 && (
                      <>
                        <span className="text-sol-base01">Tags</span>
                        <div className="flex flex-wrap gap-1">
                          {todoInfo.tags.map((tag) => (
                            <span key={tag} className="bg-sol-base02 text-sol-base0 px-1.5 py-0.5 rounded text-[0.6rem]">{tag}</span>
                          ))}
                        </div>
                      </>
                    )}
                    {todoInfo.progress && (
                      <>
                        <span className="text-sol-base01">Progress</span>
                        <span className="text-sol-base0 whitespace-pre-wrap">{todoInfo.progress}</span>
                      </>
                    )}
                    {todoInfo.created_at && (
                      <>
                        <span className="text-sol-base01">Created</span>
                        <span className="text-sol-base0 font-mono text-[0.65rem]">{new Date(todoInfo.created_at).toLocaleString()}</span>
                      </>
                    )}
                    {todoInfo.updated_at && (
                      <>
                        <span className="text-sol-base01">Updated</span>
                        <span className="text-sol-base0 font-mono text-[0.65rem]">{new Date(todoInfo.updated_at).toLocaleString()}</span>
                      </>
                    )}
                    {todoInfo.completed_at && (
                      <>
                        <span className="text-sol-base01">Completed</span>
                        <span className="text-sol-green font-mono text-[0.65rem]">{new Date(todoInfo.completed_at).toLocaleString()}</span>
                      </>
                    )}
                  </div>
                  {/* History section */}
                  {todoInfo.history && todoInfo.history.length > 0 && (
                    <div className="px-2 pb-2">
                      <button
                        onClick={() => setHistoryOpen((v) => !v)}
                        className="flex items-center gap-1.5 text-[0.65rem] text-sol-base01 hover:text-sol-base0 cursor-pointer mb-1"
                      >
                        <span className="text-[0.55rem]">{historyOpen ? "▼" : "▶"}</span>
                        <span>History ({todoInfo.history.length})</span>
                      </button>
                      {historyOpen && (
                        <div className="ml-1 border-l border-sol-base02 pl-2 space-y-1.5">
                          {todoInfo.history.map((h, i) => {
                            return (
                              <div key={i} className="flex items-start gap-1.5 relative">
                                <div className="absolute -left-[calc(0.5rem+1px)] top-1 w-1.5 h-1.5 rounded-full bg-sol-base01 border border-sol-base02" />
                                <span className="text-[0.6rem] text-sol-base01 font-mono shrink-0">
                                  {new Date(h.timestamp).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                                </span>
                                <span className={`text-[0.55rem] px-1 rounded shrink-0 ${actionBadgeClass(h.action)}`}>{h.action}</span>
                                {h.note && <span className="text-[0.6rem] text-sol-base0 break-all">{h.note}</span>}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </>)}
              </div>
            )}

            {traceChats.length > 0 ? (
              <WaterfallChart chats={traceChats} onClickSkill={onSelectChat} />
            ) : (
              <p className="text-sol-base01 italic text-xs mt-2">No chats found for this todo</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
