// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FinanceAIBacktest } from "./FinanceAIBacktest";
import { FinanceBacktest } from "./FinanceBacktest";
import type { AIBacktestDateCoverage, AIBacktestPreview, AIBacktestRun } from "../../api/types/financialBacktests";
import * as api from "../../api/financialBacktests";
import * as agentsApi from "../../api/agents";
import type { AgentConfigWorkspace } from "../../api/types/agents";

vi.mock("../../api/financialBacktests", async original => ({ ...await original<typeof import("../../api/financialBacktests")>(), fetchAIBacktests: vi.fn(), fetchAIBacktest: vi.fn(), previewAIBacktest: vi.fn(), previewForkAIBacktest: vi.fn(), compareAIBacktests: vi.fn(), startAIBacktest: vi.fn(), stopAIBacktest: vi.fn(), resumeAIBacktest: vi.fn() }));
vi.mock("../../api/agents", async original => ({ ...await original<typeof import("../../api/agents")>(), fetchAgentConfigWorkspace: vi.fn() }));
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
const selectableModels = {
  agentModelChoices: [
    { modelId: "model", modelRef: "provider/model", modelKey: "model", upstreamId: "model", label: "Model", model: "Model", providerId: "provider", providerLabel: "Provider", providerKind: "openai", providerBaseUrl: "", transport: "chat_completions", source: "pinned", runtimeSelectable: true, availability: "available", verificationStatus: "verified", catalogStale: false, slotCompatibility: { dialogue: { allowed: true, reasonCode: "" } }, capabilities: {}, apiKeyEnv: "", apiKeyConfigured: true, apiKeyState: "configured", requiresApiKey: true, missingApiKey: false, capabilityStatus: "verified", capabilitySource: "test" },
    { modelId: "other-model", modelRef: "provider/other-model", modelKey: "other-model", upstreamId: "other-model", label: "Other", model: "Other", providerId: "provider", providerLabel: "Provider", providerKind: "openai", providerBaseUrl: "", transport: "chat_completions", source: "pinned", runtimeSelectable: true, availability: "available", verificationStatus: "verified", catalogStale: false, slotCompatibility: { dialogue: { allowed: true, reasonCode: "" } }, capabilities: {}, apiKeyEnv: "", apiKeyConfigured: true, apiKeyState: "configured", requiresApiKey: true, missingApiKey: false, capabilityStatus: "verified", capabilitySource: "test" },
  ],
} as unknown as AgentConfigWorkspace;
const basketPreview: AIBacktestPreview = { ...preview, previewId: "basket-preview", symbol: null, symbols: basketSymbols, dateCoverage: coverage, assetCoverage: { "sh600519": coverage, "sz000001": { ...coverage, actualStartDate: "2026-07-02", tradingDays: 39 } }, assetSources: { "sh600519": { source: "Tencent", fetchedAt: "2026-10-08T15:00:00+08:00" }, "sz000001": { source: "Tencent", fetchedAt: "2026-10-08T15:00:00+08:00" } } };
const evaluationWindow = { startDate: "2026-07-01", endDate: "2026-07-30", baselineDate: null, startingEquity: 100000, startingBenchmarkEquity: 100000, tradingDays: 20, metrics: { ...metrics, tradeCount: 1, fees: 5 } };
const advancedEvaluation = {
  schemaVersion: 1 as const,
  basis: "frozen_decisions" as const,
  status: "available" as const,
  outOfSampleStartDate: "2026-08-01",
  costStress: { status: "available" as const, scenarios: [
    { id: "baseline" as const, status: "available" as const, costMultiplier: 1, commissionBps: 3, minimumCommission: 5, slippageBps: 5, metrics: { totalReturnPct: 4, benchmarkReturnPct: 2, excessReturnPct: 2, maxDrawdownPct: -1, tradeCount: 1, fees: 5 }, outOfSampleMetrics: null, error: null },
    { id: "cost_1_5x" as const, status: "available" as const, costMultiplier: 1.5, commissionBps: 4.5, minimumCommission: 7.5, slippageBps: 7.5, metrics: { totalReturnPct: 3, benchmarkReturnPct: 2, excessReturnPct: 1, maxDrawdownPct: -2, tradeCount: 1, fees: 7.5 }, outOfSampleMetrics: null, error: null },
    { id: "cost_2x" as const, status: "available" as const, costMultiplier: 2, commissionBps: 6, minimumCommission: 10, slippageBps: 10, metrics: { totalReturnPct: 2, benchmarkReturnPct: 1, excessReturnPct: 1, maxDrawdownPct: -3, tradeCount: 1, fees: 10 }, outOfSampleMetrics: null, error: null },
  ], notice: "冻结决策费用重放。" },
  returnUncertainty: { status: "insufficient_sample" as const, method: "newey_west_hac" as const, metric: "annualized_log_excess_return_pct" as const, confidenceLevel: 0.95, observations: 1, lag: null, pointEstimatePct: null, lowerPct: null, upperPct: null, error: "样本不足", notice: "只描述冻结历史序列。" },
  notice: "费用情景沿用已保存决策。",
};
const basketRun: AIBacktestRun = { ...run, runId: "basket-run", symbol: null, symbols: basketSymbols, status: "completed", decisionCount: 2, completedDecisionCount: 2, metrics, benchmarkStatus: "partial_cash_sleeves", unfilledBenchmarkSymbols: ["sz000001"], evaluation: { outOfSampleStartDate: "2026-08-01", inSample: evaluationWindow, outOfSample: { ...evaluationWindow, startDate: "2026-08-01", endDate: "2026-09-01", baselineDate: "2026-07-30", startingEquity: 104000, startingBenchmarkEquity: 102000 }, notice: "样本外以前一交易日收盘净值为基准。" }, advancedEvaluation, dateCoverage: coverage, assetCoverage: basketPreview.assetCoverage, assetSources: basketPreview.assetSources, decisions: [{ date: "2026-08-01", reason: "风险适中", targetWeights: { "sh600519": 60, "sz000001": 20 }, inputHash: "input", decisionHash: "decision", modelId: "model", attempts: 1, tokens: 500 }], equity: [{ date: "2026-09-01", equity: 104000, benchmarkEquity: 102000, cash: 20000, positions: { "sh600519": 100, "sz000001": 200 } }], orders: [{ date: "2026-08-02", symbol: "sh600519", side: "buy", status: "filled", reason: "next_session_open" }, { date: "2026-08-02", symbol: "sz000001", side: "buy", status: "filled", reason: "next_session_open" }], trades: [{ signalDate: "2026-08-01", date: "2026-08-02", symbol: "sh600519", side: "buy", price: 100, units: 100, fee: 5 }, { signalDate: "2026-08-01", date: "2026-08-02", symbol: "sz000001", side: "buy", price: 20, units: 200, fee: 5 }] };
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
async function chooseSelectOption(ariaLabel: string, label: string) {
  const trigger = document.body.querySelector<HTMLElement>(`[data-vui-select-trigger="true"][aria-label="${ariaLabel}"]`);
  if (!trigger) throw new Error(`Select not found: ${ariaLabel}`);
  await act(async () => trigger.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 })));
  let option = [...document.body.querySelectorAll<HTMLElement>('[role="option"]')].find(item => item.textContent?.includes(label));
  if (!option) {
    await act(async () => trigger.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    option = [...document.body.querySelectorAll<HTMLElement>('[role="option"]')].find(item => item.textContent?.includes(label));
  }
  if (!option) throw new Error(`Select option not found: ${label}`);
  await act(async () => option!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}
async function render(currentStock = stock) {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceAIBacktest agentId="a" stock={currentStock} zh disabled={false} /></QueryClientProvider>));
  await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
}
beforeEach(() => { vi.resetAllMocks(); node = document.createElement("div"); document.body.append(node); root = createRoot(node); client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [], nextCursor: null }); vi.mocked(agentsApi.fetchAgentConfigWorkspace).mockResolvedValue(selectableModels); });
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });

