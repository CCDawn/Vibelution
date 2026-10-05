// @vitest-environment happy-dom

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ fetchQuotes: vi.fn() }));
vi.mock("../../api/financialResearch", () => ({
  fetchFinancialMarketQuotes: api.fetchQuotes,
  financialResearchKeys: { quotes: (symbols: readonly string[]) => ["financial-research", "quotes", [...symbols].sort()] },
}));

import { FinanceWatchlistTable } from "./FinanceWatchlistTable";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const watchlist = [
  { symbol: "sz000001", ticker: "000001", name: "平安银行", market: "深交所" },
  { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" },
];
const quote = (stock: (typeof watchlist)[number], changePercent: number) => ({ ...stock, price: 10, previousClose: 10, open: 10, high: 11, low: 9, change: 0, changePercent, volumeLots: 20, turnoverYuan: 2000, peRatio: 12, pbRatio: 2, totalMarketCapYuan: 3_000_000_000, timestamp: "2026-10-05T09:30:00+08:00" });

let root: Root | null = null;
let node: HTMLDivElement;
let client: QueryClient;
async function render(props: Partial<React.ComponentProps<typeof FinanceWatchlistTable>> = {}) {
  await act(async () => root?.render(<QueryClientProvider client={client}><FinanceWatchlistTable watchlist={watchlist} onSelectStock={() => {}} onRemoveStock={() => {}} zh {...props} /></QueryClientProvider>));
  await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
}
beforeEach(() => {
  api.fetchQuotes.mockReset().mockResolvedValue({ source: "腾讯财经", sourceUrl: "https://gu.qq.com/", fetchedAt: "2026-10-05T01:00:00+00:00", items: [
    { symbol: "sz000001", quote: quote(watchlist[0], -1.2), error: null },
    { symbol: "sh600519", quote: quote(watchlist[1], 2.4), error: null },
  ] });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node);
});
afterEach(async () => {
  await act(async () => root?.unmount()); root = null; node.remove(); client.clear();
});

describe("FinanceWatchlistTable", () => {
  it("sorts by fetched quotes and removes the chosen stock", async () => {
    const onRemoveStock = vi.fn();
    await render({ onRemoveStock });
    const rows = Array.from(node.querySelectorAll('[role="row"]')).map((row) => row.textContent ?? "");
    expect(rows[1]).toContain("贵州茅台");
    expect(rows[2]).toContain("平安银行");
    const remove = Array.from(node.querySelectorAll("button")).find((button) => button.getAttribute("aria-label") === "移除 平安银行");
    expect(remove).toBeTruthy();
    await act(async () => remove?.click());
    expect(onRemoveStock).toHaveBeenCalledWith(watchlist[0]);
  });
});
