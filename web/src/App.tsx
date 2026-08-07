import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router";
import useSWR from "swr";
import { useAuth } from "./hooks/useAuth";
import { API, authFetch, jsonFetcher } from "./api";
import ChatFallbackView from "./components/ChatFallbackView";
import GoogleSignInButton from "./components/GoogleSignInButton";
import FileViewer from "./components/FileViewer";
import ActivityBar, { BUILT_IN_PANEL_ITEMS, type SidebarPanel } from "./components/ActivityBar";
import RightActivityBar from "./components/RightActivityBar";
import { buildChatPanelItem, buildFilePanelItem, buildNotePanelItem, resolveRightPanel, restoreRightPanel, type PanelItem } from "./components/panelCatalog";
import CommandPalette, { CommandAction } from "./components/CommandPalette";
import TerminalView from "./components/TerminalView";
import LinkList from "./components/LinkList";
import EmailList from "./components/EmailList";
import RssFeedList from "./components/RssFeedList";
import EntityList from "./components/EntityList";
import TagList from "./components/TagList";
import type { TagResultItem } from "./api";
import { navigateTag, openTodo } from "./utils/tagNavigate";
import {
  chatIdFromPayload,
  openChat,
  setChatTraceFilter,
  traceIdFromPayload,
  usePublishSelectedChatIntent,
} from "./utils/chatHost";
import {
  fileOpenPayload,
  fileSearchPayload,
  isHostWorkspaceTab,
  isOrdinaryFilePath,
  publishFileOpenAction,
  publishFileRefresh,
  publishFileSearchAction,
  usePublishFileContext,
} from "./utils/fileHost";
import { usePublishNoteIntent } from "./utils/noteHost";
import ReminderList from "./components/ReminderList";
import RoutineList from "./components/RoutineList";
import EnglishList from "./components/EnglishList";
import GitPanel from "./components/GitPanel";
import LinkActionDialog from "./components/LinkActionDialog";
import ErrorBoundary from "./components/ErrorBoundary";
import type { ArtifactType } from "./components/ArtifactView";
import ArtifactMount from "./host/ArtifactMount";
import {
  artifactLabel,
  artifactSlugFromPanel,
  artifactTabKey,
  isPersistableTab,
  modulesFromPayload,
  mountableUiArtifacts,
  resolveShellSlot,
  shellClaimant,
} from "./host/artifacts";
import { registerHostCommand } from "./host/commands";
import { registerArtifactDetailOpener, setArtifactIntent } from "./host/intents";

interface VmConfigItem {
  name: string;
  vm_name: string;
  work_dir: string;
}

interface BotConfigItem {
  name: string;
  backend: string | null;
  model: string;
}

// Tabs for panels that migrated to a dynamic-load UI artifact and no longer
// exist as a host file path. A browser holding one of these in its restored
// tab state would otherwise fetch a nonexistent file.
const RETIRED_TABS = new Set(["bot.md", "calendar.md", "todo.md"]);

// Round-2 gap closure (plan-3046-right-sidebar.md R1) + module cuts: exactly
// four right categories. Chat, Notes, and Files resolve dynamically; Diff stays
// host-owned. Links remains in the left activity bar. Order: Chat, Notes, Files, Diff.
type RightPanel = "diff" | `artifact:${string}`;
type ArtifactTab = { type: ArtifactType; spec: string };

