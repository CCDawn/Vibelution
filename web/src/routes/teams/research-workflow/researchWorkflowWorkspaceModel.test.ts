import { describe, expect, it } from "vitest";

import type {
  ResearchWorkflowCurrentTask,
  ResearchWorkflowProgress,
  ResearchWorkflowSnapshot,
} from "../../../api/types/research-workflow/core";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import {
  allowsResearchRunLaunch,
  buildResearchWorkflowWorkspaceModel,
  mergeResearchWorkflowWorkspaceSnapshot,
  type ResearchWorkflowWorkspaceModelInput,
} from "./researchWorkflowWorkspaceModel";

function formalTask(overrides: Partial<ResearchWorkflowCurrentTask> = {}): ResearchWorkflowCurrentTask {
  return {
    key: "task:source-finding",
    nodeId: "source_finding",
    stageId: "knowledge_collection",
    nodeRunId: "node-run-1",
    attempt: 1,
    actorKind: "agent",
    taskId: null,
    status: "running",
    state: "auto_running",
    kind: "node",
    label: "资料寻找",
    detail: "系统正在搜集资料",
    responsibility: "system",
    maxAttempts: 3,
    automaticNextStep: { effectCode: "advance" },
    blockedReason: null,
    recovery: {
      status: "none",
      retryable: false,
      code: null,
      detail: null,
      retryScope: "none",
      recoveryPoint: null,
      nextRetryAt: null,
      requiresOperator: false,
      afterSubmit: null,
    },
    authority: "formal_runtime",
    ...overrides,
  };
}

function progress(overrides: Partial<ResearchWorkflowProgress> = {}): ResearchWorkflowProgress {
  return {
    completedNodes: 2,
    totalNodes: 16,
    blockedNodes: 0,
    currentStageId: "knowledge_collection",
    stages: [
      { id: "hypothesis_first", completed: 1, total: 1, blocked: 0, state: "completed" },
      { id: "knowledge_collection", completed: 1, total: 5, blocked: 0, state: "current" },
      { id: "experiment_design", completed: 0, total: 5, blocked: 0, state: "upcoming" },
    ],
    completedNodeIds: ["source_finding"],
    blockedNodeIds: [],
    completed: 2,
    total: 16,
    percent: 12.5,
    currentNodeId: "source_finding",
    status: "running",
    ...overrides,
  };
}

function offer(overrides: Partial<CommandOffer> = {}): CommandOffer {
  return {
    command: "retry_node",
    nodeId: "source_finding",
    available: true,
    label: "重试资料寻找",
    reasonCode: "",
    blockerIds: [],
    idempotencyKey: "retry:run-1:source-finding",
    expectedRunVersion: 4,
    payload: {},
    ...overrides,
  };
}

function snapshot(overrides: Partial<ResearchWorkflowSnapshot> = {}): ResearchWorkflowSnapshot {
  return {
    run: {
      runId: "run-1",
      teamId: "team-1",
      workflowId: CHALLENGE_CUP_WORKFLOW_ID,
      workflowVersionId: "workflow-v1",
      threadId: "thread-1",
      projectId: "project-1",
      questionId: "SCI-001",
      status: "running",
      runVersion: 4,
      inputSnapshotHash: "a".repeat(64),
      bindingSnapshotSetId: "bindings-1",
      activeNodeId: "source_finding",
      parentRunId: null,
      forkedFromCheckpointId: null,
      completionKind: null,
      terminalReason: null,
      createdAtMs: 1,
      updatedAtMs: 2,
      completedAtMs: null,
    },
    definition: {},
    nodeAttempts: {},
    activeNodeIds: ["source_finding"],
    pendingHumanTasks: [],
    commandOffers: [offer()],
    handoffSummary: { countsByStatus: {}, refs: [], count: 0 },
    agentBindingSummary: {
      bindingSnapshotSetId: "bindings-1",
      bindingSnapshotIds: [],
      count: 0,
    },
    budgetSummary: { safetyLimits: {}, receiptRefs: [], receiptCount: 0 },
    latestEventSequence: 8,
    generatedAt: "2026-08-23T00:00:00.000Z",
    schemaVersion: 2,
    currentTask: formalTask(),
    progress: progress(),
    ...overrides,
  };
}

function baseInput(overrides: Partial<ResearchWorkflowWorkspaceModelInput> = {}): ResearchWorkflowWorkspaceModelInput {
  return {
    scope: {
      teamId: "team-1",
      workflowId: CHALLENGE_CUP_WORKFLOW_ID,
      questionId: "SCI-001",
      runId: "run-1",
      runVersion: 4,
    },
    snapshot: snapshot(),
    commandOffers: snapshot().commandOffers,
    selectedNodeId: "source_finding",
    panel: "node",
    resyncRequired: false,
    ...overrides,
  };
}

