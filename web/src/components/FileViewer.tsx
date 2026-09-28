import { useEffect, useState, useCallback } from "react";
import { API } from "../api";
import DiffViewer from "./DiffViewer";
import TraceView, { type TraceChatsResponse, type TraceNote } from "./TraceView";
import ArtifactView, { type ArtifactMode, type ArtifactType } from "./ArtifactView";
import ArtifactMount from "../host/ArtifactMount";
import { artifactLabel as uiArtifactLabel, artifactSlugFromTab, type MountableModule } from "../host/artifacts";
import TabRefreshButton from "./shell/TabRefreshButton";
import { tabRefreshTitle, tabRefreshVisible } from "./shell/tabRefreshState";
import { useTabRefreshChrome } from "./shell/useTabRefreshChrome";
import { fileDetailContext, type FocusRequest, type OrdinaryFileTab, type TabHistoryMap } from "../utils/fileWorkspace";
import { closeTabShortcutLabel, isApplePlatform } from "../utils/platform";
import FileTabStrip, { FileBreadcrumb } from "./shell/FileTabStrip";
import MarkdownPreview from "./shell/MarkdownPreview";


interface FileViewerProps {
  openFiles: string[];
  activeFile: string | null;
  onSelectFile: (path: string, line?: number) => void;
  onCloseFile: (path: string) => void;
  onReorderFiles: (files: string[]) => void;
  vmName?: string | null;
  workDir?: string;
  defaultWorkDir?: string;
  diffFiles?: Set<string>;
  artifactTabs?: Record<string, { type: ArtifactType; spec: string }>;
  fileTabs?: Record<string, OrdinaryFileTab>;
  fileDirty?: Record<string, boolean>;
  fileFocus?: Record<string, FocusRequest>;
  uiArtifacts?: MountableModule[];
  uiArtifactsLoaded?: boolean;
  onUiArtifactRolledBack?: () => void;
  onSelectChat?: (chatId: string) => void;
  previewFile?: string | null;
  onPinFile?: (path: string) => void;
  // Per-tab back/forward navigation history (todo 3288). Shown only when the
  // active tab is an ordinary file tab.
  fileHistory?: TabHistoryMap;
  onFileBack?: () => void;
  onFileForward?: () => void;
  // Public trace projection: render note tabs keyed by note `share_id`, with content
  // fetched from the public S3-backed `/api/note/share` endpoint (no auth, no /api/file/*).
  // Public mode only: the reserved `trace.md` tab renders <TraceView> in injected mode from `traceData`.
  // Authenticated `trace.md` is retired (todo 3179 H3); do not reintroduce it here.
  mode?: "public";
  noteMeta?: Record<string, { content_key: string; front_matter?: Record<string, unknown> | null }>;
  traceData?: TraceChatsResponse | null;
  onOpenNote?: (note: TraceNote) => void;
}

// Reserved share-tab key for the trace.md special-view in the public FileViewer.
const PUBLIC_TRACE_TAB = "trace.md";

function getFileName(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash >= 0 ? path.slice(slash + 1) : path;
}

function inlineArtifactLabel(path: string, artifactTabs?: Record<string, { type: ArtifactType; spec: string }>): string {
  return artifactTabs?.[path]?.type ?? "artifact";
}

function uiArtifactLabelForPath(path: string, artifacts: MountableModule[]): string {
  const slug = artifactSlugFromTab(path);
  const artifact = slug ? artifacts.find((item) => item.slug === slug) : undefined;
  return artifact ? uiArtifactLabel(artifact) : slug ?? "ui";
}

interface PublicNoteCache {
  content?: string;
  loading: boolean;
  error?: string;
}

