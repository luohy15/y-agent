import { useEffect, useState, useRef, useMemo, useCallback } from "react";
import { useSWRConfig } from "swr";
import { API, authFetch } from "../api";
import hljs from "highlight.js";
import "highlight.js/styles/base16/solarized-dark.min.css";
import DiffViewer from "./DiffViewer";
import TraceView, { type TraceChatsResponse, type TraceNote } from "./TraceView";
import LinkList from "./LinkList";
import EnglishView from "./EnglishView";
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
  isLoggedIn?: boolean;
  selectedLinkId?: string | null;
  selectedLinkLinkId?: string | null;
  selectedLinkContentKey?: string | null;
  selectedCorrectionId?: string | null;
  selectedFeedId?: string | null;
  selectedFeedLabel?: string | null;
  onClearFeed?: () => void;
  onSelectChat?: (chatId: string) => void;
  onPreviewLink?: (activityId: string) => void;
  onPreviewLinkFull?: (activityId: string, contentKey: string | null) => void;
  onExternalLinkClick?: (url: string) => void;
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

function getExt(path: string): string {
  const dot = path.lastIndexOf(".");
  return dot >= 0 ? path.slice(dot + 1).toLowerCase() : "";
}

function getFileName(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash >= 0 ? path.slice(slash + 1) : path;
}

