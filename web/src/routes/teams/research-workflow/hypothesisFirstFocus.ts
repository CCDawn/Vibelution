/**
 * Resolve the canvas node to land on after create-run or experiment switch.
 *
 * Toolbar/URL must follow the typed next-action model, not checkpoint
 * `source_finding`. Fail closed to generation when the chain cannot be read.
 */
import {
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisSelections,
  fetchMeetingRounds,
  fetchReviewRoundLinks,
} from "../../../api/hypothesisFirst";
import type { MeetingRoundRecord } from "../../../api/types/hypothesisFirst";
import { HYPOTHESIS_FIRST_GENERATION_NODE_ID } from "./hypothesisFirstCanvasRegion";
import {
  focusNodeFromNextAction,
  resolveHypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";

function latestSelection<T extends { createdAt?: string }>(items: readonly T[] | undefined): T | null {
  if (!items?.length) return null;
  return items.reduce((latest, item) =>
    String(item.createdAt ?? "") > String(latest.createdAt ?? "") ? item : latest);
}

function meetingMatchesQuestion(meeting: MeetingRoundRecord, questionId: string): boolean {
  const needle = questionId.trim().toUpperCase();
  if (!needle) return true;
  return String(meeting.question || "").trim().toUpperCase() === needle;
}

export async function fetchHypothesisFirstFocusNode(
  teamId: string,
  questionId: string,
): Promise<string> {
  const trimmedTeam = teamId.trim();
  const trimmedQuestion = questionId.trim();
  if (!trimmedTeam || !trimmedQuestion) {
    return HYPOTHESIS_FIRST_GENERATION_NODE_ID;
  }
  try {
    const [chainState, meetingList, selectionList, requestList, reviewLinkList] = await Promise.all([
      fetchHypothesisFirstChainState(trimmedTeam, trimmedQuestion),
      fetchMeetingRounds(trimmedTeam),
      fetchHypothesisSelections(trimmedTeam, trimmedQuestion),
      fetchCollectionRequests(trimmedTeam, trimmedQuestion),
      fetchReviewRoundLinks(trimmedTeam, trimmedQuestion),
    ]);
    const next = resolveHypothesisFirstNextAction({
      run: { runId: "present" },
      chainState,
      meetings: (meetingList.meetings ?? []).filter((meeting) =>
        meetingMatchesQuestion(meeting, trimmedQuestion)),
      reviewRoundLinks: reviewLinkList.links,
      selection: latestSelection(selectionList.selections),
      collectionRequests: requestList.requests,
    });
    return focusNodeFromNextAction(next);
  } catch {
    return HYPOTHESIS_FIRST_GENERATION_NODE_ID;
  }
}
