import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { useAuth } from "./hooks/useAuth";
import { API, authFetch } from "./api";
import Header from "./components/Header";
import ChatView from "./components/ChatView";
import ChatList from "./components/ChatList";
import FileTree from "./components/FileTree";
import FileViewer from "./components/FileViewer";
import ActivityBar, { SidebarPanel } from "./components/ActivityBar";
import FileSearchDialog from "./components/FileSearchDialog";
import TerminalView from "./components/TerminalView";
import TraceView from "./components/TraceView";
import GitPanel from "./components/GitPanel";

interface VmConfigItem {
  name: string;
  vm_name: string;
  work_dir: string;
}

export default function App() {
  const { traceId: urlTraceId } = useParams<{ traceId?: string }>();
  const auth = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile overlay
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(() => localStorage.getItem("desktopSidebarOpen") !== "false");
  const [vmList, setVmList] = useState<VmConfigItem[]>([]);
  const [selectedVM, setSelectedVM] = useState<string | null>(() => localStorage.getItem("selectedVM") || null);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = localStorage.getItem("sidebarWidth");
    return saved ? parseInt(saved, 10) : 384;
  });
  const resizingRef = useRef(false);
  const [openFiles, setOpenFiles] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("openFiles") || "[]"); } catch { return []; }
  });
  const [activeFile, setActiveFile] = useState<string | null>(() => localStorage.getItem("activeFile") || null);
  const [chatMaximize, setChatMaximize] = useState(() => { const v = localStorage.getItem("chatMaximize"); return v === null ? true : v === "true"; });
  const [chatHide, setChatHide] = useState(() => { const v = localStorage.getItem("chatHide"); return v === null ? false : v === "true"; });
  const [fileSearchOpen, setFileSearchOpen] = useState(false);
  const [selectedChatId, setSelectedChatId] = useState<string | null>(() => localStorage.getItem("selectedChatId") || null);
  const [chatListOpen, setChatListOpen] = useState(() => { const v = localStorage.getItem("chatListOpen"); return v === null ? false : v !== "false"; });
  const [bottomTab, setBottomTab] = useState<"chat" | "terminal" | "trace">(() => urlTraceId ? "trace" : ((localStorage.getItem("bottomTab") as "chat" | "terminal" | "trace") || "chat"));
  const [sidebarPanel, setSidebarPanel] = useState<SidebarPanel>(() => (localStorage.getItem("sidebarPanel") as SidebarPanel) || "files");
  const [diffFiles, setDiffFiles] = useState<Set<string>>(new Set());
  const [chatWorkDir, setChatWorkDir] = useState<string | null>(null);
  const [chatListRefreshKey, setChatListRefreshKey] = useState(0);
  const currentVmWorkDir = vmList.find(v => v.name === (selectedVM || "default"))?.work_dir;
  const effectiveWorkDir = (selectedChatId && chatWorkDir) ? chatWorkDir : currentVmWorkDir;
  const [chatListWidth, setChatListWidth] = useState(() => {
    const saved = localStorage.getItem("chatListWidth");
    return saved ? parseInt(saved, 10) : 220;
  });
  const chatListResizingRef = useRef(false);

  useEffect(() => { localStorage.setItem("openFiles", JSON.stringify(openFiles)); }, [openFiles]);
  useEffect(() => { if (activeFile) localStorage.setItem("activeFile", activeFile); else localStorage.removeItem("activeFile"); }, [activeFile]);

  const handleOpenFile = useCallback((path: string) => {
    const p = path.replace(/^\.\//, "");
    setOpenFiles((files) => files.includes(p) ? files : [...files, p]);
    setActiveFile(p);
    if (!chatHide) setChatMaximize(false);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, [chatHide]);

  const handleOpenDiffFile = useCallback((path: string) => {
    const diffPath = `diff:${path}`;
    setDiffFiles((prev) => new Set(prev).add(diffPath));
    handleOpenFile(diffPath);
  }, [handleOpenFile]);

  const handleCloseFile = useCallback((path: string) => {
    setOpenFiles((files) => {
      const idx = files.indexOf(path);
      const next = files.filter((f) => f !== path);
      setActiveFile((cur) => {
        if (cur !== path) return cur;
        if (next.length === 0) return null;
        return next[Math.min(idx, next.length - 1)];
      });
      return next;
    });
    if (path.startsWith("diff:")) {
      setDiffFiles((prev) => { const next = new Set(prev); next.delete(path); return next; });
    }
  }, []);

  useEffect(() => { localStorage.setItem("chatMaximize", String(chatMaximize)); }, [chatMaximize]);
  useEffect(() => { localStorage.setItem("chatHide", String(chatHide)); }, [chatHide]);
  useEffect(() => { if (selectedChatId) localStorage.setItem("selectedChatId", selectedChatId); else localStorage.removeItem("selectedChatId"); }, [selectedChatId]);
  useEffect(() => { localStorage.setItem("chatListOpen", String(chatListOpen)); }, [chatListOpen]);
  useEffect(() => { localStorage.setItem("chatListWidth", String(chatListWidth)); }, [chatListWidth]);
  useEffect(() => { localStorage.setItem("desktopSidebarOpen", String(desktopSidebarOpen)); }, [desktopSidebarOpen]);
  useEffect(() => { localStorage.setItem("bottomTab", bottomTab); }, [bottomTab]);
  useEffect(() => { localStorage.setItem("sidebarPanel", sidebarPanel); }, [sidebarPanel]);
  useEffect(() => { if (selectedVM) localStorage.setItem("selectedVM", selectedVM); else localStorage.removeItem("selectedVM"); }, [selectedVM]);
  useEffect(() => {
    if (!auth.isLoggedIn) { setVmList([]); return; }
    authFetch(`${API}/api/vm-config/list`).then(r => r.json()).then(data => setVmList(data || [])).catch(() => setVmList([]));
  }, [auth.isLoggedIn]);

  const activeFileRef = useRef(activeFile);
  activeFileRef.current = activeFile;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "`") {
        e.preventDefault();
        setChatHide((v) => !v);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "p") {
        e.preventDefault();
        setFileSearchOpen(true);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "w") {
        const el = document.activeElement;
        if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) return;
        e.preventDefault();
        if (activeFileRef.current) handleCloseFile(activeFileRef.current);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleCloseFile]);

  useEffect(() => {
    localStorage.setItem("sidebarWidth", String(sidebarWidth));
  }, [sidebarWidth]);

  const handleResizeStart = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    resizingRef.current = true;
    const startX = e.clientX;
    const startWidth = sidebarWidth;

    const onMove = (ev: PointerEvent) => {
      const newWidth = Math.max(200, Math.min(600, startWidth + ev.clientX - startX));
      setSidebarWidth(newWidth);
    };
    const onUp = () => {
      resizingRef.current = false;
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [sidebarWidth]);

  const handleChatListResizeStart = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    chatListResizingRef.current = true;
    const startX = e.clientX;
    const startWidth = chatListWidth;
    const onMove = (ev: PointerEvent) => {
      const newWidth = Math.max(150, Math.min(400, startWidth - (ev.clientX - startX)));
      setChatListWidth(newWidth);
    };
    const onUp = () => {
      chatListResizingRef.current = false;
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [chatListWidth]);

  const handleChatCreated = useCallback((chatId: string) => {
    setSelectedChatId(chatId);
  }, []);

  const handleLogout = useCallback(() => {
    auth.logout();
  }, [auth]);

  return (
    <div className="h-dvh flex flex-col overflow-hidden">
      <Header key={String(auth.isLoggedIn)} email={auth.email} isLoggedIn={auth.isLoggedIn} gsiReady={auth.gsiReady} onLogout={handleLogout} onClickLogo={() => setSelectedChatId(null)} onToggleChatList={() => setChatListOpen((v) => !v)} chatListOpen={chatListOpen} onOpenFileSearch={() => setFileSearchOpen(true)} vmList={vmList} selectedVM={selectedVM} onSelectVM={(name) => { setSelectedVM(name); setSelectedChatId(null); }} onToggleSidebar={() => setSidebarOpen((v) => !v)} />
      <div className="flex flex-1 min-h-0">
        {/* Left: Activity Bar */}
        <ActivityBar
          isLoggedIn={auth.isLoggedIn}
          vmList={vmList}
          selectedVM={selectedVM}
          onSelectVM={(name) => { setSelectedVM(name); setSelectedChatId(null); }}
          sidebarOpen={window.innerWidth < 768 ? sidebarOpen : desktopSidebarOpen}
          onToggleSidebar={() => {
            const isMobile = window.innerWidth < 768;
            if (isMobile) setSidebarOpen((v) => !v);
            else setDesktopSidebarOpen((v) => !v);
          }}
          activePanel={sidebarPanel}
          onSelectPanel={setSidebarPanel}
          onOpenFile={handleOpenFile}
          activeFile={activeFile}
        />
        {/* Mobile overlay backdrop */}
        {sidebarOpen && (
          <div className="fixed inset-0 bg-black/40 z-20 md:hidden" onClick={() => setSidebarOpen(false)} />
        )}
        {/* Left: FileTree */}
        <div
          className={`
            fixed inset-y-0 left-0 z-30 transform transition-transform duration-200 md:relative md:z-auto shrink-0 border-r border-sol-base02 bg-sol-base03 overflow-hidden max-w-[280px] md:max-w-none
            ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
            ${desktopSidebarOpen ? "md:translate-x-0" : "md:-translate-x-full md:hidden"}
          `}
          style={{ width: sidebarWidth }}
        >
          {sidebarPanel === "files" ? (
            <FileTree isLoggedIn={auth.isLoggedIn} onSelectFile={handleOpenFile} vmName={selectedVM} workDir={effectiveWorkDir} />
          ) : (
            <GitPanel isLoggedIn={auth.isLoggedIn} vmName={selectedVM} workDir={effectiveWorkDir} onSelectFile={handleOpenDiffFile} />
          )}
          <div
            className="hidden md:block absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-sol-blue/40 active:bg-sol-blue/60 z-10"
            onPointerDown={handleResizeStart}
          />
        </div>
        {/* Right */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          {/* Right top: FileViewer (kept mounted, hidden via CSS to preserve scroll state) */}
          <div className={`${chatMaximize && !chatHide ? "hidden" : chatHide ? "flex-1" : "h-2/5"} min-h-0 overflow-hidden`}>
            <FileViewer openFiles={openFiles} activeFile={activeFile} onSelectFile={setActiveFile} onCloseFile={handleCloseFile} onReorderFiles={setOpenFiles} vmName={selectedVM} workDir={effectiveWorkDir} diffFiles={diffFiles} />
          </div>
          {/* Toolbar (always visible) */}
          <div className="flex items-center justify-end gap-1.5 sm:gap-1 px-3 py-1 sm:py-0.5 border-t border-sol-base02 bg-sol-base03 shrink-0">
            {!chatHide && <span className="font-mono text-sm sm:text-xs truncate mr-auto flex items-center gap-1 p-2 sm:p-1 text-sol-base01" title={effectiveWorkDir || ""}><svg className="w-5 h-5 sm:w-3.5 sm:h-3.5 shrink-0" viewBox="0 0 16 16" fill="currentColor"><path d="M1 3.5A1.5 1.5 0 0 1 2.5 2h3.879a1.5 1.5 0 0 1 1.06.44l1.122 1.12A1.5 1.5 0 0 0 9.62 4H13.5A1.5 1.5 0 0 1 15 5.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 12.5v-9z"/></svg><span className="hidden sm:inline truncate">{effectiveWorkDir}</span></span>}
            {!chatHide && (
              <>
                {/* Tab switcher */}
                <button
                  onClick={() => setBottomTab("chat")}
                  className={`p-2 sm:p-1 rounded cursor-pointer ${bottomTab === "chat" ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1"}`}
                  title="Chat"
                >
                  <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z"/>
                  </svg>
                </button>
                <button
                  onClick={() => setBottomTab("terminal")}
                  className={`p-2 sm:p-1 rounded cursor-pointer ${bottomTab === "terminal" ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1"}`}
                  title="Terminal"
                >
                  <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <polyline points="2,4 6,7 2,10" />
                    <line x1="7" y1="11" x2="12" y2="11" />
                  </svg>
                </button>
                <button
                  onClick={() => setBottomTab("trace")}
                  className={`p-2 sm:p-1 rounded cursor-pointer ${bottomTab === "trace" ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1"}`}
                  title="Traces"
                >
                  <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <circle cx="3" cy="3" r="1.5" />
                    <circle cx="11" cy="7" r="1.5" />
                    <circle cx="3" cy="11" r="1.5" />
                    <line x1="4.5" y1="3.5" x2="9.5" y2="6.5" />
                    <line x1="9.5" y1="7.5" x2="4.5" y2="10.5" />
                  </svg>
                </button>
                <div className="w-px h-4 bg-sol-base02 mx-0.5" />
                <button
                  onClick={() => { setSelectedChatId(null); }}
                  className="p-2 sm:p-1 text-sol-base01 hover:text-sol-base1 bg-sol-base02 rounded cursor-pointer"
                  title="New chat"
                >
                  <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <line x1="7" y1="2" x2="7" y2="12" />
                    <line x1="2" y1="7" x2="12" y2="7" />
                  </svg>
                </button>
<button
                  onClick={() => setChatMaximize((v) => !v)}
                  className="p-2 sm:p-1 text-sol-base01 hover:text-sol-base1 bg-sol-base02 rounded cursor-pointer"
                  title={chatMaximize ? "Restore chat" : "Maximize chat"}
                >
                  {chatMaximize ? (
                    <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <polyline points="1,5 5,5 5,1" />
                      <polyline points="13,5 9,5 9,1" />
                      <polyline points="1,9 5,9 5,13" />
                      <polyline points="13,9 9,9 9,13" />
                    </svg>
                  ) : (
                    <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <polyline points="5,1 1,1 1,5" />
                      <polyline points="9,1 13,1 13,5" />
                      <polyline points="1,9 1,13 5,13" />
                      <polyline points="13,9 13,13 9,13" />
                    </svg>
                  )}
                </button>
              </>
            )}
            <button
              onClick={() => setChatHide((v) => !v)}
              className="p-2 sm:p-1 text-sol-base01 hover:text-sol-base1 bg-sol-base02 rounded cursor-pointer"
              title={chatHide ? "Open terminal (Ctrl+`)" : "Close terminal (Ctrl+`)"}
            >
              {chatHide ? (
                <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <polyline points="2,4 6,7 2,10" />
                  <line x1="7" y1="11" x2="12" y2="11" />
                </svg>
              ) : (
                <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <line x1="3" y1="3" x2="11" y2="11" />
                  <line x1="11" y1="3" x2="3" y2="11" />
                </svg>
              )}
            </button>
          </div>
          {/* Right bottom: ChatView / TerminalView + ChatList */}
          <div className={`flex flex-col min-h-0 ${chatMaximize ? "flex-1" : "h-3/5"} ${chatHide ? "hidden" : ""}`}>
            <div className="flex flex-1 min-h-0 relative">
              <div className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden relative">
                {/* Chat (kept mounted, toggled via CSS) */}
                <div className={`absolute inset-0 flex flex-col ${bottomTab === "chat" ? "" : "invisible pointer-events-none"}`}>
                  <ChatView isLoggedIn={auth.isLoggedIn} gsiReady={auth.gsiReady} chatId={selectedChatId} onChatCreated={handleChatCreated} onClear={() => setSelectedChatId(null)} vmName={selectedVM} onWorkDirChange={setChatWorkDir} onComplete={() => setChatListRefreshKey((k) => k + 1)} onOpenFile={handleOpenFile} />
                </div>
                {/* Terminal (kept mounted, toggled via CSS) */}
                <div className={`absolute inset-0 flex flex-col ${bottomTab === "terminal" ? "" : "invisible pointer-events-none"}`}>
                  <TerminalView isLoggedIn={auth.isLoggedIn} vmName={selectedVM} workDir={effectiveWorkDir} />
                </div>
                {/* Trace (kept mounted, toggled via CSS) */}
                <div className={`absolute inset-0 flex flex-col ${bottomTab === "trace" ? "" : "invisible pointer-events-none"}`}>
                  <TraceView isLoggedIn={auth.isLoggedIn} initialTraceId={urlTraceId} />
                </div>
              </div>
              {/* Desktop: chat list panel (hidden with chat) */}
              {!chatHide && bottomTab === "chat" && (
                <div
                  className={`
                    hidden md:block
                    shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden relative
                  `}
                  style={{ width: chatListWidth }}
                >
                  <div
                    className="absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-sol-blue/40 active:bg-sol-blue/60 z-10"
                    onPointerDown={handleChatListResizeStart}
                  />
                  <ChatList isLoggedIn={auth.isLoggedIn} selectedChatId={selectedChatId} onSelectChat={(id) => { setSelectedChatId(id); setChatListOpen(false); }} refreshKey={chatListRefreshKey} />
                </div>
              )}
            </div>
          </div>
          {/* Mobile: chat list drawer (visible even when chat is hidden) */}
          {chatListOpen && (
            <div className="fixed inset-0 bg-black/40 z-20 md:hidden" onClick={() => setChatListOpen(false)} />
          )}
          <div
            className={`
              fixed inset-y-0 right-0 z-30 transform transition-transform duration-200
              md:hidden
              shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden
              ${chatListOpen ? "translate-x-0" : "translate-x-full"}
            `}
            style={{ width: chatListWidth }}
          >
            <ChatList isLoggedIn={auth.isLoggedIn} selectedChatId={selectedChatId} onSelectChat={(id) => { setSelectedChatId(id); setChatListOpen(false); }} />
          </div>
        </div>
      </div>
      <FileSearchDialog open={fileSearchOpen} onClose={() => setFileSearchOpen(false)} onSelectFile={handleOpenFile} vmName={selectedVM} workDir={effectiveWorkDir} openFiles={openFiles} />
    </div>
  );
}
