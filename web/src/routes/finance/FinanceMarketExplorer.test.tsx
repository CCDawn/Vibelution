// @vitest-environment happy-dom

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FinancialMarketScreen, FinancialStockResearch } from "../../api/financialResearch";
import { MAX_FINANCE_SCREEN_PRESETS, financeScreenPresetStorageKey, writeFinanceScreenPresets, type FinanceScreenPreset } from "./financeScreenPresets";

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

function metricValues(): string[] {
  return [...node.querySelectorAll("strong")].map((item) => item.textContent ?? "");
}

function buttonWithText(text: string): HTMLButtonElement {
  const button = Array.from(node.querySelectorAll("button")).find((item) => item.textContent?.includes(text));
  if (!button) throw new Error(`Button not found: ${text}`);
  return button;
}

function setInputValue(label: string, value: string) {
  const field = node.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
  if (!field) throw new Error(`Input not found: ${label}`);
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

async function chooseSelect(label: string, optionLabel: string) {
  const trigger = node.querySelector<HTMLElement>(`[data-vui-select-trigger="true"][aria-label="${label}"]`);
  if (!trigger) throw new Error(`Select not found: ${label}`);
  await act(async () => trigger.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 })));
  let option = Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]'))
    .find((item) => item.textContent?.includes(optionLabel));
  if (!option) {
    await act(async () => trigger.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    option = Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]'))
      .find((item) => item.textContent?.includes(optionLabel));
  }
  if (!option) throw new Error(`Option not found: ${optionLabel}`);
  await act(async () => option.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

const elementPrototype = Element.prototype as unknown as Record<string, unknown>;
if (typeof elementPrototype.hasPointerCapture !== "function") {
  elementPrototype.hasPointerCapture = () => false;
  elementPrototype.setPointerCapture = () => undefined;
  elementPrototype.releasePointerCapture = () => undefined;
}

beforeEach(() => {
  localStorage.clear();
  api.fetchScreen.mockReset().mockResolvedValue(screen);
  api.fetchResearch.mockReset().mockResolvedValue(research);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node);
});
afterEach(async () => {
  await act(async () => root?.unmount()); root = null; node.remove(); client.clear();
  localStorage.clear();
});

