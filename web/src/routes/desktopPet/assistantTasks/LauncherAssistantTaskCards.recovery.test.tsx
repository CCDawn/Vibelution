// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider, type InfiniteData } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LauncherAssistantDispatch, LauncherAssistantStatus, LauncherAssistantTeamRun, LauncherAssistantTeamRunsPage } from "../../../api/launcherAssistant";
import { LauncherNotificationProvider, useLauncherNotices, type LauncherNotice } from "../../../app/LauncherNotifications";
import { LauncherAssistantTaskCards } from "./LauncherAssistantTaskCards";
import { LauncherAssistantTaskSidebar } from "./LauncherAssistantTaskSidebar";
import { LauncherTaskModelControls } from "./__fixtures__/LauncherTaskModelControls";
import { useLauncherTasks, type LauncherTaskModel } from "./LauncherTaskContext";
import type { AssistantTeamRunObservationPage } from "./assistantTeamRunTasks";

const STATUS: LauncherAssistantStatus = { teamRunsVersion: 1,
  assistant: { agentId: "assistant-1", directSessionId: "session-1", displayName: "助理" } };
const TEAM_KEY = ["launcher-assistant", "team-task-cards", "assistant-1", "session-1"];
function team(overrides: Partial<LauncherAssistantTeamRun> = {}): LauncherAssistantTeamRun {
  return { projectId: "project-1", requestId: "request-1", originAction: "team_run", teamId: "team-1", flowId: "flow-1",
    runId: "run-1", status: "completed", revision: "r1", title: "已完成团队任务", readState: "ready",
    observedAt: "2026-11-05T03:00:00Z", businessAcceptance: "not_evaluated", ...overrides };
}
function page(teamRuns: LauncherAssistantTeamRun[] = []): LauncherAssistantTeamRunsPage {
  return { schemaVersion: 1, assistant: { agentId: "assistant-1", directSessionId: "session-1" }, teamRuns,
    offset: 0, total: teamRuns.length, nextCursor: null, state: "partial",
    coverage: { kind: "local_associations", historyComplete: false, legacyUnrecoverable: 2, invalidRecords: 0 } };
}
function terminalDispatches(): LauncherAssistantDispatch[] {
  return ["succeeded", "succeeded", "timed_out", "failed"].map((status, index) => ({
    dispatchId: `dispatch-${index}`, projectId: "project-1", agentId: "worker-1", nativeTaskId: `native-${index}`,
    title: `现场任务 ${index + 1}`, receipt: { taskId: `native-${index}`, status, shouldPoll: false },
  }));
}

