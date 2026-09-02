/**
 * Hypothesis-first flow DTOs (HF-5).
 *
 * Mirrors the backend route DTOs in
 * `core/web/routes/team_workflows/hypothesis_first_models.py` and the service
 * record shapes from `core/web/services/team_workflow/`. Completion state is
 * always a server-side projection — the UI must not infer it locally.
 */

import type { ChallengeQuestionHypothesis } from "./teams";

// ---------------------------------------------------------------------------
// Shared scope
// ---------------------------------------------------------------------------

export type HypothesisFirstScope = {
  program: string;
  theme: string;
  campaign: string;
  question: string;
  branch: string;
  workflow: string;
  agentId: string;
  workflowRunId?: string;
};

// ---------------------------------------------------------------------------
// Selection (HF-1)
// ---------------------------------------------------------------------------

export type HypothesisSelectionRecord = HypothesisFirstScope & {
  schemaVersion: number;
  selectionId: string;
  selectionHash: string;
  mode: string;
  scopeHash: string;
  questionId: string;
  selectedCandidateIds: string[];
  previousSelectionId: string;
  decidedBy: string;
  createdAt: string;
};

export type HypothesisSelectionRecordPayload = HypothesisFirstScope & {
  mode: string;
  questionId: string;
  selectedCandidateIds: string[];
  previousSelectionId?: string;
  decidedBy: string;
  createdAt?: string;
  selectionId?: string;
};

export type HypothesisSelectionRecordResponse = {
  schemaVersion: number;
  teamId: string;
  status: string;
  selection: HypothesisSelectionRecord;
  reviewMeeting?: MeetingRoundRecord | null;
  storagePath?: string;
};

export type HypothesisSelectionGetResponse = {
  schemaVersion: number;
  teamId: string;
  selection: HypothesisSelectionRecord;
  storagePath?: string;
};

export type HypothesisSelectionListResponse = {
  schemaVersion: number;
  teamId: string;
  selectionCount: number;
  selections: HypothesisSelectionRecord[];
  storagePath?: string;
};

export type CandidateEvidenceEntry = {
  meetingRoundId: string;
  meetingLabel: string;
  messageId: string;
  speaker: string;
  excerpt: string;
  createdAt: string;
};

export type CandidateEvidenceTrail = {
  candidateId: string;
  entries: CandidateEvidenceEntry[];
};

export type CandidateEvidenceTrailResponse = {
  schemaVersion: number;
  teamId: string;
  questionId: string;
  workflowRunId?: string;
  trails: CandidateEvidenceTrail[];
  storagePath?: string;
};

export type HypothesisSelectionContext = {
  schemaVersion: number;
  teamId: string;
  questionId: string;
  workflowRunId: string;
  scope: HypothesisFirstScope;
  mode: string;
  candidates: ChallengeQuestionHypothesis[];
  defaultSelectedCandidateIds: string[];
  latestSelection: HypothesisSelectionRecord | null;
  reviewMeeting?: MeetingRoundRecord | null;
  generationMeeting?: MeetingRoundRecord | null;
};

// ---------------------------------------------------------------------------
// Meeting rounds (HF-2)
// ---------------------------------------------------------------------------

export type MeetingRoundStatus =
  | "open"
  | "summarizing"
  | "awaiting_approval"
  | "closed"
  | (string & {});

export type MeetingProposedCandidate = {
  candidateId: string;
  statement: string;
  rationale?: string;
  proposedBy?: string;
};

export type MeetingSearchEnvelope = {
  keywords?: string[];
  sourceTypes?: string[];
  evidenceLevels?: string[];
};

/** Server-authored structured digest validation error (HF digest contract). */
export type MeetingDigestValidationError = {
  code: string;
  message: string;
};

