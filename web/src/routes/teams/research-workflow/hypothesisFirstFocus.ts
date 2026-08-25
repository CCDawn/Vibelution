/**
 * Resolve the canvas node to land on after create-run or experiment switch.
 *
 * Toolbar/URL must follow the typed next-action model, not checkpoint
 * `source_finding`. The canonical V2 snapshot is authoritative; V1 reads are
 * only a compatibility path for servers that explicitly lack state-v2.
 */
import {
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisFirstStateV2,
  fetchHypothesisSelections,
  fetchMeetingRounds,
  fetchReviewRoundLinks,
  isHypothesisFirstStateV2EndpointUnavailable,
} from "../../../api/hypothesisFirst";
import type { MeetingRoundRecord } from "../../../api/types/hypothesisFirst";
import { HYPOTHESIS_FIRST_GENERATION_NODE_ID } from "./hypothesisFirstCanvasRegion";
import {
  focusNodeFromNextAction,
  resolveHypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";
import { resolveHypothesisFirstNextActionFromV2 } from "./hypothesisFirstStateV2Adapter";

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
    const stateV2 = await fetchHypothesisFirstStateV2(trimmedTeam, trimmedQuestion);
    const fatalProblem = stateV2.problems.find((problem) => problem.severity === "fatal");
    if (fatalProblem) {
      throw new Error(fatalProblem.message || `Hypothesis-first state is fatal: ${fatalProblem.code}`);
    }
    return focusNodeFromNextAction(resolveHypothesisFirstNextActionFromV2(stateV2));
  } catch (error) {
    // V1 is a compatibility path for installations whose server has not
    // exposed state-v2 yet. Domain failures, malformed DTOs, and server
    // errors must remain visible to the caller instead of looking initial.
    if (!isHypothesisFirstStateV2EndpointUnavailable(error)) {
      throw error;
    }
  }

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
}
