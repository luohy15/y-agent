/**
 * Finance bits shared by FinanceViewer and TickerView.
 * Hoisted so the price-range buttons and amount formatting stay single-source.
 */

export interface FinancePriceRow {
  symbol: string;
  price_date: string;
  price: number;
  currency: string;
}

export type PriceRange = "1M" | "3M" | "1Y" | "YTD" | "ALL";

// `value` is the `time` query param for /api/finance/prices ("" = no bound).
export const PRICE_RANGES: Array<{ label: PriceRange; value: string }> = [
  { label: "1M", value: "1M" },
  { label: "3M", value: "3M" },
  { label: "1Y", value: "1Y" },
  { label: "YTD", value: "YTD" },
  { label: "ALL", value: "" },
];

export function formatAmount(amount: number): string {
  return (amount === 0 ? 0 : amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
