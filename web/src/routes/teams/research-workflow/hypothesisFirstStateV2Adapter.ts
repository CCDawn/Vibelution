import type {
  AllowedAction,
  CommandAction,
  HypothesisFirstClaimBeliefGate,
  HypothesisFirstPhase,
  HypothesisFirstStateV2,
  NavigationAction,
  PhaseState,
  ReviewCandidateState,
} from "../../../api/types/hypothesisFirst";
import { parseClaimBeliefGate } from "../../../api/hypothesisFirst";
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
  /** Copy language for synthesized status/detail text; server-authored labels stay verbatim. */
  lang?: "zh" | "en";
};

/** V2-only extension kept local so legacy next-action consumers remain stable. */
export type HypothesisFirstV2NextAction = HypothesisFirstNextAction & {
  canonicalActions?: readonly CommandAction[];
  /** Server claim belief hard gate verdict parsed from the convergence payload. */
  claimGate?: HypothesisFirstClaimBeliefGate | null;
};

/** zh explanation for a gate-blocked convergence; the raw reason stays visible for unmapped codes. */
function claimGateBlockedCopy(gate: HypothesisFirstClaimBeliefGate): string {
  return `收敛被 claim 证据门拦截（${gate.reason || "原因未知"}）；入选候选的 claim 证据不足或存在反证，需先补齐证据再继续。`;
}

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

export type HypothesisFirstSelectionProjection = {
  /** `editable` is the only state in which a new selection may be submitted. */
  status: "editable" | "committed" | "locked";
  locked: boolean;
  selectedCandidateIds: string[];
  selectionId: string | null;
  lockReason: string | null;
  canonicalAction?: Extract<CommandAction, { command: "record_selection" }>;
};

export type HypothesisFirstSelectionProjectionInput = {
  /** The one server-authored V2 snapshot for this question. */
  state?: HypothesisFirstStateV2 | null;
  /** Optional envelope form used by adapters that may observe zero/many states. */
  states?: readonly HypothesisFirstStateV2[] | null;
  loading?: boolean;
  error?: unknown;
  /** Explicit count lets a caller fail closed when its source is ambiguous. */
  stateCount?: number | null;
  expectedTeamId?: string | null;
  expectedQuestionId?: string | null;
};

function lockedSelectionProjection(
  reason: string,
  selectedCandidateIds: string[] = [],
  selectionId: string | null = null,
  status: "committed" | "locked" = "locked",
): HypothesisFirstSelectionProjection {
  return {
    status,
    locked: true,
    selectedCandidateIds,
    selectionId,
    lockReason: reason,
  };
}

function reviewHasFacts(state: HypothesisFirstStateV2): boolean {
  const aggregate = state.review?.aggregate;
  return Boolean(
    state.review?.candidates?.length
    || (aggregate && [aggregate.total, aggregate.completed, aggregate.pending, aggregate.failed, aggregate.blocked]
      .some((value) => Number(value) > 0))
    || state.review?.lifecycle !== "not_started"
    || state.review?.outcome !== "none"
    || state.review?.actionability !== "idle",
  );
}

/**
 * Project the only mutation-safe selection state from the canonical V2 read.
 *
 * Selection context is a candidate/detail read model, not proof that a new
 * selection is still writable.  Once the V2 snapshot contains a selection or
 * any review fact, this helper returns the committed IDs and locks mutation;
 * loading, failed, ambiguous, stale, or malformed snapshots also fail closed.
 */
export function projectHypothesisFirstSelection(
  input: HypothesisFirstSelectionProjectionInput,
): HypothesisFirstSelectionProjection {
  if (input.loading) return lockedSelectionProjection("state_loading");
  if (input.error !== undefined && input.error !== null) {
    return lockedSelectionProjection("state_error");
  }

  const states = input.states;
  if (states && states.length !== 1) return lockedSelectionProjection("state_not_unique");
  if (input.stateCount != null && input.stateCount !== 1) {
    return lockedSelectionProjection("state_not_unique");
  }
  const state = states ? states[0] : input.state;
  if (!state) return lockedSelectionProjection("state_unavailable");

  if (
    (input.expectedTeamId && state.teamId.trim() !== input.expectedTeamId.trim())
    || (input.expectedQuestionId
      && state.questionId.trim().toUpperCase() !== input.expectedQuestionId.trim().toUpperCase())
  ) {
    return lockedSelectionProjection("state_scope_mismatch");
  }

  const selectedCandidateIds = Array.isArray(state.selection?.selectedCandidateIds)
    ? state.selection.selectedCandidateIds.map((candidateId) => String(candidateId))
    : [];
  const selectionId = String(state.selection?.selectionId || "").trim() || null;
  const hasDuplicateSelectionId = new Set(selectedCandidateIds).size !== selectedCandidateIds.length;
  if (hasDuplicateSelectionId) {
    return lockedSelectionProjection("state_not_unique", selectedCandidateIds, selectionId);
  }

  if (selectionId || selectedCandidateIds.length > 0) {
    return lockedSelectionProjection("selection_committed", selectedCandidateIds, selectionId, "committed");
  }
  if (reviewHasFacts(state)) return lockedSelectionProjection("review_has_facts");
  if (state.currentPhase !== "selection") return lockedSelectionProjection("selection_not_current");

  const recordSelectionActions = (state.allowedActions ?? []).filter(
    (action): action is Extract<CommandAction, { command: "record_selection" }> => (
      action.kind === "command"
      && action.command === "record_selection"
      && action.enabled
      && action.targetPhase === "selection"
    ),
  );
  if (recordSelectionActions.length !== 1) {
    return lockedSelectionProjection(
      recordSelectionActions.length === 0 ? "record_selection_unavailable" : "state_not_unique",
    );
  }

  return {
    status: "editable",
    locked: false,
    selectedCandidateIds,
    selectionId,
    lockReason: null,
    canonicalAction: recordSelectionActions[0],
  };
}

