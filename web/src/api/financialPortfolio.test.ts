import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchJson } from "./client";
import { fetchFinancialPortfolioResearch, financialPortfolioKeys } from "./financialPortfolio";

vi.mock("./client", () => ({ fetchJson: vi.fn() }));

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
});
