export type FinancialPreference = { id: string; text: string; createdAt: string };
export type FinancialPreferences = { agentId: string; memoryEnabled: boolean; items: FinancialPreference[]; limit: number };
import type { StockIdentity } from "./financialMarket";

export type FinancialWatchStock = StockIdentity & { tags: string[]; note: string };
export type FinancialResearchProfile = {
  id: string; name: string; scope: "financial" | "events" | "risk" | "comprehensive";
  depth: "brief" | "basic" | "standard" | "detailed" | "exhaustive";
  period: string; instructions: string; isDefault: boolean;
};
export type FinancialManualPosition = {
  id: string; stock: StockIdentity; quantity: number; costPrice: number;
  currency: "CNY" | "HKD" | "USD"; note: string;
};
export type FinancialReviewCase = {
  id: string; sessionId: string; turnId: string; title: string; tags: string[]; note: string;
};
export type FinancialWorkspaceSettings = {
  schemaVersion: 1; agentId: string; revision: number; updatedAt: string;
  selectedStock: StockIdentity | null; watchlist: FinancialWatchStock[];
  profiles: FinancialResearchProfile[]; manualPositions: FinancialManualPosition[];
  reviewCases: FinancialReviewCase[];
};
export type FinancialWorkspacePatch = Partial<Pick<FinancialWorkspaceSettings,
  "selectedStock" | "watchlist" | "profiles" | "manualPositions" | "reviewCases">>;