/** Server-authored typed evidence request on a review digest (HF digest contract). */
export type MeetingEvidenceRequestDraft = {
  rationale?: string;
  candidateRefs?: string[];
  evidenceRefs?: string[];
  searchEnvelope?: MeetingSearchEnvelope | null;
  requirements?: Record<string, unknown>;
  writebackPolicy?: Record<string, unknown> | null;
};

export type MeetingDigestDraft = {
  summary: string;
  discussionTopics?: string[];
  agendaSummary?: string;
  agreements?: Array<string | Record<string, unknown>>;
  disagreements?: Array<Record<string, unknown>>;
  actionItems?: Array<Record<string, unknown>>;
  risks?: string[];
  blockers?: string[];
  knowledgeCandidates?: string[];
  sourceMessageRefs?: string[];
  contentHash?: string;
  proposedCandidates?: MeetingProposedCandidate[];
  evidenceRequests?: MeetingEvidenceRequestDraft[];
  validationErrors?: MeetingDigestValidationError[];
};

export type MeetingRoundRecord = HypothesisFirstScope & {
  schemaVersion?: number;
  meetingRoundId: string;
  meetingType: string;
  mode: string;
  scopeHash: string;
  participants: string[];
  discussionItemRefs?: string[];
  status: MeetingRoundStatus;
  startedAt: string;
  closedAt?: string;
  closedBy?: string;
  stage?: string;
  roundType?: string;
  agenda?: string[];
  agendaQuestions?: string[];
  agendaRules?: string[];
  rounds?: number;
  participantRoleIds?: string[];
  inputArtifactRefs?: string[];
  linkedChatRoomId?: string;
  chatRoomRoundIds?: string[];
  digestDraft?: MeetingDigestDraft | null;
  decisionRefs?: string[];
  /** Ledger field for the closed meeting digest; `digestRef` never existed server-side. */
  digestId?: string;
  /** @deprecated legacy frontend-only name; kept only so old snapshots still parse. */
  digestRef?: string;
  closureHash?: string;
  roundIndex?: number;
  previousMeetingRoundId?: string;
  selectionId?: string;
  summarizedBy?: string;
  summaryStartedAt?: string;
  summaryHumanTriggered?: boolean;
  summaryError?: string;
  summaryDraftError?: {
    code?: string;
    message?: string;
    remediationLabel?: string;
  };
  recoveryReason?: string;
  boundChatRoundsTerminal?: boolean;
  draftRejectedBy?: string;
  draftRejectedReason?: string;
  updatedAt?: string;
  /** Server-authored discussion scope; formal candidate meetings carry candidateId here. */
  discussionScope?: Record<string, unknown>;
};

export type MeetingRoundListResponse = {
  schemaVersion: number;
  teamId: string;
  meetingCount: number;
  meetings: MeetingRoundRecord[];
  storagePath?: string;
};

export type MeetingRoundGetResponse = {
  schemaVersion: number;
  teamId: string;
  meetingRound: MeetingRoundRecord;
  storagePath?: string;
};

/**
 * One evidence request dropped while closing a review meeting; reported in
 * the close result's `collection.skipped` so the UI can surface the cause
 * instead of silently leaving the request pending.
 */
export type MeetingCollectionSkippedItem = {
  decisionId: string;
  reason: string;
  error?: string;
};

/**
 * Why a summary-draft prepare was blocked (discussion still running / no
 * completed statements); mirrors the blocker object built by
 * `prepare_meeting_summary_draft` in the meeting runtime.
 */
export type MeetingSummaryBlocker = {
  code?: string;
  message?: string;
  remediationLabel?: string;
  runningRoundIds?: string[];
};

export type MeetingRoundMutationResponse = {
  schemaVersion: number;
  teamId: string;
  status: string;
  meetingRound: MeetingRoundRecord;
  digestDraft?: MeetingDigestDraft | null;
  /**
   * Present when the prepare-draft state machine returns
   * `{status:"blocked", blocker}` instead of starting a summary; the UI must
   * surface it rather than treat the mutation as a silent no-op.
   */
  blocker?: MeetingSummaryBlocker;
  /** Present when a close reports dropped evidence requests. */
  collection?: {
    skipped?: MeetingCollectionSkippedItem[];
  };
  storagePath?: string;
};