// Public note-tab viewer: tabs keyed by note `share_id`, content from the no-JWT
// `/api/note/share` endpoint, rendered via MarkdownPreview. No edit/save/import,
// no binary/raw, no special-views, no /api/file/* fetches.
function PublicFileViewer({ openFiles, activeFile, onSelectFile, onCloseFile, onReorderFiles, noteMeta, traceData, onSelectChat, onOpenNote }: {
  openFiles: string[];
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onCloseFile: (path: string) => void;
  onReorderFiles: (files: string[]) => void;
  noteMeta: Record<string, { content_key: string; front_matter?: Record<string, unknown> | null }>;
  traceData?: TraceChatsResponse | null;
  onSelectChat?: (chatId: string) => void;
  onOpenNote?: (note: TraceNote) => void;
}) {
  const [cache, setCache] = useState<Record<string, PublicNoteCache>>({});

  useEffect(() => {
    if (!activeFile || activeFile === PUBLIC_TRACE_TAB) return;
    if (cache[activeFile] && !cache[activeFile].error) return;
    setCache((prev) => ({ ...prev, [activeFile]: { loading: true } }));
    fetch(`${API}/api/note/share?share_id=${encodeURIComponent(activeFile)}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 401 ? "This note is password-protected" : "Failed to load note");
        const data = await res.json();
        setCache((prev) => ({ ...prev, [activeFile]: { content: data.content ?? "", loading: false } }));
      })
      .catch((e) => setCache((prev) => ({ ...prev, [activeFile]: { loading: false, error: e.message } })));
  }, [activeFile, cache]);

  const labelFor = (shareId: string) => {
    if (shareId === PUBLIC_TRACE_TAB) return "trace";
    const ck = noteMeta[shareId]?.content_key || shareId;
    return ck.replace(/^.*\//, "").replace(/\.md$/, "");
  };

  if (openFiles.length === 0) {
    return <div className="h-full border-b border-sol-base02 bg-sol-base03" />;
  }

  const tabs = openFiles.map((shareId) => ({
    key: shareId,
    label: labelFor(shareId),
    title: noteMeta[shareId]?.content_key || shareId,
    closable: shareId !== PUBLIC_TRACE_TAB,
  }));

  return (
    <div className="flex flex-col h-full border-b border-sol-base02">
      <FileTabStrip
        tabs={tabs}
        activeKey={activeFile}
        onSelect={onSelectFile}
        onClose={onCloseFile}
        onReorder={onReorderFiles}
        breadcrumb={activeFile ? (
          <FileBreadcrumb path={noteMeta[activeFile]?.content_key || activeFile} />
        ) : undefined}
      />
      {/* Content - render all open tabs, show/hide to preserve scroll */}
      <div className="flex-1 min-h-0 bg-sol-base03 relative">
        {openFiles.map((shareId) => {
          const isActive = shareId === activeFile;
          if (shareId === PUBLIC_TRACE_TAB) {
            // trace.md special-view: same todo detail + waterfall + related links/notes
            // as the authed app, rendered read-only from the injected payload.
            return (
              <div key={shareId} className={`absolute inset-0 overflow-hidden ${isActive ? "" : "hidden"}`}>
                <TraceView
                  isLoggedIn={false}
                  selectedTraceId={traceData?.todo?.todo_id || ""}
                  injectedData={traceData}
                  onSelectChat={onSelectChat}
                  onOpenNote={onOpenNote}
                />
              </div>
            );
          }
          const fileData = cache[shareId];
          return (
            <div key={shareId} className={`absolute inset-0 overflow-auto ${isActive ? "" : "hidden"}`}>
              {!fileData || fileData.loading ? (
                <p className="text-sol-base01 italic text-sm p-3">Loading...</p>
              ) : fileData.error ? (
                <p className="text-sol-red text-sm p-3">{fileData.error}</p>
              ) : fileData.content !== undefined ? (
                <MarkdownPreview content={fileData.content} />
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function FileViewer({ openFiles, activeFile, onSelectFile, onCloseFile, onReorderFiles, vmName, workDir, defaultWorkDir, diffFiles, artifactTabs, fileTabs = {}, fileDirty = {}, fileFocus = {}, uiArtifacts = [], uiArtifactsLoaded = true, onUiArtifactRolledBack, onSelectChat, previewFile, onPinFile, fileHistory = {}, onFileBack, onFileForward, mode, noteMeta, traceData, onOpenNote }: FileViewerProps) {
  const [mdPreview, setMdPreview] = useState<Record<string, boolean>>({});
  // One refresh registry, remount nonce, and spin flag per open module tab
  // (todo 3674, contract v18; shared runner extracted for todo 3680). Keyed by
  // tab key, not slug: every open tab stays mounted while hidden, so a refresh
  // must reach exactly the active tab's subtree.
  const tabRefreshChrome = useTabRefreshChrome(openFiles);
  const isDiff = !!(activeFile && diffFiles?.has(activeFile));
  const isArtifact = !!activeFile?.startsWith("artifact:");
  const isUiArtifact = !!activeFile?.startsWith("ui:");
  // C1: host FileViewer no longer fetches ordinary files; only special tabs remain.

  const hostRefreshable = !!activeFile && !isArtifact && !isUiArtifact && !fileTabs[activeFile];
  const showRefresh = tabRefreshVisible(hostRefreshable, isUiArtifact);
  const refreshing = !!activeFile && tabRefreshChrome.isRefreshing(activeFile);

  const onRefreshClick = useCallback(() => {
    if (!activeFile || tabRefreshChrome.isRefreshing(activeFile)) return;
    // Diff tabs keep the plain host spin (they have nothing cached to
    // invalidate); module tabs get the generic two-stage refresh with no
    // module cooperation.
    if (hostRefreshable) {
      tabRefreshChrome.trigger(activeFile, () => {});
    } else {
      tabRefreshChrome.triggerScoped(activeFile);
    }
  }, [activeFile, tabRefreshChrome, hostRefreshable]);

  if (mode === "public") {
    return (
      <PublicFileViewer
        openFiles={openFiles}
        activeFile={activeFile}
        onSelectFile={onSelectFile}
        onCloseFile={onCloseFile}
        onReorderFiles={onReorderFiles}
        noteMeta={noteMeta || {}}
        traceData={traceData}
        onSelectChat={onSelectChat}
        onOpenNote={onOpenNote}
      />
    );
  }

  if (openFiles.length === 0) {
    return <div className="h-full border-b border-sol-base02 bg-sol-base03" />;
  }

  const tabs = openFiles.map((filePath) => ({
    key: filePath,
    label: fileTabs[filePath]
      ? getFileName(fileTabs[filePath].path)
      : filePath.startsWith("artifact:")
      ? inlineArtifactLabel(filePath, artifactTabs)
      : filePath.startsWith("ui:")
      ? uiArtifactLabelForPath(filePath, uiArtifacts)
      : filePath.startsWith("diff:")
      ? `${getFileName(filePath.slice(5))} (diff)`
      : getFileName(filePath),
    title: fileTabs[filePath]?.path ?? filePath,
    dirty: !!fileDirty[filePath],
    italic: filePath === previewFile,
  }));

  const activeOrdinaryTab = activeFile ? fileTabs[activeFile] : undefined;
  const activeTabHistory = activeFile ? fileHistory[activeFile] : undefined;
  const canFileBack = !!activeTabHistory && activeTabHistory.back.length > 0;
  const canFileForward = !!activeTabHistory && activeTabHistory.forward.length > 0;
  const tabHistoryNav = activeOrdinaryTab ? (
    <div className="flex items-center gap-0.5 pl-2 pr-1 shrink-0">
      <button
        type="button"
        onClick={onFileBack}
        disabled={!canFileBack}
        aria-label="Back"
        title={isApplePlatform() ? "Back (⌘[)" : "Back (Alt+←)"}
        className="text-sol-base01 hover:text-sol-base1 disabled:opacity-30 disabled:cursor-default disabled:hover:text-sol-base01 cursor-pointer p-0.5"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="15 18 9 12 15 6" />
        </svg>
      </button>
      <button
        type="button"
        onClick={onFileForward}
        disabled={!canFileForward}
        aria-label="Forward"
        title={isApplePlatform() ? "Forward (⌘])" : "Forward (Alt+→)"}
        className="text-sol-base01 hover:text-sol-base1 disabled:opacity-30 disabled:cursor-default disabled:hover:text-sol-base01 cursor-pointer p-0.5"
      >
        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>
    </div>
  ) : undefined;

  const breadcrumbPath = activeFile
    ? isArtifact
      ? inlineArtifactLabel(activeFile, artifactTabs)
      : isUiArtifact
      ? uiArtifactLabelForPath(activeFile, uiArtifacts)
      : activeFile.replace(/^diff:/, "")
    : "";

  return (
    <div className="flex flex-col h-full border-b border-sol-base02">
      <FileTabStrip
        tabs={tabs}
        activeKey={activeFile}
        onSelect={onSelectFile}
        onClose={onCloseFile}
        onReorder={onReorderFiles}
        leading={tabHistoryNav}
        closeHint={closeTabShortcutLabel()}
        onDoubleClick={(filePath) => { if (filePath === previewFile && onPinFile) onPinFile(filePath); }}
        breadcrumb={activeFile && !fileTabs[activeFile] ? (
          <FileBreadcrumb
            path={breadcrumbPath}
            leading={isDiff ? <span className="text-sol-yellow font-semibold mr-1 shrink-0">DIFF</span> : undefined}
            trailing={
              <>
                {showRefresh && (
                  <TabRefreshButton
                    title={tabRefreshTitle(hostRefreshable)}
                    spinning={refreshing}
                    onClick={onRefreshClick}
                  />
                )}
                {!isArtifact && !isUiArtifact && <button
                  onClick={() => navigator.clipboard.writeText(activeFile.replace(/^\.\//, ""))}
                  className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-1 shrink-0"
                  title="Copy path"
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M4 2a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V2zm2-1a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H6z" />
                    <path d="M2 4a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-1h1v1a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h1v1H2z" />
                  </svg>
                </button>}
              </>
            }
          />
        ) : undefined}
      />
      {/* Content - render all open files, show/hide to preserve scroll */}
      <div className="flex-1 min-h-0 bg-sol-base03 relative">
        {openFiles.map((filePath) => {
          const ordinaryTab = fileTabs[filePath];
          const fileDiff = !!(diffFiles?.has(filePath));
          const fileArtifact = filePath.startsWith("artifact:");
          const fileUiArtifactSlug = artifactSlugFromTab(filePath);
          const fileUiArtifact = fileUiArtifactSlug ? uiArtifacts.find((artifact) => artifact.slug === fileUiArtifactSlug) : undefined;
          const fileModule = ordinaryTab
            ? uiArtifacts.find((artifact) => artifact.slug === "file")
            : undefined;
          const fileName = filePath.replace(/^\.\//, "").replace(/^diff:/, "");
          const isActive = filePath === activeFile;
          return (
            <div
              key={filePath}
              className={`absolute inset-0 ${ordinaryTab || fileArtifact || fileUiArtifactSlug || fileDiff ? "overflow-hidden" : "overflow-auto"} ${isActive ? "" : "hidden"}`}
            >
              {ordinaryTab && fileModule ? (
                <div className="h-full overflow-hidden" data-ui-artifact-route="file" data-file-tab={ordinaryTab.id}>
                  <ArtifactMount
                    slug={fileModule.slug}
                    artifactId={fileModule.module_id}
                    version={fileModule.active_version}
                    label={uiArtifactLabel(fileModule)}
                    surface="detail"
                    detailContext={fileDetailContext(ordinaryTab, isActive, fileFocus[ordinaryTab.id])}
                    onRolledBack={onUiArtifactRolledBack}
                  />
                </div>
              ) : ordinaryTab ? (
                uiArtifactsLoaded ? (
                  <div className="flex h-full items-center justify-center p-4 text-sm text-sol-base01">
                    Files module is unavailable.
                  </div>
                ) : null
              ) : fileDiff ? (
                <DiffViewer filePath={fileName} vmName={vmName} workDir={workDir} />
              ) : fileUiArtifact ? (
                <div className="h-full overflow-auto" data-ui-artifact-route={fileUiArtifact.slug}>
                  <ArtifactMount
                    slug={fileUiArtifact.slug}
                    artifactId={fileUiArtifact.module_id}
                    version={fileUiArtifact.active_version}
                    label={uiArtifactLabel(fileUiArtifact)}
                    surface="detail"
                    detailContext={{ active: isActive, vmName: vmName ?? null, workDir: workDir ?? null, defaultWorkDir: defaultWorkDir ?? null }}
                    onRolledBack={onUiArtifactRolledBack}
                    refreshRegistry={tabRefreshChrome.registryFor(filePath)}
                    refreshNonce={tabRefreshChrome.nonceFor(filePath)}
                  />
                </div>
              ) : fileUiArtifactSlug ? (
                uiArtifactsLoaded ? (
                  <div className="flex h-full items-center justify-center p-4 text-sm text-sol-base01">
                    UI artifact &quot;{fileUiArtifactSlug}&quot; is unavailable.
                  </div>
                ) : null
              ) : fileArtifact && artifactTabs?.[filePath] ? (
                <ArtifactView
                  type={artifactTabs[filePath].type}
                  spec={artifactTabs[filePath].spec}
                  mode={(mdPreview[filePath] !== false ? "preview" : "raw") as ArtifactMode}
                  onModeChange={(mode) => setMdPreview((prev) => ({ ...prev, [filePath]: mode === "preview" }))}
                  variant="tab"
                />
              ) : (
                <p className="text-sol-base01 italic text-sm p-3">Unknown tab.</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
