import { useState, useEffect, useRef } from "react";

export type ShareMode = "public" | "generate" | "custom";

interface CreateResult {
  share_id: string;
  password?: string;
}

export interface ExistingShare {
  share_id: string;
  has_password: boolean;
}

interface SharePopoverProps {
  onCreate: (opts: { password?: string; generate_password?: boolean }) => Promise<CreateResult>;
  buildUrl: (shareId: string) => string;
  buttonClassName?: string;
  buttonLabel?: string;
  align?: "left" | "right";
  existingShare?: ExistingShare | null;
  onDelete?: (shareId: string) => Promise<void>;
}

export default function SharePopover({ onCreate, buildUrl, buttonClassName, buttonLabel = "share", align = "right", existingShare, onDelete }: SharePopoverProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<ShareMode>("public");
  const [customPassword, setCustomPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<"idle" | "copied" | "error" | "deleted">("idle");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (!open) setConfirmDelete(false);
  }, [open]);

  const doShare = async () => {
    if (busy) return;
    if (mode === "custom" && !customPassword.trim()) return;
    setBusy(true);
    setStatus("idle");
    try {
      const opts =
        mode === "public" ? {} :
        mode === "generate" ? { generate_password: true } :
        { password: customPassword };
      const result = await onCreate(opts);
      const base = buildUrl(result.share_id);
      const password = result.password ?? (mode === "custom" ? customPassword : undefined);
      const url = password ? `${base}?p=${encodeURIComponent(password)}` : base;
      await navigator.clipboard.writeText(url);
      setStatus("copied");
      setTimeout(() => { setOpen(false); setStatus("idle"); }, 1500);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 1500);
    } finally {
      setBusy(false);
    }
  };

  const doCopyExisting = async () => {
    if (!existingShare) return;
    try {
      await navigator.clipboard.writeText(buildUrl(existingShare.share_id));
      setStatus("copied");
      setTimeout(() => setStatus("idle"), 1500);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 1500);
    }
  };

  const doDelete = async () => {
    if (!existingShare || !onDelete || busy) return;
    setBusy(true);
    setStatus("idle");
    try {
      await onDelete(existingShare.share_id);
      setStatus("deleted");
      setConfirmDelete(false);
      setTimeout(() => { setOpen(false); setStatus("idle"); }, 1500);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 1500);
    } finally {
      setBusy(false);
    }
  };

  const label = status === "copied" ? "copied!" : status === "error" ? "error" : status === "deleted" ? "deleted" : existingShare ? "shared" : buttonLabel;
  const stateCls =
    status === "copied" ? "bg-sol-green/20 text-sol-green" :
    status === "error" ? "bg-sol-red/20 text-sol-red" :
    status === "deleted" ? "bg-sol-base02 text-sol-base01" :
    existingShare ? "bg-sol-green/10 text-sol-green" :
    "";

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={buttonClassName ? `${buttonClassName} ${stateCls}` : stateCls}
      >
        {label}
      </button>
      {open && (
        <div className={`absolute ${align === "left" ? "left-0" : "right-0"} top-full mt-1 z-20 w-64 bg-sol-base03 border border-sol-base02 rounded shadow-lg p-2 text-xs`}>
          {existingShare ? (
            <>
              <div className="text-sol-base01 mb-1.5">Currently shared</div>
              <div className="bg-sol-base02/50 rounded px-2 py-1 mb-2 font-mono text-[0.65rem] text-sol-base0 break-all">
                {buildUrl(existingShare.share_id)}
                {existingShare.has_password && <span className="ml-1 text-sol-base01">[password]</span>}
              </div>
              <div className="flex gap-1">
                <button
                  onClick={doCopyExisting}
                  disabled={busy}
                  className="flex-1 px-2 py-1 bg-sol-blue text-sol-base03 rounded font-semibold text-xs cursor-pointer disabled:opacity-50"
                >
                  Copy link
                </button>
                {onDelete && (
                  confirmDelete ? (
                    <button
                      onClick={doDelete}
                      disabled={busy}
                      className="flex-1 px-2 py-1 bg-sol-red text-sol-base03 rounded font-semibold text-xs cursor-pointer disabled:opacity-50"
                      title="Click to confirm"
                    >
                      {busy ? "..." : "Confirm"}
                    </button>
                  ) : (
                    <button
                      onClick={() => setConfirmDelete(true)}
                      disabled={busy}
                      className="flex-1 px-2 py-1 bg-sol-base02 text-sol-red rounded text-xs cursor-pointer disabled:opacity-50"
                      title="The URL will return 404"
                    >
                      Unshare
                    </button>
                  )
                )}
              </div>
              {confirmDelete && (
                <div className="mt-1 text-[0.6rem] text-sol-base01">URL will return 404.</div>
              )}
            </>
          ) : (
            <>
              <div className="text-sol-base01 mb-1.5">Share as</div>
              <label className="flex items-center gap-2 py-0.5 cursor-pointer">
                <input type="radio" name="share-mode" checked={mode === "public"} onChange={() => setMode("public")} />
                <span className="text-sol-base0">Public link</span>
              </label>
              <label className="flex items-center gap-2 py-0.5 cursor-pointer">
                <input type="radio" name="share-mode" checked={mode === "generate"} onChange={() => setMode("generate")} />
                <span className="text-sol-base0">Auto-generate password</span>
              </label>
              <label className="flex items-center gap-2 py-0.5 cursor-pointer">
                <input type="radio" name="share-mode" checked={mode === "custom"} onChange={() => setMode("custom")} />
                <span className="text-sol-base0">Custom password</span>
              </label>
              {mode === "custom" && (
                <input
                  type="text"
                  value={customPassword}
                  onChange={(e) => setCustomPassword(e.target.value)}
                  placeholder="password"
                  className="mt-1 w-full px-2 py-1 bg-sol-base02 text-sol-base1 rounded text-xs outline-none"
                />
              )}
              <button
                onClick={doShare}
                disabled={busy || (mode === "custom" && !customPassword.trim())}
                className="mt-2 w-full px-2 py-1 bg-sol-blue text-sol-base03 rounded font-semibold text-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {busy ? "..." : "Copy link"}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
