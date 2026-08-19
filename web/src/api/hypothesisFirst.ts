/**
 * Hypothesis-first flow transports (HF-5).
 *
 * Owns every `/api/teams/{teamId}/workflow-orchestration/{hypothesis-first,
 * meeting-rounds, hypothesis-rounds}` JSON path. Routes/hooks import named
 * functions from here — never `fetchJson` or raw URL literals.
 */

import { fetchJson } from "./client";
import type {
  CloseReviewMeetingResponse,
  CollectionHandoffResponse,
  CollectionRequestListResponse,
  HypothesisFirstChainState,
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
  ReviewRoundLinkListResponse,
} from "./types/hypothesisFirst";

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

function questionQuery(questionId: string): string {
  return questionId ? `?questionId=${encodeURIComponent(questionId)}` : "";
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
  options?: { signal?: AbortSignal },
): Promise<HypothesisSelectionListResponse> {
  return fetchJson<HypothesisSelectionListResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/selections${questionQuery(questionId)}`,
    { signal: options?.signal },
  );
}

export function fetchLatestHypothesisSelection(
  teamId: string,
  questionId: string,
  options?: { signal?: AbortSignal },
): Promise<HypothesisSelectionGetResponse> {
  return fetchJson<HypothesisSelectionGetResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/selections/latest${questionQuery(questionId)}`,
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
  options?: { signal?: AbortSignal },
): Promise<HypothesisSelectionContext> {
  return fetchJson<HypothesisSelectionContext>(
    `${teamPrefix(teamId)}/hypothesis-first/questions/${encodeURIComponent(questionId)}/selection-context`,
    { signal: options?.signal },
  );
}

export function openHypothesisCandidateGeneration(
  teamId: string,
  questionId: string,
): Promise<MeetingRoundMutationResponse> {
  return writeJson<MeetingRoundMutationResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/candidate-generation`,
    "POST",
    { questionId },
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
  options?: { signal?: AbortSignal },
): Promise<HypothesisFirstChainState> {
  return fetchJson<HypothesisFirstChainState>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/state${questionQuery(questionId)}`,
    { signal: options?.signal },
  );
}

export function fetchCollectionRequests(
  teamId: string,
  questionId = "",
  options?: { signal?: AbortSignal },
): Promise<CollectionRequestListResponse> {
  return fetchJson<CollectionRequestListResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/collection-requests${questionQuery(questionId)}`,
    { signal: options?.signal },
  );
}

export function fetchReviewRoundLinks(
  teamId: string,
  questionId = "",
  options?: { signal?: AbortSignal },
): Promise<ReviewRoundLinkListResponse> {
  return fetchJson<ReviewRoundLinkListResponse>(
    `${teamPrefix(teamId)}/hypothesis-first/chain/review-round-links${questionQuery(questionId)}`,
    { signal: options?.signal },
  );
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
