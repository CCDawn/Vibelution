// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LauncherAssistantDispatch, LauncherAssistantStatus, LauncherAssistantTeamRun, LauncherAssistantTeamRunsPage } from "../../../api/launcherAssistant";
import { LauncherAssistantTaskCards } from "./LauncherAssistantTaskCards";
import { LauncherAssistantTaskSidebar } from "./LauncherAssistantTaskSidebar";
import { LauncherTaskModelControls } from "./__fixtures__/LauncherTaskModelControls";
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

describe("task card facts and direct cleanup", () => {
  function operationCalls(operation: string) { return invoke.mock.calls.filter(([request]) => request.operation === operation); }
  const terminal = () => { rows = [row({ receipt: { taskId: "native-1", status: "succeeded", resultSummary: "已生成周报，待人工核对" } })]; };

  it("keeps the card to its task title and human owner, with project and receipt facts in the dialog", async () => {
    rows = [row({ agentName: "报告 Agent", projectName: "周报项目", updatedAt: "2026-11-02T03:04:00Z", createdAt: "2026-11-01T01:00:00Z",
      receipt: { taskId: "native-1", status: "running", resultSummary: "已整理三份资料，正在核对来源" } })];
    await render();
    const card = container.querySelector("article")!;
    expect(card.textContent).toContain("核对周报");
    expect(card.textContent).toContain("报告 Agent · 执行中");
    expect(card.querySelectorAll("button")).toHaveLength(1);
    expect(card.textContent).not.toContain("周报项目");
    expect(card.textContent).not.toContain("已整理三份资料");
    expect(card.textContent).not.toContain("worker-1");
    expect(card.textContent).not.toContain("project-1");
    expect(card.textContent).not.toContain("native-1");
    const dialog = await openTask(card);
    expect(container.contains(dialog)).toBe(false);
    expect(dialog.getAttribute("role")).toBe("dialog");
    expect(dialog.textContent).toContain("负责人：报告 Agent");
    expect(dialog.textContent).toContain("项目：周报项目");
    expect(dialog.textContent).toContain("已整理三份资料，正在核对来源");
    expect(dialog.textContent).not.toContain("更新：未提供");
    expect(dialog.textContent).not.toContain("native-1");
    await click("引用信息", dialog);
    expect(dialog.textContent).toContain("原生任务编号：native-1");
  });

  it("uses a human owner for legacy names and never uses identifiers or prompt/code bodies as card copy", async () => {
    rows = [row({ dispatchId: "legacy-111111", agentName: "报告 Agent", title: "助理任务", receipt: { taskId: "native-1", status: "failed" } }),
      Object.assign(row({ dispatchId: "legacy-222222", title: undefined }), { prompt: "secret prompt body", code: "source code body" })];
    await render();
    await click("已结束 1");
    expect(container.textContent).toContain("报告 Agent的委派任务");
    await click("进行中 1");
    expect(container.querySelector("article")?.getAttribute("aria-label")).toBe("委派任务");
    expect(container.textContent).not.toContain("secret prompt body");
    expect(container.textContent).not.toContain("source code body");
    expect(container.textContent).not.toContain("222222");
    await click("已结束 1");
    expect(container.textContent).not.toContain("111111");
    expect(container.textContent).not.toContain("222222");
    expect(container.textContent).not.toContain("未命名任务");
    expect(container.textContent).not.toContain("secret prompt body");
    expect(container.textContent).not.toContain("source code body");
    expect(container.textContent).not.toContain("worker-1");
    expect(container.textContent).not.toContain("project-1");
  });

  it("uses a native receipt error as the failure explanation but never calls a communication error task failure", async () => {
    rows = [row({ title: "真实失败", receipt: { taskId: "native-1", status: "failed", error: { message: "远程仓库拒绝访问" } } }),
      row({ dispatchId: "dispatch-sync", title: "连接中断", lastError: { message: "offline" }, receipt: { taskId: "native-1", status: "failed" } }),
      row({ dispatchId: "dispatch-unbound", title: "尚未绑定", nativeTaskId: undefined, receipt: null })];
    await render();
    await click("已结束 2");
    const sync = container.querySelector('article[aria-label="连接中断"]')!;
    expect(sync.getAttribute("data-task-state")).toBe("unknown");
    expect(sync.textContent).not.toContain("执行失败");
    const syncDialog = await openTask(sync);
    expect(button("移除记录", syncDialog).disabled).toBe(false);
    await click("关闭", syncDialog);
    await click("待处理 1");
    expect(container.querySelector('article[aria-label="尚未绑定"]')?.getAttribute("data-task-state")).toBe("unknown");
    await click("已结束 2");
    const failed = container.querySelector('article[aria-label="真实失败"]')!;
    expect(failed.textContent).toContain("执行失败");
    expect((await openTask(failed)).textContent).toContain("远程仓库拒绝访问");
  });

  it("attaches the failure code label to the failure reason while an unknown code stays silent", async () => {
    rows = [row({ title: "分类失败", receipt: { taskId: "native-1", status: "failed", error: { code: "TASK_NOT_FOUND", message: "native receipt missing" } } }),
      row({ dispatchId: "dispatch-future", title: "未知码失败", receipt: { taskId: "native-1", status: "failed", error: { code: "FUTURE_CODE", message: "opaque failure" } } })];
    await render();
    const classified = await openTask(container.querySelector('article[aria-label="分类失败"]')!);
    expect(classified.textContent).toContain("任务不存在");
    expect(classified.textContent).toContain("native receipt missing");
    await click("关闭", classified);
    const opaque = await openTask(container.querySelector('article[aria-label="未知码失败"]')!);
    expect(opaque.textContent).toContain("opaque failure");
    expect(opaque.textContent).not.toContain("任务不存在");
    await click("关闭", opaque);
  });

  it("shows current loaded group counts and sorts real task times inside each group", async () => {
    rows = [row({ dispatchId: "old", title: "较早任务", updatedAt: "2026-11-01T00:00:00Z" }),
      row({ dispatchId: "new", title: "较新任务", updatedAt: "2026-11-02T00:00:00Z" }),
      row({ dispatchId: "wait", title: "等待授权", receipt: { taskId: "native-1", status: "awaiting_approval" } }),
      row({ dispatchId: "done", title: "已结束任务", receipt: { taskId: "native-1", status: "succeeded" } })];
    await render();
    expect(button("待处理 1").getAttribute("aria-selected")).toBe("true");
    expect(button("进行中 2")).toBeTruthy();
    expect(button("已结束 1")).toBeTruthy();
    expect([...container.querySelectorAll("article")].map(element => element.getAttribute("aria-label"))).toEqual(["等待授权"]);
    await click("进行中 2");
    expect([...container.querySelectorAll('[data-task-group="active"] [data-task-title]')].map(element => element.textContent)).toEqual(["较新任务", "较早任务"]);
    await click("进行中 2");
    expect(container.querySelectorAll('[data-task-group="active"] article')).toHaveLength(2);
    await click("已结束 1");
    expect([...container.querySelectorAll("article")].map(element => element.getAttribute("aria-label"))).toEqual(["已结束任务"]);
    expect(container.textContent).not.toContain("全平台");
  });

  it("keeps long receipt summaries out of cards and makes the complete summary available in the dialog", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "running", resultSummary: "长摘要".repeat(80) } })];
    await render();
    expect(container.textContent).not.toContain("长摘要");
    expect((await openTask()).textContent).toContain("长摘要".repeat(80));
  });

  it("keeps loaded cards while the model refresh is pending", async () => {
    await render();
    let resolveRows!: (value: LauncherAssistantDispatch[]) => void;
    dispatchReply = () => new Promise(resolve => { resolveRows = resolve; });
    await click("刷新");
    expect(container.querySelector("article")).toBeTruthy();
    expect(button("刷新").disabled).toBe(true);
    expect(container.querySelector('[data-vui="skeleton"]')).toBeNull();
    await act(async () => { resolveRows(rows); }); await settle();
  });

  it("keeps public Agent names when task and team observations open together", async () => {
    status.teamRunsVersion = 1;
    let teamReading = false;
    let finishTeam!: () => void;
    teamReply = () => {
      teamReading = true;
      return new Promise(resolve => { finishTeam = () => { teamReading = false; resolve(teamPage([])); }; });
    };
    // Native optional names yield while a team read owns the project reader.
    dispatchReply = async () => {
      await Promise.resolve();
      return [row({ title: "", agentName: teamReading ? undefined : "报告 Agent",
        receipt: { taskId: "native-1", status: "failed" } })];
    };
    await render();
    await act(async () => { finishTeam(); }); await settle();
    expect(container.querySelector("article")?.textContent).toContain("报告 Agent · 执行失败");
  });

  it("does not start a queued native read after the task view becomes hidden", async () => {
    status.teamRunsVersion = 1;
    let finishTeam!: () => void;
    teamReply = () => new Promise(resolve => { finishTeam = () => resolve(teamPage([])); });
    await render();
    // A running dispatch poll can queue while a slow team read is pending.
    await act(async () => { await vi.advanceTimersByTimeAsync(3_001); });
    expect(client.getQueryState(["launcher-assistant", "task-cards", "assistant-1", "session-1"])?.fetchStatus).toBe("fetching");
    const readsBeforeHide = dispatchReads();
    visibility = "hidden";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await act(async () => { finishTeam(); }); await settle();
    expect(dispatchReads()).toBe(readsBeforeHide);
  });

  it("cleans one card directly without opening details or requesting confirmation", async () => {
    terminal();
    executeReply = async () => { rows = []; return { schemaVersion: 1, releasedBytes: 3072,
      items: [{ key: dispatchCleanupKey, status: "deleted", releasedBytes: 3072, retained: [], failures: [] }] }; };
    await render();
    const card = container.querySelector("article")!;
    expect(card.querySelectorAll("button")).toHaveLength(2);
    expect(card.querySelector("button button")).toBeNull();
    await click("清理“核对周报”", card);
    expect(document.body.querySelector('[data-vui="launcher-task-detail"]')).toBeNull();
    expect(operationCalls("previewTaskCleanup")).toHaveLength(1);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    expect(invoke).toHaveBeenCalledWith({ operation: "executeTaskCleanup", agentId: "assistant-1", directSessionId: "session-1", fingerprint: "preview-1",
      targets: [{ kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-1" }] });
    expect(document.body.textContent).toContain("实际释放 3,072 字节");
    expect(document.body.textContent).not.toContain("永久删除");
    expect(document.body.textContent).not.toContain("预计释放");
    expect(container.querySelector("article")).toBeNull();
    expect(dispatchReads()).toBe(2);
  });

  it("also cleans directly from an already open detail dialog", async () => {
    terminal(); await render();
    await cleanupFromDetail();
    expect(operationCalls("previewTaskCleanup")).toHaveLength(1);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    expect(document.body.textContent).toContain("已清理");
  });

  it("retains partial results and retries only the incomplete references in one click", async () => {
    terminal();
    rows.push(row({ dispatchId: "dispatch-2", title: "另一项", receipt: { taskId: "native-1", status: "failed" } }));
    executeReply = async request => ({ schemaVersion: 1, releasedBytes: 1024,
      items: (request.targets as LauncherTaskCleanupTarget[]).map(target => ({ key: cleanupKey(target),
        status: cleanupKey(target) === dispatchCleanupKey ? "deleted" : "partial", releasedBytes: 512,
        retained: [{ kind: "session", reason: "仍有共享引用" }], failures: cleanupKey(target) === dispatchCleanupKey
          ? [] : [{ code: "FILE_BUSY", message: "文件正在使用" }] })) });
    await render(); await click("清理已结束");
    expect(container.querySelectorAll("article")).toHaveLength(2);
    expect(document.body.textContent).toContain("文件正在使用");
    expect(document.body.textContent).toContain("仍有共享引用");
    await click("重试清理", document.body.querySelector('[data-vui="launcher-task-cleanup"]')!);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(2);
    expect((operationCalls("previewTaskCleanup")[1][0] as unknown as { targets: unknown[] }).targets)
      .toEqual([{ kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-2" }]);
  });

  it("shows an unconfirmed execution failure and retries only on an explicit retry click", async () => {
    terminal(); executeReply = async () => { throw new Error("cleanup backend offline"); };
    await render(); await click("清理“核对周报”");
    expect(document.body.textContent).toContain("清理未获确认");
    expect(document.body.textContent).toContain("cleanup backend offline");
    expect(container.querySelector("article")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    await click("重试清理");
    expect(operationCalls("previewTaskCleanup")).toHaveLength(2);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(2);
  });

  it("preserves the host's blocking reason and offers a direct retry", async () => {
    terminal(); previewReply = async () => ({ schemaVersion: 1, fingerprint: "blocked", estimatedBytes: 0,
      items: [{ key: dispatchCleanupKey, title: "核对周报", status: "blocked", estimatedBytes: 0, resources: [], retained: [], reason: "工作目录含未合入代码" }] });
    await render(); await click("清理“核对周报”");
    expect(document.body.textContent).toContain("工作目录含未合入代码");
    expect(document.body.textContent).toContain("暂不能清理");
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
    previewReply = async () => { throw new Error("source unavailable"); };
    await click("重试清理");
    expect(document.body.textContent).toContain("source unavailable");
    expect(operationCalls("previewTaskCleanup")).toHaveLength(2);
  });

  it("keeps active tasks disabled while sending unknown local references to the host for verification", async () => {
    rows = [row(), row({ dispatchId: "unknown", title: "待同步任务", nativeTaskId: undefined, receipt: null })];
    previewReply = async request => ({ schemaVersion: 1, fingerprint: "blocked", estimatedBytes: 0,
      items: (request.targets as LauncherTaskCleanupTarget[]).map(target => ({ key: cleanupKey(target), title: "待同步任务",
        status: "blocked", estimatedBytes: 0, resources: [], retained: [], reason: "任务尚未结束" })) });
    await render();
    expect(button("清理已结束").disabled).toBe(false);
    const remove = button("移除记录“待同步任务”");
    expect(remove.textContent).toBe("");
    expect(remove.querySelector("svg")).not.toBeNull();
    await act(async () => { remove.focus(); }); await settle();
    expect(document.body.querySelector('[role="tooltip"]')?.textContent).toBe("移除记录 · 核验后仅移除本地记录，保留源任务和文件");
    await click("移除记录“待同步任务”");
    expect(document.body.querySelector('[data-vui="launcher-task-detail"]')).toBeNull();
    expect((operationCalls("previewTaskCleanup")[0][0] as unknown as { targets: unknown[] }).targets)
      .toEqual([{ kind: "dispatch", projectId: "project-1", dispatchId: "unknown", localOnly: true }]);
    expect(document.body.textContent).toContain("任务尚未结束");
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
    await click("关闭"); await click("进行中 1");
    expect(container.querySelector("article")!.querySelectorAll("button")).toHaveLength(1);
    expect(button("清理", await openTask()).disabled).toBe(true);
  });

  it.each(["zh", "en"] as const)("requests local-only removal of an unknown team association without native run IDs in %s", async lang => {
    rows = []; status.teamRunsVersion = 1;
    teamReply = async () => teamPage([teamRun({ teamId: null, flowId: null, runId: null, status: null, observedAt: null, readState: "unknown" })], { state: "partial" });
    await render(lang); await click(lang === "zh" ? "移除记录“团队周报”" : "Remove record “团队周报”");
    expect((operationCalls("previewTaskCleanup")[0][0] as unknown as { targets: unknown[] }).targets)
      .toEqual([{ kind: "team_run", projectId: "project-1", requestId: "request-1", originAction: "team_run", localOnly: true }]);
    expect((operationCalls("executeTaskCleanup")[0][0] as unknown as { targets: unknown[] }).targets)
      .toEqual([{ kind: "team_run", projectId: "project-1", requestId: "request-1", originAction: "team_run", localOnly: true }]);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
  });

  it("keeps local-only removal when retrying an unknown dispatch from its detail and translates retained source resources", async () => {
    rows = [row({ lastError: { message: "offline" }, receipt: { taskId: "native-1", status: "failed" } })];
    const retained = [{ kind: "source_resources", reason: "本次仅移除本地关联。" }];
    executeReply = async request => ({ schemaVersion: 1, releasedBytes: 0,
      items: (request.targets as LauncherTaskCleanupTarget[]).map(target => ({ key: cleanupKey(target), status: "blocked",
        releasedBytes: 0, retained, failures: [{ code: "cleanup_source_unconfirmed", message: "尚未确认源任务的身份和状态" }] })) });
    await render();
    const detail = await openTask();
    await click("移除记录", detail);
    const result = document.body.querySelector('[data-vui="launcher-task-cleanup"]')!;
    expect(result.textContent).toContain("核验后仅移除本地记录，保留源任务和文件。");
    expect(result.textContent).toContain("保留 源任务和文件 — 本次仅移除本地关联。");
    expect(result.textContent).toContain("尚未确认源任务的身份和状态");
    await click("重试清理", result);
    for (const [request] of [...operationCalls("previewTaskCleanup"), ...operationCalls("executeTaskCleanup")])
      expect((request as unknown as { targets: unknown[] }).targets)
        .toEqual([{ kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-1", localOnly: true }]);
    expect(operationCalls("previewTaskCleanup")).toHaveLength(2);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(2);
    expect(container.querySelector("article")).toBeTruthy();
  });

  it("keeps incomplete host cleanup in ended tasks even after TASK_NOT_FOUND", async () => {
    rows = [Object.assign(row({ receipt: null, lastError: { code: "TASK_NOT_FOUND", message: "deleted native receipt" } }), { cleanupPending: true })];
    await render();
    const card = container.querySelector('article[data-task-state="unknown"]')!;
    expect(card.textContent).toContain("待清理");
    expect(card.closest('[data-task-group="ended"]')).toBeTruthy();
    await click("清理已结束");
    expect(operationCalls("previewTaskCleanup")).toHaveLength(1);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
  });

  it("groups bound historical terminal receipts as ended and degrades bulk unknown targets to record-only removal", async () => {
    rows = [row({ title: "待同步的已结束任务", lastError: { message: "offline" }, receipt: { taskId: "native-1", status: "failed" } }),
      row({ dispatchId: "unbound", receipt: { taskId: "other", status: "succeeded" } })];
    await render();
    expect(button("已结束 1")).toBeTruthy();
    expect(button("待处理 1")).toBeTruthy();
    expect(container.querySelector("article")?.getAttribute("data-task-state")).toBe("unknown");
    await click("清理已结束");
    const targets = (operationCalls("previewTaskCleanup")[0][0] as unknown as { targets: LauncherTaskCleanupTarget[] }).targets;
    // Bulk unknown-state targets match single-item removals: verified
    // record-only degradation, never a silent strict path.
    expect(targets).toEqual([{ kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-1", localOnly: true },
      { kind: "dispatch", projectId: "project-1", dispatchId: "unbound", localOnly: true }]);
  });

  it.each(["succeeded", "failed", "timed_out", "cancelled"])("keeps a bound %s receipt with a source error in ended tasks", async nativeStatus => {
    rows = [row({ lastError: { message: "offline" }, receipt: { taskId: "native-1", status: nativeStatus } })];
    await render();
    expect(button("已结束 1").getAttribute("aria-selected")).toBe("true");
    expect(button("待处理 0")).toBeTruthy();
    const card = container.querySelector('article[data-task-state="unknown"]')!;
    expect(card.closest('[data-task-group="ended"]')).toBeTruthy();
    expect(button("移除记录“核对周报”", card).querySelector("svg")).not.toBeNull();
    await click("移除记录“核对周报”", card);
    expect((operationCalls("executeTaskCleanup")[0][0] as unknown as { targets: unknown[] }).targets)
      .toEqual([{ kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-1", localOnly: true }]);
  });

  it("includes successful, failed, timed-out and stopped endings and every team alias in bulk cleanup", async () => {
    terminal(); status.teamRunsVersion = 1;
    for (const nativeStatus of ["failed", "timed_out", "cancelled"]) rows.push(row({ dispatchId: nativeStatus, receipt: { taskId: "native-1", status: nativeStatus } }));
    rows.push(row({ dispatchId: "active" }), row({ dispatchId: "unknown", receipt: null }));
    const teamRows = [teamRun(), teamRun({ requestId: "request-2", originAction: "flow_start" }),
      teamRun({ requestId: "failed-run", runId: "failed-run", status: "failed" }), teamRun({ requestId: "stopped-run", runId: "stopped-run", status: "stopped" }),
      teamRun({ requestId: "running", runId: "running", status: "running" })];
    teamReply = async () => teamPage(teamRows);
    await render();
    expect(button("已结束 7")).toBeTruthy();
    await click("清理已结束");
    const targets = operationCalls("previewTaskCleanup").flatMap(([request]) => (request as unknown as { targets: LauncherTaskCleanupTarget[] }).targets);
    expect(targets).toHaveLength(9);
    expect(targets.filter(target => target.kind === "dispatch").map(target => target.dispatchId).sort()).toEqual(["cancelled", "dispatch-1", "failed", "timed_out", "unknown"]);
    expect(targets.filter(target => target.kind === "team_run").map(target => target.requestId).sort()).toEqual(["failed-run", "request-1", "request-2", "stopped-run"]);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(5);
  });

  it("collects all cursor pages beyond the visible ten cards and processes more than 32 references", async () => {
    rows = []; status.teamRunsVersion = 1;
    const runs = Array.from({ length: 41 }, (_, index) => teamRun({ requestId: `request-${index}`, runId: `run-${index}` }));
    const cursors = [16, 32].map(offset => btoa(JSON.stringify({ snapshot: "a".repeat(64), offset })).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_"));
    teamReply = async cursor => {
      const offset = cursor === cursors[1] ? 32 : cursor === cursors[0] ? 16 : 0;
      return teamPage(runs.slice(offset, offset + 16), { offset, total: 41, nextCursor: offset === 0 ? cursors[0] : offset === 16 ? cursors[1] : null });
    };
    await render();
    expect(container.querySelectorAll("article")).toHaveLength(10);
    await click("清理已结束");
    const targets = operationCalls("executeTaskCleanup").flatMap(([request]) => (request as unknown as { targets: LauncherTaskCleanupTarget[] }).targets);
    expect(targets).toHaveLength(41);
    expect(new Set(targets.map(cleanupKey)).size).toBe(41);
    expect(invoke).toHaveBeenCalledWith({ operation: "teamRuns", cursor: cursors[0] });
    expect(invoke).toHaveBeenCalledWith({ operation: "teamRuns", cursor: cursors[1] });
    expect(document.body.textContent).toContain("任务清理结果");
  });

  it("reads fresh dispatch receipts before deciding which tasks to clean", async () => {
    terminal(); rows.push(row({ dispatchId: "newly-ended", title: "刚结束的任务" }));
    await render();
    rows = rows.map(value => value.dispatchId === "newly-ended"
      ? { ...value, receipt: { taskId: "native-1", status: "failed" } } : value);
    await click("清理已结束");
    const targets = operationCalls("previewTaskCleanup").flatMap(([request]) => (request as unknown as { targets: LauncherTaskCleanupTarget[] }).targets);
    expect(targets).toHaveLength(2);
    expect(targets).toContainEqual({ kind: "dispatch", projectId: "project-1", dispatchId: "newly-ended" });
  });

  it("sends identifiable unknown rows from a partial team snapshot for authoritative bulk verification", async () => {
    rows = []; status.teamRunsVersion = 1;
    teamReply = async () => teamPage([teamRun({ teamId: null, flowId: null, runId: null, status: null, observedAt: null, readState: "unknown" })], { state: "partial" });
    previewReply = async request => ({ schemaVersion: 1, fingerprint: "blocked", estimatedBytes: 0,
      items: (request.targets as LauncherTaskCleanupTarget[]).map(target => ({ key: cleanupKey(target), title: "团队周报",
        status: "blocked", estimatedBytes: 0, resources: [], retained: [], reason: "团队运行仍在执行" })) });
    await render();
    expect(button("待处理 1")).toBeTruthy();
    expect(button("已结束 0")).toBeTruthy();
    expect(button("清理已结束").disabled).toBe(false);
    await click("清理已结束");
    expect((operationCalls("previewTaskCleanup")[0][0] as unknown as { targets: unknown[] }).targets)
      .toEqual([{ kind: "team_run", projectId: "project-1", requestId: "request-1", originAction: "team_run", localOnly: true }]);
    expect(document.body.textContent).toContain("团队运行仍在执行");
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
  });

  it.each(["queued", "running", "cancelling", "awaiting_approval"])("does not offer cleanup for a known %s dispatch", async nativeStatus => {
    rows = [row({ receipt: { taskId: "native-1", status: nativeStatus } })];
    await render();
    expect(button("已结束 0")).toBeTruthy();
    expect(container.querySelector("article")?.querySelectorAll("button")).toHaveLength(1);
    expect(button("清理已结束").disabled).toBe(true);
    onlyReads();
  });

  it("enables bulk cleanup when ended tasks only exist on a later page", async () => {
    rows = []; status.teamRunsVersion = 1;
    const cursor = btoa(JSON.stringify({ snapshot: "b".repeat(64), offset: 1 })).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
    teamReply = async value => value ? teamPage([teamRun({ status: "failed" })], { offset: 1, total: 2 })
      : teamPage([teamRun({ requestId: "active", runId: "active", status: "running" })], { total: 2, nextCursor: cursor });
    await render();
    expect(button("清理已结束").disabled).toBe(false);
    await click("清理已结束");
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
  });

  it("fails visibly on a repeated cursor without deleting a partial list", async () => {
    rows = []; status.teamRunsVersion = 1;
    const cursor = btoa(JSON.stringify({ snapshot: "c".repeat(64), offset: 1 })).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
    teamReply = async value => teamPage([teamRun()], { offset: value ? 1 : 0, total: 3, nextCursor: cursor });
    await render(); await click("清理已结束");
    expect(document.body.textContent).toContain("团队运行暂不可用");
    expect(operationCalls("previewTaskCleanup")).toHaveLength(0);
    expect(button("重试未核验来源与剩余项").disabled).toBe(false);
  });

  it.each(["identity", "hidden", "unmounted"] as const)("stops cleanup collection if the view becomes %s", async change => {
    rows = []; status.teamRunsVersion = 1;
    const cursor = btoa(JSON.stringify({ snapshot: "d".repeat(64), offset: 1 })).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
    teamReply = async () => teamPage([teamRun()], { total: 2, nextCursor: cursor });
    await render();
    let resolvePage!: (value: LauncherAssistantTeamRunsPage) => void;
    teamReply = () => new Promise(resolve => { resolvePage = resolve; });
    await click("清理已结束");
    if (change === "identity") {
      status = { teamRunsVersion: 1, assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
      teamReply = async () => teamPage([]);
      await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); }); await settle();
    } else if (change === "hidden") {
      visibility = "hidden"; await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    } else await act(async () => { root!.unmount(); root = null; });
    const reads = teamReads();
    await act(async () => { resolvePage(teamPage([teamRun()], { total: 2, nextCursor: cursor })); }); await settle();
    expect(teamReads()).toBe(reads);
    expect(operationCalls("previewTaskCleanup")).toHaveLength(0);
  });

  it.each(["identity", "hidden", "status_error"] as const)("stops before execution when %s changes during host verification", async change => {
    terminal();
    let resolvePreview!: (value: LauncherTaskCleanupPreview) => void;
    const originalPreview = previewReply;
    const response = await originalPreview({ targets: [{ kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-1" }] });
    previewReply = () => new Promise(resolve => { resolvePreview = resolve; });
    await render(); await click("清理“核对周报”");
    if (change === "identity") {
      status = { assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
      await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); });
    } else if (change === "hidden") {
      visibility = "hidden"; await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    } else {
      invoke.mockImplementation(async () => { throw new Error("identity offline"); });
      await act(async () => { await client.refetchQueries({ queryKey: ["launcher-assistant", "status"], exact: true }); });
    }
    await settle();
    await act(async () => { resolvePreview(response); }); await settle();
    expect(operationCalls("executeTaskCleanup")).toHaveLength(0);
    expect(document.body.querySelector('[data-vui="launcher-task-cleanup"]')).toBeNull();
  });

  it("stops later execution batches after identity change", async () => {
    rows = Array.from({ length: 33 }, (_, index) => row({ dispatchId: `dispatch-${index}`, receipt: { taskId: "native-1", status: "succeeded" } }));
    let resolveExecute!: (value: LauncherTaskCleanupResult) => void;
    let firstTargets: LauncherTaskCleanupTarget[] = [];
    executeReply = request => { firstTargets = request.targets as LauncherTaskCleanupTarget[]; return new Promise(resolve => { resolveExecute = resolve; }); };
    await render(); await click("清理已结束");
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    status = { assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
    await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); }); await settle();
    await act(async () => { resolveExecute({ schemaVersion: 1, releasedBytes: 4, items: firstTargets.map(target => ({
      key: cleanupKey(target), status: "deleted", releasedBytes: 1, retained: [], failures: [],
    })) }); }); await settle();
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    expect(document.body.textContent).not.toContain("任务清理结果");
  });

  it("shares one synchronous lock between single and bulk clicks", async () => {
    terminal();
    let resolveExecute!: (value: LauncherTaskCleanupResult) => void;
    executeReply = () => new Promise(resolve => { resolveExecute = resolve; });
    await render();
    const single = button("清理“核对周报”"), bulk = button("清理已结束");
    await act(async () => { single.click(); bulk.click(); single.click(); }); await settle();
    expect(operationCalls("previewTaskCleanup")).toHaveLength(1);
    expect(operationCalls("executeTaskCleanup")).toHaveLength(1);
    expect(button("清理“核对周报”").disabled).toBe(true);
    expect(button("清理已结束").disabled).toBe(true);
    await act(async () => { resolveExecute({ schemaVersion: 1, releasedBytes: 0,
      items: [{ key: dispatchCleanupKey, status: "deleted", releasedBytes: 0, retained: [], failures: [] }] }); }); await settle();
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
async function render(lang: "zh" | "en" = "zh", children?: React.ReactNode) {
  await act(async () => { root!.render(<QueryClientProvider client={client}>
    <LauncherAssistantTaskCards onReview={onReview} onApproval={onApproval} lang={lang}>
      <LauncherTaskModelControls lang={lang} />
      {children ?? <LauncherAssistantTaskSidebar lang={lang} />}
    </LauncherAssistantTaskCards>
  </QueryClientProvider>); });
  await settle();
}
function button(label: string, within: ParentNode = document.body): HTMLButtonElement {
  const result = [...within.querySelectorAll<HTMLButtonElement>("button")].find(element => element.getAttribute("aria-label") === label || element.textContent === label);
  if (!result) throw new Error(`Missing button: ${label}`);
  return result;
}
async function click(label: string, within: ParentNode = document.body) {
  await act(async () => {
    const target = button(label, within);
    // Radix tab selection follows the pointer press, as in VTabs' own tests.
    if (target.getAttribute("role") === "tab") target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    target.click();
  }); await settle();
}
function taskDialog(): HTMLElement {
  const dialog = document.body.querySelector<HTMLElement>('[data-vui="launcher-task-detail"]');
  if (!dialog) throw new Error("Missing task detail dialog");
  return dialog;
}
async function openTask(card: Element = container.querySelector("article")!): Promise<HTMLElement> {
  const trigger = card?.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]');
  if (!trigger) throw new Error("Missing task card dialog trigger");
  await act(async () => { trigger.click(); }); await settle();
  return taskDialog();
}
async function cleanupFromDetail(card?: Element) {
  const dialog = await openTask(card);
  await click("清理", dialog);
}
function dispatchReads() { return invoke.mock.calls.filter(([request]) => request.operation === "dispatches").length; }
function teamReads() { return invoke.mock.calls.filter(([request]) => request.operation === "teamRuns").length; }
function onlyReads() { expect(invoke.mock.calls.every(([request]) => ["status", "dispatches", "teamRuns"].includes(request.operation))).toBe(true); }

describe("Launcher assistant task cards", () => {
  it.each(["identity", "hidden"] as const)("invalidates the selected task dialog when %s changes", async change => {
    rows = [row({ title: "旧身份的任务" })];
    await render();
    await openTask();
    if (change === "identity") {
      status = { assistant: { agentId: "assistant-2", directSessionId: "session-2", displayName: "新助理" } };
      // The same native references may exist under both assistant identities.
      rows = [row({ title: "当前身份的任务" })];
      await act(async () => { client.setQueryData(["launcher-assistant", "status"], status); });
    } else {
      visibility = "hidden";
      await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    }
    await settle();
    expect(document.body.querySelector('[data-vui="launcher-task-detail"]')).toBeNull();
    expect(document.body.textContent).not.toContain("旧身份的任务");
    expect(onReview).not.toHaveBeenCalled();
    expect(onApproval).not.toHaveBeenCalled();
    if (change === "identity") {
      expect((await openTask()).textContent).toContain("当前身份的任务");
      await click("去对话核对");
      expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project-1", dispatchId: "dispatch-1" }));
    }
    onlyReads();
  });

  it("closes task details without remounting the conversation or discarding its draft", async () => {
    const mounted = vi.fn(), unmounted = vi.fn();
    function Conversation() {
      React.useEffect(() => { mounted(); return () => { unmounted(); }; }, []);
      return <textarea aria-label="聊天草稿" defaultValue="未发送的草稿" />;
    }
    await render("zh", <><LauncherAssistantTaskSidebar /><Conversation /></>);
    const draft = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="聊天草稿"]')!;
    draft.value = "继续编辑的草稿";
    const trigger = container.querySelector<HTMLButtonElement>('article button[aria-haspopup="dialog"]')!;
    const dialog = await openTask();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(dialog.parentElement).toBeTruthy();
    expect(container.contains(dialog)).toBe(false);
    await click("关闭", dialog);
    expect(document.body.querySelector('[data-vui="launcher-task-detail"]')).toBeNull();
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(container.querySelector('textarea[aria-label="聊天草稿"]')).toBe(draft);
    expect(draft.value).toBe("继续编辑的草稿");
    expect(mounted).toHaveBeenCalledTimes(1);
    expect(unmounted).not.toHaveBeenCalled();
    expect(onReview).not.toHaveBeenCalled();
    expect(onApproval).not.toHaveBeenCalled();
    onlyReads();
  });

  it("localizes the card, fallback title, details, and navigation when Launcher uses English", async () => {
    rows = [row({ title: undefined, receipt: { taskId: "native-1", status: "succeeded", shouldPoll: false } })];
    await render("en");
    expect(container.querySelector('section[aria-label="Assistant tasks"]')).toBeTruthy();
    expect(container.querySelector("article")?.getAttribute("aria-label")).toBe("Delegated task");
    expect(container.textContent).toContain("Ended");
    const dialog = await openTask();
    expect(dialog.textContent).toContain("Execution result");
    expect(dialog.textContent).toContain("No result summary yet.");
    expect(dialog.textContent).toContain("The actual result still needs verification.");
    await click("References", dialog);
    expect(dialog.textContent).toContain("Project ID: project-1");
    expect(document.body.textContent).not.toMatch(/[\u4e00-\u9fff]/);
    await click("Review in chat");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ state: "awaiting_verification" }));
    onlyReads();
  });

  it("renders receipt summaries as text in the dialog and only reveals technical identifiers on request", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "succeeded", resultSummary: '<img src=x onerror="alert(1)"> 周报待核对' } })];
    await render();
    expect(container.querySelector("article")?.textContent).toContain("已结束");
    expect(container.textContent).not.toContain("dispatch-1");
    expect(container.textContent).not.toContain("周报待核对");
    expect(container.querySelector('button[aria-expanded="false"]')).toBeTruthy();
    const dialog = await openTask();
    expect(dialog.textContent).not.toContain("dispatch-1");
    expect(dialog.textContent).toContain("周报待核对");
    expect(document.body.querySelector("img")).toBeNull();
    await click("引用信息", dialog);
    expect(dialog.textContent).toContain("dispatch-1");
    expect(container.querySelector('button[aria-expanded="true"]')).toBeTruthy();
    await click("收起引用信息", dialog);
    expect(dialog.textContent).not.toContain("native-1");
    await click("关闭", dialog);
    expect(document.body.textContent).not.toContain("周报待核对");
  });

  it("only navigates to the existing approval flow and never decides an approval", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "awaiting_approval", shouldPoll: false, pendingApprovals: [{
      approvalId: "approval-1", toolName: "write", risk: "write", targetSummary: {}, revision: "r1", availableDecisions: ["accept", "decline"],
    }] } })];
    await render();
    const dialog = await openTask();
    expect(dialog.textContent).not.toContain("同意");
    expect(dialog.textContent).not.toContain("拒绝");
    await click("处理授权");
    expect(onApproval).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project-1", dispatchId: "dispatch-1", state: "waiting_user" }),
      expect.objectContaining({ assistantAgentId: "assistant-1", sessionId: "session-1", projectId: "project-1",
        dispatchId: "dispatch-1", nativeTaskId: "native-1", agentId: "worker-1", approvalId: "approval-1", nonce: expect.any(String) }));
    expect(onReview).not.toHaveBeenCalled();
    onlyReads();
  });

  it("offers failure review without retry, restart, dispatch, or other mutations", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "failed", shouldPoll: false } })];
    await render();
    const dialog = await openTask();
    expect([...dialog.querySelectorAll("button")].map(element => element.textContent)).not.toEqual(expect.arrayContaining(["重试任务", "重新派遣", "重启"]));
    await click("去对话核对");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ state: "failed", businessAcceptance: "not_evaluated" }));
    expect(onApproval).not.toHaveBeenCalled();
    onlyReads();
  });

  it("presents native success as awaiting verification and reviews the exact project and dispatch", async () => {
    rows = [row({ receipt: { taskId: "native-1", status: "succeeded", resultSummary: "所有目标已完成", shouldPoll: false } })];
    await render();
    expect(container.querySelector('[data-task-state="awaiting_verification"]')).toBeTruthy();
    expect(container.querySelector("article")?.textContent).toContain("已结束");
    const dialog = await openTask();
    expect(dialog.textContent).toContain("仍需核对实际结果");
    expect(dialog.textContent).toContain("所有目标已完成");
    await click("去对话核对");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project-1", dispatchId: "dispatch-1", state: "awaiting_verification" }));
    onlyReads();
  });

  it("distinguishes a first read failure from an available empty feed and probes the error with bounded backoff", async () => {
    dispatchReply = async () => { throw new Error("offline"); };
    await render();
    expect(container.textContent).toContain("任务状态暂不可用");
    expect(container.textContent).not.toContain("暂无此类任务");
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); }); await settle();
    expect(dispatchReads()).toBe(4); // probes due at +3s, +9s, +21s after the first failure
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); }); await settle();
    expect(dispatchReads()).toBe(6); // probes at +33s and +45s exhaust the five-attempt budget
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(dispatchReads()).toBe(6); // no retry storm past the cap
    rows = []; dispatchReply = async () => rows;
    await click("刷新");
    expect(container.textContent).toContain("暂无此类任务");
    expect(dispatchReads()).toBe(7);
  });

  it("retains old cards as unknown after a poll fails and probes the error with bounded backoff", async () => {
    await render();
    expect(container.textContent).toContain("执行中");
    dispatchReply = async () => { throw new Error("disconnected"); };
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(dispatchReads()).toBe(2);
    expect(client.getQueryState(["launcher-assistant", "task-cards", "assistant-1", "session-1"])).toMatchObject({ status: "error" });
    await click("待处理 1");
    expect(container.textContent).toContain("核对周报");
    expect(container.querySelector('[data-task-state="unknown"]')).toBeTruthy();
    const dialog = await openTask();
    expect(dialog.textContent).toContain("保留上次记录");
    await click("关闭", dialog);
    expect(container.textContent).not.toContain("暂无此类任务");
    const reads = dispatchReads();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); }); await settle();
    expect(dispatchReads()).toBe(reads + 3); // probes due at +3s, +9s, +21s after the failed poll
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(dispatchReads()).toBe(reads + 5); // probes at +33s and +45s finish the five-attempt budget
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(dispatchReads()).toBe(reads + 5); // capped: waiting for manual refresh instead of a retry storm
  });

  it("pauses bounded error probing while the view is hidden and recovers through the re-enable read", async () => {
    dispatchReply = async () => { throw new Error("offline"); };
    await render();
    expect(dispatchReads()).toBe(1);
    visibility = "hidden";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(dispatchReads()).toBe(1); // hidden: no probe fires, however long the page is away
    visibility = "visible";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await settle();
    expect(dispatchReads()).toBe(2); // visible again: the stale error read reruns once on re-enable
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(dispatchReads()).toBe(2); // the probe budget was spent by elapsed time: no retry storm
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
    // Recovery still follows only the probe cadence, never the status refreshes.
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); }); await settle();
    expect(dispatchReads()).toBe(3); // probes due at +3s and +9s after the first failure
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
    const dialog = await openTask(second);
    expect(dialog.textContent).toContain("乙的摘要");
    expect(dialog.textContent).not.toContain("甲的摘要");
    await click("去对话核对", dialog);
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project-2", dispatchId: "dispatch-1" }));
  });

  it("shows ten cards initially and reveals more without claiming complete platform coverage", async () => {
    rows = Array.from({ length: 12 }, (_, index) => row({ dispatchId: `dispatch-${index}`, title: `任务 ${index}`,
      receipt: { taskId: "native-1", status: "succeeded", shouldPoll: false } }));
    await render();
    expect(container.querySelectorAll("article")).toHaveLength(10);
    expect(button("已结束 12").getAttribute("aria-selected")).toBe("true");
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
    expect(container.querySelector('[role="status"][aria-label="正在读取任务"]')).toBeTruthy();
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
    await click("已结束 1");
    const card = container.querySelector('article[data-task-kind="team_run"]')!;
    expect(card.getAttribute("data-task-state")).toBe("awaiting_verification");
    expect(card.textContent).toContain("已结束");
    expect(card.textContent).not.toContain("run-1");
    const dialog = await openTask(card);
    expect(dialog.textContent).toContain("来源尚未提供当前负责的 Agent");
    expect(dialog.textContent).toContain("仍需核对实际结果");
    await click("引用信息", dialog);
    expect(dialog.textContent).toContain("团队编号：team-1");
    expect(dialog.textContent).toContain("流程编号：flow-1");
    expect(dialog.textContent).toContain("运行编号：run-1");
    await click("去对话核对", dialog);
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
    expect(container.querySelector("article")?.getAttribute("aria-label")).toBe("Team run record");
    expect(container.textContent).toContain("Waiting for input");
    expect(container.textContent).not.toContain("authorization");
    expect(container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
    await openTask();
    await click("Review in chat");
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ kind: "team_run", state: "waiting_input" }));
    expect(onApproval).not.toHaveBeenCalled();
    onlyReads();
  });

  it("keeps dispatch cards current when the independent team source fails and probes it only on the bounded error cadence", async () => {
    status.teamRunsVersion = 1;
    teamReply = async () => { throw new Error("team offline"); };
    await render();
    expect(container.textContent).toContain("团队运行状态暂不可用");
    expect(container.querySelector('article[data-task-kind="dispatch"]')?.getAttribute("data-task-state")).toBe("running");
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(teamReads()).toBe(2); // the dispatch cadence plus the first bounded probe of the failed team source
    expect(dispatchReads()).toBe(2);
    teamReply = async () => teamPage([teamRun()]);
    await click("刷新");
    expect(teamReads()).toBe(3);
    await click("已结束 1");
    expect(container.querySelector('article[data-task-kind="team_run"]')?.getAttribute("data-task-state")).toBe("awaiting_verification");
  });

  it("retains team cards as unknown after a failed active poll while leaving dispatch receipts intact", async () => {
    status.teamRunsVersion = 1;
    teamReply = async () => teamPage([teamRun({ status: "running" })]);
    await render();
    teamReply = async () => { throw new Error("team offline"); };
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(teamReads()).toBe(2);
    await click("待处理 1");
    expect(container.querySelector('article[data-task-kind="team_run"]')?.getAttribute("data-task-state")).toBe("unknown");
    const dialog = await openTask(container.querySelector('article[data-task-kind="team_run"]')!);
    await click("去对话核对", dialog);
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ runId: null, teamId: null, flowId: null,
      nativeStatus: null, revision: null, observedAt: null, receiptBound: false, lastKnown: expect.objectContaining({ runId: "run-1" }) }));
    await click("进行中 1");
    expect(container.querySelector('article[data-task-kind="dispatch"]')?.getAttribute("data-task-state")).toBe("running");
    const reads = teamReads();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(teamReads()).toBe(reads + 5); // five bounded probes after the failed active poll
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); }); await settle();
    expect(teamReads()).toBe(reads + 5); // capped: no retry storm past the budget
  });

  it("keeps partial unknown observations manual and suspends known active team reads when hidden", async () => {
    status.teamRunsVersion = 1;
    rows = [];
    teamReply = async () => teamPage([teamRun({ status: null, observedAt: null, readState: "unknown" })], { state: "partial" });
    await render();
    expect(container.textContent).toContain("部分团队关联或状态暂无法核验");
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
    expect(container.textContent).not.toContain("全部任务");
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
    expect(container.textContent).toContain("部分团队关联或状态暂无法核验");
    expect(container.textContent).not.toContain("暂无此类任务");
  });

  it("retains both confirmed-identity sources as unknown if shared identity refresh fails", async () => {
    status.teamRunsVersion = 1;
    teamReply = async () => teamPage([teamRun({ status: "running" })]);
    await render();
    const dialog = await openTask();
    invoke.mockImplementation(async (request: { operation: string }) => {
      if (request.operation === "status") throw new Error("identity offline");
      if (request.operation === "dispatches") return { dispatches: rows };
      if (request.operation === "teamRuns") return teamReply();
      throw new Error(`Unexpected mutation: ${request.operation}`);
    });
    await act(async () => { await client.refetchQueries({ queryKey: ["launcher-assistant", "status"], exact: true }); });
    await settle();
    await click("待处理 2");
    expect(container.querySelectorAll('article[data-task-state="unknown"]')).toHaveLength(2);
    expect(container.textContent).toContain("团队周报");
    const dispatchCount = dispatchReads(), teamCount = teamReads();
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(dispatchReads()).toBe(dispatchCount);
    expect(teamReads()).toBe(teamCount);
    expect(button("去对话核对", dialog).disabled).toBe(true);
    await click("关闭", dialog);
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
    await click("进行中 2");
    expect(container.querySelectorAll('article[data-task-state="running"]')).toHaveLength(2);
  });

  it("keeps last-verified display facts across a successful unknown read, updates on recovery and drops deleted requests", async () => {
    status.teamRunsVersion = 1;
    rows = [];
    teamReply = async () => teamPage([teamRun({ status: "running" })]);
    await render();
    const original = container.querySelector('article[data-task-kind="team_run"]')!;
    let dialog = await openTask(original);
    await click("引用信息", dialog);
    const unknown = teamRun({ teamId: null, flowId: null, runId: null, status: null, revision: null,
      title: "", observedAt: null, readState: "unknown" });
    teamReply = async () => teamPage([unknown], { state: "partial" });
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); }); await settle();
    expect(container.querySelector('article[data-task-kind="team_run"]')).toBeNull();
    // The selected receipt stays in the dialog while its card moves categories.
    dialog = taskDialog();
    expect(dialog.textContent).toContain("以下为上次核验的信息");
    expect(dialog.textContent).toContain("运行编号：run-1");
    expect(dialog.textContent).toContain("版本：r1");
    expect(dialog.textContent).toContain("2026-11-02T01:00:00Z");
    await click("去对话核对", dialog);
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ teamId: null, flowId: null, runId: null,
      nativeStatus: null, revision: null, observedAt: null, receiptBound: false, shouldPoll: false,
      lastKnown: expect.objectContaining({ runId: "run-1" }) }));
    await click("待处理 1");
    let card = container.querySelector('article[data-task-kind="team_run"]')!;
    expect(card.getAttribute("data-task-state")).toBe("unknown");
    expect(card.textContent).toContain("团队周报");
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(teamReads()).toBe(2);
    await click("刷新");
    expect(card.textContent).toContain("团队周报");
    teamReply = async () => teamPage([teamRun({ title: "更新后的周报", status: "completed", revision: "r2", observedAt: "2026-11-02T02:00:00Z" })]);
    await click("刷新");
    await click("已结束 1");
    card = container.querySelector('article[data-task-kind="team_run"]')!;
    dialog = await openTask(card);
    await click("引用信息", dialog);
    expect(card.getAttribute("data-task-state")).toBe("awaiting_verification");
    expect(card.textContent).toContain("更新后的周报");
    expect(dialog.textContent).toContain("版本：r2");
    expect(dialog.textContent).not.toContain("上次核验的信息");
    teamReply = async () => teamPage([]);
    await click("刷新");
    expect(container.querySelector("article")).toBeNull();
    expect(document.body.querySelector('[data-vui="launcher-task-detail"]')).toBeNull();
    teamReply = async () => teamPage([unknown], { state: "partial" });
    await click("刷新");
    expect(container.textContent).not.toContain("更新后的周报");
    await click("待处理 1");
    dialog = await openTask();
    await click("引用信息", dialog);
    expect(dialog.textContent).not.toContain("上次核验的信息");
    expect(dialog.textContent).not.toContain("run-1");
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
    const dialog = await openTask();
    await click("引用信息", dialog);
    expect(dialog.textContent).not.toContain("上次核验的信息");
    expect(dialog.textContent).not.toContain("run-1");
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
    await click("待处理 1");
    expect(container.querySelectorAll("article")).toHaveLength(1);
    await openTask();
    await click("去对话核对");
    expect(onReview.mock.lastCall?.[0].sourceRefs).toHaveLength(2);
    teamReply = async () => teamPage([teamRun({ ...unknown, ...alias })], { state: "partial" });
    await click("刷新");
    expect(container.querySelectorAll("article")).toHaveLength(1);
    await openTask();
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
