/**
 * Hypothesis-first flow transports (HF-5).
 *
 * Owns every `/api/teams/{teamId}/workflow-orchestration/{hypothesis-first,
 * meeting-rounds, hypothesis-rounds}` JSON path. Routes/hooks import named
 * functions from here — never `fetchJson` or raw URL literals.
 */

import { fetchJson, isFetchJsonHttpError } from "./client";
import type {
  ActionCommand,
  ActionInputByCommand,
  AnomalyInboxExtendBudgetRequest,
  AnomalyInboxItem,
  AnomalyInboxResponse,
  CandidateEvidenceTrailResponse,
  CommandAction,
  CloseReviewMeetingResponse,
  CollectionHandoffResponse,
  CollectionRequestListResponse,
  HypothesisFirstChainState,
  HypothesisFirstClaimBeliefGate,
  HypothesisFirstClaimGateEntry,
  HypothesisFirstClaimGateEvidenceGap,
  HypothesisFirstStateV2,
  HypothesisRoundGetResponse,
  HypothesisRoundListResponse,
  HypothesisSelectionContext,
  HypothesisSelectionGetResponse,
  HypothesisSelectionListResponse,
  HypothesisSelectionRecordPayload,
  HypothesisSelectionRecordResponse,
  MeetingApproveDigestRequest,
  MeetingClosureApprovePayload,
  MeetingDigestDraft,
  MeetingRoundGetResponse,
  MeetingRoundListResponse,
  MeetingRoundMutationResponse,
  MeetingSourceMessagesResponse,
  MeetingSummaryDraftRequest,
  ReviewNextRoundResponse,
  ReviewRoundLinkListResponse,
  QuestionRunResetPreview,
  QuestionRunResetResponse,
} from "./types/hypothesisFirst";

// Re-exported so inspector surfaces classify HTTP errors through this domain
// module — routes must not import `api/client` directly
// (fullStackApiBoundary.test.ts).
export { isFetchJsonHttpError };

function teamPrefix(teamId: string): string {
  return `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration`;
}

function writeJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function scopedQuery(input: {
  questionId?: string;
  runId?: string;
  includeSourceCursor?: boolean;
}): string {
  const parts: string[] = [];
  if (input.questionId) parts.push(`questionId=${encodeURIComponent(input.questionId)}`);
  if (input.runId) parts.push(`runId=${encodeURIComponent(input.runId)}`);
  if (input.includeSourceCursor) parts.push("includeSourceCursor=true");
  return parts.length ? `?${parts.join("&")}` : "";
}

function commandRunId(action: CommandAction, explicitRunId = ""): string {
  if (explicitRunId.trim()) return explicitRunId.trim();
  const payload = action.payload as Record<string, unknown>;
  return [payload.workflowRunId, payload.runId, payload.outputRunId]
    .map((value) => typeof value === "string" ? value.trim() : "")
    .find(Boolean) ?? "";
}

const V2_ENDPOINT_UNAVAILABLE_CODES = new Set([
  "endpoint_not_found",
  "endpoint_unavailable",
  "contract_not_supported",
  "route_not_found",
]);

/** Only infrastructure-level absence permits the compatibility V1 read. */
export function isHypothesisFirstStateV2EndpointUnavailable(error: unknown): boolean {
  if (!isFetchJsonHttpError(error)) return false;
  const details = isRecord(error.details) ? error.details : null;
  const defaultRouteNotFound = details?.detail === "Not Found";
  return error.status === 501
    || (
      error.status === 404
      && (
        V2_ENDPOINT_UNAVAILABLE_CODES.has(String(error.code || ""))
        || (error.code === null && defaultRouteNotFound)
      )
    );
}

// ---------------------------------------------------------------------------
// Selection (HF-1)
// ---------------------------------------------------------------------------

