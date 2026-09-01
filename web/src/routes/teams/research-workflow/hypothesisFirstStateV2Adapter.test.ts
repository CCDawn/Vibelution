import { describe, expect, it } from "vitest";

import type {
  CommandAction,
  HypothesisFirstStateV2,
  NavigationAction,
  PhaseState,
  ReviewCandidateState,
} from "../../../api/types/hypothesisFirst";
import {
  HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
  HYPOTHESIS_FIRST_GENERATION_NODE_ID,
  HYPOTHESIS_FIRST_REVIEW_NODE_ID,
  HYPOTHESIS_FIRST_SELECTION_NODE_ID,
} from "./hypothesisFirstCanvasRegion";
import {
  projectHypothesisFirstSelection,
  resolveHypothesisFirstNextActionFromV2,
} from "./hypothesisFirstStateV2Adapter";

const idle: PhaseState = {
  lifecycle: "not_started",
  outcome: "none",
  actionability: "idle",
  attempt: null,
  updatedAt: null,
  problems: [],
};

function stateV2(overrides: Partial<HypothesisFirstStateV2> = {}): HypothesisFirstStateV2 {
  return {
    schemaVersion: 2,
    contract: "hypothesis-first-state/v2",
    teamId: "team-1",
    questionId: "SCI-001",
    stateVersion: "state-1",
    representationVersion: "repr-1",
    computedAt: "2026-08-25T00:00:00Z",
    scope: { questionInOfficialCatalog: true, catalogId: "challenge-cup", catalogSha256: "sha" },
    resetBoundary: { resetId: "origin", resetAt: null, source: "origin" },
    isInitial: true,
    awaitingHumanCount: 0,
    currentPhase: "generation",
    overall: { ...idle, actionability: "available" },
    generation: { ...idle, actionability: "available", generationMeetingId: null, candidateCount: 0, candidateIds: [] },
    selection: { ...idle, selectionId: null, selectedCandidateIds: [] },
    review: {
      ...idle,
      activeRoundIndex: null,
      aggregate: { total: 0, completed: 0, pending: 0, failed: 0, blocked: 0 },
      candidates: [],
    },
    collection: {
      ...idle,
      aggregate: { total: 0, completed: 0, pending: 0, failed: 0, blocked: 0 },
      requests: [],
    },
    convergence: { ...idle, latestHypothesisRoundId: null, accepted: false, roundIndex: 0, roundBudget: 5 },
    formalRuntime: {
      ...idle,
      runId: null,
      runVersion: null,
      runStatus: null,
      completionKind: null,
      lineageDisposition: null,
      isCurrentRevision: false,
      parentRunId: null,
      childRunIds: [],
      currentNodeIds: [],
    },
    programDelivery: {
      ...idle,
      deliveryStatus: "not_started",
      deliveryArtifactRef: null,
      handoffStatus: "not_started",
      outputRecordId: null,
      outputRunId: null,
      humanReviewStatus: "not_started",
      humanGates: {
        decisions: {
          H1_problem_understanding: "pending",
          H2_hypothesis_selection: "pending",
          H3_research_plan: "pending",
          H4_external_output: "pending",
        },
        reviewer: null,
        rationale: null,
        decidedAt: null,
      },
      approvedGateCount: 0,
      requiredGateCount: 4,
    },
    allowedActions: [],
    problems: [],
    ...overrides,
  };
}

function command(
  action: Pick<CommandAction, "command" | "payload">,
  label = "继续",
): CommandAction {
  const targetPhase = action.command === "record_selection"
    ? "selection"
    : ["approve_summary", "retry_review_dispatch", "reopen_review", "resume_discussion", "stop_discussion", "regenerate_summary"].includes(action.command)
      ? "review"
    : action.command === "create_formal_run"
      ? "formal_runtime"
      : action.command === "open_next_review" || action.command === "human_adjudication"
        ? "convergence"
      : "generation";
  return {
    kind: "command",
    actionId: `action:${action.command}`,
    command: action.command,
    label,
    enabled: true,
    disabledReason: null,
    targetPhase,
    targetNodeId: null,
    payload: action.payload,
    inputSchemaRef: null,
    idempotencyKey: `idem:${action.command}`,
    expectedStateVersion: "state-1",
    requiresConfirmation: false,
    confirmationText: null,
  } as CommandAction;
}

