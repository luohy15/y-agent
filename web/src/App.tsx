import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router";
import useSWR from "swr";
import { useAuth } from "./hooks/useAuth";
import { useUserPreference } from "./hooks/useUserPreference";
import { API, authFetch, jsonFetcher } from "./api";
import ChatFallbackView from "./components/ChatFallbackView";
import GoogleSignInButton from "./components/GoogleSignInButton";
import FileViewer from "./components/FileViewer";
import ActivityBar, { BUILT_IN_PANEL_ITEMS, type SidebarPanel } from "./components/ActivityBar";
import RightActivityBar from "./components/RightActivityBar";
import { buildChatPanelItem, buildFilePanelItem, buildNotePanelItem, resolveRightPanel, restoreRightPanel, type PanelItem } from "./components/panelCatalog";
import DesktopHeaderBar from "./components/shell/DesktopHeaderBar";
import CentreModeTabs from "./components/shell/CentreModeTabs";
import CommandPalette, { CommandAction } from "./components/CommandPalette";
import TerminalView from "./components/TerminalView";
import LinkList from "./components/LinkList";
import EmailList from "./components/EmailList";
import RssFeedList from "./components/RssFeedList";
import EntityList from "./components/EntityList";
import { openCalendarFocusDate } from "./utils/calendarNavigate";
import { navigateTag, type TagResultItem } from "./utils/tagNavigate";
import {
  applyTodoDeepLink,
  applyTodoHeaderChip,
  registerTodoDetailEntryPoints,
} from "./utils/todoDetailEntryPoints";
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
import {
  closeWorkspaceTabKey,
  fileDirtyPayload,
  fileRemapPayload,
  fileRemovePayload,
  FILE_AGGREGATE_TAB,
  HOST_FILE_TABS_COLLAPSED_KEY,
  HOST_FILE_TABS_MIGRATION_KEY,
  makeFileTab,
  openOrdinaryWorkspaceTab,
  persistHostWorkspace,
  readStoredDescriptors,
  reconcileFileWorkspace,
  serializeFileWorkspace,
  remapOrdinaryTabs,
  removeOrdinaryTabs,
  restoreHostWorkspace,
  restoreHostWorkspaceWithoutMigration,
  type FocusRequest,
  type OrdinaryFileTab,
} from "./utils/fileWorkspace";
import { resolveFileWorkspaceModeTransition } from "./utils/fileWorkspaceMode";
import FileSearchDialog from "./components/FileSearchDialog";
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
  isContextualFileModule,
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
  const fileWorkspacePref = useUserPreference<unknown>("fileWorkspace", { enabled: auth.isLoggedIn });
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
  // Aggregate file modules (min_host_version < 8) ignore detailContext, so the
  // host keeps the single ui:file path until a contextual file version is active.
  const contextualFileTabs = useMemo(
    () => !uiArtifactsLoading && isContextualFileModule(uiArtifactBySlug.get("file")),
    [uiArtifactsLoading, uiArtifactBySlug],
  );
  const contextualFileTabsRef = useRef(contextualFileTabs);
  contextualFileTabsRef.current = contextualFileTabs;
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
  // Todo 3084 H1: restore host workspace. One-way migration from
  // file.workspace.v2 is deferred until a contextual file module (min_host_version
  // >= 8) is active, so aggregate file v7/v10 still mounts once at ui:file.
  const initialWorkspace = useMemo(() => {
    let hostOpenTabs: string[] = [];
    try {
      hostOpenTabs = (JSON.parse(localStorage.getItem("openFiles") || "[]") as string[])
        .filter((p) => isPersistableTab(p) || p.startsWith("["))
        .filter((p) => !RETIRED_TABS.has(p));
    } catch { hostOpenTabs = []; }
    const hostActive = localStorage.getItem("activeFile");
    const hostPreview = localStorage.getItem("previewFile");
    const hostFiles = readStoredDescriptors(localStorage);
    const migrationDone = localStorage.getItem(HOST_FILE_TABS_MIGRATION_KEY) === "true";
    const collapsed = localStorage.getItem(HOST_FILE_TABS_COLLAPSED_KEY) === "true";
    return restoreHostWorkspaceWithoutMigration(
      hostOpenTabs,
      hostActive,
      hostPreview,
      hostFiles,
      (path) => isHostWorkspaceTab(path) && !RETIRED_TABS.has(path),
      isPersistableTab,
      migrationDone,
      collapsed,
    );
  }, []);
  const [openFiles, setOpenFiles] = useState<string[]>(() => initialWorkspace.openTabs);
  const [activeFile, setActiveFile] = useState<string | null>(() => initialWorkspace.active);
  const [previewFile, setPreviewFile] = useState<string | null>(() => initialWorkspace.preview);
  const [fileTabs, setFileTabs] = useState<Record<string, OrdinaryFileTab>>(() => initialWorkspace.files);
  const [fileDirty, setFileDirty] = useState<Record<string, boolean>>({});
  const [fileFocus, setFileFocus] = useState<Record<string, FocusRequest>>({});
  const [fileSearchOpen, setFileSearchOpen] = useState(false);
  const [fileSearchContext, setFileSearchContext] = useState<{ vmName: string | null; workDir: string | null }>({
    vmName: null,
    workDir: null,
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
    // C1 / todo 3164: migrate retired fixed entries onto their module panel keys.
    // `tags` becomes `artifact:tag`.
    const saved = (
      raw === "files" ? "artifact:file"
        : raw === "notes" ? "artifact:note"
          : raw === "tags" ? "artifact:tag"
            : raw
    ) as SidebarPanel;
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
  // selectedTraceId / dirty plumbing still feed the authenticated trace.md tab
  // until H3 retires it. H2 entry points must not seed or write this state —
  // selection authority is the Todo module intent only. Init from the legacy
  // persistence key so a still-open tab keeps its previous selection.
  const [selectedTraceId] = useState<string | null>(() => localStorage.getItem("selectedTraceId") || null);
  const traceTodoDirtyRef = useRef(false);
  const setTraceTodoDirty = useCallback((dirty: boolean) => { traceTodoDirtyRef.current = dirty; }, []);
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

  // Keep ui:file while collapsed, even if the active file version already looks
  // contextual. Persistence runs before the remigrate effect and must not erase
  // the aggregate slot that remigrate uses for ordering (round-12).
  useEffect(() => {
    const collapsed = localStorage.getItem(HOST_FILE_TABS_COLLAPSED_KEY) === "true";
    const dropAggregate = contextualFileTabs && !collapsed;
    const persistable = openFiles
      .filter((key) => isPersistableTab(key) || !!fileTabs[key])
      .filter((key) => (dropAggregate ? key !== FILE_AGGREGATE_TAB : true));
    localStorage.setItem("openFiles", JSON.stringify(persistable));
  }, [openFiles, fileTabs, contextualFileTabs]);
  useEffect(() => {
    const collapsed = localStorage.getItem(HOST_FILE_TABS_COLLAPSED_KEY) === "true";
    const dropAggregate = contextualFileTabs && !collapsed;
    if (
      activeFile
      && (dropAggregate ? activeFile !== FILE_AGGREGATE_TAB : true)
      && (isPersistableTab(activeFile) || fileTabs[activeFile])
    ) {
      localStorage.setItem("activeFile", activeFile);
    } else {
      localStorage.removeItem("activeFile");
    }
  }, [activeFile, fileTabs, contextualFileTabs]);
  useEffect(() => {
    const collapsed = localStorage.getItem(HOST_FILE_TABS_COLLAPSED_KEY) === "true";
    const dropAggregate = contextualFileTabs && !collapsed;
    if (
      previewFile
      && (dropAggregate ? previewFile !== FILE_AGGREGATE_TAB : true)
      && (isPersistableTab(previewFile) || fileTabs[previewFile])
    ) {
      localStorage.setItem("previewFile", previewFile);
    } else {
      localStorage.removeItem("previewFile");
    }
  }, [previewFile, fileTabs, contextualFileTabs]);
  useEffect(() => {
    // Never clobber retained descriptors with an empty live map while collapsed.
    if (localStorage.getItem(HOST_FILE_TABS_COLLAPSED_KEY) === "true" && Object.keys(fileTabs).length === 0) return;
    try {
      localStorage.setItem("host.fileDescriptors.v1", JSON.stringify(Object.values(fileTabs)));
    } catch { /* quota — leave prior descriptors */ }
  }, [fileTabs]);
  useEffect(() => { if (selectedLinkId) localStorage.setItem("selectedLinkId", selectedLinkId); else localStorage.removeItem("selectedLinkId"); }, [selectedLinkId]);
  useEffect(() => { if (selectedLinkLinkId) localStorage.setItem("selectedLinkLinkId", selectedLinkLinkId); else localStorage.removeItem("selectedLinkLinkId"); }, [selectedLinkLinkId]);
  useEffect(() => { if (selectedLinkContentKey) localStorage.setItem("selectedLinkContentKey", selectedLinkContentKey); else localStorage.removeItem("selectedLinkContentKey"); }, [selectedLinkContentKey]);
  useEffect(() => { if (selectedEntityId) localStorage.setItem("selectedEntityId", selectedEntityId); else localStorage.removeItem("selectedEntityId"); }, [selectedEntityId]);
  useEffect(() => { if (selectedCorrectionId) localStorage.setItem("selectedCorrectionId", selectedCorrectionId); else localStorage.removeItem("selectedCorrectionId"); }, [selectedCorrectionId]);
  useEffect(() => { if (selectedThreadId) localStorage.setItem("selectedThreadId", selectedThreadId); else localStorage.removeItem("selectedThreadId"); }, [selectedThreadId]);
  useEffect(() => { if (selectedThreadAccount) localStorage.setItem("selectedThreadAccount", selectedThreadAccount); else localStorage.removeItem("selectedThreadAccount"); }, [selectedThreadAccount]);

  const openFilesRef = useRef(openFiles);
  openFilesRef.current = openFiles;
  const previewFileRef = useRef(previewFile);
  previewFileRef.current = previewFile;
  const activeFileRef = useRef(activeFile);
  activeFileRef.current = activeFile;
  const fileTabsRef = useRef(fileTabs);
  fileTabsRef.current = fileTabs;
  const workspaceTouchedRef = useRef(false);
  const workspaceReconciledRef = useRef(false);
  const [workspaceVisible, setWorkspaceVisible] = useState(!auth.isLoggedIn);
  const workspaceModeKeyRef = useRef<string | null>(null);
  const workspaceModeSettledRef = useRef(false);
  const [workspaceModeSettled, setWorkspaceModeSettled] = useState(false);
  const workspaceModeKey = `${uiArtifactsLoading}:${contextualFileTabs}`;
  if (workspaceModeKeyRef.current !== workspaceModeKey) {
    workspaceModeKeyRef.current = workspaceModeKey;
    workspaceModeSettledRef.current = false;
  }
  const lastWorkspacePayloadRef = useRef<string | null>(null);
  const touchWorkspace = useCallback(() => {
    workspaceTouchedRef.current = true;
    setWorkspaceVisible(true);
  }, []);

  useEffect(() => {
    if (!auth.isLoggedIn) {
      workspaceTouchedRef.current = false;
      workspaceReconciledRef.current = false;
      setWorkspaceVisible(true);
      setWorkspaceModeSettled(false);
      lastWorkspacePayloadRef.current = null;
    } else {
      setWorkspaceVisible(false);
    }
  }, [auth.isLoggedIn]);

  // Do not leave the cached fallback hidden indefinitely if module discovery stalls.
  useEffect(() => {
    if (!auth.isLoggedIn || workspaceVisible || !fileWorkspacePref.loaded) return;
    const timer = window.setTimeout(() => setWorkspaceVisible(true), 1500);
    return () => window.clearTimeout(timer);
  }, [auth.isLoggedIn, fileWorkspacePref.loaded, workspaceVisible]);

  // Reconcile only after the authenticated preference GET and file-module mode
  // are known. A local action during the GET wins over its stale response.
  useEffect(() => {
    if (!auth.isLoggedIn || uiArtifactsLoading || !workspaceModeSettledRef.current || !workspaceModeSettled || !fileWorkspacePref.loaded || workspaceReconciledRef.current) return;
    const result = reconcileFileWorkspace(
      {
        openTabs: openFilesRef.current,
        active: activeFileRef.current,
        preview: previewFileRef.current,
        files: fileTabsRef.current,
      },
      fileWorkspacePref.serverValue,
      workspaceTouchedRef.current,
      (path) => isHostWorkspaceTab(path) && !RETIRED_TABS.has(path),
      isPersistableTab,
    );
    workspaceReconciledRef.current = true;
    const payload = serializeFileWorkspace(
      result.snapshot,
      (path) => isHostWorkspaceTab(path) && !RETIRED_TABS.has(path),
      isPersistableTab,
    );
    lastWorkspacePayloadRef.current = JSON.stringify(payload);
    if (result.source === "server") {
      persistHostWorkspace(localStorage, result.snapshot, false);
      setOpenFiles(result.snapshot.openTabs);
      setActiveFile(result.snapshot.active);
      setPreviewFile(result.snapshot.preview);
      setFileTabs(result.snapshot.files);
    } else if (result.shouldPersist) {
      fileWorkspacePref.setValue(payload);
    }
    setWorkspaceVisible(true);
  }, [auth.isLoggedIn, fileWorkspacePref.loaded, fileWorkspacePref.serverValue, fileWorkspacePref.setValue, uiArtifactsLoading, workspaceModeSettled]);

  // Persist complete normalized snapshots after bootstrap. This deliberately has
  // last-successful-write-wins behavior, matching activity-bar preferences.
  useEffect(() => {
    if (!auth.isLoggedIn || !workspaceReconciledRef.current) return;
    const snapshot = {
      openTabs: openFiles,
      active: activeFile,
      preview: previewFile,
      files: fileTabs,
    };
    const payload = serializeFileWorkspace(
      snapshot,
      (path) => isHostWorkspaceTab(path) && !RETIRED_TABS.has(path),
      isPersistableTab,
    );
    const serialized = JSON.stringify(payload);
    if (serialized === lastWorkspacePayloadRef.current) return;
    lastWorkspacePayloadRef.current = serialized;
    fileWorkspacePref.setValue(payload);
  }, [auth.isLoggedIn, openFiles, activeFile, previewFile, fileTabs, fileWorkspacePref.setValue]);

  const openHostWorkspaceTab = useCallback((path: string) => {
    touchWorkspace();
    const p = path.replace(/^\.\//, "");
    // Aggregate file mode still needs ui:file; contextual mode never reopens it.
    if (p === FILE_AGGREGATE_TAB && contextualFileTabsRef.current) return;
    setOpenFiles((files) => files.includes(p) ? files : [...files, p]);
    setActiveFile(p);
    // Pin preview if this file is the current preview (opened via non-preview action)
    setPreviewFile((current) => current === p ? null : current);
    setChatHide(true);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, [touchWorkspace]);

  const applyOrdinaryOpen = useCallback((
    path: string,
    vmName: string | null,
    workDir: string | null,
    preview: boolean,
    line?: number,
  ) => {
    touchWorkspace();
    if (!contextualFileTabsRef.current) {
      openHostWorkspaceTab(FILE_AGGREGATE_TAB);
      // Single publish for the aggregate module; callers must not re-publish.
      publishFileOpenAction(path, vmName, workDir, line);
      if (window.innerWidth < 768) setChatListOpen(false);
      return;
    }
    const tab = makeFileTab(path, vmName, workDir);
    const next = openOrdinaryWorkspaceTab(
      {
        openTabs: openFilesRef.current,
        active: activeFileRef.current,
        preview: previewFileRef.current,
        files: fileTabsRef.current,
      },
      tab,
      preview,
    );
    setFileTabs(next.files);
    setOpenFiles(next.openTabs);
    setActiveFile(next.active);
    setPreviewFile(next.preview);
    if (typeof line === "number" && Number.isFinite(line)) {
      setFileFocus((prev) => ({ ...prev, [tab.id]: { line, nonce: Date.now() } }));
    }
    setChatHide(true);
    if (window.innerWidth < 768) {
      setSidebarOpen(false);
      setChatListOpen(false);
    }
  }, [openHostWorkspaceTab, touchWorkspace]);

  const openOrdinaryFile = useCallback((
    path: string,
    line?: number,
    preview = false,
    vmName: string | null = selectedVM,
    workDir: string | null = effectiveWorkDir ?? null,
  ) => {
    const p = path.replace(/^\.\//, "");
    // applyOrdinaryOpen publishes once in aggregate mode; contextual mode has no
    // retained open action consumer.
    applyOrdinaryOpen(p, vmName, workDir, preview, line);
  }, [applyOrdinaryOpen, selectedVM, effectiveWorkDir]);

  const handleOpenFile = useCallback((path: string, line?: number) => {
    const p = path.replace(/^\.\//, "");
    if (isOrdinaryFilePath(p)) {
      // Explicit non-preview open pins (contextual) or opens aggregate ui:file.
      openOrdinaryFile(p, line, false);
      return;
    }
    openHostWorkspaceTab(p);
  }, [openHostWorkspaceTab, openOrdinaryFile]);

  // Staged rollout: migrate once a contextual file module is active; collapse
  // back to one ui:file when rolled back to aggregate file v7/v10; remigrate
  // from retained sources when contextual mode returns. Leaves file.workspace.v2
  // untouched as the module's rollback source.
  useEffect(() => {
    if (uiArtifactsLoading) return;
    setWorkspaceModeSettled(false);
    // Prefer the live strip (still holds ui:file while collapsed). Stored openFiles
    // may already have been rewritten by the earlier persistence effect on the same
    // render when contextualFileTabs flipped true (round-12).
    const liveOpenTabs = openFilesRef.current;
    let hostOpenTabs = liveOpenTabs;
    if (!liveOpenTabs.includes(FILE_AGGREGATE_TAB)) {
      try {
        const stored = (JSON.parse(localStorage.getItem("openFiles") || "[]") as string[])
          .filter((p) => isPersistableTab(p) || p.startsWith("["))
          .filter((p) => !RETIRED_TABS.has(p));
        if (stored.length) hostOpenTabs = stored;
      } catch { /* keep live openFiles */ }
    }
    const transition = resolveFileWorkspaceModeTransition({
      contextual: contextualFileTabs,
      modulesKnown: true,
      storage: localStorage,
      openTabs: hostOpenTabs,
      active: activeFileRef.current ?? localStorage.getItem("activeFile"),
      preview: previewFileRef.current ?? localStorage.getItem("previewFile"),
      // Live ordinary descriptors only. Retained storage is read inside remigrate.
      files: fileTabsRef.current,
      isHostSpecialTab: (path) => isHostWorkspaceTab(path) && !RETIRED_TABS.has(path),
      isPersistable: isPersistableTab,
    });
    if (transition.type === "none") {
      workspaceModeSettledRef.current = true;
      setWorkspaceModeSettled(true);
      return;
    }
    if (transition.type === "migrate" || transition.type === "remigrate") {
      if (!persistHostWorkspace(localStorage, transition.snapshot, true)) {
        workspaceModeSettledRef.current = true;
        setWorkspaceModeSettled(true);
        return;
      }
      try { localStorage.removeItem(HOST_FILE_TABS_COLLAPSED_KEY); } catch { /* ignore */ }
    } else if (transition.type === "collapse") {
      // Rewrite live host tabs only. Keep migration marker + descriptors +
      // file.workspace.v2; set the collapsed flag so reload preserves ui:file.
      try {
        localStorage.setItem("openFiles", JSON.stringify(transition.snapshot.openTabs));
        if (transition.snapshot.active) localStorage.setItem("activeFile", transition.snapshot.active);
        else localStorage.removeItem("activeFile");
        localStorage.removeItem("previewFile");
        localStorage.setItem(HOST_FILE_TABS_COLLAPSED_KEY, "true");
      } catch { /* quota — still apply in-memory collapse */ }
    }
    setOpenFiles(transition.snapshot.openTabs);
    setActiveFile(transition.snapshot.active);
    setPreviewFile(transition.snapshot.preview);
    setFileTabs(transition.snapshot.files);
    if (transition.type === "collapse") {
      setFileDirty({});
      setFileFocus({});
      setFileSearchOpen(false);
    }
    workspaceModeSettledRef.current = true;
    setWorkspaceModeSettled(true);
  }, [contextualFileTabs, uiArtifactsLoading]);

  // Contract v3 (plan sub-task S0, pages/plan-2979-calendar-dynamic-ui.md
  // Part D): give any artifact's `openArtifactDetail(slug)` call the same
  // tab-open path the "Open <label> full view" button already uses.
  useEffect(() => registerArtifactDetailOpener((slug) => handleOpenFile(artifactTabKey(slug))), [handleOpenFile]);

  useEffect(() => {
    // H2: todo.open / todo.openTrace / chat.openTrace share one registration
    // seam so payload ids flow into ui:todo without host selectedTraceId writes.
    const unregisterTodoDetail = registerTodoDetailEntryPoints({
      handleOpenFile,
      setChatListTraceId,
      setSelectedChatId,
      setChatHide,
      onAfterTodoOpen: () => setSidebarOpen(false),
    });
    // Plan P2 (pages/plan-3042-control-plane.md): chat control-plane host
    // commands for the code/y-module/chat UI.
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
    // Todo 3179 H1: narrow adapters for the exported TraceView module leaf.
    // chat.open / file.open already cover chat + note/file callbacks; these three
    // fill the remaining link / calendar / deep-link-back gaps without aliases.
    const unregisterLinkOpen = registerHostCommand("link.open", (payload) => {
      if (!payload || typeof payload !== "object") return;
      const { activityId, contentKey } = payload as { activityId?: unknown; contentKey?: unknown };
      if (typeof activityId !== "string") return;
      setSelectedLinkId(activityId);
      setSelectedLinkLinkId(null);
      setSelectedLinkContentKey(typeof contentKey === "string" ? contentKey : null);
      handleOpenFile("link.md");
    });
    const unregisterCalendarFocus = registerHostCommand("calendar.focusDate", (payload) => {
      if (!payload || typeof payload !== "object") return;
      const { date } = payload as { date?: unknown };
      if (typeof date !== "string") return;
      openCalendarFocusDate(date, handleOpenFile);
    });
    const unregisterTraceClearRoute = registerHostCommand("trace.clearRoute", () => {
      if (!window.location.pathname.startsWith("/trace/")) return;
      window.history.replaceState(null, "", "/");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    return () => {
      unregisterTodoDetail();
      unregisterChatOpen();
      unregisterChatSetTraceFilter();
      unregisterLinkOpen();
      unregisterCalendarFocus();
      unregisterTraceClearRoute();
    };
  }, [handleOpenFile, selectedChatId]);

  useEffect(() => {
    if (uiArtifactsLoading) return;
    const slug = artifactSlugFromPanel(sidebarPanel);
    if (slug && !uiArtifactBySlug.has(slug)) setSidebarPanel("artifact:todo");
  }, [sidebarPanel, uiArtifactBySlug, uiArtifactsLoading]);

  const handlePreviewFile = useCallback((
    path: string,
    line?: number,
    vmName: string | null = selectedVM,
    workDir: string | null = effectiveWorkDir ?? null,
  ) => {
    touchWorkspace();
    const p = path.replace(/^\.\//, "");
    if (isOrdinaryFilePath(p)) {
      // Panel/link opens retain preview semantics (plan decision 5).
      openOrdinaryFile(p, line, true, vmName, workDir);
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
      // Replace existing preview tab in-place (may drop an ordinary descriptor).
      const idx = files.indexOf(currentPreview);
      const newFiles = [...files];
      newFiles[idx] = p;
      setOpenFiles(newFiles);
      if (fileTabsRef.current[currentPreview]) {
        setFileTabs((prev) => {
          if (!prev[currentPreview]) return prev;
          const next = { ...prev };
          delete next[currentPreview];
          return next;
        });
        setFileDirty((prev) => {
          if (!(currentPreview in prev)) return prev;
          const next = { ...prev };
          delete next[currentPreview];
          return next;
        });
      }
    } else if (!isAlreadyOpen) {
      // No preview exists — add new tab
      setOpenFiles((f) => f.includes(p) ? f : [...f, p]);
    }

    setPreviewFile(p);
    setActiveFile(p);
    setChatHide(true);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, [openOrdinaryFile, selectedVM, effectiveWorkDir, touchWorkspace]);

  const handlePinFile = useCallback((path: string) => {
    touchWorkspace();
    setPreviewFile((current) => current === path ? null : current);
  }, [touchWorkspace]);

  const handleOpenDiffFile = useCallback((path: string) => {
    const diffPath = `diff:${path}`;
    setDiffFiles((prev) => new Set(prev).add(diffPath));
    handlePreviewFile(diffPath);
  }, [handlePreviewFile]);

  const handleOpenArtifact = useCallback((type: ArtifactType, spec: string) => {
    touchWorkspace();
    const id = Math.random().toString(36).slice(2, 10);
    const path = `artifact:${id}.${type}`;
    setArtifactTabs((prev) => ({ ...prev, [path]: { type, spec } }));
    setOpenFiles((files) => [...files, path]);
    setActiveFile(path);
    setPreviewFile(null);
    setChatHide(true);
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, [touchWorkspace]);

  const handleCloseFile = useCallback((path: string) => {
    touchWorkspace();
    if (fileTabsRef.current[path]) {
      const next = closeWorkspaceTabKey(
        {
          openTabs: openFilesRef.current,
          active: activeFileRef.current,
          preview: previewFileRef.current,
          files: fileTabsRef.current,
        },
        path,
      );
      setOpenFiles(next.openTabs);
      setActiveFile(next.active);
      setPreviewFile(next.preview);
      setFileTabs(next.files);
      setFileDirty((prev) => {
        if (!(path in prev)) return prev;
        const dirty = { ...prev };
        delete dirty[path];
        return dirty;
      });
      setFileFocus((prev) => {
        if (!(path in prev)) return prev;
        const focus = { ...prev };
        delete focus[path];
        return focus;
      });
      return;
    }
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
  }, [touchWorkspace]);

  const handleCloseAllFiles = useCallback(() => {
    touchWorkspace();
    setOpenFiles([]);
    setActiveFile(null);
    setPreviewFile(null);
    setFileTabs({});
    setFileDirty({});
    setFileFocus({});
  }, [touchWorkspace]);

  const handleSelectFile = useCallback((path: string) => {
    touchWorkspace();
    setActiveFile(path);
  }, [touchWorkspace]);

  const handleReorderFiles = useCallback((openTabs: string[]) => {
    touchWorkspace();
    const next = restoreHostWorkspace(
      openTabs,
      activeFileRef.current,
      previewFileRef.current,
      fileTabsRef.current,
      (path) => isHostWorkspaceTab(path) && !RETIRED_TABS.has(path),
      isPersistableTab,
    );
    setOpenFiles(next.openTabs);
    setActiveFile(next.active);
    setPreviewFile(next.preview);
    setFileTabs(next.files);
  }, [touchWorkspace]);

  const handleRemapOrdinaryFiles = useCallback((
    oldPath: string,
    newPath: string,
    vmName?: string | null,
    workDir?: string | null,
  ) => {
    touchWorkspace();
    const next = remapOrdinaryTabs(
      {
        openTabs: openFilesRef.current,
        active: activeFileRef.current,
        preview: previewFileRef.current,
        files: fileTabsRef.current,
      },
      oldPath,
      newPath,
      vmName,
      workDir,
    );
    setOpenFiles(next.openTabs);
    setActiveFile(next.active);
    setPreviewFile(next.preview);
    setFileTabs(next.files);
  }, [touchWorkspace]);

  const handleRemoveOrdinaryFiles = useCallback((
    path: string,
    vmName?: string | null,
    workDir?: string | null,
  ) => {
    touchWorkspace();
    const next = removeOrdinaryTabs(
      {
        openTabs: openFilesRef.current,
        active: activeFileRef.current,
        preview: previewFileRef.current,
        files: fileTabsRef.current,
      },
      path,
      vmName,
      workDir,
    );
    setOpenFiles(next.openTabs);
    setActiveFile(next.active);
    setPreviewFile(next.preview);
    setFileTabs(next.files);
  }, [touchWorkspace]);

  // C1: publish retained per-location VM/work-directory context for the
  // Files module panel — left uses default VM + currentVmWorkDir, right uses
  // selectedVM + effectiveWorkDir.
  usePublishFileContext(null, currentVmWorkDir ?? null, selectedVM, effectiveWorkDir ?? null);

  // Plan 3084 H3/H4: ordinary file.open opens a host tab when contextual; search
  // opens the host dialog with the caller's VM/work-dir context; remap/remove/
  // dirty are context-scoped host commands. Aggregate ui:file remains until a
  // contextual file module is active.
  useEffect(() => {
    const unregisterFileOpen = registerHostCommand("file.open", (payload) => {
      const parsed = fileOpenPayload(payload);
      if (!parsed) return;
      // applyOrdinaryOpen publishes once in aggregate mode; no second publish.
      applyOrdinaryOpen(parsed.path, parsed.vmName, parsed.workDir, true, parsed.line);
    });
    const unregisterFileClose = registerHostCommand("file.close", (payload) => {
      if (payload && typeof payload === "object" && typeof (payload as { tabId?: unknown }).tabId === "string") {
        handleCloseFile((payload as { tabId: string }).tabId);
        return;
      }
      // Compatibility: close aggregate tab if still present mid-rollout.
      if (openFilesRef.current.includes(FILE_AGGREGATE_TAB)) handleCloseFile(FILE_AGGREGATE_TAB);
    });
    const unregisterFileSearch = registerHostCommand("file.search", (payload) => {
      const { vmName, workDir } = fileSearchPayload(payload);
      // Aggregate mode: only the module dialog. Contextual mode: only the host dialog.
      if (!contextualFileTabsRef.current) {
        setFileSearchOpen(false);
        openHostWorkspaceTab(FILE_AGGREGATE_TAB);
        publishFileSearchAction(vmName, workDir);
        return;
      }
      setFileSearchContext({ vmName, workDir });
      setFileSearchOpen(true);
    });
    const unregisterFileDirty = registerHostCommand("file.dirty", (payload) => {
      const parsed = fileDirtyPayload(payload);
      if (!parsed) return;
      setFileDirty((prev) => {
        if (!parsed.dirty) {
          if (!(parsed.tabId in prev)) return prev;
          const next = { ...prev };
          delete next[parsed.tabId];
          return next;
        }
        if (prev[parsed.tabId]) return prev;
        return { ...prev, [parsed.tabId]: true };
      });
    });
    const unregisterFileRemap = registerHostCommand("file.remap", (payload) => {
      const parsed = fileRemapPayload(payload);
      if (!parsed) return;
      handleRemapOrdinaryFiles(parsed.oldPath, parsed.newPath, parsed.vmName, parsed.workDir);
    });
    const unregisterFileRemove = registerHostCommand("file.remove", (payload) => {
      const parsed = fileRemovePayload(payload);
      if (!parsed) return;
      handleRemoveOrdinaryFiles(parsed.path, parsed.vmName, parsed.workDir);
    });
    return () => {
      unregisterFileOpen();
      unregisterFileClose();
      unregisterFileSearch();
      unregisterFileDirty();
      unregisterFileRemap();
      unregisterFileRemove();
    };
  }, [applyOrdinaryOpen, handleCloseFile, handleRemapOrdinaryFiles, handleRemoveOrdinaryFiles, openHostWorkspaceTab]);

  useEffect(() => { localStorage.setItem("chatHide", String(chatHide)); }, [chatHide]);
  useEffect(() => { if (selectedChatId) localStorage.setItem("selectedChatId", selectedChatId); else localStorage.removeItem("selectedChatId"); }, [selectedChatId]);
  // Plan P2: publish selected-chat intent for code/y-module/chat (no visible change).
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

  // URL /trace/:traceId → open the Todo module's in-place detail (H2). Selection
  // authority is the retained todo intent only; do not write host selectedTraceId.
  useEffect(() => {
    applyTodoDeepLink(urlTraceId, {
      handleOpenFile,
      setSidebarPanel: (panel) => setSidebarPanel(panel),
    });
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
          if (idx < files.length) handleSelectFile(files[idx]);
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
        if (!contextualFileTabsRef.current) {
          setFileSearchOpen(false);
          openHostWorkspaceTab(FILE_AGGREGATE_TAB);
          publishFileSearchAction(selectedVM, effectiveWorkDir ?? null);
          return;
        }
        setFileSearchContext({ vmName: selectedVM, workDir: effectiveWorkDir ?? null });
        setFileSearchOpen(true);
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
    // Skip already-handled events so a module/detail bridge that preventDefault'd
    // does not also close/switch host tabs (3084 H3).
    const onPreviewKeydown = (e: MessageEvent) => {
      const k = (e.data as { __yPreviewKeydown?: KeyboardEventInit })?.__yPreviewKeydown;
      if (!k) return;
      const synthetic = new KeyboardEvent("keydown", k);
      window.dispatchEvent(synthetic);
    };
    window.addEventListener("keydown", handler);
    window.addEventListener("message", onPreviewKeydown);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("message", onPreviewKeydown);
    };
  }, [handleCloseFile, handleSelectFile, openHostWorkspaceTab, selectedVM, effectiveWorkDir]);

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

  // D-B (pages/decision-3042-chat-shell-host-seam.md): host commands the chat
  // module shell emits that had no registerHostCommand wiring yet. `chat.open`
  // / `chat.setTraceFilter` are already registered above; list refresh is
  // module-local (todo 3141), not a host command. Each remaining handler
  // mirrors the equivalent built-in ChatView prop/callback so the module shell
  // drives the same host state. Kept in its own effect (below handlePreviewFile
  // / handleOpenArtifact / handleChatCreated) since those are declared after
  // the control-plane effect above.
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
    // chat.openTrace is registered with todo.open / todo.openTrace in
    // registerTodoDetailEntryPoints (H2 seam); do not re-register here.
    return () => {
      unregisterChatCreated();
      unregisterChatCleared();
      unregisterWorkDirChanged();
      unregisterOpenFile();
      unregisterOpenArtifact();
    };
  }, [handleChatCreated, handleOpenFile, handleOpenArtifact, handlePreviewFile]);

  const handleSelectFeed = useCallback((feedId: string, label: string) => {
    setSelectedFeedId(feedId);
    setSelectedFeedLabel(label);
    handleOpenFile("links.md");
  }, [handleOpenFile]);

  const handleClearFeed = useCallback(() => {
    setSelectedFeedId(null);
    setSelectedFeedLabel(null);
  }, []);

  // Tag module click-to-navigate: one type-dispatch callback covering all 10
  // tag carriers. The actual dispatch logic lives in utils/tagNavigate.ts; this
  // supplies bound setters and closes the mobile sidebar drawer after navigating.
  // The same dependencies feed the host `tag.open` command.
  const handleTagNavigate = useCallback((entityType: string, item: TagResultItem) => {
    navigateTag(entityType, item, {
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
  }, [handleOpenFile, handlePreviewFile, defaultWorkDir, handleSelectFeed]);

  useEffect(() => {
    // Todo 3164: tag module result clicks open carrier viewers through the host.
    return registerHostCommand("tag.open", (payload) => {
      if (!payload || typeof payload !== "object") return;
      const { entityType, item } = payload as { entityType?: unknown; item?: unknown };
      if (typeof entityType !== "string" || !item || typeof item !== "object") return;
      const id = (item as { id?: unknown }).id;
      if (typeof id !== "string") return;
      const title = (item as { title?: unknown }).title;
      const resultItem: TagResultItem = typeof title === "string" ? { id, title } : { id };
      handleTagNavigate(entityType, resultItem);
    });
  }, [handleTagNavigate]);

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
              if (!contextualFileTabsRef.current) {
                setFileSearchOpen(false);
                openHostWorkspaceTab(FILE_AGGREGATE_TAB);
                publishFileSearchAction(selectedVM, effectiveWorkDir ?? null);
                return;
              }
              setFileSearchContext({ vmName: selectedVM, workDir: effectiveWorkDir ?? null });
              setFileSearchOpen(true);
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
        <DesktopHeaderBar
          leftOpen={desktopSidebarOpen}
          bottomOpen={!bottomPanelCollapsed}
          rightOpen={!rightPanelCollapsed}
          onToggleLeft={() => setDesktopSidebarOpen(v => !v)}
          onToggleBottom={() => setBottomPanelCollapsed(v => !v)}
          onToggleRight={() => setRightPanelCollapsed(v => !v)}
          meta={
            <>
              {chatListTraceId && (
                <button
                  onClick={() => applyTodoHeaderChip(chatListTraceId, { handleOpenFile })}
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
                  <div className="absolute left-0 top-full mt-1 z-50 bg-sol-base02 border border-sol-base01 rounded shadow-float py-1 min-w-[140px]">
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
                    <div className="absolute left-0 top-full mt-1 z-50 bg-sol-base02 border border-sol-base01 rounded shadow-float py-1 min-w-[140px]">
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
            </>
          }
        />
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
            <CentreModeTabs
              mode={chatHide ? "files" : "chat"}
              onModeChange={(mode) => setChatHide(mode === "files")}
              onNew={() => { setSelectedChatId(null); setChatListTraceId(null); setChatListRoutineName(null); setChatListRoutineOnly(false); setChatTopic(null); setChatSkill(null); setChatBackend(null); setChatBotName(null); setChatTraceId(null); }}
            />
            {/* Center top: FileViewer / ChatView */}
            <div className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden relative">
              {/* FileViewer (shown when chat hidden) */}
              <div className={`absolute inset-0 ${chatHide ? "" : "hidden"}`}>
                <ErrorBoundary label="Panel">
                  <FileViewer openFiles={workspaceVisible ? openFiles : []} activeFile={workspaceVisible ? activeFile : null} onSelectFile={handleSelectFile} onCloseFile={handleCloseFile} onReorderFiles={handleReorderFiles} vmName={selectedVM} workDir={effectiveWorkDir} defaultWorkDir={defaultWorkDir} diffFiles={diffFiles} artifactTabs={artifactTabs} fileTabs={workspaceVisible ? fileTabs : {}} fileDirty={fileDirty} fileFocus={fileFocus} uiArtifacts={mountedUiArtifacts} uiArtifactsLoaded={!auth.isLoggedIn || !uiArtifactsLoading} onUiArtifactRolledBack={() => { void mutateUiArtifacts(); }} isLoggedIn={auth.isLoggedIn} selectedTraceId={selectedTraceId} selectedLinkId={selectedLinkId} selectedLinkLinkId={selectedLinkLinkId} selectedLinkContentKey={selectedLinkContentKey} selectedEntityId={selectedEntityId} selectedCorrectionId={selectedCorrectionId} selectedThreadId={selectedThreadId} selectedThreadAccount={selectedThreadAccount} selectedFeedId={selectedFeedId} selectedFeedLabel={selectedFeedLabel} onClearFeed={handleClearFeed} onSelectChat={(id) => { setSelectedChatId(id); setChatListOpen(false); setChatHide(false); }} onSelectCalendarEvent={(startTime) => openCalendarFocusDate(startTime, handleOpenFile)} onPreviewLink={(activityId) => { setSelectedLinkId(activityId); setSelectedLinkLinkId(null); setSelectedLinkContentKey(null); handleOpenFile("link.md"); }} onPreviewLinkFull={(activityId, contentKey) => { setSelectedLinkId(activityId); setSelectedLinkLinkId(null); setSelectedLinkContentKey(contentKey); handleOpenFile("link.md"); }} onExternalLinkClick={handleExternalLinkClick} previewFile={workspaceVisible ? previewFile : null} onPinFile={handlePinFile} onPreviewFile={handlePreviewFile} onTraceTodoDirtyChange={setTraceTodoDirty} />
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
                    <a href="/demo" className="px-4 py-2 bg-sol-cyan text-sol-base03 rounded text-sm font-semibold cursor-pointer">Demo Trace</a>
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
      {/* Host search is always available (zero-tab shell). Use the caller's
          VM/work-dir context for both the query and the result open identity. */}
      <FileSearchDialog
        open={fileSearchOpen}
        onClose={() => setFileSearchOpen(false)}
        onSelectFile={(path) => handlePreviewFile(path, undefined, fileSearchContext.vmName, fileSearchContext.workDir)}
        vmName={fileSearchContext.vmName}
        workDir={fileSearchContext.workDir ?? undefined}
        openFiles={openFiles.map((key) => fileTabs[key]?.path ?? key)}
        onCloseAll={handleCloseAllFiles}
      />
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
