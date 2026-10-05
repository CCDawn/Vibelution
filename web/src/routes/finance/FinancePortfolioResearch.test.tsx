// @vitest-environment happy-dom

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FetchJsonHttpError } from "../../api/client";
import type { FinancialPortfolioResearch } from "../../api/financialPortfolio";
import type { FinancialAssistant } from "../../api/financialAssistant";

const api = vi.hoisted(() => ({ fetchResearch: vi.fn() }));
vi.mock("../../api/financialPortfolio", () => ({
  fetchFinancialPortfolioResearch: api.fetchResearch,
  financialPortfolioKeys: {
    research: (agentId: string) => ["financial-portfolio", agentId, "research"],
  },
}));

import { FinancePortfolioResearch } from "./FinancePortfolioResearch";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const research: FinancialPortfolioResearch = {
  agentId: "agent-one",
  accountId: "paper-account-one",
  generatedAt: "2026-10-05T07:00:00Z",
  source: "腾讯财经",
  sourceUrl: "https://gu.qq.com/",
  adjustment: "qfq",
  period: "day",
  simulationOnly: true,
  summary: {
    equityYuan: "100000.00",
    cashYuan: "20000.00",
    marketValueYuan: "80000.00",
    cashWeightPercent: "20.00",
    positionCount: 2,
    valuedPositionCount: 2,
    valuationComplete: true,
    maxPositionWeightPercent: "50.00",
    topThreeWeightPercent: "80.00",
    correlationPairCount: 1,
    highCorrelationPairCount: 1,
    insufficientCorrelationPairCount: 0,
    unavailableCorrelationPairCount: 0,
  },
  positions: [
    {
      symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所", quantity: 100,
      markPriceYuan: "500.00", marketValueYuan: "50000.00", unrealizedPnlYuan: "100.00", weightPercent: "50.00",
      valuationStatus: "fresh", quoteTimestamp: "2026-10-05T15:00:00+08:00", quoteFetchedAt: "2026-10-05T07:00:00Z",
      source: "腾讯财经", sourceUrl: "https://gu.qq.com/sh600519/gp", returnSeriesStatus: "available",
    },
    {
      symbol: "sz000001", ticker: "000001", name: "平安银行", market: "深交所", quantity: 1000,
      markPriceYuan: "30.00", marketValueYuan: "30000.00", unrealizedPnlYuan: "-50.00", weightPercent: "30.00",
      valuationStatus: "fresh", quoteTimestamp: "2026-10-05T15:00:00+08:00", quoteFetchedAt: "2026-10-05T07:00:00Z",
      source: "腾讯财经", sourceUrl: "https://gu.qq.com/sz000001/gp", returnSeriesStatus: "available",
    },
  ],
  correlations: [{
    firstSymbol: "sh600519", firstName: "贵州茅台", secondSymbol: "sz000001", secondName: "平安银行",
    correlation: -0.842, observations: 25, startDate: "2026-09-01", endDate: "2026-10-03",
  }],
  coverage: {
    eligiblePositionCount: 2,
    selectedPositionCount: 2,
    candleLoadedPositionCount: 2,
    candleUnavailablePositionCount: 0,
    budgetSkippedPositionCount: 0,
    capacitySkippedPositionCount: 0,
    deadlineSkippedPositionCount: 0,
    unvaluedPositionCount: 0,
    maxAnalyzedPositions: 12,
    maxConcurrentFetches: 3,
    deadlineSeconds: 10,
    minimumCorrelationObservations: 20,
    analyzedSymbols: ["sh600519", "sz000001"],
    budgetSkippedSymbols: [],
    unavailableSymbols: [],
  },
  notice: "仅分析模拟账本持仓；公开行情可能延迟。",
};

let root: Root | null = null;
let node: HTMLDivElement;
let client: QueryClient;

