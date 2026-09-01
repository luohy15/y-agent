import { useState, type KeyboardEvent } from "react";
import { API, authFetch } from "../api";
import { wordDiff } from "../utils/wordDiff";

export interface RefineResult {
  original: string;
  changed: boolean;
  corrected: string;
  categories: string[];
  explanation: string;
  correction_id?: string | null;
}

interface RefineTabProps {
  isLoggedIn: boolean;
  onSaved?: () => void;
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

export default function RefineTab({ isLoggedIn, onSaved }: RefineTabProps) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RefineResult | null>(null);
  const [copied, setCopied] = useState(false);

  const runRefine = async () => {
    const original = text.trim();
    if (!original || busy) return;
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const res = await authFetch(`${API}/api/english/refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: original }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `refine failed: ${res.status}`);
      }
      const payload = (await res.json()) as Omit<RefineResult, "original">;
      setResult({ ...payload, original });
      if (payload.changed) onSaved?.();
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void runRefine();
    }
  };

  const copyCorrected = async () => {
    if (!result?.corrected) return;
    try {
      await navigator.clipboard.writeText(result.corrected);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // ignore
    }
  };

  if (!isLoggedIn) {
    return <p className="text-sol-base01 italic p-2">Sign in to refine a sentence</p>;
  }

  const spans = result ? wordDiff(result.original, result.corrected || "") : [];

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden text-xs">
      <div className="p-2 flex flex-col gap-1.5 shrink-0">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={busy}
          maxLength={2000}
          rows={4}
          placeholder="Type or paste a sentence. Enter to refine, Shift+Enter for a new line."
          className="w-full resize-y min-h-[4.5rem] px-2 py-1.5 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none placeholder:text-sol-base01 disabled:opacity-50"
        />
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => void runRefine()}
            disabled={busy || !text.trim()}
            className="px-2 py-1 rounded bg-sol-blue text-sol-base03 text-[0.65rem] cursor-pointer disabled:opacity-50 disabled:cursor-default"
          >
            {busy ? "Refining…" : "Refine"}
          </button>
          <span className="ml-auto text-[0.55rem] text-sol-base01 font-mono">{text.length}/2000</span>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2 space-y-2">
        {error && (
          <div className="rounded border border-sol-red/40 bg-sol-red/10 px-2 py-1.5 text-[0.65rem] text-sol-red whitespace-pre-wrap">
            {error}
          </div>
        )}
        {result && (
          <div className="rounded border border-sol-base02 bg-sol-base02/40 px-2 py-2 space-y-2">
            <div className="flex items-center gap-1.5 flex-wrap">
              {result.changed ? (
                <span className="text-[0.6rem] text-sol-cyan">saved to corrections</span>
              ) : (
                <span className="text-[0.6rem] text-sol-green">already natural ✓</span>
              )}
              <button
                onClick={() => void copyCorrected()}
                className="ml-auto px-1.5 py-0.5 rounded bg-sol-base02 border border-sol-base01 text-sol-base01 hover:text-sol-base0 text-[0.55rem] cursor-pointer"
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            {(result.categories || []).length > 0 && (
              <div className="flex gap-1 flex-wrap">
                {result.categories.map((c, i) => (
                  <span
                    key={`${c}-${i}`}
                    className={`px-1 rounded bg-sol-base03 ${catColor(c, i)} text-[0.55rem]`}
                  >
                    {c}
                  </span>
                ))}
              </div>
            )}
            <div className="rounded bg-sol-base02 border border-sol-base01/40 px-2 py-1.5 text-[0.75rem] text-sol-base1 leading-relaxed font-mono whitespace-pre-wrap">
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
            {result.explanation && (
              <div className="text-[0.7rem] text-sol-base0 leading-relaxed whitespace-pre-wrap">
                {result.explanation}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