describe("researchWorkflowWorkspaceModel", () => {
  it.each([
    ["auto_running", "running"],
    ["waiting_user", "waiting_user"],
    ["blocked_retryable", "recoverable_error"],
    ["blocked_terminal", "blocked"],
    ["completed", "completed"],
  ] as const)("maps formal %s to %s without legacy override", (state, status) => {
    const model = buildResearchWorkflowWorkspaceModel(baseInput({
      legacyNextAction: {
        stage: "selection_required",
        targetNodeId: "hf_selection",
        navigationLabel: "前往假说选择",
        command: "record_selection",
        commandLabel: "记录选择并开启评审",
      },
      snapshot: snapshot({ currentTask: formalTask({ state }) }),
    }));
    expect(model.source).toBe("formal_runtime");
    expect(model.currentTask?.source).toBe("formal_runtime");
    expect(model.currentTask?.status).toBe(status);
    expect(model.currentTask?.nodeId).toBe("source_finding");
  });

  it("takes exactly one matching available formal offer as primary action", () => {
    const model = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: snapshot({
        currentTask: formalTask({ state: "waiting_user", responsibility: "user" }),
        commandOffers: [offer()],
      }),
      commandOffers: [offer()],
    }));
    expect(model.primaryAction?.offer.command).toBe("retry_node");
    expect(model.currentTask?.source === "formal_runtime" && model.currentTask.primaryAction?.offer.nodeId)
      .toBe("source_finding");
  });

  it("fails closed when formal offers conflict or do not match the task", () => {
    const model = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: snapshot({
        currentTask: formalTask({ state: "waiting_user", responsibility: "user" }),
        commandOffers: [offer(), offer({ command: "cancel_node", idempotencyKey: "cancel:1" })],
      }),
      commandOffers: [offer(), offer({ command: "cancel_node", idempotencyKey: "cancel:1" })],
    }));
    expect(model.primaryAction).toBeNull();
    expect(model.currentTask?.source === "formal_runtime" && model.currentTask.primaryAction).toBeNull();
  });

  it("does not expose a CTA for automatic, completed, or terminal blocked states", () => {
    for (const state of ["auto_running", "completed", "blocked_terminal"] as const) {
      const model = buildResearchWorkflowWorkspaceModel(baseInput({
        snapshot: snapshot({ currentTask: formalTask({ state }) }),
      }));
      expect(model.primaryAction).toBeNull();
    }
  });

  it("uses catalog authorization before hypothesis-first when explicitly required", () => {
    const model = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: null,
      scope: { ...baseInput().scope, runId: null, runVersion: null },
      legacyNextAction: {
        stage: "generation_missing",
        targetNodeId: "hf_generation",
        navigationLabel: "前往候选生成",
        command: "open_generation",
        commandLabel: "生成候选假说",
      },
      catalogAuthorization: {
        required: true,
        status: "waiting",
        label: "等待研究授权",
        detail: "目录研究需要授权后才能启动",
      },
    }));
    expect(model.source).toBe("catalog_authorization");
    expect(model.currentTask?.source).toBe("catalog_authorization");
    expect(model.primaryAction).toBeNull();
  });

  it("falls back to hypothesis-first and then route/no_run", () => {
    const hypothesis = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: null,
      scope: { ...baseInput().scope, runId: null, runVersion: null },
      legacyNextAction: {
        stage: "generation_missing",
        targetNodeId: "hf_generation",
        navigationLabel: "前往候选生成",
        command: "open_generation",
        commandLabel: "生成候选假说",
      },
    }));
    expect(hypothesis.source).toBe("hypothesis_first");
    expect(hypothesis.currentTask?.source).toBe("hypothesis_first");

    const route = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: null,
      legacyNextAction: null,
      scope: { ...baseInput().scope, questionId: null, runId: null, runVersion: null },
    }));
    expect(route.source).toBe("route");
    expect(route.currentTask?.source).toBe("route");
  });

  it("only allows the launch surface for route/no_run tasks", () => {
    const formal = buildResearchWorkflowWorkspaceModel(baseInput());
    expect(allowsResearchRunLaunch(formal)).toBe(false);

    const formalPending = buildResearchWorkflowWorkspaceModel(baseInput({ snapshot: null }));
    expect(formalPending.source).toBe("formal_runtime");
    expect(formalPending.currentTask).toBeNull();
    expect(allowsResearchRunLaunch(formalPending)).toBe(false);

    const hypothesis = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: null,
      scope: { ...baseInput().scope, questionId: "SCI-001", runId: null, runVersion: null },
      legacyNextAction: {
        stage: "selection_required",
        targetNodeId: "hf_selection",
        navigationLabel: "前往假说选择",
        command: "record_selection",
        commandLabel: "记录选择并开启评审",
      },
    }));
    expect(allowsResearchRunLaunch(hypothesis)).toBe(false);

    const noRun = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: null,
      scope: { ...baseInput().scope, questionId: "SCI-001", runId: null, runVersion: null },
      legacyNextAction: {
        stage: "no_run",
        targetNodeId: null,
        navigationLabel: "选择题目开始研究",
        command: "create_run",
        commandLabel: "选择题目开始研究",
      },
    }));
    expect(allowsResearchRunLaunch(noRun)).toBe(true);

    const converged = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: null,
      scope: { ...baseInput().scope, questionId: "SCI-001", runId: null, runVersion: null },
      legacyNextAction: {
        stage: "converged",
        targetNodeId: "hf_convergence",
        navigationLabel: "创建正式研究运行",
        command: "create_run",
        commandLabel: "创建正式研究运行",
      },
    }));
    expect(converged.source).toBe("hypothesis_first");
    expect(allowsResearchRunLaunch(converged)).toBe(false);

    const route = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: null,
      scope: { ...baseInput().scope, questionId: null, runId: null, runVersion: null },
      legacyNextAction: null,
    }));
    expect(allowsResearchRunLaunch(route)).toBe(true);
  });

  it("rejects scope conflicts and keeps history selection separate", () => {
    const model = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: snapshot({
        run: { ...snapshot().run, questionId: "SCI-002" },
      }),
      selectedNodeId: "source_extraction",
    }));
    expect(model.scopeMismatch).toBe(true);
    expect(model.currentTask).toBeNull();
    expect(model.primaryAction).toBeNull();

    const history = buildResearchWorkflowWorkspaceModel(baseInput({ selectedNodeId: "source_extraction" }));
    expect(history.currentTask?.source).toBe("formal_runtime");
    expect(history.view.selectedNodeId).toBe("source_extraction");
    expect(history.view.selectedIsCurrentTask).toBe(false);
  });

  it("uses v2 progress rather than stage index guesses", () => {
    const model = buildResearchWorkflowWorkspaceModel(baseInput({
      snapshot: snapshot({
        progress: progress({
          completed: 9,
          total: 16,
          percent: 56.25,
          blockedNodes: 2,
          stages: [
            { id: "hypothesis_first", completed: 1, total: 1, blocked: 0, state: "completed" },
            { id: "knowledge_collection", completed: 3, total: 5, blocked: 2, state: "blocked" },
          ],
        }),
      }),
    }));
    expect(model.progress?.percent).toBe(56.25);
    expect(model.progress?.stages[1].state).toBe("blocked");
  });

  it("does not let an older snapshot or resync state regress the model", () => {
    const current = buildResearchWorkflowWorkspaceModel(baseInput());
    const older = mergeResearchWorkflowWorkspaceSnapshot(current, {
      ...baseInput({ snapshot: snapshot({ latestEventSequence: 7 }) }),
    });
    expect(older.sequence).toBe(8);
    expect(older.snapshot?.latestEventSequence).toBe(8);

    const resync = mergeResearchWorkflowWorkspaceSnapshot(current, {
      ...baseInput({ snapshot: snapshot({ latestEventSequence: 9 }), resyncRequired: true }),
    });
    expect(resync.primaryAction).toBeNull();
    expect(resync.resyncRequired).toBe(true);
  });

  it("drops the previous snapshot when the atomic scope changes", () => {
    const current = buildResearchWorkflowWorkspaceModel(baseInput());
    const nextScope = {
      teamId: "team-1",
      workflowId: CHALLENGE_CUP_WORKFLOW_ID,
      questionId: "SCI-002",
      runId: "run-2",
      runVersion: 1,
    };
    const next = mergeResearchWorkflowWorkspaceSnapshot(current, {
      ...baseInput({
        scope: nextScope,
        snapshot: snapshot({
          run: {
            ...snapshot().run,
            runId: "run-2",
            questionId: "SCI-002",
            runVersion: 1,
          },
          latestEventSequence: 1,
        }),
      }),
      scope: nextScope,
    });
    expect(next.scopeMismatch).toBe(false);
    expect(next.snapshot?.run.runId).toBe("run-2");
    expect(next.sequence).toBe(1);
  });

  it("keeps a named formal run fail-closed until its snapshot arrives", () => {
    const legacyNextAction = {
      stage: "selection_required" as const,
      targetNodeId: "hf_selection",
      navigationLabel: "前往假说选择",
      command: "record_selection" as const,
      commandLabel: "记录选择并开启评审",
    };
    for (const state of [
      { loading: true, error: null },
      { loading: false, error: "snapshot_unavailable" },
    ]) {
      const model = buildResearchWorkflowWorkspaceModel(baseInput({
        snapshot: null,
        legacyNextAction,
        loading: state.loading,
        error: state.error,
      }));
      expect(model.source).toBe("formal_runtime");
      expect(model.currentTask).toBeNull();
      expect(model.primaryAction).toBeNull();
      expect(model.legacyNextAction).toBeNull();
    }
  });
});
