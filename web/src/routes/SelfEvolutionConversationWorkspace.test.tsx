import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { SelfEvolutionAutonomousLoopRun, SelfObservationRun, SupervisedWorktreeRun } from "../api/types";
import {
  buildSelfEvolutionConversationPhases,
  canConfirmAutonomousAction,
  canConfirmObservationAction,
  canConfirmWorktreeAction,
  SelfEvolutionConversationWorkspace,
} from "./SelfEvolutionConversationWorkspace";

function autonomousRun(overrides: Partial<SelfEvolutionAutonomousLoopRun> = {}): SelfEvolutionAutonomousLoopRun {
  return {
    schemaVersion: 1,
    runKind: "self_evolution_autonomous_loop",
    runId: "self-loop-1",
    status: "running",
    phase: "observing",
    request: { goal: "整理运行历史", maxIterations: 1 },
    observation: { summary: "观察摘要", evidence: [], conversationSessionId: "session-observe" },
    plan: { summary: "计划摘要", steps: [], conversationSessionId: "session-plan" },
    candidate: {
      summary: "候选摘要",
      changedFiles: [],
      verification: [],
      baseCommit: "base-123",
      headCommit: "head-456",
      worktreePath: "C:/tmp/candidate",
      branchName: "codex/self-loop",
      conversationSessionId: "session-evolve",
    },
    reviewGate: { status: "pending", requiredActorType: "user" },
    createdAt: "2026-09-29T00:00:00Z",
    startedAt: "2026-09-29T00:00:00Z",
    updatedAt: "2026-09-29T00:01:00Z",
    ...overrides,
  };
}

function observationRun(): SelfObservationRun {
  return {
    runId: "observation-1",
    runKind: "self_observation_run",
    selfMode: "observation",
    status: "running",
    phase: "observing",
    runtimeStatus: "running",
    goal: "只读观察目标",
    durationSeconds: 300,
    allowedTools: [],
    writeLeases: [],
    worktreeCreated: false,
    conversationSessionId: "session-observation",
    startedAt: "2026-09-29T00:00:00Z",
    updatedAt: "2026-09-29T00:01:00Z",
    finishedAt: "",
    latestMessage: "观察正在运行",
    report: "",
    boundaryViolation: "",
    actionStates: { terminate: { enabled: true, reason: "" } },
  };
}

function worktreeRun(overrides: Partial<SupervisedWorktreeRun> = {}): SupervisedWorktreeRun {
  return {
    runId: "worktree-1", runKind: "self_evolution", status: "completed", phase: "review",
    runtimeStatus: "idle", outcome: "", mode: "", executionMode: "", sourceKind: "",
    datasetName: "", datasetLimit: null, bundleName: "", keepWorktree: true,
    startedAt: "", updatedAt: "", finishedAt: "", latestMessage: "",
    costEstimate: { caseCount: 0, evaluationCalls: 0, selfEditCalls: 0, modelCalls: 0,
      estimatedInputTokens: 0, estimatedOutputTokens: 0, estimatedTotalTokens: 0, note: "" },
    decision: {}, mergeAnalysis: {}, actionStates: {},
    ...overrides,
  };
}