describe("FinanceMarketExplorer", () => {
  it("shows available fallback metrics with their verification limitation", async () => {
    api.fetchResearch.mockResolvedValue({
      ...research,
      fundamentals: { ...research.fundamentals, source: "东方财富 USF10", error: "SEC 财务核验暂不可用；以下为第三方备用数据，未经 SEC 核验。" },
    });
    await render("fundamentals");
    expect(node.textContent).toContain("来源限制");
    expect(node.textContent).toContain("未经 SEC 核验");
    expect(node.textContent).toContain("每股收益");
    expect(node.textContent).toContain("2.3元/股");
    expect(node.textContent).not.toContain("财务数据源暂不可用");
  });

  it("shows partial source coverage and supports stock selection and AI handoff", async () => {
    const onSelectStock = vi.fn(); const onResearchPrompt = vi.fn();
    await render("screen", { onSelectStock, onResearchPrompt });
    expect(node.textContent).toContain("2 / 5,571");
    expect(node.textContent).toContain("新浪 hs_a 行情池");
    expect(node.textContent).toContain("部分结果仅基于已加载项");
    expect(node.textContent).toContain("不等于全市场覆盖");
    expect(node.textContent).toContain("日期未提供");
    expect(node.textContent).not.toContain("市值单位尚未核实");
    await act(async () => buttonWithText("贵州茅台").click());
    expect(onSelectStock).toHaveBeenCalledWith(expect.objectContaining({ symbol: "sh600519" }));
    await act(async () => buttonWithText("AI研读").click());
    expect(onResearchPrompt).toHaveBeenCalledWith(expect.stringContaining("贵州茅台"));
    expect(node.textContent).not.toContain("987654321");
  });

  it("shows the source trading date when Sina provides one", async () => {
    api.fetchScreen.mockResolvedValue({ ...screen, dataDate: "2026-10-05" });
    await render("screen");
    expect(node.textContent).toContain("14:55:00 · 2026-10-05");
    expect(node.textContent).not.toContain("Date unavailable");
  });

  it("keeps the last successful screen and source timestamp after a refresh failure", async () => {
    await render("screen");
    api.fetchScreen.mockRejectedValueOnce(new Error("screen refresh failed"));
    await act(async () => buttonWithText("刷新").click());
    await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });

    expect(node.textContent).toContain("刷新失败，当前显示上次成功获取的数据");
    expect(node.textContent).toContain("screen refresh failed");
    expect(node.textContent).toContain("贵州茅台");
    expect(node.textContent).toContain("上次成功抓取 2026-10-05T01:00:00+00:00");

    await act(async () => buttonWithText("重试").click());
    await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(api.fetchScreen).toHaveBeenCalledTimes(3);
    expect(node.textContent).not.toContain("screen refresh failed");
  });

  it("disables only AI research when the native handoff is unavailable", async () => {
    const onResearchPrompt = vi.fn();
    await render("screen", { onResearchPrompt, researchDisabled: true });

    expect(api.fetchScreen).toHaveBeenCalledTimes(1);
    expect(buttonWithText("筛选").disabled).toBe(false);
    expect(node.querySelector<HTMLInputElement>('input[aria-label="最低 PB"]')?.disabled).toBe(false);
    expect(buttonWithText("AI研读").disabled).toBe(true);
    expect(node.querySelector('[role="note"]')?.getAttribute("aria-label")).toContain("研究会话忙碌或模型未就绪");
    await act(async () => buttonWithText("AI研读").click());
    expect(onResearchPrompt).not.toHaveBeenCalled();
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
    expect(metricValues()).toContain("2.3元/股");
    expect(metricValues()).not.toContain("没有这一项");
    expect(node.textContent).toContain("这组数字是东方财富快照，不是对照巨潮资讯原文核对过的数。");
  });

  it("hides a figure that has no report period or disclosure date", async () => {
    api.fetchResearch.mockResolvedValue({
      ...research,
      fundamentals: {
        ...research.fundamentals,
        reportDate: "2026-06-30",
        publishedAt: null,
        items: [
          { key: "EPSJB", label: "每股收益", value: 2.3, unit: "元/股", reportDate: "  ", publishedAt: " " },
          { key: "TOTALOPERATEREVE", label: "营业总收入", value: 8.8, unit: "元", reportDate: null, publishedAt: null },
        ],
      },
    });
    await render("fundamentals");
    expect(metricValues()).toEqual(["没有这一项", "没有这一项"]);
    expect(node.textContent).not.toContain("2.3");
    expect(node.textContent).not.toContain("8.8");
    expect(node.textContent).toContain("报告期 2026-06-30");
    expect(node.textContent).not.toContain("披露 2026");
  });

  it("uses the group dates when a metric leaves them blank", async () => {
    api.fetchResearch.mockResolvedValue({
      ...research,
      fundamentals: {
        ...research.fundamentals,
        items: [{ key: "EPSJB", label: "每股收益", value: 2.3, unit: "元/股", reportDate: null, publishedAt: "" }],
      },
    });
    await render("fundamentals");
    expect(metricValues()).toContain("2.3元/股");
    expect(node.textContent).toContain("披露 2026-08-28");
  });

  it("keeps a dash when a dated metric has no value", async () => {
    api.fetchResearch.mockResolvedValue({
      ...research,
      fundamentals: {
        ...research.fundamentals,
        items: [{ key: "EPSJB", label: "每股收益", value: null, unit: "元/股", reportDate: "2026-06-30", publishedAt: "2026-08-28" }],
      },
    });
    await render("fundamentals");
    expect(metricValues()).toEqual(["—"]);
  });

  it("links the stock annual report to the cninfo original", async () => {
    api.fetchResearch.mockResolvedValue({
      ...research,
      announcements: {
        ...research.announcements,
        source: "巨潮资讯",
        sourceUrl: "https://www.cninfo.com.cn/",
        items: [
          { title: "贵州茅台2025年年度报告", publishedAt: "2026-04-17", noticeDate: "2026-04-17", url: "https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF", articleCode: "cninfo-2026-04-17", publisher: "巨潮资讯" },
          { title: "关于召开股东大会的通知", publishedAt: "2026-05-01", noticeDate: "2026-05-01", url: "https://data.eastmoney.com/notices/detail/600519/AN202605010013.html", articleCode: "AN202605010013", publisher: "东方财富" },
          { title: "无来源标记", publishedAt: null, noticeDate: null, url: "https://data.eastmoney.com/notices/detail/600519/AN202605010014.html", articleCode: "AN202605010014", publisher: null },
        ],
      },
    });
    await render("news");
    const annual = node.querySelector('a[href="https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF"]');
    expect(annual?.textContent).toContain("贵州茅台2025年年度报告");
    expect(node.textContent).toContain("巨潮资讯");
    expect(node.textContent).toContain("东方财富");
    expect(node.textContent).toContain("公司公告");
    expect(node.textContent).not.toContain("年度报告摘要");
  });

  it("says when the annual-report original was not found", async () => {
    api.fetchResearch.mockResolvedValue({
      ...research,
      announcements: {
        ...research.announcements,
        error: "没有核到巨潮资讯年报原文，未列出年报转载。",
        items: [
          { title: "关于召开股东大会的通知", publishedAt: "2026-05-01", noticeDate: "2026-05-01", url: "https://data.eastmoney.com/notices/detail/600519/AN202605010013.html", articleCode: "AN202605010013", publisher: "东方财富" },
        ],
      },
    });
    await render("news");
    expect(node.textContent).toContain("没有核到巨潮资讯年报原文，未列出年报转载。");
    expect(node.textContent).toContain("关于召开股东大会的通知");
    expect(node.textContent).not.toContain("年度报告");
  });

  it("converts PB and turnover criteria to the provider contract and saves, loads, and removes presets", async () => {
    await render("screen", { agentId: "finance-agent-1" });
    await act(async () => {
      setInputValue("最低 PB", "1.25");
      setInputValue("最低成交额（亿元）", "12.5");
      setInputValue("预设名称", "低估值高成交");
    });
    await act(async () => buttonWithText("筛选").click());
    await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(api.fetchScreen).toHaveBeenLastCalledWith(
      expect.objectContaining({ minPb: 1.25, minTurnoverYuan: 1_250_000_000 }),
      expect.objectContaining({ signal: expect.anything() }),
    );

    await act(async () => buttonWithText("保存预设").click());
    expect(node.textContent).toContain("预设已保存");
    expect(buttonWithText("载入").disabled).toBe(false);
    expect(localStorage.getItem(financeScreenPresetStorageKey("finance-agent-1"))).toContain('"minPb":"1.25"');
    await act(async () => setInputValue("最低 PB", "2.5"));
    await act(async () => buttonWithText("载入").click());
    expect(node.textContent).toContain("已载入条件");
    expect(node.querySelector<HTMLInputElement>('input[aria-label="最低 PB"]')?.value).toBe("1.25");
    expect(node.querySelector<HTMLInputElement>('input[aria-label="最低成交额（亿元）"]')?.value).toBe("12.5");
    await act(async () => buttonWithText("删除").click());
    expect(localStorage.getItem(financeScreenPresetStorageKey("finance-agent-1"))).toBe("[]");
    await act(async () => buttonWithText("清除").click());
    await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
    const clearedFilters = api.fetchScreen.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    expect(clearedFilters).not.toHaveProperty("minPb");
    expect(clearedFilters).not.toHaveProperty("minTurnoverYuan");
  });

  it("rejects inverted ranges and prevents saving beyond the Agent preset limit", async () => {
    await render("screen", { agentId: "finance-agent-1" });
    const initialCalls = api.fetchScreen.mock.calls.length;
    await act(async () => {
      setInputValue("最低价", "20");
      setInputValue("最高价", "10");
    });
    await act(async () => buttonWithText("筛选").click());
    expect(node.textContent).toContain("股价下限不能大于上限");
    expect(api.fetchScreen).toHaveBeenCalledTimes(initialCalls);

    const presets: FinanceScreenPreset[] = Array.from({ length: MAX_FINANCE_SCREEN_PRESETS }, (_, index) => ({
      id: `saved-${index}`, name: `方案${index + 1}`, filters: {
        minPrice: "", maxPrice: "", minChangePercent: "", maxChangePercent: "", minPe: "", maxPe: "",
        minPb: "", maxPb: "", minVolumeLots: "", minTurnoverYi: "", maxTurnoverYi: "", sortBy: "changePercent", direction: "desc",
      },
    }));
    expect(writeFinanceScreenPresets("full-agent", presets)).toBe(true);
    await render("screen", { agentId: "full-agent" });
    await act(async () => setInputValue("预设名称", "第21组"));
    expect(buttonWithText("保存预设").disabled).toBe(true);
    expect(node.textContent).toContain(`${MAX_FINANCE_SCREEN_PRESETS}/${MAX_FINANCE_SCREEN_PRESETS}`);
  });

  it("retries a failed financial data source without leaving the stock", async () => {
    api.fetchResearch.mockResolvedValueOnce({ ...research, fundamentals: { ...research.fundamentals, status: "unavailable", items: [], error: "来源暂不可用" } });
    await render("fundamentals");
    expect(node.textContent).toContain("财务数据源暂不可用");
    await act(async () => buttonWithText("刷新资料").click());
    await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(api.fetchResearch).toHaveBeenCalledTimes(2);
    expect(api.fetchResearch).toHaveBeenLastCalledWith(stock.symbol, expect.objectContaining({ signal: expect.anything() }));
    expect(node.textContent).toContain("每股收益");
    expect(node.textContent).not.toContain("财务数据源暂不可用");
  });

  it("keeps cached fundamentals and retries after a failed source refresh", async () => {
    await render("fundamentals");
    api.fetchResearch.mockRejectedValueOnce(new Error("research refresh failed"));
    await act(async () => buttonWithText("刷新资料").click());
    await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });

    expect(node.textContent).toContain("刷新失败，当前显示上次成功获取的数据");
    expect(node.textContent).toContain("research refresh failed");
    expect(node.textContent).toContain("每股收益");
    expect(node.textContent).toContain("上次成功抓取 2026-10-05T01:00:00+00:00");

    await act(async () => buttonWithText("重试").click());
    await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(api.fetchResearch).toHaveBeenCalledTimes(3);
    expect(node.textContent).not.toContain("research refresh failed");
  });

  it("applies PB sorting in the selected direction", async () => {
    await render("screen");
    await chooseSelect("排序字段", "市净率");
    await chooseSelect("排序顺序", "从低到高");
    await act(async () => buttonWithText("筛选").click());
    await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(api.fetchScreen).toHaveBeenLastCalledWith(
      expect.objectContaining({ sortBy: "pbRatio", direction: "asc" }),
      expect.objectContaining({ signal: expect.anything() }),
    );
  });
});
