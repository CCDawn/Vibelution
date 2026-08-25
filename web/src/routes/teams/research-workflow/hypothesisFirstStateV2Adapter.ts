import type {
  AllowedAction,
  CommandAction,
  HypothesisFirstPhase,
  HypothesisFirstStateV2,
  NavigationAction,
  ReviewCandidateState,
} from "../../../api/types/hypothesisFirst";
import {
  HYPOTHESIS_FIRST_COLLECTION_NODE_ID,
  HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
  HYPOTHESIS_FIRST_GENERATION_NODE_ID,
  HYPOTHESIS_FIRST_REVIEW_NODE_ID,
  HYPOTHESIS_FIRST_SELECTION_NODE_ID,
} from "./hypothesisFirstCanvasRegion";
import type {
  HypothesisFirstCommand,
  HypothesisFirstNextAction,
  HypothesisFirstStage,
} from "./hypothesisFirstNextAction";

type ResolveV2Options = {
  preferredCandidateId?: string | null;
  preferredMeetingRoundId?: string | null;
};

function reviewNodeId(candidate: ReviewCandidateState): string {
  return `hf_meeting_${candidate.roundIndex}_${encodeURIComponent(candidate.candidateId)}`;
}

function phaseTarget(
  state: HypothesisFirstStateV2,
  reviewCandidate: ReviewCandidateState | null,
): string {
  switch (state.currentPhase) {
    case "generation": return HYPOTHESIS_FIRST_GENERATION_NODE_ID;
    case "selection": return HYPOTHESIS_FIRST_SELECTION_NODE_ID;
    case "review": return reviewCandidate?.meetingRoundId
      ? reviewNodeId(reviewCandidate)
      : HYPOTHESIS_FIRST_REVIEW_NODE_ID;
    case "collection": return HYPOTHESIS_FIRST_COLLECTION_NODE_ID;
    case "formal_runtime":
      return state.formalRuntime.currentNodeIds[0] || HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID;
    case "convergence":
    case "program_delivery":
    case "completed":
      return HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID;
  }
}

function phaseState(state: HypothesisFirstStateV2) {
  switch (state.currentPhase) {
    case "formal_runtime": return state.formalRuntime;
    case "program_delivery":
    case "completed": return state.programDelivery;
    case "generation": return state.generation;
    case "selection": return state.selection;
    case "review": return state.review;
    case "collection": return state.collection;
    case "convergence": return state.convergence;
  }
}

function firstEnabledCommand(
  actions: readonly AllowedAction[],
  phase: HypothesisFirstPhase,
  reviewCandidate: ReviewCandidateState | null,
): CommandAction | null {
  const commands = actions.filter((action): action is CommandAction => (
    action.kind === "command" && action.enabled && action.targetPhase === phase
  ));
  if (phase !== "review" || !reviewCandidate) return commands[0] ?? null;
  return commands.find((action) => {
    const payload = action.payload as Record<string, unknown>;
    if (String(payload.meetingRoundId || "") === reviewCandidate.meetingRoundId) {
      return true;
    }
    return Array.isArray(payload.candidateIds)
      && payload.candidateIds.some((candidateId) => String(candidateId) === reviewCandidate.candidateId);
  }) ?? null;
}

function firstReadyNavigation(
  actions: readonly AllowedAction[],
  phase: HypothesisFirstPhase,
  preferredCandidateId?: string | null,
): NavigationAction | null {
  const ready = actions.filter((action): action is NavigationAction => (
    action.kind === "navigation"
    && action.enabled
    && action.targetPhase === phase
    && action.navigation.status === "ready"
    && Boolean(action.navigation.deepLink)
  ));
  if (preferredCandidateId) {
    return ready.find((action) => action.navigation.candidateId === preferredCandidateId) ?? null;
  }
  return ready[0] ?? null;
}

function activeReviewCandidate(
  state: HypothesisFirstStateV2,
  options: ResolveV2Options = {},
): ReviewCandidateState | null {
  const preferred = state.review.candidates.find((candidate) => (
    (options.preferredCandidateId && candidate.candidateId === options.preferredCandidateId)
    || (options.preferredMeetingRoundId && candidate.meetingRoundId === options.preferredMeetingRoundId)
  ));
  if (preferred) return preferred;
  return state.review.candidates.find((candidate) => candidate.lifecycle !== "completed")
    ?? state.review.candidates[0]
    ?? null;
}

function legacyCommand(action: CommandAction | null, phase: HypothesisFirstPhase): HypothesisFirstCommand | undefined {
  if (!action) return undefined;
  switch (action.command) {
    case "open_generation":
    case "retry_generation": return "open_generation";
    case "record_selection": return "record_selection";
    case "regenerate_summary": return "retry_draft_summary";
    case "approve_summary": return phase === "generation"
      ? "approve_generation_digest"
      : "approve_review_digest";
    case "retry_collection": return "retry_collection";
    case "continue_collection": return "continue_collection";
    case "handoff_collection": return "retry_handoff";
    case "open_next_review": return "open_next_review";
    case "human_adjudication": return "human_adjudication";
    case "create_formal_run": return "create_run";
    case "retry_program_handoff": return "retry_program_handoff";
    case "record_program_review": return "record_program_review";
    case "create_formal_revision": return "create_formal_revision";
    case "reconcile_formal_run": return "reconcile_formal_run";
    case "retry_review_dispatch": return "retry_review_dispatch";
    case "resume_discussion":
    case "stop_discussion":
      return undefined;
  }
}

