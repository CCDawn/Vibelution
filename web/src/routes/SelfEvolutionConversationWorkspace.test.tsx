import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { SelfEvolutionAutonomousLoopRun, SelfObservationRun } from "../api/types";
import {
  buildSelfEvolutionConversationPhases,
  canConfirmAutonomousAction,
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
});
