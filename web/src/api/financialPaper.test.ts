import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchJson = vi.hoisted(() => vi.fn());
vi.mock("./client", async () => ({
  ...(await vi.importActual<typeof import("./client")>("./client")),
  fetchJson,
}));

import { FetchJsonHttpError } from "./client";
import { fetchFinancialPaperAccount, fetchFinancialPaperReview, isFinancialPaperAccountNotOpened, openFinancialPaperAccount, submitFinancialPaperOrder } from "./financialPaper";

describe("financial paper API", () => {
  beforeEach(() => fetchJson.mockClear());

  it("reads only the selected Agent ledger and bounds recent orders", async () => {
    fetchJson.mockResolvedValueOnce({});
    await fetchFinancialPaperAccount("agent/one", { orderLimit: 50 });
    expect(fetchJson).toHaveBeenCalledWith("/api/financial-paper/agent%2Fone?orderLimit=50", { signal: undefined });
  });

  it("opens the fixed virtual account without accepting a client balance", async () => {
    fetchJson.mockResolvedValueOnce({});
    await openFinancialPaperAccount("agent-one");
    expect(fetchJson).toHaveBeenCalledWith("/api/financial-paper/agent-one/account", { method: "POST" });
  });

  it("sends no client price, path, or real-account fields with an order", async () => {
    fetchJson.mockResolvedValueOnce({});
    const request = {
      clientOrderId: "client-id",
      symbol: "sh600519",
      side: "buy" as const,
      quantity: 100,
      reason: "test rationale",
    };
    await submitFinancialPaperOrder("agent-one", request);
    expect(fetchJson).toHaveBeenCalledWith("/api/financial-paper/agent-one/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    expect(Object.keys(JSON.parse(fetchJson.mock.calls.at(-1)?.[1]?.body ?? "{}"))).toEqual([
      "clientOrderId", "symbol", "side", "quantity", "reason",
    ]);
  });

  it("scopes monthly review to the same Agent", async () => {
    fetchJson.mockResolvedValueOnce({});
    await fetchFinancialPaperReview("agent-one", "2026-10");
    expect(fetchJson).toHaveBeenCalledWith("/api/financial-paper/agent-one/review?month=2026-10", { signal: undefined });
  });

  it("classifies only the domain-specific missing-account response", () => {
    expect(isFinancialPaperAccountNotOpened(new FetchJsonHttpError("尚未开设模拟账户", { status: 404 }))).toBe(true);
    expect(isFinancialPaperAccountNotOpened(new FetchJsonHttpError("金融助手不存在", { status: 404 }))).toBe(false);
    expect(isFinancialPaperAccountNotOpened(new Error("network failure"))).toBe(false);
  });
});
