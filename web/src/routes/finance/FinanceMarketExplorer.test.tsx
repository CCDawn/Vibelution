// @vitest-environment happy-dom

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FinancialMarketScreen, FinancialStockResearch } from "../../api/financialResearch";

const api = vi.hoisted(() => ({ fetchScreen: vi.fn(), fetchResearch: vi.fn(), fetchQuotes: vi.fn() }));
vi.mock("../../api/financialResearch", () => ({
  fetchFinancialMarketScreen: api.fetchScreen,
  fetchFinancialStockResearch: api.fetchResearch,
  fetchFinancialMarketQuotes: api.fetchQuotes,
  financialResearchKeys: {
    screen: (filters: unknown) => ["financial-research", "screen", filters],
    stock: (symbol: string) => ["financial-research", "stock", symbol],
    quotes: (symbols: readonly string[]) => ["financial-research", "quotes", [...symbols].sort()],
  },
}));

import { FinanceMarketExplorer } from "./FinanceMarketExplorer";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
const screen: FinancialMarketScreen = {
  source: "新浪财经", sourceUrl: "https://vip.stock.finance.sina.com.cn/mkt/#hs_a",
  fetchedAt: "2026-10-05T01:00:00+00:00", dataDate: null, dataTime: "14:55:00", cacheKey: "sina:hs_a:14:55:00", cacheSeconds: 600,
  coverage: { providerTotal: 5_571, loaded: 2, complete: false, failedPages: [3], invalidRows: 0, duplicateRows: 0, totalFiltered: 2 },
  resultScope: "loaded_subset", sortBy: "changePercent", direction: "desc", page: 1, pageSize: 50,
  items: [
    { ...stock, price: 1258.62, previousClose: 1235.58, open: 1239.53, high: 1268, low: 1236, change: 23.04, changePercent: 1.86, volumeLots: 38331, turnoverYuan: 4_797_250_000, peRatio: 19.32, pbRatio: 6.26, totalMarketCapYuan: null, timestamp: null, timeOfDay: "14:55:00" },
    { symbol: "sz000001", ticker: "000001", name: "平安银行", market: "深交所", price: 11.2, previousClose: 11.4, open: 11.3, high: 11.4, low: 11.1, change: -0.2, changePercent: -1.75, volumeLots: 93_000, turnoverYuan: 1_042_000_000, peRatio: 5.6, pbRatio: 0.5, totalMarketCapYuan: null, timestamp: null, timeOfDay: "14:55:00" },
  ],
  notice: "新浪返回时分但未提供交易日期。",
};
const research: FinancialStockResearch = {
  stock,
  news: { status: "available", source: "东方财富", sourceUrl: "https://so.eastmoney.com/news/", fetchedAt: "2026-10-05T01:00:00+00:00", error: null, items: [{ title: "贵州茅台发布公告", publishedAt: "2026-10-04", publisher: "东方财富", url: "https://finance.eastmoney.com/a/123456789012.html" }] },
  announcements: { status: "available", source: "东方财富", sourceUrl: "https://data.eastmoney.com/notices/", fetchedAt: "2026-10-05T01:00:00+00:00", error: null, items: [] },
  fundamentals: { status: "available", source: "东方财富", sourceUrl: "https://data.eastmoney.com/bbsj/", fetchedAt: "2026-10-05T01:00:00+00:00", error: null, reportDate: "2026-06-30", publishedAt: "2026-08-28", items: [{ key: "EPSJB", label: "每股收益", value: 2.3, unit: "元/股", reportDate: "2026-06-30", publishedAt: "2026-08-28" }] },
};

let root: Root | null = null;
let node: HTMLDivElement;
let client: QueryClient;

async function render(mode: "screen" | "news" | "fundamentals", props: Partial<React.ComponentProps<typeof FinanceMarketExplorer>> = {}) {
  await act(async () => root?.render(<QueryClientProvider client={client}><FinanceMarketExplorer mode={mode} stock={stock} onSelectStock={() => {}} onResearchPrompt={() => {}} zh {...props} /></QueryClientProvider>));
  await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
}

function buttonWithText(text: string): HTMLButtonElement {
  const button = Array.from(node.querySelectorAll("button")).find((item) => item.textContent?.includes(text));
  if (!button) throw new Error(`Button not found: ${text}`);
  return button;
}

beforeEach(() => {
  api.fetchScreen.mockReset().mockResolvedValue(screen);
  api.fetchResearch.mockReset().mockResolvedValue(research);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node);
});
afterEach(async () => {
  await act(async () => root?.unmount()); root = null; node.remove(); client.clear();
});

describe("FinanceMarketExplorer", () => {
  it("shows partial source coverage and supports stock selection and AI handoff", async () => {
    const onSelectStock = vi.fn(); const onResearchPrompt = vi.fn();
    await render("screen", { onSelectStock, onResearchPrompt });
    expect(node.textContent).toContain("2 / 5,571");
    expect(node.textContent).toContain("新浪 hs_a 行情池");
    expect(node.textContent).toContain("部分结果仅基于已加载项");
    expect(node.textContent).toContain("不等于全市场覆盖");
    expect(node.textContent).toContain("日期未提供");
    await act(async () => buttonWithText("贵州茅台").click());
    expect(onSelectStock).toHaveBeenCalledWith(expect.objectContaining({ symbol: "sh600519" }));
    await act(async () => buttonWithText("AI研读").click());
    expect(onResearchPrompt).toHaveBeenCalledWith(expect.stringContaining("贵州茅台"));
    expect(node.textContent).not.toContain("987654321");
  });

  it("clarifies that a complete Sina pool read is not full-market coverage", async () => {
    api.fetchScreen.mockResolvedValue({
      ...screen,
      coverage: { ...screen.coverage, loaded: 5_571, complete: true, failedPages: [] },
      resultScope: "provider_universe",
    });
    await render("screen");
    expect(node.textContent).toContain("完整读取仅代表新浪 hs_a 行情池，不等于全市场覆盖");
    expect(node.textContent).not.toContain("部分结果仅基于已加载项");
  });

  it("shows dated financial metrics in the fundamentals mode", async () => {
    await render("fundamentals");
    expect(node.textContent).toContain("每股收益");
    expect(node.textContent).toContain("2026-06-30");
    expect(node.textContent).toContain("披露");
  });
});
