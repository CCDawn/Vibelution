// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LauncherAssistantDispatch, LauncherAssistantStatus, LauncherAssistantTeamRun, LauncherAssistantTeamRunsPage } from "../../../api/launcherAssistant";
import { LauncherAssistantTaskCards } from "./LauncherAssistantTaskCards";
import type { LauncherTaskCleanupPreview, LauncherTaskCleanupResult, LauncherTaskCleanupTarget } from "../../../api/launcherAssistantTaskCleanup";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const dispatchCleanupKey = JSON.stringify(["dispatch", "project-1", "dispatch-1", null]);
function cleanupKey(target: LauncherTaskCleanupTarget) {
  return JSON.stringify([target.kind, target.projectId, target.kind === "dispatch" ? target.dispatchId : target.originAction,
    target.kind === "team_run" ? target.requestId : null]);
}

function row(overrides: Partial<LauncherAssistantDispatch> = {}): LauncherAssistantDispatch {
  return { dispatchId: "dispatch-1", projectId: "project-1", agentId: "worker-1", nativeTaskId: "native-1", title: "核对周报",
    receipt: { taskId: "native-1", status: "running", shouldPoll: true }, ...overrides };
}

function teamRun(overrides: Partial<LauncherAssistantTeamRun> = {}): LauncherAssistantTeamRun {
  return { projectId: "project-1", requestId: "request-1", originAction: "team_run", teamId: "team-1", flowId: "flow-1",
    runId: "run-1", status: "completed", revision: "r1", title: "团队周报", readState: "ready",
    observedAt: "2026-11-02T01:00:00Z", businessAcceptance: "not_evaluated", ...overrides };
}

function teamPage(teamRuns: LauncherAssistantTeamRun[], overrides: Partial<LauncherAssistantTeamRunsPage> = {}): LauncherAssistantTeamRunsPage {
  return { schemaVersion: 1, assistant: { agentId: status.assistant.agentId, directSessionId: status.assistant.directSessionId },
    teamRuns, offset: 0, total: teamRuns.length, nextCursor: null,
    coverage: { kind: "local_associations", historyComplete: false, legacyUnrecoverable: 0, invalidRecords: 0 },
    state: "ready", ...overrides };
}

let root: Root | null, container: HTMLDivElement, client: QueryClient;
let rows: LauncherAssistantDispatch[], status: LauncherAssistantStatus;
let dispatchReply: () => Promise<LauncherAssistantDispatch[]>;
let teamReply: (cursor?: string) => Promise<LauncherAssistantTeamRunsPage>;
let visibility: DocumentVisibilityState;
let previewReply: (request: Record<string, unknown>) => Promise<LauncherTaskCleanupPreview>;
let executeReply: (request: Record<string, unknown>) => Promise<LauncherTaskCleanupResult>;
let invoke: ReturnType<typeof vi.fn>, onReview: ReturnType<typeof vi.fn>, onApproval: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  visibility = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  rows = [row()];
  status = { assistant: { agentId: "assistant-1", directSessionId: "session-1", displayName: "助理" } };
  dispatchReply = async () => rows;
  teamReply = async () => teamPage([]);
  previewReply = async request => {
    const targets = request.targets as LauncherTaskCleanupTarget[];
    return { schemaVersion: 1, fingerprint: "preview-1", estimatedBytes: targets.length * 4096, items: targets.map(target => ({
      key: cleanupKey(target), title: "核对周报", status: "ready", estimatedBytes: 4096,
      resources: [{ kind: "task_files", count: 2, bytes: 4096 }], retained: [{ kind: "project", reason: "项目为共享资源" }],
    })) };
  };
  executeReply = async request => {
    const targets = request.targets as LauncherTaskCleanupTarget[];
    return { schemaVersion: 1, releasedBytes: targets.length * 4096, items: targets.map(target => ({ key: cleanupKey(target),
      status: "deleted", releasedBytes: 4096, retained: [], failures: [] })) };
  };
  invoke = vi.fn(async (request: { operation: string; cursor?: string }) => {
    if (request.operation === "status") return status;
    if (request.operation === "dispatches") return { dispatches: await dispatchReply() };
    if (request.operation === "teamRuns") return teamReply(request.cursor);
    if (request.operation === "previewTaskCleanup") return previewReply(request);
    if (request.operation === "executeTaskCleanup") return executeReply(request);
    throw new Error(`Unexpected mutation: ${request.operation}`);
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  onReview = vi.fn(); onApproval = vi.fn();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});

