// @vitest-environment happy-dom

import React, { act } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StockIdentity, StockSnapshot } from "../../api/financialMarket";
import { FinanceMarketPanel, FinanceStockHeader } from "./FinanceStockOverview";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const stock: StockSnapshot["stock"] = {
  symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所",
  price: 1_258.62, previousClose: 1_235.58, open: 1_239.53, high: 1_268, low: 1_236,
  change: 23.04, changePercent: 1.86, volumeLots: 38_331, turnoverYuan: 4_797_250_000,
  peRatio: 19.32, pbRatio: 6.26, totalMarketCapYuan: null, timestamp: "2026-10-05T09:30:00+08:00",
};
const snapshot: StockSnapshot = {
  stock,
  candles: Array.from({ length: 40 }, (_, index) => ({
    date: `2026-10-${String(index + 1).padStart(2, "0")}`,
    open: 100 + index, close: 101 + index, high: 102 + index, low: 99 + index, volumeLots: 100,
  })),
  period: "day", adjustment: "raw", source: "腾讯财经", sourceUrl: "https://gu.qq.com/",
  fetchedAt: "2026-10-05T01:00:00+00:00", candleError: "", notice: "",
};

let root: Root | null = null;
let node: HTMLDivElement;
afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  node.remove();
});

describe("FinanceStockOverview cached refresh failure", () => {
  it("keeps compact report quotes and provenance without losing refresh or follow actions", async () => {
    const refetch = vi.fn().mockResolvedValue({});
    const follow = vi.fn();
    const query = { data: snapshot, isPending: false, isFetching: false, refetch } as unknown as UseQueryResult<StockSnapshot, Error>;
    node = document.createElement("div");
    document.body.appendChild(node);
    root = createRoot(node);
    await act(async () => root?.render(<FinanceStockHeader stock={stock} query={query} starred={false} onToggleStar={follow} zh compact />));
    expect(node.querySelector("dl")).toBeNull();
    expect(node.textContent).toContain("1,258.62");
    expect(node.textContent).toContain("腾讯财经");
    expect(node.textContent).toContain("可能延迟");
    expect(node.textContent).toContain(snapshot.stock.timestamp);
    expect(node.textContent).toContain(snapshot.fetchedAt);
    await act(async () => node.querySelector<HTMLButtonElement>('button[aria-label="刷新行情"]')!.click());
    await act(async () => [...node.querySelectorAll("button")].find(button => button.textContent === "加入自选")!.click());
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(follow).toHaveBeenCalledTimes(1);
  });

  it("keeps the quote and chart, shows source timestamps, and retries", async () => {
    const refetch = vi.fn().mockResolvedValue({});
    const query = {
      data: snapshot,
      error: new Error("quote refresh failed"),
      isError: true,
      isPending: false,
      isFetching: false,
      refetch,
    } as unknown as UseQueryResult<StockSnapshot, Error>;
    const identity: StockIdentity = stock;
    node = document.createElement("div");
    document.body.appendChild(node);
    root = createRoot(node);

    await act(async () => root?.render(<>
      <FinanceStockHeader stock={identity} query={query} starred={false} onToggleStar={() => {}} zh />
      <FinanceMarketPanel query={query} period="day" onPeriodChange={() => {}} zh />
    </>));

    expect(node.textContent).toContain("1,258.62");
    expect(node.querySelector('svg[role="img"]')).toBeTruthy();
    expect(node.textContent).toContain("刷新失败，当前仍显示上次成功获取的行情");
    expect(node.textContent).toContain("quote refresh failed");
    expect(node.textContent).toContain("2026-10-05T09:30:00+08:00");
    expect(node.textContent).toContain("2026-10-05T01:00:00+00:00");

    const retry = Array.from(node.querySelectorAll("button")).find((button) => button.textContent?.includes("重试"));
    expect(retry).toBeTruthy();
    await act(async () => retry?.click());
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