function commandActionsForPhase(
  actions: readonly AllowedAction[],
  phase: HypothesisFirstPhase,
  reviewCandidate: ReviewCandidateState | null,
): CommandAction[] {
  const commands = actions.filter((action): action is CommandAction => (
    action.kind === "command" && action.targetPhase === phase
  ));
  if (phase !== "review" || !reviewCandidate) return commands;
  return commands.filter((action) => {
    const payload = action.payload as Record<string, unknown>;
    if (String(payload.meetingRoundId || "") === reviewCandidate.meetingRoundId) {
      return true;
    }
    if (Array.isArray(payload.candidateIds)
      && payload.candidateIds.some((candidateId) => String(candidateId) === reviewCandidate.candidateId)) {
      return true;
    }
    return action.targetNodeId === reviewNodeId(reviewCandidate);
  });
}

function firstEnabledCommand(
  actions: readonly AllowedAction[],
  phase: HypothesisFirstPhase,
  reviewCandidate: ReviewCandidateState | null,
): CommandAction | null {
  const commands = commandActionsForPhase(actions, phase, reviewCandidate);
  if (phase === "generation") {
    const regenerateSummary = commands.find((action) => (
      action.enabled && action.command === "regenerate_summary"
    ));
    if (regenerateSummary) return regenerateSummary;
  }
  if (phase === "review" && reviewCandidate) {
    const summaryFailed = reviewCandidate.problems.some((problem) => problem.code === "summary_draft_failed");
    if (summaryFailed) {
      const regenerateSummary = commands.find((action) => (
        action.enabled
        && action.command === "regenerate_summary"
        && String((action.payload as Record<string, unknown>).meetingRoundId || "") === reviewCandidate.meetingRoundId
      ));
      if (regenerateSummary) return regenerateSummary;
    }
  }
  return commands.find((action) => action.enabled) ?? null;
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

/**
 * Map a V2 canonical command to the legacy command name, when one exists.
 *
 * `stop_collection` / `cancel_run` / `archive_run` are V2-only commands with
 * no legacy endpoint: they must stay `undefined` here and be dispatched by the
 * button layer through `executeHypothesisFirstCommand(nextAction.canonicalAction)`.
 * Every other button datum (commandLabel / commandDetail / targetNodeId /
 * canonicalAction) is emitted from the canonical action regardless, so a
 * missing legacy mapping never drops the primary button data.
 */
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
    case "retry_formal_node": return "retry_formal_node";
    case "reconcile_formal_run": return "reconcile_formal_run";
    case "retry_review_dispatch": return "retry_review_dispatch";
    case "reopen_review": return "reopen_review";
    case "resume_discussion": return "resume_discussion";
    case "stop_discussion": return "stop_discussion";
    case "stop_collection":
    case "cancel_run":
    case "archive_run": return undefined;
  }
  // Compile-time guard: every backend ActionCommand must be handled above —
  // either mapped to a legacy command or deliberately left canonical-only.
  // Once the switch is exhaustive, control flow narrows `action` to `never`
  // and this line compiles; a newly added backend command keeps it reachable
  // and fails `tsc -b` here instead of silently losing the primary button
  // (the P2-9 failure mode).
  const unmapped: never = action;
  return unmapped;
}

function stageFor(
  state: HypothesisFirstStateV2,
  reviewCandidate: ReviewCandidateState | null = null,
  summaryRecovery: CommandAction | null = null,
): HypothesisFirstStage {
  if (state.currentPhase === "generation" && summaryRecovery?.command === "regenerate_summary") {
    return "generation_summarizing";
  }
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
      const candidate = reviewCandidate ?? activeReviewCandidate(state);
      if (!candidate || candidate.actionability === "blocked") return "blocked";
      if (candidate.approval.lifecycle === "waiting_human") return "review_awaiting_approval";
      if (candidate.lifecycle === "failed") return "blocked";
      if (candidate.summarization.lifecycle === "running") return "review_summarizing";
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
      if (state.formalRuntime.actionability === "blocked") return "blocked";
      if (["failed", "cancelled", "reconciliation_required"].includes(String(state.formalRuntime.runStatus))) {
        return "blocked";
      }
      return "converged";
    case "program_delivery": return "program_delivery";
    case "completed": return "completed";
  }
}