export function recordHypothesisSelection(
  teamId: string,
  body: HypothesisSelectionRecordPayload,
): Promise<HypothesisSelectionRecordResponse> {
  return writeJson<HypothesisSelectionRecordResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/selections`,
    "POST",
    body,
  );
}

export function fetchHypothesisSelections(
  teamId: string,
  questionId = "",
  options?: { signal?: AbortSignal; runId?: string },
): Promise<HypothesisSelectionListResponse> {
  return fetchJson<HypothesisSelectionListResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/selections${scopedQuery({ questionId, runId: options?.runId })}`,
    { signal: options?.signal },
  );
}

export function fetchLatestHypothesisSelection(
  teamId: string,
  questionId: string,
  options?: { signal?: AbortSignal; runId?: string },
): Promise<HypothesisSelectionGetResponse> {
  return fetchJson<HypothesisSelectionGetResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/selections/latest${scopedQuery({ questionId, runId: options?.runId })}`,
    { signal: options?.signal },
  );
}

export function fetchHypothesisSelection(
  teamId: string,
  selectionId: string,
  options?: { signal?: AbortSignal },
): Promise<HypothesisSelectionGetResponse> {
  return fetchJson<HypothesisSelectionGetResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/selections/${encodeURIComponent(selectionId)}`,
    { signal: options?.signal },
  );
}

export function fetchHypothesisSelectionContext(
  teamId: string,
  questionId: string,
  options?: { signal?: AbortSignal; runId?: string },
): Promise<HypothesisSelectionContext> {
  return fetchJson<HypothesisSelectionContext>(
    `${teamPrefix(teamId)}/hypothesis-first/questions/${encodeURIComponent(questionId)}/selection-context${scopedQuery({ runId: options?.runId })}`,
    { signal: options?.signal },
  );
}

export function fetchCandidateEvidenceTrail(
  teamId: string,
  questionId: string,
  options?: { signal?: AbortSignal; runId?: string },
): Promise<CandidateEvidenceTrailResponse> {
  return fetchJson<CandidateEvidenceTrailResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/questions/${encodeURIComponent(questionId)}/candidates/evidence-trail${scopedQuery({ runId: options?.runId })}`,
    { signal: options?.signal },
  );
}

export function openHypothesisCandidateGeneration(
  teamId: string,
  questionId: string,
  runId = "",
): Promise<MeetingRoundMutationResponse> {
  return writeJson<MeetingRoundMutationResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/candidate-generation`,
    "POST",
    { questionId, ...(runId ? { workflowRunId: runId } : {}) },
  );
}

export function fetchQuestionRunResetPreview(
  teamId: string,
  questionId: string,
  options?: { signal?: AbortSignal },
): Promise<QuestionRunResetPreview> {
  return fetchJson<QuestionRunResetPreview>(
    `${teamPrefix(teamId)}/hypothesis-first/questions/${encodeURIComponent(questionId)}/run-reset-preview`,
    { signal: options?.signal },
  );
}

