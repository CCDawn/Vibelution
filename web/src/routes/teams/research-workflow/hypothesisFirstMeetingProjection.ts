import type {
  MeetingRoundRecord,
  ReviewRoundLinkRecord,
} from "../../../api/types/hypothesisFirst";

const REVIEW_MEETING_TYPE = "hypothesis_review";
const REVIEW_NODE_PREFIX = "hf_meeting_";

export type ProjectedReviewMeeting = {
  meeting: MeetingRoundRecord;
  nodeId: string;
  selectionId: string;
  roundIndex: number;
  candidateId: string;
  candidateOrder: number;
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

function reviewNodeId(roundIndex: number, candidateId: string): string {
  return `${REVIEW_NODE_PREFIX}${roundIndex}_${encodeURIComponent(candidateId)}`;
}

function projectionKey(selectionId: string, roundIndex: number, candidateId: string): string {
  return JSON.stringify([selectionId, roundIndex, candidateId]);
}

function candidateOrder(link: ReviewRoundLinkRecord | undefined): number {
  const value = link?.candidateOrder;
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : Number.MAX_SAFE_INTEGER;
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
  const hasSelectionScopedLinks = (links ?? []).some((link) => normalizedId(link.selectionId));
  const scopedLinks = currentSelectionId && hasSelectionScopedLinks
    ? (links ?? []).filter((link) => normalizedId(link.selectionId) === currentSelectionId)
    : (links ?? []);
  for (const link of scopedLinks) {
    const meetingLinks = linksByMeetingId.get(link.meetingRoundId) ?? [];
    meetingLinks.push(link);
    linksByMeetingId.set(link.meetingRoundId, meetingLinks);
  }
  const scopedMeetings = (meetings ?? [])
    .filter((meeting) => meeting.meetingType === REVIEW_MEETING_TYPE)
    .filter((meeting) => {
      if (!currentSelectionId || !hasSelectionScopedLinks) return true;
      const meetingSelectionId = normalizedId(meeting.selectionId);
      if (meetingSelectionId) return meetingSelectionId === currentSelectionId;
      return linksByMeetingId.has(meeting.meetingRoundId);
    });
  const candidates = scopedMeetings
    .map((meeting) => {
      const meetingLinks = linksByMeetingId.get(meeting.meetingRoundId) ?? [];
      if (meetingLinks.length > 1) return null;
      const link = meetingLinks[0];
      // A linked review round is candidate-specific. Never make an arbitrary
      // choice when the backend cannot tell us which selected candidate owns it.
      if (link && !normalizedId(link.candidateId)) return null;
      const roundIndex = validRoundIndex(link?.roundIndex)
        ?? validRoundIndex(meeting.roundIndex);
      if (roundIndex === null) return null;
      const linkedSelectionId = normalizedId(link?.selectionId);
      const candidateId = normalizedId(link?.candidateId) || `legacy:${meeting.meetingRoundId}`;
      return {
        meeting,
        selectionId: linkedSelectionId || normalizedId(meeting.selectionId) || "legacy",
        nodeId: link ? reviewNodeId(roundIndex, candidateId) : `${REVIEW_NODE_PREFIX}${roundIndex}`,
        roundIndex,
        candidateId,
        candidateOrder: candidateOrder(link),
        previousMeetingRoundId: String(
          link?.previousMeetingRoundId || meeting.previousMeetingRoundId || "",
        ),
      } satisfies ProjectedReviewMeeting;
    })
    .filter((round): round is ProjectedReviewMeeting => round !== null);

  const countByProjectionKey = new Map<string, number>();
  const countByNodeId = new Map<string, number>();
  for (const round of candidates) {
    const key = projectionKey(round.selectionId, round.roundIndex, round.candidateId);
    countByProjectionKey.set(key, (countByProjectionKey.get(key) ?? 0) + 1);
    countByNodeId.set(round.nodeId, (countByNodeId.get(round.nodeId) ?? 0) + 1);
  }
  const rounds = candidates
    .filter((round) => countByProjectionKey.get(projectionKey(
      round.selectionId,
      round.roundIndex,
      round.candidateId,
    )) === 1 && countByNodeId.get(round.nodeId) === 1)
    .sort((left, right) => {
      if (left.roundIndex !== right.roundIndex) return left.roundIndex - right.roundIndex;
      if (left.candidateOrder !== right.candidateOrder) {
        return left.candidateOrder - right.candidateOrder;
      }
      const byCandidate = left.candidateId.localeCompare(right.candidateId);
      if (byCandidate !== 0) return byCandidate;
      return String(left.meeting.startedAt ?? "").localeCompare(String(right.meeting.startedAt ?? ""));
    });
  const byMeetingId = new Map(rounds.map((round) => [round.meeting.meetingRoundId, round]));
  const byNodeId = new Map(rounds.map((round) => [round.nodeId, round]));
  const unresolvedMeetingIds = scopedMeetings
    .filter((meeting) => !byMeetingId.has(meeting.meetingRoundId))
    .map((meeting) => meeting.meetingRoundId);

  return { rounds, byMeetingId, byNodeId, unresolvedMeetingIds };
}

export function currentProjectedReview(
  projection: HypothesisFirstReviewProjection,
): ProjectedReviewMeeting | null {
  return projection.rounds[projection.rounds.length - 1] ?? null;
}

/** The next writable review is still server-authored; this only chooses a
 * stable card for navigation while preserving every sibling in the projection. */
export function currentActionableProjectedReview(
  projection: HypothesisFirstReviewProjection,
): ProjectedReviewMeeting | null {
  return [...projection.rounds].reverse().find((round) => round.meeting.status !== "closed") ?? null;
}
