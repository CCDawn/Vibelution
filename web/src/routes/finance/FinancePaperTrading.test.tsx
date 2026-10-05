// @vitest-environment happy-dom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FetchJsonHttpError } from "../../api/client";

const api = vi.hoisted(() => ({
  fetchAccount: vi.fn(),
  fetchReview: vi.fn(),
  openAccount: vi.fn(),
  submitOrder: vi.fn(),
  fetchStock: vi.fn(),
  isUnopened: vi.fn((error: unknown) => error instanceof Error && (error as Error & { status?: number }).status === 404 && /尚未开设模拟账户|paper account (?:is )?not open(?:ed)?/i.test(error.message)),
}));

vi.mock("../../api/financialPaper", () => ({
  fetchFinancialPaperAccount: api.fetchAccount,
  fetchFinancialPaperReview: api.fetchReview,
  openFinancialPaperAccount: api.openAccount,
  submitFinancialPaperOrder: api.submitOrder,
  isFinancialPaperAccountNotOpened: api.isUnopened,
  financialPaperKeys: {
    account: (agentId: string) => ["financial-paper", agentId, "account"],
    review: (agentId: string, month: string) => ["financial-paper", agentId, "review", month],
  },
}));
vi.mock("../../api/financialMarket", () => ({
  fetchFinancialStock: api.fetchStock,
  financialMarketKeys: { stock: (symbol: string, period: string) => ["market", symbol, period] },
}));

import { FinancePaperTrading } from "./FinancePaperTrading";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const agent = {
  agentId: "financial-agent",
  agentCode: "FIN-1",
  displayName: "炒股智能体",
  status: "active",
  setupStatus: "ready",
  directSessionId: "session-1",
  knowledgeBaseId: "finance-kb",
  knowledgeReadable: true,
  modelStatus: "configured_unverified",
  reportStatus: "ready",
  marketDataStatus: "public_quotes",
  newsDelegationStatus: "disabled",
  privateLedgerStatus: "available",
  tradingEnabled: false,
};
const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
const account = {
  agentId: agent.agentId,
  accountId: "paper-1",
  openedAt: "2026-10-05T00:00:00+00:00",
  initialCashYuan: "1000000.00",
  cashYuan: "1000000.00",
  marketValueYuan: "0.00",
  equityYuan: "1000000.00",
  realizedPnlYuan: "0.00",
  unrealizedPnlYuan: "0.00",
  totalPnlYuan: "0.00",
  totalFeesYuan: "0.00",
  valuationStatus: "fresh" as const,
  valuationNotice: "腾讯公开报价，可能延迟。",
  positions: [],
  orders: [],
  ordersTotal: 0,
  ordersLimit: 50,
  ordersTruncated: false,
  feePolicy: {
    commissionRate: "0.0003",
    minimumCommissionYuan: "5.00",
    sellStampDutyRate: "0.0005",
    transferFeeIncluded: false,
    description: "模拟佣金及印花税口径。",
  },
  tPlusOneRule: "模拟 T+1：买入日之后的北京时间自然日可卖出。",
  simulationOnly: true as const,
};

let root: Root | null = null;
let container: HTMLDivElement;
let client: QueryClient;

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function render(node: ReactNode) {
  await act(async () => root?.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>));
  await flush();
}

function buttonWithText(label: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find((item) => item.textContent?.includes(label));
  if (!button) throw new Error(`Could not find button: ${label}`);
  return button;
}

describe("FinancePaperTrading", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    api.fetchAccount.mockRejectedValue(new FetchJsonHttpError("尚未开设模拟账户", { status: 404 }));
    api.fetchReview.mockResolvedValue({ account, month: "2026-10", days: [], summary: {
      totalTradeCount: 0,
      buyCount: 0,
      sellCount: 0,
      winningSellCount: 0,
      allTimeRealizedPnlYuan: "0.00",
      allTimeFeesYuan: "0.00",
      monthTradeCount: 0,
      monthRealizedPnlYuan: "0.00",
      monthFeesYuan: "0.00",
    }, feePolicy: account.feePolicy, tPlusOneRule: account.tPlusOneRule, simulationOnly: true });
    api.openAccount.mockResolvedValue(account);
    api.fetchStock.mockResolvedValue({ stock: { ...stock, price: 10, timestamp: "2026-10-05T15:00:00+08:00" }, source: "腾讯财经", fetchedAt: "2026-10-05T07:00:00+00:00" });
  });

  afterEach(async () => {
    await act(async () => root?.unmount());
    container.remove();
    root = null;
  });

  it("opens a fixed virtual balance once and passes the real ledger to AI review only after the user clicks", async () => {
    const onResearchPrompt = vi.fn();
    await render(<FinancePaperTrading assistant={agent} stock={stock} zh mode="account" onResearchPrompt={onResearchPrompt} />);
    expect(container.textContent).toContain("尚未开设模拟账户");

    await act(async () => {
      buttonWithText("开设模拟账户").click();
      buttonWithText("开设模拟账户").click();
      await Promise.resolve();
    });
    await flush();
    expect(api.openAccount).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("¥1,000,000.00");
    expect(container.textContent).toContain("仅模拟");
    expect(onResearchPrompt).not.toHaveBeenCalled();

    await act(async () => buttonWithText("AI 复盘").click());
    expect(onResearchPrompt).toHaveBeenCalledTimes(1);
    expect(onResearchPrompt.mock.calls[0][0]).toContain("1,000,000");
    expect(onResearchPrompt.mock.calls[0][0]).toContain("2026-10-05T15:00:00+08:00");
  });

  it("renders calendar totals from actual ledger days and keeps no-trade months empty", async () => {
    api.fetchReview.mockResolvedValueOnce({
      account,
      month: "2026-10",
      days: [{ date: "2026-10-03", tradeCount: 2, buyCount: 1, sellCount: 1, buyAmountYuan: "1000.00", sellAmountYuan: "1100.00", feesYuan: "10.55", realizedPnlYuan: "89.45" }],
      summary: { totalTradeCount: 2, buyCount: 1, sellCount: 1, winningSellCount: 1, allTimeRealizedPnlYuan: "89.45", allTimeFeesYuan: "10.55", monthTradeCount: 2, monthRealizedPnlYuan: "89.45", monthFeesYuan: "10.55" },
      feePolicy: account.feePolicy,
      tPlusOneRule: account.tPlusOneRule,
      simulationOnly: true,
    });
    const onResearchPrompt = vi.fn();
    await render(<FinancePaperTrading assistant={agent} stock={stock} zh mode="review" onResearchPrompt={onResearchPrompt} />);
    expect(container.textContent).toContain("交易日历");
    expect(container.textContent).toContain("2 笔");
    expect(container.textContent).toContain("¥89.45");
    await act(async () => buttonWithText("AI 复盘").click());
    expect(onResearchPrompt.mock.calls[0][0]).toContain("2026-10-03");
    expect(onResearchPrompt.mock.calls[0][0]).toContain("10.55");
  });
});