it("previews without a model call and refuses to start blocked corporate-action data", async () => {
  vi.mocked(api.previewAIBacktest).mockResolvedValue({ ...preview, canStart: false, actionsStatus: "blocked", blockReason: "区间内含公司行动" });
  await render(); await act(async () => button("检查数据与预算").click());
  expect(node.textContent).toContain("区间内含公司行动"); expect(button("开始AI回测").disabled).toBe(true); expect(api.startAIBacktest).not.toHaveBeenCalled();
});

it("submits the selected free Sina source without starting the model", async () => {
  vi.mocked(api.previewAIBacktest).mockResolvedValue(preview);
  await render();
  await chooseSelectOption("AI回测历史行情源", "新浪财经");
  await act(async () => button("检查数据与预算").click());
  expect(api.previewAIBacktest).toHaveBeenCalledWith("a", expect.objectContaining({ dataSource: "sina" }));
  expect(api.startAIBacktest).not.toHaveBeenCalled();
});

it("preflights the cash dividend policy and shows frozen coverage without starting a model", async () => {
  vi.mocked(api.previewAIBacktest).mockResolvedValue({ ...preview, corporateActionCoverage: { [stock.symbol]: { status: "complete", ruleVersion: "ashare_cash_dividend_v1", artifactHash: "a".repeat(64), startDate: "2026-07-01", endDate: "2026-09-01", eventCount: 2 } } });
  await render();
  await chooseSelectOption("AI回测公司行动", "核验现金分红");
  await act(async () => button("检查数据与预算").click());
  expect(api.previewAIBacktest).toHaveBeenCalledWith("a", expect.objectContaining({ corporateActionPolicy: "verified_cash_dividends" }));
  expect(node.textContent).toContain("现金分红 2 次 · 官方公告已冻结");
  expect(api.startAIBacktest).not.toHaveBeenCalled();
});

