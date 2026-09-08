import type { PhaseState, HypothesisFirstStateV2, CommandAction } from "../../../api/types/hypothesisFirst";
import { HYPOTHESIS_FIRST_SELECTION_NODE_ID } from "./hypothesisFirstCanvasRegion";

const idle: PhaseState = {
  lifecycle: "not_started",
  outcome: "none",
  actionability: "idle",
  attempt: null,
  updatedAt: null,
  problems: [],
};

export function stateV2(overrides: Record<string, any> = {}): HypothesisFirstStateV2 {
  const base: HypothesisFirstStateV2 = {
    schemaVersion: 2,
    contract: "hypothesis-first-state/v2",
    teamId: "team-1",
    questionId: "Q-01",
    stateVersion: "state-1",
    representationVersion: "repr-1",
    computedAt: "2026-08-25T00:00:00Z",
    scope: { workflowRunId: null, questionInOfficialCatalog: true, catalogId: "challenge-cup", catalogSha256: "sha" },
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
    convergence: { ...idle, claimBeliefGate: null, latestHypothesisRoundId: null, accepted: false, roundIndex: 0, roundBudget: 5 },
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
  };
  return {
    ...base, ...overrides,
    ...Object.fromEntries(["scope", "overall", "generation", "selection", "review", "collection", "convergence", "formalRuntime", "programDelivery"].map((key) => [key, { ...base[key as keyof HypothesisFirstStateV2] as object, ...overrides[key] }])),
  };
}

export function command(
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
    targetNodeId: action.command === "record_selection"
      ? HYPOTHESIS_FIRST_SELECTION_NODE_ID
      : null,
    payload: action.payload,
    inputSchemaRef: null,
    idempotencyKey: `idem:${action.command}`,
    expectedStateVersion: "state-1",
    requiresConfirmation: false,
    confirmationText: null,
  } as CommandAction;
}


export function reviewState(meetingRoundId = "meeting-1", roundIndex = 1) {
  const phase = { ...idle, lifecycle: "running", actionability: "executing" };
  return stateV2({currentPhase: "review", generation: {candidateCount: 1}, selection: {selectionId: "selection-1", selectedCandidateIds: ["candidate-1"]}, review: {
    ...phase, activeRoundIndex: roundIndex,
    aggregate: {total: 1, completed: 0, pending: 1, failed: 0, blocked: 0},
    candidates: [{...phase, candidateId: "candidate-1", candidateOrder: 1, selectionId: "selection-1", roundIndex, meetingRoundId, discussionAnchor: null, discussion: phase, summarization: idle, approval: idle}],
  }});
}