describe("task card facts and cleanup confirmation", () => {
  function operationCalls(operation: string) { return invoke.mock.calls.filter(([request]) => request.operation === operation); }
  const terminal = () => { rows = [row({ receipt: { taskId: "native-1", status: "succeeded", resultSummary: "已生成周报，待人工核对" } })]; };

  it("shows the actual owner, project, latest summary and update time before opening details", async () => {
    rows = [row({ agentName: "报告 Agent", projectName: "周报项目", updatedAt: "2026-11-02T03:04:00Z", createdAt: "2026-11-01T01:00:00Z",
      receipt: { taskId: "native-1", status: "running", resultSummary: "已整理三份资料，正在核对来源" } })];
    await render();
    const card = container.querySelector("article")!;
    expect(card.textContent).toContain("负责人：报告 Agent");
    expect(card.textContent).toContain("项目：周报项目");
    expect(card.textContent).toContain("已整理三份资料，正在核对来源");
    expect(card.textContent).not.toContain("更新：未提供");
    expect(card.textContent).not.toContain("worker-1");
    expect(card.textContent).not.toContain("project-1");
    expect(card.textContent).not.toContain("native-1");
  });

  it("makes legacy task names distinct and ignores prompt/code bodies for naming", async () => {
    rows = [row({ dispatchId: "legacy-111111", title: "助理任务", receipt: { taskId: "native-1", status: "failed" } }),
      Object.assign(row({ dispatchId: "legacy-222222", title: undefined }), { prompt: "secret prompt body", code: "source code body" })];
    await render();
    expect(container.textContent).toContain("未命名任务 · 111111");
    expect(container.textContent).toContain("未命名任务 · 222222");
    expect(container.textContent).not.toContain("secret prompt body");
    expect(container.textContent).not.toContain("source code body");
    expect(container.textContent).toContain("负责人：worker-1");
    expect(container.textContent).toContain("项目：project-1");
    expect(container.textContent).toContain("更新：未提供");
  });

  it("uses a native receipt error as the failure explanation but never calls a communication error task failure", async () => {
    rows = [row({ title: "真实失败", receipt: { taskId: "native-1", status: "failed", error: { message: "远程仓库拒绝访问" } } }),
      row({ dispatchId: "dispatch-sync", title: "连接中断", lastError: { message: "offline" }, receipt: { taskId: "native-1", status: "failed" } }),
      row({ dispatchId: "dispatch-unbound", title: "尚未绑定", nativeTaskId: undefined, receipt: null })];
    await render();
    const failed = container.querySelector('article[aria-label="真实失败"]')!, sync = container.querySelector('article[aria-label="连接中断"]')!;
    expect(failed.textContent).toContain("远程仓库拒绝访问");
    expect(failed.textContent).toContain("执行失败");
    expect(sync.textContent).toContain("状态同步失败");
    expect(sync.textContent).not.toContain("执行失败");
    expect(button("删除", sync).disabled).toBe(true);
    expect(container.querySelector('article[aria-label="尚未绑定"]')?.textContent).toContain("身份未确认");
  });

  it("shows current loaded group counts and sorts real task times inside each group", async () => {
    rows = [row({ dispatchId: "old", title: "较早任务", updatedAt: "2026-11-01T00:00:00Z" }),
      row({ dispatchId: "new", title: "较新任务", updatedAt: "2026-11-02T00:00:00Z" }),
      row({ dispatchId: "wait", title: "等待授权", receipt: { taskId: "native-1", status: "awaiting_approval" } }),
      row({ dispatchId: "done", title: "已结束任务", receipt: { taskId: "native-1", status: "succeeded" } })];
    await render();
    expect(container.textContent).toContain("当前已加载 · 4");
    expect(button("需要你处理 · 1")).toBeTruthy();
    expect(button("进行中 · 2")).toBeTruthy();
    expect(button("已结束 · 1")).toBeTruthy();
    expect([...container.querySelectorAll('[data-task-group="active"] article h3')].map(element => element.textContent)).toEqual(["较新任务", "较早任务"]);
    await click("进行中 · 2");
    expect(container.querySelectorAll('[data-task-group="active"] article')).toHaveLength(0);
    await click("进行中 · 2");
    expect(container.querySelectorAll('[data-task-group="active"] article')).toHaveLength(2);
    expect(container.textContent).not.toContain("全平台");
  });

  it("keeps long summaries at two lines and exposes an explicit expansion action", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "running", resultSummary: "长摘要".repeat(80) } })];
    await render();
    expect(container.querySelector(".line-clamp-2")).toBeTruthy();
    await click("展开摘要");
    expect(container.querySelector(".line-clamp-2")).toBeNull();
    await click("收起摘要");
    expect(container.querySelector(".line-clamp-2")).toBeTruthy();
  });

  it("keeps loaded cards during a slow refresh with text instead of skeletons", async () => {
    await render();
    let resolveRows!: (value: LauncherAssistantDispatch[]) => void;
    dispatchReply = () => new Promise(resolve => { resolveRows = resolve; });
    await click("刷新");
    expect(container.querySelector("article")).toBeTruthy();
    expect(container.textContent).toContain("正在更新任务");
    expect(container.querySelector('[data-vui="skeleton"]')).toBeNull();
    await act(async () => { resolveRows(rows); }); await settle();
  });

  it("previews actual bytes and retention before confirmation; cancel sends no deletion", async () => {
    terminal(); await render();
    await click("删除");
    expect(operationCalls("previewTaskCleanup")).toHaveLength(1);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
    expect(document.body.textContent).toContain("预计释放：4,096 字节");
    expect(document.body.textContent).toContain("项目为共享资源");
    expect(invoke).toHaveBeenCalledWith({ operation: "previewTaskCleanup", agentId: "assistant-1", directSessionId: "session-1",
      targets: [{ kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-1" }] });
    await click("取消", document.body);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
    expect(container.querySelector("article")).toBeTruthy();
  });

  it("only executes after explicit confirmation, carries the preview fingerprint and refreshes the native list", async () => {
    terminal();
    executeReply = async () => { rows = []; return { schemaVersion: 1, releasedBytes: 3072,
      items: [{ key: dispatchCleanupKey, status: "deleted", releasedBytes: 3072, retained: [], failures: [] }] }; };
    await render(); await click("删除");
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
    await click("永久删除", document.body);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    expect(invoke).toHaveBeenCalledWith({ operation: "executeTaskCleanup", agentId: "assistant-1", directSessionId: "session-1", fingerprint: "preview-1",
      targets: [{ kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-1" }] });
    expect(document.body.textContent).toContain("实际释放：3,072 字节");
    expect(container.querySelector("article")).toBeNull();
    expect(dispatchReads()).toBe(2);
  });

  it("keeps partial records visible and requires a fresh preview and confirmation for retry", async () => {
    terminal();
    executeReply = async () => ({ schemaVersion: 1, releasedBytes: 1024, items: [{ key: dispatchCleanupKey, status: "partial", releasedBytes: 1024,
      retained: [{ kind: "session", reason: "仍有共享引用" }], failures: [{ code: "FILE_BUSY", message: "文件正在使用" }] }] });
    await render(); await click("删除"); await click("永久删除", document.body);
    expect(container.querySelector("article")).toBeTruthy();
    expect(document.body.textContent).toContain("实际释放：1,024 字节");
    expect(document.body.textContent).toContain("文件正在使用");
    expect(document.body.textContent).toContain("仍有共享引用");
    await click("重新预览后重试", document.body);
    expect(operationCalls("previewTaskCleanup")).toHaveLength(2);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    await click("取消", document.body);
    expect(container.querySelector("article")).toBeTruthy();
  });

  it("displays execution errors without silently hiding records or retrying deletion", async () => {
    terminal(); executeReply = async () => { throw new Error("cleanup backend offline"); };
    await render(); await click("删除"); await click("永久删除", document.body);
    expect(document.body.textContent).toContain("清理未获确认");
    expect(document.body.textContent).toContain("cleanup backend offline");
    expect(container.querySelector("article")).toBeTruthy();
    expect([...document.body.querySelectorAll("button")].some(element => element.textContent === "永久删除" && !element.disabled)).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    await click("重新预览后重试", document.body);
    expect(operationCalls("previewTaskCleanup")).toHaveLength(2);
  });

  it("keeps confirmation disabled if the actual preview is blocked or fails", async () => {
    terminal(); previewReply = async () => ({ schemaVersion: 1, fingerprint: "blocked", estimatedBytes: 0,
      items: [{ key: dispatchCleanupKey, title: "核对周报", status: "blocked", estimatedBytes: 0, resources: [], retained: [], reason: "任务仍被引用" }] });
    await render(); await click("删除");
    expect(button("永久删除", document.body).disabled).toBe(true);
    expect(document.body.textContent).toContain("任务仍被引用");
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
    await click("取消", document.body);
    previewReply = async () => { throw new Error("preview unavailable"); };
    await click("删除");
    expect(button("永久删除", document.body).disabled).toBe(true);
    expect(document.body.textContent).toContain("preview unavailable");
  });

  it("never enables deletion for active, unbound, unknown or stale-terminal receipts", async () => {
    rows = [row(), row({ dispatchId: "unknown", receipt: { taskId: "native-1", status: "new_state" } }),
      row({ dispatchId: "unbound", receipt: { taskId: "other", status: "succeeded" } }),
      row({ dispatchId: "stale", lastError: { message: "offline" }, receipt: { taskId: "native-1", status: "succeeded" } })];
    await render();
    expect([...container.querySelectorAll("article")].every(card => button("删除", card).disabled)).toBe(true);
    expect(button("清理已完成").disabled).toBe(true);
    onlyReads();
  });

  it("keeps a host-marked incomplete cleanup retryable after a native TASK_NOT_FOUND refresh", async () => {
    rows = [Object.assign(row({ receipt: { taskId: "native-1", status: "succeeded" } }), { cleanupPending: true })];
    await render();
    expect(container.textContent).toContain("清理未完成，可重试");
    rows = [Object.assign(row({ receipt: null, lastError: { code: "TASK_NOT_FOUND", message: "deleted native receipt" } }), { cleanupPending: true })];
    await click("刷新");
    const card = container.querySelector('article[data-task-state="unknown"]')!;
    expect(card.textContent).toContain("清理未完成，可重试");
    expect(card.textContent).not.toContain("正在推进");
    expect(card.closest('[data-task-group="attention"]')).toBeTruthy();
    expect(button("重试清理", card).disabled).toBe(false);
    expect(button("清理已完成").disabled).toBe(false);
    await click("重试清理", card);
    expect(operationCalls("previewTaskCleanup")).toHaveLength(1);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
    expect(button("永久删除", document.body).disabled).toBe(false);
    await click("取消", document.body);
    await click("清理已完成");
    expect(operationCalls("previewTaskCleanup")).toHaveLength(2);
  });

  it("does not treat a string cleanup flag or an unbound recovery reference as deletion authority", async () => {
    rows = [Object.assign(row({ receipt: null, lastError: { code: "TASK_NOT_FOUND" } }), { cleanupPending: "true" }),
      Object.assign(row({ dispatchId: "no-native", nativeTaskId: undefined, receipt: null }), { cleanupPending: true })];
    await render();
    const cards = [...container.querySelectorAll("article")];
    expect(button("删除", cards[0]).disabled).toBe(true);
    expect(button("重试清理", cards[1]).disabled).toBe(true);
    expect(button("清理已完成").disabled).toBe(true);
    onlyReads();
  });

  it("limits bulk cleanup to loaded successful endings and includes every team alias", async () => {
    terminal(); status.teamRunsVersion = 1;
    rows.push(row({ dispatchId: "failed", receipt: { taskId: "native-1", status: "failed" } }), row({ dispatchId: "active" }));
    const teamRows = [teamRun(), teamRun({ requestId: "request-2", originAction: "flow_start" }), teamRun({ requestId: "running", runId: "running", status: "running" })];
    teamReply = async () => teamPage(teamRows);
    await render(); await click("清理已完成");
    const request = operationCalls("previewTaskCleanup")[0][0] as unknown as { targets: unknown[] };
    expect(request.targets).toEqual([{ kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-1" },
      { kind: "team_run", projectId: "project-1", requestId: "request-1", originAction: "team_run", teamId: "team-1", flowId: "flow-1", runId: "run-1" },
      { kind: "team_run", projectId: "project-1", requestId: "request-2", originAction: "flow_start", teamId: "team-1", flowId: "flow-1", runId: "run-1" }]);
    expect(document.body.textContent).toContain("当前已加载且执行成功结束");
    expect(document.body.textContent).toContain("不代表业务已验收");
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
  });

  it("sends all team source references for a single terminal card and displays optional progress facts without inventing missing counts", async () => {
    status.teamRunsVersion = 1; rows = [];
    teamReply = async () => teamPage([teamRun({ teamName: "校验团队", projectName: "资料项目", current: 0, stepCount: 4,
      currentAgentName: "核验 Agent", resultSummary: "三份证据已核对" }), teamRun({ requestId: "request-2", originAction: "flow_start" })]);
    await render();
    expect(container.textContent).toContain("团队：校验团队");
    expect(container.textContent).toContain("项目：资料项目");
    expect(container.textContent).toContain("三份证据已核对");
    await click("详情");
    expect(container.textContent).toContain("当前步骤：0");
    expect(container.textContent).toContain("步骤数：4");
    expect(container.textContent).toContain("尝试次数：未提供");
    expect(container.textContent).toContain("当前 Agent：核验 Agent");
    await click("删除");
    const request = operationCalls("previewTaskCleanup")[0][0] as unknown as { targets: unknown[] };
    expect(request.targets).toHaveLength(2);
  });

  it.each(["identity", "hidden", "status_error"] as const)("invalidates a loaded cleanup preview after %s changes", async change => {
    terminal(); await render(); await click("删除");
    expect(button("永久删除", document.body).disabled).toBe(false);
    if (change === "identity") {
      status = { assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
      await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); }); await settle();
    } else if (change === "hidden") {
      visibility = "hidden"; await act(async () => { document.dispatchEvent(new Event("visibilitychange")); }); await settle();
    } else {
      invoke.mockImplementation(async (request: { operation: string }) => { if (request.operation === "status") throw new Error("identity offline"); return {}; });
      await act(async () => { await client.refetchQueries({ queryKey: ["launcher-assistant", "status"], exact: true }); }); await settle();
    }
    expect([...document.body.querySelectorAll("button")].some(element => element.textContent === "永久删除")).toBe(false);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
  });

  it("discards a late cleanup preview from a previous assistant identity", async () => {
    terminal();
    let resolvePreview!: (value: LauncherTaskCleanupPreview) => void;
    previewReply = () => new Promise(resolve => { resolvePreview = resolve; });
    await render(); await click("删除");
    expect(button("永久删除", document.body).disabled).toBe(true);
    status = { assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
    await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); }); await settle();
    await act(async () => { resolvePreview({ schemaVersion: 1, fingerprint: "old-preview", estimatedBytes: 1,
      items: [{ key: "old", title: "旧身份清理结果", status: "ready", estimatedBytes: 1, resources: [], retained: [] }] }); }); await settle();
    expect(document.body.textContent).not.toContain("旧身份清理结果");
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
  });

  it("does not request later preview batches after the assistant identity changes", async () => {
    rows = Array.from({ length: 33 }, (_, index) => row({ dispatchId: `dispatch-${index}`,
      receipt: { taskId: "native-1", status: "succeeded" } }));
    let resolvePreview!: (value: LauncherTaskCleanupPreview) => void;
    let firstTargets: LauncherTaskCleanupTarget[] = [];
    previewReply = request => { firstTargets = request.targets as LauncherTaskCleanupTarget[]; return new Promise(resolve => { resolvePreview = resolve; }); };
    await render(); await click("清理已完成");
    status = { assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
    await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); }); await settle();
    await act(async () => { resolvePreview({ schemaVersion: 1, fingerprint: "native-old", estimatedBytes: 32,
      items: firstTargets.map(target => ({ key: cleanupKey(target), title: "旧任务", status: "ready", estimatedBytes: 1, resources: [], retained: [] })) }); });
    await settle();
    expect(operationCalls("previewTaskCleanup")).toHaveLength(1);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
    expect(document.body.textContent).not.toContain("旧任务");
  });

  it("stops later execute batches on identity change without projecting an old result into the next assistant", async () => {
    rows = Array.from({ length: 33 }, (_, index) => row({ dispatchId: `dispatch-${index}`,
      receipt: { taskId: "native-1", status: "succeeded" } }));
    let resolveExecute!: (value: LauncherTaskCleanupResult) => void;
    let firstTargets: LauncherTaskCleanupTarget[] = [];
    executeReply = request => { firstTargets = request.targets as LauncherTaskCleanupTarget[]; return new Promise(resolve => { resolveExecute = resolve; }); };
    await render(); await click("清理已完成");
    expect(operationCalls("previewTaskCleanup")).toHaveLength(2);
    await click("永久删除", document.body);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    status = { assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
    await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); }); await settle();
    await act(async () => { resolveExecute({ schemaVersion: 1, releasedBytes: 32, items: firstTargets.map(target => ({
      key: cleanupKey(target), status: "deleted", releasedBytes: 1, retained: [], failures: [],
    })) }); }); await settle();
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    expect(document.body.textContent).not.toContain("任务清理结果");
  });

  it("prevents duplicate execution from two confirmation clicks in the same event batch", async () => {
    terminal();
    let resolveExecute!: (value: LauncherTaskCleanupResult) => void;
    executeReply = () => new Promise(resolve => { resolveExecute = resolve; });
    await render(); await click("删除");
    const confirm = button("永久删除", document.body);
    await act(async () => { confirm.click(); confirm.click(); }); await settle();
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    await act(async () => { resolveExecute({ schemaVersion: 1, releasedBytes: 0, items: [{
      key: dispatchCleanupKey, status: "blocked", releasedBytes: 0, retained: [], failures: [],
    }] }); }); await settle();
  });
});