export type MeetingSourceMessage = {
  messageId?: string;
  agentId?: string;
  role?: string;
  /** Human-facing identity from the room (e.g. 「A014 · 科研协调」). */
  speakerTitle?: string;
  content?: string;
  createdAt?: string;
  roomId?: string;
  roundId?: string;
  status?: string;
} & Record<string, unknown>;

export type MeetingSourceMessagesResponse = {
  schemaVersion: number;
  teamId: string;
  meetingRoundId: string;
  messageCount: number;
  messages: MeetingSourceMessage[];
};

export type MeetingDecisionInput = {
  decision: string;
  rationale: string;
  decidedBy: string;
  candidateRefs?: string[];
  evidenceRefs?: string[];
  status?: string;
  searchEnvelope?: Record<string, unknown> | null;
  requirements?: Record<string, unknown>;
  writebackPolicy?: Record<string, unknown> | null;
};

export type MeetingSummaryDraftRequest = {
  actor: string;
  force: false;
};

export type MeetingApproveDigestRequest = {
  closedBy: string;
  expectedDigestContentHash: string;
};

export type MeetingClosureApprovePayload = {
  decisions: MeetingDecisionInput[];
  closedBy?: string;
};

// ---------------------------------------------------------------------------
// Hypothesis rounds (HF-3)
// ---------------------------------------------------------------------------

/**
 * One seven-dimension audit review row attached to a round candidate
 * (extension field; DEV fixture rounds may omit it entirely). Dimensions use
 * the canonical `REQUIRED_REVIEW_DIMENSIONS` snake_case keys.
 */
export type HypothesisCandidateDimensionReview = {
  dimension: string;
  rating: "insufficient" | "weak" | "mixed" | "adequate" | "strong" | (string & {});
  rationale: string;
  evidence_refs: string[];
  reviewer: string;
};

export type HypothesisRoundCandidate = {
  candidateId: string;
  claim: string;
  rationale: string;
  differenceFromAlternatives: string;
  lineageRefs: string[];
  scores: Record<string, number>;
  /** Auxiliary diagnostics (replicability, scopeAlignment); optional. */
  diagnostics?: Record<string, number>;
  /** Seven-dimension audit review rows; optional extension field. */
  dimensionReviews?: HypothesisCandidateDimensionReview[];
  reviewedBy: string;
  status: string;
};

export type HypothesisPairwiseComparison = {
  comparisonId: string;
  leftCandidateId: string;
  rightCandidateId: string;
  reviewerAgentId: string;
  outcome: string;
  justification: string;
};

export type HypothesisParetoAnalysis = {
  paretoFrontCandidateIds: string[];
  dominatedCandidateIds: string[];
  analystAgentId: string;
  notes: string;
};

export type HypothesisMetaReview = {
  metaReviewId: string;
  reviewerAgentId: string;
  recommendationCandidateId: string;
  rationale: string;
  riskNotes: string;
  accepted: boolean;
};

export type HypothesisLineageRef = {
  kind: string;
  id: string;
};

export type HypothesisMeetingRef = {
  kind: string;
  id: string;
};

export type HypothesisRoundRecord = HypothesisFirstScope & {
  roundId: string;
  mode: string;
  scopeHash: string;
  status: string;
  candidates: HypothesisRoundCandidate[];
  pairwiseComparisons: HypothesisPairwiseComparison[];
  pareto: HypothesisParetoAnalysis;
  metaReview: HypothesisMetaReview;
  lineage: HypothesisLineageRef[];
  meetingRefs: HypothesisMeetingRef[];
  createdAt: string;
  closedAt?: string;
  closedBy?: string;
};

