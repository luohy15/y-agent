import { useState, useEffect, useMemo, useRef } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken, jsonFetcher as fetcher } from "../api";
import WaterfallChart, { type TraceChat } from "./WaterfallChart";
import { topicBadgeClass, statusBadgeClass } from "./badges";
import SharePopover, { type ExistingShare } from "./SharePopover";
import TraceTodoDetail, { type TodoInfo, type TodoPatch } from "./TraceTodoDetail";

export type { TraceChat } from "./WaterfallChart";
export type { TodoInfo, TodoPatch } from "./TraceTodoDetail";

export interface TraceViewProps {
  isLoggedIn: boolean;
  selectedTraceId: string | null;
  defaultWorkDir?: string;
  onSelectChat?: (chatId: string) => void;
  onPreviewLink?: (activityId: string) => void;
  onSelectCalendarEvent?: (startTime: string) => void;
  onOpenFile?: (path: string) => void;
  onTraceTodoDirtyChange?: (dirty: boolean) => void;
  // Public trace projection: when supplied, TraceView renders read-only from this
  // injected payload and never self-fetches `/api/trace/chats` or `/api/trace/share/mine`
  // (both JWT-only). The trace SharePopover + per-note NoteShareButton are hidden, and
  // note clicks call `onOpenNote` (open as a public FileViewer tab) instead of `onOpenFile`.
  injectedData?: TraceChatsResponse | null;
  onOpenNote?: (note: TraceNote) => void;
  /** Always-visible back affordance for in-place module detail (todo 3179). */
  onBack?: () => void;
  /**
   * When true, a successful authenticated payload without a valid `todo` is treated
   * as unavailable (stale/deleted selection) rather than an empty detail. Public
   * injected mode ignores this flag.
   */
  requireTodo?: boolean;
  /**
   * Fired when `requireTodo` resolves the selection as missing/malformed.
   * Latched once per `selectedTraceId` while unavailable holds; callers should
   * still treat the callback as idempotent (todo 3179 M3).
   */
  onUnavailable?: () => void;
}

export interface TraceLink {
  link_id: string;
  base_url: string;
  title?: string;
  download_status?: string | null;
  activity_id?: string;
}

export interface TraceNote {
  note_id: string;
  content_key: string;
  front_matter?: Record<string, any> | null;
  created_at?: string;
  share_id?: string;
  has_password?: boolean;
}

export interface TraceCalendarEvent {
  event_id: string;
  summary: string;
  start_time: string;
  end_time?: string;
  description?: string;
  all_day: boolean;
  status: string;
  source?: string;
}

export interface TraceChatsResponse {
  chats: TraceChat[];
  todo_name: string | null;
  todo_status: string | null;
  todo: TodoInfo | null;
  links?: TraceLink[];
  notes?: TraceNote[];
  calendar_events?: TraceCalendarEvent[];
}

// Stable empty fallback so normalizeTraceData failures do not mint a new chats
// identity on every parent render (WaterfallChart memos on `chats`).
const EMPTY_TRACE: TraceChatsResponse = {
  chats: [],
  todo_name: null,
  todo_status: null,
  todo: null,
  links: [],
  notes: [],
  calendar_events: [],
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

/** Normalize a trace payload so malformed fields cannot throw during render. */
export function normalizeTraceData(raw: unknown): TraceChatsResponse | null {
  const obj = asRecord(raw);
  if (!obj) return null;
  const todoRaw = asRecord(obj.todo);
  const todoId = todoRaw && typeof todoRaw.todo_id === "string" ? todoRaw.todo_id : null;
  const todo: TodoInfo | null = todoRaw && todoId
    ? {
        ...(todoRaw as unknown as TodoInfo),
        todo_id: todoId,
        name: typeof todoRaw.name === "string" ? todoRaw.name : todoId,
        status: typeof todoRaw.status === "string" ? todoRaw.status : "pending",
      }
    : null;
  return {
    chats: asArray<TraceChat>(obj.chats),
    todo_name: typeof obj.todo_name === "string" ? obj.todo_name : null,
    todo_status: typeof obj.todo_status === "string" ? obj.todo_status : null,
    todo,
    links: asArray<TraceLink>(obj.links),
    notes: asArray<TraceNote>(obj.notes),
    calendar_events: asArray<TraceCalendarEvent>(obj.calendar_events),
  };
}

function getDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function formatEventTime(ev: TraceCalendarEvent): string {
  const start = new Date(ev.start_time);
  if (ev.all_day) return start.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false };
  const startStr = start.toLocaleString(undefined, opts);
  if (!ev.end_time) return startStr;
  const end = new Date(ev.end_time);
  const sameDay = start.toDateString() === end.toDateString();
  const endStr = sameDay
    ? end.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })
    : end.toLocaleString(undefined, opts);
  return `${startStr} – ${endStr}`;
}