afterEach(async () => {
  await act(async () => { root?.unmount(); });
  container.remove(); client.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers();
});

async function settle() {
  // Query notifications scheduled from an interval land on the next fake-clock tick.
  for (let index = 0; index < 5; index += 1) await act(async () => { await vi.advanceTimersByTimeAsync(1); });
}
async function render(lang: "zh" | "en" = "zh") {
  await act(async () => { root!.render(<QueryClientProvider client={client}>
    <LauncherAssistantTaskCards onReview={onReview} onApproval={onApproval} lang={lang} />
  </QueryClientProvider>); });
  await settle();
}
function button(label: string, within: ParentNode = container): HTMLButtonElement {
  const result = [...within.querySelectorAll<HTMLButtonElement>("button")].find(element => element.textContent === label);
  if (!result) throw new Error(`Missing button: ${label}`);
  return result;
}
async function click(label: string, within: ParentNode = container) {
  await act(async () => { button(label, within).click(); }); await settle();
}
function dispatchReads() { return invoke.mock.calls.filter(([request]) => request.operation === "dispatches").length; }
function teamReads() { return invoke.mock.calls.filter(([request]) => request.operation === "teamRuns").length; }
function onlyReads() { expect(invoke.mock.calls.every(([request]) => ["status", "dispatches", "teamRuns"].includes(request.operation))).toBe(true); }

