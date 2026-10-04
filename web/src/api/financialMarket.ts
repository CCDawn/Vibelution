import { fetchJson } from "./client";
import type { StockIdentity, StockPeriod, StockSnapshot } from "./types/financialMarket";
export type { StockIdentity, StockPeriod, StockSnapshot, StockQuote, StockCandle } from "./types/financialMarket";

export const financialMarketKeys = {
  search: (query: string) => ["financial-market", "search", query] as const,
  stock: (symbol: string, period: StockPeriod) => ["financial-market", "stock", symbol, period] as const,
};
export function searchFinancialStocks(query: string, options?: { signal?: AbortSignal }) {
  return fetchJson<StockIdentity[]>(`/api/financial-market/search?query=${encodeURIComponent(query)}`, { signal: options?.signal });
}
export function fetchFinancialStock(symbol: string, period: StockPeriod, options?: { signal?: AbortSignal }) {
  return fetchJson<StockSnapshot>(`/api/financial-market/stocks/${encodeURIComponent(symbol)}?period=${period}`, { signal: options?.signal });
}
