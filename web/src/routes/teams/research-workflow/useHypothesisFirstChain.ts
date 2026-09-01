/**
 * Hypothesis-first chain data for the research process canvas (HFC-3).
 *
 * React Query read model over the existing hypothesis-first clients; the canvas
 * region composer consumes the returned ledger facts. No request is issued when
 * teamId/questionId is empty. `useHypothesisFirstChainInvalidation` bridges run
 * SSE progress into these queries so cross-panel chain actions (selection,
 * meeting closure, handoff) refresh the canvas region.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  executeHypothesisFirstCommand,
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisFirstStateV2,
  fetchHypothesisSelections,
  fetchMeetingRounds,
  isHypothesisFirstCommandStateConflict,
  recoverCollectionRequest,
  fetchReviewRoundLinks,
  isHypothesisFirstStateV2EndpointUnavailable,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import { resolvePollingInterval, usePageVisibility } from "../../../app/pollingPolicy";
import { collectionRequestNeedsPolling } from "./hypothesisFirstCollectionStatus";
import type {
  CollectionRequestRecord,
  HypothesisFirstChainState,
  HypothesisFirstStateV2,
  HypothesisSelectionRecord,
  MeetingRoundRecord,
  ReviewRoundLinkRecord,
} from "../../../api/types/hypothesisFirst";

const EMPTY_MEETINGS: MeetingRoundRecord[] = [];
const EMPTY_REQUESTS: CollectionRequestRecord[] = [];
const EMPTY_LINKS: ReviewRoundLinkRecord[] = [];

const LIVE_MEETING = new Set(["open", "summarizing"]);
const BOUNDED_POLL_MS = 4_000;

// These lists are requested separately from V2, so their cache identity must
// carry the same workflow-run scope as the canonical snapshot.
export const hypothesisFirstChainCollectionRequestsKey = (
  teamId: string,
  questionId: string,
  runId = "",
) => ["teams", teamId, "hypothesis-first", "chain", "collection-requests", questionId, runId] as const;
export const hypothesisFirstChainReviewRoundLinksKey = (
  teamId: string,
  questionId: string,
  runId = "",
) => ["teams", teamId, "hypothesis-first", "chain", "review-round-links", questionId, runId] as const;

/**
 * Display fallback for the single server-owned review-round hard limit, shared
 * with the workspace chrome. The authoritative value travels on the snapshot
 * itself (`stateV2.convergence.roundBudget` / `chainState.roundBudget`); this
 * constant only covers payloads that carry no readable budget.
 */
export const HYPOTHESIS_FIRST_REVIEW_ROUND_LIMIT = 5;

function isReadableRoundBudget(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 1;
}

/**
 * Read the review-round budget from the server snapshot: V2 first, then the
 * V1 compatibility chain state, then the hard-limit fallback. Both snapshot
 * surfaces are recomputed server-side on every read, so replayed review-round
 * links written under the retired default-3 budget model never reach this
 * resolver — those historical per-round values stay replay-only data and do
 * not reduce the limit. Legacy V1 snapshots default `roundBudget` to 0, and
 * any other unreadable value (negative/NaN) also falls back so old payloads
 * keep the stable hard-limit display.
 *
 * The input is deliberately structural (optional convergence/roundBudget) so
 * partial snapshots from any consumer stay assignable; the runtime guard,
 * not the type, decides readability.
 */
export function resolveHypothesisFirstRoundBudget(input: {
  stateV2?: { convergence?: { roundBudget?: number } | null } | null;
  chainState?: { roundBudget?: number } | null;
}): number {
  if (isReadableRoundBudget(input.stateV2?.convergence?.roundBudget)) {
    return input.stateV2.convergence.roundBudget;
  }
  if (isReadableRoundBudget(input.chainState?.roundBudget)) {
    return input.chainState.roundBudget;
  }
  return HYPOTHESIS_FIRST_REVIEW_ROUND_LIMIT;
}

