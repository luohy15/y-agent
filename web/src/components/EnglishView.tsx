import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { wordDiff } from "../utils/wordDiff";
import type { EnglishCorrection } from "./EnglishList";

interface EnglishViewProps {
  correctionId: string;
}

const CAT_COLORS = [
  "text-sol-yellow",
  "text-sol-cyan",
  "text-sol-orange",
  "text-sol-magenta",
  "text-sol-violet",
  "text-sol-green",
  "text-sol-blue",
];

function catColor(cat: string, index: number): string {
  let h = 0;
  for (let i = 0; i < cat.length; i++) h = (h * 31 + cat.charCodeAt(i)) | 0;
  return CAT_COLORS[Math.abs(h) % CAT_COLORS.length] || CAT_COLORS[index % CAT_COLORS.length];
}

function formatHeaderTime(iso: string | undefined, unixMs?: number): string {
  const d = unixMs ? new Date(unixMs) : iso ? new Date(iso) : null;
  if (!d || isNaN(d.getTime())) return "—";
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfMsg = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dayDiff = Math.round((startOfToday.getTime() - startOfMsg.getTime()) / 86400000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  if (dayDiff === 0) return `today ${hh}:${mm}`;
  if (dayDiff === 1) return `yesterday ${hh}:${mm}`;
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function EnglishView({ correctionId }: EnglishViewProps) {
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const { mutate: globalMutate } = useSWRConfig();

  const key = correctionId
    ? `${API}/api/english/detail?correction_id=${encodeURIComponent(correctionId)}`
    : null;
  const { data, error, isLoading, mutate } = useSWR<EnglishCorrection>(key, fetcher, {
    revalidateOnFocus: false,
  });

  if (!correctionId) {
    return (
      <p className="text-sol-base01 italic text-sm p-3">
        No correction selected. Pick a row in the English panel.
      </p>
    );
  }
  if (isLoading && !data) {
    return <p className="text-sol-base01 italic text-sm p-3">Loading…</p>;
  }
  if (error && !data) {
    return <p className="text-sol-red text-sm p-3">Failed to load correction.</p>;
  }
  if (!data) {
    return <p className="text-sol-base01 italic text-sm p-3">Correction not found.</p>;
  }

  const spans = wordDiff(data.original_text || "", data.corrected_text || "");
  const msgLabel = data.message_id
    ? data.message_id.length > 10
      ? data.message_id.slice(0, 8)
      : data.message_id
    : "—";

  const handleDismiss = async () => {
    if (busy || data.dismissed) return;
    setBusy(true);
    try {
      const res = await authFetch(`${API}/api/english/dismiss`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ correction_id: data.correction_id }),
      });
      if (!res.ok) throw new Error(`dismiss failed: ${res.status}`);
      await mutate();
      await globalMutate((key) => typeof key === "string" && key.includes("/api/english/list"));
      setConfirm(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden text-xs bg-sol-base03">
      <div className="px-4 py-3 border-b border-sol-base02 flex items-start gap-3 shrink-0">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[0.6rem] font-mono text-sol-base01">{data.correction_id}</span>
            {data.dismissed ? (
              <span className="px-1.5 py-0.5 rounded bg-sol-base02 text-sol-base01 text-[0.55rem] line-through decoration-sol-base01">
                dismissed
              </span>
            ) : (
              <span className="px-1.5 py-0.5 rounded bg-sol-base02 text-sol-blue text-[0.55rem]">
                active
              </span>
            )}
            {data.dismissed && (
              <span className="text-[0.55rem] text-sol-base01">excluded from patterns</span>
            )}
          </div>
          <div className="mt-1 text-[0.65rem] text-sol-base01 font-mono truncate">
            chat <span className="text-sol-base0">{data.chat_id}</span>
            {" · "}msg <span className="text-sol-base0">{msgLabel}</span>
            {" · "}
            {formatHeaderTime(data.message_at, data.message_at_unix)}
          </div>
        </div>
        {!data.dismissed && (
          <button
            onClick={() => setConfirm(true)}
            disabled={busy}
            className="shrink-0 px-2 py-1 rounded bg-sol-base02 border border-sol-base01 text-sol-base0 hover:text-sol-base1 hover:border-sol-base0 text-[0.65rem] cursor-pointer disabled:opacity-50"
          >
            Dismiss
          </button>
        )}
      </div>

      <div className={`flex-1 overflow-y-auto px-4 py-3 space-y-4 ${data.dismissed ? "opacity-70" : ""}`}>
        <div>
          <div className="text-[0.6rem] uppercase tracking-wider text-sol-base01 mb-1.5">
            Error classification
          </div>
          <div className="flex gap-1 flex-wrap">
            {(data.error_categories || []).length === 0 ? (
              <span className="text-sol-base01 text-[0.65rem]">—</span>
            ) : (
              (data.error_categories || []).map((c, i) => (
                <span
                  key={c}
                  className={`px-1.5 py-0.5 rounded bg-sol-base02 ${catColor(c, i)} text-[0.65rem]`}
                >
                  {c}
                </span>
              ))
            )}
          </div>
        </div>

        <div>
          <div className="text-[0.6rem] uppercase tracking-wider text-sol-base01 mb-1.5">Original</div>
          <div className="rounded bg-sol-base02/60 border border-sol-base02 px-3 py-2 text-[0.8rem] text-sol-base1 leading-relaxed whitespace-pre-wrap">
            {data.original_text}
          </div>
        </div>

        <div>
          <div className="text-[0.6rem] uppercase tracking-wider text-sol-base01 mb-1.5">
            Minimally corrected
          </div>
          <div className="rounded bg-sol-base02/60 border border-sol-base02 px-3 py-2 text-[0.8rem] text-sol-base1 leading-relaxed whitespace-pre-wrap">
            {data.corrected_text}
          </div>
        </div>

        <div>
          <div className="text-[0.6rem] uppercase tracking-wider text-sol-base01 mb-1.5">
            Diff
            <span className="normal-case tracking-normal text-sol-base00 ml-1">
              (from original / corrected · not stored)
            </span>
          </div>
          <div className="rounded bg-sol-base02 border border-sol-base01/40 px-3 py-2 text-[0.8rem] text-sol-base1 leading-relaxed whitespace-pre-wrap">
            {spans.map((s, i) =>
              s.type === "same" ? (
                <span key={i}>{s.text}</span>
              ) : s.type === "del" ? (
                <span key={i} className="diff-del">
                  {s.text}
                </span>
              ) : (
                <span key={i} className="diff-ins">
                  {s.text}
                </span>
              ),
            )}
          </div>
          <div className="flex gap-3 mt-1.5 text-[0.55rem] text-sol-base01">
            <span>
              <span className="diff-del px-0.5">removed</span> original span
            </span>
            <span>
              <span className="diff-ins px-0.5">added</span> corrected span
            </span>
          </div>
        </div>

        <div>
          <div className="text-[0.6rem] uppercase tracking-wider text-sol-base01 mb-1.5">
            Grammar explanation
          </div>
          <div className="rounded border border-sol-base02 px-3 py-2 text-[0.75rem] text-sol-base0 leading-relaxed whitespace-pre-wrap">
            {data.explanation}
          </div>
        </div>
      </div>

      {confirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={() => !busy && setConfirm(false)}
        >
          <div
            className="w-full max-w-sm bg-sol-base03 border border-sol-base02 rounded overflow-hidden text-xs shadow-float"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-3 py-2 border-b border-sol-base02 flex items-center justify-between">
              <span className="text-sol-base1 font-medium text-[0.7rem]">Dismiss correction?</span>
              <span className="text-sol-base01 text-[0.6rem] font-mono">{data.correction_id}</span>
            </div>
            <div className="p-3 space-y-3">
              <p className="text-[0.7rem] text-sol-base0 leading-relaxed">
                Dismissed items stay in history but drop out of recurring-pattern counts. Use this
                for false positives or deliberate informal phrasing.
              </p>
              <div className="rounded bg-sol-base02/60 border border-sol-base02 px-2.5 py-2 text-[0.7rem] text-sol-base1">
                {data.original_text}
              </div>
              <p className="text-[0.55rem] text-sol-base01 leading-relaxed">
                One action only: sets <code className="text-sol-cyan">dismissed=true</code>. No
                reason field in v1.
              </p>
              <div className="flex gap-2 justify-end pt-1">
                <button
                  onClick={() => setConfirm(false)}
                  disabled={busy}
                  className="px-2.5 py-1 rounded bg-sol-base02 text-sol-base01 text-[0.65rem] cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDismiss}
                  disabled={busy}
                  className="px-2.5 py-1 rounded bg-sol-orange/20 border border-sol-orange/50 text-sol-orange text-[0.65rem] cursor-pointer disabled:opacity-50"
                >
                  {busy ? "Dismissing…" : "Dismiss"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
