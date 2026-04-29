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
import NoteList from "./components/NoteList";
import RssFeedList from "./components/RssFeedList";
import EntityList from "./components/EntityList";
import ReminderList from "./components/ReminderList";
import RoutineList from "./components/RoutineList";
import GitPanel from "./components/GitPanel";
import LinkActionDialog from "./components/LinkActionDialog";
import { TRACE_BADGE, CHAT_BADGE, topicBadgeClass } from "./components/badges";

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

type RightPanel = "notes" | "chats" | "links" | "files" | "git";

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
  const [previewFile, setPreviewFile] = useState<string | null>(() => localStorage.getItem("previewFile") || null);
  const [chatHide, setChatHide] = useState(() => { const v = localStorage.getItem("chatHide"); return v === null ? false : v === "true"; });
  const [fileSearchOpen, setFileSearchOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [selectedChatId, setSelectedChatId] = useState<string | null>(() => localStorage.getItem("selectedChatId") || null);
  const [chatListOpen, setChatListOpen] = useState(() => { const v = localStorage.getItem("chatListOpen"); return v === null ? false : v !== "false"; });
  const [sidebarPanel, setSidebarPanel] = useState<SidebarPanel>(() => {
    const saved = localStorage.getItem("sidebarPanel") as SidebarPanel;
    const valid: SidebarPanel[] = ["todo", "chats", "notes", "links", "rss", "entity", "files", "reminder", "routine", "calendar", "finance", "email", "dev"];
    return valid.includes(saved) ? saved : "todo";
  });
  const [diffFiles, setDiffFiles] = useState<Set<string>>(new Set());
  const [chatWorkDir, setChatWorkDir] = useState<string | null>(null);
  const [chatTopic, setChatTopic] = useState<string | null>(null);
  const [chatSkill, setChatSkill] = useState<string | null>(null);
  const [chatTraceId, setChatTraceId] = useState<string | null>(null);
  const [chatBackend, setChatBackend] = useState<string | null>(null);
  const [selectedLinkId, setSelectedLinkId] = useState<string | null>(() => localStorage.getItem("selectedLinkId") || null);
  const [selectedLinkLinkId, setSelectedLinkLinkId] = useState<string | null>(() => localStorage.getItem("selectedLinkLinkId") || null);
  const [selectedLinkContentKey, setSelectedLinkContentKey] = useState<string | null>(() => localStorage.getItem("selectedLinkContentKey") || null);
  const [pendingLinkUrl, setPendingLinkUrl] = useState<string | null>(null);
  const [pendingLinkStatus, setPendingLinkStatus] = useState<string | null>(null);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(() => localStorage.getItem("selectedEntityId") || null);
  const [selectedFeedId, setSelectedFeedId] = useState<string | null>(null);
  const [selectedFeedLabel, setSelectedFeedLabel] = useState<string | null>(null);
  const [chatListRefreshKey, setChatListRefreshKey] = useState(0);
  const [chatRefreshKey, setChatRefreshKey] = useState(0);
  const [chatListSpinning, setChatListSpinning] = useState(false);
  const [chatSpinning, setChatSpinning] = useState(false);
  const currentVmWorkDir = vmList.find(v => v.name === (selectedVM || "default"))?.work_dir;
  const defaultWorkDir = vmList.find(v => v.name === "default")?.work_dir;
  const effectiveWorkDir = (selectedChatId && chatWorkDir) ? chatWorkDir : currentVmWorkDir;
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(urlTraceId || localStorage.getItem("selectedTraceId") || null);
  const [chatListTraceId, setChatListTraceId] = useState<string | null>(localStorage.getItem("chatListTraceId") || null);
  const [chatListRoutineId, setChatListRoutineId] = useState<string | null>(localStorage.getItem("chatListRoutineId") || null);
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
    return saved === "chats" || saved === "notes" || saved === "links" || saved === "files" || saved === "git" ? saved : "chats";
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
  useEffect(() => { if (previewFile) localStorage.setItem("previewFile", previewFile); else localStorage.removeItem("previewFile"); }, [previewFile]);
  useEffect(() => { if (selectedLinkId) localStorage.setItem("selectedLinkId", selectedLinkId); else localStorage.removeItem("selectedLinkId"); }, [selectedLinkId]);
  useEffect(() => { if (selectedLinkLinkId) localStorage.setItem("selectedLinkLinkId", selectedLinkLinkId); else localStorage.removeItem("selectedLinkLinkId"); }, [selectedLinkLinkId]);
  useEffect(() => { if (selectedLinkContentKey) localStorage.setItem("selectedLinkContentKey", selectedLinkContentKey); else localStorage.removeItem("selectedLinkContentKey"); }, [selectedLinkContentKey]);
  useEffect(() => { if (selectedEntityId) localStorage.setItem("selectedEntityId", selectedEntityId); else localStorage.removeItem("selectedEntityId"); }, [selectedEntityId]);

  const handleOpenFile = useCallback((path: string) => {
    const p = path.replace(/^\.\//, "");
    setOpenFiles((files) => files.includes(p) ? files : [...files, p]);
    setActiveFile(p);
    // Pin preview if this file is the current preview (opened via non-preview action)
    setPreviewFile((current) => current === p ? null : current);
    setChatHide(true);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, []);

  const openFilesRef = useRef(openFiles);
  openFilesRef.current = openFiles;
  const previewFileRef = useRef(previewFile);
  previewFileRef.current = previewFile;

  const handlePreviewFile = useCallback((path: string) => {
    const p = path.replace(/^\.\//, "");
    const files = openFilesRef.current;
    const currentPreview = previewFileRef.current;
    const isAlreadyOpen = files.includes(p);

    if (isAlreadyOpen && currentPreview !== p) {
      // Already open as pinned — just activate
      setActiveFile(p);
      setChatHide(true);
      if (window.innerWidth < 768) setSidebarOpen(false);
      return;
    }

    if (currentPreview === p) {
      // Already the preview — just activate
      setActiveFile(p);
      setChatHide(true);
      if (window.innerWidth < 768) setSidebarOpen(false);
      return;
    }

    if (currentPreview && files.includes(currentPreview)) {
      // Replace existing preview tab in-place
      const idx = files.indexOf(currentPreview);
      const newFiles = [...files];
      newFiles[idx] = p;
      setOpenFiles(newFiles);
    } else if (!isAlreadyOpen) {
      // No preview exists — add new tab
      setOpenFiles((f) => f.includes(p) ? f : [...f, p]);
    }

    setPreviewFile(p);
    setActiveFile(p);
    setChatHide(true);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, []);

  const handlePinFile = useCallback((path: string) => {
    setPreviewFile((current) => current === path ? null : current);
  }, []);

  const handleOpenDiffFile = useCallback((path: string) => {
    const diffPath = `diff:${path}`;
    setDiffFiles((prev) => new Set(prev).add(diffPath));
    handlePreviewFile(diffPath);
  }, [handlePreviewFile]);

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
    setPreviewFile((current) => current === path ? null : current);
    if (path.startsWith("diff:")) {
      setDiffFiles((prev) => { const next = new Set(prev); next.delete(path); return next; });
    }
  }, []);

  useEffect(() => { localStorage.setItem("chatHide", String(chatHide)); }, [chatHide]);
  useEffect(() => { if (selectedChatId) localStorage.setItem("selectedChatId", selectedChatId); else localStorage.removeItem("selectedChatId"); }, [selectedChatId]);
  useEffect(() => { if (selectedTraceId) localStorage.setItem("selectedTraceId", selectedTraceId); else localStorage.removeItem("selectedTraceId"); }, [selectedTraceId]);
  useEffect(() => { if (chatListTraceId) localStorage.setItem("chatListTraceId", chatListTraceId); else localStorage.removeItem("chatListTraceId"); }, [chatListTraceId]);
  useEffect(() => { if (chatListRoutineId) localStorage.setItem("chatListRoutineId", chatListRoutineId); else localStorage.removeItem("chatListRoutineId"); }, [chatListRoutineId]);
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

  // URL ?entity_id=... → open entity.md
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const eid = params.get("entity_id");
    if (eid) {
      setSelectedEntityId(eid);
      handleOpenFile("entity.md");
    }
  }, [handleOpenFile]);

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
        if ((el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) && !el.dataset.editor) return;
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

  const handleSelectChat = useCallback((id: string | null) => {
    if (id && id === selectedChatId) setChatRefreshKey((k) => k + 1);
    setSelectedChatId(id);
    setChatListOpen(false);
    setChatHide(false);
  }, [selectedChatId]);

  const handleSelectFeed = useCallback((feedId: string, label: string) => {
    setSelectedFeedId(feedId);
    setSelectedFeedLabel(label);
    handleOpenFile("links.md");
  }, [handleOpenFile]);

  const handleClearFeed = useCallback(() => {
    setSelectedFeedId(null);
    setSelectedFeedLabel(null);
  }, []);

  const handleExternalLinkClick = useCallback(async (url: string) => {
    try {
      const res = await authFetch(`${API}/api/link/resolve?url=${encodeURIComponent(url)}`);
      if (!res.ok) {
        window.open(url, "_blank", "noopener,noreferrer");
        return;
      }
      const data = await res.json();
      if (data.download_status === "done" && data.content_key) {
        setSelectedLinkId(data.activity_id ?? null);
        setSelectedLinkLinkId(data.link_id ?? null);
        setSelectedLinkContentKey(data.content_key);
        handleOpenFile("link.md");
        return;
      }
      setPendingLinkUrl(url);
      setPendingLinkStatus(data.download_status ?? null);
    } catch {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  }, [handleOpenFile]);

  const handleLogout = useCallback(() => {
    auth.logout();
  }, [auth]);

  const commandActions: CommandAction[] = useMemo(() => [
    {
      id: 'close-all-editors',
      label: 'Close All Editors',
      execute: () => { setOpenFiles([]); setActiveFile(null); setPreviewFile(null); },
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
                    onClick={() => { setSelectedVM(null); setSelectedChatId(null); setChatTopic(null); setChatSkill(null); setChatBackend(null); setChatTraceId(null); setVmDropdownOpen(false); }}
                    className={`w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 ${!selectedVM ? "text-sol-blue font-semibold" : "text-sol-base1"}`}
                  >
                    default
                  </button>
                  {vmList.filter((vm) => vm.name !== "default").map((vm) => (
                    <button
                      key={vm.name}
                      onClick={() => { setSelectedVM(vm.name); setSelectedChatId(null); setChatTopic(null); setChatSkill(null); setChatBackend(null); setChatTraceId(null); setVmDropdownOpen(false); }}
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
          {(() => {
            const panelFileMap: Partial<Record<SidebarPanel, { path: string; label: string }>> = {
              todo: { path: "todo.md", label: "Open todo.md" },
              calendar: { path: "calendar.md", label: "Open calendar.md" },
              finance: { path: "finance.bean", label: "Open finance.bean" },
              email: { path: "emails.md", label: "Open emails.md" },
              dev: { path: "dev.md", label: "Open dev.md" },
            };
            const panelFile = panelFileMap[sidebarPanel];
            const body =
              sidebarPanel === "todo" ? (
                <TodoList isLoggedIn={auth.isLoggedIn} onSelectTodo={(todoId) => { setSelectedTraceId(todoId); setChatListTraceId(todoId); setSidebarOpen(false); authFetch(`${API}/api/trace/latest_chat?trace_id=${encodeURIComponent(todoId)}`).then(r => r.json()).then(d => { if (d.chat_id) { setSelectedChatId(d.chat_id); setChatHide(false);} }).catch(() => {}); }} onSelectTrace={(traceId) => { setSelectedTraceId(traceId); handleOpenFile("trace.md"); }} onChatListRefresh={() => setChatListRefreshKey((k) => k + 1)} />
              ) : sidebarPanel === "chats" ? (
                <ChatList isLoggedIn={auth.isLoggedIn} selectedChatId={selectedChatId} onSelectChat={handleSelectChat} refreshKey={chatListRefreshKey} routineId={chatListRoutineId} onClearRoutineId={() => setChatListRoutineId(null)} onSelectTrace={(traceId) => { setSelectedTraceId(traceId); handleOpenFile("trace.md"); }} />
              ) : sidebarPanel === "notes" ? (
                <NoteList isLoggedIn={auth.isLoggedIn} vmName={selectedVM} workDir={defaultWorkDir} onOpenFile={handlePreviewFile} />
              ) : sidebarPanel === "links" ? (
                <LinkList isLoggedIn={auth.isLoggedIn} onPreview={(link) => { setSelectedLinkId(link.activity_id); setSelectedLinkLinkId(null); setSelectedLinkContentKey(link.content_key || null); handleOpenFile("link.md"); }} />
              ) : sidebarPanel === "rss" ? (
                <RssFeedList isLoggedIn={auth.isLoggedIn} onSelectFeed={handleSelectFeed} selectedFeedId={selectedFeedId} />
              ) : sidebarPanel === "entity" ? (
                <EntityList isLoggedIn={auth.isLoggedIn} selectedEntityId={selectedEntityId} onSelectEntity={(id) => { setSelectedEntityId(id); handleOpenFile("entity.md"); }} />
              ) : sidebarPanel === "reminder" ? (
                <ReminderList isLoggedIn={auth.isLoggedIn} />
              ) : sidebarPanel === "routine" ? (
                <RoutineList
                  isLoggedIn={auth.isLoggedIn}
                  onShowChats={(rid) => {
                    setChatListRoutineId(rid);
                    setChatListTraceId(null);
                    setSidebarPanel("chats");
                    if (window.innerWidth < 768) {
                      setSidebarOpen(true);
                    } else {
                      setDesktopSidebarOpen(true);
                    }
                  }}
                />
              ) : sidebarPanel === "files" ? (
                <FileTree isLoggedIn={auth.isLoggedIn} onSelectFile={handleOpenFile} vmName={null} workDir={currentVmWorkDir} />
              ) : null;
            return (
              <div className="flex flex-col h-full min-h-0">
                {panelFile && (
                  <div className="p-2 border-b border-sol-base02 shrink-0">
                    <button
                      onClick={() => handleOpenFile(panelFile.path)}
                      className="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded text-xs text-sol-base1 bg-sol-base02 hover:bg-sol-base01/20 cursor-pointer"
                      title={panelFile.label}
                    >
                      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M15 3h6v6" /><path d="M10 14L21 3" /><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" />
                      </svg>
                      <span>{panelFile.label}</span>
                    </button>
                  </div>
                )}
                <div className="flex-1 min-h-0 overflow-hidden">
                  {body}
                </div>
              </div>
            );
          })()}
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
                title="Notes (Ctrl+`)"
              >
                <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
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
                onClick={() => { setSelectedChatId(null); setChatListTraceId(null); setChatListRoutineId(null); setChatTopic(null); setChatSkill(null); setChatBackend(null); setChatTraceId(null); }}
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
                <FileViewer openFiles={openFiles} activeFile={activeFile} onSelectFile={setActiveFile} onCloseFile={handleCloseFile} onReorderFiles={setOpenFiles} vmName={selectedVM} workDir={effectiveWorkDir} defaultWorkDir={defaultWorkDir} diffFiles={diffFiles} isLoggedIn={auth.isLoggedIn} selectedTraceId={selectedTraceId} selectedLinkId={selectedLinkId} selectedLinkLinkId={selectedLinkLinkId} selectedLinkContentKey={selectedLinkContentKey} selectedEntityId={selectedEntityId} selectedFeedId={selectedFeedId} selectedFeedLabel={selectedFeedLabel} onClearFeed={handleClearFeed} onSelectChat={(id) => { setSelectedChatId(id); setChatListOpen(false); setChatHide(false); }} onPreviewLink={(activityId) => { setSelectedLinkId(activityId); setSelectedLinkLinkId(null); handleOpenFile("link.md"); }} onPreviewLinkFull={(activityId, contentKey) => { setSelectedLinkId(activityId); setSelectedLinkLinkId(null); setSelectedLinkContentKey(contentKey); handleOpenFile("link.md"); }} onExternalLinkClick={handleExternalLinkClick} previewFile={previewFile} onPinFile={handlePinFile} onPreviewFile={handlePreviewFile} onChatListRefresh={() => setChatListRefreshKey((k) => k + 1)} />
              </div>
              {/* Chat (kept mounted, toggled via CSS) */}
              <div className={`absolute inset-0 flex flex-col ${chatHide ? "hidden" : ""}`}>
                {/* Chat header: VM, workdir, trace_id, chat_id, topic, refresh */}
                <div className="flex items-center gap-1 px-3 py-0.5 text-sol-base01 font-mono text-xs border-b border-sol-base02 bg-sol-base03 shrink-0">
                  {chatTraceId && <button onClick={() => { setSelectedTraceId(chatTraceId); handleOpenFile("trace.md"); }} className={`text-[0.65rem] cursor-pointer ${TRACE_BADGE}`} title="View todo">#{chatTraceId.slice(0, 8)}</button>}
                  {selectedChatId && <button onClick={() => navigator.clipboard.writeText(selectedChatId)} className={`gap-0.5 text-[0.65rem] cursor-pointer ${CHAT_BADGE}`} title="Copy chat ID"><svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>{selectedChatId.slice(0, 8)}</button>}
                  {chatTopic && <span className={`text-[0.65rem] ${topicBadgeClass(chatTopic)}`}>{chatTopic}</span>}
                  {chatSkill && <span className={`text-[0.65rem] ${topicBadgeClass(chatSkill)}`} title={`Skill: ${chatSkill}`}>/{chatSkill}</span>}
                  {chatBackend && <span className="inline-flex items-center px-1.5 py-0.5 rounded font-mono font-medium shrink-0 text-[0.65rem] bg-sol-base01/20 text-sol-base01">{chatBackend}</span>}
                  {selectedChatId && <button onClick={() => { setChatRefreshKey((k) => k + 1); setChatSpinning(true); setTimeout(() => setChatSpinning(false), 600); }} className="ml-auto inline-flex items-center hover:text-sol-blue cursor-pointer shrink-0" title="Refresh chat"><svg className={`w-3 h-3 ${chatSpinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg></button>}
                </div>
                <ChatView key={chatRefreshKey} isLoggedIn={auth.isLoggedIn} gsiReady={auth.gsiReady} chatId={selectedChatId} onChatCreated={handleChatCreated} onClear={() => { setSelectedChatId(null); setChatTopic(null); setChatSkill(null); setChatBackend(null); setChatTraceId(null); }} vmName={selectedVM} botName={selectedBot} defaultWorkDir={defaultWorkDir} onWorkDirChange={setChatWorkDir} onTopicChange={setChatTopic} onSkillChange={setChatSkill} onTraceIdChange={(traceId) => { setChatTraceId(traceId); if (traceId) setChatListTraceId(traceId); }} onBackendChange={(b) => { setChatBackend(b); if (b) setSelectedBot(b); }} onComplete={() => setChatListRefreshKey((k) => k + 1)} onOpenFile={handlePreviewFile} onSelectChat={(id) => { setSelectedChatId(id); setChatHide(false); setChatListOpen(true); }} onSelectTrace={(traceId) => { setSelectedTraceId(traceId); handleOpenFile("trace.md"); }} />
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
                <button onClick={() => setRightPanel("notes")} className={rightPanelBtnClass(rightPanel === "notes")} title="Notes">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" /></svg>
                </button>
                <button onClick={() => setRightPanel("chats")} className={rightPanelBtnClass(rightPanel === "chats")} title="Filtered Chats">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z"/></svg>
                </button>
                <button onClick={() => setRightPanel("links")} className={rightPanelBtnClass(rightPanel === "links")} title="Filtered Links">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></svg>
                </button>
                <button onClick={() => setRightPanel("files")} className={rightPanelBtnClass(rightPanel === "files")} title="Files">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                </button>
                <button onClick={() => setRightPanel("git")} className={rightPanelBtnClass(rightPanel === "git")} title="Source Control">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M13 6h3a2 2 0 0 1 2 2v7" /><line x1="6" y1="9" x2="6" y2="21" /></svg>
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
                {rightPanel === "chats" ? (
                  // Right-side ChatList is the in-context, trace-bound view — only filters
                  // by trace_id (the surrounding chat's todo). Routine filtering lives on
                  // the left-side ChatList instead.
                  <ChatList isLoggedIn={auth.isLoggedIn} selectedChatId={selectedChatId} onSelectChat={handleSelectChat} refreshKey={chatListRefreshKey} traceId={chatListTraceId} hideFilters onSelectTrace={(traceId) => { setSelectedTraceId(traceId); handleOpenFile("trace.md"); }} />
                ) : rightPanel === "notes" ? (
                  <NoteList isLoggedIn={auth.isLoggedIn} vmName={selectedVM} workDir={defaultWorkDir} onOpenFile={handleOpenFile} todoId={chatListTraceId} hideFilters />
                ) : rightPanel === "links" ? (
                  <LinkList isLoggedIn={auth.isLoggedIn} onPreview={(link) => { setSelectedLinkId(link.activity_id); setSelectedLinkLinkId(null); setSelectedLinkContentKey(link.content_key || null); handleOpenFile("link.md"); }} todoId={chatListTraceId} hideFilters />
                ) : rightPanel === "files" ? (
                  <FileTree isLoggedIn={auth.isLoggedIn} onSelectFile={handlePreviewFile} vmName={selectedVM} workDir={effectiveWorkDir} />
                ) : (
                  <GitPanel isLoggedIn={auth.isLoggedIn} vmName={selectedVM} workDir={effectiveWorkDir} onSelectFile={handleOpenDiffFile} />
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
              shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden flex flex-col
              max-w-[280px]
              ${chatListOpen ? "translate-x-0" : "translate-x-full"}
            `}
            style={{ width: rightPanelWidth }}
          >
            {/* Mobile right panel tab header */}
            <div className="flex items-center gap-1 px-2 py-1 border-b border-sol-base02 shrink-0">
              <button onClick={() => setRightPanel("notes")} className={rightPanelBtnClass(rightPanel === "notes")} title="Notes">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" /></svg>
              </button>
              <button onClick={() => setRightPanel("chats")} className={rightPanelBtnClass(rightPanel === "chats")} title="Filtered Chats">
                <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor"><path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z"/></svg>
              </button>
              <button onClick={() => setRightPanel("links")} className={rightPanelBtnClass(rightPanel === "links")} title="Filtered Links">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></svg>
              </button>
              <button onClick={() => setRightPanel("files")} className={rightPanelBtnClass(rightPanel === "files")} title="Files">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
              </button>
              <button onClick={() => setRightPanel("git")} className={rightPanelBtnClass(rightPanel === "git")} title="Source Control">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M13 6h3a2 2 0 0 1 2 2v7" /><line x1="6" y1="9" x2="6" y2="21" /></svg>
              </button>
              <div className="ml-auto flex items-center gap-1">
                <button
                  onClick={() => { setChatListRefreshKey((k) => k + 1); setChatListSpinning(true); setTimeout(() => setChatListSpinning(false), 600); }}
                  className="p-1.5 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer"
                  title="Refresh"
                >
                  <svg className={`w-4 h-4 transition-transform ${chatListSpinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                </button>
                <button
                  onClick={() => setChatListOpen(false)}
                  className="p-1.5 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer"
                  title="Close"
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
            </div>
            {/* Mobile right panel content */}
            <div className="flex-1 min-h-0 overflow-hidden">
              {rightPanel === "chats" ? (
                // Right-side ChatList is the in-context, trace-bound view — only filters
                // by trace_id. Routine filtering lives on the left-side ChatList.
                <ChatList isLoggedIn={auth.isLoggedIn} selectedChatId={selectedChatId} onSelectChat={handleSelectChat} refreshKey={chatListRefreshKey} traceId={chatListTraceId} hideFilters onSelectTrace={(traceId) => { setSelectedTraceId(traceId); handleOpenFile("trace.md"); }} />
              ) : rightPanel === "notes" ? (
                <NoteList isLoggedIn={auth.isLoggedIn} vmName={selectedVM} workDir={defaultWorkDir} onOpenFile={(path) => { handleOpenFile(path); setChatListOpen(false); }} todoId={chatListTraceId} hideFilters />
              ) : rightPanel === "links" ? (
                <LinkList isLoggedIn={auth.isLoggedIn} onPreview={(link) => { setSelectedLinkId(link.activity_id); setSelectedLinkLinkId(null); setSelectedLinkContentKey(link.content_key || null); handleOpenFile("link.md"); setChatListOpen(false); }} todoId={chatListTraceId} hideFilters />
              ) : rightPanel === "files" ? (
                <FileTree isLoggedIn={auth.isLoggedIn} onSelectFile={(path) => { handlePreviewFile(path); setChatListOpen(false); }} vmName={selectedVM} workDir={effectiveWorkDir} />
              ) : (
                <GitPanel isLoggedIn={auth.isLoggedIn} vmName={selectedVM} workDir={effectiveWorkDir} onSelectFile={(path) => { handleOpenDiffFile(path); setChatListOpen(false); }} />
              )}
            </div>
          </div>
        </div>
      </div>
      <FileSearchDialog open={fileSearchOpen} onClose={() => setFileSearchOpen(false)} onSelectFile={handleOpenFile} vmName={selectedVM} workDir={effectiveWorkDir} openFiles={openFiles} />
      <CommandPalette open={commandPaletteOpen} onClose={() => setCommandPaletteOpen(false)} actions={commandActions} />
      <LinkActionDialog
        open={!!pendingLinkUrl}
        url={pendingLinkUrl}
        status={pendingLinkStatus}
        onClose={() => { setPendingLinkUrl(null); setPendingLinkStatus(null); }}
      />
    </div>
  );
}