it("discloses strategy and benchmark dividend audit separately with an official source", async () => {
  const audit = { schemaVersion: 1 as const, ruleVersion: "ashare_cash_dividend_v1" as const, artifactHash: "a".repeat(64), symbol: stock.symbol,
    settlementRounding: "unverified_decimal_exact" as const, receivable: "50", taxPayable: "10", taxTotal: "10", dividendsTotal: "100", lots: [],
    events: [{ actionId: "cash-1", noticeId: "123", title: "权益分派实施公告", publishedDate: "2026-07-01", sourceUrl: "https://static.cninfo.com.cn/finalpage/2026-07-01/123.PDF", pdfSha256: "b".repeat(64), recordDate: "2026-07-10", exDate: "2026-07-13", paymentDate: "2026-07-14", cashPerShare: "0.5", recordCaptured: true, ledgerApplied: true, entitledShares: 200, grossAmount: "100", exRecognized: true, paymentComplete: false, taxPayable: "10", taxTotal: "10", taxPaid: "0" }] };
  const completed = { ...run, status: "completed" as const, metrics: { ...metrics, grossDividends: 100, dividendTaxPaid: 0, dividendTaxPayable: 10, benchmarkGrossDividends: 200 }, dividendAccounting: audit, benchmarkDividendAccounting: { ...audit, dividendsTotal: "200" }, equity: [{ date: "2026-07-13", equity: 104000, benchmarkEquity: 102000, cash: 20000, dividendReceivable: 50, dividendTaxPayable: 10 }] };
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ agentId: "a", items: [{ ...run, status: "completed", totalReturnPct: 4 }], nextCursor: null });
  vi.mocked(api.fetchAIBacktest).mockResolvedValue(completed);
  await render();
  await act(async () => button("已完成 · sz000001 · " + new Date(run.startedAt!).toLocaleString("zh-CN") + " · 0/8").click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
  expect(node.textContent).toContain("待到账 50.00");
  expect(node.textContent).toContain("待扣红利税 10.00");
  expect(node.querySelector('[aria-label="AI回测分红审计"]')).toBeNull();
  await act(async () => button("分红与红利税明细").click());
  expect(node.textContent).toContain("AI策略");
  expect(node.textContent).toContain("持有基准");
  expect(node.querySelector<HTMLAnchorElement>(`a[href="${audit.events[0].sourceUrl}"]`)?.rel).toContain("noreferrer");
});

