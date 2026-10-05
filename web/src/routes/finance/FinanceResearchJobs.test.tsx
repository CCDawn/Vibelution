// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FinanceResearchJobs } from "./FinanceResearchJobs";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { FinancialResearchBatch } from "../../api/financialJobs";

const api = vi.hoisted(() => ({ schedules: vi.fn(), batches: vi.fn(), create: vi.fn(), patch: vi.fn(), stop: vi.fn(), retry: vi.fn() }));
vi.mock("../../api/financialJobs", () => ({ fetchFinancialResearchSchedules: api.schedules, fetchFinancialResearchBatches: api.batches, createFinancialResearchSchedule: api.create, updateFinancialResearchSchedule: api.patch, stopFinancialResearchBatch: api.stop, retryFinancialResearchBatch: api.retry }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const assistant = { agentId: "finance", setupStatus: "ready", modelStatus: "configured_unverified" } as FinancialAssistant;
const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
const open = vi.fn(); let root: Root, client: QueryClient, node: HTMLDivElement;
function batch(status: FinancialResearchBatch["status"]): FinancialResearchBatch {
  return { batchId: "batch", scheduleId: "schedule", assistantAgentId: "finance", status, triggeredAt: "2026-10-06T12:00:00+08:00", updatedAt: "2026-10-06T12:00:00+08:00", researchDate: "2026-10-06", periodDays: 30, depth: "brief", symbols: ["sh600519", "sz000001"], terminalReason: null, items: [{ symbol: "sh600519", status: "completed", runId: "earlier-run", startedAt: null, completedAt: null, terminalReason: null, turnRefs: [] }, { symbol: "sz000001", status: status === "blocked" ? "blocked" : "skipped", runId: null, startedAt: null, completedAt: null, terminalReason: "尚未启动", turnRefs: [] }] };
}
async function render(mode: "batches" | "schedules" = "batches") { await act(async () => root.render(<QueryClientProvider client={client}><FinanceResearchJobs assistant={assistant} stock={stock} watchlist={[stock]} mode={mode} zh onOpenRun={open} /></QueryClientProvider>)); await act(async () => new Promise((done) => setTimeout(done, 15))); }
function button(label: string) { return [...node.querySelectorAll("button")].find((item) => item.textContent?.includes(label))!; }
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

it("labels weekday scheduling honestly and pauses only future runs", async () => {
  const schedule = { scheduleId: "daily", assistantAgentId: "finance", symbols: [stock.symbol], periodDays: 30, depth: "brief", execution: { kind: "weekdays", scheduledAt: null, timeOfDay: "18:00", timezone: "Asia/Shanghai" }, researchDate: null, enabled: true, nextRunAt: "2026-10-06T18:00:00+08:00", lastTriggeredAt: null, lastBatchId: null, createdAt: "2026-10-06T12:00:00+08:00", updatedAt: "2026-10-06T12:00:00+08:00" };
  api.schedules.mockImplementation(async () => ({ assistantAgentId: "finance", schedules: [schedule] }));
  api.patch.mockImplementation(async () => { schedule.enabled = false; return { ...schedule, nextRunAt: null }; });
  await render("schedules"); expect(node.textContent).toContain("节假日照常研究"); expect(node.textContent).toContain("北京时间");
  await act(async () => button("暂停计划").click());
  expect(api.patch).toHaveBeenCalledWith("finance", "daily", false); expect(api.stop).not.toHaveBeenCalled(); expect(button("恢复计划")).toBeDefined();
});