export type HypothesisRoundListResponse = {
  schemaVersion: number;
  teamId: string;
  roundCount: number;
  rounds: HypothesisRoundRecord[];
  /** Ledger lines quarantined during the list projection (fail-closed marker). */
  corruptQuarantinedLineCount?: number;
  storagePath?: string;
};

export type HypothesisRoundGetResponse = {
  schemaVersion: number;
  teamId: string;
  round: HypothesisRoundRecord;
  storagePath?: string;
};

// ---------------------------------------------------------------------------
// Hypothesis-first chain (HF-4)
// ---------------------------------------------------------------------------

export type CollectionRequestRecord = HypothesisFirstScope & {
  schemaVersion: number;
  recordKind: string;
  requestId: string;
  requestHash: string;
  status: string;
  meetingRoundId: string;
  decisionId: string;
  questionId: string;
  mode: string;
  scopeHash: string;
  searchEnvelope: Record<string, unknown>;
  requirements: Record<string, unknown>;
  writebackPolicy: Record<string, unknown>;
  collectionRunId: string;
  collectionRunStatus?: string;
  startError?: {
    code: string;
    message: string;
  };
  createdAt: string;
  handedOffAt?: string;
  handoffRef?: string;
};

export type ReviewRoundLinkRecord = {
  schemaVersion: number;
  recordKind: string;
  linkId: string;
  meetingRoundId: string;
  previousMeetingRoundId: string;
  selectionId: string;
  collectionRequestId: string;
  questionId: string;
  roundIndex: number;
  /** Candidate-specific review lineage. Older records may omit it; UI treats
   * a missing value on a linked review as unresolved rather than guessing. */
  candidateId?: string;
  /** Zero-based server-authored position within a parallel candidate review round. */
  candidateOrder?: number | null;
  roundBudget?: number;
  createdAt: string;
};

export type HypothesisFirstChainState = {
  schemaVersion: number;
  teamId: string;
  questionId: string;
  selectionId: string;
  meetingCount: number;
  firstMeetingId: string;
  firstMeetingClosed: boolean;
  openMeetingIds: string[];
  collectionRequests: CollectionRequestRecord[];
  collectionRequestCount: number;
  pendingCollectionCount: number;
  collectionReady: boolean;
  hypothesisRoundCount: number;
  latestHypothesisRoundId: string;
  hypothesisConverged: boolean;
  convergenceDetail: string;
  /** R2.2 claim belief hard gate verdict; null while not structurally converged. */
  claimBeliefGate?: HypothesisFirstClaimBeliefGate | null;
  roundBudget: number;
  budgetExhausted: boolean;
  templateBaselineExists: boolean;
  templateBaselineIds: string[];
  candidateCount?: number;
  generationMeetingId?: string;
  generationMeetingStatus?: string;
};

// ---------------------------------------------------------------------------
// Canonical workflow state V2
// ---------------------------------------------------------------------------

export type WorkflowLifecycle =
  | "not_started"
  | "queued"
  | "running"
  | "waiting_human"
  | "completed"
  | "failed"
  | "cancelled"
  | "superseded";

export type WorkflowOutcome =
  | "none"
  | "succeeded"
  | "empty"
  | "partial"
  | "rejected"
  | "exhausted";

export type WorkflowActionability =
  | "idle"
  | "available"
  | "executing"
  | "waiting_user"
  | "waiting_system"
  | "blocked"
  | "terminal";

export type HypothesisFirstPhase =
  | "generation"
  | "selection"
  | "review"
  | "collection"
  | "convergence"
  | "formal_runtime"
  | "program_delivery"
  | "completed";

export type WorkflowProblem = {
  code: string;
  category: "validation" | "execution" | "integrity" | "dependency" | "stale";
  severity: "info" | "warning" | "error" | "fatal";
  message: string;
  recoverable: boolean;
  sourceKind: string;
  sourceId: string | null;
  detectedAt: string;
};