it("allows independent backtest preflight when the native research session is unavailable", async () => {
  vi.mocked(api.previewAIBacktest).mockRejectedValue(new Error("回测模型配置需要检查"));
  const research = vi.fn();
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceBacktest agentId="a" stock={stock} zh disabled onResearchPrompt={research} /></QueryClientProvider>));
  await act(async () => button("检查数据与预算").click());
  expect(api.previewAIBacktest).toHaveBeenCalledTimes(1);
  expect(node.textContent).toContain("回测模型配置需要检查");
  expect(api.startAIBacktest).not.toHaveBeenCalled();
  expect(research).not.toHaveBeenCalled();
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
  expect(button("查看成本与统计评估")).toBeTruthy();
  await act(async () => button("查看成本与统计评估").click());
  expect(node.textContent).toContain("冻结决策重放");
  expect(node.textContent).toContain("费用 1.5×");
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

it("renders explicit advanced-evaluation unavailability for a legacy result without metrics", async () => {
  const reason = "没有可校验的冻结行情快照";
  const legacy: AIBacktestRun = {
    ...run,
    status: "completed",
    metrics: null,
    advancedEvaluation: {
      ...advancedEvaluation,
      status: "unavailable",
      error: reason,
      costStress: { ...advancedEvaluation.costStress, status: "unavailable", scenarios: [], error: reason },
      returnUncertainty: { ...advancedEvaluation.returnUncertainty, status: "unavailable", observations: 0, lag: null, pointEstimatePct: null, lowerPct: null, upperPct: null, error: reason },
    },
  };
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [legacy], nextCursor: null });
  vi.mocked(api.fetchAIBacktest).mockResolvedValue(legacy);
  await render();
  const historyEntry = [...node.querySelectorAll("button")].find(item => item.textContent?.startsWith("已完成 ·"));
  expect(historyEntry).toBeTruthy();
  await act(async () => historyEntry!.click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
  expect(button("查看成本与统计评估")).toBeTruthy();
  await act(async () => button("查看成本与统计评估").click());
  expect(node.textContent).toContain(reason);
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

it("creates a same-data fork from the selected run and starts only after a matching preview", async () => {
  const source = { ...run, runId: "source-run", status: "completed" as const, dataHash: "frozen-data", params: { strategy: "Source strategy", initialCash: 100000, maxPositionPct: 80, decisionInterval: 5, commissionBps: 3, minimumCommission: 5, slippageBps: 5, maxDecisions: 30, maxTokens: 60000 } };
  const forkPreview: AIBacktestPreview = { ...preview, previewId: "fork-preview", dataHash: "frozen-data", modelId: "model", comparisonProvenance: { contractVersion: "finance-ai-backtest-v1", commonParamsHash: "common", strategyHash: "strategy", sourceRunId: "source-run" } };
  const forkRun = { ...source, runId: "fork-run", dataHash: "frozen-data", status: "queued" as const };
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [source], nextCursor: null });
  vi.mocked(api.fetchAIBacktest).mockImplementation(async (_agentId, runId) => runId === "fork-run" ? forkRun : source);
  vi.mocked(api.previewForkAIBacktest).mockResolvedValue(forkPreview);
  vi.mocked(api.startAIBacktest).mockResolvedValue(forkRun);
  await render();
  await act(async () => [...node.querySelectorAll("button")].find(item => item.textContent?.startsWith("已完成 ·"))!.click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
  await act(async () => button("创建同数据副本").click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 20)));
  const strategyInput = document.body.querySelector<HTMLTextAreaElement>('textarea[aria-label="对照回测策略指令"]');
  expect(strategyInput?.value).toBe("Source strategy");
  await act(async () => button("同数据预检").click());
  expect(api.previewForkAIBacktest).toHaveBeenCalledWith("a", "source-run", { strategy: "Source strategy", modelId: "model", maxTokens: 60000 });
  expect(api.previewAIBacktest).not.toHaveBeenCalled();
  expect(button("开始对照回测").disabled).toBe(false);
  await act(async () => button("开始对照回测").click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
  expect(api.startAIBacktest).toHaveBeenCalledWith("a", "fork-preview", expect.any(String));
  expect(api.fetchAIBacktest).toHaveBeenCalledWith("a", "fork-run", expect.any(AbortSignal));
  expect(node.textContent).toContain("排队中");
});

