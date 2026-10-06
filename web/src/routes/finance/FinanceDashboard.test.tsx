// @vitest-environment happy-dom

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { SessionSummary } from "../../api/types";
import type { FinancialMarketQuoteBatch } from "../../api/types/financialResearch";
import { FinanceDashboard } from "./FinanceDashboard";

const api = vi.hoisted(() => ({ quotes: vi.fn(), batches: vi.fn(), schedules: vi.fn() }));
vi.mock("../../api/financialResearch", () => ({
  fetchFinancialMarketQuotes: api.quotes,
  financialResearchKeys: { quotes: (symbols: readonly string[]) => ["quotes", [...symbols].sort()] },
}));
vi.mock("../../api/financialJobs", () => ({
  fetchFinancialResearchBatches: api.batches,
  fetchFinancialResearchSchedules: api.schedules,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const assistant = {
  agentId: "finance-agent-1", agentCode: "finance", displayName: "炒股智能体", status: "active", setupStatus: "ready",
  directSessionId: "session-1", knowledgeBaseId: "knowledge-1", knowledgeReadable: true, modelStatus: "configured_unverified",
  reportStatus: "configured", marketDataStatus: "public_quotes", newsDelegationStatus: "available", privateLedgerStatus: "available", tradingEnabled: true,
} as FinancialAssistant;
const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
const record = {
  id: "session-1", title: "贵州茅台研究", agentId: assistant.agentId, status: "ready", taskSummary: "基本面研究",
  lastActive: "2026-10-06 09:30", updatedAt: "2026-10-06T01:30:00Z", currentPhase: "completed", lastTurnStatus: "completed",
} as SessionSummary;
const quoteBatch: FinancialMarketQuoteBatch = {
  source: "腾讯财经", sourceUrl: "https://qt.gtimg.cn/", fetchedAt: "2026-10-06T01:30:00Z",
  items: [{
    symbol: stock.symbol,
    quote: {
      ...stock, price: 1258.62, previousClose: 1235.58, open: 1239.53, high: 1268, low: 1236,
      change: 23.04, changePercent: 1.86, volumeLots: 38331, turnoverYuan: 4_797_250_000,
      peRatio: 19.32, pbRatio: 6.26, totalMarketCapYuan: null, timestamp: null, timeOfDay: "09:30:00",
    },
    error: null,
  }],
};
let root: Root | null = null;
let node: HTMLDivElement;
let client: QueryClient;

async function render(props: Partial<React.ComponentProps<typeof FinanceDashboard>> = {}) {
  await act(async () => root?.render(<QueryClientProvider client={client}><FinanceDashboard
    assistant={assistant}
    watchlist={[stock]}
    recentResearch={[record]}
    onNavigate={() => {}}
    onSelectStock={() => {}}
    onOpenResearch={() => {}}
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
  api.quotes.mockReset().mockResolvedValue(quoteBatch);
  api.batches.mockReset().mockResolvedValue({ assistantAgentId: assistant.agentId, batches: [{ assistantAgentId: assistant.agentId, status: "running" }] });
  api.schedules.mockReset().mockResolvedValue({ assistantAgentId: assistant.agentId, schedules: [{ assistantAgentId: assistant.agentId, enabled: true, execution: { kind: "daily" } }] });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  node = document.createElement("div");
  document.body.appendChild(node);
  root = createRoot(node);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  node.remove();
  client.clear();
});

describe("FinanceDashboard", () => {
  it("labels the optional external filings service separately from research reports", async () => {
    await render({ assistant: { ...assistant, reportStatus: "not_configured" } });
    expect(node.textContent).toContain("外部财报库未接入");
    expect(node.textContent).not.toContain("报告未配置");
    expect(buttonWithText("报告中心").disabled).toBe(false);
  });

  it("shows watchlist prices, research and live task counts, and routes into existing work areas", async () => {
    const onNavigate = vi.fn(); const onSelectStock = vi.fn(); const onOpenResearch = vi.fn();
    await render({ onNavigate, onSelectStock, onOpenResearch });
    expect(node.textContent).toContain("1.86%");
    expect(node.textContent).toContain("1,258.62");
    expect(node.textContent).toContain("贵州茅台研究");
    expect(node.textContent).toContain("1");
    await act(async () => buttonWithText("贵州茅台").click());
    expect(onSelectStock).toHaveBeenCalledWith(stock);
    expect(onNavigate).toHaveBeenCalledWith("workspace");
    await act(async () => buttonWithText("贵州茅台研究").click());
    expect(onOpenResearch).toHaveBeenCalledWith(record);
    await act(async () => buttonWithText("智能选股").click());
    expect(onNavigate).toHaveBeenCalledWith("screen");
    await act(async () => buttonWithText("组合研究").click());
    expect(onNavigate).toHaveBeenLastCalledWith("portfolio");
    await act(async () => buttonWithText("交易复盘").click());
    expect(onNavigate).toHaveBeenLastCalledWith("review");
  });

  it("keeps useful empty and unavailable states instead of rendering placeholder metrics", async () => {
    await render({ watchlist: [], recentResearch: [] });
    expect(node.textContent).toContain("暂无自选股票");
    expect(node.textContent).toContain("暂无研究记录");
    expect(api.quotes).not.toHaveBeenCalled();

    api.quotes.mockRejectedValue(new Error("quote provider unavailable"));
    await act(async () => root?.render(<QueryClientProvider client={client}><FinanceDashboard
      assistant={assistant} watchlist={[stock]} recentResearch={[]} onNavigate={() => {}}
      onSelectStock={() => {}} onOpenResearch={() => {}} zh
    /></QueryClientProvider>));
    await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(node.textContent).toContain("自选行情暂不可用");
  });
});
