import type {
  MeetingRoundRecord,
  ReviewRoundLinkRecord,
} from "../../../api/types/hypothesisFirst";

const REVIEW_MEETING_TYPE = "hypothesis_review";
const REVIEW_NODE_PREFIX = "hf_meeting_";

export type ProjectedReviewMeeting = {
  meeting: MeetingRoundRecord;
  nodeId: string;
  roundIndex: number;
  previousMeetingRoundId: string;
};

export type HypothesisFirstReviewProjection = {
  rounds: ProjectedReviewMeeting[];
  byMeetingId: ReadonlyMap<string, ProjectedReviewMeeting>;
  byNodeId: ReadonlyMap<string, ProjectedReviewMeeting>;
  unresolvedMeetingIds: readonly string[];
};

function validRoundIndex(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function normalizedId(value: unknown): string {
  return String(value ?? "").trim();
}

/**
 * Join review meetings to the chain lineage by stable meeting id.
 *
 * The meeting ledger predates roundIndex/previousMeetingRoundId, while the
 * review-link ledger is the chain authority for both fields. UI navigation
 * must consume this projection instead of guessing that a missing index is 1.
 */
export function buildHypothesisFirstReviewProjection(
  meetings: readonly MeetingRoundRecord[] | null | undefined,
  links: readonly ReviewRoundLinkRecord[] | null | undefined,
  selectionId?: string | null,
): HypothesisFirstReviewProjection {
  const currentSelectionId = normalizedId(selectionId);
  const linksByMeetingId = new Map<string, ReviewRoundLinkRecord[]>();
  const scopedLinks = currentSelectionId
    ? (links ?? []).filter((link) => normalizedId(link.selectionId) === currentSelectionId)
    : (links ?? []);
  for (const link of scopedLinks) {
    const meetingLinks = linksByMeetingId.get(link.meetingRoundId) ?? [];
    meetingLinks.push(link);
    linksByMeetingId.set(link.meetingRoundId, meetingLinks);
  }
  const candidates = (meetings ?? [])
    .filter((meeting) => meeting.meetingType === REVIEW_MEETING_TYPE)
    .filter((meeting) => {
      if (!currentSelectionId) return true;
      const meetingSelectionId = normalizedId(meeting.selectionId);
      if (meetingSelectionId) return meetingSelectionId === currentSelectionId;
      return linksByMeetingId.has(meeting.meetingRoundId);
    })
    .map((meeting) => {
      const meetingLinks = linksByMeetingId.get(meeting.meetingRoundId) ?? [];
      if (meetingLinks.length > 1) return null;
      const link = meetingLinks[0];
      const roundIndex = validRoundIndex(link?.roundIndex)
        ?? validRoundIndex(meeting.roundIndex);
      if (roundIndex === null) return null;
      return {
        meeting,
        nodeId: `${REVIEW_NODE_PREFIX}${roundIndex}`,
        roundIndex,
        previousMeetingRoundId: String(
          link?.previousMeetingRoundId || meeting.previousMeetingRoundId || "",
        ),
      } satisfies ProjectedReviewMeeting;
    })
    .filter((round): round is ProjectedReviewMeeting => round !== null);

  const countByRoundIndex = new Map<number, number>();
  for (const round of candidates) {
    countByRoundIndex.set(round.roundIndex, (countByRoundIndex.get(round.roundIndex) ?? 0) + 1);
  }
  const rounds = candidates
    .filter((round) => countByRoundIndex.get(round.roundIndex) === 1)
    .sort((left, right) => {
      if (left.roundIndex !== right.roundIndex) return left.roundIndex - right.roundIndex;
      return String(left.meeting.startedAt ?? "").localeCompare(String(right.meeting.startedAt ?? ""));
    });
  const byMeetingId = new Map(rounds.map((round) => [round.meeting.meetingRoundId, round]));
  const byNodeId = new Map(rounds.map((round) => [round.nodeId, round]));
  const unresolvedMeetingIds = (meetings ?? [])
    .filter((meeting) => meeting.meetingType === REVIEW_MEETING_TYPE)
    .filter((meeting) => !byMeetingId.has(meeting.meetingRoundId))
    .map((meeting) => meeting.meetingRoundId);

  return { rounds, byMeetingId, byNodeId, unresolvedMeetingIds };
}

export function currentProjectedReview(
  projection: HypothesisFirstReviewProjection,
): ProjectedReviewMeeting | null {
  return projection.rounds[projection.rounds.length - 1] ?? null;
}
