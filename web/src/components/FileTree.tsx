import { useState, useCallback, useRef, useEffect, MutableRefObject } from "react";
import { API, authFetch } from "../api";

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
}

function FileTreeNode({
  name, path, type, depth, onSelectFile,
  selected, selection, selectedPaths, dirRefreshMap, visiblePathsRef, collapseVersion,
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
      const res = await authFetch(`${API}/api/file/list?path=${encodeURIComponent(path)}`);
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
  }, [path]);

  const refresh = useCallback(() => {
    setChildren(null);
    if (expanded) {
      loadChildren();
    }
  }, [expanded, loadChildren]);

  const isDir = type === "directory";
  useEffect(() => {
    if (isDir) {
      dirRefreshMap.set(path, refresh);
      return () => { dirRefreshMap.delete(path); };
    }
  }, [isDir, path, refresh, dirRefreshMap]);

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
      await authFetch(`${API}/api/file/move`, {
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
        className={`flex items-center gap-1 px-2 py-0.5 text-xs truncate cursor-pointer hover:bg-sol-base02 ${
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
        />
      ))}
    </div>
  );
}

interface FileTreeProps {
  isLoggedIn: boolean;
  onSelectFile?: (path: string) => void;
}

export default function FileTree({ isLoggedIn, onSelectFile }: FileTreeProps) {
  const [roots, setRoots] = useState<FileEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [collapseVersion, setCollapseVersion] = useState(0);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const dirRefreshMapRef = useRef<DirRefreshMap>(new Map());
  const anchorRef = useRef<string | null>(null);
  const visiblePathsRef = useRef<string[]>([]);
  const rootPath = ".";

  // Clear visible paths at the start of each render so nodes re-register
  visiblePathsRef.current = [];

  const loadRoot = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authFetch(`${API}/api/file/list?path=${encodeURIComponent(rootPath)}`);
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
  }, [rootPath]);

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

  if (isLoggedIn && roots === null && !loading) {
    loadRoot();
  }

  const handleBackgroundClick = useCallback((e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      setSelectedPaths(new Set());
      anchorRef.current = null;
    }
  }, []);

  return (
    <div className="h-full bg-sol-base03 flex flex-col">
      <div className="flex items-center justify-end px-2 py-1 border-b border-sol-base02 shrink-0">
        <button
          onClick={() => setCollapseVersion(v => v + 1)}
          className="text-sol-base01 hover:text-sol-base1 cursor-pointer w-4 h-4 flex items-center justify-center"
          title="Collapse all folders"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
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
            />
          ))
        ) : null}
      </div>
    </div>
  );
}
