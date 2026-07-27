/**
 * Whitespace-tokenized word-level LCS diff for english correction detail view.
 * Emits spans of type same | del | ins. Diff is computed at read time only.
 */

export type DiffSpan = {
  type: "same" | "del" | "ins";
  text: string;
};

function tokenize(s: string): string[] {
  // Keep whitespace as separate tokens so CJK segments and spacing round-trip.
  const parts = s.match(/\S+|\s+/g);
  return parts ?? [];
}

function lcsTable(a: string[], b: string[]): number[][] {
  const m = a.length;
  const n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (a[i] === b[j]) dp[i][j] = dp[i + 1][j + 1] + 1;
      else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  return dp;
}

/** Merge adjacent spans of the same type so the renderer stays simple. */
function pushSpan(out: DiffSpan[], type: DiffSpan["type"], text: string) {
  if (!text) return;
  const last = out[out.length - 1];
  if (last && last.type === type) {
    last.text += text;
  } else {
    out.push({ type, text });
  }
}

export function wordDiff(original: string, corrected: string): DiffSpan[] {
  if (original === corrected) {
    return original ? [{ type: "same", text: original }] : [];
  }
  const a = tokenize(original);
  const b = tokenize(corrected);
  const dp = lcsTable(a, b);
  const out: DiffSpan[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      pushSpan(out, "same", a[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      pushSpan(out, "del", a[i]);
      i++;
    } else {
      pushSpan(out, "ins", b[j]);
      j++;
    }
  }
  while (i < a.length) {
    pushSpan(out, "del", a[i]);
    i++;
  }
  while (j < b.length) {
    pushSpan(out, "ins", b[j]);
    j++;
  }
  return out;
}
