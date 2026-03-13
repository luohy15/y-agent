import { useEffect, useState } from "react";
import { PatchDiff } from "@pierre/diffs/react";
import { API, authFetch } from "../api";

interface DiffViewerProps {
  filePath: string;
  vmName?: string | null;
  workDir?: string;
}

export default function DiffViewer({ filePath, vmName, workDir }: DiffViewerProps) {
  const [diff, setDiff] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const vmQuery = (vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "") + (workDir ? `&work_dir=${encodeURIComponent(workDir)}` : "");

  useEffect(() => {
    setLoading(true);
    setError(null);
    setDiff(null);
    authFetch(`${API}/api/git/diff?path=${encodeURIComponent(filePath)}${vmQuery}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch diff");
        return res.json();
      })
      .then((data) => {
        setDiff(data.diff || "");
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [filePath, vmQuery]);

  if (loading) {
    return <p className="text-sol-base01 italic text-sm p-3">Loading diff...</p>;
  }
  if (error) {
    return <p className="text-sol-red text-sm p-3">{error}</p>;
  }
  if (!diff) {
    return <p className="text-sol-base01 text-sm p-3">No changes</p>;
  }

  return (
    <div className="h-full overflow-auto">
      <PatchDiff patch={diff} options={{ theme: "solarized-dark" }} />
    </div>
  );
}
