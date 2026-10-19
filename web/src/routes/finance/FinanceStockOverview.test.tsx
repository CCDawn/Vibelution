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
  it("retains chart preferences through period loading and retry while resetting the old viewport", async () => {
    node = document.createElement("div");
    document.body.appendChild(node);
    root = createRoot(node);
    const refetch = vi.fn();
    const changePeriod = vi.fn();
    const renderPanel = async (data: StockSnapshot | undefined, pending = false, error?: Error) => {
      const query = { data, isPending: pending, isError: Boolean(error), error, refetch } as unknown as UseQueryResult<StockSnapshot, Error>;
      await act(async () => root?.render(<FinanceMarketPanel query={query} period={data?.period ?? "week"} onPeriodChange={changePeriod} zh />));
    };
    const selectTab = async (label: string) => {
      const target = [...node.querySelectorAll('[role="tab"]')].find(item => item.textContent === label)!;
      await act(async () => target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    };
    await renderPanel(snapshot);
    await selectTab("RSI");
    await selectTab("30 根");
    await act(async () => node.querySelector<HTMLButtonElement>('button[aria-label="查看更早 K 线"]')!.click());
    await selectTab("周 K");
    expect(changePeriod).toHaveBeenCalledWith("week");
    await renderPanel(undefined, true);
    expect(node.querySelector('svg[role="img"]')).toBeNull();
    const weekly: StockSnapshot = { ...snapshot, period: "week", candles: snapshot.candles.map((candle, index) => ({ ...candle, date: `week-${index + 1}` })) };
    await renderPanel(weekly);
    expect(node.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe("周 K");
    expect([...node.querySelectorAll('[role="tab"][aria-selected="true"]')].map(item => item.textContent)).toEqual(["周 K", "RSI", "30 根"]);
    expect(node.querySelector('svg[role="img"]')?.textContent).toContain("week-11");
    expect(node.querySelector('button[aria-label="查看较新 K 线"]')?.hasAttribute("disabled")).toBe(true);
    await renderPanel(undefined, false, new Error("temporary chart failure"));
    expect(node.textContent).toContain("行情加载失败");
    await act(async () => [...node.querySelectorAll("button")].find(button => button.textContent === "重试")!.click());
    expect(refetch).toHaveBeenCalledOnce();
    await renderPanel(weekly);
    expect([...node.querySelectorAll('[role="tab"][aria-selected="true"]')].map(item => item.textContent)).toEqual(["周 K", "RSI", "30 根"]);
  });

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
    expect(node.textContent).toContain("成交额(元)");
    expect(node.textContent).toContain("47.97亿");

    const retry = Array.from(node.querySelectorAll("button")).find((button) => button.textContent?.includes("重试"));
    expect(retry).toBeTruthy();
    await act(async () => retry?.click());
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