export function resetQuestionRun(
  teamId: string,
  questionId: string,
  confirmationQuestionId: string,
): Promise<QuestionRunResetResponse> {
  return writeJson<QuestionRunResetResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/questions/${encodeURIComponent(questionId)}/run-reset`,
    "POST",
    { confirmationQuestionId },
  );
}

// ---------------------------------------------------------------------------
// Meeting rounds (HF-2)
// ---------------------------------------------------------------------------

export function fetchMeetingRounds(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<MeetingRoundListResponse> {
  return fetchJson<MeetingRoundListResponse>(`${teamPrefix(teamId)}/meeting-rounds`, {
    signal: options?.signal,
  });
}

export function fetchMeetingRound(
  teamId: string,
  meetingRoundId: string,
  options?: { signal?: AbortSignal },
): Promise<MeetingRoundGetResponse> {
  return fetchJson<MeetingRoundGetResponse>(
    `${teamPrefix(teamId)}/meeting-rounds/${encodeURIComponent(meetingRoundId)}`,
    { signal: options?.signal },
  );
}

export function fetchMeetingRoundSourceMessages(
  teamId: string,
  meetingRoundId: string,
  options?: { signal?: AbortSignal },
): Promise<MeetingSourceMessagesResponse> {
  return fetchJson<MeetingSourceMessagesResponse>(
    `${teamPrefix(teamId)}/meeting-rounds/${encodeURIComponent(meetingRoundId)}/source-messages`,
    { signal: options?.signal },
  );
}

export function beginMeetingSummary(
  teamId: string,
  meetingRoundId: string,
  body: { actor?: string; humanTriggered?: boolean },
): Promise<MeetingRoundMutationResponse> {
  return writeJson<MeetingRoundMutationResponse>(
    `${teamPrefix(teamId)}/meeting-rounds/${encodeURIComponent(meetingRoundId)}/summary`,
    "POST",
    body,
  );
}

/** P0/P1 managed digest: UI sends only `{ actor, force: false }`. */
export function draftMeetingSummary(
  teamId: string,
  meetingRoundId: string,
  body: MeetingSummaryDraftRequest = { actor: "operator", force: false },
): Promise<MeetingRoundMutationResponse> {
  return writeJson<MeetingRoundMutationResponse>(
    `${teamPrefix(teamId)}/meeting-rounds/${encodeURIComponent(meetingRoundId)}/summary-draft`,
    "POST",
    { actor: body.actor, force: false },
  );
}

/** Chain-aware confirm: UI sends only `{ closedBy, expectedDigestContentHash }`. */
export function approveHypothesisDigest(
  teamId: string,
  meetingRoundId: string,
  body: MeetingApproveDigestRequest,
): Promise<CloseReviewMeetingResponse> {
  return writeJson<CloseReviewMeetingResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/meetings/${encodeURIComponent(meetingRoundId)}/approve-digest`,
    "POST",
    {
      closedBy: body.closedBy,
      expectedDigestContentHash: body.expectedDigestContentHash,
    },
  );
}

export function submitMeetingDigestDraft(
  teamId: string,
  meetingRoundId: string,
  body: MeetingDigestDraft,
): Promise<MeetingRoundMutationResponse> {
  return writeJson<MeetingRoundMutationResponse>(
    `${teamPrefix(teamId)}/meeting-rounds/${encodeURIComponent(meetingRoundId)}/digest-draft`,
    "POST",
    body,
  );
}

export function rejectMeetingDigestDraft(
  teamId: string,
  meetingRoundId: string,
  body: { actor?: string; reason?: string },
): Promise<MeetingRoundMutationResponse> {
  return writeJson<MeetingRoundMutationResponse>(
    `${teamPrefix(teamId)}/meeting-rounds/${encodeURIComponent(meetingRoundId)}/digest-reject`,
    "POST",
    body,
  );
}

export function approveMeetingClosure(
  teamId: string,
  meetingRoundId: string,
  body: MeetingClosureApprovePayload,
): Promise<CloseReviewMeetingResponse> {
  return writeJson<CloseReviewMeetingResponse>(
    `${teamPrefix(teamId)}/meeting-rounds/${encodeURIComponent(meetingRoundId)}/closure`,
    "POST",
    body,
  );
}

// ---------------------------------------------------------------------------
// Hypothesis rounds (HF-3, read-only)
// ---------------------------------------------------------------------------

export function fetchHypothesisRounds(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<HypothesisRoundListResponse> {
  return fetchJson<HypothesisRoundListResponse>(
    `${teamPrefix(teamId)}/hypothesis-rounds`,
    { signal: options?.signal },
  );
}

export function fetchHypothesisRound(
  teamId: string,
  roundId: string,
  options?: { signal?: AbortSignal },
): Promise<HypothesisRoundGetResponse> {
  return fetchJson<HypothesisRoundGetResponse>(
    `${teamPrefix(teamId)}/hypothesis-rounds/${encodeURIComponent(roundId)}`,
    { signal: options?.signal },
  );
}

// ---------------------------------------------------------------------------
// Hypothesis-first chain (HF-4)
// ---------------------------------------------------------------------------

export function fetchHypothesisFirstChainState(
  teamId: string,
  questionId: string,
  options?: { signal?: AbortSignal; runId?: string },
): Promise<HypothesisFirstChainState> {
  return fetchJson<HypothesisFirstChainState>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/state${scopedQuery({ questionId, runId: options?.runId })}`,
    { signal: options?.signal },
  );
}

/** Canonical workflow state snapshot. V1 chain state remains available below for compatibility. */
export function fetchHypothesisFirstStateV2(
  teamId: string,
  questionId: string,
  options?: { signal?: AbortSignal; includeSourceCursor?: boolean; runId?: string },
): Promise<HypothesisFirstStateV2> {
  return fetchJson<unknown>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/state-v2${scopedQuery({
      questionId,
      runId: options?.runId,
      includeSourceCursor: options?.includeSourceCursor,
    })}`,
    { signal: options?.signal },
  ).then((payload) => parseHypothesisFirstStateV2(payload));
}