export type WorkflowAttempt = {
  attemptId: string;
  number: number;
  lifecycle: WorkflowLifecycle;
  queuedAt: string | null;
  startedAt: string | null;
  heartbeatAt: string | null;
  finishedAt: string | null;
  supersedesAttemptId: string | null;
};

export type PhaseState = {
  lifecycle: WorkflowLifecycle;
  outcome: WorkflowOutcome;
  actionability: WorkflowActionability;
  attempt: WorkflowAttempt | null;
  updatedAt: string | null;
  problems: WorkflowProblem[];
};

export type ActionCommand =
  | "open_generation"
  | "retry_generation"
  | "record_selection"
  | "retry_review_dispatch"
  | "reopen_review"
  | "resume_discussion"
  | "stop_discussion"
  | "regenerate_summary"
  | "approve_summary"
  | "retry_collection"
  | "continue_collection"
  | "stop_collection"
  | "handoff_collection"
  | "open_next_review"
  | "human_adjudication"
  | "create_formal_run"
  | "retry_formal_node"
  | "reconcile_formal_run"
  | "cancel_run"
  | "archive_run"
  | "retry_program_handoff"
  | "record_program_review"
  | "create_formal_revision";

export type ActionPayloadByCommand = {
  open_generation: { questionId: string };
  retry_generation: { questionId: string; previousAttemptId: string };
  record_selection: { questionId: string; generationAttemptId: string };
  retry_review_dispatch: { selectionId: string; candidateIds: string[] };
  reopen_review: { meetingRoundId: string };
  resume_discussion: { meetingRoundId: string };
  stop_discussion: { meetingRoundId: string };
  regenerate_summary: { meetingRoundId: string };
  approve_summary: { meetingRoundId: string };
  retry_collection: { requestId: string; childRunId: string | null };
  continue_collection: { requestId: string; childRunId: string };
  stop_collection: { requestId: string; childRunId: string };
  handoff_collection: { requestId: string; childRunId: string };
  open_next_review: { previousMeetingRoundId: string; roundBudget: number };
  human_adjudication: { hypothesisRoundId: string };
  create_formal_run: { questionId: string; hypothesisRoundId: string };
  retry_formal_node: { runId: string; nodeId: string };
  reconcile_formal_run: { runId: string };
  cancel_run: { runId: string };
  archive_run: { runId: string };
  retry_program_handoff: { runId: string; deliveryArtifactRef: string | null };
  record_program_review: { questionId: string; outputRunId: string };
  create_formal_revision: { runId: string; outputRecordId: string };
};

export type ProgramHumanGateKey =
  | "H1_problem_understanding"
  | "H2_hypothesis_selection"
  | "H3_research_plan"
  | "H4_external_output";

export type ProgramHumanGateDecision =
  | "pending"
  | "approved"
  | "revision_requested"
  | "rejected";

export type ActionInputByCommand = {
  record_selection: { candidateIds: string[] };
  approve_summary: { decision: "accepted" | "rejected" | "revised" };
  human_adjudication: { decision: string; rationale: string };
  record_program_review: {
    reviewer: string;
    rationale: string;
    decisions: Record<
      ProgramHumanGateKey,
      Exclude<ProgramHumanGateDecision, "pending">
    >;
  };
};

export type ActionCommon = {
  actionId: string;
  label: string;
  enabled: boolean;
  disabledReason: string | null;
  targetPhase: HypothesisFirstPhase;
  targetNodeId: string | null;
};

export type CommandAction = {
  [C in ActionCommand]: ActionCommon & {
    kind: "command";
    command: C;
    payload: ActionPayloadByCommand[C];
    inputSchemaRef: string | null;
    idempotencyKey: string;
    expectedStateVersion: string;
    requiresConfirmation: boolean;
    confirmationText: string | null;
  };
}[ActionCommand];

