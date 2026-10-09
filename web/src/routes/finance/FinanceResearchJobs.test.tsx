// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FinanceResearchJobs } from "./FinanceResearchJobs";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { FinancialResearchBatch } from "../../api/financialJobs";
import type { FinanceProposalBatchImport } from "./financeProposalImportModel";

const api = vi.hoisted(() => ({ schedules: vi.fn(), batches: vi.fn(), create: vi.fn(), patch: vi.fn(), stop: vi.fn(), retry: vi.fn() }));
vi.mock("../../api/financialJobs", () => ({ fetchFinancialResearchSchedules: api.schedules, fetchFinancialResearchBatches: api.batches, createFinancialResearchSchedule: api.create, updateFinancialResearchSchedule: api.patch, stopFinancialResearchBatch: api.stop, retryFinancialResearchBatch: api.retry }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const assistant = { agentId: "finance", setupStatus: "ready", modelStatus: "configured_unverified" } as FinancialAssistant;
const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
const open = vi.fn(); let root: Root, client: QueryClient, node: HTMLDivElement;
function batch(status: FinancialResearchBatch["status"]): FinancialResearchBatch {
  return { batchId: "batch", scheduleId: "schedule", assistantAgentId: "finance", status, triggeredAt: "2026-10-06T12:00:00+08:00", updatedAt: "2026-10-06T12:00:00+08:00", researchDate: "2026-10-06", periodDays: 30, depth: "brief", symbols: ["sh600519", "sz000001"], terminalReason: null, items: [{ symbol: "sh600519", status: "completed", runId: "earlier-run", startedAt: null, completedAt: null, terminalReason: null, turnRefs: [] }, { symbol: "sz000001", status: status === "blocked" ? "blocked" : "skipped", runId: null, startedAt: null, completedAt: null, terminalReason: "尚未启动", turnRefs: [] }] };
}
async function render(mode: "batches" | "schedules" = "batches", onProposalImport?: (source: FinanceProposalBatchImport) => void) { await act(async () => root.render(<QueryClientProvider client={client}><FinanceResearchJobs assistant={assistant} stock={stock} watchlist={[stock]} mode={mode} zh onOpenRun={open} onProposalImport={onProposalImport} /></QueryClientProvider>)); await act(async () => new Promise((done) => setTimeout(done, 15))); }
function button(label: string) { return [...document.body.querySelectorAll("button")].find((item) => item.textContent?.includes(label))!; }
async function chooseFrequency(label: string) {
  await act(async () => node.querySelector<HTMLButtonElement>('button[aria-label="执行频率"]')!.click());
  await act(async () => [...document.querySelectorAll<HTMLElement>('[role="option"]')].find((item) => item.textContent?.includes(label))!.click());
}
beforeEach(() => { vi.resetAllMocks(); node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node); client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); api.schedules.mockResolvedValue({ assistantAgentId: "finance", schedules: [] }); api.batches.mockResolvedValue({ assistantAgentId: "finance", batches: [] }); });
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });

it("rejects unsupported symbols before creating work and provides visible feedback", async () => {
  await render(); const field = node.querySelector("textarea")!;
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(field, "510300"); field.dispatchEvent(new Event("input", { bubbles: true })); });
  await act(async () => button("开始批量研究").click());
  expect(api.create).not.toHaveBeenCalled(); expect(node.textContent).toContain("无法识别股票代码");
});

it("opens the exact completed stock run while keeping stopped items distinct", async () => {
  api.batches.mockResolvedValue({ assistantAgentId: "finance", batches: [batch("stopped")] });
  await render(); expect(node.textContent).toContain("已完成 1/2"); expect(node.textContent).toContain("已停止"); expect(node.textContent).toContain("未启动");
  await act(async () => button("查看结果").click()); expect(open).toHaveBeenCalledWith("earlier-run", "sh600519");
  expect(button("重试未完成")).toBeDefined();
});

it("does not offer retry for blocked or already completed batches", async () => {
  api.batches.mockResolvedValue({ assistantAgentId: "finance", batches: [batch("blocked")] }); await render();
  expect(node.textContent).toContain("需处理"); expect(button("重试未完成")).toBeUndefined();
});