/**
 * Which authority the returned chain data came from. Everything except
 * `v2_canonical` fails closed for legacy mutation gates because those gates
 * compare against `"v2_canonical"` only (plan §8.3: UI must know its source).
 */
export type HypothesisFirstStateSource =
  | "v2_canonical"
  | "v1_legacy"
  /** V2 read failed (500 / invalid DTO / fatal). Never V1-inferred. */
  | "v2_error"
  /** No authoritative read result yet; consumers must not guess a phase. */
  | "pending";

/** Explicit discrimination of the V2 canonical snapshot read itself. */
export type HypothesisFirstV2ReadState =
  /** Snapshot received and parsed. */
  | "ok"
  /** Route-level 404/501 — the only fallback that may run the V1 resolver. */
  | "route_unavailable"
  /** Server up, route present, but 500/malformed/fatal: fail closed. */
  | "v2_error"
  /** First-frame loading or not started. */
  | "pending";

export type HypothesisFirstChainData = {
  /** Stable identity of the requested read scope. */
  questionScopeKey: string;
  questionId: string;
  runId: string;
  /** True when a scoped payload declares a different question or run. */
  scopeMismatch: boolean;
  /** Canonical server snapshot when the V2 endpoint is available. */
  stateV2: HypothesisFirstStateV2 | null;
  /** Explicitly tells consumers whether the read is canonical or compatibility data. */
  stateSource: HypothesisFirstStateSource;
  /** Four-state discrimination of the canonical V2 read; drives fail-closed UI. */
  v2ReadState: HypothesisFirstV2ReadState;
  chainState: HypothesisFirstChainState | null;
  /** Latest selection for the question (server already filters by questionId). */
  selection: HypothesisSelectionRecord | null;
  meetings: MeetingRoundRecord[];
  collectionRequests: CollectionRequestRecord[];
  reviewRoundLinks: ReviewRoundLinkRecord[];
  loading: boolean;
  error: string | null;
  recoveryBusy: boolean;
  recoveryError: string | null;
  recoverCollection: (requestId: string) => Promise<void>;
};

export function invalidateHypothesisFirstQueries(
  queryClient: QueryClient,
  teamId: string,
  questionId: string,
  runId = "",
): void {
  void queryClient.invalidateQueries({ queryKey: ["teams", teamId, "hypothesis-first"] });
  void queryClient.invalidateQueries({ queryKey: queryKeys.teamMeetingRounds(teamId) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.teamHypothesisRounds(teamId) });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId, runId),
  });
}

function shouldPollMeetings(meetings: MeetingRoundRecord[] | undefined): boolean {
  return (meetings ?? []).some((meeting) => LIVE_MEETING.has(String(meeting.status)));
}

function shouldPollCollections(
  state: HypothesisFirstChainState | undefined,
  requests: CollectionRequestRecord[] | undefined,
): boolean {
  const list = requests ?? [];
  if (list.length > 0) return list.some(collectionRequestNeedsPolling);
  return Boolean(state?.collectionReady && state.pendingCollectionCount > 0);
}

function normalizedQuestion(value: string | null | undefined): string {
  return String(value || "").trim().toUpperCase();
}

function recordMatchesQuestion(value: string | null | undefined, questionId: string): boolean {
  const recordQuestion = normalizedQuestion(value);
  return Boolean(recordQuestion && recordQuestion === questionId);
}

function normalizedRun(value: string | null | undefined): string {
  return String(value || "").trim();
}

function meetingWorkflowRunId(meeting: MeetingRoundRecord): string {
  const receiptAuthority = (meeting as MeetingRoundRecord & {
    modelInvocationReceiptAuthority?: Record<string, unknown>;
  }).modelInvocationReceiptAuthority;
  if (typeof receiptAuthority?.workflowRunId === "string") {
    const receiptRunId = normalizedRun(receiptAuthority.workflowRunId);
    if (receiptRunId) return receiptRunId;
  }
  const discussionScope = meeting.discussionScope;
  if (discussionScope && typeof discussionScope.workflowRunId === "string") {
    const discussionRunId = normalizedRun(discussionScope.workflowRunId);
    if (discussionRunId) return discussionRunId;
  }
  // Compatibility for meetings created before receipt/discussion scope
  // identity was persisted. This is deliberately the last fallback.
  return normalizedRun(meeting.workflowRunId);
}