function reviewCandidate(candidateId: string, lifecycle: ReviewCandidateState["lifecycle"]): ReviewCandidateState {
  const terminal = lifecycle === "completed";
  return {
    ...idle,
    lifecycle,
    actionability: terminal ? "terminal" : "waiting_user",
    candidateId,
    candidateOrder: candidateId === "cand-1" ? 1 : 2,
    selectionId: "selection-1",
    roundIndex: 1,
    meetingRoundId: `meeting-${candidateId}`,
    discussionAnchor: null,
    discussion: { ...idle, lifecycle: "completed", outcome: "succeeded", actionability: "terminal" },
    summarization: { ...idle, lifecycle: "completed", outcome: "succeeded", actionability: "terminal" },
    approval: terminal
      ? { ...idle, lifecycle: "completed", outcome: "succeeded", actionability: "terminal" }
      : { ...idle, lifecycle: "waiting_human", actionability: "waiting_user" },
  };
}

describe("resolveHypothesisFirstNextActionFromV2", () => {
  it("keeps every scoped command while preserving the first enabled legacy action", () => {
    const resume = command({
      command: "resume_discussion",
      payload: { meetingRoundId: "meeting-1" },
    }, "恢复讨论");
    const stop = {
      ...command({
        command: "stop_discussion",
        payload: { meetingRoundId: "meeting-1" },
      }, "停止讨论"),
      actionId: "action:stop-discussion",
      enabled: false,
      disabledReason: "停止讨论需要先确认当前轮次",
      requiresConfirmation: true,
      confirmationText: "停止后将关闭当前讨论轮次。",
    } as CommandAction;
    const regenerate = command({
      command: "regenerate_summary",
      payload: { meetingRoundId: "meeting-1" },
    }, "重新整理纪要");
    const state = stateV2({
      isInitial: false,
      currentPhase: "review",
      allowedActions: [resume, stop, regenerate],
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);

    expect(action.canonicalAction?.command).toBe("resume_discussion");
    expect(action.command).toBe("resume_discussion");
    expect(action.canonicalActions?.map((item) => item.command)).toEqual([
      "resume_discussion",
      "stop_discussion",
      "regenerate_summary",
    ]);
    expect(action.canonicalActions?.[1]).toMatchObject({
      enabled: false,
      disabledReason: "停止讨论需要先确认当前轮次",
      requiresConfirmation: true,
    });
  });

  it("marks a failed formal runtime as blocked instead of converged", () => {
    const reconcile = {
      ...command({
        command: "reconcile_formal_run",
        payload: { runId: "formal-run-1" },
      }, "核对正式运行状态"),
      targetPhase: "formal_runtime",
    } as CommandAction;
    const state = stateV2({
      isInitial: false,
      currentPhase: "formal_runtime",
      formalRuntime: {
        ...stateV2().formalRuntime,
        runId: "formal-run-1",
        runStatus: "failed",
        actionability: "blocked",
      },
      allowedActions: [reconcile],
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);

    expect(action.stage).toBe("blocked");
    expect(action.canonicalActions?.map((item) => item.command)).toEqual(["reconcile_formal_run"]);
  });

  it("maps an official catalog cold start to the generation CTA", () => {
    const state = stateV2({
      allowedActions: [command({ command: "open_generation", payload: { questionId: "SCI-001" } }, "生成候选假说")],
    });
    const action = resolveHypothesisFirstNextActionFromV2(state);
    expect(action.stage).toBe("generation_missing");
    expect(action.targetNodeId).toBe(HYPOTHESIS_FIRST_GENERATION_NODE_ID);
    expect(action.command).toBe("open_generation");
    expect(action.expectedStateVersion).toBe("state-1");
  });

  it("maps generation summary recovery to the meeting operations panel", () => {
    const regenerate = {
      ...command({
        command: "regenerate_summary",
        payload: { meetingRoundId: "generation-1" },
      }, "重试生成纪要"),
      targetPhase: "generation",
      targetNodeId: HYPOTHESIS_FIRST_GENERATION_NODE_ID,
    } as CommandAction;
    const state = stateV2({
      isInitial: false,
      currentPhase: "generation",
      generation: {
        ...stateV2().generation,
        lifecycle: "failed",
        actionability: "blocked",
        generationMeetingId: "generation-1",
      },
      allowedActions: [regenerate],
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);

    expect(action.stage).toBe("generation_summarizing");
    expect(action.command).toBe("retry_draft_summary");
    expect(action.commandLabel).toBe("重试生成纪要");
    expect(action.canonicalAction?.command).toBe("regenerate_summary");
  });

  it("keeps generation summary recovery ahead of a stale parent attempt retry", () => {
    const retryGeneration = {
      ...command({
        command: "retry_generation",
        payload: { questionId: "SCI-001", previousAttemptId: "attempt-1" },
      }, "重新生成候选"),
      targetPhase: "generation",
      targetNodeId: HYPOTHESIS_FIRST_GENERATION_NODE_ID,
    } as CommandAction;
    const regenerate = {
      ...command({
        command: "regenerate_summary",
        payload: { meetingRoundId: "generation-1" },
      }, "重试生成纪要"),
      targetPhase: "generation",
      targetNodeId: HYPOTHESIS_FIRST_GENERATION_NODE_ID,
    } as CommandAction;
    const state = stateV2({
      isInitial: false,
      currentPhase: "generation",
      generation: {
        ...stateV2().generation,
        lifecycle: "running",
        actionability: "blocked",
        generationMeetingId: "generation-1",
      },
      allowedActions: [retryGeneration, regenerate],
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);

    expect(action.stage).toBe("generation_summarizing");
    expect(action.command).toBe("retry_draft_summary");
    expect(action.commandLabel).toBe("重试生成纪要");
    expect(action.canonicalAction?.command).toBe("regenerate_summary");
    expect(action.canonicalActions.map((item) => item.command)).toEqual([
      "retry_generation",
      "regenerate_summary",
    ]);
  });

  it("maps generated candidates to selection", () => {
    const state = stateV2({
      isInitial: false,
      currentPhase: "selection",
      generation: { ...stateV2().generation, lifecycle: "completed", outcome: "succeeded", actionability: "terminal", candidateCount: 2, candidateIds: ["cand-1", "cand-2"] },
      selection: { ...stateV2().selection, lifecycle: "waiting_human", actionability: "waiting_user" },
      allowedActions: [command({ command: "record_selection", payload: { questionId: "SCI-001", generationAttemptId: "gen-1" } }, "记录选择")],
    });
    const action = resolveHypothesisFirstNextActionFromV2(state);
    expect(action.stage).toBe("selection_required");
    expect(action.targetNodeId).toBe(HYPOTHESIS_FIRST_SELECTION_NODE_ID);
    expect(action.command).toBe("record_selection");
  });

  it("keeps healthy review progress ahead of a stale dispatch problem", () => {
    const dispatchProblem = {
      code: "review_dispatch_missing",
      category: "integrity" as const,
      severity: "error" as const,
      message: "已记录选择，但候选评审会议尚未建立",
      recoverable: true,
      sourceKind: "review_dispatch",
      sourceId: "selection-1",
      detectedAt: "2026-08-25T00:00:00Z",
    };
    const candidate = {
      ...reviewCandidate("cand-1", "running"),
      actionability: "executing" as const,
      discussion: { ...idle, lifecycle: "running" as const, actionability: "executing" as const },
      summarization: { ...idle },
      approval: { ...idle },
    };
    const state = stateV2({
      isInitial: false,
      currentPhase: "review",
      review: {
        ...stateV2().review,
        lifecycle: "running",
        actionability: "blocked",
        problems: [dispatchProblem],
        activeRoundIndex: 1,
        aggregate: { total: 2, completed: 0, pending: 2, failed: 0, blocked: 0 },
        candidates: [candidate],
      },
      problems: [dispatchProblem],
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);
    expect(action.stage).toBe("review_running");
    expect(action.statusMessage).toBe("本轮候选评审：已完成 0/2");
    expect(action.disabledReason).toBeUndefined();
  });

  it("surfaces the canonical reopen action for an orphaned review round", () => {
    const blockedCandidate = {
      ...reviewCandidate("cand-1", "failed"),
      actionability: "blocked" as const,
      discussion: { ...idle, lifecycle: "failed" as const, actionability: "blocked" as const },
      summarization: { ...idle },
      approval: { ...idle },
    };
    const reopen = command({
      command: "reopen_review",
      payload: { meetingRoundId: "meeting-cand-1" },
    }, "重新发起评审讨论");
    const state = stateV2({
      isInitial: false,
      currentPhase: "review",
      review: {
        ...stateV2().review,
        lifecycle: "failed",
        actionability: "blocked",
        activeRoundIndex: 1,
        aggregate: { total: 1, completed: 0, pending: 0, failed: 1, blocked: 1 },
        candidates: [blockedCandidate],
      },
      allowedActions: [reopen],
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);

    expect(action.stage).toBe("blocked");
    expect(action.command).toBe("reopen_review");
    expect(action.canonicalAction?.command).toBe("reopen_review");
    expect(action.disabledReason).toBeUndefined();
  });

  it("retries only the failed candidate summary instead of redispatching the review batch", () => {
    const summaryProblem = {
      code: "summary_draft_failed",
      category: "execution" as const,
      severity: "error" as const,
      message: "Service temporarily unavailable",
      recoverable: true,
      sourceKind: "meeting_round",
      sourceId: "meeting-cand-1",
      detectedAt: "2026-08-26T15:24:12Z",
    };
    const failedCandidate = {
      ...reviewCandidate("cand-1", "failed"),
      actionability: "available" as const,
      problems: [summaryProblem],
      summarization: { ...idle, lifecycle: "running" as const, actionability: "waiting_system" as const },
      approval: { ...idle },
    };
    const redispatch = command({
      command: "retry_review_dispatch",
      payload: { selectionId: "selection-1", candidateIds: ["cand-1"] },
    }, "重试候选评审分发");
    const regenerate = command({
      command: "regenerate_summary",
      payload: { meetingRoundId: "meeting-cand-1" },
    }, "重试生成纪要");
    const state = stateV2({
      isInitial: false,
      currentPhase: "review",
      review: {
        ...stateV2().review,
        lifecycle: "failed",
        actionability: "available",
        problems: [summaryProblem],
        activeRoundIndex: 2,
        aggregate: { total: 1, completed: 0, pending: 0, failed: 1, blocked: 0 },
        candidates: [failedCandidate],
      },
      allowedActions: [redispatch, regenerate],
      problems: [summaryProblem],
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);

    expect(action.stage).toBe("blocked");
    expect(action.command).toBe("retry_draft_summary");
    expect(action.commandLabel).toBe("重试生成纪要");
    expect(action.canonicalAction?.command).toBe("regenerate_summary");
    expect(action.canonicalActions.map((item) => item.command)).toEqual([
      "retry_review_dispatch",
      "regenerate_summary",
    ]);
  });

  it("selects the exact pending candidate from a two-candidate review", () => {
    const completedNavigation: NavigationAction = {
      kind: "navigation",
      actionId: "navigate:cand-1",
      label: "进入候选一会议",
      enabled: true,
      disabledReason: null,
      targetPhase: "review",
      targetNodeId: HYPOTHESIS_FIRST_REVIEW_NODE_ID,
      navigation: {
        status: "ready",
        degradedReason: null,
        roomId: "room-1",
        meetingRoundId: "meeting-cand-1",
        questionId: "SCI-001",
        selectionId: "selection-1",
        candidateId: "cand-1",
        deepLink: "/chat?room=room-1",
        returnTo: "/teams?questionId=SCI-001",
        returnLabel: "返回流程",
      },
    };
    const pendingNavigation: NavigationAction = {
      ...completedNavigation,
      actionId: "navigate:cand-2",
      label: "进入候选二会议",
      navigation: {
        ...completedNavigation.navigation,
        roomId: "room-2",
        meetingRoundId: "meeting-cand-2",
        candidateId: "cand-2",
        deepLink: "/chat?room=room-2",
      },
    };
    const state = stateV2({
      isInitial: false,
      currentPhase: "review",
      review: {
        ...stateV2().review,
        lifecycle: "waiting_human",
        actionability: "waiting_user",
        activeRoundIndex: 1,
        aggregate: { total: 2, completed: 1, pending: 1, failed: 0, blocked: 0 },
        candidates: [reviewCandidate("cand-1", "completed"), reviewCandidate("cand-2", "waiting_human")],
      },
      allowedActions: [completedNavigation, pendingNavigation],
    });
    const action = resolveHypothesisFirstNextActionFromV2(state);
    expect(action.targetNodeId).toBe("hf_meeting_1_cand-2");
    expect(action.stage).toBe("review_awaiting_approval");
    expect(action.meetingRoundId).toBe("meeting-cand-2");
    expect(action.navigationDeepLink).toBe("/chat?room=room-2");
  });

  it("keeps mixed sibling commands bound to the selected candidate meeting", () => {
    const runningCandidate = {
      ...reviewCandidate("cand-1", "running"),
      actionability: "executing" as const,
      discussion: { ...idle, lifecycle: "running" as const, actionability: "executing" as const },
      summarization: { ...idle },
      approval: { ...idle },
    };
    const approveCandidateTwo = command({
      command: "approve_summary",
      payload: { meetingRoundId: "meeting-cand-2" },
    }, "确认候选二纪要");
    const state = stateV2({
      isInitial: false,
      currentPhase: "review",
      review: {
        ...stateV2().review,
        lifecycle: "running",
        actionability: "executing",
        activeRoundIndex: 1,
        aggregate: { total: 2, completed: 0, pending: 2, failed: 0, blocked: 0 },
        candidates: [runningCandidate, reviewCandidate("cand-2", "waiting_human")],
      },
      allowedActions: [approveCandidateTwo],
    });

    const globalAction = resolveHypothesisFirstNextActionFromV2(state);
    expect(globalAction.targetNodeId).toBe("hf_meeting_1_cand-1");
    expect(globalAction.canonicalAction).toBeUndefined();
    expect(globalAction.meetingRoundId).toBe("meeting-cand-1");

    const candidateTwoAction = resolveHypothesisFirstNextActionFromV2(state, {
      preferredCandidateId: "cand-2",
    });
    expect(candidateTwoAction.targetNodeId).toBe("hf_meeting_1_cand-2");
    expect(candidateTwoAction.canonicalAction?.command).toBe("approve_summary");
    expect(candidateTwoAction.meetingRoundId).toBe("meeting-cand-2");
  });

  it("does not borrow a pending sibling command when the selected candidate is completed", () => {
    const approveCandidateTwo = command({
      command: "approve_summary",
      payload: { meetingRoundId: "meeting-cand-2" },
    }, "确认候选二纪要");
    const state = stateV2({
      isInitial: false,
      currentPhase: "review",
      review: {
        ...stateV2().review,
        lifecycle: "waiting_human",
        actionability: "waiting_user",
        activeRoundIndex: 1,
        aggregate: { total: 2, completed: 1, pending: 1, failed: 0, blocked: 0 },
        candidates: [reviewCandidate("cand-1", "completed"), reviewCandidate("cand-2", "waiting_human")],
      },
      allowedActions: [approveCandidateTwo],
    });

    const completedCandidateAction = resolveHypothesisFirstNextActionFromV2(state, {
      preferredCandidateId: "cand-1",
    });

    expect(completedCandidateAction.targetNodeId).toBe("hf_meeting_1_cand-1");
    expect(completedCandidateAction.meetingRoundId).toBe("meeting-cand-1");
    expect(completedCandidateAction.canonicalAction).toBeUndefined();
  });

  it("offers formal run creation after convergence", () => {
    const state = stateV2({
      isInitial: false,
      currentPhase: "formal_runtime",
      convergence: { ...stateV2().convergence, lifecycle: "completed", outcome: "succeeded", actionability: "terminal", accepted: true, latestHypothesisRoundId: "round-3", roundIndex: 3 },
      formalRuntime: { ...stateV2().formalRuntime, actionability: "available" },
      allowedActions: [command({ command: "create_formal_run", payload: { questionId: "SCI-001", hypothesisRoundId: "round-3" } }, "创建正式研究运行")],
    });
    const action = resolveHypothesisFirstNextActionFromV2(state);
    expect(action.command).toBe("create_run");
    expect(action.targetNodeId).toBe(HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID);
  });

  it("keeps an unaccepted round in review until the server budget is exhausted", () => {
    const state = stateV2({
      isInitial: false,
      currentPhase: "convergence",
      convergence: { ...stateV2().convergence, lifecycle: "waiting_human", actionability: "waiting_user", latestHypothesisRoundId: "round-1", roundIndex: 1, roundBudget: 3 },
      allowedActions: [command({ command: "open_next_review", payload: { previousMeetingRoundId: "meeting-1", roundBudget: 3 } }, "发起下一轮候选评审")],
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);
    expect(action.stage).toBe("next_review");
    expect(action.command).toBe("open_next_review");
    expect(action.canonicalAction?.command).toBe("open_next_review");
  });

  it("explains a claim-gate-blocked convergence without touching the server action authority", () => {
    const state = stateV2({
      isInitial: false,
      currentPhase: "convergence",
      convergence: {
        ...stateV2().convergence,
        lifecycle: "waiting_human",
        actionability: "waiting_user",
        accepted: false,
        latestHypothesisRoundId: "round-2",
        roundIndex: 2,
        roundBudget: 5,
        claimBeliefGate: {
          decisionPoint: "converge_question",
          roundId: "round-2",
          candidateId: "cand-1",
          status: "blocked",
          reason: "claim_belief_state_blocked",
          claims: [],
          blockedClaims: [{ claimId: "claim-7", beliefState: "contradicted" }],
          evidenceGaps: [],
        },
      },
      allowedActions: [command({ command: "open_next_review", payload: { previousMeetingRoundId: "meeting-1", roundBudget: 5 } }, "发起下一轮候选评审")],
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);

    // Navigation mapping stays stable; the server-authored button stays the
    // single authority (present, enabled, unmodified).
    expect(action.stage).toBe("next_review");
    expect(action.canonicalAction?.command).toBe("open_next_review");
    expect(action.canonicalAction?.enabled).toBe(true);
    expect(action.canonicalActions.map((item) => item.command)).toEqual(["open_next_review"]);
    // The guidance copy explains the gate block instead of luring the user
    // into "open the next review round" as if it were the fix.
    expect(action.claimGate?.status).toBe("blocked");
    expect(action.claimGate?.blockedClaims.map((claim) => claim.claimId)).toEqual(["claim-7"]);
    expect(action.statusMessage).toContain("claim 证据门拦截");
    expect(action.statusMessage).toContain("claim_belief_state_blocked");
    expect(action.commandDetail).toContain("claim 证据门拦截");
  });

  it("treats a malformed claim gate payload as unknown instead of crashing", () => {
    const state = stateV2({
      isInitial: false,
      currentPhase: "convergence",
      convergence: {
        ...stateV2().convergence,
        lifecycle: "waiting_human",
        actionability: "waiting_user",
        claimBeliefGate: { status: 42, reason: null, blockedClaims: "noise" } as never,
      },
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);

    expect(action.claimGate?.status).toBe("unknown");
    expect(action.claimGate?.blockedClaims).toEqual([]);
    expect(action.statusMessage).not.toContain("claim 证据门拦截");
  });

  it("reports a terminally rejected adjudication without inventing a next action", () => {
    const state = stateV2({
      isInitial: false,
      currentPhase: "convergence",
      convergence: {
        ...stateV2().convergence,
        lifecycle: "completed",
        outcome: "rejected",
        actionability: "terminal",
        latestHypothesisRoundId: "round-3",
        roundIndex: 3,
        roundBudget: 3,
      },
      allowedActions: [],
    });

    const action = resolveHypothesisFirstNextActionFromV2(state);

    expect(action.stage).toBe("blocked");
    expect(action.command).toBeUndefined();
    expect(action.statusMessage).toContain("已拒绝");
  });

  it("keeps program delivery as an explicit phase", () => {
    const staleReviewNavigation: NavigationAction = {
      kind: "navigation",
      actionId: "navigate:old-review",
      label: "旧评审会议",
      enabled: true,
      disabledReason: null,
      targetPhase: "review",
      targetNodeId: HYPOTHESIS_FIRST_REVIEW_NODE_ID,
      navigation: {
        status: "ready",
        degradedReason: null,
        roomId: "old-room",
        meetingRoundId: "old-meeting",
        questionId: "SCI-001",
        selectionId: "selection-1",
        candidateId: "cand-1",
        deepLink: "/chat?room=old-room",
        returnTo: "/teams?questionId=SCI-001",
        returnLabel: "返回流程",
      },
    };
    const state = stateV2({
      isInitial: false,
      currentPhase: "program_delivery",
      programDelivery: { ...stateV2().programDelivery, lifecycle: "running", actionability: "waiting_system", deliveryStatus: "running", outputRunId: "run-1" },
      allowedActions: [staleReviewNavigation],
    });
    const action = resolveHypothesisFirstNextActionFromV2(state);
    expect(action.stage).toBe("program_delivery");
    expect(action.targetNodeId).toBe(HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID);
    expect(action.navigationDeepLink).toBeUndefined();
  });

  it("maps four approved gates to completed", () => {
    const state = stateV2({
      isInitial: false,
      currentPhase: "completed",
      programDelivery: { ...stateV2().programDelivery, lifecycle: "completed", outcome: "succeeded", actionability: "terminal", deliveryStatus: "succeeded", handoffStatus: "registered", humanReviewStatus: "approved", approvedGateCount: 4 },
    });
    const action = resolveHypothesisFirstNextActionFromV2(state);
    expect(action.stage).toBe("completed");
    expect(action.statusMessage).toContain("已闭环");
  });

  it("preserves the server navigation deep link and return parameters", () => {
    const navigation: NavigationAction = {
      kind: "navigation",
      actionId: "navigate:review",
      label: "进入候选会议",
      enabled: true,
      disabledReason: null,
      targetPhase: "review",
      targetNodeId: HYPOTHESIS_FIRST_REVIEW_NODE_ID,
      navigation: {
        status: "ready",
        degradedReason: null,
        roomId: "room-1",
        meetingRoundId: "meeting-cand-2",
        questionId: "SCI-001",
        selectionId: "selection-1",
        candidateId: "cand-2",
        deepLink: "/chat?room=room-1&returnTo=%2Fteams%3FquestionId%3DSCI-001&returnLabel=%E8%BF%94%E5%9B%9E%E6%B5%81%E7%A8%8B",
        returnTo: "/teams?questionId=SCI-001",
        returnLabel: "返回流程",
      },
    };
    const state = stateV2({ currentPhase: "review", allowedActions: [navigation] });
    expect(resolveHypothesisFirstNextActionFromV2(state).navigationDeepLink).toBe(navigation.navigation.deepLink);
  });
});

describe("projectHypothesisFirstSelection", () => {
  it("uses only a unique, current V2 selection phase as editable", () => {
    const state = stateV2({
      isInitial: false,
      currentPhase: "selection",
      generation: {
        ...stateV2().generation,
        lifecycle: "completed",
        outcome: "succeeded",
        actionability: "terminal",
        candidateCount: 2,
        candidateIds: ["cand-1", "cand-2"],
      },
      selection: { ...stateV2().selection, lifecycle: "waiting_human", actionability: "waiting_user" },
      allowedActions: [command({
        command: "record_selection",
        payload: { questionId: "SCI-001", generationAttemptId: "generation-1" },
      }, "记录选择")],
    });

    expect(projectHypothesisFirstSelection({ state })).toMatchObject({
      status: "editable",
      locked: false,
      selectedCandidateIds: [],
      selectionId: null,
    });
  });

  it("projects the committed selection and locks mutation after selection or review facts", () => {
    const committed = stateV2({
      isInitial: false,
      currentPhase: "selection",
      selection: {
        ...stateV2().selection,
        lifecycle: "completed",
        outcome: "succeeded",
        actionability: "terminal",
        selectionId: "selection-1",
        selectedCandidateIds: ["cand-2", "cand-1"],
      },
      allowedActions: [command({
        command: "record_selection",
        payload: { questionId: "SCI-001", generationAttemptId: "generation-1" },
      })],
    });
    const committedProjection = projectHypothesisFirstSelection({ state: committed });
    expect(committedProjection).toMatchObject({
      status: "committed",
      locked: true,
      selectedCandidateIds: ["cand-2", "cand-1"],
      selectionId: "selection-1",
    });

    const reviewed = stateV2({
      isInitial: false,
      currentPhase: "review",
      review: {
        ...stateV2().review,
        lifecycle: "waiting_human",
        actionability: "waiting_user",
        activeRoundIndex: 1,
        aggregate: { total: 1, completed: 0, pending: 1, failed: 0, blocked: 0 },
        candidates: [reviewCandidate("cand-1", "waiting_human")],
      },
      allowedActions: [],
    });
    expect(projectHypothesisFirstSelection({ state: reviewed })).toMatchObject({
      status: "locked",
      locked: true,
      selectedCandidateIds: [],
    });
  });

  it("fails closed while V2 is loading, failed, or not unique", () => {
    expect(projectHypothesisFirstSelection({ loading: true })).toMatchObject({
      status: "locked",
      locked: true,
    });
    expect(projectHypothesisFirstSelection({ error: new Error("state unavailable") })).toMatchObject({
      status: "locked",
      locked: true,
    });
    expect(projectHypothesisFirstSelection({ states: [] })).toMatchObject({
      status: "locked",
      locked: true,
    });
    expect(projectHypothesisFirstSelection({ states: [stateV2(), stateV2()] })).toMatchObject({
      status: "locked",
      locked: true,
    });
  });
});