it("previews a one-parameter A-share fork while preserving every other frozen input", async () => {
  const params = { strategy: "Source strategy", initialCash: 100000, maxPositionPct: 80, maxParticipationPct: 1, decisionInterval: 5, commissionBps: 3, minimumCommission: 5, slippageBps: 5, maxDecisions: 30, maxTokens: 60000 };
  const source = { ...run, runId: "source-run", status: "completed" as const, dataHash: "frozen-data", params, researchInput: "price_only" as const, researchHash: null, outOfSampleStartDate: "2026-08-01" };
  const forkPreview: AIBacktestPreview = {
    ...preview,
    previewId: "parameter-preview",
    dataHash: "frozen-data",
    maxTokens: 60000,
    modelId: "model",
    params: { ...params, maxPositionPct: 70 },
    researchInput: "price_only",
    researchHash: null,
    outOfSampleStartDate: "2026-08-01",
  };
  const forkRun = { ...source, runId: "parameter-run", status: "queued" as const, params: forkPreview.params };
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [source], nextCursor: null });
  vi.mocked(api.fetchAIBacktest).mockImplementation(async (_agentId, runId) => runId === "parameter-run" ? forkRun : source);
  vi.mocked(api.previewForkAIBacktest).mockResolvedValue(forkPreview);
  vi.mocked(api.startAIBacktest).mockResolvedValue(forkRun);
  await render();
  await act(async () => [...node.querySelectorAll("button")].find(item => item.textContent?.startsWith("已完成 ·"))!.click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
  await act(async () => button("创建同数据副本").click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 20)));
  await chooseSelectOption("回测副本用途", "单参数敏感性");
  expect(document.body.textContent).toContain("沿用源策略、模型与 Token 预算");
  await chooseSelectOption("参数敏感性目标", "持仓上限");
  const parameterInput = document.body.querySelector<HTMLInputElement>('input[aria-label="参数敏感性取值"]');
  expect(parameterInput).toBeTruthy();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(parameterInput, "70");
    parameterInput!.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(button("同数据预检").disabled).toBe(false);
  await act(async () => button("同数据预检").click());
  expect(api.previewForkAIBacktest).toHaveBeenCalledWith("a", "source-run", { maxPositionPct: 70 });
  expect(api.previewAIBacktest).not.toHaveBeenCalled();
  expect(button("开始对照回测").disabled).toBe(false);
  await act(async () => button("开始对照回测").click());
  expect(api.startAIBacktest).toHaveBeenCalledWith("a", "parameter-preview", expect.any(String));
});