function recordMatchesRun(value: string | null | undefined, runId: string): boolean {
  return !runId || normalizedRun(value) === runId;
}

function isTerminalLifecycle(value: string | null | undefined): boolean {
  return ["completed", "failed", "cancelled", "superseded"].includes(String(value || ""));
}

/**
 * Keep the existing HFC-3 return shape usable while the route consumers move
 * to `stateV2`. This is a compatibility adapter only; it does not decide the
 * current phase or create actions.
 */
function legacyChainStateFromV2(state: HypothesisFirstStateV2): HypothesisFirstChainState {
  const candidateMeetings = state.review.candidates
    .map((candidate) => candidate.meetingRoundId)
    .filter((meetingId): meetingId is string => Boolean(meetingId));
  const firstMeetingId = state.generation.generationMeetingId
    || candidateMeetings[0]
    || "";
  const reviewCompleted = isTerminalLifecycle(state.review.lifecycle)
    && state.review.lifecycle === "completed";
  const collectionRequests = state.collection.requests.length;
  const collectionReady = state.collection.lifecycle === "completed"
    && state.collection.outcome === "succeeded";
  const latestHypothesisRoundId = state.convergence.latestHypothesisRoundId || "";
  return {
    schemaVersion: 1,
    teamId: state.teamId,
    questionId: state.questionId,
    selectionId: state.selection.selectionId || "",
    meetingCount: state.review.aggregate.total,
    firstMeetingId,
    firstMeetingClosed: reviewCompleted,
    openMeetingIds: candidateMeetings.filter((meetingId) => (
      !state.review.candidates.find((candidate) => candidate.meetingRoundId === meetingId
        && isTerminalLifecycle(candidate.lifecycle))
    )),
    collectionRequests: [],
    collectionRequestCount: collectionRequests,
    pendingCollectionCount: state.collection.aggregate.pending,
    collectionReady,
    hypothesisRoundCount: latestHypothesisRoundId ? 1 : 0,
    latestHypothesisRoundId,
    hypothesisConverged: state.convergence.accepted,
    convergenceDetail: state.convergence.problems[0]?.message || "",
    roundBudget: state.convergence.roundBudget,
    budgetExhausted: state.convergence.outcome === "exhausted",
    templateBaselineExists: false,
    templateBaselineIds: [],
    candidateCount: state.generation.candidateCount,
    generationMeetingId: state.generation.generationMeetingId || undefined,
    generationMeetingStatus: state.generation.lifecycle,
  };
}

function errorMessage(error: unknown): string | null {
  return error instanceof Error ? error.message : error ? String(error) : null;
}

export function shouldPollQuestionScopedChain(input: {
  questionId: string;
  state?: HypothesisFirstChainState;
  requests?: CollectionRequestRecord[];
}): boolean {
  const questionId = normalizedQuestion(input.questionId);
  const state = input.state && recordMatchesQuestion(input.state.questionId, questionId)
    ? input.state
    : undefined;
  const requests = (input.requests ?? []).filter((request) => (
    recordMatchesQuestion(request.questionId, questionId)
  ));
  return shouldPollCollections(state, requests);
}

export function shouldPollHypothesisFirstStateV2(state: HypothesisFirstStateV2 | undefined): boolean {
  if (!state) return false;
  const isLive = (phase: { lifecycle: string; actionability: string }) => (
    phase.lifecycle === "queued"
    || phase.lifecycle === "running"
    || phase.actionability === "executing"
    || phase.actionability === "waiting_system"
  );
  if ([
    state.generation,
    state.review,
    state.collection,
    state.formalRuntime,
    state.programDelivery,
  ].some(isLive)) return true;
  if (state.review.candidates.some((candidate) => (
    isLive(candidate)
    || isLive(candidate.discussion)
    || isLive(candidate.summarization)
  ))) return true;
  return state.collection.requests.some((request) => (
    isLive(request)
    || isLive(request.childRun)
    || isLive(request.handoff)
    || request.sources.some(isLive)
  ));
}