export type HypothesisFirstCommandExecutionResponse = {
  schemaVersion: 2;
  teamId: string;
  questionId: string;
  command: CommandAction["command"];
  actionId: string;
  idempotencyKey: string;
  acceptedStateVersion: string;
  result: unknown;
};

export function isHypothesisFirstCommandStateConflict(error: unknown): boolean {
  return isFetchJsonHttpError(error)
    && error.status === 409
    && error.code === "state_version_conflict";
}

/** Submit an action exactly as authorized by the canonical V2 snapshot. */
export function executeHypothesisFirstCommand<C extends ActionCommand>(
  teamId: string,
  questionId: string,
  action: Extract<CommandAction, { command: C }>,
  input?: C extends keyof ActionInputByCommand ? ActionInputByCommand[C] : never,
  options?: { runId?: string },
): Promise<HypothesisFirstCommandExecutionResponse> {
  const runId = commandRunId(action, options?.runId);
  return writeJson<HypothesisFirstCommandExecutionResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/commands${scopedQuery({ questionId, runId })}`,
    "POST",
    {
      actionId: action.actionId,
      idempotencyKey: action.idempotencyKey,
      expectedStateVersion: action.expectedStateVersion,
      payload: action.payload,
      ...(input === undefined ? {} : { input }),
    },
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/** Lightweight runtime boundary: malformed V2 must stay an error, never V1 initial state. */
function parseHypothesisFirstStateV2(payload: unknown): HypothesisFirstStateV2 {
  if (!isRecord(payload)) {
    throw new Error("Invalid hypothesis-first state V2 response");
  }
  const phaseNames = [
    "overall",
    "generation",
    "selection",
    "review",
    "collection",
    "convergence",
    "formalRuntime",
    "programDelivery",
  ];
  const valid = payload.schemaVersion === 2
    && payload.contract === "hypothesis-first-state/v2"
    && typeof payload.teamId === "string"
    && typeof payload.questionId === "string"
    && typeof payload.stateVersion === "string"
    && typeof payload.representationVersion === "string"
    && typeof payload.awaitingHumanCount === "number"
    && phaseNames.every((name) => isRecord(payload[name]))
    && isRecord(payload.review)
    && Array.isArray(payload.review.candidates)
    && isRecord(payload.review.aggregate)
    && isRecord(payload.collection)
    && Array.isArray(payload.collection.requests)
    && isRecord(payload.collection.aggregate)
    && isRecord(payload.selection)
    && isRecord(payload.generation)
    && isRecord(payload.convergence)
    && Array.isArray(payload.allowedActions)
    && Array.isArray(payload.problems);
  if (!valid) {
    throw new Error("Invalid hypothesis-first state V2 response");
  }
  return payload as unknown as HypothesisFirstStateV2;
}

function gateEntries(value: unknown): HypothesisFirstClaimGateEntry[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    const claimId = String(item.claimId ?? "").trim();
    if (!claimId) return [];
    const support = Number(item.acceptedSupportCount);
    const counter = Number(item.acceptedCounterCount);
    return [{
      claimId,
      beliefState: String(item.beliefState ?? "").trim() || "unknown",
      ...(Number.isFinite(support) ? { acceptedSupportCount: support } : {}),
      ...(Number.isFinite(counter) ? { acceptedCounterCount: counter } : {}),
      ...(Array.isArray(item.supportingEvidenceIds)
        ? { supportingEvidenceIds: item.supportingEvidenceIds.map((id) => String(id)) }
        : {}),
      ...(Array.isArray(item.counterEvidenceIds)
        ? { counterEvidenceIds: item.counterEvidenceIds.map((id) => String(id)) }
        : {}),
      ...(typeof item.problem === "string" && item.problem.trim() ? { problem: item.problem.trim() } : {}),
    }];
  });
}

function gateEvidenceGaps(value: unknown): HypothesisFirstClaimGateEvidenceGap[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    const claimId = String(item.claimId ?? "").trim();
    const gap = String(item.gap ?? "").trim();
    return claimId && gap ? [{ claimId, gap }] : [];
  });
}

/**
 * Fail-closed parse of the claim belief hard gate payload (R2.2). An
 * absent/null payload means the gate did not run (null return). A present but
 * malformed payload normalizes to `status: "unknown"` so UIs degrade to a
 * visible "gate status unknown" state instead of crashing or treating it as a
 * pass.
 */
export function parseClaimBeliefGate(value: unknown): HypothesisFirstClaimBeliefGate | null {
  if (value === null || value === undefined) return null;
  const source = isRecord(value) ? value : {};
  const rawStatus = typeof source.status === "string" ? source.status.trim().toLowerCase() : "";
  return {
    decisionPoint: typeof source.decisionPoint === "string" ? source.decisionPoint.trim() : "",
    roundId: typeof source.roundId === "string" ? source.roundId.trim() : "",
    candidateId: typeof source.candidateId === "string" ? source.candidateId.trim() : "",
    status: rawStatus === "allowed" || rawStatus === "blocked" ? rawStatus : "unknown",
    reason: typeof source.reason === "string" ? source.reason.trim() : "",
    claims: gateEntries(source.claims),
    blockedClaims: gateEntries(source.blockedClaims),
    evidenceGaps: gateEvidenceGaps(source.evidenceGaps),
  };
}

export function fetchCollectionRequests(
  teamId: string,
  questionId = "",
  options?: { signal?: AbortSignal; runId?: string },
): Promise<CollectionRequestListResponse> {
  return fetchJson<CollectionRequestListResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/collection-requests${scopedQuery({ questionId, runId: options?.runId })}`,
    { signal: options?.signal },
  );
}

