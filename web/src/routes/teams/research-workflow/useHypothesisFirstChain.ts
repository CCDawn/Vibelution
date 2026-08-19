/**
 * Hypothesis-first chain data for the research process canvas (HFC-3).
 *
 * React Query read model over the existing hypothesis-first clients; the canvas
 * region composer consumes the returned ledger facts. No request is issued when
 * teamId/questionId is empty. `useHypothesisFirstChainInvalidation` bridges run
 * SSE progress into these queries so cross-panel chain actions (selection,
 * meeting closure, handoff) refresh the canvas region.
 */
import { useEffect } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";

import {
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisSelections,
  fetchMeetingRounds,
  fetchReviewRoundLinks,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
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

// queryKeys.ts is read-only in this lane; the two chain list keys follow the
// established hypothesis-first key shape so invalidation by prefix works.
export const hypothesisFirstChainCollectionRequestsKey = (teamId: string, questionId: string) =>
  ["teams", teamId, "hypothesis-first", "chain", "collection-requests", questionId] as const;
export const hypothesisFirstChainReviewRoundLinksKey = (teamId: string, questionId: string) =>
  ["teams", teamId, "hypothesis-first", "chain", "review-round-links", questionId] as const;

export type HypothesisFirstChainData = {
  chainState: HypothesisFirstChainState | null;
  /** Latest selection for the question (server already filters by questionId). */
  selection: HypothesisSelectionRecord | null;
  meetings: MeetingRoundRecord[];
  collectionRequests: CollectionRequestRecord[];
  reviewRoundLinks: ReviewRoundLinkRecord[];
  loading: boolean;
  error: string | null;
};

export function useHypothesisFirstChain(teamId: string, questionId: string): HypothesisFirstChainData {
  const enabled = Boolean(teamId.trim() && questionId.trim());
  const [chainState, selections, meetings, requests, links] = useQueries({
    queries: [
      {
        queryKey: queryKeys.hypothesisFirstChainState(teamId, questionId),
        queryFn: ({ signal }) => fetchHypothesisFirstChainState(teamId, questionId, { signal }),
        enabled,
      },
      {
        queryKey: queryKeys.hypothesisFirstSelections(teamId, questionId),
        queryFn: ({ signal }) => fetchHypothesisSelections(teamId, questionId, { signal }),
        enabled,
      },
      {
        queryKey: queryKeys.teamMeetingRounds(teamId),
        queryFn: ({ signal }) => fetchMeetingRounds(teamId, { signal }),
        enabled,
      },
      {
        queryKey: hypothesisFirstChainCollectionRequestsKey(teamId, questionId),
        queryFn: ({ signal }) => fetchCollectionRequests(teamId, questionId, { signal }),
        enabled,
      },
      {
        queryKey: hypothesisFirstChainReviewRoundLinksKey(teamId, questionId),
        queryFn: ({ signal }) => fetchReviewRoundLinks(teamId, questionId, { signal }),
        enabled,
      },
    ],
  });

  const selectionList = selections.data?.selections;
  const selection = selectionList?.length
    ? selectionList.reduce((latest, item) =>
        String(item.createdAt ?? "") > String(latest.createdAt ?? "") ? item : latest)
    : null;

  const firstError = [chainState, selections, meetings, requests, links]
    .map((query) => query.error)
    .find(Boolean);

  return {
    chainState: chainState.data ?? null,
    selection,
    meetings: meetings.data?.meetings ?? EMPTY_MEETINGS,
    collectionRequests: requests.data?.requests ?? EMPTY_REQUESTS,
    reviewRoundLinks: links.data?.links ?? EMPTY_LINKS,
    loading: enabled && [chainState, selections, meetings, requests, links].some((query) => query.isPending),
    error: firstError instanceof Error ? firstError.message : firstError ? String(firstError) : null,
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
      void queryClient.invalidateQueries({ queryKey: ["teams", teamId, "hypothesis-first"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamMeetingRounds(teamId) });
    }, 250);
    return () => clearTimeout(timer);
  }, [queryClient, teamId, questionId, lastSequence]);
}