function stageFor(state: HypothesisFirstStateV2): HypothesisFirstStage {
  switch (state.currentPhase) {
    case "generation":
      if (state.generation.lifecycle === "waiting_human") return "generation_awaiting_approval";
      if (state.generation.lifecycle === "queued" || state.generation.lifecycle === "running") {
        return "generation_running";
      }
      if (
        state.generation.lifecycle === "not_started"
        || state.generation.lifecycle === "failed"
        || state.generation.outcome === "empty"
      ) return "generation_missing";
      return "selection_required";
    case "selection": return "selection_required";
    case "review": {
      const candidate = activeReviewCandidate(state);
      if (!candidate || candidate.actionability === "blocked") return "blocked";
      if (candidate.approval.lifecycle === "waiting_human") return "review_awaiting_approval";
      if (candidate.summarization.lifecycle === "running") return "review_summarizing";
      if (candidate.lifecycle === "failed") return "review_summarizing";
      return "review_running";
    }
    case "collection":
      if (state.collection.lifecycle === "waiting_human") return "handoff_pending";
      if (state.collection.lifecycle === "failed" || state.collection.actionability === "blocked") {
        return "collection_recovery";
      }
      return "collecting";
    case "convergence":
      if (state.convergence.outcome === "exhausted") return "budget_exhausted";
      if (state.convergence.accepted) return "converged";
      return state.convergence.lifecycle === "waiting_human" ? "next_review" : "blocked";
    case "formal_runtime":
      return state.formalRuntime.runId ? "converged" : "converged";
    case "program_delivery": return "program_delivery";
    case "completed": return "completed";
  }
}

function defaultStatus(state: HypothesisFirstStateV2): string {
  const problem = state.problems.find((item) => item.severity === "fatal")
    ?? state.problems.find((item) => item.severity === "error")
    ?? state.problems[0];
  if (problem) return problem.message;
  switch (state.currentPhase) {
    case "generation": return state.isInitial ? "可以开始生成候选假说" : "候选生成状态已更新";
    case "selection": return "请选择进入评审的候选假说";
    case "review": return `候选评审 ${state.review.aggregate.completed}/${state.review.aggregate.total}`;
    case "collection": return `资料搜集 ${state.collection.aggregate.completed}/${state.collection.aggregate.total}`;
    case "convergence": return state.convergence.accepted
      ? "假说已经收敛"
      : state.convergence.outcome === "rejected"
        ? "人工已拒绝当前收敛结果"
        : "等待假说收敛";
    case "formal_runtime": return state.formalRuntime.runId ? "正式研究运行进行中" : "可以创建正式研究运行";
    case "program_delivery": return state.programDelivery.humanReviewStatus === "waiting_human"
      ? `等待 H1–H4 审核（${state.programDelivery.approvedGateCount}/4）`
      : "正式研究结果正在交付";
    case "completed": return "挑战杯研究流程已闭环";
  }
}

export function resolveHypothesisFirstNextActionFromV2(
  state: HypothesisFirstStateV2,
  options: ResolveV2Options = {},
): HypothesisFirstNextAction {
  const reviewCandidate = state.currentPhase === "review"
    ? activeReviewCandidate(state, options)
    : null;
  const command = firstEnabledCommand(
    state.allowedActions,
    state.currentPhase,
    reviewCandidate,
  );
  const navigation = firstReadyNavigation(
    state.allowedActions,
    state.currentPhase,
    reviewCandidate?.candidateId,
  );
  const request = state.collection.requests.find((item) => item.lifecycle !== "completed")
    ?? state.collection.requests[0]
    ?? null;
  const current = phaseState(state);
  const mappedCommand = legacyCommand(command, state.currentPhase);
  return {
    stage: stageFor(state),
    targetNodeId: phaseTarget(state, reviewCandidate),
    navigationLabel: navigation?.label || command?.label || "前往当前任务",
    command: mappedCommand,
    commandLabel: command?.label,
    commandDetail: command?.confirmationText || defaultStatus(state),
    disabledReason: current.actionability === "blocked"
      ? current.problems[0]?.message || command?.disabledReason || "当前状态需要修复后才能继续"
      : command && !command.enabled
        ? command.disabledReason || undefined
        : undefined,
    recovery: null,
    statusMessage: defaultStatus(state),
    meetingRoundId: reviewCandidate?.meetingRoundId
      || state.generation.generationMeetingId
      || navigation?.navigation.meetingRoundId
      || undefined,
    collectionRequestId: request?.requestId,
    collectionRunId: request?.childRun.runId || undefined,
    stateSource: "v2_canonical",
    canonicalActionId: command?.actionId,
    canonicalAction: command || undefined,
    canonicalCommand: command?.command,
    expectedStateVersion: command?.expectedStateVersion,
    navigationDeepLink: navigation?.navigation.deepLink || undefined,
  };
}