// Download a file preserving its original name/extension. Pass `blobUrl` for
// binary files (images/PDFs) or `content` for text; one of the two is used.
function downloadFile(filename: string, source: { content?: string | null; blobUrl?: string }) {
  const safe = (filename || "download").replace(/[\\/:*?"<>|]/g, "_");
  const url = source.blobUrl ?? URL.createObjectURL(
    new Blob([source.content ?? ""], { type: "application/octet-stream" })
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = safe;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  if (!source.blobUrl) URL.revokeObjectURL(url);
}

function inlineArtifactLabel(path: string, artifactTabs?: Record<string, { type: ArtifactType; spec: string }>): string {
  return artifactTabs?.[path]?.type ?? "artifact";
}

function uiArtifactLabelForPath(path: string, artifacts: MountableModule[]): string {
  const slug = artifactSlugFromTab(path);
  const artifact = slug ? artifacts.find((item) => item.slug === slug) : undefined;
  return artifact ? uiArtifactLabel(artifact) : slug ?? "ui";
}

interface FileCache {
  content?: string | null;
  summary?: string | null;
  blobUrl?: string;
  loading: boolean;
  error?: string;
  linkTitle?: string;
  linkUrl?: string;
  summaryContentKey?: string;
}

function FileContentTable({ filePath, content }: { filePath: string; content: string }) {
  const highlightedHtml = useMemo(() => {
    const lang = getExt(filePath);
    try {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(content, { language: lang }).value;
      }
      return hljs.highlightAuto(content).value;
    } catch {
      return null;
    }
  }, [content, filePath]);

  const lines = (content ?? "").split("\n");
  const highlightedLines = highlightedHtml?.split("\n");

  return (
    <table className="text-sm font-mono leading-relaxed w-full border-collapse">
      <tbody>
        {lines.map((line, i) => (
          <tr key={i}>
            <td className="select-none text-right pr-3 pl-2 text-sol-base01 border-r border-sol-base02 align-top bg-sol-base03 sticky left-0 w-[1%]">
              {i + 1}
            </td>
            {highlightedLines ? (
              <td className="pl-4 pr-3 whitespace-pre-wrap break-all hljs" dangerouslySetInnerHTML={{ __html: highlightedLines[i] ?? "" }} />
            ) : (
              <td className="pl-4 pr-3 text-sol-base0 whitespace-pre-wrap break-all">
                {line}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

async function fetchLinkContent({ activityId, linkId }: { activityId?: string | null; linkId?: string | null }): Promise<{ title?: string; url?: string; content: string | null; summary?: string | null; summaryContentKey?: string }> {
  const qs = activityId
    ? `activity_id=${encodeURIComponent(activityId)}`
    : linkId
    ? `link_id=${encodeURIComponent(linkId)}`
    : "";
  const res = await authFetch(`${API}/api/link/content?${qs}`);
  if (!res.ok) throw new Error("Failed to fetch content");
  const data = await res.json();
  return { title: data.title, url: data.url || data.base_url, content: data.content, summary: data.summary, summaryContentKey: data.summary_content_key };
}

function LinkContentView({ activityId, linkId, cache, setCache, raw, onExternalLinkClick }: { activityId: string | null; linkId?: string | null; cache: Record<string, FileCache>; setCache: React.Dispatch<React.SetStateAction<Record<string, FileCache>>>; raw?: boolean; onExternalLinkClick?: (url: string) => void }) {
  const cacheKey = activityId ? `link:activity:${activityId}` : linkId ? `link:link:${linkId}` : "";
  const fileData = cacheKey ? cache[cacheKey] : undefined;
  const [showSummary, setShowSummary] = useState(false);
  const [generatingSummary, setGeneratingSummary] = useState(false);

  useEffect(() => {
    if (!cacheKey) return;
    if (!activityId && !linkId) return;
    if (fileData && !fileData.error) return;

    setCache((prev) => ({ ...prev, [cacheKey]: { loading: true } }));
    fetchLinkContent({ activityId, linkId })
      .then(({ title, url, content, summary, summaryContentKey }) => setCache((prev) => ({ ...prev, [cacheKey]: { content, summary, summaryContentKey, linkTitle: title, linkUrl: url, loading: false } })))
      .catch((e) => setCache((prev) => ({ ...prev, [cacheKey]: { loading: false, error: e.message } })));
  }, [activityId, linkId, fileData, setCache, cacheKey]);

  const handleGenerateSummary = async () => {
    if (!cacheKey || generatingSummary) return;
    setGeneratingSummary(true);
    try {
      const body = linkId ? { link_id: linkId } : { activity_id: activityId };
      const res = await authFetch(`${API}/api/link/tldr`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to generate TLDR");
      const data = await res.json();
      setCache((prev) => ({
        ...prev,
        [cacheKey]: {
          ...(prev[cacheKey] || { loading: false }),
          loading: false,
          summary: data.summary,
          summaryContentKey: data.summary_content_key,
        },
      }));
      setShowSummary(true);
    } catch (e) {
      setCache((prev) => ({ ...prev, [cacheKey]: { ...(prev[cacheKey] || { loading: false }), loading: false, error: e instanceof Error ? e.message : String(e) } }));
    } finally {
      setGeneratingSummary(false);
    }
  };

  if (!activityId && !linkId) {
    return <p className="text-sol-base01 italic text-sm p-3">No link selected.</p>;
  }

  if (!fileData || fileData.loading) {
    return <p className="text-sol-base01 italic text-sm p-3">Loading...</p>;
  }
  if (fileData.error) {
    return <p className="text-sol-red text-sm p-3">{fileData.error}</p>;
  }
  if (fileData.content !== undefined || fileData.summary !== undefined) {
    const contentMissing = fileData.content === null || fileData.content === undefined;
    const visibleContent = showSummary && fileData.summary ? fileData.summary : (fileData.content || "");
    const header = (fileData.linkTitle || fileData.linkUrl || fileData.summaryContentKey) ? (
      <div className="px-4 pt-3 pb-2 border-b border-sol-base02 shrink-0">
        {fileData.linkTitle && (
          <button
            type="button"
            onClick={() => { navigator.clipboard.writeText(fileData.linkTitle!); }}
            className="text-sol-base1 font-semibold text-sm break-words text-left cursor-pointer bg-transparent border-0 p-0 hover:text-sol-blue"
            title={`Copy title: ${fileData.linkTitle}`}
          >
            {fileData.linkTitle}
          </button>
        )}
        {fileData.linkUrl && (
          <button
            type="button"
            onClick={() => { navigator.clipboard.writeText(fileData.linkUrl!); }}
            className="text-sol-blue hover:text-sol-cyan text-xs truncate block mt-0.5 text-left cursor-pointer bg-transparent border-0 p-0 w-full"
            title={`Copy URL: ${fileData.linkUrl}`}
          >
            {fileData.linkUrl}
          </button>
        )}
        <div className="flex gap-1 mt-2">
          {contentMissing && (
            <span className="px-1.5 py-0.5 rounded text-[0.6rem] bg-sol-orange/20 text-sol-orange" title="content_key is set but the file is not present on the EC2 VM">
              not on VM
            </span>
          )}
          {fileData.summaryContentKey && (
            <button
              onClick={() => setShowSummary((v) => !v)}
              className="px-1.5 py-0.5 rounded text-[0.6rem] bg-sol-blue/20 text-sol-blue hover:text-sol-cyan cursor-pointer"
              title={fileData.summaryContentKey}
            >
              {showSummary ? "Full Content" : "TLDR"}
            </button>
          )}
          {!fileData.summaryContentKey && (
            <button
              onClick={handleGenerateSummary}
              disabled={generatingSummary}
              className="px-1.5 py-0.5 rounded text-[0.6rem] bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer disabled:opacity-50"
            >
              {generatingSummary ? "Generating TLDR..." : "Generate TLDR"}
            </button>
          )}
        </div>
      </div>
    ) : null;
    return (
      <div className="flex flex-col h-full">
        {header}
        <div className="flex-1 min-h-0 overflow-auto">
          {contentMissing && !showSummary ? (
            <p className="text-sol-base01 italic text-sm p-3">Content key is set, but the file is not on the EC2 VM.</p>
          ) : raw ? <FileContentTable filePath={cacheKey} content={visibleContent} /> : <MarkdownPreview content={visibleContent} onExternalLinkClick={onExternalLinkClick} />}
        </div>
      </div>
    );
  }
  return null;
}

function LinksMdView({ isLoggedIn, feedId, feedLabel, onClearFeed, onPreview }: { isLoggedIn: boolean; feedId: string | null; feedLabel: string | null; onClearFeed?: () => void; onPreview: (activityId: string, contentKey: string | null) => void }) {
  return (
    <div className="flex flex-col h-full">
      {feedId ? (
        <div className="px-3 py-1.5 border-b border-sol-base02 flex items-center gap-2 bg-sol-base02/50 shrink-0">
          <span className="text-sol-base01 text-xs shrink-0">Feed:</span>
          <span className="text-sol-base0 text-sm truncate flex-1" title={feedId}>{feedLabel || feedId}</span>
          {onClearFeed && (
            <button onClick={onClearFeed} className="shrink-0 text-sol-base01 hover:text-sol-red cursor-pointer" title="Clear feed filter">
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          )}
        </div>
      ) : (
        <div className="px-3 py-2 text-sol-base01 text-sm italic shrink-0">No feed selected. Click a feed in the sidebar.</div>
      )}
      <div className="flex-1 min-h-0">
        <LinkList isLoggedIn={isLoggedIn} onPreview={(link) => onPreview(link.activity_id, link.content_key || null)} feedId={feedId} />
      </div>
    </div>
  );
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

export default function FileViewer({ openFiles, activeFile, onSelectFile, onCloseFile, onReorderFiles, vmName, workDir, defaultWorkDir, diffFiles, artifactTabs, fileTabs = {}, fileDirty = {}, fileFocus = {}, uiArtifacts = [], uiArtifactsLoaded = true, onUiArtifactRolledBack, isLoggedIn, selectedLinkId, selectedLinkLinkId, selectedLinkContentKey, selectedCorrectionId, selectedFeedId, selectedFeedLabel, onClearFeed, onSelectChat, onPreviewLink, onPreviewLinkFull, onExternalLinkClick, previewFile, onPinFile, fileHistory = {}, onFileBack, onFileForward, mode, noteMeta, traceData, onOpenNote }: FileViewerProps) {
  const { mutate } = useSWRConfig();
  const [cache, setCache] = useState<Record<string, FileCache>>({});
  const [mdPreview, setMdPreview] = useState<Record<string, boolean>>({});
  // One refresh registry, remount nonce, and spin flag per open module tab
  // (todo 3674, contract v18; shared runner extracted for todo 3680). Keyed by
  // tab key, not slug: every open tab stays mounted while hidden, so a refresh
  // must reach exactly the active tab's subtree.
  const tabRefreshChrome = useTabRefreshChrome(openFiles);
  const blobUrls = useRef<Set<string>>(new Set());
  const activeFileName = activeFile?.replace(/^\.\//, "") ?? "";
  const isDiff = !!(activeFile && diffFiles?.has(activeFile));
  const isArtifact = !!activeFile?.startsWith("artifact:");
  const isUiArtifact = !!activeFile?.startsWith("ui:");
  const isLinkPreview = !isDiff && activeFileName === "link.md";
  const isLinksMd = !isDiff && activeFileName === "links.md";
  const isEnglishPreview = !isDiff && activeFileName === "english.md";
  // C1: host FileViewer no longer fetches ordinary files; only special tabs remain.

  // Clean up blob URLs and cache for closed files (link previews still use cache).
  useEffect(() => {
    setCache((prev) => {
      const next: Record<string, FileCache> = {};
      for (const f of openFiles) {
        if (prev[f]) next[f] = prev[f];
      }
      // Keep link: activity/link cache keys while their special tab is open.
      for (const [path, entry] of Object.entries(prev)) {
        if (path.startsWith("link:") && openFiles.includes("link.md")) next[path] = entry;
        if (!openFiles.includes(path) && !path.startsWith("link:") && entry.blobUrl) {
          URL.revokeObjectURL(entry.blobUrl);
          blobUrls.current.delete(entry.blobUrl);
        }
      }
      return next;
    });
  }, [openFiles]);

  useEffect(() => {
    return () => {
      blobUrls.current.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  const handleRefresh = useCallback(() => {
    if (!activeFile) return;
    if (isLinkPreview) {
      setCache((prev) => {
        const next = { ...prev };
        delete next[activeFile];
        if (selectedLinkId) delete next[`link:activity:${selectedLinkId}`];
        if (selectedLinkLinkId) delete next[`link:link:${selectedLinkLinkId}`];
        return next;
      });
      return;
    }
    if (isLinksMd) {
      mutate((key) => typeof key === "string" && key.includes("/api/link/list"));
      return;
    }
    if (isEnglishPreview) {
      mutate((key) => typeof key === "string" && key.includes("/api/english/"));
      return;
    }
  }, [activeFile, isLinkPreview, isLinksMd, isEnglishPreview, mutate, selectedLinkId, selectedLinkLinkId]);

  const hostRefreshable = !!activeFile && !isArtifact && !isUiArtifact && !fileTabs[activeFile];
  const showRefresh = tabRefreshVisible(hostRefreshable, isUiArtifact);
  const refreshing = !!activeFile && tabRefreshChrome.isRefreshing(activeFile);

  const onRefreshClick = useCallback(() => {
    if (!activeFile || tabRefreshChrome.isRefreshing(activeFile)) return;
    // Legacy special tabs keep their own targeted invalidation; module tabs get
    // the generic two-stage refresh with no module cooperation.
    if (hostRefreshable) {
      tabRefreshChrome.trigger(activeFile, () => handleRefresh());
    } else {
      tabRefreshChrome.triggerScoped(activeFile);
    }
  }, [activeFile, tabRefreshChrome, hostRefreshable, handleRefresh]);

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
      : isLinkPreview && selectedLinkContentKey
      ? (defaultWorkDir ? `${defaultWorkDir}/${selectedLinkContentKey}` : selectedLinkContentKey)
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
                {isLinkPreview && (
                  <button
                    onClick={() => setMdPreview((prev) => ({ ...prev, [activeFile]: prev[activeFile] === false }))}
                    className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0 text-xs"
                    title={mdPreview[activeFile] !== false ? "Show raw" : "Show preview"}
                  >
                    {mdPreview[activeFile] !== false ? "Raw" : "Preview"}
                  </button>
                )}
                {isLinkPreview && selectedLinkContentKey && (
                  <a
                    href={`https://github.com/luohy15/y-history/commits/main/${selectedLinkContentKey}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0 text-xs"
                    title="View file history"
                  >
                    History
                  </a>
                )}
                {isLinkPreview && (selectedLinkId || selectedLinkLinkId) && (() => {
                  const linkCacheKey = selectedLinkId
                    ? `link:activity:${selectedLinkId}`
                    : selectedLinkLinkId
                    ? `link:link:${selectedLinkLinkId}`
                    : "";
                  const linkContent = linkCacheKey ? cache[linkCacheKey]?.content : undefined;
                  if (!linkContent) return null;
                  const nameSource = selectedLinkContentKey
                    ? getFileName(selectedLinkContentKey)
                    : `link-${selectedLinkId || selectedLinkLinkId}`;
                  return (
                    <button
                      onClick={() => downloadFile(`${nameSource.replace(/\.md$/i, "")}.md`, { content: linkContent })}
                      className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0"
                      title="Download as Markdown"
                    >
                      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                        <polyline points="7 10 12 15 17 10"/>
                        <line x1="12" y1="15" x2="12" y2="3"/>
                      </svg>
                    </button>
                  );
                })()}
                {showRefresh && (
                  <TabRefreshButton
                    title={tabRefreshTitle(hostRefreshable)}
                    spinning={refreshing}
                    onClick={onRefreshClick}
                  />
                )}
                {!isArtifact && !isUiArtifact && <button
                  onClick={() => {
                    const pathToCopy = isLinkPreview && selectedLinkContentKey && defaultWorkDir
                      ? `${defaultWorkDir}/${selectedLinkContentKey}`
                      : activeFile.replace(/^\.\//, "");
                    navigator.clipboard.writeText(pathToCopy);
                  }}
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
          const fileLinkPreview = !fileDiff && !ordinaryTab && fileName === "link.md";
          const fileLinksMd = !fileDiff && !ordinaryTab && fileName === "links.md";
          const fileEnglishPreview = !fileDiff && !ordinaryTab && fileName === "english.md";
          const isActive = filePath === activeFile;
          return (
            <div
              key={filePath}
              className={`absolute inset-0 ${ordinaryTab || fileArtifact || fileUiArtifactSlug || fileDiff || fileLinksMd || fileEnglishPreview ? "overflow-hidden" : "overflow-auto"} ${isActive ? "" : "hidden"}`}
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
              ) : fileLinkPreview ? (
                <LinkContentView activityId={selectedLinkId || null} linkId={selectedLinkLinkId || null} cache={cache} setCache={setCache} raw={mdPreview[filePath] === false} onExternalLinkClick={onExternalLinkClick} />
              ) : fileLinksMd ? (
                <LinksMdView
                  isLoggedIn={!!isLoggedIn}
                  feedId={selectedFeedId || null}
                  feedLabel={selectedFeedLabel || null}
                  onClearFeed={onClearFeed}
                  onPreview={(activityId, contentKey) => {
                    if (onPreviewLinkFull) onPreviewLinkFull(activityId, contentKey);
                    else if (onPreviewLink) onPreviewLink(activityId);
                  }}
                />
              ) : fileEnglishPreview ? (
                <EnglishView correctionId={selectedCorrectionId || ""} />
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
