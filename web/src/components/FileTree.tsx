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
  onContextMenu: (e: React.MouseEvent, path: string) => void;
  vmQuery: string;
}

function FileTreeNode({
  name, path, type, depth, onSelectFile,
  selected, selection, selectedPaths, dirRefreshMap, visiblePathsRef, collapseVersion,
  onContextMenu: onCtxMenu, vmQuery,
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

  const handleClick = useCallback((e: React.MouseEvent) => {
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
    onCtxMenu(e, path);
  }, [path, onCtxMenu]);

  const handleDragStart = useCallback((e: React.DragEvent) => {
    const paths = selectedPaths.has(path) ? Array.from(selectedPaths) : [path];
    e.dataTransfer.setData("application/json", JSON.stringify(paths));
    e.dataTransfer.effectAllowed = "move";
  }, [path, selectedPaths]);

  const destDir = isDir ? path : path.substring(0, path.lastIndexOf("/"));

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    try {
      const sources: string[] = JSON.parse(e.dataTransfer.getData("application/json"));
      const valid = sources.filter(s => s !== path && !destDir.startsWith(s + "/"));
      if (valid.length === 0) return;
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
    }
  }, [path, destDir, dirRefreshMap]);

  return (
    <div>
      <div
        draggable
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        onContextMenu={handleContextMenu}
        className={`flex items-center gap-1 px-2 py-0.5 text-sm truncate cursor-pointer hover:bg-sol-base02 ${
          isDir ? "" : "text-sol-base0"
        } ${selected ? "bg-sol-base02 text-sol-base1" : ""} ${
          dragOver ? "bg-sol-base02 outline outline-1 outline-sol-blue" : ""
        }`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        <span className="w-3 text-center text-sol-base01 text-xs shrink-0">{icon}</span>
        <span className="truncate">{name}</span>
        {loading && <span className="text-sol-base01 text-xs ml-1">...</span>}
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
        />
      ))}
    </div>
  );
}

interface FileTreeProps {
  isLoggedIn: boolean;
  onSelectFile?: (path: string) => void;
  vmName?: string | null;
  workDir?: string;
}

export default function FileTree({ isLoggedIn, onSelectFile, vmName, workDir }: FileTreeProps) {
  const vmQuery = vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "";
  const [roots, setRoots] = useState<FileEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [collapseVersion, setCollapseVersion] = useState(0);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [ctxMenu, setCtxMenu] = useState<ContextMenuState | null>(null);
  const dirRefreshMapRef = useRef<DirRefreshMap>(new Map());
  const anchorRef = useRef<string | null>(null);
  const visiblePathsRef = useRef<string[]>([]);
  const rootPath = ".";
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

  if (isLoggedIn && roots === null && !loading) {
    loadRoot();
  }

  const uploadInputRef = useRef<HTMLInputElement>(null);

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (files.length === 0) return;

    // Upload into the root directory by default
    const destDir = ".";

    for (const file of files) {
      if (file.size > MAX_UPLOAD_BYTES) {
        alert(`${file.name} exceeds 50 MB limit`);
        continue;
      }
      const form = new FormData();
      form.append("file", file);
      form.append("dest_dir", destDir);
      if (vmName) form.append("vm_name", vmName);
      await authFetch(`${API}/api/file/upload`, { method: "POST", body: form });
    }

    // Refresh affected directories
    const refresh = dirRefreshMapRef.current.get(destDir) ?? dirRefreshMapRef.current.get(".");
    if (refresh) refresh();
  }, [vmName]);

  const handleBackgroundClick = useCallback((e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      setSelectedPaths(new Set());
      anchorRef.current = null;
    }
  }, []);

  const handleNodeContextMenu = useCallback((e: React.MouseEvent, path: string) => {
    setCtxMenu({ x: e.clientX, y: e.clientY, path });
  }, []);

  const dismissCtxMenu = useCallback(() => setCtxMenu(null), []);

  const copyPath = useCallback(() => {
    if (!ctxMenu) return;
    const cleanPath = ctxMenu.path.startsWith("./") ? ctxMenu.path.slice(2) : ctxMenu.path;
    navigator.clipboard.writeText(cleanPath);
    setCtxMenu(null);
  }, [ctxMenu]);

  useEffect(() => {
    if (!ctxMenu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setCtxMenu(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [ctxMenu]);

  return (
    <div className="h-full bg-sol-base03 flex flex-col">
      <div className="flex items-center gap-3 px-2 py-1.5 sm:py-1 border-b border-sol-base02 shrink-0">
        {workDir && <span className="text-sm sm:text-xs text-sol-base01 truncate flex-1" title={workDir}>{workDir}</span>}
        {!workDir && <span className="flex-1" />}
        <input ref={uploadInputRef} type="file" multiple className="hidden" onChange={handleUpload} />
        <button
          onClick={() => uploadInputRef.current?.click()}
          className="text-sol-base01 hover:text-sol-base1 cursor-pointer w-6 h-6 sm:w-4 sm:h-4 flex items-center justify-center"
          title="Upload file(s)"
        >
          <svg className="w-5 h-5 sm:w-3.5 sm:h-3.5" viewBox="0 0 16 16" fill="currentColor">
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
      <div className="flex-1 overflow-y-auto py-1" onClick={handleBackgroundClick}>
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
                />
          ))
        ) : null}
      </div>
      {ctxMenu && createPortal(
        <>
          <div className="fixed inset-0 z-40" onClick={dismissCtxMenu} onContextMenu={(e) => { e.preventDefault(); dismissCtxMenu(); }} />
          <div
            className="fixed z-50 bg-sol-base02 border border-sol-base01 rounded shadow-lg py-1 min-w-[120px]"
            style={{ left: ctxMenu.x, top: ctxMenu.y }}
          >
            <button
              className="w-full text-left px-3 py-1 text-xs text-sol-base1 hover:bg-sol-base03 cursor-pointer"
              onClick={copyPath}
            >
              Copy Path
            </button>
          </div>
        </>,
        document.body
      )}
    </div>
  );
}