it("requires an explicit capped selection of exact synthesis reports before handing off", async () => {
  const source = batch("completed");
  source.items = Array.from({ length: 6 }, (_, index) => ({
    symbol: `sh60000${index}`, status: "completed", runId: `run-${index}`, startedAt: null, completedAt: null, terminalReason: null,
    turnRefs: [
      { role: "market" as const, sessionId: `analyst-session-${index}`, turnId: `analyst-turn-${index}` },
      { role: "synthesis" as const, sessionId: `synthesis-session-${index}`, turnId: `synthesis-turn-${index}` },
    ],
  }));
  source.symbols = source.items.map((item) => item.symbol);
  api.batches.mockResolvedValue({ assistantAgentId: "finance", batches: [source] });
  const onProposalImport = vi.fn();
  await render("batches", onProposalImport);

  await act(async () => button("用于组合建议").click());
  await act(async () => new Promise((done) => setTimeout(done, 0)));
  const checkboxes = [...document.body.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
  expect(checkboxes).toHaveLength(6);
  expect(checkboxes.some((checkbox) => checkbox.checked)).toBe(false);
  expect(button("带入组合建议（0）").disabled).toBe(true);

  for (const checkbox of checkboxes.slice(0, 5)) await act(async () => checkbox.click());
  expect(checkboxes.slice(0, 5).every((checkbox) => checkbox.checked)).toBe(true);
  expect(checkboxes[5].disabled).toBe(true);
  await act(async () => button("带入组合建议（5）").click());

  expect(onProposalImport).toHaveBeenCalledOnce();
  const imported = onProposalImport.mock.calls[0][0];
  expect(imported).toMatchObject({ assistantAgentId: "finance", batchId: "batch", researchDate: "2026-10-06" });
  expect(imported.reports).toEqual(Array.from({ length: 5 }, (_, index) => ({ symbol: `sh60000${index}`, sessionId: `synthesis-session-${index}`, turnId: `synthesis-turn-${index}` })));
  expect(imported.reports.some((report: { turnId: string }) => report.turnId.startsWith("analyst"))).toBe(false);
  expect(api.create).not.toHaveBeenCalled();
});

it("requires the user to choose A-share reports explicitly and disables HK reports in mixed batches", async () => {
  const source = batch("completed");
  source.items = [
    { symbol: "sh600000", status: "completed", runId: "cn-run", startedAt: null, completedAt: null, terminalReason: null, turnRefs: [{ role: "synthesis", sessionId: "cn-session", turnId: "cn-turn" }] },
    { symbol: "hk00700", status: "completed", runId: "hk-run", startedAt: null, completedAt: null, terminalReason: null, turnRefs: [{ role: "synthesis", sessionId: "hk-session", turnId: "hk-turn" }] },
  ];
  source.symbols = source.items.map((item) => item.symbol);
  api.batches.mockResolvedValue({ assistantAgentId: "finance", batches: [source] });
  const onProposalImport = vi.fn();
  await render("batches", onProposalImport);

  await act(async () => button("用于组合建议").click());
  const checkboxes = [...document.body.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
  expect(checkboxes).toHaveLength(2);
  expect(checkboxes.every((checkbox) => !checkbox.checked)).toBe(true);
  expect(checkboxes[0].disabled).toBe(false);
  expect(checkboxes[1].disabled).toBe(true);
  expect(document.body.textContent).toContain("组合建议仅支持沪、深、北交所 A 股");
  await act(async () => checkboxes[1].click());
  expect(checkboxes[1].checked).toBe(false);

  await act(async () => checkboxes[0].click());
  await act(async () => button("带入组合建议（1）").click());
  expect(onProposalImport).toHaveBeenCalledOnce();
  expect(onProposalImport.mock.calls[0][0].reports).toEqual([{ symbol: "sh600000", sessionId: "cn-session", turnId: "cn-turn" }]);
});

it("shows a disabled proposal action with a reason for batches containing only HK and US results", async () => {
  const source = batch("partial");
  source.items = ["hk00700", "usAAPL"].map((symbol, index) => ({
    symbol, status: "completed", runId: `run-${index}`, startedAt: null, completedAt: null, terminalReason: null,
    turnRefs: [{ role: "synthesis" as const, sessionId: `session-${index}`, turnId: `turn-${index}` }],
  }));
  source.symbols = source.items.map((item) => item.symbol);
  api.batches.mockResolvedValue({ assistantAgentId: "finance", batches: [source] });
  const onProposalImport = vi.fn();
  await render("batches", onProposalImport);

  expect(button("用于组合建议").disabled).toBe(true);
  expect(node.textContent).toContain("此批次不含可导入的 A 股结果");
  expect(onProposalImport).not.toHaveBeenCalled();
});

it("labels weekday scheduling honestly and pauses only future runs", async () => {
  const schedule = { scheduleId: "daily", assistantAgentId: "finance", symbols: [stock.symbol], periodDays: 30, depth: "brief", execution: { kind: "weekdays", scheduledAt: null, timeOfDay: "18:00", timezone: "Asia/Shanghai" }, researchDate: null, enabled: true, nextRunAt: "2026-10-06T18:00:00+08:00", lastTriggeredAt: null, lastBatchId: null, createdAt: "2026-10-06T12:00:00+08:00", updatedAt: "2026-10-06T12:00:00+08:00" };
  api.schedules.mockImplementation(async () => ({ assistantAgentId: "finance", schedules: [schedule] }));
  api.patch.mockImplementation(async () => { schedule.enabled = false; return { ...schedule, nextRunAt: null }; });
  await render("schedules");
  expect(node.textContent).toContain("周一至五 18:00"); expect(node.textContent).toContain("北京时间");
  await chooseFrequency("周一至周五");
  expect(node.textContent).toContain("周一至五执行，节假日照常研究");
  await act(async () => button("暂停计划").click());
  expect(api.patch).toHaveBeenCalledWith("finance", "daily", false); expect(api.stop).not.toHaveBeenCalled(); expect(button("恢复计划")).toBeDefined();
});

it("shows calendar coverage gaps and the persisted downtime catch-up record", async () => {
  const schedule = { scheduleId: "a-share", assistantAgentId: "finance", symbols: [stock.symbol], periodDays: 30, depth: "brief", execution: { kind: "trading_days", scheduledAt: null, timeOfDay: "18:00", timezone: "Asia/Shanghai" }, researchDate: null, enabled: true, nextRunAt: null, lastTriggeredAt: "2026-10-06T19:00:00+08:00", lastBatchId: "batch", lastScheduledAt: "2026-10-06T18:00:00+08:00", lastTriggerReason: "downtime_catch_up", lastSkippedOccurrenceCount: 2, calendarStatus: "unavailable", createdAt: "2026-10-06T12:00:00+08:00", updatedAt: "2026-10-06T12:00:00+08:00" };
  api.schedules.mockResolvedValue({ assistantAgentId: "finance", schedules: [schedule] });

  await render("schedules");

  expect(node.textContent).toContain("A股交易日");
  expect(node.textContent).toContain("日历未覆盖");
  expect(node.textContent).toContain("未知年份不会触发");
  expect(node.textContent).toContain("最近停机补跑");
  expect(node.textContent).toContain("跳过 2 次");
});