export function fetchReviewRoundLinks(
  teamId: string,
  questionId = "",
  options?: { signal?: AbortSignal; runId?: string },
): Promise<ReviewRoundLinkListResponse> {
  return fetchJson<ReviewRoundLinkListResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/review-round-links${scopedQuery({ questionId, runId: options?.runId })}`,
    { signal: options?.signal },
  );
}

/**
 * R4.3 anomaly inbox: one sorted server-owned projection per question.
 * Malformed payloads fail closed here so the panel never has to guess.
 */
export function fetchHypothesisFirstAnomalyInbox(
  teamId: string,
  questionId = "",
  options?: { signal?: AbortSignal },
): Promise<AnomalyInboxResponse> {
  return fetchJson<unknown>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/anomaly-inbox${scopedQuery({ questionId })}`,
    { signal: options?.signal },
  ).then((payload) => parseAnomalyInboxResponse(payload));
}

/**
 * One-click extend CTA execution (human-authorized): the server refuses the
 * request without `confirmed: true` (428), derives the idempotency key and
 * the new stage total itself, then submits the existing extend_budget command.
 */
export function executeHypothesisFirstInboxExtendBudget(
  teamId: string,
  request: AnomalyInboxExtendBudgetRequest,
): Promise<Record<string, unknown>> {
  return writeJson(
    `${teamPrefix(teamId)}/hypothesis-first/chain/anomaly-inbox/actions/extend-budget`,
    "POST",
    request,
  );
}

const ANOMALY_SEVERITIES = new Set(["critical", "high", "medium"]);

const ANOMALY_KINDS = new Set([
  "blocked_run",
  "heartbeat_stale",
  "needs_human_gate",
  "claim_disputed",
  "review_disagreement_escalation",
  "drift_sentinel_hit",
  "budget_exhausted",
  "retry_budget_exhausted",
]);

