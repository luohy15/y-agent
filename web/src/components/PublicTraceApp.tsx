import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { API } from "../api";
import ChatView from "./ChatView";
import ChatList from "./ChatList";
import FileViewer from "./FileViewer";
import NoteList from "./NoteList";
import LinkList, { type Link } from "./LinkList";
import { type TraceChat } from "./WaterfallChart";
import { type TodoInfo, type TodoNoteInfo } from "./TraceTodoDetail";
import { topicBadgeClass, statusBadgeClass } from "./badges";

// Reserved special-view tab for the trace.md (todo detail + waterfall + related
// links/notes), mirroring the authed app's FileViewer trace.md tab.
const TRACE_TAB = "trace.md";

interface TraceShareResponse {
  chats: TraceChat[];
  todo_name: string | null;
  todo_status: string | null;
  todo: TodoInfo | null;
  notes?: TodoNoteInfo[];
  links?: Link[];
}

type RightPanel = "chats" | "notes" | "links";

const GithubIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
);

export default function PublicTraceApp() {
  const { shareId } = useParams<{ shareId: string }>();
  const [searchParams] = useSearchParams();
  const sharePassword = searchParams.get("p") || undefined;

  const [data, setData] = useState<TraceShareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [passwordRequired, setPasswordRequired] = useState(false);
  const [passwordInput, setPasswordInput] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  // chatHide: true → FileViewer (trace.md / note tabs) center pane; false → snapshot
  // ChatView pane. Default to FileViewer/trace.md, matching the authed app's default.
  const [chatHide, setChatHide] = useState(true);
  // FileViewer tabs: the permanent `trace.md` tab plus note tabs keyed by `share_id`.
  const [openFiles, setOpenFiles] = useState<string[]>([TRACE_TAB]);
  const [activeFile, setActiveFile] = useState<string>(TRACE_TAB);
  const [rightPanel, setRightPanel] = useState<RightPanel>("chats");
  const [rightPanelOpen, setRightPanelOpen] = useState(false); // mobile drawer
  const [shareLabel, setShareLabel] = useState("share");

  const fetchShare = useCallback(async (password?: string) => {
    if (!shareId) return;
    const url = `${API}/api/trace/share?share_id=${encodeURIComponent(shareId)}${password ? `&password=${encodeURIComponent(password)}` : ""}`;
    const r = await fetch(url);
    if (r.status === 401) { setPasswordRequired(true); setLoading(false); return; }
    if (r.status === 403) { setPasswordError("Wrong password"); return; }
    if (r.status === 429) { setPasswordError("Too many attempts — try again later"); return; }
    if (!r.ok) throw new Error("Shared trace not found");
    const d: TraceShareResponse = await r.json();
    setData(d);
    setPasswordRequired(false);
    setPasswordError(null);
    setSelectedChatId((prev) => (prev && d.chats.some((c) => c.chat_id === prev)) ? prev : (d.chats[0]?.chat_id ?? null));
  }, [shareId]);

  useEffect(() => {
    if (!shareId) return;
    setLoading(true);
    setError(null);
    fetchShare(sharePassword)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [shareId, sharePassword, fetchShare]);

  const handleRefresh = useCallback(() => {
    fetchShare(sharePassword).catch((e) => setError(e.message));
  }, [fetchShare, sharePassword]);

  // Ctrl+` toggles the center FileViewer <-> ChatView, matching the authed app.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "`") {
        e.preventDefault();
        setChatHide((v) => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const onSubmitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!passwordInput || verifying) return;
    setVerifying(true);
    setPasswordError(null);
    try {
      await fetchShare(passwordInput);
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : "Error");
    } finally {
      setVerifying(false);
    }
  };

  const noteMeta = useMemo(() => {
    const m: Record<string, { content_key: string; front_matter?: Record<string, unknown> | null }> = {};
    for (const n of data?.notes ?? []) {
      if (n.share_id) m[n.share_id] = { content_key: n.content_key, front_matter: n.front_matter };
    }
    return m;
  }, [data]);

  const openNote = useCallback((note: TodoNoteInfo) => {
    // No share_id → no S3 snapshot → not openable (graceful no-op).
    if (!note.share_id) return;
    setOpenFiles((prev) => prev.includes(note.share_id!) ? prev : [...prev, note.share_id!]);
    setActiveFile(note.share_id);
    setChatHide(true);
    setRightPanelOpen(false);
  }, []);

  const closeFile = useCallback((file: string) => {
    if (file === TRACE_TAB) return; // the trace.md tab is permanent
    setOpenFiles((prev) => {
      const idx = prev.indexOf(file);
      const next = prev.filter((s) => s !== file);
      setActiveFile((cur) => cur !== file ? cur : next[Math.min(idx, next.length - 1)] ?? TRACE_TAB);
      return next;
    });
  }, []);

  const selectChat = useCallback((chatId: string) => {
    setSelectedChatId(chatId);
    setChatHide(false);
    setRightPanelOpen(false);
  }, []);

  if (loading) {
    return (
      <div className="h-dvh flex items-center justify-center bg-sol-base03">
        <span className="text-sol-base01 text-sm">Loading...</span>
      </div>
    );
  }

  if (passwordRequired) {
    return (
      <div className="h-dvh flex items-center justify-center bg-sol-base03 px-4">
        <form onSubmit={onSubmitPassword} className="w-full max-w-sm flex flex-col gap-3">
          <span className="text-sol-base01 text-sm">This share is password-protected.</span>
          <input
            type="password"
            autoFocus
            value={passwordInput}
            onChange={(e) => setPasswordInput(e.target.value)}
            placeholder="Password"
            className="w-full px-3 py-2 bg-sol-base02 text-sol-base1 rounded text-sm outline-none"
          />
          {passwordError && <span className="text-sol-red text-xs">{passwordError}</span>}
          <button
            type="submit"
            disabled={verifying || !passwordInput}
            className="px-3 py-2 bg-sol-blue text-sol-base03 rounded text-sm font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {verifying ? "..." : "Unlock"}
          </button>
        </form>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="h-dvh flex items-center justify-center bg-sol-base03">
        <span className="text-sol-red text-sm">{error || "Failed to load"}</span>
      </div>
    );
  }

  const selectedChat = data.chats.find((c) => c.chat_id === selectedChatId);
  const skills = [...new Set(data.chats.map((c) => (c.skill && c.skill.trim()) || c.topic).filter(Boolean))];

  const modeBtnClass = (active: boolean) =>
    `p-1.5 sm:p-1 rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1"}`;
  const tabBtnClass = (active: boolean) =>
    `px-2 py-1 text-[0.65rem] rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1"}`;

  const rightPanelBody = (
    <div className="h-full min-h-0 flex flex-col">
      <div className="flex items-center gap-1 px-2 py-2 border-b border-sol-base02 shrink-0">
        <button onClick={() => setRightPanel("chats")} className={tabBtnClass(rightPanel === "chats")} title="Chats">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        </button>
        <button onClick={() => setRightPanel("notes")} className={tabBtnClass(rightPanel === "notes")} title="Notes">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
        </button>
        <button onClick={() => setRightPanel("links")} className={tabBtnClass(rightPanel === "links")} title="Links">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
        </button>
        <button onClick={handleRefresh} className="ml-auto p-1 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer" title="Refresh trace">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        </button>
        <button onClick={() => setRightPanelOpen(false)} className="md:hidden p-1 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer" title="Close">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">
        {rightPanel === "chats" ? (
          <ChatList
            isLoggedIn={false}
            hideFilters
            items={data.chats}
            selectedChatId={selectedChatId}
            onSelectChat={(id) => { if (id) selectChat(id); }}
          />
        ) : rightPanel === "notes" ? (
          <NoteList
            isLoggedIn={false}
            onOpenFile={() => {}}
            items={data.notes ?? []}
            onSelectNote={(n) => openNote(n as TodoNoteInfo)}
          />
        ) : (
          <LinkList isLoggedIn={false} onPreview={() => {}} items={data.links ?? []} />
        )}
      </div>
    </div>
  );

  return (
    <div className="h-dvh flex flex-col overflow-hidden bg-sol-base03">
      {/* Full-width page header: centered todo title + badges, above the center|right split */}
      <div className="flex flex-wrap items-center justify-center gap-1.5 px-2 pt-2.5 pb-2 bg-sol-base03 shrink-0">
        <span className="text-sol-base1 text-sm font-medium truncate">{data.todo_name || "Trace"}</span>
        {data.todo_status && <span className={`text-[0.6rem] px-1 rounded ${statusBadgeClass(data.todo_status)}`}>{data.todo_status}</span>}
        <div className="flex flex-wrap gap-0.5">
          {skills.map((s) => <span key={s} className={`text-[0.6rem] ${topicBadgeClass(s)}`}>{s}</span>)}
        </div>
      </div>
      <div className="flex flex-1 min-h-0">
        {/* Center column */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          {/* Toolbar: mode switcher (left) + mobile right-panel toggle (right) */}
          <div className="flex items-center gap-1 px-2 py-2 bg-sol-base03 shrink-0 border-b border-sol-base02">
            <button onClick={() => setChatHide(true)} className={modeBtnClass(chatHide)} title="Notes">
              <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" /></svg>
            </button>
            <button onClick={() => setChatHide(false)} className={modeBtnClass(!chatHide)} title="Chat">
              <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z"/></svg>
            </button>
            {/* Mobile right-panel toggle */}
            <button onClick={() => setRightPanelOpen(true)} className="md:hidden ml-auto p-1.5 text-sol-base01 hover:text-sol-base1 bg-sol-base02 rounded cursor-pointer" title="Chats & context">
              <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2z"/></svg>
            </button>
          </div>
          {/* Center two-mode pane */}
          <div className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden relative">
            {/* FileViewer (trace.md + note tabs), shown when chatHide */}
            <div className={`absolute inset-0 ${chatHide ? "" : "hidden"}`}>
              <FileViewer
                mode="public"
                openFiles={openFiles}
                activeFile={activeFile}
                onSelectFile={(s) => setActiveFile(s)}
                onCloseFile={closeFile}
                onReorderFiles={setOpenFiles}
                noteMeta={noteMeta}
                traceData={data}
                onSelectChat={selectChat}
                onOpenNote={openNote}
              />
            </div>
            {/* Snapshot ChatView, shown when !chatHide */}
            <div className={`absolute inset-0 flex flex-col ${chatHide ? "hidden" : ""}`}>
              {selectedChat ? (
                <ChatView
                  key={selectedChat.chat_id}
                  mode="snapshot"
                  isLoggedIn={false}
                  chatId={selectedChat.chat_id}
                  snapshotMessages={(selectedChat.messages as unknown[]) || []}
                  onRefresh={handleRefresh}
                />
              ) : (
                <div className="flex-1 flex items-center justify-center text-sol-base01 text-sm italic">No chat selected.</div>
              )}
            </div>
          </div>
        </div>
        {/* Right panel (desktop) */}
        <div className="hidden md:flex shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden flex-col w-[260px]">
          {rightPanelBody}
        </div>
        {/* Right panel (mobile drawer) */}
        {rightPanelOpen && (
          <div className="fixed inset-0 bg-black/40 z-20 md:hidden" onClick={() => setRightPanelOpen(false)} />
        )}
        <div className={`fixed inset-y-0 right-0 z-30 transform transition-transform duration-200 md:hidden shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden flex flex-col w-[280px] max-w-[85vw] ${rightPanelOpen ? "translate-x-0" : "translate-x-full"}`}>
          {rightPanelBody}
        </div>
      </div>
      {/* Footer */}
      <div className="shrink-0 px-6 py-2 flex items-center justify-center gap-3 border-t border-sol-base02">
        <button
          onClick={() => { navigator.clipboard.writeText(window.location.href); setShareLabel("copied!"); setTimeout(() => setShareLabel("share"), 1500); }}
          className={`font-mono cursor-pointer px-2 py-0.5 rounded text-[0.7rem] font-semibold ${shareLabel === "copied!" ? "bg-sol-green text-sol-base03" : "bg-sol-base02 text-sol-base01"}`}
        >
          {shareLabel}
        </button>
        <a href="https://github.com/luohy15/y-agent" target="_blank" rel="noopener noreferrer" className="flex items-center text-sol-base01 hover:text-sol-base1">
          <GithubIcon />
        </a>
      </div>
    </div>
  );
}
