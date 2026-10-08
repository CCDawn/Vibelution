import { fetchJson, fetchJsonWithTimeout, isFetchJsonHttpError } from "./client";
import type {
  FinancialPortfolioProposal,
  FinancialPortfolioProposalApprovalRequest,
  FinancialPortfolioProposalCreateRequest,
  FinancialPortfolioProposalList,
  FinancialPortfolioProposalPreviewRequest,
  FinancialPortfolioResearch,
} from "./types/financialPortfolio";

export type {
  FinancialPortfolioCorrelation,
  FinancialPortfolioPosition,
  FinancialPortfolioResearch,
  FinancialPortfolioReturnSeriesStatus,
  FinancialPortfolioProposal,
  FinancialPortfolioProposalApprovalRequest,
  FinancialPortfolioProposalCreateRequest,
  FinancialPortfolioProposalList,
  FinancialPortfolioProposalPreviewRequest,
  FinancialPortfolioRebalancePolicy,
  FinancialPortfolioRebalanceTarget,
} from "./types/financialPortfolio";

export const financialPortfolioKeys = {
  research: (agentId: string) => ["financial-portfolio", agentId, "research"] as const,
  proposals: (agentId: string) => ["financial-portfolio", agentId, "proposals"] as const,
  proposal: (agentId: string, proposalId: string) => ["financial-portfolio", agentId, "proposal", proposalId] as const,
};

export function isFinancialPortfolioProposalNotFound(error: unknown): boolean {
  return isFetchJsonHttpError(error) && error.status === 404;
}

function proposalsPath(agentId: string): string {
  return `/api/financial-portfolios/${encodeURIComponent(agentId)}/proposals`;
}

export function fetchFinancialPortfolioResearch(
  agentId: string,
  options?: { signal?: AbortSignal },
): Promise<FinancialPortfolioResearch> {
  return fetchJson<FinancialPortfolioResearch>(
    `/api/financial-portfolios/${encodeURIComponent(agentId)}/research`,
    { signal: options?.signal },
  );
}

export function fetchFinancialPortfolioProposals(
  agentId: string,
  options?: { signal?: AbortSignal },
): Promise<FinancialPortfolioProposalList> {
  return fetchJson<FinancialPortfolioProposalList>(proposalsPath(agentId), { signal: options?.signal });
}

export function fetchFinancialPortfolioProposal(
  agentId: string,
  proposalId: string,
  options?: { signal?: AbortSignal },
): Promise<FinancialPortfolioProposal> {
  return fetchJson<FinancialPortfolioProposal>(
    `${proposalsPath(agentId)}/${encodeURIComponent(proposalId)}`,
    { signal: options?.signal },
  );
}

/** The model call is synchronous and may take several minutes; callers keep this UUID for readback/retry. */
export function createFinancialPortfolioProposal(
  agentId: string,
  request: FinancialPortfolioProposalCreateRequest,
  options?: { signal?: AbortSignal },
): Promise<FinancialPortfolioProposal> {
  return fetchJsonWithTimeout<FinancialPortfolioProposal>(proposalsPath(agentId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal: options?.signal,
    timeoutMs: 600_000,
  });
}

export function previewFinancialPortfolioProposal(
  agentId: string,
  proposalId: string,
  request: FinancialPortfolioProposalPreviewRequest,
): Promise<FinancialPortfolioProposal> {
  return fetchJson<FinancialPortfolioProposal>(
    `${proposalsPath(agentId)}/${encodeURIComponent(proposalId)}/preview`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) },
  );
}

export function approveFinancialPortfolioProposal(
  agentId: string,
  proposalId: string,
  request: FinancialPortfolioProposalApprovalRequest,
): Promise<FinancialPortfolioProposal> {
  return fetchJson<FinancialPortfolioProposal>(
    `${proposalsPath(agentId)}/${encodeURIComponent(proposalId)}/approve`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) },
  );
}
