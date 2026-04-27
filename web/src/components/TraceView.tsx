import { useState } from "react";
import useSWR from "swr";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API, authFetch, clearToken, jsonFetcher as fetcher } from "../api";
import WaterfallChart, { type TraceChat } from "./WaterfallChart";
import { topicBadgeClass, statusBadgeClass, priorityColorClass, actionBadgeClass } from "./badges";
import SharePopover, { type ExistingShare } from "./SharePopover";

interface TraceViewProps {
  isLoggedIn: boolean;
  selectedTraceId: string | null;
  defaultWorkDir?: string;
  onSelectChat?: (chatId: string) => void;
  onPreviewLink?: (activityId: string) => void;
  onOpenFile?: (path: string) => void;
}

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

interface TraceLink {
  link_id: string;
  base_url: string;
  title?: string;
  download_status?: string;
  activity_id?: string;
}

interface TraceNote {
  note_id: string;
  content_key: string;
  front_matter?: { tags?: string[]; [key: string]: unknown };
  created_at?: string;
}

interface TraceChatsResponse {
  chats: TraceChat[];
  todo_name: string | null;
  todo_status: string | null;
  todo: TodoInfo | null;
  links?: TraceLink[];
  notes?: TraceNote[];
}

function getDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

export default function TraceView({ isLoggedIn, selectedTraceId, defaultWorkDir, onSelectChat, onPreviewLink, onOpenFile }: TraceViewProps) {
  // Fetch chats for selected trace
  const { data: traceData } = useSWR<TraceChatsResponse>(
    selectedTraceId && isLoggedIn ? `${API}/api/trace/chats?trace_id=${encodeURIComponent(selectedTraceId)}` : null,
    fetcher,
  );

  // Fetch current share (if any) for this trace
  const myShareKey = selectedTraceId && isLoggedIn ? `${API}/api/trace/share/mine?trace_id=${encodeURIComponent(selectedTraceId)}` : null;
  const { data: myShare, mutate: mutateMyShare } = useSWR<ExistingShare | null>(
    myShareKey,
    async (url: string) => {
      const res = await authFetch(url);
      if (res.status === 404) return null;
      if (res.status === 401) { clearToken(); throw new Error("Unauthorized"); }
      if (!res.ok) throw new Error("fetch failed");
      return res.json();
    },
  );

  const traceChats = traceData?.chats;
  const todoName = traceData?.todo_name;
  const todoStatus = traceData?.todo_status;
  const todoInfo = traceData?.todo;
  const traceLinks = traceData?.links;
  const traceNotes = traceData?.notes;
  const [todoDetailOpen, setTodoDetailOpen] = useState(true);
  const [linksOpen, setLinksOpen] = useState(true);
  const [notesOpen, setNotesOpen] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const createTraceShare = async (opts: { password?: string; generate_password?: boolean }) => {
    if (!selectedTraceId) throw new Error("no trace");
    const res = await authFetch(`${API}/api/trace/share`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trace_id: selectedTraceId, ...opts }),
    });
    if (!res.ok) throw new Error("share failed");
    const result = await res.json();
    mutateMyShare();
    return result;
  };
  const deleteTraceShare = async (shareId: string) => {
    const res = await authFetch(`${API}/api/trace/share?share_id=${encodeURIComponent(shareId)}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error("delete failed");
    mutateMyShare();
  };
  const buildTraceShareUrl = (shareId: string) => `${window.location.origin}/t/${shareId}`;

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
              {/* Skill+backend badges */}
              {traceChats.length > 0 && (
                <div className="flex flex-wrap gap-0.5">
                  {[...new Set(traceChats.map((c) => {
                    const skill = (c.skill && c.skill.trim()) || c.topic;
                    return c.backend ? `${skill}:${c.backend}` : skill;
                  }).filter(Boolean))].map((key) => {
                    const skill = key.includes(":") ? key.slice(0, key.indexOf(":")) : key;
                    const backend = key.includes(":") ? key.slice(key.indexOf(":") + 1) : "";
                    return (
                      <span key={key} className={`text-[0.6rem] ${topicBadgeClass(skill)}`}>
                        {skill}{backend && <span className="ml-0.5 opacity-70">{backend}</span>}
                      </span>
                    );
                  })}
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
              <SharePopover
                onCreate={createTraceShare}
                buildUrl={buildTraceShareUrl}
                buttonClassName="text-[0.6rem] font-mono px-1.5 py-0.5 rounded cursor-pointer bg-sol-base02 text-sol-base01 hover:text-sol-base0"
                align="left"
                existingShare={myShare ?? null}
                onDelete={deleteTraceShare}
              />
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
                        <div className="text-sol-base0 prose prose-sm prose-invert max-w-none [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_pre]:my-1 [&_pre]:overflow-x-auto [&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-xs">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{todoInfo.desc}</ReactMarkdown>
                        </div>
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
              <WaterfallChart chats={traceChats} onClickChat={onSelectChat} />
            ) : (
              <p className="text-sol-base01 italic text-xs mt-2">No chats found for this todo</p>
            )}

            {/* Related Links */}
            {traceLinks && traceLinks.length > 0 && (
              <div className="mt-3 border border-sol-base02 rounded">
                <button
                  onClick={() => setLinksOpen((v) => !v)}
                  className="w-full flex items-center gap-2 px-2 py-1 text-xs text-sol-base01 hover:text-sol-base0 cursor-pointer"
                >
                  <span className="text-[0.6rem]">{linksOpen ? "▼" : "▶"}</span>
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                  </svg>
                  <span className="font-medium text-sol-base0">Related Links ({traceLinks.length})</span>
                </button>
                {linksOpen && (
                  <div className="px-2 pb-2 space-y-1">
                    {traceLinks.map((link) => (
                      <div key={link.link_id} className="flex items-center gap-1.5 py-0.5 group">
                        <img
                          src={`https://www.google.com/s2/favicons?domain=${getDomain(link.base_url)}&sz=16`}
                          alt=""
                          className="w-3.5 h-3.5 shrink-0"
                          loading="lazy"
                        />
                        <a
                          href={link.base_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sol-base0 hover:text-sol-blue truncate text-[0.7rem] min-w-0 flex-1"
                          title={link.base_url}
                        >
                          {link.title || getDomain(link.base_url)}
                        </a>
                        {link.download_status === "done" && link.activity_id && onPreviewLink && (
                          <button
                            onClick={() => onPreviewLink(link.activity_id!)}
                            className="shrink-0 w-4 h-4 flex items-center justify-center text-sol-base01 opacity-0 group-hover:opacity-100 hover:text-sol-cyan cursor-pointer"
                            title="Preview content"
                          >
                            <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor">
                              <path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/>
                              <path fillRule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clipRule="evenodd"/>
                            </svg>
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Related Notes */}
            {traceNotes && traceNotes.length > 0 && (
              <div className="mt-3 border border-sol-base02 rounded">
                <button
                  onClick={() => setNotesOpen((v) => !v)}
                  className="w-full flex items-center gap-2 px-2 py-1 text-xs text-sol-base01 hover:text-sol-base0 cursor-pointer"
                >
                  <span className="text-[0.6rem]">{notesOpen ? "▼" : "▶"}</span>
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
                  </svg>
                  <span className="font-medium text-sol-base0">Notes ({traceNotes.length})</span>
                </button>
                {notesOpen && (
                  <div className="px-2 pb-2 space-y-1">
                    {traceNotes.map((note) => (
                      <div
                        key={note.note_id}
                        className={`bg-sol-base02/50 rounded px-2 py-1 ${onOpenFile ? "cursor-pointer hover:bg-sol-base02" : ""}`}
                        onClick={() => onOpenFile?.(defaultWorkDir ? `${defaultWorkDir}/${note.content_key}` : note.content_key)}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="text-[0.6rem] text-sol-base01">#{note.note_id}</span>
                          {note.front_matter?.tags?.map((tag) => (
                            <span key={tag} className="text-[0.55rem] bg-sol-base02 text-sol-base0 px-1 rounded">{tag}</span>
                          ))}
                        </div>
                        <p className="text-[0.7rem] text-sol-base1 whitespace-pre-wrap mt-0.5">{note.content_key}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
