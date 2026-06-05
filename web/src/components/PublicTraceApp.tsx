import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { API } from "../api";
import ChatView from "./ChatView";
import FileViewer from "./FileViewer";
import NoteList from "./NoteList";
import LinkList, { type Link } from "./LinkList";
import WaterfallChart, { type TraceChat } from "./WaterfallChart";
import TraceTodoDetail, { type TodoInfo, type TodoNoteInfo } from "./TraceTodoDetail";
import { topicBadgeClass, getTopicColor, statusBadgeClass } from "./badges";

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
  // chatHide: true → FileViewer (notes) center pane; false → snapshot ChatView pane.
  const [chatHide, setChatHide] = useState(false);
  // Open note tabs are keyed by note `share_id`.
  const [openNotes, setOpenNotes] = useState<string[]>([]);
  const [activeNote, setActiveNote] = useState<string | null>(null);
  const [rightPanel, setRightPanel] = useState<RightPanel>("chats");
  const [rightPanelOpen, setRightPanelOpen] = useState(false); // mobile drawer
  const [todoDetailOpen, setTodoDetailOpen] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
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
    setOpenNotes((prev) => prev.includes(note.share_id!) ? prev : [...prev, note.share_id!]);
    setActiveNote(note.share_id);
    setChatHide(true);
    setRightPanelOpen(false);
  }, []);

  const closeNote = useCallback((shareId: string) => {
    setOpenNotes((prev) => {
      const idx = prev.indexOf(shareId);
      const next = prev.filter((s) => s !== shareId);
      setActiveNote((cur) => cur !== shareId ? cur : (next.length === 0 ? null : next[Math.min(idx, next.length - 1)]));
      return next;
    });
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

  const todoInfo = data.todo ? { ...data.todo, notes: data.notes ?? [] } : null;
  const selectedChat = data.chats.find((c) => c.chat_id === selectedChatId);
  const skills = [...new Set(data.chats.map((c) => (c.skill && c.skill.trim()) || c.topic).filter(Boolean))];

  const modeBtnClass = (active: boolean) =>
    `p-1.5 sm:p-1 rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1"}`;
  const tabBtnClass = (active: boolean) =>
    `px-2 py-1 text-[0.65rem] rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1"}`;

  const rightPanelBody = (
    <div className="h-full min-h-0 flex flex-col">
      <div className="flex items-center gap-1 px-2 py-1 border-b border-sol-base02 shrink-0">
        <button onClick={() => setRightPanel("chats")} className={tabBtnClass(rightPanel === "chats")}>Chat</button>
        <button onClick={() => setRightPanel("notes")} className={tabBtnClass(rightPanel === "notes")}>Note</button>
        <button onClick={() => setRightPanel("links")} className={tabBtnClass(rightPanel === "links")}>Link</button>
        <button onClick={handleRefresh} className="ml-auto p-1 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer" title="Refresh trace">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        </button>
        <button onClick={() => setRightPanelOpen(false)} className="md:hidden p-1 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer" title="Close">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">
        {rightPanel === "chats" ? (
          <div className="h-full overflow-y-auto p-1.5 space-y-0.5 text-xs">
            {data.chats.length === 0 ? (
              <p className="text-sol-base01 italic p-2">No chats</p>
            ) : data.chats.map((c) => {
              const topicColor = getTopicColor(c.topic);
              const isSelected = c.chat_id === selectedChatId;
              const displayTitle = (c.title || "").replace(/^\[.*?\]\s*/, "") || c.chat_id.slice(0, 8);
              return (
                <button
                  key={c.chat_id}
                  onClick={() => { setSelectedChatId(c.chat_id); setChatHide(false); setRightPanelOpen(false); }}
                  className={`w-full text-left text-[0.7rem] px-2 py-1.5 rounded cursor-pointer truncate ${
                    isSelected ? `${topicColor.bg} ${topicColor.text}` : "text-sol-base01 hover:text-sol-base0 hover:bg-sol-base02"
                  }`}
                >
                  <span className="font-medium">{c.topic || "chat"}</span>
                  <span className="ml-1 opacity-70">{displayTitle}</span>
                </button>
              );
            })}
          </div>
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
      <div className="flex flex-1 min-h-0">
        {/* Center column */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          {/* Mode switcher header */}
          <div className="flex items-center gap-1 px-2 py-2 bg-sol-base03 shrink-0 border-b border-sol-base02">
            <button onClick={() => setChatHide(true)} className={modeBtnClass(chatHide)} title="Notes">
              <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" /></svg>
            </button>
            <button onClick={() => setChatHide(false)} className={modeBtnClass(!chatHide)} title="Chat">
              <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z"/></svg>
            </button>
            <span className="ml-2 text-sol-base1 text-sm font-medium truncate">{data.todo_name || "Trace"}</span>
            {data.todo_status && <span className={`text-[0.6rem] px-1 rounded ${statusBadgeClass(data.todo_status)}`}>{data.todo_status}</span>}
            <div className="flex flex-wrap gap-0.5">
              {skills.map((s) => <span key={s} className={`text-[0.6rem] ${topicBadgeClass(s)}`}>{s}</span>)}
            </div>
            {/* Mobile right-panel toggle */}
            <button onClick={() => setRightPanelOpen(true)} className="md:hidden ml-auto p-1.5 text-sol-base01 hover:text-sol-base1 bg-sol-base02 rounded cursor-pointer" title="Chats & context">
              <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2z"/></svg>
            </button>
          </div>
          {/* Center two-mode pane */}
          <div className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden relative">
            {/* FileViewer (notes), shown when chatHide */}
            <div className={`absolute inset-0 ${chatHide ? "" : "hidden"}`}>
              {openNotes.length === 0 ? (
                <div className="h-full flex items-center justify-center text-sol-base01 text-sm italic px-4 text-center">
                  Select a note from the Note panel to open it here.
                </div>
              ) : (
                <FileViewer
                  mode="public"
                  openFiles={openNotes}
                  activeFile={activeNote}
                  onSelectFile={(s) => setActiveNote(s)}
                  onCloseFile={closeNote}
                  onReorderFiles={setOpenNotes}
                  noteMeta={noteMeta}
                />
              )}
            </div>
            {/* Snapshot ChatView, shown when !chatHide */}
            <div className={`absolute inset-0 flex flex-col ${chatHide ? "hidden" : ""}`}>
              <div className="shrink-0 max-h-[45%] overflow-y-auto px-4 py-3 border-b border-sol-base02">
                {todoInfo && (
                  <TraceTodoDetail
                    todoInfo={todoInfo}
                    open={todoDetailOpen}
                    setOpen={setTodoDetailOpen}
                    historyOpen={historyOpen}
                    setHistoryOpen={setHistoryOpen}
                    onOpenNote={openNote}
                  />
                )}
                {data.chats.length > 0 ? (
                  <WaterfallChart chats={data.chats} onClickChat={(chatId) => { setSelectedChatId(chatId); setChatHide(false); }} />
                ) : (
                  <p className="text-sol-base01 italic text-xs mt-2">No chats found</p>
                )}
              </div>
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