export type WorkflowNavigationAnchor = {
  status: "ready" | "degraded";
  degradedReason: string | null;
  roomId: string | null;
  meetingRoundId: string | null;
  questionId: string;
  selectionId: string | null;
  candidateId: string | null;
  deepLink: string | null;
  returnTo: string;
  returnLabel: string;
};

export type NavigationAction = ActionCommon & {
  kind: "navigation";
  navigation: WorkflowNavigationAnchor;
};

export type AllowedAction = CommandAction | NavigationAction;

export type CommandRequest<C extends ActionCommand> = {
  actionId: string;
  idempotencyKey: string;
  expectedStateVersion: string;
  payload: ActionPayloadByCommand[C];
} & (C extends keyof ActionInputByCommand
  ? { input: ActionInputByCommand[C] }
  : { input?: never });

export type ReviewCandidateState = PhaseState & {
  candidateId: string;
  candidateOrder: number;
  selectionId: string;
  roundIndex: number;
  meetingRoundId: string | null;
  discussionAnchor: WorkflowNavigationAnchor | null;
  discussion: PhaseState;
  summarization: PhaseState;
  approval: PhaseState;
};

export type CollectionSourceState = PhaseState & {
  sourceId: string;
  label: string;
  itemCount: number;
  error: WorkflowProblem | null;
};

export type CollectionRequestState = PhaseState & {
  requestId: string;
  queryCount: number;
  childRun: PhaseState & { runId: string | null };
  sources: CollectionSourceState[];
  handoff: PhaseState & {
    handoffId: string | null;
    targetRoundIndex: number | null;
  };
};

export type FormalRunViewStatus =
  | "queued"
  | "running"
  | "waiting_human"
  | "blocked"
  | "reconciliation_required"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "archived";

export type FormalRunLineageDisposition =
  | "current"
  | "branched_parent"
  | "historical"
  | "conflicted";

export type ProgramDeliveryStatus =
  | "not_started"
  | "queued"
  | "running"
  | "blocked"
  | "succeeded"
  | "failed";

export type ProgramCandidateHandoffStatus =
  | "not_started"
  | "needs_context"
  | "registered"
  | "idempotent"
  | "failed";

export type ProgramHumanReviewStatus =
  | "not_started"
  | "waiting_human"
  | "revision_requested"
  | "rejected"
  | "approved";

export type ProgramHumanGateState = {
  decisions: Record<ProgramHumanGateKey, ProgramHumanGateDecision>;
  reviewer: string | null;
  rationale: string | null;
  decidedAt: string | null;
};

export type HypothesisFirstStateV2 = {
  schemaVersion: 2;
  contract: "hypothesis-first-state/v2";
  teamId: string;
  questionId: string;
  stateVersion: string;
  representationVersion: string;
  computedAt: string;
  scope: {
    questionInOfficialCatalog: true;
    catalogId: string;
    catalogSha256: string;
    workflowRunId: string | null;
  };
  resetBoundary: {
    resetId: string;
    resetAt: string | null;
    source: "question_reset_audit" | "origin";
  };
  isInitial: boolean;
  awaitingHumanCount: number;
  currentPhase: HypothesisFirstPhase;
  overall: PhaseState;
  generation: PhaseState & {
    generationMeetingId: string | null;
    candidateCount: number;
    candidateIds: string[];
  };
  selection: PhaseState & {
    selectionId: string | null;
    selectedCandidateIds: string[];
  };
  review: PhaseState & {
    activeRoundIndex: number | null;
    aggregate: StateAggregate;
    candidates: ReviewCandidateState[];
  };
  collection: PhaseState & {
    aggregate: StateAggregate;
    requests: CollectionRequestState[];
  };
  convergence: PhaseState & {
    latestHypothesisRoundId: string | null;
    accepted: boolean;
    roundIndex: number;
    roundBudget: number;
    /** R2.2 claim belief hard gate verdict; null while not structurally converged. */
    claimBeliefGate: HypothesisFirstClaimBeliefGate | null;
  };
  formalRuntime: PhaseState & {
    runId: string | null;
    runVersion: number | null;
    runStatus: FormalRunViewStatus | null;
    completionKind: string | null;
    lineageDisposition: FormalRunLineageDisposition | null;
    isCurrentRevision: boolean;
    parentRunId: string | null;
    childRunIds: string[];
    currentNodeIds: string[];
  };
  programDelivery: PhaseState & {
    deliveryStatus: ProgramDeliveryStatus;
    deliveryArtifactRef: string | null;
    handoffStatus: ProgramCandidateHandoffStatus;
    outputRecordId: string | null;
    outputRunId: string | null;
    humanReviewStatus: ProgramHumanReviewStatus;
    humanGates: ProgramHumanGateState;
    approvedGateCount: number;
    requiredGateCount: 4;
  };
  allowedActions: AllowedAction[];
  problems: WorkflowProblem[];
  sourceCursor?: Record<string, string>;
};

