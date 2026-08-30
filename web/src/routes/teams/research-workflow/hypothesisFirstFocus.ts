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

function normalizedRun(value: string | null | undefined): string {
  return String(value || "").trim();
}

function meetingWorkflowRunId(meeting: MeetingRoundRecord): string {
  const receiptAuthority = (meeting as MeetingRoundRecord & {
    modelInvocationReceiptAuthority?: Record<string, unknown>;
  }).modelInvocationReceiptAuthority;
  const receiptRunId = normalizedRun(
    typeof receiptAuthority?.workflowRunId === "string"
      ? receiptAuthority.workflowRunId
      : "",
  );
  if (receiptRunId) return receiptRunId;

  const discussionScope = meeting.discussionScope;
  const discussionRunId = normalizedRun(
    typeof discussionScope?.workflowRunId === "string"
      ? discussionScope.workflowRunId
      : "",
  );
  if (discussionRunId) return discussionRunId;

  // Older meetings predate both server-owned identity fields. Keep the old
  // top-level field only as a compatibility fallback after the authorities
  // above have been exhausted.
  return normalizedRun(meeting.workflowRunId);
}

function meetingMatchesRun(meeting: MeetingRoundRecord, runId: string): boolean {
  return !runId || meetingWorkflowRunId(meeting) === runId;
}

export async function fetchHypothesisFirstFocusNode(
  teamId: string,
  questionId: string,
  runId = "",
): Promise<string> {
  const trimmedTeam = teamId.trim();
  const trimmedQuestion = questionId.trim();
  const trimmedRun = normalizedRun(runId);
  if (!trimmedTeam || !trimmedQuestion) {
    return HYPOTHESIS_FIRST_GENERATION_NODE_ID;
  }

  try {
    const stateV2 = await fetchHypothesisFirstStateV2(trimmedTeam, trimmedQuestion, {
      runId: trimmedRun,
    });
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
    fetchHypothesisFirstChainState(trimmedTeam, trimmedQuestion, { runId: trimmedRun }),
    fetchMeetingRounds(trimmedTeam),
    fetchHypothesisSelections(trimmedTeam, trimmedQuestion, { runId: trimmedRun }),
    fetchCollectionRequests(trimmedTeam, trimmedQuestion, { runId: trimmedRun }),
    fetchReviewRoundLinks(trimmedTeam, trimmedQuestion, { runId: trimmedRun }),
  ]);
  const meetings = (meetingList.meetings ?? []).filter((meeting) => (
    meetingMatchesQuestion(meeting, trimmedQuestion)
    && meetingMatchesRun(meeting, trimmedRun)
  ));
  const meetingIds = new Set(meetings.map((meeting) => String(meeting.meetingRoundId || "")));
  const selections = (selectionList.selections ?? []).filter((selection) => (
    (!trimmedRun || normalizedRun(selection.workflowRunId) === trimmedRun)
  ));
  const requests = (requestList.requests ?? []).filter((request) => (
    !trimmedRun || meetingIds.has(String(request.meetingRoundId || ""))
  ));
  const reviewRoundLinks = (reviewLinkList.links ?? []).filter((link) => (
    !trimmedRun || meetingIds.has(String(link.meetingRoundId || ""))
  ));
  const next = resolveHypothesisFirstNextAction({
    run: { runId: trimmedRun || "present" },
    chainState,
    meetings,
    reviewRoundLinks,
    selection: latestSelection(selections),
    collectionRequests: requests,
  });
  return focusNodeFromNextAction(next);
}
