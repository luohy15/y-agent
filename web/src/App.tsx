import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router";
import { useAuth } from "./hooks/useAuth";
import { API, authFetch } from "./api";
import ChatView from "./components/ChatView";
import ChatList from "./components/ChatList";
import FileTree from "./components/FileTree";
import FileViewer from "./components/FileViewer";
import ActivityBar, { SidebarPanel } from "./components/ActivityBar";
import FileSearchDialog from "./components/FileSearchDialog";
import CommandPalette, { CommandAction } from "./components/CommandPalette";
import TerminalView from "./components/TerminalView";
import TodoList from "./components/TodoList";
import LinkList from "./components/LinkList";
import GitPanel from "./components/GitPanel";
import { TRACE_BADGE, CHAT_BADGE, skillBadgeClass } from "./components/badges";

interface VmConfigItem {
  name: string;
  vm_name: string;
  work_dir: string;
}

interface BotConfigItem {
  name: string;
  api_type: string | null;
  model: string;
}

type RightPanel = "files" | "git" | "chats" | "links";

export default function App() {
  const { traceId: urlTraceId } = useParams<{ traceId?: string }>();
  const auth = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile overlay
  const [activityBarOpen, setActivityBarOpen] = useState(false); // mobile activity bar drawer
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(() => localStorage.getItem("desktopSidebarOpen") !== "false");
  const [vmList, setVmList] = useState<VmConfigItem[]>([]);
  const [selectedVM, setSelectedVM] = useState<string | null>(() => localStorage.getItem("selectedVM") || null);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = localStorage.getItem("sidebarWidth");
    return saved ? parseInt(saved, 10) : 280;
  });
  const resizingRef = useRef(false);
  const [openFiles, setOpenFiles] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("openFiles") || "[]"); } catch { return []; }
  });
  const [activeFile, setActiveFile] = useState<string | null>(() => localStorage.getItem("activeFile") || null);
  const [chatHide, setChatHide] = useState(() => { const v = localStorage.getItem("chatHide"); return v === null ? false : v === "true"; });
  const [fileSearchOpen, setFileSearchOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [selectedChatId, setSelectedChatId] = useState<string | null>(() => localStorage.getItem("selectedChatId") || null);
  const [chatListOpen, setChatListOpen] = useState(() => { const v = localStorage.getItem("chatListOpen"); return v === null ? false : v !== "false"; });
  const [sidebarPanel, setSidebarPanel] = useState<SidebarPanel>(() => {
    const saved = localStorage.getItem("sidebarPanel") as SidebarPanel;
    return saved === "todo" || saved === "chats" || saved === "links" ? saved : "todo";
  });
  const [diffFiles, setDiffFiles] = useState<Set<string>>(new Set());
  const [chatWorkDir, setChatWorkDir] = useState<string | null>(null);
  const [chatSkill, setChatSkill] = useState<string | null>(null);
  const [chatTraceId, setChatTraceId] = useState<string | null>(null);
  const [chatBackend, setChatBackend] = useState<string | null>(null);
  const [selectedLinkId, setSelectedLinkId] = useState<string | null>(null);
  const [selectedLinkContentKey, setSelectedLinkContentKey] = useState<string | null>(null);
  const [chatListRefreshKey, setChatListRefreshKey] = useState(0);
  const [chatRefreshKey, setChatRefreshKey] = useState(0);
  const [chatListSpinning, setChatListSpinning] = useState(false);
  const [chatSpinning, setChatSpinning] = useState(false);
  const currentVmWorkDir = vmList.find(v => v.name === (selectedVM || "default"))?.work_dir;
  const effectiveWorkDir = (selectedChatId && chatWorkDir) ? chatWorkDir : currentVmWorkDir;
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(urlTraceId || localStorage.getItem("selectedTraceId") || null);
  const [chatListTraceId, setChatListTraceId] = useState<string | null>(localStorage.getItem("chatListTraceId") || null);
  const [bottomPanelCollapsed, setBottomPanelCollapsed] = useState(() => localStorage.getItem("bottomPanelCollapsed") === "true");
  const [bottomPanelHeight, setBottomPanelHeight] = useState(() => {
    const saved = localStorage.getItem("bottomPanelHeight");
    return saved ? parseInt(saved, 10) : 200;
  });
  const bottomPanelResizingRef = useRef(false);
  const [rightPanelWidth, setRightPanelWidth] = useState(() => {
    const saved = localStorage.getItem("chatListWidth");
    return saved ? parseInt(saved, 10) : 220;
  });
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(() => localStorage.getItem("chatListCollapsed") === "true");
  const [rightPanel, setRightPanel] = useState<RightPanel>(() => {
    const saved = localStorage.getItem("rightPanel") as RightPanel;
    return saved === "files" || saved === "git" || saved === "chats" || saved === "links" ? saved : "chats";
  });
  const rightPanelResizingRef = useRef(false);
  const [vmDropdownOpen, setVmDropdownOpen] = useState(false);
  const vmDropdownRef = useRef<HTMLDivElement>(null);
  const [botList, setBotList] = useState<BotConfigItem[]>([]);
  const [selectedBot, setSelectedBot] = useState<string | null>(() => localStorage.getItem("selectedBot") || null);
  const [botDropdownOpen, setBotDropdownOpen] = useState(false);
  const botDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => { localStorage.setItem("openFiles", JSON.stringify(openFiles)); }, [openFiles]);
  useEffect(() => { if (activeFile) localStorage.setItem("activeFile", activeFile); else localStorage.removeItem("activeFile"); }, [activeFile]);

  const handleOpenFile = useCallback((path: string) => {
    const p = path.replace(/^\.\//, "");
    setOpenFiles((files) => files.includes(p) ? files : [...files, p]);
    setActiveFile(p);
    setChatHide(true);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, []);

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

  useEffect(() => { localStorage.setItem("chatHide", String(chatHide)); }, [chatHide]);
  useEffect(() => { if (selectedChatId) localStorage.setItem("selectedChatId", selectedChatId); else localStorage.removeItem("selectedChatId"); }, [selectedChatId]);
  useEffect(() => { if (selectedTraceId) localStorage.setItem("selectedTraceId", selectedTraceId); else localStorage.removeItem("selectedTraceId"); }, [selectedTraceId]);
  useEffect(() => { if (chatListTraceId) localStorage.setItem("chatListTraceId", chatListTraceId); else localStorage.removeItem("chatListTraceId"); }, [chatListTraceId]);
  useEffect(() => { localStorage.setItem("chatListOpen", String(chatListOpen)); }, [chatListOpen]);
  useEffect(() => { localStorage.setItem("chatListWidth", String(rightPanelWidth)); }, [rightPanelWidth]);
  useEffect(() => { localStorage.setItem("chatListCollapsed", String(rightPanelCollapsed)); }, [rightPanelCollapsed]);
  useEffect(() => { localStorage.setItem("bottomPanelCollapsed", String(bottomPanelCollapsed)); }, [bottomPanelCollapsed]);
  useEffect(() => { localStorage.setItem("bottomPanelHeight", String(bottomPanelHeight)); }, [bottomPanelHeight]);
  useEffect(() => { localStorage.setItem("desktopSidebarOpen", String(desktopSidebarOpen)); }, [desktopSidebarOpen]);
  useEffect(() => { localStorage.setItem("sidebarPanel", sidebarPanel); }, [sidebarPanel]);
  useEffect(() => { localStorage.setItem("rightPanel", rightPanel); }, [rightPanel]);
  useEffect(() => { if (selectedVM) localStorage.setItem("selectedVM", selectedVM); else localStorage.removeItem("selectedVM"); }, [selectedVM]);
  useEffect(() => { if (selectedBot) localStorage.setItem("selectedBot", selectedBot); else localStorage.removeItem("selectedBot"); }, [selectedBot]);
  useEffect(() => {
    if (!vmDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (vmDropdownRef.current && !vmDropdownRef.current.contains(e.target as Node)) setVmDropdownOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [vmDropdownOpen]);
  useEffect(() => {
    if (!botDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (botDropdownRef.current && !botDropdownRef.current.contains(e.target as Node)) setBotDropdownOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [botDropdownOpen]);
  useEffect(() => {
    if (!auth.isLoggedIn) { setVmList([]); setBotList([]); return; }
    authFetch(`${API}/api/vm-config/list`).then(r => r.json()).then(data => setVmList(data || [])).catch(() => setVmList([]));
    authFetch(`${API}/api/bot/list`).then(r => r.json()).then(data => setBotList(data || [])).catch(() => setBotList([]));
  }, [auth.isLoggedIn]);

  // URL /trace/:traceId → open trace as file
  useEffect(() => {
    if (urlTraceId) {
      setSelectedTraceId(urlTraceId);
      handleOpenFile("trace.md");
      setSidebarPanel("todo");
    }
  }, [urlTraceId, handleOpenFile]);

  const activeFileRef = useRef(activeFile);
  activeFileRef.current = activeFile;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "`") {
        e.preventDefault();
        setChatHide((v) => !v);
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "p") {
        e.preventDefault();
        setCommandPaletteOpen(true);
        return;
      }
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key === "p") {
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

  const handleRightPanelResizeStart = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    rightPanelResizingRef.current = true;
    const startX = e.clientX;
    const startWidth = rightPanelWidth;
    const onMove = (ev: PointerEvent) => {
      const newWidth = Math.max(150, Math.min(400, startWidth - (ev.clientX - startX)));
      setRightPanelWidth(newWidth);
    };
    const onUp = () => {
      rightPanelResizingRef.current = false;
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [rightPanelWidth]);

  const handleBottomPanelResizeStart = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    bottomPanelResizingRef.current = true;
    const startY = e.clientY;
    const startHeight = bottomPanelHeight;
    const onMove = (ev: PointerEvent) => {
      const newHeight = Math.max(100, Math.min(500, startHeight - (ev.clientY - startY)));
      setBottomPanelHeight(newHeight);
    };
    const onUp = () => {
      bottomPanelResizingRef.current = false;
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
  }, [bottomPanelHeight]);

  const handleChatCreated = useCallback((chatId: string) => {
    setSelectedChatId(chatId);
  }, []);

  const handleLogout = useCallback(() => {
    auth.logout();
  }, [auth]);

  const commandActions: CommandAction[] = useMemo(() => [
    {
      id: 'close-all-editors',
      label: 'Close All Editors',
      execute: () => { setOpenFiles([]); setActiveFile(null); },
    },
  ], []);

  const rightPanelBtnClass = (active: boolean) =>
    `p-1.5 sm:p-1 rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1"}`;

  return (
    <div className="h-dvh flex flex-col overflow-hidden">
      {/* Mobile-only nav bar */}
      {auth.isLoggedIn && (
        <div className="md:hidden flex items-center gap-1 px-2 py-1.5 border-b border-sol-base02 bg-sol-base03 shrink-0">
          <button
            onClick={() => setActivityBarOpen((v) => !v)}
            className={`h-8 flex items-center gap-1.5 px-2 text-sm cursor-pointer rounded hover:bg-sol-base02 ${activityBarOpen ? "text-sol-blue" : "text-sol-base01 hover:text-sol-base1"}`}
            title="Menu"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <button
            onClick={() => setFileSearchOpen(true)}
            className="h-8 flex items-center gap-1.5 px-2 text-sm cursor-pointer rounded hover:bg-sol-base02 text-sol-base01 hover:text-sol-base1"
            title="Search files (Ctrl+P)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </button>
          <button
            onClick={() => setChatListOpen((v) => !v)}
            className={`h-8 flex items-center gap-1.5 px-2 text-sm cursor-pointer rounded hover:bg-sol-base02 ${chatListOpen ? "text-sol-blue" : "text-sol-base01 hover:text-sol-base1"}`}
            title={chatListOpen ? "Hide chat list" : "Show chat list"}
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </button>
        </div>
      )}
      {/* Desktop-only header bar */}
      {auth.isLoggedIn && (
        <div className="hidden md:flex items-center px-2 py-1 bg-sol-base03 border-b border-sol-base02 shrink-0">
          {/* Center: trace ID, VM, workdir */}
          <div className="flex-1 flex justify-center items-center gap-2 text-sol-base01 font-mono text-xs">
            {chatListTraceId && (
              <button
                onClick={() => { setSelectedTraceId(chatListTraceId); handleOpenFile("trace.md"); }}
                className="text-sol-base01 hover:text-sol-base1 text-xs font-mono cursor-pointer"
              >
                #{chatListTraceId.slice(0, 8)}
              </button>
            )}
            <div className="relative shrink-0" ref={vmDropdownRef}>
              <button
                onClick={() => { if (!selectedChatId) setVmDropdownOpen((v) => !v); }}
                className={`p-0 bg-transparent border-0 ${selectedChatId ? "cursor-default" : vmDropdownOpen ? "text-sol-blue cursor-pointer" : "hover:text-sol-base0 cursor-pointer"}`}
                title={`VM: ${selectedVM || "default"}`}
              >
                {selectedVM || "default"}
              </button>
              {vmDropdownOpen && (
                <div className="absolute left-0 top-full mt-1 z-50 bg-sol-base02 border border-sol-base01 rounded shadow-lg py-1 min-w-[140px]">
                  <button
                    onClick={() => { setSelectedVM(null); setSelectedChatId(null); setChatSkill(null); setChatBackend(null); setChatTraceId(null); setVmDropdownOpen(false); }}
                    className={`w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 ${!selectedVM ? "text-sol-blue font-semibold" : "text-sol-base1"}`}
                  >
                    default
                  </button>
                  {vmList.filter((vm) => vm.name !== "default").map((vm) => (
                    <button
                      key={vm.name}
                      onClick={() => { setSelectedVM(vm.name); setSelectedChatId(null); setChatSkill(null); setChatBackend(null); setChatTraceId(null); setVmDropdownOpen(false); }}
                      className={`w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 ${selectedVM === vm.name ? "text-sol-blue font-semibold" : "text-sol-base1"}`}
                    >
                      {vm.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {botList.length > 1 && (
              <div className="relative shrink-0" ref={botDropdownRef}>
                <button
                  onClick={() => { if (!selectedChatId) setBotDropdownOpen((v) => !v); }}
                  className={`p-0 bg-transparent border-0 ${selectedChatId ? "cursor-default" : botDropdownOpen ? "text-sol-blue cursor-pointer" : "hover:text-sol-base0 cursor-pointer"}`}
                  title={`Bot: ${selectedBot || "default"}`}
                >
                  {selectedBot || "default"}
                </button>
                {botDropdownOpen && (
                  <div className="absolute left-0 top-full mt-1 z-50 bg-sol-base02 border border-sol-base01 rounded shadow-lg py-1 min-w-[140px]">
                    <button
                      onClick={() => { setSelectedBot(null); setBotDropdownOpen(false); }}
                      className={`w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 ${!selectedBot ? "text-sol-blue font-semibold" : "text-sol-base1"}`}
                    >
                      default
                    </button>
                    {botList.filter((b) => b.name !== "default").map((b) => (
                      <button
                        key={b.name}
                        onClick={() => { setSelectedBot(b.name); setBotDropdownOpen(false); }}
                        className={`w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 ${selectedBot === b.name ? "text-sol-blue font-semibold" : "text-sol-base1"}`}
                      >
                        {b.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            <span>{effectiveWorkDir}</span>
          </div>
          {/* Right: panel toggle buttons */}
          <div className="flex items-center gap-1 shrink-0">
            {/* Left sidebar toggle */}
            <button
              onClick={() => setDesktopSidebarOpen(v => !v)}
              className={`p-1 rounded cursor-pointer ${desktopSidebarOpen ? "text-sol-base1" : "text-sol-base01 hover:text-sol-base1"}`}
              title={desktopSidebarOpen ? "Hide left sidebar" : "Show left sidebar"}
            >
              <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1">
                <rect x="1" y="1" width="14" height="14" rx="1" />
                <line x1="5" y1="1" x2="5" y2="15" />
                {desktopSidebarOpen && <rect x="1" y="1" width="4" height="14" rx="1" fill="currentColor" stroke="none" />}
              </svg>
            </button>
            {/* Bottom panel toggle */}
            <button
              onClick={() => setBottomPanelCollapsed(v => !v)}
              className={`p-1 rounded cursor-pointer ${!bottomPanelCollapsed ? "text-sol-base1" : "text-sol-base01 hover:text-sol-base1"}`}
              title={bottomPanelCollapsed ? "Show bottom panel" : "Hide bottom panel"}
            >
              <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1">
                <rect x="1" y="1" width="14" height="14" rx="1" />
                <line x1="1" y1="11" x2="15" y2="11" />
                {!bottomPanelCollapsed && <rect x="1" y="11" width="14" height="4" rx="1" fill="currentColor" stroke="none" />}
              </svg>
            </button>
            {/* Right panel toggle */}
            <button
              onClick={() => setRightPanelCollapsed(v => !v)}
              className={`p-1 rounded cursor-pointer ${!rightPanelCollapsed ? "text-sol-base1" : "text-sol-base01 hover:text-sol-base1"}`}
              title={rightPanelCollapsed ? "Show right panel" : "Hide right panel"}
            >
              <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1">
                <rect x="1" y="1" width="14" height="14" rx="1" />
                <line x1="11" y1="1" x2="11" y2="15" />
                {!rightPanelCollapsed && <rect x="11" y="1" width="4" height="14" rx="1" fill="currentColor" stroke="none" />}
              </svg>
            </button>
          </div>
        </div>
      )}
      <div className="flex flex-1 min-h-0">
        {/* Left: Activity Bar */}
        <ActivityBar
          isLoggedIn={auth.isLoggedIn}
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
          chatHide={chatHide}
          onToggleChatHide={() => setChatHide((v) => !v)}
          email={auth.email}
          gsiReady={auth.gsiReady}
          onLogout={handleLogout}
        />
        {/* Mobile overlay backdrop (sidebar or activity bar) */}
        {(sidebarOpen || activityBarOpen) && (
          <div className="fixed inset-0 bg-black/40 z-20 md:hidden" onClick={() => { setSidebarOpen(false); setActivityBarOpen(false); }} />
        )}
        {/* Mobile: Activity Bar drawer */}
        <div
          className={`
            fixed inset-y-0 left-0 z-30 transform transition-transform duration-200
            md:hidden
            shrink-0 border-r border-sol-base02 bg-sol-base03 overflow-y-auto
            ${activityBarOpen ? "translate-x-0" : "-translate-x-full"}
          `}
          style={{ width: 200 }}
        >
          <ActivityBar
            mobile
            isLoggedIn={auth.isLoggedIn}
            sidebarOpen={sidebarOpen}
            onToggleSidebar={() => { setActivityBarOpen(false); setSidebarOpen((v) => !v); }}
            activePanel={sidebarPanel}
            onSelectPanel={(panel) => { setSidebarPanel(panel); setActivityBarOpen(false); setSidebarOpen(true); }}
            onOpenFile={(path) => { handleOpenFile(path); setActivityBarOpen(false); }}
            activeFile={activeFile}
            chatHide={chatHide}
            onToggleChatHide={() => { setChatHide((v) => !v); setActivityBarOpen(false); }}
            email={auth.email}
            gsiReady={auth.gsiReady}
            onLogout={handleLogout}
          />
        </div>
        {/* Left: Sidebar (global views) */}
        <div
          className={`
            fixed inset-y-0 left-0 z-30 transform transition-transform duration-200 md:relative md:z-auto shrink-0 border-r border-sol-base02 bg-sol-base03 overflow-hidden max-w-[280px] md:max-w-none
            ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
            ${desktopSidebarOpen ? "md:translate-x-0" : "md:-translate-x-full md:hidden"}
          `}
          style={{ width: sidebarWidth }}
        >
          {sidebarPanel === "todo" ? (
            <TodoList isLoggedIn={auth.isLoggedIn} onSelectTodo={(todoId) => { setSelectedTraceId(todoId); setChatListTraceId(todoId); setSidebarOpen(false); authFetch(`${API}/api/trace/latest_chat?trace_id=${encodeURIComponent(todoId)}`).then(r => r.json()).then(d => { if (d.chat_id) { setSelectedChatId(d.chat_id); setChatHide(false);} }).catch(() => {}); }} onSelectTrace={(traceId) => { setSelectedTraceId(traceId); handleOpenFile("trace.md"); }} />
          ) : sidebarPanel === "chats" ? (
            <ChatList isLoggedIn={auth.isLoggedIn} selectedChatId={selectedChatId} onSelectChat={(id) => { setSelectedChatId(id); setChatListOpen(false); setChatHide(false);}} refreshKey={chatListRefreshKey} onSelectTrace={(traceId) => { setSelectedTraceId(traceId); handleOpenFile("trace.md"); }} />
          ) : (
            <LinkList isLoggedIn={auth.isLoggedIn} onPreview={(link) => { setSelectedLinkId(link.activity_id); setSelectedLinkContentKey(link.content_key || null); handleOpenFile("link.md"); }} />
          )}
          <div
            className="hidden sm:block absolute top-0 -right-2 w-4 lg:w-1 lg:right-0 h-full cursor-col-resize z-10 group"
            onPointerDown={handleResizeStart}
          >
            <div className="absolute top-0 right-2 lg:right-0 w-1 h-full hover:bg-sol-blue/40 active:bg-sol-blue/60" />
          </div>
        </div>
        {/* Center + Right */}
        <div className="flex-1 flex min-w-0 min-h-0">
          {/* Center column */}
          <div className="flex-1 flex flex-col min-w-0 min-h-0">
            {/* Center mode switcher header */}
            <div className="flex items-center gap-1 px-2 py-2 bg-sol-base03 shrink-0">
              <button
                onClick={() => setChatHide(true)}
                className={rightPanelBtnClass(chatHide)}
                title="Files (Ctrl+`)"
              >
                <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M4 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4.5L9.5 0H4zm5.5 0v3a1.5 1.5 0 0 0 1.5 1.5h3"/>
                </svg>
              </button>
              <button
                onClick={() => setChatHide(false)}
                className={rightPanelBtnClass(!chatHide)}
                title="Chat"
              >
                <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z"/>
                </svg>
              </button>
              <div className="w-px h-4 bg-sol-base02 mx-0.5" />
              <button
                onClick={() => { setSelectedChatId(null); setChatListTraceId(null); setChatSkill(null); setChatBackend(null); setChatTraceId(null); }}
                className="p-1.5 sm:p-1 text-sol-base01 hover:text-sol-base1 bg-sol-base02 rounded cursor-pointer"
                title="New chat"
              >
                <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <line x1="7" y1="2" x2="7" y2="12" />
                  <line x1="2" y1="7" x2="12" y2="7" />
                </svg>
              </button>
            </div>
            {/* Center top: FileViewer / ChatView */}
            <div className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden relative">
              {/* FileViewer (shown when chat hidden) */}
              <div className={`absolute inset-0 ${chatHide ? "" : "hidden"}`}>
                <FileViewer openFiles={openFiles} activeFile={activeFile} onSelectFile={setActiveFile} onCloseFile={handleCloseFile} onReorderFiles={setOpenFiles} vmName={selectedVM} workDir={effectiveWorkDir} diffFiles={diffFiles} isLoggedIn={auth.isLoggedIn} selectedTraceId={selectedTraceId} selectedLinkId={selectedLinkId} selectedLinkContentKey={selectedLinkContentKey} onSelectChat={(id) => { setSelectedChatId(id); setChatListOpen(false); setChatHide(false); }} onPreviewLink={(activityId) => { setSelectedLinkId(activityId); handleOpenFile("link.md"); }} />
              </div>
              {/* Chat (kept mounted, toggled via CSS) */}
              <div className={`absolute inset-0 flex flex-col ${chatHide ? "hidden" : ""}`}>
                {/* Chat header: VM, workdir, trace_id, chat_id, skill, refresh */}
                <div className="flex items-center gap-1 px-3 py-0.5 text-sol-base01 font-mono text-xs border-b border-sol-base02 bg-sol-base03 shrink-0">
                  {chatTraceId && <button onClick={() => { setSelectedTraceId(chatTraceId); handleOpenFile("trace.md"); }} className={`text-[0.65rem] cursor-pointer ${TRACE_BADGE}`} title="View todo">#{chatTraceId.slice(0, 8)}</button>}
                  {selectedChatId && <button onClick={() => navigator.clipboard.writeText(selectedChatId)} className={`gap-0.5 text-[0.65rem] cursor-pointer ${CHAT_BADGE}`} title="Copy chat ID"><svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>{selectedChatId.slice(0, 8)}</button>}
                  {chatSkill && <span className={`text-[0.65rem] ${skillBadgeClass(chatSkill)}`}>{chatSkill}</span>}
                  {chatBackend && <span className="inline-flex items-center px-1.5 py-0.5 rounded font-mono font-medium shrink-0 text-[0.65rem] bg-sol-base01/20 text-sol-base01">{chatBackend}</span>}
                  {selectedChatId && <button onClick={() => { setChatRefreshKey((k) => k + 1); setChatSpinning(true); setTimeout(() => setChatSpinning(false), 600); }} className="ml-auto inline-flex items-center hover:text-sol-blue cursor-pointer shrink-0" title="Refresh chat"><svg className={`w-3 h-3 ${chatSpinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg></button>}
                </div>
                <ChatView key={chatRefreshKey} isLoggedIn={auth.isLoggedIn} gsiReady={auth.gsiReady} chatId={selectedChatId} onChatCreated={handleChatCreated} onClear={() => { setSelectedChatId(null); setChatSkill(null); setChatBackend(null); setChatTraceId(null); }} vmName={selectedVM} botName={selectedBot} onWorkDirChange={setChatWorkDir} onSkillChange={setChatSkill} onTraceIdChange={(traceId) => { setChatTraceId(traceId); if (traceId) setChatListTraceId(traceId); }} onBackendChange={(b) => { setChatBackend(b); if (b) setSelectedBot(b); }} onComplete={() => setChatListRefreshKey((k) => k + 1)} onOpenFile={handleOpenFile} onSelectChat={(id) => { setSelectedChatId(id); setChatHide(false); setChatListOpen(true); }} onSelectTrace={(traceId) => { setSelectedTraceId(traceId); handleOpenFile("trace.md"); }} />
              </div>
            </div>
            {/* Bottom panel: Terminal (VS Code style) */}
            {!bottomPanelCollapsed && (
              <>
                {/* Resize handle */}
                <div
                  className="hidden md:block h-1 cursor-row-resize shrink-0 group relative"
                  onPointerDown={handleBottomPanelResizeStart}
                >
                  <div className="absolute inset-x-0 top-0 h-1 hover:bg-sol-blue/40 active:bg-sol-blue/60" />
                </div>
                <div
                  className="hidden md:flex shrink-0 border-t border-sol-base02 bg-sol-base03 overflow-hidden flex-col"
                  style={{ height: bottomPanelHeight }}
                >
                  <TerminalView isLoggedIn={auth.isLoggedIn} vmName={selectedVM} workDir={effectiveWorkDir} />
                </div>
              </>
            )}
          </div>
          {/* Right panel (scoped views, always visible independent of chatHide) */}
          {!rightPanelCollapsed && (
            <div
              className="hidden sm:flex shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden relative flex-col"
              style={{ width: rightPanelWidth }}
            >
              <div
                className="absolute top-0 -left-2 w-4 lg:w-1 lg:left-0 h-full cursor-col-resize z-10 group"
                onPointerDown={handleRightPanelResizeStart}
              >
                <div className="absolute top-0 left-2 lg:left-0 w-1 h-full hover:bg-sol-blue/40 active:bg-sol-blue/60" />
              </div>
              {/* Right panel tab header */}
              <div className="flex items-center gap-1 px-2 py-0.5 border-b border-sol-base02 shrink-0">
                <button onClick={() => setRightPanel("files")} className={rightPanelBtnClass(rightPanel === "files")} title="Files">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                </button>
                <button onClick={() => setRightPanel("git")} className={rightPanelBtnClass(rightPanel === "git")} title="Source Control">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M13 6h3a2 2 0 0 1 2 2v7" /><line x1="6" y1="9" x2="6" y2="21" /></svg>
                </button>
                <button onClick={() => setRightPanel("chats")} className={rightPanelBtnClass(rightPanel === "chats")} title="Filtered Chats">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z"/></svg>
                </button>
                <button onClick={() => setRightPanel("links")} className={rightPanelBtnClass(rightPanel === "links")} title="Filtered Links">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></svg>
                </button>
                <div className="ml-auto flex items-center gap-1">
                  <button
                    onClick={() => { setChatListRefreshKey((k) => k + 1); setChatListSpinning(true); setTimeout(() => setChatListSpinning(false), 600); }}
                    className="p-1 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer"
                    title="Refresh"
                  >
                    <svg className={`w-3.5 h-3.5 transition-transform ${chatListSpinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                  </button>
                  <button
                    onClick={() => setRightPanelCollapsed(true)}
                    className="p-1 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer"
                    title="Hide right panel"
                  >
                    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                  </button>
                </div>
              </div>
              {/* Right panel content */}
              <div className="flex-1 min-h-0 overflow-hidden">
                {rightPanel === "files" ? (
                  <FileTree isLoggedIn={auth.isLoggedIn} onSelectFile={handleOpenFile} vmName={selectedVM} workDir={effectiveWorkDir} />
                ) : rightPanel === "git" ? (
                  <GitPanel isLoggedIn={auth.isLoggedIn} vmName={selectedVM} workDir={effectiveWorkDir} onSelectFile={handleOpenDiffFile} />
                ) : rightPanel === "chats" ? (
                  <ChatList isLoggedIn={auth.isLoggedIn} selectedChatId={selectedChatId} onSelectChat={(id) => { setSelectedChatId(id); setChatListOpen(false); setChatHide(false);}} refreshKey={chatListRefreshKey} traceId={chatListTraceId} hideFilters onSelectTrace={(traceId) => { setSelectedTraceId(traceId); handleOpenFile("trace.md"); }} />
                ) : (
                  <LinkList isLoggedIn={auth.isLoggedIn} onPreview={(link) => { setSelectedLinkId(link.activity_id); setSelectedLinkContentKey(link.content_key || null); handleOpenFile("link.md"); }} todoId={chatListTraceId} hideFilters />
                )}
              </div>
            </div>
          )}
          {/* Mobile: chat/trace list drawer (visible even when chat is hidden) */}
          {chatListOpen && (
            <div className="fixed inset-0 bg-black/40 z-20 md:hidden" onClick={() => setChatListOpen(false)} />
          )}
          <div
            className={`
              fixed inset-y-0 right-0 z-30 transform transition-transform duration-200
              md:hidden
              shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden
              max-w-[280px]
              ${chatListOpen ? "translate-x-0" : "translate-x-full"}
            `}
            style={{ width: rightPanelWidth }}
          >
            <ChatList isLoggedIn={auth.isLoggedIn} selectedChatId={selectedChatId} onSelectChat={(id) => { setSelectedChatId(id); setChatListOpen(false); setChatHide(false);}} traceId={chatListTraceId} onClearTraceId={() => setChatListTraceId(null)} onSelectTrace={(traceId) => { setSelectedTraceId(traceId); handleOpenFile("trace.md"); }} />
          </div>
        </div>
      </div>
      <FileSearchDialog open={fileSearchOpen} onClose={() => setFileSearchOpen(false)} onSelectFile={handleOpenFile} vmName={selectedVM} workDir={effectiveWorkDir} openFiles={openFiles} />
      <CommandPalette open={commandPaletteOpen} onClose={() => setCommandPaletteOpen(false)} actions={commandActions} />
    </div>
  );
}
