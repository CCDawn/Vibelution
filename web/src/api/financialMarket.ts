import { fetchJson } from "./client";
import type { StockIdentity, StockMarketCode, StockPeriod, StockSnapshot } from "./types/financialMarket";
export type { StockIdentity, StockMarketCode, StockCurrency, StockPriceUnit, StockPeriod, StockSnapshot, StockQuote, StockCandle } from "./types/financialMarket";

export const financialMarketKeys = {
  search: (query: string, market: StockMarketCode = "CN") => ["financial-market", "search", market, query] as const,
  stock: (symbol: string, period: StockPeriod) => ["financial-market", "stock", symbol, period] as const,
};
export function searchFinancialStocks(query: string, options?: { signal?: AbortSignal; market?: StockMarketCode }) {
  const params = new URLSearchParams({ query });
  if (options?.market && options.market !== "CN") params.set("market", options.market);
  return fetchJson<StockIdentity[]>(`/api/financial-market/search?${params.toString()}`, { signal: options?.signal });
}
export function fetchFinancialStock(symbol: string, period: StockPeriod, options?: { signal?: AbortSignal }) {
  return fetchJson<StockSnapshot>(`/api/financial-market/stocks/${encodeURIComponent(symbol)}?period=${period}`, { signal: options?.signal });
}