describe("Launcher assistant task cards", () => {
  it("localizes the card, fallback title, details, and navigation when Launcher uses English", async () => {
    rows = [row({ title: undefined, receipt: { taskId: "native-1", status: "succeeded", shouldPoll: false } })];
    await render("en");
    expect(container.querySelector('section[aria-label="Assistant tasks"]')).toBeTruthy();
    expect(container.textContent).toContain("Untitled task · patch1");
    expect(container.textContent).toContain("Awaiting verification");
    expect(container.textContent).toContain("Showing tasks dispatched by your assistant");
    await click("Details");
    expect(container.textContent).toContain("Latest receipt summary");
    expect(container.textContent).toContain("No result summary yet.");
    expect(container.textContent).toContain("Project ID: project-1");
    expect(container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
    await click("Review in chat");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ state: "awaiting_verification" }));
    onlyReads();
  });

  it("shows a safe summary on the first screen while keeping technical identifiers in details", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "succeeded", resultSummary: '<img src=x onerror="alert(1)"> 周报待核对' } })];
    await render();
    expect(container.textContent).toContain("待验收");
    expect(container.textContent).not.toContain("dispatch-1");
    expect(container.textContent).toContain("周报待核对");
    expect(container.querySelector('button[aria-expanded="false"]')).toBeTruthy();
    await click("详情");
    expect(container.textContent).toContain("dispatch-1");
    expect(container.textContent).toContain("周报待核对");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector('button[aria-expanded="true"]')).toBeTruthy();
    await click("收起详情");
    expect(container.textContent).not.toContain("native-1");
  });

  it("only navigates to the existing approval flow and never decides an approval", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "awaiting_approval", shouldPoll: false, pendingApprovals: [{
      approvalId: "approval-1", toolName: "write", risk: "write", targetSummary: {}, revision: "r1", availableDecisions: ["accept", "decline"],
    }] } })];
    await render();
    await click("处理授权");
    expect(onApproval).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project-1", dispatchId: "dispatch-1", state: "waiting_user" }));
    expect(onReview).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("同意");
    onlyReads();
  });

  it("offers failure review without retry, restart, dispatch, or other mutations", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "failed", shouldPoll: false } })];
    await render(); await click("去对话核对");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ state: "failed", businessAcceptance: "not_evaluated" }));
    expect(onApproval).not.toHaveBeenCalled();
    expect([...container.querySelectorAll("button")].map(element => element.textContent)).not.toEqual(expect.arrayContaining(["重试任务", "重新派遣", "重启"]));
    onlyReads();
  });

  it("presents native success as awaiting verification and reviews the exact project and dispatch", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "succeeded", resultSummary: "所有目标已完成", shouldPoll: false } })];
    await render();
    expect(container.querySelector('[data-task-state="awaiting_verification"]')).toBeTruthy();
    expect(container.textContent).toContain("仍需核对实际结果");
    expect(container.textContent).toContain("所有目标已完成");
    await click("去对话核对");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project-1", dispatchId: "dispatch-1", state: "awaiting_verification" }));
    onlyReads();
  });

  it("distinguishes a first read failure from an available empty feed and does not auto retry", async () => {
    dispatchReply = async () => { throw new Error("offline"); };
    await render();
    expect(container.textContent).toContain("任务状态暂不可用");
    expect(container.textContent).not.toContain("暂无助理派遣任务");
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(dispatchReads()).toBe(1);
    rows = []; dispatchReply = async () => rows;
    await click("刷新");
    expect(container.textContent).toContain("暂无助理派遣任务");
    expect(dispatchReads()).toBe(2);
  });

  it("retains old cards as unknown after a poll fails and stops polling the error", async () => {
    await render();
    expect(container.textContent).toContain("执行中");
    dispatchReply = async () => { throw new Error("disconnected"); };
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(dispatchReads()).toBe(2);
    expect(client.getQueryState(["launcher-assistant", "task-cards", "assistant-1", "session-1"])).toMatchObject({ status: "error" });
    expect(container.textContent).toContain("核对周报");
    expect(container.querySelector('[data-task-state="unknown"]')).toBeTruthy();
    expect(container.textContent).toContain("保留上次记录");
    expect(container.textContent).not.toContain("暂无助理派遣任务");
    const reads = dispatchReads();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(dispatchReads()).toBe(reads);
  });

  it("does not turn unrelated shared status refreshes into automatic retries of a failed feed", async () => {
    dispatchReply = async () => { throw new Error("offline"); };
    await render();
    expect(dispatchReads()).toBe(1);
    for (let index = 0; index < 3; index += 1) {
      await act(async () => { await client.refetchQueries({ queryKey: ["launcher-assistant", "status"], exact: true }); });
      await settle();
    }
    expect(dispatchReads()).toBe(1);
    expect(container.textContent).toContain("任务状态暂不可用");
  });

  it.each([
    { status: "running", shouldPoll: false },
    { status: "succeeded", shouldPoll: true },
    { status: "unfamiliar", shouldPoll: true },
  ])("does not poll an idle, terminal, or unknown receipt: $status/$shouldPoll", async receipt => {
    rows = [row({ receipt: { taskId: "native-1", ...receipt } })];
    await render();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(dispatchReads()).toBe(1);
  });

  it("polls known active receipts only while visible and stops after unmount", async () => {
    await render();
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(dispatchReads()).toBe(2);
    visibility = "hidden";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(dispatchReads()).toBe(2);
    await act(async () => { root!.unmount(); root = null; });
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(dispatchReads()).toBe(2);
  });

  it("keeps same-dispatch identifiers from different projects bound to their own summary and callback", async () => {
    rows = [row({ title: "项目甲", receipt: { taskId: "native-1", status: "failed", resultSummary: "甲的摘要" } }),
      row({ projectId: "project-2", title: "项目乙", receipt: { taskId: "native-1", status: "failed", resultSummary: "乙的摘要" } })];
    await render();
    const second = container.querySelector('article[aria-label="项目乙"]')!;
    await click("详情", second);
    expect(second.textContent).toContain("乙的摘要");
    expect(second.textContent).not.toContain("甲的摘要");
    await click("去对话核对", second);
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project-2", dispatchId: "dispatch-1" }));
  });

  it("shows ten cards initially and reveals more without claiming complete platform coverage", async () => {
    rows = Array.from({ length: 12 }, (_, index) => row({ dispatchId: `dispatch-${index}`, title: `任务 ${index}`,
      receipt: { taskId: "native-1", status: "succeeded", shouldPoll: false } }));
    await render();
    expect(container.querySelectorAll("article")).toHaveLength(10);
    expect(container.textContent).toContain("这里显示助理已派出的任务");
    await click("显示更多");
    expect(container.querySelectorAll("article")).toHaveLength(12);
    expect(container.textContent).not.toContain("全部任务");
    expect(dispatchReads()).toBe(1);
  });

  it("aborts obsolete identity responses instead of caching them for the next assistant", async () => {
    let resolveOld!: (value: LauncherAssistantDispatch[]) => void;
    dispatchReply = () => new Promise(resolve => { resolveOld = resolve; });
    await render();
    const next = { assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
    dispatchReply = async () => [row({ title: "新身份任务", receipt: { taskId: "native-1", status: "failed" } })];
    await act(async () => { client.setQueryData(["launcher-assistant", "status"], next); }); await settle();
    expect(container.textContent).toContain("新身份任务");
    await act(async () => { resolveOld([row({ title: "过期身份任务" })]); }); await settle();
    expect(container.textContent).not.toContain("过期身份任务");
    expect(client.getQueryData(["launcher-assistant", "task-cards", "assistant-1", "session-1"])).toBeUndefined();
    expect(client.getQueryData(["launcher-assistant", "task-cards", "assistant-2", "session-2"])).toEqual(expect.any(Array));
  });

  it("does not expose cached cards before the current opening verifies the assistant identity", async () => {
    client.setQueryData(["launcher-assistant", "status"], status);
    client.setQueryData(["launcher-assistant", "task-cards", "assistant-1", "session-1"], [row({
      title: "旧身份的任务", receipt: { taskId: "native-1", status: "failed" },
    })]);
    let resolveStatus!: (value: LauncherAssistantStatus) => void;
    invoke.mockImplementation(async (request: { operation: string }) => {
      if (request.operation === "status") return new Promise<LauncherAssistantStatus>(resolve => { resolveStatus = resolve; });
      if (request.operation === "dispatches") return { dispatches: [row({ title: "当前身份的任务" })] };
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    await render();
    expect(container.textContent).toContain("正在读取任务");
    expect(container.textContent).not.toContain("旧身份的任务");
    expect(container.querySelector("article")).toBeNull();
    expect(onReview).not.toHaveBeenCalled();
    expect(onApproval).not.toHaveBeenCalled();
    expect(dispatchReads()).toBe(0);
    await act(async () => { resolveStatus({ assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } }); });
    await settle();
    expect(container.textContent).toContain("当前身份的任务");
    expect(container.textContent).not.toContain("旧身份的任务");
  });

  it("keeps older hosts on the dispatch source without requesting team runs", async () => {
    await render();
    expect(dispatchReads()).toBe(1);
    expect(teamReads()).toBe(0);
  });

  it("shares the card layout and keeps team completion awaiting actual verification", async () => {
    status.teamRunsVersion = 1;
    teamReply = async () => teamPage([teamRun()]);
    await render();
    const card = container.querySelector('article[data-task-kind="team_run"]')!;
    expect(card.getAttribute("data-task-state")).toBe("awaiting_verification");
    expect(card.textContent).toContain("待验收");
    expect(card.textContent).not.toContain("run-1");
    expect(container.textContent).toContain("关联团队运行");
    await click("详情", card);
    expect(card.textContent).toContain("团队编号：team-1");
    expect(card.textContent).toContain("流程编号：flow-1");
    expect(card.textContent).toContain("运行编号：run-1");
    await click("去对话核对", card);
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ kind: "team_run", projectId: "project-1",
      runId: "run-1", state: "awaiting_verification", businessAcceptance: "not_evaluated" }));
    expect(onApproval).not.toHaveBeenCalled();
    onlyReads();
  });

  it("treats a team input wait as review in chat without offering authorization", async () => {
    status.teamRunsVersion = 1;
    rows = [];
    teamReply = async () => teamPage([teamRun({ status: "waiting", title: "" })]);
    await render("en");
    expect(container.textContent).toContain("Untitled task · quest1");
    expect(container.textContent).toContain("Waiting for input");
    expect(container.textContent).not.toContain("authorization");
    expect(container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
    await click("Review in chat");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ kind: "team_run", state: "waiting_input" }));
    expect(onApproval).not.toHaveBeenCalled();
    onlyReads();
  });

  it("keeps dispatch cards current when the independent team source fails and does not retry that source", async () => {
    status.teamRunsVersion = 1;
    teamReply = async () => { throw new Error("team offline"); };
    await render();
    expect(container.textContent).toContain("团队运行状态暂不可用");
    expect(container.querySelector('article[data-task-kind="dispatch"]')?.getAttribute("data-task-state")).toBe("running");
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(teamReads()).toBe(1);
    expect(dispatchReads()).toBe(2);
    teamReply = async () => teamPage([teamRun()]);
    await click("刷新");
    expect(teamReads()).toBe(2);
    expect(container.querySelector('article[data-task-kind="team_run"]')?.getAttribute("data-task-state")).toBe("awaiting_verification");
  });

  it("retains team cards as unknown after a failed active poll while leaving dispatch receipts intact", async () => {
    status.teamRunsVersion = 1;
    teamReply = async () => teamPage([teamRun({ status: "running" })]);
    await render();
    teamReply = async () => { throw new Error("team offline"); };
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(teamReads()).toBe(2);
    expect(container.querySelector('article[data-task-kind="team_run"]')?.getAttribute("data-task-state")).toBe("unknown");
    expect(container.querySelector('article[data-task-kind="dispatch"]')?.getAttribute("data-task-state")).toBe("running");
    await click("去对话核对", container.querySelector('article[data-task-kind="team_run"]')!);
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ runId: null, teamId: null, flowId: null,
      nativeStatus: null, revision: null, observedAt: null, receiptBound: false, lastKnown: expect.objectContaining({ runId: "run-1" }) }));
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); }); await settle();
    expect(teamReads()).toBe(2);
  });

  it("keeps partial unknown observations manual and suspends known active team reads when hidden", async () => {
    status.teamRunsVersion = 1;
    rows = [];
    teamReply = async () => teamPage([teamRun({ status: null, observedAt: null, readState: "unknown" })], { state: "partial" });
    await render();
    expect(container.textContent).toContain("部分团队运行待核对");
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(teamReads()).toBe(1);
    teamReply = async () => teamPage([teamRun({ status: "running" })]);
    await click("刷新");
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(teamReads()).toBe(3);
    visibility = "hidden";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(teamReads()).toBe(3);
  });

  it("uses the existing show-more action for local cards and then cursor pagination", async () => {
    status.teamRunsVersion = 1;
    rows = [];
    const runs = Array.from({ length: 17 }, (_, index) => teamRun({ requestId: `request-${index}`, runId: `run-${index}` }));
    const cursor = btoa(JSON.stringify({ snapshot: "a".repeat(64), offset: 16 })).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
    teamReply = async value => value === cursor
      ? teamPage(runs.slice(16), { offset: 16, total: 17 })
      : teamPage(runs.slice(0, 16), { total: 17, nextCursor: cursor });
    await render();
    expect(container.querySelectorAll("article")).toHaveLength(10);
    expect(teamReads()).toBe(1);
    await click("显示更多");
    expect(container.querySelectorAll("article")).toHaveLength(16);
    expect(teamReads()).toBe(1);
    await click("显示更多");
    expect(container.querySelectorAll("article")).toHaveLength(17);
    expect(teamReads()).toBe(2);
    expect(invoke).toHaveBeenCalledWith({ operation: "teamRuns", cursor });
    expect(container.textContent).toContain("历史记录可能不完整");
  });

  it("hides cached team cards until identity confirmation and discards a late old-identity response", async () => {
    status.teamRunsVersion = 1;
    client.setQueryData(["launcher-assistant", "status"], status);
    client.setQueryData(["launcher-assistant", "team-task-cards", "assistant-1", "session-1"], {
      pages: [teamPage([teamRun({ title: "旧团队缓存" })])], pageParams: [undefined],
    });
    let resolveStatus!: (value: LauncherAssistantStatus) => void;
    let resolveTeam!: (value: LauncherAssistantTeamRunsPage) => void;
    invoke.mockImplementation(async (request: { operation: string }) => {
      if (request.operation === "status") return new Promise<LauncherAssistantStatus>(resolve => { resolveStatus = resolve; });
      if (request.operation === "dispatches") return { dispatches: [] };
      if (request.operation === "teamRuns") return teamReply();
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    teamReply = () => new Promise(resolve => { resolveTeam = resolve; });
    await render();
    expect(container.textContent).not.toContain("旧团队缓存");
    expect(teamReads()).toBe(0);
    await act(async () => { resolveStatus(status); }); await settle();
    const oldPage = teamPage([teamRun({ title: "过期团队返回" })]);
    status = { teamRunsVersion: 1, assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
    teamReply = async () => teamPage([teamRun({ title: "新身份团队" })]);
    await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); }); await settle();
    expect(container.textContent).toContain("新身份团队");
    await act(async () => { resolveTeam(oldPage); }); await settle();
    expect(container.textContent).not.toContain("过期团队返回");
    expect(container.textContent).not.toContain("旧团队缓存");
    expect(onReview).not.toHaveBeenCalled();
  });

  it("does not describe a partial zero-row team read as an available empty task list", async () => {
    status.teamRunsVersion = 1;
    rows = [];
    teamReply = async () => teamPage([], { state: "partial",
      coverage: { kind: "local_associations", historyComplete: false, legacyUnrecoverable: 1, invalidRecords: 1 } });
    await render();
    expect(container.textContent).toContain("部分团队运行待核对");
    expect(container.textContent).not.toContain("暂无助理任务");
    expect(container.textContent).not.toContain("暂无助理派遣任务");
  });

  it("retains both confirmed-identity sources as unknown if shared identity refresh fails", async () => {
    status.teamRunsVersion = 1;
    teamReply = async () => teamPage([teamRun({ status: "running" })]);
    await render();
    invoke.mockImplementation(async (request: { operation: string }) => {
      if (request.operation === "status") throw new Error("identity offline");
      if (request.operation === "dispatches") return { dispatches: rows };
      if (request.operation === "teamRuns") return teamReply();
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    await click("刷新");
    expect(container.querySelectorAll('article[data-task-state="unknown"]')).toHaveLength(2);
    expect(container.textContent).toContain("团队周报");
    const dispatchCount = dispatchReads(), teamCount = teamReads();
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(dispatchReads()).toBe(dispatchCount);
    expect(teamReads()).toBe(teamCount);
    expect(button("去对话核对").disabled).toBe(true);
    expect(onReview).not.toHaveBeenCalled();
    invoke.mockImplementation(async (request: { operation: string }) => {
      if (request.operation === "status") return status;
      if (request.operation === "dispatches") return { dispatches: rows };
      if (request.operation === "teamRuns") return teamReply();
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    await click("刷新");
    expect(dispatchReads()).toBeGreaterThan(dispatchCount);
    expect(teamReads()).toBeGreaterThan(teamCount);
    expect(container.querySelectorAll('article[data-task-state="running"]')).toHaveLength(2);
  });

  it("keeps last-verified display facts across a successful unknown read, updates on recovery and drops deleted requests", async () => {
    status.teamRunsVersion = 1;
    rows = [];
    teamReply = async () => teamPage([teamRun({ status: "running" })]);
    await render();
    const original = container.querySelector('article[data-task-kind="team_run"]')!;
    await click("详情", original);
    const unknown = teamRun({ teamId: null, flowId: null, runId: null, status: null, revision: null,
      title: "", observedAt: null, readState: "unknown" });
    teamReply = async () => teamPage([unknown], { state: "partial" });
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    let card = container.querySelector('article[data-task-kind="team_run"]')!;
    // Moving from in-progress to needs-attention changes the group container.
    await click("详情", card);
    expect(card.getAttribute("data-task-state")).toBe("unknown");
    expect(card.textContent).toContain("团队周报");
    expect(card.textContent).toContain("以下为上次核验的信息");
    expect(card.textContent).toContain("运行编号：run-1");
    expect(card.textContent).toContain("版本：r1");
    expect(card.textContent).toContain("2026-11-02T01:00:00Z");
    await click("去对话核对", card);
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ teamId: null, flowId: null, runId: null,
      nativeStatus: null, revision: null, observedAt: null, receiptBound: false, shouldPoll: false,
      lastKnown: expect.objectContaining({ runId: "run-1" }) }));
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(teamReads()).toBe(2);
    await click("刷新");
    expect(card.textContent).toContain("团队周报");
    teamReply = async () => teamPage([teamRun({ title: "更新后的周报", status: "completed", revision: "r2", observedAt: "2026-11-02T02:00:00Z" })]);
    await click("刷新");
    card = container.querySelector('article[data-task-kind="team_run"]')!;
    await click("详情", card);
    expect(card.getAttribute("data-task-state")).toBe("awaiting_verification");
    expect(card.textContent).toContain("更新后的周报");
    expect(card.textContent).toContain("版本：r2");
    expect(card.textContent).not.toContain("上次核验的信息");
    teamReply = async () => teamPage([]);
    await click("刷新");
    expect(container.querySelector("article")).toBeNull();
    teamReply = async () => teamPage([unknown], { state: "partial" });
    await click("刷新");
    expect(container.textContent).not.toContain("更新后的周报");
    expect(container.textContent).not.toContain("上次核验的信息");
  });

  it("does not borrow last-verified display facts from another assistant with the same source request", async () => {
    status.teamRunsVersion = 1;
    rows = [];
    teamReply = async () => teamPage([teamRun({ title: "仅旧助理可见" })]);
    await render();
    status = { teamRunsVersion: 1, assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
    teamReply = async () => teamPage([teamRun({ title: "", teamId: null, flowId: null, runId: null,
      status: null, revision: null, observedAt: null, readState: "unknown" })], { state: "partial" });
    await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); }); await settle();
    expect(container.textContent).not.toContain("仅旧助理可见");
    await click("详情");
    expect(container.textContent).not.toContain("上次核验的信息");
    expect(container.textContent).not.toContain("run-1");
    await click("去对话核对");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ state: "unknown", runId: null, lastKnown: null }));
  });

  it("keeps two aliases as one unknown card and removes a revoked alias from the next read", async () => {
    status.teamRunsVersion = 1;
    rows = [];
    const alias = { requestId: "request-2", originAction: "flow_start" as const };
    teamReply = async () => teamPage([teamRun(), teamRun(alias)]);
    await render();
    expect(container.querySelectorAll("article")).toHaveLength(1);
    const unknown = { title: "", teamId: null, flowId: null, runId: null, status: null, revision: null,
      observedAt: null, readState: "unknown" as const };
    teamReply = async () => teamPage([teamRun(unknown), teamRun({ ...unknown, ...alias })], { state: "partial" });
    await click("刷新");
    expect(container.querySelectorAll("article")).toHaveLength(1);
    await click("去对话核对");
    expect(onReview.mock.lastCall?.[0].sourceRefs).toHaveLength(2);
    teamReply = async () => teamPage([teamRun({ ...unknown, ...alias })], { state: "partial" });
    await click("刷新");
    expect(container.querySelectorAll("article")).toHaveLength(1);
    await click("去对话核对");
    expect(onReview.mock.lastCall?.[0].sourceRefs).toEqual([alias]);
  });

  it.each(["hidden", "unmounted"] as const)("does not continue manual source reads if the view is %s while identity refresh is pending", async disposition => {
    status.teamRunsVersion = 1;
    teamReply = async () => teamPage([teamRun()]);
    await render();
    let resolveStatus!: (value: LauncherAssistantStatus) => void;
    invoke.mockImplementation(async (request: { operation: string }) => {
      if (request.operation === "status") return new Promise<LauncherAssistantStatus>(resolve => { resolveStatus = resolve; });
      if (request.operation === "dispatches") return { dispatches: rows };
      if (request.operation === "teamRuns") return teamReply();
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    await click("刷新");
    if (disposition === "hidden") {
      visibility = "hidden";
      await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    } else await act(async () => { root!.unmount(); root = null; });
    const dispatchCount = dispatchReads(), teamCount = teamReads();
    await act(async () => { resolveStatus(status); }); await settle();
    expect(dispatchReads()).toBe(dispatchCount);
    expect(teamReads()).toBe(teamCount);
  });
});
