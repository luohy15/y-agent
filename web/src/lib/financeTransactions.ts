/**
 * Transaction classification helpers shared by FinanceViewer and TickerView.
 * Hoisted from FinanceViewer so trade markers / symbol resolution stay single-source.
 */

export interface TransactionAmount {
  amount: number;
  currency: string;
}

export interface PostingRow {
  account: string;
  symbol: string;
  side: string;
  quantity: number | null;
  price: number | null;
  price_currency: string;
  amount: number | null;
  amount_currency: string;
  cost: number | null;
  cost_currency: string;
  commission: number | null;
  commission_currency: string;
}

export interface TransactionRow {
  transaction_date: string;
  entry_id?: string;
  symbol: string;
  side: string;
  symbols?: string[];
  sides?: string[];
  quantity: number | TransactionAmount[] | null;
  price: number | null;
  price_currency: string;
  amount: number | TransactionAmount[] | null;
  amount_currency?: string;
  commission: number | null;
  commission_currency: string;
  payee: string;
  narration: string;
  postings: PostingRow[];
  source?: string;
}

export type TxnType = "buy" | "sell" | "income" | "fee" | "other";

// The only account in the ledger that holds non-fiat (share) units — the
// ticker is carried as the posting's symbol, not a per-symbol subaccount.
// startsWith rather than === so a future per-symbol split keeps working.
// Deliberately narrower than the ":Stock" substring test used elsewhere
// (classifyTxnType / entryPrice / primarySymbol), which also matches
// Assets:Stock:MPF and the non-IBKR A-share accounts.
export function isIbkrStockLeg(p: PostingRow): boolean {
  return p.account.startsWith("Assets:Stock:IBKR");
}

// Classify an entry into a semantic type. Trades are identified by the security
// leg (Assets:Stock) side; dividend/interest credited to an Income account are
// income; entries made up only of fee/tax legs plus their settling cash leg are
// fees (e.g. foreign tax withholding: a Taxes-and-fees expense leg + an
// Assets:Cash Withdrawal leg); the rest (transfers, FX conversions, salary,
// expenses) are "other".
export function classifyTxnType(row: TransactionRow): TxnType {
  const postings = row.postings || [];
  const stockLeg = postings.find((p) => p.account.includes(":Stock") && (p.side === "Buy" || p.side === "Sell"));
  if (stockLeg) return stockLeg.side === "Buy" ? "buy" : "sell";
  if (postings.some((p) => (p.side === "Dividend" || p.side === "Interest") && p.account.startsWith("Income"))) return "income";
  const isFeeLeg = (p: PostingRow) => p.side === "Taxes and fees" || p.account.startsWith("Expenses:Fees") || p.account.startsWith("Expenses:Interest");
  const isSettlingCashLeg = (p: PostingRow) => p.account.startsWith("Assets:Cash") && p.side === "Withdrawal";
  if (postings.some((p) => p.side === "Taxes and fees") && postings.every((p) => isFeeLeg(p) || isSettlingCashLeg(p))) return "fee";
  return "other";
}

// Entry-level price = the security leg's per-unit price (entry.price is null).
export function entryPrice(postings: PostingRow[]): TransactionAmount | null {
  const leg = (postings || []).find((p) => p.price != null && p.account.includes(":Stock"));
  return leg && leg.price != null ? { amount: leg.price, currency: leg.price_currency } : null;
}

// Cutoff raised from 1e-6 to 0.005 so a sub-cent residue can never render as
// "0.00" (audited: 0 residuals fall in that range across the live dataset).
export function amountsFromMap(m: Record<string, number>): TransactionAmount[] {
  return Object.entries(m)
    .filter(([, v]) => Math.abs(v) > 0.005)
    .map(([currency, amount]) => ({ amount, currency }));
}

// Shares: the IBKR security legs' unit deltas, summed per ticker.
export function entryShares(postings: PostingRow[]): TransactionAmount[] {
  const totals: Record<string, number> = {};
  for (const p of postings || []) {
    if (isIbkrStockLeg(p) && p.quantity != null) {
      totals[p.symbol] = (totals[p.symbol] || 0) + p.quantity;
    }
  }
  return amountsFromMap(totals);
}

// Ticker for an entry: the IBKR security leg's symbol if present; else, for
// an IBKR-touching entry only (plan §0 scopes option B to "IBKR-touching"
// entries whose narration names a held ticker — a bare cash leg on some
// other account must not qualify), the first known IBKR ticker matched as a
// whole word in narration/payee (cash-only dividend / foreign-tax-
// withholding entries have no security leg).
export function entryTicker(row: TransactionRow, tickers: Set<string>): string | null {
  const postings = row.postings || [];
  const stockLeg = postings.find((p) => isIbkrStockLeg(p) && p.symbol);
  if (stockLeg) return stockLeg.symbol;
  if (!postings.some((p) => p.account.includes(":IBKR"))) return null;
  const haystack = `${row.narration || ""} ${row.payee || ""}`;
  for (const ticker of tickers) {
    const escaped = ticker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    if (new RegExp(`\\b${escaped}\\b`).test(haystack)) return ticker;
  }
  return null;
}

// Ticker universe: the set of IBKR stock symbols actually present in the
// fetched rows, so it never needs separate maintenance.
export function buildTickerUniverse(rows: TransactionRow[]): Set<string> {
  const set = new Set<string>();
  for (const row of rows) {
    for (const p of row.postings || []) {
      if (isIbkrStockLeg(p) && p.symbol) set.add(p.symbol);
    }
  }
  return set;
}
