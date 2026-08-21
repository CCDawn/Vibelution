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
  trails: CandidateEvidenceTrail[];
  storagePath?: string;
};

export type HypothesisSelectionContext = {
  schemaVersion: number;
  teamId: string;
  questionId: string;
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

export type MeetingRoundMutationResponse = {
  schemaVersion: number;
  teamId: string;
  status: string;
  meetingRound: MeetingRoundRecord;
  digestDraft?: MeetingDigestDraft | null;
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

export type HypothesisRoundCandidate = {
  candidateId: string;
  claim: string;
  rationale: string;
  differenceFromAlternatives: string;
  lineageRefs: string[];
  scores: Record<string, number>;
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
  roundBudget: number;
  budgetExhausted: boolean;
  templateBaselineExists: boolean;
  templateBaselineIds: string[];
  candidateCount?: number;
  generationMeetingId?: string;
  generationMeetingStatus?: string;
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
  meetingRound: MeetingRoundRecord;
  digest: Record<string, unknown>;
  decisions: DecisionRecordView[];
  collection: {
    requests?: CollectionRequestRecord[];
    skipped?: Array<Record<string, unknown>>;
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