export type StateAggregate = {
  total: number;
  completed: number;
  pending: number;
  failed: number;
  blocked: number;
  /** Overtaken-by-the-formal-chain items; absent in older snapshots. */
  superseded?: number;
};

export type CollectionRequestListResponse = {
  schemaVersion: number;
  teamId: string;
  requestCount: number;
  requests: CollectionRequestRecord[];
  storagePath?: string;
};

export type ReviewRoundLinkListResponse = {
  schemaVersion: number;
  teamId: string;
  linkCount: number;
  links: ReviewRoundLinkRecord[];
  storagePath?: string;
};

// ---------------------------------------------------------------------------
// Claim belief hard gate (R2.2) — server-authored convergence verdict
// ---------------------------------------------------------------------------

/** One claim's belief summary inside a gate verdict. */
export type HypothesisFirstClaimGateEntry = {
  claimId: string;
  beliefState: string;
  acceptedSupportCount?: number;
  acceptedCounterCount?: number;
  supportingEvidenceIds?: string[];
  counterEvidenceIds?: string[];
  /** Present when the ledger entry itself could not be evaluated. */
  problem?: string;
};

/** One accepted-evidence shortfall on a blocked gate verdict. */
export type HypothesisFirstClaimGateEvidenceGap = {
  claimId: string;
  gap: string;
};

/**
 * Claim belief hard gate verdict attached to a structurally converged round:
 * `convergence.claimBeliefGate` on the V2 state, top-level `claimBeliefGate`
 * on the legacy V1 chain state. `status` is `allowed` / `blocked`; the UI must
 * treat any other value (or a malformed payload) as unknown, never as a pass.
 */
export type HypothesisFirstClaimBeliefGate = {
  decisionPoint: string;
  roundId: string;
  candidateId: string;
  status: "allowed" | "blocked" | "unknown";
  reason: string;
  claims: HypothesisFirstClaimGateEntry[];
  blockedClaims: HypothesisFirstClaimGateEntry[];
  /**
   * Server optionality is asymmetric: the V1 chain state always copies the
   * verdict's `evidenceGaps`, while the V2 state projection omits the field
   * entirely. `parseClaimBeliefGate` normalizes both to an array.
   */
  evidenceGaps?: HypothesisFirstClaimGateEvidenceGap[];
};

// ---------------------------------------------------------------------------
// Anomaly inbox (R4.3) — verbatim shape of the server contract projection
// ---------------------------------------------------------------------------

export type AnomalySeverity = "critical" | "high" | "medium";

export type AnomalyKind =
  | "blocked_run"
  | "heartbeat_stale"
  | "needs_human_gate"
  | "claim_disputed"
  | "review_disagreement_escalation"
  | "drift_sentinel_hit"
  | "budget_exhausted"
  | "retry_budget_exhausted";

export type AnomalyInboxScope = {
  teamId: string;
  questionId: string;
  runId: string;
  nodeId: string;
  meetingRoundId: string;
};

