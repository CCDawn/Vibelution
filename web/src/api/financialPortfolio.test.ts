import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchJson, fetchJsonWithTimeout } from "./client";
import {
  approveFinancialPortfolioProposal,
  createFinancialPortfolioProposal,
  fetchFinancialPortfolioProposal,
  fetchFinancialPortfolioProposals,
  fetchFinancialPortfolioResearch,
  financialPortfolioKeys,
  isFinancialPortfolioProposalNotFound,
  previewFinancialPortfolioProposal,
} from "./financialPortfolio";

vi.mock("./client", async (importOriginal) => ({
  ...await importOriginal<typeof import("./client")>(),
  fetchJson: vi.fn(),
  fetchJsonWithTimeout: vi.fn(),
}));

describe("financialPortfolio API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("fetches read-only portfolio research for one encoded Agent", async () => {
    vi.mocked(fetchJson).mockResolvedValue({} as never);
    const controller = new AbortController();
    await fetchFinancialPortfolioResearch("agent/one", { signal: controller.signal });

    expect(fetchJson).toHaveBeenCalledWith(
      "/api/financial-portfolios/agent%2Fone/research",
      { signal: controller.signal },
    );
    expect(financialPortfolioKeys.research("agent/one")).toEqual([
      "financial-portfolio",
      "agent/one",
      "research",
    ]);
  });

  it("reads proposal history and an exact proposal under the encoded Agent", async () => {
    vi.mocked(fetchJson).mockResolvedValue({ items: [] } as never);
    const controller = new AbortController();
    await fetchFinancialPortfolioProposals("agent/one", { signal: controller.signal });
    await fetchFinancialPortfolioProposal("agent/one", "a/b", { signal: controller.signal });

    expect(fetchJson).toHaveBeenNthCalledWith(1, "/api/financial-portfolios/agent%2Fone/proposals", { signal: controller.signal });
    expect(fetchJson).toHaveBeenNthCalledWith(2, "/api/financial-portfolios/agent%2Fone/proposals/a%2Fb", { signal: controller.signal });
    expect(financialPortfolioKeys.proposals("agent/one")).toEqual(["financial-portfolio", "agent/one", "proposals"]);
    expect(financialPortfolioKeys.proposal("agent/one", "proposal-1")).toEqual(["financial-portfolio", "agent/one", "proposal", "proposal-1"]);
  });

  it("creates with the stable UUID request identity and a bounded model timeout", async () => {
    const request = {
      clientRequestId: "bd3a4394-7c20-44af-8ba0-95b9eb986238",
      symbols: ["600000"],
      reports: [{ sessionId: "session-1", turnId: "turn-1" }],
      instruction: "降低集中风险",
      policy: { maxPositionPct: 30, minCashPct: 10, maxTurnoverPct: 100, maxQuoteAgeHours: 72 },
    };
    vi.mocked(fetchJsonWithTimeout).mockResolvedValue({ proposalId: request.clientRequestId } as never);
    const controller = new AbortController();
    await createFinancialPortfolioProposal("agent/one", request, { signal: controller.signal });

    expect(fetchJsonWithTimeout).toHaveBeenCalledWith("/api/financial-portfolios/agent%2Fone/proposals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
      timeoutMs: 600_000,
    });
  });

  it("posts editable targets and requires an explicit simulation approval", async () => {
    vi.mocked(fetchJson).mockResolvedValue({} as never);
    const targets = [{ symbol: "600000", weightPct: 20, reason: "分散配置" }];
    const policy = { maxPositionPct: 30, minCashPct: 10, maxTurnoverPct: 100, maxQuoteAgeHours: 72 };
    await previewFinancialPortfolioProposal("agent-1", "proposal-1", { targets, policy });
    await approveFinancialPortfolioProposal("agent-1", "proposal-1", { planHash: "exact-plan-hash", confirmSimulation: true });

    expect(fetchJson).toHaveBeenNthCalledWith(1, "/api/financial-portfolios/agent-1/proposals/proposal-1/preview", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ targets, policy }),
    });
    expect(fetchJson).toHaveBeenNthCalledWith(2, "/api/financial-portfolios/agent-1/proposals/proposal-1/approve", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ planHash: "exact-plan-hash", confirmSimulation: true }),
    });
  });

  it("classifies only a proposal 404 as a missing readback", async () => {
    const { FetchJsonHttpError } = await import("./client");
    expect(isFinancialPortfolioProposalNotFound(new FetchJsonHttpError("missing", { status: 404 }))).toBe(true);
    expect(isFinancialPortfolioProposalNotFound(new FetchJsonHttpError("forbidden", { status: 403 }))).toBe(false);
    expect(isFinancialPortfolioProposalNotFound(new Error("network disconnected"))).toBe(false);
  });
});
