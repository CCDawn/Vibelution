import type { StockIdentity, StockQuote } from "./financialMarket";

export type FinancialMarketQuoteResult = {
  symbol: string;
  quote: StockQuote | null;
  error: string | null;
};

export type FinancialMarketQuoteBatch = {
  source: string;
  sourceUrl: string;
  fetchedAt: string;
  items: FinancialMarketQuoteResult[];
};

export type FinancialMarketScreenSort =
  | "changePercent"
  | "turnoverYuan"
  | "price"
  | "volumeLots"
  | "peRatio"
  | "pbRatio";
// Advanced screening remains in the validated A-share universe.

export type FinancialMarketScreenFilters = {
  minPrice?: number;
  maxPrice?: number;
  minChangePercent?: number;
  maxChangePercent?: number;
  minPe?: number;
  maxPe?: number;
  minVolumeLots?: number;
  minPb?: number;
  maxPb?: number;
  minTurnoverYuan?: number;
  maxTurnoverYuan?: number;
  sortBy?: FinancialMarketScreenSort;
  direction?: "asc" | "desc";
  page?: number;
  pageSize?: number;
};

export type FinancialMarketScreenStock = StockIdentity & {
  price: number | null;
  previousClose: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  change: number | null;
  changePercent: number | null;
  volumeLots: number | null;
  turnoverYuan: number | null;
  peRatio: number | null;
  pbRatio: number | null;
  totalMarketCapYuan: number | null;
  timestamp: string | null;
  timeOfDay: string | null;
};

export type FinancialMarketScreen = {
  source: string;
  sourceUrl: string;
  fetchedAt: string;
  dataDate: string | null;
  dataTime: string | null;
  cacheKey: string;
  cacheSeconds: number;
  coverage: {
    providerTotal: number;
    loaded: number;
    complete: boolean;
    failedPages: number[];
    invalidRows: number;
    duplicateRows: number;
    totalFiltered: number;
  };
  resultScope: "provider_universe" | "loaded_subset";
  sortBy: FinancialMarketScreenSort;
  direction: "asc" | "desc";
  page: number;
  pageSize: number;
  items: FinancialMarketScreenStock[];
  notice: string;
};

export type FinancialResearchNewsItem = {
  title: string;
  publishedAt: string | null;
  publisher: string;
  url: string | null;
};

export type FinancialResearchAnnouncement = {
  title: string;
  publishedAt: string | null;
  noticeDate: string | null;
  url: string;
  articleCode: string;
  publisher?: string | null;
};

export type FinancialResearchMetric = {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  reportDate: string | null;
  publishedAt: string | null;
};

export type FinancialResearchFacet<T> = {
  status: "available" | "unavailable";
  source: string;
  sourceUrl: string;
  fetchedAt: string;
  error: string | null;
  items: T[];
};

export type FinancialResearchFundamentals = FinancialResearchFacet<FinancialResearchMetric> & {
  reportDate: string | null;
  publishedAt: string | null;
};

export type FinancialStockResearch = {
  stock: StockIdentity;
  news: FinancialResearchFacet<FinancialResearchNewsItem>;
  announcements: FinancialResearchFacet<FinancialResearchAnnouncement>;
  fundamentals: FinancialResearchFundamentals;
};
