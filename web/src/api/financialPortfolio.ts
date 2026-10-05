import { fetchJson } from "./client";
import type { FinancialPortfolioResearch } from "./types/financialPortfolio";

export type {
  FinancialPortfolioCorrelation,
  FinancialPortfolioPosition,
  FinancialPortfolioResearch,
  FinancialPortfolioReturnSeriesStatus,
} from "./types/financialPortfolio";

export const financialPortfolioKeys = {
  research: (agentId: string) => ["financial-portfolio", agentId, "research"] as const,
};

export function fetchFinancialPortfolioResearch(
  agentId: string,
  options?: { signal?: AbortSignal },
): Promise<FinancialPortfolioResearch> {
  return fetchJson<FinancialPortfolioResearch>(
    `/api/financial-portfolios/${encodeURIComponent(agentId)}/research`,
    { signal: options?.signal },
  );
}