function parseAnomalyInboxResponse(payload: unknown): AnomalyInboxResponse {
  if (!isRecord(payload) || payload.schemaVersion !== 1) {
    throw new Error("Invalid anomaly inbox response");
  }
  const inbox = payload.inbox;
  if (
    !isRecord(inbox)
    || inbox.schemaVersion !== 1
    || inbox.ruleId !== "anomaly_inbox_rule.v1"
    || typeof inbox.generatedAt !== "string"
    || !Array.isArray(inbox.items)
    || typeof payload.teamId !== "string"
    || typeof payload.questionId !== "string"
  ) {
    throw new Error("Invalid anomaly inbox response");
  }
  const items = inbox.items.map((item): AnomalyInboxItem => {
    if (!isRecord(item) || !isRecord(item.scope)) {
      throw new Error("Invalid anomaly inbox response");
    }
    const scope = item.scope;
    const validScope = ANOMALY_KINDS.has(String(item.kind))
      && ANOMALY_SEVERITIES.has(String(item.severity))
      && typeof item.firstSeenAt === "string"
      && typeof item.lastSeenAt === "string"
      && typeof item.summary === "string"
      && (item.recommendedAction === null || typeof item.recommendedAction === "string")
      && Array.isArray(item.evidence)
      && item.evidence.every((ref) => typeof ref === "string")
      && (item.action === undefined || item.action === null || isRecord(item.action))
      && ["teamId", "questionId", "runId", "nodeId", "meetingRoundId"]
        .every((field) => typeof scope[field] === "string");
    if (!validScope) {
      throw new Error("Invalid anomaly inbox response");
    }
    return item as unknown as AnomalyInboxItem;
  });
  return {
    schemaVersion: 1,
    teamId: payload.teamId,
    questionId: payload.questionId,
    inbox: {
      schemaVersion: 1,
      ruleId: "anomaly_inbox_rule.v1",
      generatedAt: inbox.generatedAt,
      items,
    },
  };
}

export function closeHypothesisReviewMeeting(
  teamId: string,
  meetingRoundId: string,
  body: MeetingClosureApprovePayload,
): Promise<CloseReviewMeetingResponse> {
  return writeJson<CloseReviewMeetingResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/review-meetings/${encodeURIComponent(meetingRoundId)}/close`,
    "POST",
    body,
  );
}

export function closeReviewMeeting(
  teamId: string,
  meetingRoundId: string,
  body: { closedBy: string; decisions: Array<Record<string, unknown>> },
): Promise<CloseReviewMeetingResponse> {
  return writeJson<CloseReviewMeetingResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/review-meetings/${encodeURIComponent(meetingRoundId)}/close`,
    "POST",
    body,
  );
}

export function reopenHypothesisReviewMeeting(
  teamId: string,
  meetingRoundId: string,
): Promise<CloseReviewMeetingResponse> {
  return writeJson<CloseReviewMeetingResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/review-meetings/${encodeURIComponent(meetingRoundId)}/reopen`,
    "POST",
    {},
  );
}

export function openNextHypothesisReviewRound(
  teamId: string,
  meetingRoundId: string,
): Promise<ReviewNextRoundResponse> {
  return writeJson<ReviewNextRoundResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/review-meetings/${encodeURIComponent(meetingRoundId)}/next-round`,
    "POST",
    {},
  );
}

export function recordCollectionHandoff(
  teamId: string,
  requestId: string,
  body: { handoffRef?: string },
): Promise<CollectionHandoffResponse> {
  return writeJson<CollectionHandoffResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/collection-requests/${encodeURIComponent(requestId)}/handoff`,
    "POST",
    body,
  );
}

export function recoverCollectionRequest(
  teamId: string,
  requestId: string,
): Promise<CollectionHandoffResponse> {
  return writeJson<CollectionHandoffResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/collection-requests/${encodeURIComponent(requestId)}/recover`,
    "POST",
  );
}
