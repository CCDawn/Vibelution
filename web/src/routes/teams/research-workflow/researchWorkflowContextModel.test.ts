import { describe, expect, it } from "vitest";

import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import { resolveHypothesisFirstNextAction } from "./hypothesisFirstNextAction";
import {
  buildResearchWorkflowContext,
  buildResearchWorkflowScopeKey,
  researchWorkflowScopeMismatch,
} from "./researchWorkflowContextModel";

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
    })).toContain("research-team::challenge-cup-research::SCI-004::run-4");
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
  });

  it("fails closed while a previous question payload is still visible", () => {
    const context = buildResearchWorkflowContext({
      ...base,
      dataQuestionId: "SCI-001",
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
});
