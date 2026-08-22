/**
 * Hypothesis-first chain data for the research process canvas (HFC-3).
 *
 * React Query read model over the existing hypothesis-first clients; the canvas
 * region composer consumes the returned ledger facts. No request is issued when
 * teamId/questionId is empty. `useHypothesisFirstChainInvalidation` bridges run
 * SSE progress into these queries so cross-panel chain actions (selection,
 * meeting closure, handoff) refresh the canvas region.
 */
import { useCallback, useEffect, useState } from "react";
import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisSelections,
  fetchMeetingRounds,
  recoverCollectionRequest,
  fetchReviewRoundLinks,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import { resolvePollingInterval, usePageVisibility } from "../../../app/pollingPolicy";
import type {
  CollectionRequestRecord,
  HypothesisFirstChainState,
  HypothesisSelectionRecord,
  MeetingRoundRecord,
  ReviewRoundLinkRecord,
} from "../../../api/types/hypothesisFirst";

const EMPTY_MEETINGS: MeetingRoundRecord[] = [];
const EMPTY_REQUESTS: CollectionRequestRecord[] = [];
const EMPTY_LINKS: ReviewRoundLinkRecord[] = [];

const LIVE_MEETING = new Set(["open", "summarizing"]);
const BOUNDED_POLL_MS = 4_000;

// queryKeys.ts is read-only in this lane; the two chain list keys follow the
// established hypothesis-first key shape so invalidation by prefix works.
export const hypothesisFirstChainCollectionRequestsKey = (teamId: string, questionId: string) =>
  ["teams", teamId, "hypothesis-first", "chain", "collection-requests", questionId] as const;
export const hypothesisFirstChainReviewRoundLinksKey = (teamId: string, questionId: string) =>
  ["teams", teamId, "hypothesis-first", "chain", "review-round-links", questionId] as const;

export type HypothesisFirstChainData = {
  /** Stable identity of the requested read scope. */
  questionScopeKey: string;
  questionId: string;
  /** True when a question-keyed payload declares a different question. */
  scopeMismatch: boolean;
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
): void {
  void queryClient.invalidateQueries({ queryKey: ["teams", teamId, "hypothesis-first"] });
  void queryClient.invalidateQueries({ queryKey: queryKeys.teamMeetingRounds(teamId) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.teamHypothesisRounds(teamId) });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId),
  });
}

function shouldPollMeetings(meetings: MeetingRoundRecord[] | undefined): boolean {
  return (meetings ?? []).some((meeting) => LIVE_MEETING.has(String(meeting.status)));
}

function shouldPollCollections(
  state: HypothesisFirstChainState | undefined,
  requests: CollectionRequestRecord[] | undefined,
): boolean {
  if (state?.collectionReady && state.pendingCollectionCount > 0) return true;
  return (requests ?? []).some((request) => {
    const status = String(request.status || "");
    return status !== "handed_off" && !request.handoffRef;
  });
}

function normalizedQuestion(value: string | null | undefined): string {
  return String(value || "").trim().toUpperCase();
}