function defaultStatus(
  state: HypothesisFirstStateV2,
  current: PhaseState = phaseState(state),
  lang: "zh" | "en" = "zh",
): string {
  const problem = state.problems.find((item) => item.severity === "fatal")
    ?? (
      current.actionability === "blocked" || current.lifecycle === "failed"
        ? current.problems[0]
          ?? state.problems.find((item) => item.severity === "error")
          ?? state.problems[0]
        : undefined
    );
  if (problem) return problem.message;
  switch (state.currentPhase) {
    case "generation": return state.isInitial ? "可以开始生成候选假说" : "候选生成状态已更新";
    case "selection": return "请选择进入评审的候选假说";
    case "review": return `本轮候选评审：已完成 ${state.review.aggregate.completed}/${state.review.aggregate.total}`;
    case "collection": return `资料搜集 ${state.collection.aggregate.completed}/${state.collection.aggregate.total}`;
    case "convergence": return state.convergence.accepted
      ? "假说已经收敛"
      : state.convergence.outcome === "rejected"
        ? "人工已拒绝当前收敛结果"
        : "等待假说收敛";
    case "formal_runtime": return state.formalRuntime.runId ? "正式研究运行进行中" : "可以创建正式研究运行";
    case "program_delivery": {
      // P2-10: a rejected or revision-requested human review is the opposite
      // of "delivering" — say so instead of the generic delivery copy.
      const reviewStatus = state.programDelivery.humanReviewStatus;
      const zh = lang !== "en";
      if (reviewStatus === "waiting_human") {
        return zh
          ? `等待 H1–H4 审核（${state.programDelivery.approvedGateCount}/4）`
          : `Waiting for H1–H4 review (${state.programDelivery.approvedGateCount}/4)`;
      }
      if (reviewStatus === "rejected") {
        return zh
          ? "正式研究产出已被人工驳回"
          : "The formal research output was rejected by human review";
      }
      if (reviewStatus === "revision_requested") {
        return zh
          ? "正式研究产出需要修订（已创建修订流程或等待修订）"
          : "The formal research output needs revision (a revision run was created or is pending)";
      }
      return zh ? "正式研究结果正在交付" : "The formal research output is being delivered";
    }
    case "completed": return "挑战杯研究流程已闭环";
  }
}

export function resolveHypothesisFirstNextActionFromV2(
  state: HypothesisFirstStateV2,
  options: ResolveV2Options = {},
): HypothesisFirstV2NextAction {
  const reviewCandidate = state.currentPhase === "review"
    ? activeReviewCandidate(state, options)
    : null;
  const command = firstEnabledCommand(
    state.allowedActions,
    state.currentPhase,
    reviewCandidate,
  );
  const canonicalActions = commandActionsForPhase(
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
  const current = state.currentPhase === "review" && reviewCandidate
    ? reviewCandidate
    : phaseState(state);
  const mappedCommand = legacyCommand(command, state.currentPhase);
  // R2.2 claim belief hard gate: when a structurally converged round is held
  // back by the server gate, the guidance copy explains the block while the
  // server-authored allowedActions stay the only button authority (nothing is
  // hidden, disabled, or re-labeled here).
  const claimGate = parseClaimBeliefGate(state.convergence?.claimBeliefGate);
  const gateCopy = claimGate?.status === "blocked" ? claimGateBlockedCopy(claimGate) : null;
  return {
    stage: stageFor(state, reviewCandidate, command),
    targetNodeId: phaseTarget(state, reviewCandidate),
    navigationLabel: navigation?.label || command?.label || canonicalActions[0]?.label || "前往当前任务",
    command: mappedCommand,
    commandLabel: command?.label,
    commandDetail: command?.confirmationText || gateCopy || defaultStatus(state, current, options.lang),
    disabledReason: command
      ? undefined
      : current.actionability === "blocked"
        ? current.problems[0]?.message || "当前状态需要修复后才能继续"
        : undefined,
    recovery: null,
    statusMessage: gateCopy || defaultStatus(state, current, options.lang),
    meetingRoundId: reviewCandidate?.meetingRoundId
      || state.generation.generationMeetingId
      || navigation?.navigation.meetingRoundId
      || undefined,
    collectionRequestId: request?.requestId,
    collectionRunId: request?.childRun.runId || undefined,
    stateSource: "v2_canonical",
    claimGate,
    canonicalActionId: command?.actionId,
    canonicalAction: command || undefined,
    canonicalActions,
    canonicalCommand: command?.command,
    expectedStateVersion: command?.expectedStateVersion,
    navigationDeepLink: navigation?.navigation.deepLink || undefined,
  };
}