function renderMarkup(overrides: Partial<Parameters<typeof SelfEvolutionConversationWorkspace>[0]> = {}) {
  const props: Parameters<typeof SelfEvolutionConversationWorkspace>[0] = {
    lang: "zh",
    workspaceNavigation: { activeTrack: "self" },
    selectedRunKind: null,
    goalInput: "",
    onGoalInputChange: vi.fn(),
    onStartRun: vi.fn(),
    onAutonomousAction: vi.fn(),
    onStartObservation: vi.fn(),
    onTerminateObservation: vi.fn(),
    onWorktreeAction: vi.fn(),
    onPhaseSelect: vi.fn(),
    onHistory: vi.fn(),
    onSettings: vi.fn(),
    onLibrary: vi.fn(),
    startPending: false,
    observationStartPending: false,
    observationActionPending: false,
    worktreeActionPending: false,
    autonomousActionPending: false,
    startWorktreeError: "",
    observationStartError: "",
    observationActionError: "",
    worktreeActionError: "",
    autonomousActionError: "",
    actionFeedback: "",
    runLocked: false,
    worktreeRunLocked: false,
    loading: false,
    ...overrides,
  };
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><SelfEvolutionConversationWorkspace {...props} /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SelfEvolutionConversationWorkspace", () => {
  it("maps autonomous phases only to their canonical session IDs", () => {
    const run = autonomousRun({
      phase: "reporting",
      resultReport: { summary: "等待人工审查", changedFiles: [], verification: [], candidateHead: "head-456" },
    });
    const phases = buildSelfEvolutionConversationPhases("autonomous", run, "zh");

    expect(phases.filter((phase) => phase.sessionId).map((phase) => [phase.id, phase.sessionId])).toEqual([
      ["observing", "session-observe"],
      ["planning", "session-plan"],
      ["evolving", "session-evolve"],
    ]);
    expect(phases.find((phase) => phase.id === "reporting")).toMatchObject({
      current: true,
      disabled: true,
      sessionId: "",
      summary: "等待人工审查",
    });
  });

  it("shows stage summaries as context when no canonical conversation exists", () => {
    const markup = renderMarkup({
      selectedRunKind: "autonomous",
      autonomousRun: autonomousRun({
        observation: { summary: "仅阶段摘要", evidence: [] },
        plan: undefined,
        candidate: undefined,
      }),
    });

    expect(markup).toContain("此阶段没有 Agent 对话会话");
    expect(markup).toContain("仅阶段摘要");
    expect(markup).not.toContain("原生 Agent 会话暂时无法读取");
    expect(markup).not.toContain("session-observe");
  });

  it("keeps observation controls tied to the selected observation run", () => {
    const autonomous = autonomousRun({ status: "awaiting_user_approval", phase: "reporting" });
    const markup = renderMarkup({
      selectedRunKind: "observation",
      observationRun: observationRun(),
      autonomousRun: autonomous,
    });

    expect(markup).toContain("终止观察");
    expect(markup).not.toContain("批准并集成");
    expect(markup).not.toContain("拒绝候选");
  });

  it("exposes review actions only for the selected autonomous candidate", () => {
    const markup = renderMarkup({
      selectedRunKind: "autonomous",
      autonomousRun: autonomousRun({ status: "awaiting_user_approval", phase: "reporting" }),
    });

    expect(markup).toContain("批准并集成");
    expect(markup).toContain("拒绝候选");
    expect(markup).toContain("迭代预算");
  });

  it("refuses a confirmation if the selected run or its review state changed", () => {
    const awaiting = autonomousRun({ status: "awaiting_user_approval", phase: "reporting" });
    expect(canConfirmAutonomousAction({ action: "approve", requestedRunId: awaiting.runId, selectedRun: awaiting, pending: false })).toBe(true);
    expect(canConfirmAutonomousAction({ action: "approve", requestedRunId: awaiting.runId, selectedRun: autonomousRun({ ...awaiting, runId: "other-run" }), pending: false })).toBe(false);
    expect(canConfirmAutonomousAction({ action: "approve", requestedRunId: awaiting.runId, selectedRun: autonomousRun({ ...awaiting, status: "completed", phase: "completed" }), pending: false })).toBe(false);
    expect(canConfirmAutonomousAction({ action: "approve", requestedRunId: awaiting.runId, selectedRun: awaiting, pending: true })).toBe(false);
  });

  it("distinguishes failure from cancellation and displays only the returned failure reason", () => {
    const failed = autonomousRun({ status: "failed", phase: "evolving", error: { type: "verification", message: "pytest exited with code 1" } });
    const markup = renderMarkup({ selectedRunKind: "autonomous", autonomousRun: failed });
    expect(markup).toContain("运行失败");
    expect(markup).toContain("本轮未能完成");
    expect(markup).toContain("pytest exited with code 1");
    expect(markup).toContain("当前没有可执行操作");
    expect(markup).not.toContain("已中断");
    expect(markup).not.toContain("重试 Git 集成");
    expect(markup).not.toContain("终止运行");
    expect(buildSelfEvolutionConversationPhases("autonomous", failed, "zh").find((phase) => phase.current)?.statusLabel).toBe("失败");

    const cancelled = renderMarkup({ selectedRunKind: "observation", observationRun: { ...observationRun(), status: "cancelled" } });
    expect(cancelled).toContain("本轮已取消");
    expect(cancelled).not.toContain("运行失败");
    expect(cancelled).not.toContain("终止观察");
  });

  it("states when a failure reason is missing instead of inventing an environment error", () => {
    const markup = renderMarkup({ selectedRunKind: "autonomous", autonomousRun: autonomousRun({ status: "failed", phase: "planning", error: undefined }) });
    expect(markup).toContain("服务端没有返回失败原因");
    expect(markup).not.toContain("缺少依赖");
  });

  it("keeps integration and cleanup retries specific to their existing autonomous phases", () => {
    const integration = autonomousRun({ status: "failed", phase: "integration_failed" });
    expect(renderMarkup({ selectedRunKind: "autonomous", autonomousRun: integration })).toContain("重试 Git 集成");
    expect(canConfirmAutonomousAction({ action: "approve", requestedRunId: integration.runId, selectedRun: integration, pending: false })).toBe(true);
    expect(canConfirmAutonomousAction({ action: "reject", requestedRunId: integration.runId, selectedRun: integration, pending: false })).toBe(false);
    const cleanup = autonomousRun({ status: "completed", phase: "cleanup_failed", error: { type: "cleanup", message: "worktree is locked" } });
    const markup = renderMarkup({ selectedRunKind: "autonomous", autonomousRun: cleanup });
    expect(markup).toContain("候选清理未完成");
    expect(markup).toContain("重试候选清理");
    expect(markup).toContain("worktree is locked");
    expect(canConfirmAutonomousAction({ action: "retry_cleanup", requestedRunId: cleanup.runId, selectedRun: cleanup, pending: false })).toBe(true);
    expect(canConfirmAutonomousAction({ action: "retry_cleanup", requestedRunId: cleanup.runId, selectedRun: autonomousRun(), pending: false })).toBe(false);
  });

  it("shows observation action restrictions and rechecks the selected run on confirmation", () => {
    const run = observationRun();
    const unavailable = { ...run, actionStates: { terminate: { enabled: false, reason: "观察会话正在关闭" } } };
    const markup = renderMarkup({ selectedRunKind: "observation", observationRun: unavailable });
    expect(markup).toContain("观察会话正在关闭");
    expect(canConfirmObservationAction(run, run.runId, false)).toBe(true);
    expect(canConfirmObservationAction(unavailable, run.runId, false)).toBe(false);
    expect(canConfirmObservationAction({ ...run, runId: "other" }, run.runId, false)).toBe(false);
    expect(canConfirmObservationAction({ ...run, status: "completed" }, run.runId, false)).toBe(false);
    expect(canConfirmObservationAction(run, run.runId, true)).toBe(false);
  });

  it("preserves worktree review, integration, discard and termination permissions", () => {
    const run = worktreeRun({ actionStates: {
      merge: { enabled: true, reason: "" }, approveReview: { enabled: true, reason: "" },
      discard: { enabled: true, reason: "" }, terminate: { enabled: true, reason: "" },
    } });
    const markup = renderMarkup({ selectedRunKind: "worktree", worktreeRun: run });
    expect(markup.indexOf("集成候选")).toBeLessThan(markup.indexOf("通过审查"));
    for (const action of ["merge", "approve_review", "discard", "terminate"]) {
      const input = { run, requestedRunId: run.runId, action, pending: false, locked: false };
      expect(canConfirmWorktreeAction(input)).toBe(true);
      expect(canConfirmWorktreeAction({ ...input, requestedRunId: "other" })).toBe(false);
      expect(canConfirmWorktreeAction({ ...input, pending: true })).toBe(false);
      expect(canConfirmWorktreeAction({ ...input, run: { ...run, actionStates: {} } })).toBe(false);
      expect(canConfirmWorktreeAction({ ...input, locked: true })).toBe(action === "terminate");
    }
  });

  it("shows the returned report, changed paths and explicit verification records in the overview", () => {
    const markup = renderMarkup({ selectedRunKind: "autonomous", autonomousRun: autonomousRun({
      resultReport: {
        summary: "已补充恢复分支的直接断言", candidateHead: "head-456",
        changedFiles: [{ path: "tests/test_recovery.py", changeType: "modified" }],
        verification: [{ name: "recovery regression", passed: false, exitCode: 1 }],
      },
    }) });
    expect(markup).toContain("本轮摘要");
    expect(markup).toContain("已补充恢复分支的直接断言");
    expect(markup).toContain("1 个文件");
    expect(markup).toContain("tests/test_recovery.py");
    expect(markup).toContain("通过：否");
    expect(markup).toContain("退出码：1");
    expect(markup).not.toContain("&quot;passed&quot;");
  });

  it("does not promote missing or inconclusive verification records to a pass", () => {
    const missing = renderMarkup({ selectedRunKind: "autonomous", autonomousRun: autonomousRun({ candidate: undefined }) });
    expect(missing).toContain("暂无可用摘要");
    expect(missing).toContain("暂无改动记录");
    expect(missing).toContain("暂无验证记录，尚不能判断是否通过");
    const inconclusive = renderMarkup({ selectedRunKind: "autonomous", autonomousRun: autonomousRun({
      resultReport: { summary: "候选已生成", candidateHead: "head-456", changedFiles: [], verification: [{ tool: "pytest", output: "collected 1 item" }] },
    }) });
    expect(inconclusive).toContain("1 条记录");
    expect(inconclusive).toContain("尚无明确验证结论");
    expect(inconclusive).not.toContain("通过：是");
  });
});
