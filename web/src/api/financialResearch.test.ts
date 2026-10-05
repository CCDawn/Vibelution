import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchJson = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ fetchJson }));

import { fetchFinancialMarketQuotes, fetchFinancialMarketScreen, fetchFinancialStockResearch, financialResearchKeys } from "./financialResearch";

describe("financial research API", () => {
  beforeEach(() => fetchJson.mockClear());

  it("encodes a bounded batch quote request and forwards cancellation", async () => {
    fetchJson.mockResolvedValueOnce({});
    const signal = new AbortController().signal;
    await fetchFinancialMarketQuotes(["sh600519", "sz000001"], { signal });
    expect(fetchJson).toHaveBeenCalledWith("/api/financial-market/quotes?symbols=sh600519%2Csz000001", { signal });
  });

  it("serializes only selected screen filters and paging", async () => {
    fetchJson.mockResolvedValueOnce({});
    await fetchFinancialMarketScreen({ minPrice: 10, maxChangePercent: 8, sortBy: "changePercent", direction: "desc", page: 2, pageSize: 50 });
    expect(fetchJson).toHaveBeenCalledWith("/api/financial-market/screen?minPrice=10&maxChangePercent=8&sortBy=changePercent&direction=desc&page=2&pageSize=50", { signal: undefined });
  });

  it("encodes the stock research path and keeps stable query keys", async () => {
    fetchJson.mockResolvedValueOnce({});
    const signal = new AbortController().signal;
    await fetchFinancialStockResearch("sh600519", { signal });
    expect(fetchJson).toHaveBeenCalledWith("/api/financial-market/stocks/sh600519/research", { signal });
    expect(financialResearchKeys.quotes(["sz000001", "sh600519"])).toEqual(financialResearchKeys.quotes(["sh600519", "sz000001"]));
  });
});
