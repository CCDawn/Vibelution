// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FinanceAIBacktest } from "./FinanceAIBacktest";
import type { AIBacktestDateCoverage, AIBacktestPreview, AIBacktestRun } from "../../api/types/financialBacktests";
import * as api from "../../api/financialBacktests";

vi.mock("../../api/financialBacktests", async original => ({ ...await original<typeof import("../../api/financialBacktests")>(), fetchAIBacktests: vi.fn(), fetchAIBacktest: vi.fn(), previewAIBacktest: vi.fn(), startAIBacktest: vi.fn(), stopAIBacktest: vi.fn(), resumeAIBacktest: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const elementPrototype = Element.prototype as unknown as Record<string, unknown>;
if (typeof elementPrototype.hasPointerCapture !== "function") {
  elementPrototype.hasPointerCapture = () => false;
  elementPrototype.setPointerCapture = () => undefined;
  elementPrototype.releasePointerCapture = () => undefined;
}
let root: Root, node: HTMLDivElement, client: QueryClient;
const stock = { symbol: "sz000001", ticker: "000001", name: "平安银行", market: "深交所" };
const coverage: AIBacktestDateCoverage = { requestedStartDate: "2026-07-01", requestedEndDate: "2026-09-01", actualStartDate: "2026-07-01", actualEndDate: "2026-09-01", availableStartDate: "2026-06-01", availableEndDate: "2026-09-01", tradingDays: 40, warmupBars: 20, providerWindows: [{ startDate: "2026-01-01", endDate: "2026-12-31", rawBars: 80, qfqBars: 80, calendarBars: 80 }], complete: true };
const preview: AIBacktestPreview = { agentId: "a", previewId: "preview", symbol: stock.symbol, expiresAt: "2099-01-01", modelId: "model", dateCoverage: coverage, outOfSampleStartDate: "2026-08-01", decisionCount: 8, maxDecisions: 30, maxTokens: 60000, paramsHash: "params", dataHash: "data", actionsStatus: "clear", warnings: [], canStart: true, blockReason: null };
const metrics = { totalReturnPct: 4, benchmarkReturnPct: 2, excessReturnPct: 2, maxDrawdownPct: -1, tradeCount: 2, fees: 10, annualizedReturnPct: 4, sharpeRatio: 1.2, winRatePct: 50 };
const run: AIBacktestRun = { runId: "run", agentId: "a", symbol: stock.symbol, status: "running", progress: 0, currentDecisionDate: "2026-07-01", decisionCount: 8, completedDecisionCount: 0, callsUsed: 0, tokensUsed: 0, maxTokens: 60000, modelId: "model", paramsHash: "p", dataHash: "d", decisions: [], metrics: null, equity: [], orders: [], trades: [], startedAt: "2026-10-08", updatedAt: "2026-10-08", completedAt: null, terminalReason: null };
const basketSymbols = ["sh600519", "sz000001"];
const basketPreview: AIBacktestPreview = { ...preview, previewId: "basket-preview", symbol: null, symbols: basketSymbols, dateCoverage: coverage, assetCoverage: { "sh600519": coverage, "sz000001": { ...coverage, actualStartDate: "2026-07-02", tradingDays: 39 } }, assetSources: { "sh600519": { source: "Tencent", fetchedAt: "2026-10-08T15:00:00+08:00" }, "sz000001": { source: "Tencent", fetchedAt: "2026-10-08T15:00:00+08:00" } } };
const evaluationWindow = { startDate: "2026-07-01", endDate: "2026-07-30", baselineDate: null, startingEquity: 100000, startingBenchmarkEquity: 100000, tradingDays: 20, metrics: { ...metrics, tradeCount: 1, fees: 5 } };
const basketRun: AIBacktestRun = { ...run, runId: "basket-run", symbol: null, symbols: basketSymbols, status: "completed", decisionCount: 2, completedDecisionCount: 2, metrics, benchmarkStatus: "partial_cash_sleeves", unfilledBenchmarkSymbols: ["sz000001"], evaluation: { outOfSampleStartDate: "2026-08-01", inSample: evaluationWindow, outOfSample: { ...evaluationWindow, startDate: "2026-08-01", endDate: "2026-09-01", baselineDate: "2026-07-30", startingEquity: 104000, startingBenchmarkEquity: 102000 }, notice: "样本外以前一交易日收盘净值为基准。" }, dateCoverage: coverage, assetCoverage: basketPreview.assetCoverage, assetSources: basketPreview.assetSources, decisions: [{ date: "2026-08-01", reason: "风险适中", targetWeights: { "sh600519": 60, "sz000001": 20 }, inputHash: "input", decisionHash: "decision", modelId: "model", attempts: 1, tokens: 500 }], equity: [{ date: "2026-09-01", equity: 104000, benchmarkEquity: 102000, cash: 20000, positions: { "sh600519": 100, "sz000001": 200 } }], orders: [{ date: "2026-08-02", symbol: "sh600519", side: "buy", status: "filled", reason: "next_session_open" }, { date: "2026-08-02", symbol: "sz000001", side: "buy", status: "filled", reason: "next_session_open" }], trades: [{ signalDate: "2026-08-01", date: "2026-08-02", symbol: "sh600519", side: "buy", price: 100, units: 100, fee: 5 }, { signalDate: "2026-08-01", date: "2026-08-02", symbol: "sz000001", side: "buy", price: 20, units: 200, fee: 5 }] };
const button = (text: string) => [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === text)!;
const setInputValue = (label: string, value: string) => {
  const input = node.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
  if (!input) throw new Error(`Input not found: ${label}`);
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
};
async function chooseScope(label: string) {
  const trigger = node.querySelector<HTMLElement>('[data-vui-select-trigger="true"][aria-label="AI回测范围"]');
  if (!trigger) throw new Error("Scope selector not found");
  await act(async () => trigger.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 })));
  let option = [...document.body.querySelectorAll<HTMLElement>('[role="option"]')].find(item => item.textContent?.includes(label));
  if (!option) {
    await act(async () => trigger.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    option = [...document.body.querySelectorAll<HTMLElement>('[role="option"]')].find(item => item.textContent?.includes(label));
  }
  if (!option) throw new Error(`Scope option not found: ${label}`);
  await act(async () => option!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}
async function render(currentStock = stock) {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceAIBacktest agentId="a" stock={currentStock} zh disabled={false} /></QueryClientProvider>));
  await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
}
beforeEach(() => { vi.resetAllMocks(); node = document.createElement("div"); document.body.append(node); root = createRoot(node); client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [], nextCursor: null }); });
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });

it("previews without a model call and refuses to start blocked corporate-action data", async () => {
  vi.mocked(api.previewAIBacktest).mockResolvedValue({ ...preview, canStart: false, actionsStatus: "blocked", blockReason: "区间内含公司行动" });
  await render(); await act(async () => button("检查数据与预算").click());
  expect(node.textContent).toContain("区间内含公司行动"); expect(button("开始AI回测").disabled).toBe(true); expect(api.startAIBacktest).not.toHaveBeenCalled();
});

it("deduplicates a double click and retains the idempotency key after an ambiguous start failure", async () => {
  vi.mocked(api.previewAIBacktest).mockResolvedValue(preview);
  let reject!: (error: Error) => void;
  vi.mocked(api.startAIBacktest).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; })).mockRejectedValue(new Error("网络断开"));
  await render(); await act(async () => button("检查数据与预算").click());
  await act(async () => { button("开始AI回测").click(); button("开始AI回测").click(); });
  expect(api.startAIBacktest).toHaveBeenCalledTimes(1);
  const firstKey = vi.mocked(api.startAIBacktest).mock.calls[0][2];
  await act(async () => reject(new Error("网络断开"))); await act(async () => button("开始AI回测").click());
  expect(api.startAIBacktest).toHaveBeenLastCalledWith("a", "preview", firstKey);
});

