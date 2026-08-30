import { useMemo, useState } from "react";
import useSWR from "swr";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { ListEmpty, ListError, ListLoading } from "./ListStates";

export interface VocabWord {
  word_id: string;
  word: string;
  rank: number;
  status: string;
  marked_at?: string | null;
  marked_at_unix?: number | null;
}

export interface VocabTier {
  label: string;
  max_rank: number;
  total: number;
  known: number;
  unknown: number;
  reviewed: number;
  percent: number;
}

export interface VocabStats {
  tiers: VocabTier[];
  reviewed: number;
  total: number;
  next_unseen_rank: number | null;
}

type VocabView = "scan" | "unknown";

const UNSEEN_KEY = `${API}/api/english/vocab/list?status=unseen&limit=30`;
const UNKNOWN_KEY = `${API}/api/english/vocab/list?status=unknown&limit=500`;
const STATS_KEY = `${API}/api/english/vocab/stats`;

async function markVocab(status: string, wordIds: string[]): Promise<void> {
  if (wordIds.length === 0) return;
  const res = await authFetch(`${API}/api/english/vocab/mark`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, word_ids: wordIds }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `mark ${status} failed: ${res.status}`);
  }
}

function formatCount(n: number): string {
  return n.toLocaleString();
}

export default function VocabularyTab({ isLoggedIn }: { isLoggedIn: boolean }) {
  const [view, setView] = useState<VocabView>("scan");
  const [unknownIds, setUnknownIds] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [flipping, setFlipping] = useState<string | null>(null);

  const { data: stats, error: statsError, isLoading: statsLoading, mutate: mutateStats } = useSWR<VocabStats>(
    isLoggedIn ? STATS_KEY : null,
    fetcher,
    { revalidateOnFocus: false },
  );
  const { data: unseen, error: unseenError, isLoading: unseenLoading, mutate: mutateUnseen } = useSWR<VocabWord[]>(
    isLoggedIn ? UNSEEN_KEY : null,
    fetcher,
    { revalidateOnFocus: false },
  );
  const { data: unknowns, error: unknownError, isLoading: unknownLoading, mutate: mutateUnknowns } = useSWR<VocabWord[]>(
    isLoggedIn ? UNKNOWN_KEY : null,
    fetcher,
    { revalidateOnFocus: false },
  );

  const batch = useMemo(() => (Array.isArray(unseen) ? unseen : []), [unseen]);
  const unknownList = useMemo(() => (Array.isArray(unknowns) ? unknowns : []), [unknowns]);

  const refreshAll = async () => {
    await Promise.all([mutateStats(), mutateUnseen(), mutateUnknowns()]);
    setUnknownIds(new Set());
  };

  const toggleChip = (wordId: string) => {
    setUnknownIds((prev) => {
      const next = new Set(prev);
      if (next.has(wordId)) next.delete(wordId);
      else next.add(wordId);
      return next;
    });
  };

  const handleConfirm = async () => {
    if (confirming || batch.length === 0) return;
    const idsAtFetch = batch.map((w) => w.word_id);
    const unk = idsAtFetch.filter((id) => unknownIds.has(id));
    const known = idsAtFetch.filter((id) => !unknownIds.has(id));
    setConfirming(true);
    try {
      await markVocab("unknown", unk);
      await markVocab("known", known);
      await refreshAll();
    } finally {
      setConfirming(false);
    }
  };

  const handleKnow = async (wordId: string) => {
    if (flipping) return;
    setFlipping(wordId);
    try {
      await markVocab("known", [wordId]);
      await refreshAll();
    } finally {
      setFlipping(null);
    }
  };

  const pillClass = (on: boolean) =>
    `text-[0.6rem] px-1.5 py-0.5 rounded cursor-pointer border-none ${
      on ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
    }`;

  const total = stats?.total ?? 0;
  const reviewed = stats?.reviewed ?? 0;
  const unknownCount = unknownList.length;
  const unkInBatch = batch.filter((w) => unknownIds.has(w.word_id)).length;
  const knownInBatch = batch.length - unkInBatch;
  const confirmLabel = unkInBatch
    ? `Confirm · ${knownInBatch} known / ${unkInBatch} unknown`
    : `Confirm · ${batch.length} known`;
  const minRank = batch[0]?.rank;
  const maxRank = batch[batch.length - 1]?.rank;
  const nextHintRank = maxRank != null ? maxRank + 1 : null;
  const error = statsError || unseenError || unknownError;

  if (!isLoggedIn) {
    return <p className="text-sol-base01 italic p-2">Sign in to view vocabulary</p>;
  }
  if ((statsLoading && !stats) || (stats && total > 0 && unseenLoading && !unseen)) {
    return <ListLoading />;
  }
  if (error && !stats) {
    return <ListError error={error} />;
  }
  if (stats && total === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center flex-1">
        <p className="text-sol-base01 text-[0.7rem]">No vocabulary seeded yet</p>
        <p className="text-sol-base01/80 text-[0.6rem] leading-relaxed">
          Seed from the CLI: <span className="text-sol-cyan font-mono">y english vocab seed</span>
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex items-center gap-1 p-2 border-b border-sol-base02 shrink-0">
        <button onClick={() => setView("scan")} className={pillClass(view === "scan")}>
          Scan
        </button>
        <button onClick={() => setView("unknown")} className={pillClass(view === "unknown")}>
          Unknown <span className="font-mono">{unknownCount}</span>
        </button>
        <span className="ml-auto text-[0.6rem] text-sol-base01 font-mono">
          {view === "scan" ? `${formatCount(reviewed)} / ${formatCount(total)} reviewed` : "sorted by rank"}
        </span>
      </div>

      {view === "scan" && (
        <>
          <div className="px-2.5 pt-2 pb-2 border-b border-sol-base02 shrink-0 space-y-[0.35rem]">
            {(stats?.tiers || []).map((tier) => {
              const knownPct = tier.total ? (tier.known / tier.total) * 100 : 0;
              const unkPct = tier.total ? (tier.unknown / tier.total) * 100 : 0;
              return (
                <div key={tier.label} className="flex items-center gap-[0.45rem]">
                  <span className="w-6 text-[0.6rem] text-sol-base1 font-medium">{tier.label}</span>
                  <span className="flex-1 h-[0.34rem] bg-sol-base02 rounded overflow-hidden flex">
                    <i className="h-full bg-sol-blue" style={{ width: `${knownPct}%` }} />
                    <i className="h-full bg-sol-orange" style={{ width: `${unkPct}%` }} />
                  </span>
                  <span className="text-[0.55rem] text-sol-base01 whitespace-nowrap">
                    <b className="text-sol-base0 font-medium">{tier.percent}%</b>
                    {` · ${tier.unknown} unk`}
                  </span>
                </div>
              );
            })}
          </div>

          {batch.length === 0 ? (
            <div className="flex-1 overflow-y-auto p-4 text-center">
              <p className="text-sol-base01 text-[0.7rem]">Scan complete</p>
              <p className="text-sol-base01/80 text-[0.6rem] mt-1">Every seeded word has been marked.</p>
            </div>
          ) : (
            <>
              <div className="flex items-baseline px-2.5 pt-2 pb-0.5 shrink-0">
                <span className="text-[0.7rem] text-sol-base1 font-medium">Next batch</span>
                <span className="ml-auto text-[0.55rem] text-sol-base01 font-mono">
                  rank {formatCount(minRank)} – {formatCount(maxRank)}
                </span>
              </div>
              <div className="px-2.5 pb-1.5 text-[0.55rem] text-sol-base01 shrink-0">
                Tap the words you <span className="text-sol-orange">don't know</span>. Everything else is confirmed known.
              </div>
              <div className="flex-1 overflow-y-auto px-2.5 pb-2 flex flex-wrap gap-[0.3rem] content-start">
                {batch.map((w) => {
                  const unk = unknownIds.has(w.word_id);
                  return (
                    <button
                      key={w.word_id}
                      type="button"
                      onClick={() => toggleChip(w.word_id)}
                      className={`text-[0.68rem] py-[0.22rem] px-2 cursor-pointer select-none rounded ${
                        unk
                          ? "bg-sol-orange/14 text-sol-orange border border-sol-orange"
                          : "bg-sol-base02 text-sol-base0 border border-transparent hover:text-sol-base1"
                      }`}
                    >
                      {w.word}
                    </button>
                  );
                })}
              </div>
              <div className="px-2.5 py-2 border-t border-sol-base02 shrink-0">
                <button
                  type="button"
                  onClick={handleConfirm}
                  disabled={confirming}
                  className="w-full py-[0.42rem] cursor-pointer text-[0.68rem] font-medium bg-sol-blue text-sol-base03 border-none rounded disabled:opacity-50"
                >
                  {confirming ? "Confirming…" : confirmLabel}
                </button>
                {nextHintRank != null && (
                  <div className="mt-[0.3rem] text-[0.55rem] text-sol-base01 text-center">
                    next batch starts at rank {formatCount(nextHintRank)}
                  </div>
                )}
              </div>
            </>
          )}

          <div className="px-2.5 py-1.5 border-t border-sol-base02 text-[0.55rem] text-sol-base01 leading-relaxed shrink-0">
            Seeded top-10k by frequency · CLI parity via{" "}
            <span className="text-sol-cyan font-mono">y english vocab</span>
          </div>
        </>
      )}

      {view === "unknown" && (
        <>
          <div className="flex-1 overflow-y-auto py-1.5 px-1.5">
            {unknownLoading && !unknowns ? (
              <ListLoading />
            ) : unknownList.length === 0 ? (
              <ListEmpty label="unknown words" />
            ) : (
              unknownList.map((w) => (
                <div key={w.word_id} className="flex items-center gap-2 px-[0.45rem] py-[0.34rem] rounded hover:bg-sol-base02/50">
                  <span className="w-[0.32rem] h-[0.32rem] rounded-full bg-sol-orange shrink-0" />
                  <span className="text-[0.7rem] text-sol-base0">{w.word}</span>
                  <span className="ml-auto text-[0.55rem] text-sol-base01 font-mono">#{formatCount(w.rank)}</span>
                  <button
                    type="button"
                    onClick={() => handleKnow(w.word_id)}
                    disabled={flipping === w.word_id}
                    className="text-[0.55rem] py-[0.12rem] px-[0.4rem] cursor-pointer bg-sol-base02 text-sol-base01 border border-sol-base01 rounded hover:text-sol-green hover:border-sol-green disabled:opacity-50"
                  >
                    know
                  </button>
                </div>
              ))
            )}
          </div>
          <div className="px-2.5 py-1.5 border-t border-sol-base02 text-[0.55rem] text-sol-base01 leading-relaxed shrink-0">
            Your study queue · tap <span className="text-sol-green">know</span> when a word is learned
          </div>
        </>
      )}
    </div>
  );
}
