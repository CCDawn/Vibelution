import { describe, expect, it } from "vitest";

import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import type { CommandAction } from "../../../api/types/hypothesisFirst";
import { resolveHypothesisFirstNextAction } from "./hypothesisFirstNextAction";
import {
  buildResearchWorkflowContext,
  buildResearchWorkflowScopeKey,
  researchWorkflowDispatchStatus,
  researchWorkflowScopeMismatch,
} from "./researchWorkflowContextModel";
import type { ResearchWorkflowWorkspaceModel } from "./researchWorkflowWorkspaceModel";

const base = {
  teamId: "research-team",
  workflowId: CHALLENGE_CUP_WORKFLOW_ID,
  questionId: "SCI-004",
  runId: "run-4",
  runVersion: 2,
  panel: "node" as const,
};

describe("researchWorkflowContextModel", () => {
  it("normalizes the scope key and detects stale question/run payloads", () => {
    expect(buildResearchWorkflowScopeKey({
      teamId: " research-team ",
      workflowId: CHALLENGE_CUP_WORKFLOW_ID,
      questionId: "sci-004",
      runId: " run-4 ",
      runVersion: 2,
    })).toBe("research-team::challenge-cup-research::SCI-004::run-4::2");
    expect(researchWorkflowScopeMismatch({
      questionId: "SCI-004",
      dataQuestionId: "SCI-001",
    })).toBe(true);
    expect(researchWorkflowScopeMismatch({
      questionId: "SCI-004",
      dataQuestionId: "sci-004",
      runId: "run-4",
      dataRunId: "run-4",
    })).toBe(false);
    expect(researchWorkflowScopeMismatch({
      teamId: "research-team",
      workflowId: CHALLENGE_CUP_WORKFLOW_ID,
      questionId: "SCI-004",
      runId: "run-4",
      runVersion: 2,
      dataTeamId: "research-team",
      dataWorkflowId: CHALLENGE_CUP_WORKFLOW_ID,
      dataQuestionId: null,
      dataRunId: "run-4",
      dataRunVersion: 2,
      dataScopeReady: true,
    })).toBe(true);
  });

  it("fails closed while a previous question payload is still visible", () => {
    const context = buildResearchWorkflowContext({
      ...base,
      dataQuestionId: "SCI-001",
      dataScopeReady: true,
      nextAction: {
        stage: "selection_required",
        targetNodeId: "hf_selection",
        navigationLabel: "前往假说选择",
        command: "record_selection",
        commandLabel: "记录选择并开启评审",
      },
    });
    expect(context.loadState).toBe("scope_mismatch");
    expect(context.currentTask).toBeNull();
  });

  it("distinguishes a created run with only pending placeholders from an ordinary task", () => {
    expect(researchWorkflowDispatchStatus({
      runStatus: "created",
      nodeRuns: {
        source_finding: { status: "pending", attempt: 0 },
      },
    })).toBe("never_started");

    const context = buildResearchWorkflowContext({
      ...base,
      nextAction: {
        stage: "generation_missing",
        targetNodeId: "hf_generation",
        navigationLabel: "前往候选生成",
        command: "open_generation",
        commandLabel: "生成候选假说",
      },
      runStatus: "created",
      nodeRuns: {
        source_finding: { status: "pending", attempt: 0 },
      },
    });

    expect(context.currentTask).toMatchObject({
      status: "never_started",
      title: "运行从未启动",
      targetNodeId: "hf_generation",
      commandAction: null,
      retryAction: { label: "重试启动" },
      blocker: { code: "never_started", retryable: true },
    });
  });

  it("labels review progress against the single hard limit", () => {
    const context = buildResearchWorkflowContext({
      ...base,
      nextAction: {
        stage: "generation_missing",
        targetNodeId: "hf_generation",
        navigationLabel: "前往候选生成",
        command: "open_generation",
        commandLabel: "生成候选假说",
      },
      roundProgress: { current: 2, total: 4 },
    });
    expect(context.currentTask?.progress).toEqual({
      current: 2,
      total: 4,
      label: "第 2 轮 / 硬上限 4",
    });
  });

  it("projects dispatch_never_started as failed_to_dispatch and keeps started runs normal", () => {
    expect(researchWorkflowDispatchStatus({
      runStatus: "failed",
      runTerminalReason: "dispatch_never_started",
      nodeRuns: {},
    })).toBe("failed_to_dispatch");
    expect(researchWorkflowDispatchStatus({
      runStatus: "created",
      nodeRuns: {
        source_finding: { status: "starting", attempt: 1, nodeRunId: "node-run-1" },
      },
    })).toBeNull();

    const context = buildResearchWorkflowContext({
      ...base,
      nextAction: {
        stage: "generation_missing",
        targetNodeId: "hf_generation",
        navigationLabel: "前往候选生成",
        command: "open_generation",
        commandLabel: "生成候选假说",
      },
      runStatus: "failed",
      runTerminalReason: "dispatch_never_started",
    });
    expect(context.currentTask).toMatchObject({
      status: "failed_to_dispatch",
      title: "运行启动失败",
      retryAction: { label: "重试启动" },
    });
  });

  it("keeps the review gate authoritative even when the chain is already converged", () => {
    const nextAction = resolveHypothesisFirstNextAction({
      run: { runId: "run-4", runtimeCurrentNodeIds: ["source_finding"] },
      workflowActive: true,
      questionId: "SCI-004",
      chainState: {
        schemaVersion: 1,
        teamId: "research-team",
        questionId: "SCI-004",
        selectionId: "sel-4",
        meetingCount: 1,
        firstMeetingId: "meeting-1",
        firstMeetingClosed: false,
        openMeetingIds: ["meeting-1"],
        collectionRequests: [],
        collectionRequestCount: 0,
        pendingCollectionCount: 0,
        collectionReady: false,
        hypothesisRoundCount: 1,
        latestHypothesisRoundId: "round-1",
        hypothesisConverged: true,
        convergenceDetail: "ready",
        roundBudget: 3,
        budgetExhausted: false,
        templateBaselineExists: false,
        templateBaselineIds: [],
      },
      meetings: [{
        schemaVersion: 1,
        meetingRoundId: "meeting-1",
        meetingType: "hypothesis_review",
        mode: "review",
        scopeHash: "scope",
        program: "p",
        theme: "t",
        campaign: "c",
        question: "SCI-004",
        branch: "b",
        workflow: "w",
        agentId: "a",
        participants: ["a"],
        status: "awaiting_approval",
        startedAt: "2026-08-21T00:00:00Z",
        roundIndex: 1,
        digestDraft: {
          agreements: ["保留 H1"],
          disagreements: [],
          actionItems: [],
          knowledgeCandidates: [],
          evidenceRequests: [],
        },
      }],
    });
    const context = buildResearchWorkflowContext({ ...base, nextAction });
    expect(context.currentTask).toMatchObject({
      stage: "hypothesis_first",
      step: "review",
      status: "waiting_user",
      title: "确认本轮评审结论",
      targetNodeId: "hf_meeting_1",
    });
    expect(context.currentTask?.commandAction?.label).toBe("确认并结束本轮");
  });

  it("explains review summarization instead of saying that a minutes file is being generated", () => {
    const context = buildResearchWorkflowContext({
      ...base,
      nextAction: {
        stage: "review_summarizing",
        targetNodeId: "hf_meeting_1",
        navigationLabel: "查看评审讨论",
        statusMessage: "本轮评审已结束，系统正在整理结论",
        meetingRoundId: "meeting-1",
      },
    });
    expect(context.currentTask?.status).toBe("waiting_system");
    expect(context.currentTask?.detail).toContain("保留结论、反对意见和证据缺口");
    expect(context.currentTask?.detail).not.toContain("生成纪要");
  });

  it("keeps history selection separate from the authoritative current task", () => {
    const nextAction = {
      stage: "selection_required" as const,
      targetNodeId: "hf_selection",
      navigationLabel: "前往假说选择",
      command: "record_selection" as const,
      commandLabel: "记录选择并开启评审",
    };
    const history = buildResearchWorkflowContext({
      ...base,
      selectedNodeId: "hf_generation",
      nextAction,
    });
    expect(history.currentTask?.targetNodeId).toBe("hf_selection");
    expect(history.view.selectedNodeId).toBe("hf_generation");
    expect(history.view.selectedIsCurrentTask).toBe(false);

    const current = buildResearchWorkflowContext({
      ...base,
      selectedNodeId: "hf_selection",
      nextAction,
    });
    expect(current.view.selectedIsCurrentTask).toBe(true);
  });

  it("projects collection recovery as the only recoverable command", () => {
    const context = buildResearchWorkflowContext({
      ...base,
      nextAction: {
        stage: "collection_recovery",
        targetNodeId: "source_finding",
        navigationLabel: "前往资料搜集",
        command: "continue_collection",
        commandLabel: "继续搜集",
        recovery: {
          command: "continue_collection",
          label: "继续搜集",
          reason: "资料搜集未完成",
        },
      },
    });
    expect(context.currentTask).toMatchObject({
      step: "evidence_gap",
      status: "recoverable_error",
      commandAction: { command: "continue_collection", label: "继续搜集" },
    });
  });

  it("hands a converged chain to the formal runtime stage without inventing a second state machine", () => {
    const context = buildResearchWorkflowContext({
      ...base,
      selectedNodeId: "source_finding",
      nextAction: {
        stage: "converged",
        targetNodeId: "source_finding",
        navigationLabel: "前往资料寻找",
        statusMessage: "假说先行闭环已完成",
        commandDetail: "假说阶段完成，无需再操作假说；查看下一步研究任务",
      },
    });
    expect(context.currentTask).toMatchObject({
      stage: "knowledge_collection",
      step: "formal_runtime",
      authority: "formal_runtime",
      title: "资料寻找",
    });
    expect(context.stages.map((stage) => stage.state)).toEqual([
      "completed",
      "current",
      "upcoming",
      "upcoming",
    ]);
  });

  it("falls back to the canonical channel when a V2 command has no legacy mapping", () => {
    const canonicalAction: CommandAction = {
      kind: "command",
      actionId: "stop-collection:req-1",
      label: "停止资料搜集",
      enabled: true,
      disabledReason: null,
      targetPhase: "collection",
      targetNodeId: "hf_collection_req-1",
      command: "stop_collection",
      payload: { requestId: "req-1", childRunId: "child-1" },
      inputSchemaRef: null,
      idempotencyKey: "hf2:stop-collection:req-1",
      expectedStateVersion: "hf2-action:origin:current",
      requiresConfirmation: false,
      confirmationText: null,
    };
    const canonicalOnlyAction = {
      stage: "collecting" as const,
      targetNodeId: "hf_collection_req-1",
      navigationLabel: "前往资料搜集",
      command: undefined,
      commandLabel: "停止资料搜集",
      commandDetail: "停止后可重新发起搜集",
      statusMessage: "资料搜集中",
      stateSource: "v2_canonical" as const,
      canonicalCommand: "stop_collection" as const,
      canonicalAction,
      expectedStateVersion: "hf2-action:origin:current",
    };

    // Direct (non-workspace-model) path.
    const context = buildResearchWorkflowContext({ ...base, nextAction: canonicalOnlyAction });
    expect(context.currentTask?.commandAction).toEqual({
      command: undefined,
      canonicalCommand: "stop_collection",
      canonicalAction,
      label: "停止资料搜集",
      detail: "停止后可重新发起搜集",
      disabledReason: undefined,
    });

    // Workspace-model path keeps the same fallback.
    const workspaceModel = {
      scope: {
        teamId: "research-team",
        workflowId: CHALLENGE_CUP_WORKFLOW_ID,
        questionId: "SCI-004",
        runId: "run-4",
        runVersion: 2,
      },
      scopeKey: "research-team::challenge-cup-research::SCI-004::run-4::2",
      loadState: "ready",
      source: "hypothesis_first",
      scopeMismatch: false,
      snapshot: null,
      sequence: 1,
      progress: null,
      currentTask: {
        source: "hypothesis_first",
        authority: "hypothesis_first",
        key: "task-stop-collection",
        status: "waiting_system",
        title: "正在补充证据",
        detail: "资料搜集中",
        targetNodeId: "hf_collection_req-1",
        primaryAction: null,
        nextAction: canonicalOnlyAction,
      },
      primaryAction: null,
      legacyNextAction: canonicalOnlyAction,
      view: {
        panel: "node" as const,
        selectedNodeId: null,
        selectedIsCurrentTask: false,
        archiveMode: false,
      },
      resyncRequired: false,
      error: null,
    } as ResearchWorkflowWorkspaceModel;
    const fromModel = buildResearchWorkflowContext({
      ...base,
      workspaceModel,
      panel: "node",
    });
    expect(fromModel.currentTask?.commandAction).toEqual({
      command: undefined,
      canonicalCommand: "stop_collection",
      canonicalAction,
      label: "停止资料搜集",
      detail: "停止后可重新发起搜集",
      disabledReason: undefined,
    });
  });

  it("keeps legacy commands on the legacy channel without canonical fields", () => {
    const context = buildResearchWorkflowContext({
      ...base,
      nextAction: {
        stage: "collecting",
        targetNodeId: "source_finding",
        navigationLabel: "前往资料搜集",
        statusMessage: "资料搜集中",
      },
    });
    expect(context.currentTask?.commandAction).toBeNull();
  });
});