it("runs a two-stock basket, displays frozen holdout and per-asset audit, and keeps symbol-specific fills", async () => {
  vi.mocked(api.previewAIBacktest).mockResolvedValue(basketPreview);
  vi.mocked(api.startAIBacktest).mockResolvedValue(basketRun);
  vi.mocked(api.fetchAIBacktest).mockResolvedValue(basketRun);
  await render(); await chooseScope("组合");
  await act(async () => setInputValue("组合股票代码", "600519, 000001"));
  await act(async () => button("检查数据与预算").click());
  expect(api.previewAIBacktest).toHaveBeenCalledTimes(1);
  const request = vi.mocked(api.previewAIBacktest).mock.calls[0][1];
  expect("symbols" in request ? request.symbols : []).toEqual(["sh600519", "sz000001"]);
  expect("symbol" in request ? request.symbol : undefined).toBeUndefined();
  expect(node.textContent).toContain("样本外起点 2026-08-01"); expect(node.textContent).toContain("sh600519"); expect(node.textContent).toContain("sz000001");
  await act(async () => button("开始AI回测").click());
  expect(api.startAIBacktest).toHaveBeenCalledWith("a", "basket-preview", expect.any(String));
  expect(node.textContent).toContain("样本内外评估"); expect(node.textContent).toContain("sh600519 60.00%"); expect(node.textContent).toContain("sz000001 20.00%");
  expect(node.textContent).toContain("期末股数"); expect(node.textContent).toContain("样本外以前一交易日收盘净值为基准。"); expect(node.textContent).toContain("基准有 1 只未成交，保留现金：sz000001");
});

it("keeps portfolio history available after the current stock changes", async () => {
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [basketRun], nextCursor: null }); vi.mocked(api.fetchAIBacktest).mockResolvedValue(basketRun);
  await render();
  const historyEntry = [...node.querySelectorAll("button")].find(item => item.textContent?.startsWith("已完成 · 组合"));
  expect(historyEntry).toBeTruthy();
  await act(async () => historyEntry!.click()); await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
  await render({ symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" });
  expect(node.textContent).toContain("已完成 · 组合"); expect(node.textContent).toContain("sh600519 60.00%");
});

it("invalidates a preview when its form changes", async () => {
  vi.mocked(api.previewAIBacktest).mockResolvedValue(preview);
  await render(); await act(async () => button("检查数据与预算").click());
  expect([...node.querySelectorAll("button")].some(item => item.textContent?.trim() === "开始AI回测")).toBe(true);
  await act(async () => setInputValue("AI回测样本外起点", "2026-08-02"));
  expect([...node.querySelectorAll("button")].some(item => item.textContent?.trim() === "开始AI回测")).toBe(false);
});

it("loads a persisted single-stock run and stops that exact run", async () => {
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [run], nextCursor: null }); vi.mocked(api.fetchAIBacktest).mockResolvedValue(run);
  vi.mocked(api.stopAIBacktest).mockResolvedValue({ ...run, status: "stop_requested" });
  await render(); await act(async () => [...node.querySelectorAll("button")].find(item => item.textContent?.startsWith("运行中 ·"))!.click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
  await act(async () => button("停止").click()); expect(api.stopAIBacktest).toHaveBeenCalledWith("a", "run"); expect(node.textContent).toContain("正在停止");
});

it("requires exact date and duplicate-charge confirmation before retrying an uncertain call", async () => {
  const uncertain = { ...run, status: "paused_unknown" as const, terminalReason: "调用结果没有落盘" };
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [uncertain], nextCursor: null }); vi.mocked(api.fetchAIBacktest).mockResolvedValue(uncertain); vi.mocked(api.resumeAIBacktest).mockResolvedValue(run);
  await render(); await act(async () => [...node.querySelectorAll("button")].find(item => item.textContent?.startsWith("调用结果待确认 ·"))!.click()); await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
  await act(async () => button("继续未完成部分").click()); expect(api.resumeAIBacktest).not.toHaveBeenCalled();
  await act(async () => button("确认可能重复计费并重试").click());
  expect(api.resumeAIBacktest).toHaveBeenCalledWith("a", "run", { retryUnknownDecisionDate: "2026-07-01", confirmPossibleDuplicateCharge: true });
});
