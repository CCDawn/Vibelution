// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LauncherAssistantDispatch, LauncherAssistantStatus, LauncherAssistantTeamRun, LauncherAssistantTeamRunsPage } from "../../../api/launcherAssistant";
import type { LauncherTaskCleanupPreview, LauncherTaskCleanupResult, LauncherTaskCleanupTarget } from "../../../api/launcherAssistantTaskCleanup";
import { LauncherAssistantTaskCards } from "./LauncherAssistantTaskCards";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
type CleanupRequest = { targets: LauncherTaskCleanupTarget[] };
const cleanupKey = (target: LauncherTaskCleanupTarget) => JSON.stringify([target.kind, target.projectId,
  target.kind === "dispatch" ? target.dispatchId : target.originAction, target.kind === "team_run" ? target.requestId : null]);
const dispatch = (overrides: Partial<LauncherAssistantDispatch> = {}): LauncherAssistantDispatch => ({
  dispatchId: "dispatch-1", projectId: "project-1", nativeTaskId: "native-1", title: "委派周报",
  receipt: { taskId: "native-1", status: "succeeded" }, ...overrides,
});
const team = (overrides: Partial<LauncherAssistantTeamRun> = {}): LauncherAssistantTeamRun => ({
  projectId: "project-1", requestId: "request-1", originAction: "team_run", teamId: "team-1", flowId: "flow-1", runId: "run-1",
  title: "团队周报", status: "completed", readState: "ready", revision: "r1", observedAt: "2026-11-04T01:00:00Z",
  businessAcceptance: "not_evaluated", ...overrides,
});
const page = (teamRuns: LauncherAssistantTeamRun[], overrides: Partial<LauncherAssistantTeamRunsPage> = {}): LauncherAssistantTeamRunsPage => ({
  schemaVersion: 1, assistant: { agentId: status.assistant.agentId, directSessionId: status.assistant.directSessionId }, teamRuns, offset: 0, total: teamRuns.length, nextCursor: null, state: "ready",
  coverage: { kind: "local_associations", historyComplete: false, legacyUnrecoverable: 0, invalidRecords: 0 }, ...overrides,
});
const preview = ({ targets }: CleanupRequest, blocked = false): LauncherTaskCleanupPreview => ({
  schemaVersion: 1, fingerprint: "native-preview", estimatedBytes: 0,
  items: targets.map(target => ({ key: cleanupKey(target), title: "周报", status: blocked ? "blocked" : "ready", estimatedBytes: 0,
    resources: [], retained: [], ...(blocked ? { reason: "工作区存在未提交改动" } : {}) })),
});
const outcome = ({ targets }: CleanupRequest, itemStatus: "deleted" | "partial" | "blocked" = "deleted"): LauncherTaskCleanupResult => ({
  schemaVersion: 1, releasedBytes: 0, items: targets.map(target => ({ key: cleanupKey(target), status: itemStatus,
    releasedBytes: 0, retained: [], failures: [] })),
});
let root: Root | null, container: HTMLDivElement, client: QueryClient, status: LauncherAssistantStatus;
let rows: LauncherAssistantDispatch[], dispatchReply: () => Promise<LauncherAssistantDispatch[]>;
let teamReply: (cursor?: string) => Promise<LauncherAssistantTeamRunsPage>;
let previewReply: (request: CleanupRequest) => Promise<LauncherTaskCleanupPreview>;
let executeReply: (request: CleanupRequest) => Promise<LauncherTaskCleanupResult>;
let invoke: ReturnType<typeof vi.fn>, visibility: DocumentVisibilityState;

beforeEach(() => {
  vi.useFakeTimers(); visibility = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{ width: 100, height: 30 } as DOMRect] as unknown as DOMRectList);
  status = { teamRunsVersion: 1, assistant: { agentId: "assistant-1", directSessionId: "session-1", displayName: "助理" } };
  rows = [dispatch()]; dispatchReply = async () => rows; teamReply = async () => page([team()]);
  previewReply = async request => preview(request); executeReply = async request => outcome(request);
  invoke = vi.fn(async (request: { operation: string; cursor?: string } & Partial<CleanupRequest>) => {
    if (request.operation === "status") return status;
    if (request.operation === "dispatches") return { dispatches: await dispatchReply() };
    if (request.operation === "teamRuns") return teamReply(request.cursor);
    if (request.operation === "previewTaskCleanup") return previewReply(request as CleanupRequest);
    if (request.operation === "executeTaskCleanup") return executeReply(request as CleanupRequest);
    throw new Error(`Unexpected operation: ${request.operation}`);
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => { root?.unmount(); }); container.remove(); client.clear();
  vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers();
});
async function settle(milliseconds = 5) {
  for (let index = 0; index < milliseconds; index += 1) await act(async () => { await vi.advanceTimersByTimeAsync(1); });
}
async function render() {
  await act(async () => { root!.render(<QueryClientProvider client={client}><LauncherAssistantTaskCards /></QueryClientProvider>); });
  await settle();
}
function button(label: string): HTMLButtonElement {
  const node = [...document.body.querySelectorAll<HTMLButtonElement>("button")].find(candidate => candidate.textContent === label || candidate.getAttribute("aria-label") === label);
  if (!node) throw new Error(`Missing button: ${label}`); return node;
}
async function click(label: string) {
  await act(async () => {
    const node = button(label);
    if (node.getAttribute("role") === "tab") node.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    node.click();
  }); await settle();
}
const requests = (operation: string) => invoke.mock.calls.map(([request]) => request).filter(request => request.operation === operation);
const executed = (): LauncherTaskCleanupTarget[] => requests("executeTaskCleanup").flatMap(request => request.targets ?? []);
const cleanupDialog = () => document.body.querySelector<HTMLElement>('[data-vui="launcher-task-cleanup"]')!;

