// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FinanceAIBacktest } from "./FinanceAIBacktest";
import type { AIBacktestPreview, AIBacktestRun } from "../../api/types/financialBacktests";
import * as api from "../../api/financialBacktests";

vi.mock("../../api/financialBacktests", async original => ({ ...await original<typeof import("../../api/financialBacktests")>(), fetchAIBacktests: vi.fn(), fetchAIBacktest: vi.fn(), previewAIBacktest: vi.fn(), startAIBacktest: vi.fn(), stopAIBacktest: vi.fn(), resumeAIBacktest: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, node: HTMLDivElement, client: QueryClient;
const stock = { symbol: "sz000001", ticker: "000001", name: "平安银行", market: "深交所" };
const preview: AIBacktestPreview = { agentId: "a", previewId: "preview", symbol: stock.symbol, expiresAt: "2099-01-01", modelId: "model", dateCoverage: { requestedStartDate: "2026-07-01", requestedEndDate: "2026-09-01", actualStartDate: "2026-07-01", actualEndDate: "2026-09-01", availableStartDate: "2026-06-01", availableEndDate: "2026-09-01", tradingDays: 40, warmupBars: 20, providerWindows: [{ startDate: "2026-01-01", endDate: "2026-12-31", rawBars: 80, qfqBars: 80, calendarBars: 80 }], complete: true }, decisionCount: 8, maxDecisions: 30, maxTokens: 60000, paramsHash: "params", dataHash: "data", actionsStatus: "clear", canStart: true, blockReason: null, warnings: [] };
const run: AIBacktestRun = { runId: "run", agentId: "a", symbol: stock.symbol, status: "running", progress: 0, currentDecisionDate: "2026-07-01", decisionCount: 8, completedDecisionCount: 0, callsUsed: 0, tokensUsed: 0, maxTokens: 60000, modelId: "model", paramsHash: "p", dataHash: "d", decisions: [], metrics: null, equity: [], orders: [], trades: [], startedAt: "2026-10-08", updatedAt: "2026-10-08", completedAt: null, terminalReason: null };
const button = (text: string) => [...document.querySelectorAll("button")].find(item => item.textContent === text)!;
async function render() { await act(async () => root.render(<QueryClientProvider client={client}><FinanceAIBacktest agentId="a" stock={stock} zh disabled={false} /></QueryClientProvider>)); await act(async () => new Promise(resolve => setTimeout(resolve, 15))); }
beforeEach(() => { vi.resetAllMocks(); node = document.createElement("div"); document.body.append(node); root = createRoot(node); client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); vi.mocked(api.fetchAIBacktests).mockResolvedValue({ items: [], nextCursor: null }); });
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

it("loads a persisted run and stops exactly that run", async () => {
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