it("requires an explicit eligible model when the source model is no longer selectable", async () => {
  const source = { ...run, runId: "source-run", status: "completed" as const, dataHash: "frozen-data", params: { strategy: "Source strategy", initialCash: 100000, maxPositionPct: 80, decisionInterval: 5, commissionBps: 3, minimumCommission: 5, slippageBps: 5, maxDecisions: 30, maxTokens: 60000 } };
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [source], nextCursor: null });
  vi.mocked(api.fetchAIBacktest).mockResolvedValue(source);
  vi.mocked(agentsApi.fetchAgentConfigWorkspace).mockResolvedValue({ ...selectableModels, agentModelChoices: selectableModels.agentModelChoices.filter(model => model.modelId === "other-model") });
  await render();
  await act(async () => [...node.querySelectorAll("button")].find(item => item.textContent?.startsWith("已完成 ·"))!.click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 15)));
  await act(async () => button("创建同数据副本").click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 20)));
  expect(document.body.textContent).toContain("源模型当前不可用于对话回测");
  expect(button("同数据预检").disabled).toBe(true);
  expect(api.previewForkAIBacktest).not.toHaveBeenCalled();
  vi.mocked(api.previewForkAIBacktest).mockResolvedValue({ ...preview, previewId: "other-model-preview", modelId: "other-model", dataHash: "frozen-data" });
  const trigger = document.body.querySelector<HTMLElement>('[data-vui-select-trigger="true"][aria-label="对照回测模型"]');
  expect(trigger).toBeTruthy();
  await act(async () => trigger!.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 })));
  let option = [...document.body.querySelectorAll<HTMLElement>('[role="option"]')].find(item => item.textContent?.includes("Provider · Other"));
  if (!option) {
    await act(async () => trigger!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    option = [...document.body.querySelectorAll<HTMLElement>('[role="option"]')].find(item => item.textContent?.includes("Provider · Other"));
  }
  expect(option).toBeTruthy();
  await act(async () => option!.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await act(async () => button("同数据预检").click());
  expect(api.previewForkAIBacktest).toHaveBeenCalledWith("a", "source-run", { strategy: "Source strategy", modelId: "other-model", maxTokens: 60000 });
});

it("compares selected history and only exposes metrics for a comparable response", async () => {
  const first = { ...run, runId: "compare-1", status: "completed" as const, dataHash: "frozen-data" };
  const second = { ...run, runId: "compare-2", status: "completed" as const, dataHash: "frozen-data" };
  const comparison = {
    comparisonId: "comparison-1", axis: "strategy" as const, status: "comparable" as const, reasons: [], dataHash: "frozen-data", commonParamsHash: "same-inputs", outOfSampleStartDate: "2026-08-01",
    rows: [
      { runId: "compare-1", status: "completed", modelId: "model", modelConfigHash: null, strategy: "Strategy one", strategyHash: "one", callsUsed: 1, tokensUsed: 50, maxTokens: 60000, metrics, evaluation: { outOfSampleStartDate: "2026-08-01", inSample: evaluationWindow, outOfSample: { ...evaluationWindow, metrics: { ...metrics, totalReturnPct: 7, excessReturnPct: 5, maxDrawdownPct: -2 } }, notice: "holdout" } },
      { runId: "compare-2", status: "completed", modelId: "model", modelConfigHash: null, strategy: "Strategy two", strategyHash: "two", callsUsed: 1, tokensUsed: 60, maxTokens: 60000, metrics: { ...metrics, totalReturnPct: 5 }, evaluation: { outOfSampleStartDate: "2026-08-01", inSample: evaluationWindow, outOfSample: { ...evaluationWindow, metrics: { ...metrics, totalReturnPct: 3, excessReturnPct: 1, maxDrawdownPct: -4 } }, notice: "holdout" } },
    ],
    notice: "比较仅供历史检验",
  };
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [first, second], nextCursor: null });
  vi.mocked(api.compareAIBacktests).mockResolvedValue(comparison);
  await render();
  await act(async () => button("对照历史结果").click());
  const firstCheckbox = document.body.querySelector<HTMLInputElement>('input[aria-label="选择回测 compare-1"]');
  const secondCheckbox = document.body.querySelector<HTMLInputElement>('input[aria-label="选择回测 compare-2"]');
  expect(firstCheckbox).toBeTruthy();
  await act(async () => firstCheckbox!.click());
  await act(async () => secondCheckbox!.click());
  await act(async () => button("生成比较").click());
  expect(api.compareAIBacktests).toHaveBeenCalledWith("a", { runIds: ["compare-1", "compare-2"], axis: "strategy" });
  expect(document.body.textContent).toContain("7.00%");
  expect(document.body.textContent).toContain("样本外超额");

  vi.mocked(api.compareAIBacktests).mockResolvedValue({ ...comparison, status: "incompatible", reasons: [{ code: "different_data", runIds: ["compare-2"], message: "冻结数据不同" }] });
  await act(async () => button("生成比较").click());
  expect(document.body.textContent).toContain("冻结数据不同");
  expect(document.body.textContent).not.toContain("7.00%");
});