function recordMatchesQuestion(value: string | null | undefined, questionId: string): boolean {
  const recordQuestion = normalizedQuestion(value);
  return Boolean(recordQuestion && recordQuestion === questionId);
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

export function useHypothesisFirstChain(teamId: string, questionId: string): HypothesisFirstChainData {
  const requestedQuestionId = normalizedQuestion(questionId);
  const enabled = Boolean(teamId.trim() && requestedQuestionId);
  const pageVisible = usePageVisibility();
  const queryClient = useQueryClient();
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const chainState = useQuery({
    queryKey: queryKeys.hypothesisFirstChainState(teamId, questionId),
    queryFn: ({ signal }) => fetchHypothesisFirstChainState(teamId, questionId, { signal }),
    enabled,
    refetchInterval: (query) =>
      shouldPollQuestionScopedChain({
        questionId: requestedQuestionId,
        state: query.state.data,
      })
        ? resolvePollingInterval(pageVisible, BOUNDED_POLL_MS)
        : false,
  });
  const selections = useQuery({
    queryKey: queryKeys.hypothesisFirstSelections(teamId, questionId),
    queryFn: ({ signal }) => fetchHypothesisSelections(teamId, questionId, { signal }),
    enabled,
  });
  const meetings = useQuery({
    queryKey: queryKeys.teamMeetingRounds(teamId),
    queryFn: ({ signal }) => fetchMeetingRounds(teamId, { signal }),
    enabled,
    refetchInterval: (query) =>
      shouldPollMeetings((query.state.data?.meetings ?? []).filter((meeting) => (
        recordMatchesQuestion(meeting.question, requestedQuestionId)
      )))
        ? resolvePollingInterval(pageVisible, BOUNDED_POLL_MS)
        : false,
  });
  const requests = useQuery({
    queryKey: hypothesisFirstChainCollectionRequestsKey(teamId, questionId),
    queryFn: ({ signal }) => fetchCollectionRequests(teamId, questionId, { signal }),
    enabled,
    refetchInterval: (query) =>
      shouldPollQuestionScopedChain({
        questionId: requestedQuestionId,
        requests: query.state.data?.requests,
      })
        ? resolvePollingInterval(pageVisible, BOUNDED_POLL_MS)
        : false,
  });
  const links = useQuery({
    queryKey: hypothesisFirstChainReviewRoundLinksKey(teamId, questionId),
    queryFn: ({ signal }) => fetchReviewRoundLinks(teamId, questionId, { signal }),
    enabled,
  });

  const selectionList = selections.data?.selections.filter((selection) => (
    recordMatchesQuestion(selection.questionId, requestedQuestionId)
  ));
  const selection = selectionList?.length
    ? selectionList.reduce((latest, item) =>
        String(item.createdAt ?? "") > String(latest.createdAt ?? "") ? item : latest)
    : null;

  const firstError = [chainState, selections, meetings, requests, links]
    .map((query) => query.error)
    .find(Boolean);

  const recoverCollection = useCallback(async (requestId: string) => {
    const normalizedRequestId = requestId.trim();
    if (!normalizedRequestId || recoveryBusy) return;
    setRecoveryBusy(true);
    setRecoveryError(null);
    try {
      await recoverCollectionRequest(teamId, normalizedRequestId);
      invalidateHypothesisFirstQueries(queryClient, teamId, questionId);
    } catch (error) {
      setRecoveryError(error instanceof Error ? error.message : String(error));
    } finally {
      setRecoveryBusy(false);
    }
  }, [questionId, queryClient, recoveryBusy, teamId]);

  // Meeting records never carry roundIndex server-side; the review-round
  // links are the authority. Decorate review meetings here so node ids,
  // inspectors, and next-action navigation all share one numbering.
  const scopedLinks = (links.data?.links ?? EMPTY_LINKS).filter((link) => (
    recordMatchesQuestion(link.questionId, requestedQuestionId)
  ));
  const linkByMeetingId = new Map(
    scopedLinks.map((link) => [String(link.meetingRoundId || ""), link]),
  );
  const decoratedMeetings = (meetings.data?.meetings ?? EMPTY_MEETINGS)
    .filter((meeting) => recordMatchesQuestion(meeting.question, requestedQuestionId))
    .map((meeting) => {
    const link = linkByMeetingId.get(String(meeting.meetingRoundId || ""));
    if (!link) return meeting;
    return {
      ...meeting,
      roundIndex: meeting.roundIndex ?? (Number(link.roundIndex || 0) || undefined),
      previousMeetingRoundId: meeting.previousMeetingRoundId
        || (String(link.previousMeetingRoundId || "") || undefined),
    };
  });
  const scopedRequests = (requests.data?.requests ?? EMPTY_REQUESTS).filter((request) => (
    recordMatchesQuestion(request.questionId, requestedQuestionId)
  ));
  const resolvedChainQuestionId = normalizedQuestion(chainState.data?.questionId);
  const scopeMismatch = Boolean(
    enabled
    && resolvedChainQuestionId
    && resolvedChainQuestionId !== requestedQuestionId,
  );
  return {
    questionScopeKey: `${teamId.trim()}::${requestedQuestionId || "no-question"}`,
    questionId: requestedQuestionId,
    scopeMismatch,
    chainState: scopeMismatch ? null : (chainState.data ?? null),
    selection,
    meetings: decoratedMeetings,
    collectionRequests: scopedRequests,
    reviewRoundLinks: scopedLinks,
    loading: enabled && [chainState, selections, meetings, requests, links].some((query) => query.isPending),
    error: firstError instanceof Error ? firstError.message : firstError ? String(firstError) : null,
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
  lastSequence: number,
): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!teamId.trim() || !questionId.trim() || lastSequence <= 0) {
      return;
    }
    const timer = setTimeout(() => {
      invalidateHypothesisFirstQueries(queryClient, teamId, questionId);
    }, 250);
    return () => clearTimeout(timer);
  }, [queryClient, teamId, questionId, lastSequence]);
}
