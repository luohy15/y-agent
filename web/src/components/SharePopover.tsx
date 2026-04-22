import { useState, useEffect, useRef } from "react";

export type ShareMode = "public" | "generate" | "custom";

interface CreateResult {
  share_id: string;
  password?: string;
}

interface SharePopoverProps {
  onCreate: (opts: { password?: string; generate_password?: boolean }) => Promise<CreateResult>;
  buildUrl: (shareId: string) => string;
  buttonClassName?: string;
  buttonLabel?: string;
}

export default function SharePopover({ onCreate, buildUrl, buttonClassName, buttonLabel = "share" }: SharePopoverProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<ShareMode>("public");
  const [customPassword, setCustomPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<"idle" | "copied" | "error">("idle");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
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

  const label = status === "copied" ? "copied!" : status === "error" ? "error" : buttonLabel;
  const stateCls =
    status === "copied" ? "bg-sol-green/20 text-sol-green" :
    status === "error" ? "bg-sol-red/20 text-sol-red" :
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
        <div className="absolute right-0 top-full mt-1 z-20 w-56 bg-sol-base03 border border-sol-base02 rounded shadow-lg p-2 text-xs">
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
        </div>
      )}
    </div>
  );
}