it("compares A-share runs on one parameter and labels each run's actual value", async () => {
  const params = { strategy: "Same strategy", initialCash: 100000, maxPositionPct: 80, decisionInterval: 5, commissionBps: 3, minimumCommission: 5, slippageBps: 5, maxDecisions: 30, maxTokens: 60000 };
  const records = [
    { ...run, runId: "parameter-1", status: "completed" as const, dataHash: "frozen-data", params },
    { ...run, runId: "parameter-2", status: "completed" as const, dataHash: "frozen-data", params: { ...params, maxPositionPct: 70 } },
  ];
  const comparison = {
    comparisonId: "parameter-comparison",
    axis: "parameter" as const,
    parameterKey: "maxPositionPct" as const,
    status: "comparable" as const,
    reasons: [],
    dataHash: "frozen-data",
    commonParamsHash: "same-inputs",
    outOfSampleStartDate: "2026-08-01",
    rows: [
      { runId: "parameter-1", status: "completed", modelId: "model", modelConfigHash: null, strategy: "Same strategy", strategyHash: "same", callsUsed: 1, tokensUsed: 50, maxTokens: 60000, parameterValue: 80, metrics, evaluation: null },
      { runId: "parameter-2", status: "completed", modelId: "model", modelConfigHash: null, strategy: "Same strategy", strategyHash: "same", callsUsed: 1, tokensUsed: 60, maxTokens: 60000, parameterValue: 70, metrics: { ...metrics, totalReturnPct: 2 }, evaluation: null },
    ],
    notice: "单参数历史对照，不作胜者判断。",
  };
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: records, nextCursor: null });
  vi.mocked(api.compareAIBacktests).mockResolvedValue(comparison);
  await render();
  await act(async () => button("对照历史结果").click());
  await act(async () => document.body.querySelector<HTMLInputElement>('input[aria-label="选择回测 parameter-1"]')!.click());
  await act(async () => document.body.querySelector<HTMLInputElement>('input[aria-label="选择回测 parameter-2"]')!.click());
  await chooseSelectOption("回测比较维度", "单参数");
  await chooseSelectOption("回测比较参数", "持仓上限");
  await act(async () => button("生成比较").click());
  expect(api.compareAIBacktests).toHaveBeenCalledWith("a", { runIds: ["parameter-1", "parameter-2"], axis: "parameter", parameterKey: "maxPositionPct" });
  expect(document.body.textContent).toContain("持仓上限（%）");
  expect(document.body.textContent).toContain("80");
  expect(document.body.textContent).toContain("70");
  expect(document.body.textContent).toContain("4.00%");
});

it("locks comparison inputs during a request and unlocks them after failure", async () => {
  const records = ["compare-1", "compare-2"].map(runId => ({ ...run, runId, status: "completed" as const }));
  vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: records, nextCursor: null });
  let rejectRequest!: (cause: Error) => void;
  vi.mocked(api.compareAIBacktests).mockImplementation(() => new Promise((_resolve, reject) => { rejectRequest = reject; }));
  await render();
  await act(async () => button("对照历史结果").click());
  for (const record of records) {
    await act(async () => document.body.querySelector<HTMLInputElement>(`input[aria-label="选择回测 ${record.runId}"]`)!.click());
  }
  await act(async () => button("生成比较").click());
  const axis = document.body.querySelector<HTMLButtonElement>('[data-vui-select-trigger="true"][aria-label="回测比较维度"]')!;
  expect(axis.disabled).toBe(true);
  await act(async () => rejectRequest(new Error("比较服务暂时不可用")));
  expect(axis.disabled).toBe(false);
  expect(button("生成比较").disabled).toBe(false);
  expect(document.body.textContent).toContain("比较服务暂时不可用");
});
