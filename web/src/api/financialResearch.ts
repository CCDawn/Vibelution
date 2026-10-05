import { fetchJson } from "./client";
import type {
  FinancialMarketQuoteBatch,
  FinancialMarketScreen,
  FinancialMarketScreenFilters,
  FinancialStockResearch,
} from "./types/financialResearch";

export type {
  FinancialMarketQuoteBatch,
  FinancialMarketQuoteResult,
  FinancialMarketScreen,
  FinancialMarketScreenFilters,
  FinancialMarketScreenSort,
  FinancialMarketScreenStock,
  FinancialResearchAnnouncement,
  FinancialResearchFacet,
  FinancialResearchFundamentals,
  FinancialResearchMetric,
  FinancialResearchNewsItem,
  FinancialStockResearch,
} from "./types/financialResearch";

export const financialResearchKeys = {
  quotes: (symbols: readonly string[]) => ["financial-research", "quotes", [...symbols].sort()] as const,
  screen: (filters: FinancialMarketScreenFilters) => ["financial-research", "screen", filters] as const,
  stock: (symbol: string) => ["financial-research", "stock", symbol] as const,
};

export function fetchFinancialMarketQuotes(symbols: readonly string[], options?: { signal?: AbortSignal }) {
  const query = encodeURIComponent([...symbols].join(","));
  return fetchJson<FinancialMarketQuoteBatch>(`/api/financial-market/quotes?symbols=${query}`, { signal: options?.signal });
}

export function fetchFinancialMarketScreen(filters: FinancialMarketScreenFilters = {}, options?: { signal?: AbortSignal }) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const query = params.toString();
  return fetchJson<FinancialMarketScreen>(`/api/financial-market/screen${query ? `?${query}` : ""}`, { signal: options?.signal });
}

export function fetchFinancialStockResearch(symbol: string, options?: { signal?: AbortSignal }) {
  return fetchJson<FinancialStockResearch>(`/api/financial-market/stocks/${encodeURIComponent(symbol)}/research`, { signal: options?.signal });
}
