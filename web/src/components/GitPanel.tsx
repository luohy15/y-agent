import { useEffect, useState, useCallback } from "react";
import { API, authFetch } from "../api";

interface GitFile {
  status: string;
  path: string;
}

interface GitPanelProps {
  isLoggedIn: boolean;
  vmName?: string | null;
  workDir?: string;
  onSelectFile: (path: string) => void;
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  M: { label: "M", color: "text-sol-yellow" },
  A: { label: "A", color: "text-sol-green" },
  D: { label: "D", color: "text-sol-red" },
  R: { label: "R", color: "text-sol-blue" },
  C: { label: "C", color: "text-sol-cyan" },
  "?": { label: "U", color: "text-sol-base01" },
  "??": { label: "U", color: "text-sol-base01" },
};

function getStatusInfo(status: string) {
  return STATUS_LABELS[status] || { label: status, color: "text-sol-base0" };
}

function getFileName(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash >= 0 ? path.slice(slash + 1) : path;
}

function getDirName(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash >= 0 ? path.slice(0, slash) : "";
}

export default function GitPanel({ isLoggedIn, vmName, workDir, onSelectFile }: GitPanelProps) {
  const [files, setFiles] = useState<GitFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const vmQuery = (vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "") + (workDir ? `&work_dir=${encodeURIComponent(workDir)}` : "");

  const refresh = useCallback(() => {
    if (!isLoggedIn) return;
    setLoading(true);
    setError(null);
    authFetch(`${API}/api/git/status?_=1${vmQuery}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch git status");
        return res.json();
      })
      .then((data) => {
        setFiles(data.files || []);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [isLoggedIn, vmQuery]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-sol-base02 shrink-0">
        <span className="text-xs font-semibold text-sol-base1 uppercase tracking-wider">Source Control</span>
        <button
          onClick={refresh}
          className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5"
          title="Refresh"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1a7 7 0 0 1 7 7h-1.5A5.5 5.5 0 0 0 8 2.5V5L4.5 2 8 -1v2zm0 14a7 7 0 0 1-7-7h1.5A5.5 5.5 0 0 0 8 13.5V11l3.5 3L8 17v-2z" />
          </svg>
        </button>
      </div>

      {/* File list */}
      <div className="flex-1 overflow-y-auto">
        {loading && files.length === 0 && (
          <p className="text-sol-base01 italic text-xs p-3">Loading...</p>
        )}
        {error && (
          <p className="text-sol-red text-xs p-3">{error}</p>
        )}
        {!loading && !error && files.length === 0 && (
          <p className="text-sol-base01 text-xs p-3">No changes</p>
        )}
        {files.map((file) => {
          const info = getStatusInfo(file.status);
          const dir = getDirName(file.path);
          return (
            <button
              key={file.path}
              onClick={() => onSelectFile(file.path)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-sol-base02 cursor-pointer group"
              title={file.path}
            >
              <span className={`text-xs font-mono font-bold shrink-0 w-4 text-center ${info.color}`}>
                {info.label}
              </span>
              <span className="text-sm text-sol-base1 truncate">
                {getFileName(file.path)}
              </span>
              {dir && (
                <span className="text-xs text-sol-base01 truncate ml-auto shrink-0">
                  {dir}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