let root: Root, host: HTMLDivElement, client: QueryClient;
let invoke: ReturnType<typeof vi.fn>, teamReply: (cursor?: string) => Promise<LauncherAssistantTeamRunsPage>;
let currentPage: LauncherAssistantTeamRunsPage, rows: LauncherAssistantDispatch[];
let currentStatus: LauncherAssistantStatus;
let visibility: DocumentVisibilityState;
let notices: LauncherNotice[], model: LauncherTaskModel | null;
function Observe() { notices = useLauncherNotices(); model = useLauncherTasks(); return null; }
async function settle() {
  for (let index = 0; index < 5; index += 1) await act(async () => { await vi.advanceTimersByTimeAsync(1); });
}
async function render() {
  await act(async () => root.render(<QueryClientProvider client={client}><LauncherNotificationProvider>
    <LauncherAssistantTaskCards><LauncherTaskModelControls/><LauncherAssistantTaskSidebar/><Observe/></LauncherAssistantTaskCards>
  </LauncherNotificationProvider></QueryClientProvider>));
  await settle();
}
async function refresh() {
  await act(async () => host.querySelector<HTMLButtonElement>("[data-task-model-refresh]")!.click());
  await settle();
}
function operations() { return invoke.mock.calls.map(([request]) => request.operation as string); }
function teamReads() { return operations().filter(operation => operation === "teamRuns").length; }
function cachedPage() { return client.getQueryData<InfiniteData<AssistantTeamRunObservationPage>>(TEAM_KEY)!.pages[0]; }
function expectReadOnly() {
  expect(operations().every(operation => ["status", "dispatches", "teamRuns"].includes(operation))).toBe(true);
}
function expectConflictWarning() {
  expect(notices).toHaveLength(1);
  expect(notices[0]).toMatchObject({ features: ["tasks"], title: "暂时查不到任务进度" });
  expect(model!.partial).toBe(true);
  const tasks = model!.tasks.filter(task => task.kind === "team_run");
  expect(tasks).toHaveLength(1);
  expect(tasks[0]).toMatchObject({ state: "unknown", conflictingObservations: true, receiptBound: false });
  expect(tasks[0].sourceRefs).toHaveLength(2);
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  visibility = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  rows = terminalDispatches(); currentPage = page(); notices = []; model = null;
  currentStatus = structuredClone(STATUS);
  teamReply = async () => currentPage;
  invoke = vi.fn(async (request: { operation: string; cursor?: string }) => {
    if (request.operation === "status") return currentStatus;
    if (request.operation === "dispatches") return { dispatches: rows };
    if (request.operation === "teamRuns") return teamReply(request.cursor);
    throw new Error(`Unexpected mutation: ${request.operation}`);
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove(); client.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers();
});

describe("task progress recovery", () => {
  it.each([
    { source: "dispatches", cached: false }, { source: "teamRuns", cached: false },
    { source: "dispatches", cached: true }, { source: "teamRuns", cached: true },
  ] as const)("cancels a healthy late $source read on hide without a false warning (cached=$cached)", async ({ source, cached }) => {
    let resolveRead!: () => void;
    const pending = new Promise<void>(resolve => { resolveRead = resolve; });
    let pause = !cached;
    invoke.mockImplementation(async (request: { operation: string }) => {
      if (request.operation === "status") return currentStatus;
      if (request.operation === source && pause) { pause = false; await pending; }
      if (request.operation === "dispatches") return { dispatches: rows };
      if (request.operation === "teamRuns") return currentPage;
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    await render();
    if (cached) {
      pause = true;
      await act(async () => { void model!.refresh(); });
      await settle();
    }
    expect(operations()).toContain(source);
    visibility = "hidden";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await act(async () => { resolveRead(); });
    await settle();
    expect(notices).toEqual([]);
    visibility = "visible";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle();
    expect(notices).toEqual([]);
    expect(model!.tasks).toHaveLength(4);
    expectReadOnly();
  });

  it("takes a fresh receipt after reopening before the cancelled native read drains", async () => {
    const obsolete = rows;
    let resolveRead!: () => void;
    const pending = new Promise<void>(resolve => { resolveRead = resolve; });
    let first = true;
    invoke.mockImplementation(async (request: { operation: string }) => {
      if (request.operation === "status") return currentStatus;
      if (request.operation === "dispatches") {
        if (first) { first = false; await pending; return { dispatches: obsolete }; }
        return { dispatches: rows };
      }
      if (request.operation === "teamRuns") return currentPage;
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    await render();
    visibility = "hidden";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    rows = rows.map(row => ({ ...row, dispatchId: `fresh-${row.dispatchId}` }));
    visibility = "visible";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle();
    expect(notices).toEqual([]);
    expect(operations().filter(operation => operation === "dispatches")).toHaveLength(1);
    await act(async () => { resolveRead(); });
    await settle();
    expect(notices).toEqual([]);
    expect(model!.tasks).toHaveLength(rows.length);
    expect(model!.tasks).toEqual(expect.arrayContaining(rows.map(row =>
      expect.objectContaining({ kind: "dispatch", dispatchId: row.dispatchId }))));
    expectReadOnly();
  });

  it("keeps a genuine read failure when hiding cancels its in-flight recovery", async () => {
    let resolveRead!: () => void;
    const pending = new Promise<void>(resolve => { resolveRead = resolve; });
    let failed = true, hold = true;
    invoke.mockImplementation(async (request: { operation: string }) => {
      if (request.operation === "status") return currentStatus;
      if (request.operation === "dispatches") {
        if (failed) throw new Error("Task source unavailable");
        if (hold) { hold = false; await pending; }
        return { dispatches: rows };
      }
      if (request.operation === "teamRuns") return currentPage;
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    await render();
    expect(notices).toHaveLength(1);
    failed = false;
    await act(async () => { void model!.refresh(); });
    await settle();
    visibility = "hidden";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await act(async () => { resolveRead(); });
    await settle();
    expect(notices).toHaveLength(1);
    visibility = "visible";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle();
    expect(notices).toEqual([]);
    expect(model!.tasks).toHaveLength(4);
    expectReadOnly();
  });

  it.each(["dispatches", "teamRuns"] as const)("gives a new identity its own %s probes and clears the warning on recovery", async source => {
    let failed = true;
    invoke.mockImplementation(async (request: { operation: string; cursor?: string }) => {
      if (request.operation === source && failed) throw new Error("Task read temporarily unavailable");
      if (request.operation === "status") return currentStatus;
      if (request.operation === "dispatches") return { dispatches: rows };
      if (request.operation === "teamRuns") return currentPage;
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    const reads = () => operations().filter(operation => operation === source).length;
    await render();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(reads()).toBe(6);
    expect(notices).toHaveLength(1);

    currentStatus = { ...currentStatus, assistant: { ...currentStatus.assistant, agentId: "assistant-2", directSessionId: "session-2" } };
    currentPage = { ...currentPage, assistant: { agentId: "assistant-2", directSessionId: "session-2" } };
    await act(async () => { await client.refetchQueries({ queryKey: ["launcher-assistant", "status"], exact: true }); });
    await settle();
    expect(reads()).toBe(7);
    expect(notices).toHaveLength(1);

    failed = false;
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(reads()).toBe(8);
    expect(notices).toEqual([]);
    expect(model!.unavailable).toBe(false);
    expect(model!.teamUnavailable).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(reads()).toBe(8);
    expectReadOnly();
  });

  it("keeps the live zero-team legacy gap quiet without hiding four terminal dispatch receipts", async () => {
    const original = structuredClone(currentPage);
    await render();
    expect(notices).toEqual([]);
    expect(model).toMatchObject({ partial: false, historyIncomplete: true, legacyUnrecoverable: 2 });
    expect(cachedPage()).toEqual(original);
    expect(currentPage).toEqual(original);
    expect(host.querySelector('[data-task-group="ended"]')).toBeTruthy();
    expect(host.textContent).toContain("已结束 4");
    expect(host.querySelectorAll('article[data-task-state="awaiting_verification"]')).toHaveLength(2);
    expect(host.querySelectorAll('article[data-task-state="failed"]')).toHaveLength(2);
    expect(model!.tasks.map(task => task.nativeStatus)).toEqual(["succeeded", "succeeded", "timed_out", "failed"]);

    invoke.mockClear();
    await refresh();
    expect(operations().sort()).toEqual(["dispatches", "status", "teamRuns"]);
    expectReadOnly();
    expect(notices).toEqual([]);
    expect(cachedPage()).toEqual(original);
    expect(host.querySelectorAll("article")).toHaveLength(4);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(teamReads()).toBe(1);
  });

  it("does not warn when a legacy gap accompanies a ready team observation", async () => {
    currentPage = page([team()]);
    await render();
    expect(notices).toEqual([]);
    expect(model!.partial).toBe(false);
    expect(cachedPage()).toEqual(currentPage);
    expect(host.querySelector('article[data-task-kind="team_run"]')?.getAttribute("data-task-state")).toBe("awaiting_verification");
    expect(host.textContent).toContain("已结束 5");
  });

  it("keeps same-page ready aliases with conflicting statuses visible until a consistent manual refresh", async () => {
    currentPage = page([team(), team({ requestId: "request-2", originAction: "flow_start", status: "failed", revision: "r2" })]);
    await render();
    expect(cachedPage()).toEqual(currentPage);
    expect(cachedPage().teamRuns.every(row => row.readState === "ready")).toBe(true);
    expectConflictWarning();
    await refresh();
    expectConflictWarning();
    expectReadOnly();

    currentPage = page([team(), team({ requestId: "request-2", originAction: "flow_start" })]);
    invoke.mockClear();
    await refresh();
    expect(operations().sort()).toEqual(["dispatches", "status", "teamRuns"]);
    expectReadOnly();
    expect(notices).toEqual([]);
    expect(model!.partial).toBe(false);
    expect(model!.tasks.filter(task => task.kind === "team_run")).toHaveLength(1);
    expect(model!.tasks.find(task => task.kind === "team_run")).toMatchObject({
      state: "awaiting_verification", conflictingObservations: false, receiptBound: true,
      sourceRefs: [{ requestId: "request-1", originAction: "team_run" }, { requestId: "request-2", originAction: "flow_start" }],
    });
    expect(cachedPage()).toEqual(currentPage);
  });

  it("detects conflicting revisions across native cursor pages and clears them only after consistent refresh", async () => {
    const nextCursor = btoa(JSON.stringify({ snapshot: "a".repeat(64), offset: 1 }))
      .replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
    const firstPage = { ...page([team()]), total: 2, nextCursor };
    let secondPage = { ...page([team({ requestId: "request-2", originAction: "flow_start", revision: "r2" })]), offset: 1, total: 2 };
    teamReply = async cursor => {
      if (cursor === undefined) return firstPage;
      if (cursor !== nextCursor) throw new Error("Unexpected team cursor");
      return secondPage;
    };
    await render();
    expect(notices).toEqual([]);
    expect(model!.hasNextPage).toBe(true);
    const more = [...host.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "显示更多");
    expect(more).toBeTruthy();
    await act(async () => more!.click()); await settle();
    expect(invoke).toHaveBeenCalledWith({ operation: "teamRuns", cursor: nextCursor });
    expect(client.getQueryState(TEAM_KEY)?.status).toBe("success");
    expect(client.getQueryData<InfiniteData<AssistantTeamRunObservationPage>>(TEAM_KEY)?.pages).toEqual([firstPage, secondPage]);
    expectConflictWarning();
    await refresh();
    expectConflictWarning();
    expectReadOnly();

    secondPage = { ...page([team({ requestId: "request-2", originAction: "flow_start" })]), offset: 1, total: 2 };
    invoke.mockClear();
    await refresh();
    expect(operations().sort()).toEqual(["dispatches", "status", "teamRuns", "teamRuns"]);
    expectReadOnly();
    expect(notices).toEqual([]);
    expect(model!.partial).toBe(false);
    expect(model!.tasks.filter(task => task.kind === "team_run")).toHaveLength(1);
    expect(model!.tasks.find(task => task.kind === "team_run")).toMatchObject({
      state: "awaiting_verification", conflictingObservations: false, receiptBound: true,
    });
    expect(client.getQueryData<InfiniteData<AssistantTeamRunObservationPage>>(TEAM_KEY)?.pages).toEqual([firstPage, secondPage]);
  });

  it.each(["unknown", "invalid"] as const)("retains a real %s warning until manual refresh obtains ready observations", async reason => {
    currentPage = reason === "unknown" ? page([team({ readState: "unknown", status: null, observedAt: null,
      teamId: null, flowId: null, runId: null, revision: null })]) : page();
    if (reason === "invalid") currentPage.coverage.invalidRecords = 1;
    await render();
    expect(notices).toHaveLength(1);
    expect(notices[0]).toMatchObject({ features: ["tasks"], title: "暂时查不到任务进度" });
    expect(model!.partial).toBe(true);
    expect(cachedPage()).toEqual(currentPage);
    if (reason === "unknown") expect(host.querySelector('article[data-task-kind="team_run"]')?.getAttribute("data-task-state")).toBe("unknown");
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); }); await settle();
    expect(teamReads()).toBe(1);
    await refresh();
    expect(teamReads()).toBe(2);
    expect(notices).toHaveLength(1);
    expect(model!.partial).toBe(true);

    currentPage = page([team()]);
    await refresh();
    expect(teamReads()).toBe(3);
    expect(notices).toEqual([]);
    expect(model!.partial).toBe(false);
    expect(cachedPage()).toEqual(currentPage);
    expect(model!.tasks.find(task => task.kind === "team_run")).toMatchObject({ state: "awaiting_verification", receiptBound: true });
    expectReadOnly();
  });

  it("withdraws a real transport warning when the existing automatic probe reads a recovered source", async () => {
    teamReply = async () => { throw new Error("team transport unavailable"); };
    await render();
    expect(teamReads()).toBe(1);
    expect(notices).toHaveLength(1);
    expect(model!.teamUnavailable).toBe(true);
    teamReply = async () => currentPage;
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(teamReads()).toBe(2);
    expect(notices).toEqual([]);
    expect(model!.teamUnavailable).toBe(false);
    expect(cachedPage()).toEqual(currentPage);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(teamReads()).toBe(2);
    expectReadOnly();
  });

  it("stops failed transport probes after the existing five-attempt budget", async () => {
    teamReply = async () => { throw new Error("team transport unavailable"); };
    await render();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(teamReads()).toBe(6);
    expect(notices).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(teamReads()).toBe(6);
    expect(notices).toHaveLength(1);
    expectReadOnly();
  });
});
