import { useState, useCallback, useRef, useEffect, MutableRefObject } from "react";
import { createPortal } from "react-dom";
import { API, authFetch } from "../api";

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

interface FileEntry {
  name: string;
  type: "file" | "directory";
}

// Shared registry: dirPath → refresh function
type DirRefreshMap = Map<string, () => void>;

interface SelectionHandlers {
  onPointSelect: (path: string) => void;   // ctrl/cmd click – toggle one
  onRangeSelect: (path: string) => void;   // shift click – select range from anchor
  onPlainSelect: (path: string) => void;   // plain click – select only this
}

interface ContextMenuState {
  x: number;
  y: number;
  path: string;
  type: FileEntry["type"];
}

interface FileTreeNodeProps {
  name: string;
  path: string;
  type: "file" | "directory";
  depth: number;
  onSelectFile?: (path: string) => void;
  selected: boolean;
  selection: SelectionHandlers;
  selectedPaths: Set<string>;
  dirRefreshMap: DirRefreshMap;
  visiblePathsRef: MutableRefObject<string[]>;
  collapseVersion: number;
  onContextMenu: (x: number, y: number, path: string, type: FileEntry["type"]) => void;
  vmQuery: string;
  onUpload: (files: File[], destDir: string) => void;
}

function FileTreeNode({
  name, path, type, depth, onSelectFile,
  selected, selection, selectedPaths, dirRefreshMap, visiblePathsRef, collapseVersion,
  onContextMenu: onCtxMenu, vmQuery, onUpload,
}: FileTreeNodeProps) {
  const [expanded, setExpanded] = useState(false);

  // Collapse all folders when collapseVersion changes
  const prevCollapseRef = useRef(collapseVersion);
  if (prevCollapseRef.current !== collapseVersion) {
    prevCollapseRef.current = collapseVersion;
    if (expanded) setExpanded(false);
  }
  const [children, setChildren] = useState<FileEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [moving, setMoving] = useState(false);

  // Touch long-press opens the SAME context menu as desktop right-click
  // (Copy Path / Delete). Two things must both hold on iOS Safari:
  //   1. Native HTML5 drag must be off *for the touch gesture*. A `draggable`
  //      element hijacks a stationary long-press for WebKit's native drag,
  //      which fires `pointercancel` mid-hold (aborting our timer below) and
  //      surfaces the native selection/callout — so the menu never opened.
  //      We decide draggability per interaction from the live pointer type
  //      (`nativeDraggable` below), not from a one-time `matchMedia` check:
  //      that keeps native drag available for mouse/pen on hybrid devices and
  //      never goes stale when pointer capabilities change. Touch has no
  //      working HTML5 DnD to lose anyway.
  //   2. An explicit pointer timer opens the context menu at the touch point,
  //      and the ensuing click is suppressed so long-press does not also
  //      open/toggle/select the node.
  const longPressTimerRef = useRef<number | null>(null);
  const longPressTriggeredRef = useRef(false);
  // Start draggable (desktop default); each pointerdown re-derives this from
  // the actual pointer type, so a touch gesture drops draggability before its
  // long-press threshold while mouse/pen interactions keep it.
  const [nativeDraggable, setNativeDraggable] = useState(true);

  // Register this path in visible order during render
  visiblePathsRef.current.push(path);

  const loadChildren = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authFetch(`${API}/api/file/list?path=${encodeURIComponent(path)}${vmQuery}`);
      const data = await res.json();
      const sorted = (data.entries as FileEntry[]).sort((a, b) => {
        if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
      setChildren(sorted);
    } catch {
      setChildren([]);
    } finally {
      setLoading(false);
    }
  }, [path, vmQuery]);

  const refresh = useCallback(() => {
    if (expanded) {
      loadChildren();
    } else {
      setChildren(null);
    }
  }, [expanded, loadChildren]);

  const isDir = type === "directory";
  useEffect(() => {
    if (isDir && expanded) {
      dirRefreshMap.set(path, refresh);
      return () => { dirRefreshMap.delete(path); };
    }
  }, [isDir, expanded, path, refresh, dirRefreshMap]);

  const toggle = useCallback(async () => {
    if (!isDir) {
      onSelectFile?.(path);
      return;
    }
    if (expanded) {
      setExpanded(false);
      return;
    }
    if (children === null) {
      await loadChildren();
    }
    setExpanded(true);
  }, [isDir, expanded, children, path, onSelectFile, loadChildren]);

  const icon = isDir ? (expanded ? "\u25BE" : "\u25B8") : " ";

  const cancelLongPress = useCallback(() => {
    if (longPressTimerRef.current !== null) {
      window.clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
  }, []);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    // Re-derive draggability from this gesture's pointer type. Mouse/pen keep
    // native drag; touch drops it (before the long-press threshold below) so
    // WebKit can't steal the long-press. The next pointerdown restores the
    // right value, so this never goes stale across mixed input on one device.
    const isTouch = e.pointerType === "touch";
    setNativeDraggable(!isTouch);
    // Clear any stale click-suppression flag at the start of every gesture. A
    // completed touch long-press arms it (to swallow the trailing click), but
    // iOS/WebKit may never emit that click; without this reset a later
    // mouse/pen click would be wrongly swallowed. Non-touch gestures are never
    // long-presses, so clearing here is always safe.
    longPressTriggeredRef.current = false;
    if (!isTouch) return;
    // Capture the touch point now; the synthetic event is recycled before the
    // timer fires, so we anchor the menu at these coordinates.
    const { clientX, clientY } = e;
    cancelLongPress();
    longPressTimerRef.current = window.setTimeout(() => {
      longPressTriggeredRef.current = true;
      onCtxMenu(clientX, clientY, path, type);
    }, 500);
  }, [path, type, onCtxMenu, cancelLongPress]);

  const handleClick = useCallback((e: React.MouseEvent) => {
    // A completed long-press already opened the context menu; swallow the
    // trailing click so it doesn't also open the file / toggle the folder /
    // select the node.
    if (longPressTriggeredRef.current) {
      longPressTriggeredRef.current = false;
      e.preventDefault();
      return;
    }
    if (e.shiftKey) {
      e.preventDefault();
      selection.onRangeSelect(path);
    } else if (e.metaKey || e.ctrlKey) {
      e.preventDefault();
      selection.onPointSelect(path);
    } else if (isDir) {
      selection.onPlainSelect(path);
      toggle();
    } else {
      selection.onPlainSelect(path);
      onSelectFile?.(path);
    }
  }, [path, isDir, toggle, selection, onSelectFile]);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    onCtxMenu(e.clientX, e.clientY, path, type);
  }, [path, type, onCtxMenu]);

  const handleDragStart = useCallback((e: React.DragEvent) => {
    const paths = selectedPaths.has(path) ? Array.from(selectedPaths) : [path];
    e.dataTransfer.setData("application/json", JSON.stringify(paths));
    e.dataTransfer.effectAllowed = "move";
  }, [path, selectedPaths]);

  const destDir = isDir ? path : path.substring(0, path.lastIndexOf("/"));

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const isFiles = e.dataTransfer.types.includes("Files");
    e.dataTransfer.dropEffect = isFiles ? "copy" : "move";
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    // External files dragged from the OS file manager
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      onUpload(Array.from(e.dataTransfer.files), destDir);
      return;
    }
    // Internal move: payload is JSON list of source paths
    const payload = e.dataTransfer.getData("application/json");
    if (!payload) return;
    try {
      const sources: string[] = JSON.parse(payload);
      const valid = sources.filter(s => s !== path && !destDir.startsWith(s + "/"));
      if (valid.length === 0) return;
      setMoving(true);
      await authFetch(`${API}/api/file/move${vmQuery ? `?${vmQuery.slice(1)}` : ""}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sources: valid, dest_dir: destDir }),
      });
      const destRefresh = dirRefreshMap.get(destDir);
      if (destRefresh) destRefresh();
      const parentDirs = new Set(valid.map(s => s.substring(0, s.lastIndexOf("/"))));
      for (const dir of parentDirs) {
        const parentRefresh = dirRefreshMap.get(dir);
        if (parentRefresh) parentRefresh();
      }
    } catch (err) {
      console.error("Move failed:", err);
    } finally {
      setMoving(false);
    }
  }, [path, destDir, dirRefreshMap, vmQuery, onUpload]);

  return (
    <div>
      <div
        draggable={nativeDraggable}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        onContextMenu={handleContextMenu}
        onPointerDown={handlePointerDown}
        onPointerMove={(e) => { if (e.pointerType === "touch") cancelLongPress(); }}
        onPointerUp={(e) => { if (e.pointerType === "touch") cancelLongPress(); }}
        onPointerCancel={cancelLongPress}
        className={`flex items-center gap-1 px-2 py-0.5 text-sm truncate cursor-pointer select-none [-webkit-touch-callout:none] hover:bg-sol-base02 ${
          isDir ? "" : "text-sol-base0"
        } ${selected ? "bg-sol-base02 text-sol-base1" : ""} ${
          dragOver ? "bg-sol-base02 outline outline-1 outline-sol-blue" : ""
        }`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        <span className="w-3 text-center text-sol-base01 text-xs shrink-0">{icon}</span>
        <span className="truncate">{name}</span>
        {(loading || moving) && <span className="text-sol-base01 text-xs ml-1">...</span>}
      </div>
      {expanded && children && children.map((child) => (
        <FileTreeNode
          key={child.name}
          name={child.name}
          path={`${path}/${child.name}`}
          type={child.type}
          depth={depth + 1}
          onSelectFile={onSelectFile}
          selected={selectedPaths.has(`${path}/${child.name}`)}
          selection={selection}
          selectedPaths={selectedPaths}
          dirRefreshMap={dirRefreshMap}
          visiblePathsRef={visiblePathsRef}
          collapseVersion={collapseVersion}
          onContextMenu={onCtxMenu}
          vmQuery={vmQuery}
          onUpload={onUpload}
        />
      ))}
    </div>
  );
}

interface FileTreeProps {
  isLoggedIn: boolean;
  onSelectFile?: (path: string) => void;
  onDeleteFile?: (path: string) => void;
  vmName?: string | null;
  workDir?: string;
  refreshKey?: number;
}

export default function FileTree({ isLoggedIn, onSelectFile, onDeleteFile, vmName, workDir, refreshKey }: FileTreeProps) {
  const vmQuery = (vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "") + (workDir ? `&work_dir=${encodeURIComponent(workDir)}` : "");
  const [roots, setRoots] = useState<FileEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [collapseVersion, setCollapseVersion] = useState(0);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [ctxMenu, setCtxMenu] = useState<ContextMenuState | null>(null);
  const [copyPathPressed, setCopyPathPressed] = useState(false);
  const [copyPathStatus, setCopyPathStatus] = useState<"idle" | "success" | "error">("idle");
  const copyPathTimeoutRef = useRef<number | null>(null);
  // Bumped on every dismissal / reopen (new node) / unmount so a clipboard
  // promise or scheduled timeout that settles later can tell it's stale and
  // no-op instead of mutating a menu instance it no longer belongs to.
  const copyPathOpIdRef = useRef(0);
  const isMountedRef = useRef(true);
  const [deleteDialog, setDeleteDialog] = useState<{ path: string } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [rootDragOver, setRootDragOver] = useState(false);
  const [uploadDialog, setUploadDialog] = useState<{ dir: string } | null>(null);
  const [newFileDialog, setNewFileDialog] = useState<{ path: string } | null>(null);
  const [creating, setCreating] = useState(false);
  const [overwriteDialog, setOverwriteDialog] = useState<{ files: File[]; destDir: string; names: string[] } | null>(null);
  const dirRefreshMapRef = useRef<DirRefreshMap>(new Map());
  const anchorRef = useRef<string | null>(null);
  const visiblePathsRef = useRef<string[]>([]);
  const lastUploadDirRef = useRef<string | null>(null);
  const rootPath = workDir || ".";
  // Clear visible paths at the start of each render so nodes re-register
  visiblePathsRef.current = [];

  const loadRoot = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authFetch(`${API}/api/file/list?path=${encodeURIComponent(rootPath)}${vmQuery}`);
      const data = await res.json();
      const sorted = (data.entries as FileEntry[]).sort((a, b) => {
        if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
      setRoots(sorted);
    } catch {
      setRoots([]);
    } finally {
      setLoading(false);
    }
  }, [rootPath, vmQuery]);

  useEffect(() => {
    dirRefreshMapRef.current.set(rootPath, loadRoot);
    return () => { dirRefreshMapRef.current.delete(rootPath); };
  }, [rootPath, loadRoot]);

  // Plain click: select only this item, set anchor
  const onPlainSelect = useCallback((path: string) => {
    anchorRef.current = path;
    setSelectedPaths(new Set([path]));
  }, []);

  // Ctrl/Cmd click: toggle one item, update anchor
  const onPointSelect = useCallback((path: string) => {
    anchorRef.current = path;
    setSelectedPaths(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  // Shift click: range select from anchor to target
  const onRangeSelect = useCallback((path: string) => {
    const anchor = anchorRef.current;
    if (!anchor) {
      anchorRef.current = path;
      setSelectedPaths(new Set([path]));
      return;
    }
    const visible = visiblePathsRef.current;
    const anchorIdx = visible.indexOf(anchor);
    const targetIdx = visible.indexOf(path);
    if (anchorIdx === -1 || targetIdx === -1) {
      setSelectedPaths(new Set([path]));
      return;
    }
    const start = Math.min(anchorIdx, targetIdx);
    const end = Math.max(anchorIdx, targetIdx);
    setSelectedPaths(new Set(visible.slice(start, end + 1)));
  }, []);

  const selection: SelectionHandlers = { onPlainSelect, onPointSelect, onRangeSelect };

  // Reload when vmName changes
  useEffect(() => {
    if (isLoggedIn) {
      loadRoot();
    }
  }, [vmQuery]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0 || !isLoggedIn) return;
    if (dirRefreshMapRef.current.size > 5) {
      setCollapseVersion(v => v + 1);
      loadRoot();
      return;
    }
    for (const refresh of dirRefreshMapRef.current.values()) refresh();
  }, [refreshKey, isLoggedIn, loadRoot]);

  if (isLoggedIn && roots === null && !loading) {
    loadRoot();
  }

  const uploadInputRef = useRef<HTMLInputElement>(null);

  const performUpload = useCallback(async (files: File[], destDir: string) => {
    if (files.length === 0) return;
    setUploading(true);
    try {
      for (const file of files) {
        if (file.size > MAX_UPLOAD_BYTES) {
          alert(`${file.name} exceeds 50 MB limit`);
          continue;
        }
        const form = new FormData();
        form.append("file", file);
        form.append("dest_dir", destDir);
        if (vmName) form.append("vm_name", vmName);
        if (workDir) form.append("work_dir", workDir);
        const res = await authFetch(`${API}/api/file/upload`, { method: "POST", body: form });
        if (!res.ok) {
          const detail = await res.text().catch(() => "");
          alert(`Upload failed for ${file.name}: ${detail || res.status}`);
        }
      }
    } finally {
      setUploading(false);
    }
    lastUploadDirRef.current = destDir;
    // Refresh the destination dir if it's expanded; otherwise refresh root.
    const refresh = dirRefreshMapRef.current.get(destDir) ?? dirRefreshMapRef.current.get(rootPath);
    if (refresh) refresh();
  }, [vmName, workDir, rootPath]);

  const uploadFiles = useCallback(async (files: File[], destDir: string) => {
    if (files.length === 0) return;
    // Detect same-name collisions in the target dir before overwriting.
    let existingNames = new Set<string>();
    try {
      const res = await authFetch(`${API}/api/file/list?path=${encodeURIComponent(destDir)}${vmQuery}`);
      if (res.ok) {
        const data = await res.json();
        existingNames = new Set((data.entries as FileEntry[]).map(e => e.name));
      }
    } catch {
      // Target dir may not exist yet (parents created on upload); treat as no collisions.
    }
    const collisions = files.filter(f => existingNames.has(f.name)).map(f => f.name);
    if (collisions.length > 0) {
      setOverwriteDialog({ files, destDir, names: collisions });
      return;
    }
    await performUpload(files, destDir);
  }, [vmQuery, performUpload]);

  const openUploadDialog = useCallback(() => {
    // Default target dir: last-used → single selected dir → root
    let defaultDir = lastUploadDirRef.current || rootPath;
    if (selectedPaths.size === 1) {
      defaultDir = Array.from(selectedPaths)[0];
    }
    setUploadDialog({ dir: defaultDir });
  }, [rootPath, selectedPaths]);

  const openNewFileDialog = useCallback(() => {
    // Default parent dir: same heuristic as upload (last-used → single selected dir → root)
    let defaultDir = lastUploadDirRef.current || rootPath;
    if (selectedPaths.size === 1) {
      defaultDir = Array.from(selectedPaths)[0];
    }
    setNewFileDialog({ path: `${defaultDir}/` });
  }, [rootPath, selectedPaths]);

  const createNewFile = useCallback(async (path: string) => {
    const trimmed = path.trim();
    if (!trimmed || trimmed.endsWith("/")) return;
    setCreating(true);
    try {
      const res = await authFetch(`${API}/api/file/touch${vmQuery ? `?${vmQuery.slice(1)}` : ""}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: trimmed }),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        alert(`Create failed for ${trimmed}: ${detail || res.status}`);
        return;
      }
      setNewFileDialog(null);
      const parentDir = trimmed.includes("/") ? trimmed.substring(0, trimmed.lastIndexOf("/")) : rootPath;
      lastUploadDirRef.current = parentDir;
      const refresh = dirRefreshMapRef.current.get(parentDir) ?? dirRefreshMapRef.current.get(rootPath);
      if (refresh) refresh();
      onSelectFile?.(trimmed);
    } finally {
      setCreating(false);
    }
  }, [vmQuery, rootPath, onSelectFile]);

  const handleUploadInputChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (files.length === 0) return;
    const destDir = uploadDialog?.dir.trim() || rootPath;
    setUploadDialog(null);
    await uploadFiles(files, destDir);
  }, [uploadDialog, rootPath, uploadFiles]);

  const handleBackgroundClick = useCallback((e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      setSelectedPaths(new Set());
      anchorRef.current = null;
    }
  }, []);

  const clearCopyPathFeedback = useCallback(() => {
    // Invalidate whatever copy request is in flight: its .then/.catch (and any
    // timeout it schedules) will see a stale opId and no-op instead of
    // mutating this now-dismissed/reopened menu instance.
    copyPathOpIdRef.current += 1;
    if (copyPathTimeoutRef.current !== null) {
      window.clearTimeout(copyPathTimeoutRef.current);
      copyPathTimeoutRef.current = null;
    }
    setCopyPathStatus("idle");
    setCopyPathPressed(false);
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      copyPathOpIdRef.current += 1;
      if (copyPathTimeoutRef.current !== null) window.clearTimeout(copyPathTimeoutRef.current);
    };
  }, []);

  const handleNodeContextMenu = useCallback((x: number, y: number, path: string, type: FileEntry["type"]) => {
    clearCopyPathFeedback();
    setCtxMenu({ x, y, path, type });
  }, [clearCopyPathFeedback]);

  const dismissCtxMenu = useCallback(() => {
    clearCopyPathFeedback();
    setCtxMenu(null);
  }, [clearCopyPathFeedback]);

  const copyPath = useCallback(() => {
    if (!ctxMenu) return;
    const cleanPath = ctxMenu.path.startsWith("./") ? ctxMenu.path.slice(2) : ctxMenu.path;
    // Snapshot the operation id this request belongs to; any dismissal /
    // reopen / unmount bumps copyPathOpIdRef past it, so a late-settling
    // promise or its scheduled timeout can detect it's stale below.
    const opId = ++copyPathOpIdRef.current;
    const isStale = () => !isMountedRef.current || copyPathOpIdRef.current !== opId;
    Promise.resolve(navigator.clipboard.writeText(cleanPath)).then(() => {
      if (isStale()) return;
      setCopyPathStatus("success");
      copyPathTimeoutRef.current = window.setTimeout(() => {
        copyPathTimeoutRef.current = null;
        if (isStale()) return;
        setCopyPathStatus("idle");
        setCtxMenu(null);
      }, 700);
    }).catch(() => {
      if (isStale()) return;
      setCopyPathStatus("error");
      copyPathTimeoutRef.current = window.setTimeout(() => {
        copyPathTimeoutRef.current = null;
        if (isStale()) return;
        setCopyPathStatus("idle");
      }, 1200);
    });
  }, [ctxMenu]);

  const openDeleteDialog = useCallback(() => {
    if (!ctxMenu || ctxMenu.type !== "file") return;
    setDeleteError(null);
    setDeleteDialog({ path: ctxMenu.path });
    dismissCtxMenu();
  }, [ctxMenu, dismissCtxMenu]);

  const dismissDeleteDialog = useCallback(() => {
    if (!deleting) {
      setDeleteDialog(null);
      setDeleteError(null);
    }
  }, [deleting]);

  const deleteFile = useCallback(async () => {
    if (!deleteDialog || deleting) return;
    const path = deleteDialog.path;
    setDeleting(true);
    setDeleteError(null);
    try {
      const res = await authFetch(`${API}/api/file/delete${vmQuery ? `?${vmQuery.slice(1)}` : ""}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setDeleteError(data?.detail || `Delete failed (${res.status})`);
        return;
      }
      setSelectedPaths(prev => {
        const next = new Set(prev);
        next.delete(path);
        return next;
      });
      if (anchorRef.current === path) anchorRef.current = null;
      const parentDir = path.includes("/") ? path.substring(0, path.lastIndexOf("/")) || rootPath : rootPath;
      const refresh = dirRefreshMapRef.current.get(parentDir) ?? dirRefreshMapRef.current.get(rootPath);
      if (refresh) refresh();
      setDeleteDialog(null);
      onDeleteFile?.(path);
    } catch {
      setDeleteError("Delete failed. Please try again.");
    } finally {
      setDeleting(false);
    }
  }, [deleteDialog, deleting, vmQuery, rootPath, onDeleteFile]);

  useEffect(() => {
    if (!ctxMenu && !deleteDialog) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismissCtxMenu();
      if (e.key === "Escape") dismissDeleteDialog();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [ctxMenu, deleteDialog, dismissCtxMenu, dismissDeleteDialog]);

  return (
    <div className="h-full bg-sol-base03 flex flex-col">
      <div className="flex items-center gap-3 px-2 py-1.5 sm:py-1 border-b border-sol-base02 shrink-0">
        {workDir && <span className="text-sm sm:text-xs text-sol-base01 truncate flex-1" title={workDir}>{workDir}</span>}
        {!workDir && <span className="flex-1" />}
        <input ref={uploadInputRef} type="file" multiple className="hidden" onChange={handleUploadInputChange} />
        <button
          onClick={openNewFileDialog}
          disabled={creating}
          className="text-sol-base01 hover:text-sol-base1 cursor-pointer w-6 h-6 sm:w-4 sm:h-4 flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
          title="New file"
        >
          <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 16 16" fill="currentColor">
            <path fillRule="evenodd" d="M3 1h7l3 3v11H3V1zm4 5h2v3h3v2H9v3H7v-3H4V9h3V6z" />
          </svg>
        </button>
        <button
          onClick={openUploadDialog}
          disabled={uploading}
          className="text-sol-base01 hover:text-sol-base1 cursor-pointer w-6 h-6 sm:w-4 sm:h-4 flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
          title="Upload file(s)"
        >
          <svg className={`w-5 h-5 sm:w-3.5 sm:h-3.5 ${uploading ? "animate-bounce" : ""}`} viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1l4 4H9v5H7V5H4L8 1zM2 13h12v1.5H2V13z" />
          </svg>
        </button>
        <button
          onClick={() => { if (dirRefreshMapRef.current.size > 5) { setCollapseVersion(v => v + 1); loadRoot(); } else { for (const refresh of dirRefreshMapRef.current.values()) refresh(); } }}
          className="text-sol-base01 hover:text-sol-base1 cursor-pointer w-6 h-6 sm:w-4 sm:h-4 flex items-center justify-center"
          title="Refresh file tree"
        >
          <svg className={`w-5 h-5 sm:w-3.5 sm:h-3.5 ${loading ? "animate-spin" : ""}`} viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1a7 7 0 0 1 7 7h-1.5A5.5 5.5 0 0 0 8 2.5V5L4.5 2 8 -1v2zm0 14a7 7 0 0 1-7-7h1.5A5.5 5.5 0 0 0 8 13.5V11l3.5 3L8 17v-2z" />
          </svg>
        </button>
        <button
          onClick={() => setCollapseVersion(v => v + 1)}
          className="text-sol-base01 hover:text-sol-base1 cursor-pointer w-6 h-6 sm:w-4 sm:h-4 flex items-center justify-center"
          title="Collapse all folders"
        >
          <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 16 16" fill="currentColor">
            <path d="M1 3.5h14v1H1zM3 7h10v1H3zM5 10.5h6v1H5z" />
          </svg>
        </button>
      </div>
      <div
        className={`flex-1 overflow-y-auto py-1 ${rootDragOver ? "outline outline-1 -outline-offset-1 outline-sol-blue bg-sol-base02/40" : ""}`}
        onClick={handleBackgroundClick}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes("Files")) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
          setRootDragOver(true);
        }}
        onDragLeave={(e) => {
          if (e.currentTarget === e.target) setRootDragOver(false);
        }}
        onDrop={(e) => {
          if (!e.dataTransfer.files || e.dataTransfer.files.length === 0) return;
          e.preventDefault();
          setRootDragOver(false);
          uploadFiles(Array.from(e.dataTransfer.files), rootPath);
        }}
      >
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic text-sm p-3">Sign in to browse files</p>
        ) : loading && roots === null ? (
          <p className="text-sol-base01 italic text-sm p-3">Loading...</p>
        ) : roots && roots.length === 0 ? (
          <p className="text-sol-base01 italic text-sm p-3">Empty directory</p>
        ) : roots ? (
          roots.map((entry) => (
            <FileTreeNode
              key={entry.name}
              name={entry.name}
              path={`${rootPath}/${entry.name}`}
              type={entry.type}
              depth={0}
              onSelectFile={onSelectFile}
              selected={selectedPaths.has(`${rootPath}/${entry.name}`)}
              selection={selection}
              selectedPaths={selectedPaths}
              dirRefreshMap={dirRefreshMapRef.current}
              visiblePathsRef={visiblePathsRef}
              collapseVersion={collapseVersion}
              onContextMenu={handleNodeContextMenu}
              vmQuery={vmQuery}
              onUpload={uploadFiles}
            />
          ))
        ) : null}
      </div>
      {uploadDialog && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={() => setUploadDialog(null)}
        >
          <div
            className="w-full max-w-md bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-4 py-3 border-b border-sol-base02">
              <div className="text-sol-base1 text-sm font-semibold">Upload files</div>
              <div className="text-sol-base01 text-xs mt-1">
                Files will be uploaded to the target directory. Missing parents are created automatically.
              </div>
            </div>
            <div className="px-4 py-3 flex flex-col gap-2">
              <label className="text-xs text-sol-base01">Target directory</label>
              <input
                type="text"
                autoFocus
                value={uploadDialog.dir}
                onChange={(e) => setUploadDialog({ dir: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") uploadInputRef.current?.click();
                  if (e.key === "Escape") setUploadDialog(null);
                }}
                placeholder={rootPath}
                className="px-2 py-1 bg-sol-base02 text-sol-base1 text-sm rounded border border-sol-base01 focus:outline-none focus:border-sol-blue"
              />
              <div className="flex gap-2 justify-end mt-2">
                <button
                  onClick={() => setUploadDialog(null)}
                  className="px-3 py-1.5 rounded text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={() => uploadInputRef.current?.click()}
                  disabled={uploading}
                  className="px-3 py-1.5 rounded text-sm bg-sol-blue/20 text-sol-blue hover:bg-sol-blue/30 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border border-sol-blue/40"
                >
                  Choose files...
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
      {newFileDialog && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={() => setNewFileDialog(null)}
        >
          <div
            className="w-full max-w-md bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-4 py-3 border-b border-sol-base02">
              <div className="text-sol-base1 text-sm font-semibold">New file</div>
              <div className="text-sol-base01 text-xs mt-1">
                An empty file is created at this path. Creating an existing path leaves the file untouched.
              </div>
            </div>
            <div className="px-4 py-3 flex flex-col gap-2">
              <label className="text-xs text-sol-base01">File path</label>
              <input
                type="text"
                autoFocus
                value={newFileDialog.path}
                onChange={(e) => setNewFileDialog({ path: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") createNewFile(newFileDialog.path);
                  if (e.key === "Escape") setNewFileDialog(null);
                }}
                placeholder={`${rootPath}/new-file.md`}
                className="px-2 py-1 bg-sol-base02 text-sol-base1 text-sm rounded border border-sol-base01 focus:outline-none focus:border-sol-blue"
              />
              <div className="flex gap-2 justify-end mt-2">
                <button
                  onClick={() => setNewFileDialog(null)}
                  className="px-3 py-1.5 rounded text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={() => createNewFile(newFileDialog.path)}
                  disabled={creating || !newFileDialog.path.trim() || newFileDialog.path.trim().endsWith("/")}
                  className="px-3 py-1.5 rounded text-sm bg-sol-blue/20 text-sol-blue hover:bg-sol-blue/30 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border border-sol-blue/40"
                >
                  Create
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
      {overwriteDialog && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={() => setOverwriteDialog(null)}
        >
          <div
            className="w-full max-w-md bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-4 py-3 border-b border-sol-base02">
              <div className="text-sol-base1 text-sm font-semibold">Overwrite existing file{overwriteDialog.names.length > 1 ? "s" : ""}?</div>
              <div className="text-sol-base01 text-xs mt-1">
                {overwriteDialog.names.length > 1
                  ? `${overwriteDialog.names.length} files already exist in the target directory and will be replaced:`
                  : "A file with the same name already exists in the target directory and will be replaced:"}
              </div>
            </div>
            <div className="px-4 py-3 flex flex-col gap-2">
              <div className="max-h-40 overflow-y-auto flex flex-col gap-1">
                {overwriteDialog.names.map((name) => (
                  <div key={name} className="text-sm text-sol-base1 font-mono truncate">{name}</div>
                ))}
              </div>
              <div className="flex gap-2 justify-end mt-2">
                <button
                  onClick={() => setOverwriteDialog(null)}
                  className="px-3 py-1.5 rounded text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    const { files, destDir } = overwriteDialog;
                    setOverwriteDialog(null);
                    performUpload(files, destDir);
                  }}
                  disabled={uploading}
                  className="px-3 py-1.5 rounded text-sm bg-sol-red/20 text-sol-red hover:bg-sol-red/30 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border border-sol-red/40"
                >
                  Overwrite
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
      {deleteDialog && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={dismissDeleteDialog}
        >
          <div
            className="w-full max-w-md bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-file-title"
          >
            <div className="px-4 py-3 border-b border-sol-base02">
              <div id="delete-file-title" className="text-sol-base1 text-sm font-semibold">Delete file?</div>
              <div className="text-sol-base01 text-xs mt-1">This permanently removes the file.</div>
            </div>
            <div className="px-4 py-3 flex flex-col gap-3">
              <div className="text-sm text-sol-base1 font-mono break-all">{deleteDialog.path}</div>
              {deleteError && <div className="text-xs text-sol-red bg-sol-red/10 border border-sol-red/30 rounded px-2 py-1.5">{deleteError}</div>}
              <div className="flex gap-2 justify-end">
                <button
                  onClick={dismissDeleteDialog}
                  disabled={deleting}
                  className="px-3 py-1.5 rounded text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={deleteFile}
                  disabled={deleting}
                  className="px-3 py-1.5 rounded text-sm bg-sol-red/20 text-sol-red hover:bg-sol-red/30 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border border-sol-red/40"
                >
                  {deleting ? "Deleting..." : "Delete"}
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
      {ctxMenu && createPortal(
        <>
          <div className="fixed inset-0 z-40" onClick={dismissCtxMenu} onContextMenu={(e) => { e.preventDefault(); dismissCtxMenu(); }} />
          <div
            className="fixed z-50 bg-sol-base02 border border-sol-base01 rounded shadow-lg py-1 min-w-[120px]"
            style={{ left: ctxMenu.x, top: ctxMenu.y }}
          >
            <button
              className={`w-full text-left px-3 py-1 text-xs cursor-pointer transition-colors disabled:cursor-default ${
                copyPathStatus === "success"
                  ? "text-sol-green"
                  : copyPathStatus === "error"
                  ? "text-sol-red"
                  : `text-sol-base1 ${copyPathPressed ? "bg-sol-base03" : "hover:bg-sol-base03"}`
              }`}
              onClick={copyPath}
              onPointerDown={() => setCopyPathPressed(true)}
              onPointerUp={() => setCopyPathPressed(false)}
              onPointerCancel={() => setCopyPathPressed(false)}
              onPointerLeave={() => setCopyPathPressed(false)}
              disabled={copyPathStatus !== "idle"}
              aria-live="polite"
              aria-label={copyPathStatus === "success" ? "Copied path" : copyPathStatus === "error" ? "Copy path failed" : "Copy Path"}
            >
              {copyPathStatus === "success" ? "Copied ✓" : copyPathStatus === "error" ? "Copy failed" : "Copy Path"}
            </button>
            {ctxMenu.type === "file" && (
              <button
                className="w-full text-left px-3 py-1 text-xs text-sol-red hover:bg-sol-base03 cursor-pointer"
                onClick={openDeleteDialog}
              >
                Delete
              </button>
            )}
          </div>
        </>,
        document.body
      )}
    </div>
  );
}
