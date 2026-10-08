// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { checkFinancialClaim, fetchFinancialClaims, fetchFinancialFeedback, runFinancialBacktest } from "../../api/financialEvaluation";
import type { FinancialClaim } from "../../api/types/financialEvaluation";
import { FinanceOutcomeReview } from "./FinanceOutcomeReview";
import { FinanceBacktest } from "./FinanceBacktest";

vi.mock("../../api/financialEvaluation", async importOriginal => ({ ...await importOriginal<typeof import("../../api/financialEvaluation")>(), fetchFinancialClaims: vi.fn(), checkFinancialClaim: vi.fn(), fetchFinancialFeedback: vi.fn(), runFinancialBacktest: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let cleanup = async () => {};
afterEach(async () => { await cleanup(); vi.resetAllMocks(); });
async function mount(component: React.ReactNode) {
  const node = document.createElement("div"), root = createRoot(node), client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); document.body.append(node);
  cleanup = async () => { await act(async () => root.unmount()); client.clear(); node.remove(); };
  await act(async () => root.render(<QueryClientProvider client={client}>{component}</QueryClientProvider>));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); });
  return node;
}
const row = (overrides: Partial<FinancialClaim> = {}): FinancialClaim => ({ id: "claim-1", agentId: "a", sessionId: "s", turnId: "t", symbol: "sz000001", analysisDate: "2026-09-01", dueDate: "2026-10-01", direction: "up", thresholdPct: 2, claimText: "上涨至少2%", status: "verified", registeredBeforeDue: true, retrospective: false, outcome: "hit", checkedAt: "2026-10-02", revision: 1, evidence: { baseDate: "2026-09-01", baseClose: 10, dueDateQuoteDate: "2026-09-30", dueClose: 11, returnPct: 10, sourceUrl: "https://gu.qq.com/sz000001/gp", fetchedAt: "2026-10-02", seriesHash: "hash" }, error: null, lesson: null, ...overrides });

it("excludes retrospective hits and starts reflection with exact verified evidence", async () => {
  vi.mocked(fetchFinancialClaims).mockResolvedValue({ agentId: "a", items: [row(), row({ id: "late", retrospective: true, registeredBeforeDue: false })], limit: 100 });
  vi.mocked(fetchFinancialFeedback).mockResolvedValue({ id: "claim-1", text: "原生复盘请求，引用s/t及真实核验" });
  const launch = vi.fn(), open = vi.fn();
  const node = await mount(<FinanceOutcomeReview agentId="a" zh disabled={false} onResearchPrompt={launch} onOpenReport={open} />);
  expect(node.textContent).toContain("事前登记 1 · 命中 1");
  expect(node.textContent).toContain("事后回顾");
  const buttons = [...node.querySelectorAll("button")];
  await act(async () => buttons.find(button => button.textContent === "开始AI复盘")?.click());
  expect(fetchFinancialFeedback).toHaveBeenCalledWith("a", "claim-1");
  expect(launch).toHaveBeenCalledWith("原生复盘请求，引用s/t及真实核验");
  await act(async () => buttons.find(button => button.textContent === "原报告")?.click());
  expect(open).toHaveBeenCalledWith(expect.objectContaining({ sessionId: "s", turnId: "t" }));
});

it("keeps missing-data checks retryable and prevents feedback from unverifiable outcomes", async () => {
  vi.mocked(fetchFinancialClaims).mockResolvedValue({ agentId: "a", items: [row({ status: "unverifiable", outcome: null, evidence: null, error: { code: "coverage", unavailableReason: "日线覆盖不足" } })], limit: 100 });
  vi.mocked(checkFinancialClaim).mockRejectedValue(new Error("行情暂不可用"));
  const node = await mount(<FinanceOutcomeReview agentId="a" zh disabled={false} onResearchPrompt={vi.fn()} onOpenReport={vi.fn()} />);
  const buttons = [...node.querySelectorAll("button")];
  expect(buttons.find(button => button.textContent === "开始AI复盘")?.disabled).toBe(true);
  await act(async () => buttons.find(button => button.textContent === "核验 / 重试")?.click());
  expect(checkFinancialClaim).toHaveBeenCalledWith("a", "claim-1");
  expect(node.textContent).toContain("行情暂不可用");
  expect(node.textContent).toContain("日线覆盖不足");
});

it("backtest failure shows real coverage error and never fabricates an equity result", async () => {
  vi.mocked(runFinancialBacktest).mockRejectedValue(new Error("所选起始日不足预热数据"));
  const node = await mount(<FinanceBacktest agentId="a" stock={{ symbol: "sz000001", ticker: "000001", name: "平安银行", market: "深交所" }} zh disabled={false} onResearchPrompt={vi.fn()} />);
  await act(async () => [...node.querySelectorAll("button")].find(button => button.textContent === "运行回测")?.click());
  expect(node.textContent).toContain("所选起始日不足预热数据");
  expect(node.querySelector("svg[role=img]")).toBeNull();
  expect(runFinancialBacktest).toHaveBeenCalledWith("a", expect.objectContaining({ symbol: "sz000001", window: 20, commissionBps: 3, slippageBps: 5 }));
});

it("does not create a research session from a late feedback response after leaving the panel", async () => {
  vi.mocked(fetchFinancialClaims).mockResolvedValue({ agentId: "a", items: [row()], limit: 100 });
  let settle!: (value: { id: string; text: string }) => void;
  vi.mocked(fetchFinancialFeedback).mockImplementation(() => new Promise(resolve => { settle = resolve; }));
  const launch = vi.fn();
  const node = await mount(<FinanceOutcomeReview agentId="a" zh disabled={false} onResearchPrompt={launch} onOpenReport={vi.fn()} />);
  await act(async () => [...node.querySelectorAll("button")].find(button => button.textContent === "开始AI复盘")?.click());
  await cleanup(); cleanup = async () => {};
  await act(async () => settle({ id: "claim-1", text: "late response" }));
  expect(launch).not.toHaveBeenCalled();
});

it("uses a short but sufficient daily series as the default range", async () => {
  const dates = Array.from({ length: 35 }, (_, index) => new Date(Date.UTC(2026, 6, index + 1)).toISOString().slice(0, 10));
  const node = await mount(<FinanceBacktest agentId="a" stock={{ symbol: "sz000001", ticker: "000001", name: "平安银行", market: "深交所" }} availableDates={dates} zh disabled={false} onResearchPrompt={vi.fn()} />);
  expect(node.querySelector<HTMLInputElement>("input[aria-label='回测开始日期']")?.value).toBe(dates[20]);
  expect(node.querySelector<HTMLInputElement>("input[aria-label='回测结束日期']")?.value).toBe(dates[34]);
});