export function useHypothesisFirstChain(
  teamId: string,
  questionId: string,
  runId = "",
): HypothesisFirstChainData {
  const requestedQuestionId = normalizedQuestion(questionId);
  const requestedRunId = normalizedRun(runId);
  const enabled = Boolean(teamId.trim() && requestedQuestionId);
  const pageVisible = usePageVisibility();
  const queryClient = useQueryClient();
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const stateV2Query = useQuery({
    queryKey: queryKeys.hypothesisFirstChainStateV2(teamId, questionId, requestedRunId),
    queryFn: ({ signal }) => fetchHypothesisFirstStateV2(teamId, questionId, {
      signal,
      runId: requestedRunId,
    }),
    enabled,
    retry: false,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
    refetchInterval: (query) => {
      const state = query.state.data;
      return state
        ? resolvePollingInterval(
          pageVisible,
          shouldPollHypothesisFirstStateV2(state)
            ? BOUNDED_POLL_MS
            : false,
        )
        : false;
    },
  });
  const v2EndpointUnavailable = isHypothesisFirstStateV2EndpointUnavailable(stateV2Query.error);
  const legacyChainStateQuery = useQuery({
    queryKey: queryKeys.hypothesisFirstChainState(teamId, questionId, requestedRunId),
    queryFn: ({ signal }) => fetchHypothesisFirstChainState(teamId, questionId, {
      signal,
      runId: requestedRunId,
    }),
    enabled: enabled && v2EndpointUnavailable,
    retry: false,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
    refetchInterval: (query) =>
      shouldPollQuestionScopedChain({
        questionId: requestedQuestionId,
        state: query.state.data,
      })
        ? resolvePollingInterval(pageVisible, BOUNDED_POLL_MS)
        : false,
  });
  const selections = useQuery({
    queryKey: queryKeys.hypothesisFirstSelections(teamId, questionId, requestedRunId),
    queryFn: ({ signal }) => fetchHypothesisSelections(teamId, questionId, {
      signal,
      runId: requestedRunId,
    }),
    enabled,
    // Per-query override of the global focus default (app/providers.tsx): the
    // chain ledgers must be current when the user returns to the tab without
    // waiting for the next gated poll tick. Mirrors stateV2 above.
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
  const meetings = useQuery({
    queryKey: queryKeys.teamMeetingRounds(teamId),
    queryFn: ({ signal }) => fetchMeetingRounds(teamId, { signal }),
    enabled,
    // See `selections`: same per-query focus/reconnect refresh contract.
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
    refetchInterval: (query) =>
      shouldPollMeetings((query.state.data?.meetings ?? []).filter((meeting) => (
        recordMatchesQuestion(meeting.question, requestedQuestionId)
        && recordMatchesRun(meetingWorkflowRunId(meeting), requestedRunId)
      )))
        ? resolvePollingInterval(pageVisible, BOUNDED_POLL_MS)
        : false,
  });
  const requests = useQuery({
    queryKey: hypothesisFirstChainCollectionRequestsKey(teamId, questionId, requestedRunId),
    queryFn: ({ signal }) => fetchCollectionRequests(teamId, questionId, {
      signal,
      runId: requestedRunId,
    }),
    enabled,
    // See `selections`: same per-query focus/reconnect refresh contract.
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
    refetchInterval: (query) =>
      shouldPollQuestionScopedChain({
        questionId: requestedQuestionId,
        requests: query.state.data?.requests,
      })
        ? resolvePollingInterval(pageVisible, BOUNDED_POLL_MS)
        : false,
  });
  const links = useQuery({
    queryKey: hypothesisFirstChainReviewRoundLinksKey(teamId, questionId, requestedRunId),
    queryFn: ({ signal }) => fetchReviewRoundLinks(teamId, questionId, {
      signal,
      runId: requestedRunId,
    }),
    enabled,
    // See `selections`: same per-query focus/reconnect refresh contract.
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });

  const selectionList = selections.data?.selections.filter((selection) => (
    recordMatchesQuestion(selection.questionId, requestedQuestionId)
    && recordMatchesRun(selection.workflowRunId, requestedRunId)
  ));
  const selection = selectionList?.length
    ? selectionList.reduce((latest, item) =>
        String(item.createdAt ?? "") > String(latest.createdAt ?? "") ? item : latest)
    : null;

  const canonicalState = stateV2Query.data ?? null;
  // Four-state V2 read discrimination. The route-level judgement itself stays
  // owned by api/hypothesisFirst (isHypothesisFirstStateV2EndpointUnavailable);
  // only that case may fall back to the compatibility V1 read (plan §8.3).
  const v2ReadState: HypothesisFirstV2ReadState = !enabled || stateV2Query.isPending
    ? "pending"
    : canonicalState
      ? "ok"
      : v2EndpointUnavailable
        ? "route_unavailable"
        : "v2_error";
  const stateSource: HypothesisFirstStateSource = v2ReadState === "ok"
    ? "v2_canonical"
    : v2ReadState === "route_unavailable"
      ? "v1_legacy"
      : v2ReadState === "v2_error"
        ? "v2_error"
        // Nothing authoritative has been read yet; never claim a source.
        : "pending";
  const chainState = v2ReadState === "ok" && canonicalState
    ? legacyChainStateFromV2(canonicalState)
    : v2ReadState === "route_unavailable"
      ? (legacyChainStateQuery.data ?? null)
      // v2_error and pending must not expose compatibility phase data, even
      // when a stale V1 payload lingers in the query cache.
      : null;
  const firstError = [
    stateV2Query.error && !v2EndpointUnavailable ? stateV2Query.error : null,
    legacyChainStateQuery.error,
    selections.error,
    meetings.error,
    requests.error,
    links.error,
  ].find(Boolean);

  const recoverCollection = useCallback(async (requestId: string) => {
    const normalizedRequestId = requestId.trim();
    if (!normalizedRequestId || recoveryBusy) return;
    setRecoveryBusy(true);
    setRecoveryError(null);
    try {
      const canonicalAction = stateV2Query.data?.allowedActions.find((action) => (
        action.kind === "command"
        && (action.command === "retry_collection" || action.command === "continue_collection")
        && action.payload.requestId === normalizedRequestId
      ));
      if (canonicalAction?.kind === "command"
        && (canonicalAction.command === "retry_collection" || canonicalAction.command === "continue_collection")) {
        await executeHypothesisFirstCommand(
          teamId,
          questionId,
          canonicalAction,
          undefined,
          { runId: requestedRunId },
        );
      } else if (v2EndpointUnavailable) {
        await recoverCollectionRequest(teamId, normalizedRequestId);
      } else {
        throw new Error("canonical_action_unavailable");
      }
      invalidateHypothesisFirstQueries(queryClient, teamId, questionId, requestedRunId);
    } catch (error) {
      if (isHypothesisFirstCommandStateConflict(error)) {
        invalidateHypothesisFirstQueries(queryClient, teamId, questionId, requestedRunId);
        setRecoveryError("状态已更新，请重新确认。");
      } else {
        setRecoveryError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setRecoveryBusy(false);
    }
  }, [questionId, queryClient, recoveryBusy, requestedRunId, stateV2Query.data, teamId, v2EndpointUnavailable]);

  // Meeting records never carry roundIndex server-side; the review-round
  // links are the authority. Decorate review meetings here so node ids,
  // inspectors, and next-action navigation all share one numbering. These are
  // memoized because downstream canvas/inspector composition is reference-
  // sensitive; rebuilding per render would invalidate that memoization.
  const runScopedMeetings = useMemo(() => (meetings.data?.meetings ?? EMPTY_MEETINGS)
    .filter((meeting) => (
      recordMatchesQuestion(meeting.question, requestedQuestionId)
      && recordMatchesRun(meetingWorkflowRunId(meeting), requestedRunId)
    )), [meetings.data?.meetings, requestedQuestionId, requestedRunId]);
  const runMeetingIds = useMemo(
    () => new Set(runScopedMeetings.map((meeting) => String(meeting.meetingRoundId || ""))),
    [runScopedMeetings],
  );
  const scopedLinks = useMemo(() => (links.data?.links ?? EMPTY_LINKS).filter((link) => (
    recordMatchesQuestion(link.questionId, requestedQuestionId)
    && (!requestedRunId || runMeetingIds.has(String(link.meetingRoundId || "")))
  )), [links.data?.links, requestedQuestionId, requestedRunId, runMeetingIds]);
  const linkByMeetingId = useMemo(
    () => new Map(scopedLinks.map((link) => [String(link.meetingRoundId || ""), link])),
    [scopedLinks],
  );
  const decoratedMeetings = useMemo(() => runScopedMeetings
    .map((meeting) => {
      const link = linkByMeetingId.get(String(meeting.meetingRoundId || ""));
      if (!link) return meeting;
      return {
        ...meeting,
        roundIndex: meeting.roundIndex ?? (Number(link.roundIndex || 0) || undefined),
        previousMeetingRoundId: meeting.previousMeetingRoundId
          || (String(link.previousMeetingRoundId || "") || undefined),
      };
    }), [runScopedMeetings, linkByMeetingId]);
  const scopedRequests = useMemo(() => (requests.data?.requests ?? EMPTY_REQUESTS).filter((request) => (
    recordMatchesQuestion(request.questionId, requestedQuestionId)
    && (!requestedRunId || runMeetingIds.has(String(request.meetingRoundId || "")))
  )), [requests.data?.requests, requestedQuestionId, requestedRunId, runMeetingIds]);
  const resolvedChainQuestionId = normalizedQuestion(chainState?.questionId);
  const resolvedStateRunId = normalizedRun(canonicalState?.scope.workflowRunId);
  const scopeMismatch = Boolean(
    enabled
    && (
      (resolvedChainQuestionId && resolvedChainQuestionId !== requestedQuestionId)
      || (requestedRunId && resolvedStateRunId !== requestedRunId)
    ),
  );
  return {
    questionScopeKey: `${teamId.trim()}::${requestedQuestionId || "no-question"}::${requestedRunId || "no-run"}`,
    questionId: requestedQuestionId,
    runId: requestedRunId,
    scopeMismatch,
    stateV2: scopeMismatch ? null : canonicalState,
    stateSource,
    v2ReadState,
    chainState: scopeMismatch ? null : chainState,
    selection,
    meetings: decoratedMeetings,
    collectionRequests: scopedRequests,
    reviewRoundLinks: scopedLinks,
    loading: enabled && [stateV2Query, selections, meetings, requests, links]
      .some((query) => query.isPending)
      || (enabled && v2EndpointUnavailable && legacyChainStateQuery.isPending),
    error: errorMessage(firstError),
    recoveryBusy,
    recoveryError,
    recoverCollection,
  };
}

/**
 * Run SSE events may carry chain-relevant state changes (e.g. a readiness
 * blocker lifted by a meeting closure). Debounced trailing invalidation keeps
 * the region fresh without refetching on every single event.
 */
export function useHypothesisFirstChainInvalidation(
  teamId: string,
  questionId: string,
  runId: string,
  lastSequence: number,
): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!teamId.trim() || !questionId.trim() || lastSequence <= 0) {
      return;
    }
    const timer = setTimeout(() => {
      invalidateHypothesisFirstQueries(queryClient, teamId, questionId, runId);
    }, 250);
    return () => clearTimeout(timer);
  }, [queryClient, teamId, questionId, runId, lastSequence]);
}