describe("independent cleanup sources", () => {
  it.each(["dispatch", "team_run"] as const)("cleans the healthy source when %s fails and discards incomplete team pagination", async failedSource => {
    await render();
    if (failedSource === "dispatch") dispatchReply = async () => { throw new Error("dispatch offline"); };
    else teamReply = async cursor => {
      if (cursor) throw new Error("team page offline");
      const nextCursor = btoa(JSON.stringify({ snapshot: "a".repeat(64), offset: 1 })).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
      return page([team()], { total: 2, nextCursor });
    };
    await click("清理已结束");
    expect(executed().map(target => target.kind)).toEqual([failedSource === "dispatch" ? "team_run" : "dispatch"]);
    expect(cleanupDialog().textContent).toContain(failedSource === "dispatch" ? "普通委派来源未核验" : "团队运行来源未核验");
    expect(cleanupDialog().textContent).toContain("已清理 1 项");
    if (failedSource === "team_run") expect(requests("teamRuns").some(request => request.cursor)).toBe(true);
    expect(button("重试未核验来源与剩余项")).toBeTruthy();
  });

  it("recollects recovered sources on retry and uses the current list after a successful deletion", async () => {
    await render();
    let unavailable = true;
    dispatchReply = async () => { if (unavailable) throw new Error("offline"); return rows; };
    let teamRows = [team()]; teamReply = async () => page(teamRows);
    executeReply = async request => { if (request.targets.some(target => target.kind === "team_run")) teamRows = []; return outcome(request); };
    await click("清理已结束");
    const previousDispatchReads = requests("dispatches").length, previousTeamReads = requests("teamRuns").length;
    unavailable = false;
    await click("重试未核验来源与剩余项");
    expect(requests("dispatches").length).toBeGreaterThan(previousDispatchReads);
    expect(requests("teamRuns").length).toBeGreaterThan(previousTeamReads);
    expect(executed().map(target => target.kind)).toEqual(["team_run", "dispatch"]);
    expect(cleanupDialog().textContent).not.toContain("来源未核验");
  });

  it("reports both unverified sources instead of an empty task list and can retry them", async () => {
    await render();
    dispatchReply = async () => { throw new Error("dispatch offline"); };
    teamReply = async () => { throw new Error("team offline"); };
    await click("清理已结束");
    expect(requests("previewTaskCleanup")).toHaveLength(0);
    expect(cleanupDialog().textContent).toContain("普通委派来源未核验");
    expect(cleanupDialog().textContent).toContain("团队运行来源未核验");
    expect(cleanupDialog().textContent).not.toContain("当前没有可批量清理");
    dispatchReply = async () => rows; teamReply = async () => page([team()]);
    await click("重试未核验来源与剩余项");
    expect(executed()).toHaveLength(2);
  });

  it("retries only unfinished targets when every source was verified", async () => {
    await render();
    executeReply = async request => ({ ...outcome(request), items: request.targets.map(target => ({
      key: cleanupKey(target), status: target.kind === "team_run" ? "blocked" as const : "deleted" as const, releasedBytes: 0, retained: [], failures: [],
    })) });
    await click("清理已结束");
    const previousReads = requests("dispatches").length + requests("teamRuns").length;
    executeReply = async request => outcome(request);
    await click("重试清理");
    expect(requests("executeTaskCleanup").at(-1)?.targets?.map((target: LauncherTaskCleanupTarget) => target.kind)).toEqual(["team_run"]);
    // Post-action invalidation is the only reread; no extra collection pass.
    expect(requests("dispatches").length + requests("teamRuns").length - previousReads).toBe(2);
  });

  it.each(["identity", "hidden", "unmounted"] as const)("cancels every source before cleanup after %s changes", async change => {
    await render();
    let finish!: (value: LauncherAssistantDispatch[]) => void;
    const held = new Promise<LauncherAssistantDispatch[]>(resolve => { finish = resolve; });
    dispatchReply = () => held;
    await click("清理已结束");
    dispatchReply = async () => rows;
    if (change === "identity") {
      status = { ...status, assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
      await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); }); await settle();
    } else if (change === "hidden") {
      visibility = "hidden"; await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    } else await act(async () => { root!.unmount(); root = null; });
    const teamReads = requests("teamRuns").length;
    await act(async () => { finish(rows); }); await settle();
    if (change !== "identity") expect(requests("teamRuns")).toHaveLength(teamReads);
    expect(requests("previewTaskCleanup")).toHaveLength(0);
    expect(requests("executeTaskCleanup")).toHaveLength(0);
  });
});