function NoteShareButton({ noteId, existingShare, mutateTrace }: { noteId: string; existingShare: ExistingShare | null; mutateTrace: () => Promise<TraceChatsResponse | undefined> }) {
  const createNoteShare = async (opts: { password?: string; generate_password?: boolean }) => {
    const res = await authFetch(`${API}/api/note/share`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note_id: noteId, ...opts }),
    });
    if (!res.ok) throw new Error("share failed");
    const result = await res.json();
    await mutateTrace();
    return result;
  };

  const deleteNoteShare = async (shareId: string) => {
    const res = await authFetch(`${API}/api/note/share?share_id=${encodeURIComponent(shareId)}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error("delete failed");
    await mutateTrace();
  };

  return (
    <SharePopover
      onCreate={createNoteShare}
      buildUrl={(shareId) => `${window.location.origin}/n/${shareId}`}
      buttonClassName="text-[0.6rem] font-mono px-1.5 py-0.5 rounded cursor-pointer bg-sol-base02 text-sol-base01 hover:text-sol-base0"
      align="right"
      existingShare={existingShare}
      onRefresh={() => createNoteShare({})}
      onDelete={deleteNoteShare}
    />
  );
}

export default function TraceView({
  isLoggedIn,
  selectedTraceId,
  defaultWorkDir,
  onSelectChat,
  onPreviewLink,
  onSelectCalendarEvent,
  onOpenFile,
  onTraceTodoDirtyChange,
  injectedData,
  onOpenNote,
  onBack,
  requireTodo = false,
  onUnavailable,
}: TraceViewProps) {
  // Public projection: render read-only from the injected payload, skip all JWT fetches.
  const publicMode = injectedData != null;

  // Fetch chats for selected trace (authed only; skipped when data is injected)
  const traceChatsKey = selectedTraceId && isLoggedIn && !publicMode ? `${API}/api/trace/chats?trace_id=${encodeURIComponent(selectedTraceId)}` : null;
  const {
    data: fetchedTraceData,
    error: fetchError,
    mutate: mutateTrace,
  } = useSWR<TraceChatsResponse>(traceChatsKey, fetcher, { revalidateOnFocus: false });
  // Injected public payloads stay as-provided for the existing projection;
  // authenticated fetches are normalized so a malformed field cannot throw.
  // Memoized on the fetched payload so chats/links/notes keep stable identity
  // across parent re-renders (WaterfallChart memos on `chats`).
  const authedTraceData = useMemo(() => {
    if (publicMode || fetchedTraceData === undefined) return undefined;
    return normalizeTraceData(fetchedTraceData) ?? EMPTY_TRACE;
  }, [publicMode, fetchedTraceData]);

  // Fetch current share (if any) for this trace
  const myShareKey = selectedTraceId && isLoggedIn && !publicMode ? `${API}/api/trace/share/mine?trace_id=${encodeURIComponent(selectedTraceId)}` : null;
  const { data: myShare, mutate: mutateMyShare } = useSWR<ExistingShare | null>(
    myShareKey,
    async (url: string) => {
      const res = await authFetch(url);
      if (res.status === 404) return null;
      if (res.status === 401) { clearToken(); throw new Error("Unauthorized"); }
      if (!res.ok) throw new Error("fetch failed");
      return res.json();
    },
    { revalidateOnFocus: false },
  );

  const loaded = publicMode ? injectedData != null : fetchedTraceData !== undefined;
  const fetchFailed = !publicMode && !!fetchError && !loaded;
  const traceChats = publicMode ? injectedData?.chats : authedTraceData?.chats;
  const todoName = publicMode ? injectedData?.todo_name : (authedTraceData?.todo_name ?? null);
  const todoStatus = publicMode ? injectedData?.todo_status : (authedTraceData?.todo_status ?? null);
  const todoInfo = publicMode ? (injectedData?.todo ?? null) : (authedTraceData?.todo ?? null);
  const traceLinks = publicMode ? injectedData?.links : (authedTraceData?.links ?? []);
  const traceNotes = publicMode ? injectedData?.notes : (authedTraceData?.notes ?? []);
  const traceEvents = publicMode ? injectedData?.calendar_events : (authedTraceData?.calendar_events ?? []);
  const hasValidTodo = !!(todoInfo && typeof todoInfo.todo_id === "string" && todoInfo.todo_id);
  const unavailable = !publicMode && requireTodo && loaded && !fetchFailed && !hasValidTodo;

  const [todoDetailOpen, setTodoDetailOpen] = useState(true);
  const [linksOpen, setLinksOpen] = useState(true);
  const [notesOpen, setNotesOpen] = useState(true);
  const [eventsOpen, setEventsOpen] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  // Notes deselected from the batch-share picker (default: none → all selected).
  const [deselectedNoteIds, setDeselectedNoteIds] = useState<Set<string>>(new Set());
  // Latch onUnavailable once per selectedTraceId while unavailable holds, so an
  // inline module closure identity change cannot re-fire it every render.
  const unavailableNotifiedForRef = useRef<string | null>(null);
  // Reset the batch-share selection when switching traces.
  useEffect(() => { setDeselectedNoteIds(new Set()); }, [selectedTraceId]);

  // Module detail: a required todo that resolved missing/malformed is unavailable.
  // Transient fetch failures never fire this (parent keeps the selection for retry).
  useEffect(() => {
    if (!unavailable) {
      unavailableNotifiedForRef.current = null;
      return;
    }
    if (unavailableNotifiedForRef.current === selectedTraceId) return;
    unavailableNotifiedForRef.current = selectedTraceId;
    onUnavailable?.();
  }, [unavailable, onUnavailable, selectedTraceId]);

  const createTraceShare = async (opts: { password?: string; generate_password?: boolean }) => {
    if (!selectedTraceId) throw new Error("no trace");
    // Batch-share selected assoc'd notes server-side in one request: the backend
    // shares each note in public mode (no password), skipping already-shared ones.
    // Note links surface on the public trace page as bare /n/<share_id>, so a
    // per-note password would force a second prompt there.
    const noteIds = (traceNotes ?? [])
      .filter((n) => !n.share_id && !deselectedNoteIds.has(n.note_id))
      .map((n) => n.note_id);
    const res = await authFetch(`${API}/api/trace/share`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        trace_id: selectedTraceId,
        ...opts,
        ...(noteIds.length > 0 ? { note_ids: noteIds } : {}),
      }),
    });
    if (!res.ok) throw new Error("share failed");
    const result = await res.json();
    if (noteIds.length > 0) await mutateTrace();
    mutateMyShare();
    return result;
  };
  const deleteTraceShare = async (shareId: string) => {
    const res = await authFetch(`${API}/api/trace/share?share_id=${encodeURIComponent(shareId)}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error("delete failed");
    // The backend DELETE cascades: it revokes the assoc'd notes' shares too, so the
    // trace and its notes fully revert to private. Refresh the trace payload to clear
    // the now-stale share_id badges, then the trace-share state.
    await mutateTrace();
    mutateMyShare();
  };
  const buildTraceShareUrl = (shareId: string) => `${window.location.origin}/t/${shareId}`;

  const headerBack = onBack ? (
    <button
      type="button"
      onClick={onBack}
      className="inline-flex items-center gap-1 text-[0.7rem] text-sol-base01 hover:text-sol-base0 cursor-pointer shrink-0"
      data-testid="trace-back"
    >
      <span aria-hidden="true">←</span>
      <span>Back</span>
    </button>
  ) : null;

  return (
    <div className="h-full overflow-y-auto bg-sol-base03 p-3">
      {!selectedTraceId && !publicMode ? (
        <div className="flex flex-col items-center justify-center h-full gap-2 text-sol-base01 italic text-sm">
          {headerBack}
          <span>Select a todo to view details</span>
        </div>
      ) : fetchFailed ? (
        <div className="flex flex-col items-center justify-center h-full gap-3 text-sm" data-testid="trace-error">
          {headerBack}
          <span className="text-sol-base01">Failed to load todo detail</span>
          <button
            type="button"
            onClick={() => { void mutateTrace(); }}
            className="text-[0.75rem] font-mono px-2 py-1 rounded cursor-pointer bg-sol-base02 text-sol-base0 hover:text-sol-base1"
            data-testid="trace-retry"
          >
            Retry
          </button>
        </div>
      ) : unavailable ? (
        <div className="flex flex-col items-center justify-center h-full gap-3 text-sm" data-testid="trace-unavailable">
          {headerBack}
          <span className="text-sol-base01">This todo is unavailable</span>
          {onBack && (
            <button
              type="button"
              onClick={onBack}
              className="text-[0.75rem] font-mono px-2 py-1 rounded cursor-pointer bg-sol-base02 text-sol-base0 hover:text-sol-base1"
            >
              Back to list
            </button>
          )}
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
              {headerBack}
              <span className="text-sol-base1 text-sm font-medium">
                {todoName || selectedTraceId}
              </span>
              {todoStatus && (
                <span className={`text-[0.6rem] px-1 rounded ${statusBadgeClass(todoStatus)}`}>
                  {todoStatus}
                </span>
              )}
              {/* Skill+backend+bot_name badges */}
              {traceChats.length > 0 && (
                <div className="flex flex-wrap gap-0.5">
                  {[...new Set(traceChats.map((c) => {
                    const skill = (c.skill && c.skill.trim()) || c.topic || "";
                    const backend = c.backend || "";
                    const botName = c.bot_name || "";
                    if (!skill) return "";
                    return `${skill}:${backend}:${botName}`;
                  }).filter(Boolean))].map((key) => {
                    const parts = key.split(":");
                    const skill = parts[0];
                    const backend = parts[1] || "";
                    const botName = parts[2] || "";
                    const display = [botName, backend].filter(Boolean).join(" · ");
                    return (
                      <span key={key} className={`text-[0.6rem] ${topicBadgeClass(skill)}`}>
                        {skill}{display && <span className="ml-0.5 opacity-70">{display}</span>}
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 mb-1">
              <button
                onClick={() => navigator.clipboard.writeText(todoInfo?.todo_id || selectedTraceId || "")}
                className="inline-flex items-center text-[0.6rem] text-sol-base01 hover:text-sol-base0 font-mono cursor-pointer"
                title="Copy todo ID"
              >
                #{todoInfo?.todo_id || selectedTraceId}
              </button>
              {!publicMode && <SharePopover
                onCreate={createTraceShare}
                buildUrl={buildTraceShareUrl}
                buttonClassName="text-[0.6rem] font-mono px-1.5 py-0.5 rounded cursor-pointer bg-sol-base02 text-sol-base01 hover:text-sol-base0"
                align="left"
                existingShare={myShare ?? null}
                onDelete={deleteTraceShare}
                extra={traceNotes && traceNotes.length > 0 ? (
                  <div className="mt-2 pt-2 border-t border-sol-base02">
                    <div className="text-sol-base01 mb-1">Also share notes</div>
                    <div className="max-h-32 overflow-y-auto space-y-0.5">
                      {traceNotes.map((note) => {
                        const shared = !!note.share_id;
                        const checked = shared || !deselectedNoteIds.has(note.note_id);
                        return (
                          <label key={note.note_id} className="flex items-center gap-2 py-0.5 cursor-pointer">
                            <input
                              type="checkbox" className="y-check"
                              checked={checked}
                              disabled={shared}
                              onChange={(e) => {
                                setDeselectedNoteIds((prev) => {
                                  const next = new Set(prev);
                                  if (e.target.checked) next.delete(note.note_id);
                                  else next.add(note.note_id);
                                  return next;
                                });
                              }}
                            />
                            <span className="text-sol-base0 font-mono text-[0.65rem] truncate min-w-0">#{note.note_id}</span>
                            {shared && <span className="ml-auto shrink-0 text-[0.6rem] text-sol-green">shared</span>}
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ) : undefined}
              />}
            </div>

            {/* Todo detail section */}
            {todoInfo && (
              <TraceTodoDetail
                todoInfo={todoInfo}
                open={todoDetailOpen}
                setOpen={setTodoDetailOpen}
                historyOpen={historyOpen}
                setHistoryOpen={setHistoryOpen}
                onDirtyChange={publicMode ? undefined : onTraceTodoDirtyChange}
                onSave={publicMode ? undefined : async (patch: TodoPatch) => {
                  const res = await authFetch(`${API}/api/todo/update`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ todo_id: todoInfo.todo_id, ...patch }),
                  });
                  if (!res.ok) throw new Error("update failed");
                  await mutateTrace();
                }}
              />
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
                    {traceNotes.map((note) => {
                      // Public mode: only notes carrying a `share_id` (S3 snapshot) are
                      // openable as FileViewer tabs; others are shown but non-openable.
                      const openable = publicMode ? !!note.share_id : !!onOpenFile;
                      return (
                      <div
                        key={note.note_id}
                        className={`bg-sol-base02/50 rounded px-2 py-1 ${openable ? "cursor-pointer hover:bg-sol-base02" : ""}`}
                        onClick={() => {
                          if (publicMode) {
                            if (note.share_id) onOpenNote?.(note);
                          } else {
                            onOpenFile?.(defaultWorkDir ? `${defaultWorkDir}/${note.content_key}` : note.content_key);
                          }
                        }}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="text-[0.6rem] text-sol-base01 min-w-0 truncate">#{note.note_id}</span>
                          {note.front_matter?.tags?.map((tag: string) => (
                            <span key={tag} className="text-[0.55rem] bg-sol-base02 text-sol-base0 px-1 rounded shrink-0">{tag}</span>
                          ))}
                          {!publicMode && (
                            <div className="ml-auto shrink-0" onClick={(event) => event.stopPropagation()}>
                              <NoteShareButton
                                noteId={note.note_id}
                                existingShare={note.share_id ? { share_id: note.share_id, has_password: !!note.has_password } : null}
                                mutateTrace={mutateTrace}
                              />
                            </div>
                          )}
                        </div>
                        <p className="text-[0.7rem] text-sol-base1 whitespace-pre-wrap mt-0.5">{note.content_key}</p>
                      </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Calendar Events */}
            {traceEvents && traceEvents.length > 0 && (
              <div className="mt-3 border border-sol-base02 rounded">
                <button
                  onClick={() => setEventsOpen((v) => !v)}
                  className="w-full flex items-center gap-2 px-2 py-1 text-xs text-sol-base01 hover:text-sol-base0 cursor-pointer"
                >
                  <span className="text-[0.6rem]">{eventsOpen ? "▼" : "▶"}</span>
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
                  </svg>
                  <span className="font-medium text-sol-base0">Calendar Events ({traceEvents.length})</span>
                </button>
                {eventsOpen && (
                  <div className="px-2 pb-2 space-y-1">
                    {traceEvents.map((ev) => (
                      <div
                        key={ev.event_id}
                        className={`bg-sol-base02/50 rounded px-2 py-1 ${onSelectCalendarEvent ? "cursor-pointer hover:bg-sol-base02" : ""}`}
                        onClick={onSelectCalendarEvent ? () => onSelectCalendarEvent(ev.start_time) : undefined}
                        title={onSelectCalendarEvent ? "Open in calendar" : undefined}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="text-[0.7rem] text-sol-base1 truncate min-w-0 flex-1">{ev.summary}</span>
                          {ev.source && (
                            <span className="text-[0.55rem] bg-sol-base02 text-sol-base0 px-1 rounded shrink-0">{ev.source}</span>
                          )}
                        </div>
                        <div className="text-[0.65rem] text-sol-base01 mt-0.5">
                          {formatEventTime(ev)}{ev.all_day ? " · all-day" : ""}
                        </div>
                        {ev.description && (
                          <p className="text-[0.65rem] text-sol-base0 whitespace-pre-wrap mt-0.5">{ev.description}</p>
                        )}
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
