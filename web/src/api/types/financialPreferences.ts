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
export type FinancialInvestmentProfile = {
  budgetCny?: number | null; horizonMonths?: number | null;
  availableCashCny?: number | null;
  flexibleHorizon?: boolean | null; maxLossCny?: number | null;
  cashReserveCny?: number | null; maxPositionPct?: number | null;
  market?: "CN"; holdingsStatus?: "unknown" | "none" | "recorded";
};
export type FinancialWorkspaceSettings = {
  schemaVersion: 1; agentId: string; revision: number; updatedAt: string;
  selectedStock: StockIdentity | null; watchlist: FinancialWatchStock[];
  profiles: FinancialResearchProfile[]; manualPositions: FinancialManualPosition[];
  reviewCases: FinancialReviewCase[];
  investmentProfile?: FinancialInvestmentProfile | null;
  investmentPlans?: FinancialInvestmentPlan[];
  investmentStateFingerprint?: string;
};
export type FinancialWorkspacePatch = Partial<Pick<FinancialWorkspaceSettings,
  "selectedStock" | "watchlist" | "profiles" | "manualPositions" | "reviewCases" | "investmentProfile">>;

export type FinancialInvestmentOrder = { symbol: string; side: "buy" | "sell"; quantity: number };
export type FinancialPlanDraft = {
  title: string; rationale: string; orders: FinancialInvestmentOrder[]; reviewAfter: string | null;
};
export type FinancialInvestmentPlan = FinancialPlanDraft & {
  id: string; status: "proposed" | "adopted" | "executed" | "invalidated";
  createdAt: string; updatedAt: string; source: { sessionId: string; turnId: string };
  stateFingerprint: string; needsReview: boolean;
};
export type FinancialAdvisorProposal =
  | { kind: "profile"; baseFingerprint: string; profile: FinancialInvestmentProfile }
  | { kind: "plan"; baseFingerprint: string; plan: FinancialPlanDraft };
export type FinancialAdvisorCommand = { expectedRevision: number } & (
  | { action: "confirm_proposal"; sessionId: string; turnId: string }
  | { action: "adopt" | "invalidate"; planId: string }
  | { action: "execute"; planId: string; actualCashCny: number; actualPositions: FinancialManualPosition[] }
);
export type FinancialAdvisorCheck = {
  passed: boolean; blockers: string[]; warnings: string[];
  cashAfterCny: number | null; feesCny: number; orders: FinancialInvestmentOrder[];
};