describe("stable grouping and readable results", () => {
  it("keeps the first default category through a valid unknown observation and recovery", async () => {
    rows = [dispatch({ receipt: { taskId: "native-1", status: "running" } })]; teamReply = async () => page([]);
    await render();
    expect(button("进行中 1").getAttribute("aria-selected")).toBe("true");
    rows = [dispatch({ lastError: { message: "temporarily unavailable" }, receipt: { taskId: "native-1", status: "running" } })];
    await click("刷新");
    expect(button("进行中 0").getAttribute("aria-selected")).toBe("true");
    expect(container.textContent).toContain("暂无此类任务");
    await click("待处理 1");
    rows = [dispatch({ receipt: { taskId: "native-1", status: "running" } })];
    await click("刷新");
    expect(button("待处理 0").getAttribute("aria-selected")).toBe("true");
  });

  it("chooses a new default for a different assistant identity", async () => {
    teamReply = async () => page([]); await render();
    expect(button("已结束 1").getAttribute("aria-selected")).toBe("true");
    status = { ...status, assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
    rows = [dispatch({ receipt: { taskId: "native-1", status: "running" } })];
    await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); }); await settle();
    expect(button("进行中 1").getAttribute("aria-selected")).toBe("true");
  });

  it("shows zero-byte success as a count and states each cleanup scope directly", async () => {
    await render(); await click("清理已结束");
    expect(cleanupDialog().textContent).toContain("已清理 2 项 · 部分清理 0 项 · 受阻 0 项");
    expect(cleanupDialog().textContent).toContain("实际释放 0 字节");
    expect(cleanupDialog().textContent).toContain("专属会话内容、附件和可安全清理的独占文件");
    expect(cleanupDialog().textContent).toContain("团队运行仅移除关联");
  });

  it("omits permanent history caveats while retaining unavailable team state", async () => {
    teamReply = async () => page([team()], { coverage: { kind: "local_associations", historyComplete: false, legacyUnrecoverable: 2, invalidRecords: 0 } });
    await render();
    expect(container.textContent).not.toContain("可显示的历史有限");
    expect(container.textContent).not.toContain("部分旧关联无法恢复");
    expect(container.textContent).not.toContain("部分团队关联或状态暂无法核验");
    teamReply = async () => { throw new Error("offline"); }; await click("刷新");
    expect(container.textContent).toContain("团队运行状态暂不可用");
    expect(container.textContent).not.toContain("任务状态暂不可用");
  });
});

describe("cleanup focus recovery", () => {
  it("restores the current row cleanup button after a blocked result replaces its original tooltip button", async () => {
    teamReply = async () => page([]); await render();
    const original = button("清理“委派周报”");
    let finish!: (value: LauncherTaskCleanupPreview) => void, request!: CleanupRequest;
    previewReply = async input => { request = input; return new Promise(resolve => { finish = resolve; }); };
    await act(async () => { original.focus(); }); await click("清理“委派周报”");
    expect(original.isConnected).toBe(false);
    await act(async () => { finish(preview(request, true)); }); await settle();
    const current = button("清理“委派周报”");
    expect(current).not.toBe(original);
    expect(cleanupDialog().textContent).toContain("受阻 1 项");
    await click("关闭"); await settle(32);
    expect(document.activeElement).toBe(current);
  });

  it("uses the toolbar after the cleaned task disappears", async () => {
    teamReply = async () => page([]); await render();
    executeReply = async request => { rows = []; return outcome(request); };
    await click("清理“委派周报”");
    expect(container.querySelector("article")).toBeNull();
    await click("关闭"); await settle(32);
    expect(document.activeElement).toBe(container.querySelector('[data-assistant-task-refresh]'));
  });

  it.each(["identity", "hidden", "unmounted"] as const)("does not restore old task focus when %s changes", async change => {
    teamReply = async () => page([]); previewReply = async request => preview(request, true);
    await render(); await click("清理“委派周报”");
    const focus = vi.spyOn(HTMLElement.prototype, "focus"); focus.mockClear();
    if (change === "identity") {
      status = { ...status, assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
      await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); });
    } else if (change === "hidden") {
      visibility = "hidden"; await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    } else await act(async () => { root!.unmount(); root = null; });
    await settle(32);
    expect(focus).not.toHaveBeenCalled();
  });
});