/** Structured one-click extend CTA (server-built; execution needs explicit confirmation). */
export type AnomalyInboxExtendBudgetAction = {
  command: "extend_budget";
  params: {
    runId: string;
    nodeId: string;
    stageId: string;
    stageLimitTokens: number;
    suggestedExtensionTokens: number;
    newStageTokens: number;
    limits: { stageTokens: Record<string, number> };
  };
  then: { command: "retry_node"; nodeId: string };
  hint: string;
  requiresConfirmation: true;
  confirmHint: string;
};

export type AnomalyInboxItem = {
  kind: AnomalyKind;
  scope: AnomalyInboxScope;
  severity: AnomalySeverity;
  firstSeenAt: string;
  lastSeenAt: string;
  summary: string;
  recommendedAction: string | null;
  evidence: string[];
  /** Present only on budget_precheck items with a computable extend contract. */
  action?: AnomalyInboxExtendBudgetAction | null;
};

export type AnomalyInboxExtendBudgetRequest = {
  questionId: string;
  runId: string;
  nodeId: string;
  stageId: string;
  stageLimitTokens: number;
  suggestedExtensionTokens: number;
  /** 误触防护：显式确认后才执行（缺失/False 服务端 428 拒绝）。 */
  confirmed: boolean;
  expectedRunVersion?: number;
};

export type AnomalyInboxProjection = {
  schemaVersion: number;
  ruleId: string;
  generatedAt: string;
  items: AnomalyInboxItem[];
};

export type AnomalyInboxResponse = {
  schemaVersion: number;
  teamId: string;
  questionId: string;
  inbox: AnomalyInboxProjection;
};

export type QuestionRunResetImpact = {
  candidateCount: number;
  selectionCount: number;
  meetingCount: number;
  hypothesisRoundCount: number;
  collectionRequestCount: number;
  collectionRunCount: number;
};

export type QuestionRunResetPreview = {
  schemaVersion: number;
  teamId: string;
  questionId: string;
  canReset: boolean;
  blockingReason: string;
  impact: QuestionRunResetImpact;
};

export type QuestionRunResetResponse = {
  schemaVersion: number;
  teamId: string;
  questionId: string;
  removed: QuestionRunResetImpact;
  nextAction: {
    targetNodeId: string;
    label: string;
  };
};

export type DecisionRecordView = {
  decisionId: string;
  meetingRoundId: string;
  scopeHash: string;
  decision: string;
  rationale: string;
  decidedBy: string;
  candidateRefs: string[];
  evidenceRefs: string[];
  status: string;
  createdAt: string;
};

export type CloseReviewMeetingResponse = {
  schemaVersion: number;
  teamId: string;
  status: string;
  closed: boolean;
  /** Present when closed=false: why the digest could not be confirmed. */
  validationErrors?: MeetingDigestValidationError[];
  /** Reopen path: open status of the replacement round (budget_exhausted, ...). */
  openStatus?: string;
  meetingRound: MeetingRoundRecord;
  digest: Record<string, unknown>;
  decisions: DecisionRecordView[];
  collection: {
    requests?: CollectionRequestRecord[];
    skipped?: MeetingCollectionSkippedItem[];
  };
  hypothesisRound?: HypothesisRoundRecord | null;
  resume?: Record<string, unknown> | null;
  storagePath?: string;
};

export type ReviewNextRoundResponse = {
  schemaVersion: number;
  teamId: string;
  status: string;
  selectionId: string;
  previousMeetingRoundId: string;
  collectionRequestId: string;
  roundIndex: number;
  budget: number;
  meetingRound: MeetingRoundRecord;
};

export type CollectionHandoffResponse = {
  schemaVersion: number;
  teamId: string;
  status: string;
  request: CollectionRequestRecord;
  nextMeeting?: Record<string, unknown> | null;
  resume?: Record<string, unknown> | null;
};
