import { useEffect, useRef, useState } from "react";
import { API, authFetch } from "../api";

interface LinkActionDialogProps {
  open: boolean;
  url: string | null;
  status?: string | null;
  onClose: () => void;
  onDownloaded?: () => void;
}

const STATUS_HINT: Record<string, string> = {
  pending: "A download is already queued for this URL.",
  failed: "Previous download failed. You can retry.",
};

export default function LinkActionDialog({ open, url, status, onClose, onDownloaded }: LinkActionDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setBusy(false);
    setError(null);
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open || !url) return null;

  const handleDownload = async () => {
    if (!url || busy) return;
    setBusy(true);
    setError(null);
    try {
      const createRes = await authFetch(`${API}/api/link`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, title: url, timestamp: Date.now() }),
      });
      if (!createRes.ok) throw new Error("Failed to add link");
      const downloadRes = await authFetch(`${API}/api/link/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ urls: [url] }),
      });
      if (!downloadRes.ok) throw new Error("Failed to trigger download");
      onDownloaded?.();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleOpenExternal = () => {
    window.open(url, "_blank", "noopener,noreferrer");
    onClose();
  };

  const hint = status ? STATUS_HINT[status] : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        className="w-full max-w-md bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-4 py-3 border-b border-sol-base02">
          <div className="text-sol-base1 text-sm font-semibold">External link</div>
          <div className="text-sol-base01 text-xs mt-1 break-all">{url}</div>
          {hint && <div className="text-sol-yellow text-xs mt-2">{hint}</div>}
        </div>
        {error && (
          <div className="px-4 py-2 text-xs text-sol-red border-b border-sol-base02">{error}</div>
        )}
        <div className="flex flex-col gap-2 px-4 py-3">
          <button
            onClick={handleDownload}
            disabled={busy}
            className="w-full px-3 py-1.5 rounded text-sm bg-sol-blue/20 text-sol-blue hover:bg-sol-blue/30 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border border-sol-blue/40 text-left"
          >
            {busy ? "Adding..." : status === "failed" ? "Retry download" : "Add to library & download"}
          </button>
          <button
            onClick={handleOpenExternal}
            disabled={busy}
            className="w-full px-3 py-1.5 rounded text-sm text-sol-base0 hover:bg-sol-base02 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer border border-sol-base01/40 text-left"
          >
            Open externally
          </button>
          <button
            onClick={onClose}
            disabled={busy}
            className="w-full px-3 py-1.5 rounded text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer text-left"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
