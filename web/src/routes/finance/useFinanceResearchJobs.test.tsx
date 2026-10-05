// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useFinanceResearchJobs } from "./useFinanceResearchJobs";
import type { FinancialResearchSchedule, FinancialResearchScheduleCreateRequest } from "../../api/financialJobs";

const api = vi.hoisted(() => ({ schedules: vi.fn(), batches: vi.fn(), create: vi.fn(), patch: vi.fn(), stop: vi.fn(), retry: vi.fn() }));
vi.mock("../../api/financialJobs", () => ({ fetchFinancialResearchSchedules: api.schedules, fetchFinancialResearchBatches: api.batches, createFinancialResearchSchedule: api.create, updateFinancialResearchSchedule: api.patch, stopFinancialResearchBatch: api.stop, retryFinancialResearchBatch: api.retry }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root, client: QueryClient, node: HTMLDivElement, jobs: ReturnType<typeof useFinanceResearchJobs>;
const payload: FinancialResearchScheduleCreateRequest = { symbols: ["sh600519", "sz000001"], periodDays: 30, depth: "brief", execution: { kind: "now", timezone: "Asia/Shanghai" } };
function schedule(owner = "first", enabled = true): FinancialResearchSchedule {
  return { scheduleId: "schedule-" + owner, assistantAgentId: owner, symbols: payload.symbols, periodDays: 30, depth: "brief", execution: { kind: "daily", timeOfDay: "18:00", scheduledAt: null, timezone: "Asia/Shanghai" }, researchDate: null, enabled, createdAt: "2026-10-06T12:00:00+08:00", updatedAt: "2026-10-06T12:00:00+08:00", nextRunAt: enabled ? "2026-10-06T18:00:00+08:00" : null, lastBatchId: null, lastTriggeredAt: null };
}
function pending<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }
function Consumer({ owner }: { owner: string }) { jobs = useFinanceResearchJobs(owner, true); return <div>{jobs.notice}{jobs.error}</div>; }
async function render(owner = "first") { await act(async () => root.render(<QueryClientProvider client={client}><Consumer owner={owner} /></QueryClientProvider>)); await settle(); }
async function settle() { await act(async () => new Promise((done) => setTimeout(done, 15))); }
beforeEach(() => {
  vi.resetAllMocks(); node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  api.schedules.mockImplementation(async (owner: string) => ({ assistantAgentId: owner, schedules: [] }));
  api.batches.mockImplementation(async (owner: string) => ({ assistantAgentId: owner, batches: [] }));
  api.create.mockImplementation(async (owner: string) => ({ schedule: schedule(owner), batch: null }));
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });

it("submits once for simultaneous clicks and reuses the request key after uncertain failure", async () => {
  const deferred = pending<{ schedule: FinancialResearchSchedule; batch: null }>();
  api.create.mockReturnValueOnce(deferred.promise);
  await render();
  let first!: Promise<void>;
  await act(async () => { first = jobs.create(payload); void jobs.create(payload); });
  expect(api.create).toHaveBeenCalledTimes(1); expect(jobs.creating).toBe(true);
  await act(async () => { deferred.resolve({ schedule: schedule(), batch: null }); await first; });
  api.create.mockRejectedValueOnce(new Error("response lost"));
  await act(async () => jobs.create(payload));
  const uncertainKey = api.create.mock.calls[1][2];
  expect(jobs.error).toBe("response lost");
  await act(async () => jobs.create(payload));
  expect(api.create.mock.calls[2][2]).toBe(uncertainKey);
  expect(uncertainKey).toMatch(/^financial-job-/); expect(jobs.error).toBe("");
});

it("keeps old owner completion from clearing another owner's in-flight gate", async () => {
  const old = pending<{ schedule: FinancialResearchSchedule; batch: null }>(), next = pending<{ schedule: FinancialResearchSchedule; batch: null }>();
  api.create.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
  await render(); let previous!: Promise<void>, current!: Promise<void>;
  await act(async () => { previous = jobs.create(payload); });
  await render("second"); expect(jobs.creating).toBe(false); expect(jobs.notice).toBe("");
  await act(async () => { current = jobs.create(payload); });
  await act(async () => { old.resolve({ schedule: schedule("first"), batch: null }); await previous; });
  expect(jobs.creating).toBe(true); expect(jobs.notice).toBe("");
  await act(async () => { void jobs.create(payload); });
  expect(api.create).toHaveBeenCalledTimes(2);
  await act(async () => { next.resolve({ schedule: schedule("second"), batch: null }); await current; });
  expect(jobs.creating).toBe(false); expect(jobs.notice).toBe("计划已保存");
});

it("rejects cross-owner data and does not display a successful submission", async () => {
  api.schedules.mockResolvedValue({ assistantAgentId: "other", schedules: [schedule("other")] });
  api.create.mockResolvedValue({ schedule: schedule("other"), batch: null });
  await render(); expect(jobs.schedules.isError).toBe(true);
  await act(async () => jobs.create(payload));
  expect(jobs.notice).toBe(""); expect(jobs.error).toContain("归属");
});

it("serializes pause/resume and reads back server-owned schedule state", async () => {
  let current = schedule(); api.schedules.mockImplementation(async () => ({ assistantAgentId: "first", schedules: [current] }));
  const deferred = pending<FinancialResearchSchedule>(); api.patch.mockReturnValueOnce(deferred.promise);
  await render(); let action!: Promise<void>;
  await act(async () => { action = jobs.setEnabled(current.scheduleId, false); void jobs.setEnabled(current.scheduleId, true); });
  expect(api.patch).toHaveBeenCalledTimes(1);
  await act(async () => { current = schedule("first", false); deferred.resolve(current); await action; });
  expect(jobs.schedules.data?.schedules[0].enabled).toBe(false); expect(jobs.pendingAction).toBe("");
});