async function render(props: Partial<React.ComponentProps<typeof FinancePortfolioResearch>> = {}) {
  await act(async () => root?.render(<QueryClientProvider client={client}><FinancePortfolioResearch
    assistant={{ agentId: "agent-one" } as FinancialAssistant}
    onSelectStock={() => {}}
    onResearchPrompt={() => {}}
    zh
    {...props}
  /></QueryClientProvider>));
  await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
}

function buttonWithText(text: string): HTMLButtonElement {
  const button = Array.from(node.querySelectorAll("button")).find((item) => item.textContent?.includes(text));
  if (!button) throw new Error(`Button not found: ${text}`);
  return button;
}

beforeEach(() => {
  api.fetchResearch.mockReset().mockResolvedValue(research);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node);
});

afterEach(async () => {
  await act(async () => root?.unmount()); root = null; node.remove(); client.clear();
});

describe("FinancePortfolioResearch", () => {
  it("shows actual ledger and common-session correlations and hands drafts to the native composer", async () => {
    const onSelectStock = vi.fn();
    const onResearchPrompt = vi.fn();
    await render({ onSelectStock, onResearchPrompt });

    expect(node.textContent).toContain("组合研究");
    expect(node.textContent).toContain("50.00%");
    expect(node.textContent).toContain("-0.842");
    expect(node.textContent).toContain("2026-09-01 — 2026-10-03");
    expect(node.textContent).toContain("报价有效");
    expect(node.textContent).toContain("2026/10/5 15:00:00");
    await act(async () => buttonWithText("贵州茅台").click());
    expect(onSelectStock).toHaveBeenCalledWith({ symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" });
    await act(async () => buttonWithText("个股研读").click());
    expect(onResearchPrompt).toHaveBeenCalledWith(expect.stringContaining("sh600519"));
    await act(async () => buttonWithText("生成组合诊断草稿").click());
    expect(onResearchPrompt).toHaveBeenLastCalledWith(expect.stringContaining("共同交易日"));
  });

  it("explains incomplete marks and preserves null weights", async () => {
    api.fetchResearch.mockResolvedValue({
      ...research,
      summary: { ...research.summary, valuationComplete: false, valuedPositionCount: 1, cashWeightPercent: null, maxPositionWeightPercent: null },
      positions: research.positions.map((position, index) => index === 1 ? { ...position, marketValueYuan: null, weightPercent: null, valuationStatus: "unavailable", returnSeriesStatus: "not_valued" } : position),
    });
    await render();
    expect(node.textContent).toContain("估值不完整，组合权重暂不可用");
    expect(node.textContent).toContain("缺失估值的仓位不会被当作零值");
    expect(node.textContent).toContain("估值缺失");
  });

  it("does not report a budget cutoff when extra holdings are unvalued", async () => {
    api.fetchResearch.mockResolvedValue({
      ...research,
      positions: [...research.positions, { ...research.positions[0], symbol: "sz000002", marketValueYuan: null, returnSeriesStatus: "not_valued" }],
      coverage: { ...research.coverage, maxAnalyzedPositions: 2, unvaluedPositionCount: 1 },
    });
    await render();
    expect(node.textContent).not.toContain("本次分析前");
    expect(node.textContent).toContain("预算跳过 0 只");
  });

  it("routes an unopened-account 404 to the paper account without opening it", async () => {
    api.fetchResearch.mockRejectedValue(new FetchJsonHttpError("尚未开设模拟账户", { status: 404 }));
    const onOpenAccount = vi.fn();

    await render({ onOpenAccount });

    expect(node.textContent).toContain("尚未开设模拟账户");
    expect(node.textContent).toContain("此页面不会自动创建账户");
    expect(Array.from(node.querySelectorAll("button")).some((button) => button.textContent?.includes("重试"))).toBe(false);
    await act(async () => buttonWithText("前往模拟账户").click());
    expect(onOpenAccount).toHaveBeenCalledTimes(1);
    expect(api.fetchResearch).toHaveBeenCalledTimes(1);
  });
});