const RIGHT_DIFF_ITEM: PanelItem<"diff"> = { key: "diff", label: "Diff", icon: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M13 6h3a2 2 0 0 1 2 2v7" /><line x1="6" y1="9" x2="6" y2="21" /></svg> };

export default function App() {
  const { traceId: urlTraceId } = useParams<{ traceId?: string }>();
  const auth = useAuth();
  const {
    data: uiArtifactsResponse,
    isLoading: uiArtifactsLoading,
    mutate: mutateUiArtifacts,
  } = useSWR<unknown>(auth.isLoggedIn ? `${API}/api/module/list?enabled_only=true` : null, jsonFetcher);
  const uiArtifacts = useMemo(() => modulesFromPayload(uiArtifactsResponse), [uiArtifactsResponse]);
  const mountedUiArtifacts = useMemo(() => mountableUiArtifacts(uiArtifacts), [uiArtifacts]);
  const uiArtifactBySlug = useMemo(
    () => new Map(mountedUiArtifacts.map((artifact) => [artifact.slug, artifact])),
    [mountedUiArtifacts],
  );
  const rightPanelItems = useMemo<PanelItem<RightPanel>[]>(
    () => [
      ...buildChatPanelItem(uiArtifacts),
      ...buildNotePanelItem(uiArtifacts),
      ...buildFilePanelItem(uiArtifacts),
      RIGHT_DIFF_ITEM,
    ],
    [uiArtifacts],
  );
  // D1a (plan-3042-chatview.md V1): the lowest-slug enabled module claiming
  // the `shell` surface. Mounted once below, keyed only on its version_id, so
  // rollback/republish is the only thing that ever remounts it.
  const shellArtifact = useMemo(() => shellClaimant(mountedUiArtifacts), [mountedUiArtifacts]);
  // Shell-slot precedence: wait on a cold module list, then mount the module
  // claimant, else the degraded host fallback. Logged-out never waits.
  const shellSlot = resolveShellSlot({
    isLoggedIn: auth.isLoggedIn,
    uiArtifactsLoading,
    hasShellClaimant: !!shellArtifact,
  });
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
    try {
      return (JSON.parse(localStorage.getItem("openFiles") || "[]") as string[])
        .filter(isPersistableTab)
        .filter((p) => !RETIRED_TABS.has(p))
        .filter(isHostWorkspaceTab);
    } catch { return []; }
  });
  const [activeFile, setActiveFile] = useState<string | null>(() => {
    const saved = localStorage.getItem("activeFile") || null;
    return saved && isPersistableTab(saved) && !RETIRED_TABS.has(saved) && isHostWorkspaceTab(saved) ? saved : null;
  });
  const [previewFile, setPreviewFile] = useState<string | null>(() => {
    const saved = localStorage.getItem("previewFile") || null;
    return saved && isPersistableTab(saved) && !RETIRED_TABS.has(saved) && isHostWorkspaceTab(saved) ? saved : null;
  });
  const [artifactTabs, setArtifactTabs] = useState<Record<string, ArtifactTab>>({});
  // Which mounted artifacts actually define a detail surface. Only known once
  // the module has loaded, so the "open full view" affordance appears with the
  // panel rather than being promised up front for a panel-only artifact.
  const [uiArtifactHasDetail, setUiArtifactHasDetail] = useState<Record<string, boolean>>({});
  const [chatHide, setChatHide] = useState(() => { const v = localStorage.getItem("chatHide"); return v === null ? false : v === "true"; });
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [selectedChatId, setSelectedChatId] = useState<string | null>(() => localStorage.getItem("selectedChatId") || null);
  const [chatListOpen, setChatListOpen] = useState(() => { const v = localStorage.getItem("chatListOpen"); return v === null ? false : v !== "false"; });
  const [sidebarPanel, setSidebarPanel] = useState<SidebarPanel>(() => {
    const raw = localStorage.getItem("sidebarPanel");
    // C1: migrate retired fixed entries onto their module panel keys.
    const saved = (raw === "files" ? "artifact:file" : raw === "notes" ? "artifact:note" : raw) as SidebarPanel;
    return BUILT_IN_PANEL_ITEMS.some((panel) => panel.key === saved) || saved?.startsWith("artifact:") ? saved : "artifact:todo";
  });
  const [diffFiles, setDiffFiles] = useState<Set<string>>(new Set());
  const [chatWorkDir, setChatWorkDir] = useState<string | null>(null);
  const [chatTopic, setChatTopic] = useState<string | null>(null);
  const [chatSkill, setChatSkill] = useState<string | null>(null);
  const [chatTraceId, setChatTraceId] = useState<string | null>(null);
  const [chatBackend, setChatBackend] = useState<string | null>(null);
  const [chatBotName, setChatBotName] = useState<string | null>(null);
  const [selectedLinkId, setSelectedLinkId] = useState<string | null>(() => localStorage.getItem("selectedLinkId") || null);
  const [selectedLinkLinkId, setSelectedLinkLinkId] = useState<string | null>(() => localStorage.getItem("selectedLinkLinkId") || null);
  const [selectedLinkContentKey, setSelectedLinkContentKey] = useState<string | null>(() => localStorage.getItem("selectedLinkContentKey") || null);
  const [pendingLinkUrl, setPendingLinkUrl] = useState<string | null>(null);
  const [pendingLinkStatus, setPendingLinkStatus] = useState<string | null>(null);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(() => localStorage.getItem("selectedEntityId") || null);
  const [selectedCorrectionId, setSelectedCorrectionId] = useState<string | null>(() => localStorage.getItem("selectedCorrectionId") || null);
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(() => localStorage.getItem("selectedThreadId") || null);
  const [selectedThreadAccount, setSelectedThreadAccount] = useState<string | null>(() => localStorage.getItem("selectedThreadAccount") || null);
  const [selectedFeedId, setSelectedFeedId] = useState<string | null>(null);
  const [selectedFeedLabel, setSelectedFeedLabel] = useState<string | null>(null);
  const [, setChatRefreshKey] = useState(0);
  const [rightPanelRefreshKey, setRightPanelRefreshKey] = useState(0);
  const [rightPanelSpinning, setRightPanelSpinning] = useState(false);
  const currentVmWorkDir = vmList.find(v => v.name === (selectedVM || "default"))?.work_dir;
  const defaultWorkDir = vmList.find(v => v.name === "default")?.work_dir;
  const effectiveWorkDir = (selectedChatId && chatWorkDir) ? chatWorkDir : currentVmWorkDir;
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(urlTraceId || localStorage.getItem("selectedTraceId") || null);
  const selectedTraceIdRef = useRef(selectedTraceId);
  selectedTraceIdRef.current = selectedTraceId;
  // TraceTodoDetail patch-buffer dirty flag; used to guard navigation away from a
  // todo with unsaved edits.
  const traceTodoDirtyRef = useRef(false);
  const setTraceTodoDirty = useCallback((dirty: boolean) => { traceTodoDirtyRef.current = dirty; }, []);
  const requestSelectTraceId = useCallback((id: string | null) => {
    if (id === selectedTraceIdRef.current) { setSelectedTraceId(id); return; }
    if (traceTodoDirtyRef.current && !window.confirm("Discard unsaved changes?")) return;
    traceTodoDirtyRef.current = false;
    setSelectedTraceId(id);
  }, []);
  const [chatListTraceId, setChatListTraceId] = useState<string | null>(localStorage.getItem("chatListTraceId") || null);
  const [chatListRoutineName, setChatListRoutineName] = useState<string | null>(localStorage.getItem("chatListRoutineName") || null);
  const [chatListRoutineOnly, setChatListRoutineOnly] = useState<boolean>(() => localStorage.getItem("chatListRoutineOnly") === "true");
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
  const [rightPanel, setRightPanel] = useState<RightPanel>(() => restoreRightPanel(localStorage.getItem("rightPanel")) as RightPanel);
  const rightPanelResizingRef = useRef(false);
  const [vmDropdownOpen, setVmDropdownOpen] = useState(false);
  const vmDropdownRef = useRef<HTMLDivElement>(null);
  const [botList, setBotList] = useState<BotConfigItem[]>([]);
  const [botListError, setBotListError] = useState<string | null>(null);
  const [selectedBot, setSelectedBot] = useState<string | null>(null);
  const [botDropdownOpen, setBotDropdownOpen] = useState(false);
  const botDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => { localStorage.setItem("openFiles", JSON.stringify(openFiles.filter(isPersistableTab))); }, [openFiles]);
  useEffect(() => { if (activeFile && isPersistableTab(activeFile)) localStorage.setItem("activeFile", activeFile); else localStorage.removeItem("activeFile"); }, [activeFile]);
  useEffect(() => { if (previewFile && isPersistableTab(previewFile)) localStorage.setItem("previewFile", previewFile); else localStorage.removeItem("previewFile"); }, [previewFile]);
  useEffect(() => { if (selectedLinkId) localStorage.setItem("selectedLinkId", selectedLinkId); else localStorage.removeItem("selectedLinkId"); }, [selectedLinkId]);
  useEffect(() => { if (selectedLinkLinkId) localStorage.setItem("selectedLinkLinkId", selectedLinkLinkId); else localStorage.removeItem("selectedLinkLinkId"); }, [selectedLinkLinkId]);
  useEffect(() => { if (selectedLinkContentKey) localStorage.setItem("selectedLinkContentKey", selectedLinkContentKey); else localStorage.removeItem("selectedLinkContentKey"); }, [selectedLinkContentKey]);
  useEffect(() => { if (selectedEntityId) localStorage.setItem("selectedEntityId", selectedEntityId); else localStorage.removeItem("selectedEntityId"); }, [selectedEntityId]);
  useEffect(() => { if (selectedCorrectionId) localStorage.setItem("selectedCorrectionId", selectedCorrectionId); else localStorage.removeItem("selectedCorrectionId"); }, [selectedCorrectionId]);
  useEffect(() => { if (selectedThreadId) localStorage.setItem("selectedThreadId", selectedThreadId); else localStorage.removeItem("selectedThreadId"); }, [selectedThreadId]);
  useEffect(() => { if (selectedThreadAccount) localStorage.setItem("selectedThreadAccount", selectedThreadAccount); else localStorage.removeItem("selectedThreadAccount"); }, [selectedThreadAccount]);

  const openHostWorkspaceTab = useCallback((path: string) => {
    const p = path.replace(/^\.\//, "");
    setOpenFiles((files) => files.includes(p) ? files : [...files, p]);
    setActiveFile(p);
    // Pin preview if this file is the current preview (opened via non-preview action)
    setPreviewFile((current) => current === p ? null : current);
    setChatHide(true);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, []);

  const openOrdinaryFile = useCallback((path: string, line?: number) => {
    const p = path.replace(/^\.\//, "");
    openHostWorkspaceTab(artifactTabKey("file"));
    publishFileOpenAction(p, selectedVM, effectiveWorkDir ?? null, line);
    if (window.innerWidth < 768) {
      setSidebarOpen(false);
      setChatListOpen(false);
    }
  }, [openHostWorkspaceTab, selectedVM, effectiveWorkDir]);

  const handleOpenFile = useCallback((path: string, line?: number) => {
    const p = path.replace(/^\.\//, "");
    if (isOrdinaryFilePath(p)) {
      openOrdinaryFile(p, line);
      return;
    }
    openHostWorkspaceTab(p);
  }, [openHostWorkspaceTab, openOrdinaryFile]);

  // Contract v3 (plan sub-task S0, pages/plan-2979-calendar-dynamic-ui.md
  // Part D): give any artifact's `openArtifactDetail(slug)` call the same
  // tab-open path the "Open <label> full view" button already uses.
  useEffect(() => registerArtifactDetailOpener((slug) => handleOpenFile(artifactTabKey(slug))), [handleOpenFile]);

  useEffect(() => {
    const todoIdFromPayload = (payload: unknown) => {
      if (!payload || typeof payload !== "object") return null;
      const { todoId } = payload as { todoId?: unknown };
      return typeof todoId === "string" ? todoId : null;
    };
    const unregisterOpen = registerHostCommand("todo.open", (payload) => {
      const todoId = todoIdFromPayload(payload);
      if (!todoId) return;
      openTodo(todoId, { requestSelectTraceId, setChatListTraceId, setSelectedChatId, setChatHide, handleOpenFile });
      setSidebarOpen(false);
    });
    const unregisterOpenTrace = registerHostCommand("todo.openTrace", (payload) => {
      const todoId = todoIdFromPayload(payload);
      if (!todoId) return;
      requestSelectTraceId(todoId);
      handleOpenFile("trace.md");
    });
    // Plan P2 (pages/plan-3042-control-plane.md): chat control-plane host
    // commands for the modules/chat UI.
    const unregisterChatOpen = registerHostCommand("chat.open", (payload) => {
      const chatId = chatIdFromPayload(payload);
      if (chatId === undefined) return;
      openChat(chatId, {
        selectedChatId,
        setSelectedChatId,
        setChatHide,
        setChatListOpen,
        bumpChatRefresh: () => setChatRefreshKey((k) => k + 1),
      });
    });
    const unregisterChatSetTraceFilter = registerHostCommand("chat.setTraceFilter", (payload) => {
      const traceId = traceIdFromPayload(payload);
      if (traceId === undefined) return;
      setChatTraceFilter(traceId, setChatListTraceId);
    });
    return () => {
      unregisterOpen();
      unregisterOpenTrace();
      unregisterChatOpen();
      unregisterChatSetTraceFilter();
    };
  }, [handleOpenFile, requestSelectTraceId, selectedChatId]);

  useEffect(() => {
    if (uiArtifactsLoading) return;
    const slug = artifactSlugFromPanel(sidebarPanel);
    if (slug && !uiArtifactBySlug.has(slug)) setSidebarPanel("artifact:todo");
  }, [sidebarPanel, uiArtifactBySlug, uiArtifactsLoading]);

  const openFilesRef = useRef(openFiles);
  openFilesRef.current = openFiles;
  const previewFileRef = useRef(previewFile);
  previewFileRef.current = previewFile;

  const handlePreviewFile = useCallback((path: string, line?: number) => {
    const p = path.replace(/^\.\//, "");
    if (isOrdinaryFilePath(p)) {
      // Module detail owns preview-tab semantics after C1.
      openOrdinaryFile(p, line);
      return;
    }
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
  }, [openOrdinaryFile]);

  const handlePinFile = useCallback((path: string) => {
    setPreviewFile((current) => current === path ? null : current);
  }, []);

  const handleOpenDiffFile = useCallback((path: string) => {
    const diffPath = `diff:${path}`;
    setDiffFiles((prev) => new Set(prev).add(diffPath));
    handlePreviewFile(diffPath);
  }, [handlePreviewFile]);

  const handleOpenArtifact = useCallback((type: ArtifactType, spec: string) => {
    const id = Math.random().toString(36).slice(2, 10);
    const path = `artifact:${id}.${type}`;
    setArtifactTabs((prev) => ({ ...prev, [path]: { type, spec } }));
    setOpenFiles((files) => [...files, path]);
    setActiveFile(path);
    setPreviewFile(null);
    setChatHide(true);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, []);

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
    if (path.startsWith("artifact:")) {
      setArtifactTabs((prev) => { const next = { ...prev }; delete next[path]; return next; });
    }
  }, []);

  const handleCloseAllFiles = useCallback(() => {
    setOpenFiles([]);
    setActiveFile(null);
    setPreviewFile(null);
  }, []);

  // C1: publish retained per-location VM/work-directory context for the
  // Files module panel — left uses default VM + currentVmWorkDir, right uses
  // selectedVM + effectiveWorkDir.
  usePublishFileContext(null, currentVmWorkDir ?? null, selectedVM, effectiveWorkDir ?? null);

  // Plan H2/C1: module -> host file control-plane commands. `file.open` opens
  // the `ui:file` tab and hands the detail surface the requested path + optional
  // line; `file.close` closes it (module owns internal tabs); `file.search`
  // opens `ui:file` and asks the detail surface to show its own search dialog.
  useEffect(() => {
    const unregisterFileOpen = registerHostCommand("file.open", (payload) => {
      const parsed = fileOpenPayload(payload);
      if (!parsed) return;
      openHostWorkspaceTab(artifactTabKey("file"));
      publishFileOpenAction(parsed.path, parsed.vmName, parsed.workDir, parsed.line);
      if (window.innerWidth < 768) setChatListOpen(false);
    });
    const unregisterFileClose = registerHostCommand("file.close", () => {
      handleCloseFile(artifactTabKey("file"));
    });
    const unregisterFileSearch = registerHostCommand("file.search", (payload) => {
      const { vmName, workDir } = fileSearchPayload(payload);
      openHostWorkspaceTab(artifactTabKey("file"));
      publishFileSearchAction(vmName, workDir);
    });
    return () => {
      unregisterFileOpen();
      unregisterFileClose();
      unregisterFileSearch();
    };
  }, [openHostWorkspaceTab, handleCloseFile]);

  useEffect(() => { localStorage.setItem("chatHide", String(chatHide)); }, [chatHide]);
  useEffect(() => { if (selectedChatId) localStorage.setItem("selectedChatId", selectedChatId); else localStorage.removeItem("selectedChatId"); }, [selectedChatId]);
  // Plan P2: publish selected-chat intent for modules/chat (no visible change).
  // D-C: also carries botName, since selectedBot is intentionally not persisted
  // to localStorage the way selectedVM is (no other fallback for the module).
  // R7 (plan-3046-right-sidebar.md): also carries the host trace filter, so
  // the right chat panel can consume it once it opts in via usePanelLocation.
  usePublishSelectedChatIntent(selectedChatId, selectedBot, chatListTraceId);
  // Plan H2 (pages/plan-3071-note-module.md decision 7): publish the note
  // trace-scope intent and per-location VM/work-directory context.
  usePublishNoteIntent(chatListTraceId, selectedVM, defaultWorkDir ?? null, selectedVM, defaultWorkDir ?? null);
  useEffect(() => { if (selectedTraceId) localStorage.setItem("selectedTraceId", selectedTraceId); else localStorage.removeItem("selectedTraceId"); }, [selectedTraceId]);
  useEffect(() => { if (chatListTraceId) localStorage.setItem("chatListTraceId", chatListTraceId); else localStorage.removeItem("chatListTraceId"); }, [chatListTraceId]);
  useEffect(() => { if (chatListRoutineName) localStorage.setItem("chatListRoutineName", chatListRoutineName); else localStorage.removeItem("chatListRoutineName"); }, [chatListRoutineName]);
  useEffect(() => { localStorage.setItem("chatListRoutineOnly", String(chatListRoutineOnly)); }, [chatListRoutineOnly]);
  useEffect(() => { localStorage.setItem("chatListOpen", String(chatListOpen)); }, [chatListOpen]);
  useEffect(() => { localStorage.setItem("chatListWidth", String(rightPanelWidth)); }, [rightPanelWidth]);
  useEffect(() => { localStorage.setItem("chatListCollapsed", String(rightPanelCollapsed)); }, [rightPanelCollapsed]);
  useEffect(() => { localStorage.setItem("bottomPanelCollapsed", String(bottomPanelCollapsed)); }, [bottomPanelCollapsed]);
  useEffect(() => { localStorage.setItem("bottomPanelHeight", String(bottomPanelHeight)); }, [bottomPanelHeight]);
  useEffect(() => { localStorage.setItem("desktopSidebarOpen", String(desktopSidebarOpen)); }, [desktopSidebarOpen]);
  useEffect(() => { localStorage.setItem("sidebarPanel", sidebarPanel); }, [sidebarPanel]);
  useEffect(() => { localStorage.setItem("rightPanel", rightPanel); }, [rightPanel]);
  useEffect(() => {
    setRightPanel((current) => resolveRightPanel(current, rightPanelItems, !uiArtifactsLoading) as RightPanel);
  }, [uiArtifactsLoading, rightPanelItems]);
  useEffect(() => { if (selectedVM) localStorage.setItem("selectedVM", selectedVM); else localStorage.removeItem("selectedVM"); }, [selectedVM]);
  useEffect(() => { localStorage.removeItem("selectedBot"); }, []);
  // The picker is a per-chat choice: on an existing chat it re-bots that chat on
  // its next run, so drop it when the conversation changes rather than carrying
  // the pick into an unrelated chat.
  useEffect(() => { setSelectedBot(null); }, [selectedChatId]);
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
  const refreshBotList = useCallback(() => {
    if (!auth.isLoggedIn) { setBotList([]); setBotListError(null); return; }
    authFetch(`${API}/api/chat/bot-options`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`Failed to load bot options (${r.status})`);
        return r.json();
      })
      .then(data => {
        const bots = data || [];
        setBotList(bots);
        setBotListError(null);
        if (selectedBot && !bots.some((b: BotConfigItem) => b.name === selectedBot)) {
          setSelectedBot(null);
        }
      })
      .catch((error: unknown) => {
        setBotList([]);
        setBotListError(error instanceof Error ? error.message : "Failed to load bot options");
      });
  }, [auth.isLoggedIn, selectedBot]);
  useEffect(() => {
    if (!auth.isLoggedIn) { setVmList([]); setBotList([]); return; }
    authFetch(`${API}/api/vm-config/list`).then(r => r.json()).then(data => setVmList(data || [])).catch(() => setVmList([]));
    refreshBotList();
  }, [auth.isLoggedIn, refreshBotList]);

  // URL /trace/:traceId → open trace as file
  useEffect(() => {
    if (urlTraceId) {
      setSelectedTraceId(urlTraceId);
      handleOpenFile("trace.md");
      setSidebarPanel("artifact:todo");
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
  const chatHideRef = useRef(chatHide);
  chatHideRef.current = chatHide;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "`") {
        e.preventDefault();
        setChatHide((v) => !v);
      }
      // Ctrl+<number> switches FileViewer tabs (1-8 by position, 9 = last tab,
      // browser convention). Only when the FileViewer panel is active (chat hidden)
      // and more than one tab is open. Ctrl-only to avoid clashing with the Mac
      // Cmd+number browser tab shortcut.
      if (e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey && e.key >= "1" && e.key <= "9") {
        const files = openFilesRef.current;
        if (chatHideRef.current && files.length > 1) {
          e.preventDefault();
          const n = Number(e.key);
          const idx = n === 9 ? files.length - 1 : n - 1;
          if (idx < files.length) setActiveFile(files[idx]);
          return;
        }
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "p") {
        e.preventDefault();
        setCommandPaletteOpen(true);
        return;
      }
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key === "p") {
        e.preventDefault();
        openHostWorkspaceTab(artifactTabKey("file"));
        publishFileSearchAction(selectedVM, effectiveWorkDir ?? null);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "w") {
        const el = document.activeElement;
        if ((el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) && !el.dataset.editor) return;
        e.preventDefault();
        if (activeFileRef.current) handleCloseFile(activeFileRef.current);
      }
    };
    // Sandboxed (origin-null) HTML preview iframes swallow keydown events when
    // focused, so global shortcuts stop firing once the user clicks into the
    // preview. FileViewer injects a bridge that postMessages those keydowns out;
    // replay them as synthetic window events so `handler` runs unchanged.
    const onPreviewKeydown = (e: MessageEvent) => {
      const k = (e.data as { __yPreviewKeydown?: KeyboardEventInit })?.__yPreviewKeydown;
      if (k) window.dispatchEvent(new KeyboardEvent("keydown", k));
    };
    window.addEventListener("keydown", handler);
    window.addEventListener("message", onPreviewKeydown);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("message", onPreviewKeydown);
    };
  }, [handleCloseFile, openHostWorkspaceTab, selectedVM, effectiveWorkDir]);

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

  // D-B (pages/decision-3042-chat-shell-host-seam.md): the six D1b host
  // commands modules/chat v2 emits (chat/ui/host-commands.ts) that had no
  // registerHostCommand wiring yet — `chat.open` / `chat.refreshList` /
  // `chat.setTraceFilter` are already registered above. Each mirrors the
  // equivalent built-in ChatView prop/callback so the module shell drives the
  // same host state. Kept in its own effect (below handlePreviewFile /
  // handleOpenArtifact / handleChatCreated) since those are declared after the
  // control-plane effect above.
  useEffect(() => {
    const unregisterChatCreated = registerHostCommand("chat.created", (payload) => {
      const chatId = chatIdFromPayload(payload);
      if (!chatId) return;
      handleChatCreated(chatId);
    });
    const unregisterChatCleared = registerHostCommand("chat.cleared", () => {
      setSelectedChatId(null);
      setChatTopic(null);
      setChatSkill(null);
      setChatBackend(null);
      setChatBotName(null);
      setChatTraceId(null);
    });
    const unregisterWorkDirChanged = registerHostCommand("chat.workDirChanged", (payload) => {
      if (!payload || typeof payload !== "object") return;
      const { workDir } = payload as { workDir?: unknown };
      if (workDir !== null && typeof workDir !== "string") return;
      setChatWorkDir(workDir);
    });
    const unregisterOpenFile = registerHostCommand("chat.openFile", (payload) => {
      if (!payload || typeof payload !== "object") return;
      const { path, line } = payload as { path?: unknown; line?: unknown };
      if (typeof path !== "string") return;
      handlePreviewFile(path, typeof line === "number" ? line : undefined);
    });
    const unregisterOpenArtifact = registerHostCommand("chat.openArtifact", (payload) => {
      if (!payload || typeof payload !== "object") return;
      const { type, spec } = payload as { type?: unknown; spec?: unknown };
      if (typeof type !== "string" || typeof spec !== "string") return;
      handleOpenArtifact(type as ArtifactType, spec);
    });
    const unregisterOpenTrace = registerHostCommand("chat.openTrace", (payload) => {
      const traceId = traceIdFromPayload(payload);
      if (!traceId) return;
      requestSelectTraceId(traceId);
      handleOpenFile("trace.md");
    });
    return () => {
      unregisterChatCreated();
      unregisterChatCleared();
      unregisterWorkDirChanged();
      unregisterOpenFile();
      unregisterOpenArtifact();
      unregisterOpenTrace();
    };
  }, [handleChatCreated, handleOpenFile, handleOpenArtifact, handlePreviewFile, requestSelectTraceId]);

  const handleSelectFeed = useCallback((feedId: string, label: string) => {
    setSelectedFeedId(feedId);
    setSelectedFeedLabel(label);
    handleOpenFile("links.md");
  }, [handleOpenFile]);

  const handleClearFeed = useCallback(() => {
    setSelectedFeedId(null);
    setSelectedFeedLabel(null);
  }, []);

  // Tags panel click-to-navigate: one type-dispatch callback covering all 10
  // tag carriers. The actual dispatch logic lives in utils/tagNavigate.ts (unit
  // tested there against a mocked authFetch); this just supplies the bound
  // setters and closes the mobile sidebar drawer after navigating.
  const handleTagNavigate = useCallback((entityType: string, item: TagResultItem) => {
    navigateTag(entityType, item, {
      requestSelectTraceId,
      setChatListTraceId,
      setSelectedChatId,
      setChatHide,
      handleOpenFile,
      handlePreviewFile,
      defaultWorkDir,
      setSelectedEntityId,
      setSelectedLinkId,
      setSelectedLinkLinkId,
      setSelectedLinkContentKey,
      handleSelectFeed,
      setSelectedThreadId,
      setSelectedThreadAccount,
      setSidebarPanel,
    });
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, [requestSelectTraceId, handleOpenFile, handlePreviewFile, defaultWorkDir, handleSelectFeed]);

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

  const refreshRightPanel = useCallback(() => {
    setRightPanelRefreshKey((k) => k + 1);
    // Module Files and Notes panels read top-level intent.nonce; Git uses refreshKey.
    publishFileRefresh();
    setRightPanelSpinning(true);
    setTimeout(() => setRightPanelSpinning(false), 600);
  }, []);

  const commandActions: CommandAction[] = useMemo(() => [
    {
      id: 'close-all-editors',
      label: 'Close All Editors',
      execute: handleCloseAllFiles,
    },
  ], [handleCloseAllFiles]);

  const rightPanelBtnClass = (active: boolean) =>
    `p-1.5 sm:p-1 rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1"}`;

  const renderRightPanel = (mobile = false) => {
    const artifactSlug = artifactSlugFromPanel(rightPanel);
    const artifact = artifactSlug ? uiArtifactBySlug.get(artifactSlug) : undefined;
    const closeMobile = () => { if (mobile) setChatListOpen(false); };

    if (artifact) {
      return (
        <ArtifactMount
          slug={artifact.slug}
          artifactId={artifact.module_id}
          version={artifact.active_version}
          label={artifactLabel(artifact)}
          surface="panel"
          panelLocation="right"
          onRolledBack={() => { void mutateUiArtifacts(); }}
        />
      );
    }
    return <GitPanel isLoggedIn={auth.isLoggedIn} vmName={selectedVM} workDir={effectiveWorkDir} onSelectFile={(path) => { handleOpenDiffFile(path); closeMobile(); }} refreshKey={rightPanelRefreshKey} />;
  };

  return (
    <ErrorBoundary className="h-dvh">
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
            onClick={() => {
              openHostWorkspaceTab(artifactTabKey("file"));
              publishFileSearchAction(selectedVM, effectiveWorkDir ?? null);
            }}
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
                onClick={() => { requestSelectTraceId(chatListTraceId); handleOpenFile("trace.md"); }}
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
                    onClick={() => { setSelectedVM(null); setSelectedChatId(null); setChatTopic(null); setChatSkill(null); setChatBackend(null); setChatBotName(null); setChatTraceId(null); setVmDropdownOpen(false); }}
                    className={`w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 ${!selectedVM ? "text-sol-blue font-semibold" : "text-sol-base1"}`}
                  >
                    default
                  </button>
                  {vmList.filter((vm) => vm.name !== "default").map((vm) => (
                    <button
                      key={vm.name}
                      onClick={() => { setSelectedVM(vm.name); setSelectedChatId(null); setChatTopic(null); setChatSkill(null); setChatBackend(null); setChatBotName(null); setChatTraceId(null); setVmDropdownOpen(false); }}
                      className={`w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 ${selectedVM === vm.name ? "text-sol-blue font-semibold" : "text-sol-base1"}`}
                    >
                      {vm.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {botListError && <span className="text-sol-red" title={botListError}>bot options unavailable</span>}
            {botList.length > 1 && (
              <div className="relative shrink-0" ref={botDropdownRef}>
                <button
                  onClick={() => setBotDropdownOpen((v) => !v)}
                  className={`p-0 bg-transparent border-0 ${botDropdownOpen ? "text-sol-blue cursor-pointer" : "hover:text-sol-base0 cursor-pointer"}`}
                  title={selectedChatId ? `Bot: ${selectedBot || chatBotName || "default"} (pick another to switch this chat on its next run)` : `Bot: ${selectedBot || "default"}`}
                >
                  {selectedBot || (selectedChatId ? chatBotName : null) || "default"}
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
          artifacts={uiArtifacts}
          artifactsLoaded={!auth.isLoggedIn || !uiArtifactsLoading}
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
            ${activityBarOpen ? "translate-x-0" : "-translate-x-full hidden"}
          `}
          style={{ width: 200 }}
        >
          <ActivityBar
            mobile
            isLoggedIn={auth.isLoggedIn}
            artifacts={uiArtifacts}
            artifactsLoaded={!auth.isLoggedIn || !uiArtifactsLoading}
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
            ${sidebarOpen ? "translate-x-0" : "-translate-x-full hidden"}
            ${desktopSidebarOpen ? "md:translate-x-0 md:block" : "md:-translate-x-full md:hidden"}
          `}
          style={{ width: sidebarWidth }}
        >
          {(() => {
            const artifactSlug = artifactSlugFromPanel(sidebarPanel);
            const sidebarArtifact = artifactSlug ? uiArtifactBySlug.get(artifactSlug) : undefined;
            const panelFileMap: Partial<Record<SidebarPanel, { path: string; label: string }>> = {
              dev: { path: "dev.md", label: "Open dev.md" },
            };
            const panelFile = sidebarArtifact
              ? (uiArtifactHasDetail[sidebarArtifact.slug]
                  ? { path: artifactTabKey(sidebarArtifact.slug), label: `Open ${artifactLabel(sidebarArtifact)} full view` }
                  : undefined)
              : panelFileMap[sidebarPanel];
            const body =
              sidebarArtifact ? (
                <div className="h-full overflow-auto" data-ui-artifact-sidebar={sidebarArtifact.slug}>
                  <ArtifactMount
                    slug={sidebarArtifact.slug}
                    artifactId={sidebarArtifact.module_id}
                    version={sidebarArtifact.active_version}
                    label={artifactLabel(sidebarArtifact)}
                    surface="panel"
                    panelLocation="left"
                    onRolledBack={() => { void mutateUiArtifacts(); }}
                    onDetailAvailable={(hasDetail) => setUiArtifactHasDetail((prev) => (
                      prev[sidebarArtifact.slug] === hasDetail ? prev : { ...prev, [sidebarArtifact.slug]: hasDetail }
                    ))}
                  />
                </div>
              ) : sidebarPanel === "links" ? (
                <LinkList isLoggedIn={auth.isLoggedIn} onPreview={(link) => { setSelectedLinkId(link.activity_id); setSelectedLinkLinkId(null); setSelectedLinkContentKey(link.content_key || null); handleOpenFile("link.md"); }} />
              ) : sidebarPanel === "email" ? (
                <EmailList isLoggedIn={auth.isLoggedIn} selectedThreadId={selectedThreadId} onSelectEmail={(email) => { setSelectedThreadId(email.thread_id || email.email_id); setSelectedThreadAccount(email.account || null); handleOpenFile("email.md"); }} />
              ) : sidebarPanel === "rss" ? (
                <RssFeedList isLoggedIn={auth.isLoggedIn} onSelectFeed={handleSelectFeed} selectedFeedId={selectedFeedId} />
              ) : sidebarPanel === "entity" ? (
                <EntityList isLoggedIn={auth.isLoggedIn} selectedEntityId={selectedEntityId} onSelectEntity={(id) => { setSelectedEntityId(id); handleOpenFile("entity.md"); }} />
              ) : sidebarPanel === "tags" ? (
                <TagList isLoggedIn={auth.isLoggedIn} onNavigate={handleTagNavigate} />
              ) : sidebarPanel === "reminder" ? (
                <ReminderList isLoggedIn={auth.isLoggedIn} />
              ) : sidebarPanel === "routine" ? (
                <RoutineList
                  isLoggedIn={auth.isLoggedIn}
                  onShowChats={(routineName) => {
                    setChatListRoutineName(routineName);
                    setChatListRoutineOnly(false);
                    setArtifactIntent("chat", { kind: "routine-filter", routineName, routineOnly: false, nonce: Date.now() });
                    setSidebarPanel("artifact:chat");
                    if (window.innerWidth < 768) {
                      setSidebarOpen(true);
                    } else {
                      setDesktopSidebarOpen(true);
                    }
                  }}
                  onShowAllChats={() => {
                    setChatListRoutineName(null);
                    setChatListRoutineOnly(true);
                    setArtifactIntent("chat", { kind: "routine-filter", routineName: null, routineOnly: true, nonce: Date.now() });
                    setSidebarPanel("artifact:chat");
                    if (window.innerWidth < 768) {
                      setSidebarOpen(true);
                    } else {
                      setDesktopSidebarOpen(true);
                    }
                  }}
                />
              ) : sidebarPanel === "english" ? (
                <EnglishList
                  isLoggedIn={auth.isLoggedIn}
                  selectedCorrectionId={selectedCorrectionId}
                  onSelectCorrection={(id) => {
                    setSelectedCorrectionId(id);
                    handleOpenFile("english.md");
                  }}
                />
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
                  <ErrorBoundary label="Panel">{body}</ErrorBoundary>
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
                onClick={() => { setSelectedChatId(null); setChatListTraceId(null); setChatListRoutineName(null); setChatListRoutineOnly(false); setChatTopic(null); setChatSkill(null); setChatBackend(null); setChatBotName(null); setChatTraceId(null); }}
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
                <ErrorBoundary label="Panel">
                  <FileViewer openFiles={openFiles} activeFile={activeFile} onSelectFile={setActiveFile} onCloseFile={handleCloseFile} onReorderFiles={setOpenFiles} vmName={selectedVM} workDir={effectiveWorkDir} defaultWorkDir={defaultWorkDir} diffFiles={diffFiles} artifactTabs={artifactTabs} uiArtifacts={mountedUiArtifacts} uiArtifactsLoaded={!auth.isLoggedIn || !uiArtifactsLoading} onUiArtifactRolledBack={() => { void mutateUiArtifacts(); }} isLoggedIn={auth.isLoggedIn} selectedTraceId={selectedTraceId} selectedLinkId={selectedLinkId} selectedLinkLinkId={selectedLinkLinkId} selectedLinkContentKey={selectedLinkContentKey} selectedEntityId={selectedEntityId} selectedCorrectionId={selectedCorrectionId} selectedThreadId={selectedThreadId} selectedThreadAccount={selectedThreadAccount} selectedFeedId={selectedFeedId} selectedFeedLabel={selectedFeedLabel} onClearFeed={handleClearFeed} onSelectChat={(id) => { setSelectedChatId(id); setChatListOpen(false); setChatHide(false); }} onSelectCalendarEvent={(startTime) => { setArtifactIntent("calendar", { kind: "focus-date", date: startTime, nonce: Date.now() }); handleOpenFile(artifactTabKey("calendar")); }} onPreviewLink={(activityId) => { setSelectedLinkId(activityId); setSelectedLinkLinkId(null); handleOpenFile("link.md"); }} onPreviewLinkFull={(activityId, contentKey) => { setSelectedLinkId(activityId); setSelectedLinkLinkId(null); setSelectedLinkContentKey(contentKey); handleOpenFile("link.md"); }} onExternalLinkClick={handleExternalLinkClick} previewFile={previewFile} onPinFile={handlePinFile} onPreviewFile={handlePreviewFile} onTraceTodoDirtyChange={setTraceTodoDirty} />
                </ErrorBoundary>
              </div>
              {/* Chat stays mounted while hidden. The shell module owns the live
                  view; ChatFallbackView covers a disabled or failed module. */}
              <div className={`absolute inset-0 flex flex-col ${chatHide ? "hidden" : ""}`}>
                {shellSlot === "loading" ? (
                  <div className="flex-1 flex items-center justify-center text-sol-base01 text-xs font-mono">
                    Loading chat surface…
                  </div>
                ) : shellSlot === "module" && shellArtifact ? (
                  // D1a: a module claiming `shell` replaces the host ChatView
                  // in this slot. Keyed only on version_id, so republishing an
                  // unrelated module or a slug reordering never remounts it.
                  // On bundle failure, keep ChatFallbackView under FailureCard
                  // so the conversation stays readable + sendable (D1f).
                  <ArtifactMount
                    key={shellArtifact.active_version.version_id}
                    slug={shellArtifact.slug}
                    artifactId={shellArtifact.module_id}
                    version={shellArtifact.active_version}
                    surface="shell"
                    onRolledBack={() => { void mutateUiArtifacts(); }}
                    fallback={
                      <ChatFallbackView
                        chatId={selectedChatId}
                        vmName={selectedVM}
                        botName={selectedBot}
                        onChatCreated={handleChatCreated}
                      />
                    }
                  />
                ) : !auth.isLoggedIn ? (
                  <div className="flex-1 flex flex-col items-center justify-center gap-4">
                    <a href="/t/7ef7c6" className="px-4 py-2 bg-sol-cyan text-sol-base03 rounded-md text-sm font-semibold cursor-pointer">Demo Trace</a>
                    <GoogleSignInButton gsiReady={auth.gsiReady} />
                  </div>
                ) : (
                  <ChatFallbackView
                    chatId={selectedChatId}
                    vmName={selectedVM}
                    botName={selectedBot}
                    onChatCreated={handleChatCreated}
                  />
                )}
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
          {/* Right panel (scoped views, always visible independent of chatHide).
              Round-2 gap closure (plan-3046-right-sidebar.md R2/R3): the
              category row lives inside this resizable pane, above the body,
              so it disappears with the drawer on collapse. Category clicks
              only switch panels; Close (here or the header toggle below) is
              the only thing that collapses. */}
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
              <RightActivityBar
                items={rightPanelItems}
                activePanel={rightPanel}
                onSelectPanel={setRightPanel}
                onRefresh={refreshRightPanel}
                onClose={() => setRightPanelCollapsed(true)}
                refreshing={rightPanelSpinning}
              />
              <div className="flex-1 min-h-0 overflow-hidden">
                <ErrorBoundary label="Panel">{renderRightPanel()}</ErrorBoundary>
              </div>
            </div>
          )}
          {chatListOpen && (
            <div className="fixed inset-0 bg-black/40 z-20 md:hidden" onClick={() => setChatListOpen(false)} />
          )}
          <div
            className={`
              fixed inset-y-0 right-0 z-30 transform transition-transform duration-200
              md:hidden shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden flex flex-col
              max-w-[280px] ${chatListOpen ? "translate-x-0" : "translate-x-full hidden"}
            `}
            style={{ width: rightPanelWidth }}
          >
            <RightActivityBar
              items={rightPanelItems}
              activePanel={rightPanel}
              onSelectPanel={setRightPanel}
              onRefresh={refreshRightPanel}
              onClose={() => setChatListOpen(false)}
              refreshing={rightPanelSpinning}
            />
            <div className="flex-1 min-h-0 overflow-hidden">
              <ErrorBoundary label="Panel">{renderRightPanel(true)}</ErrorBoundary>
            </div>
          </div>
        </div>
      </div>
      <CommandPalette open={commandPaletteOpen} onClose={() => setCommandPaletteOpen(false)} actions={commandActions} />
      <LinkActionDialog
        open={!!pendingLinkUrl}
        url={pendingLinkUrl}
        status={pendingLinkStatus}
        onClose={() => { setPendingLinkUrl(null); setPendingLinkStatus(null); }}
      />
    </div>
    </ErrorBoundary>
  );
}
