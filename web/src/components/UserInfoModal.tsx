import { useEffect, useState } from "react";
import { getToken } from "../api";

interface UserInfoModalProps {
  open: boolean;
  email: string | null;
  onClose: () => void;
}

interface JwtPayload {
  user_id?: string | number;
  email?: string;
  [key: string]: unknown;
}

function decodeJwt(token: string | null): JwtPayload | null {
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}

export default function UserInfoModal({ open, email, onClose }: UserInfoModalProps) {
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setCopied(null);
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  const claims = decodeJwt(getToken());
  const userId = claims?.user_id != null ? String(claims.user_id) : null;
  const claimEmail = claims?.email ?? null;
  const displayEmail = email ?? claimEmail;
  const initial = displayEmail ? displayEmail[0].toUpperCase() : "?";

  const copy = async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      setTimeout(() => setCopied((c) => (c === label ? null : c)), 1200);
    } catch {
      // ignore
    }
  };

  const Row = ({ label, value }: { label: string; value: string | null }) => (
    <div className="flex items-baseline gap-3">
      <div className="w-16 shrink-0 text-xs text-sol-base01">{label}</div>
      <div className="flex-1 min-w-0 flex items-center gap-2">
        <div className="text-sm text-sol-base1 font-mono break-all">{value ?? "—"}</div>
        {value && (
          <button
            onClick={() => copy(label, value)}
            className="shrink-0 text-[10px] text-sol-base01 hover:text-sol-base1 cursor-pointer"
            title={`Copy ${label}`}
          >
            {copied === label ? "Copied" : "Copy"}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-sol-base02">
          <div className="w-10 h-10 rounded-full bg-sol-base02 flex items-center justify-center text-base font-bold text-sol-base1 shrink-0">
            {initial}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sol-base1 text-sm font-semibold">User info</div>
            <div className="text-sol-base01 text-xs truncate">{displayEmail || "Not signed in"}</div>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 p-1 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer"
            title="Close"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div className="flex flex-col gap-2 px-4 py-3">
          <Row label="Email" value={displayEmail} />
          <Row label="User ID" value={userId} />
        </div>
      </div>
    </div>
  );
}
