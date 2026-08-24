import { describe, expect, it } from "vitest";

import type {
  MeetingRoundRecord,
  ReviewRoundLinkRecord,
} from "../../../api/types/hypothesisFirst";
import {
  buildHypothesisFirstReviewProjection,
  currentProjectedReview,
} from "./hypothesisFirstMeetingProjection";

function meeting(id: string, startedAt: string): MeetingRoundRecord {
  return {
    program: "p",
    theme: "t",
    campaign: "c",
    question: "SCI-001",
    branch: "b",
    workflow: "w",
    agentId: "a",
    meetingRoundId: id,
    meetingType: "hypothesis_review",
    mode: "review",
    scopeHash: "scope",
    participants: [],
    status: id === "r5" ? "summarizing" : "closed",
    startedAt,
  };
}

function link(id: string, roundIndex: number, candidateId = `cand-${id}`): ReviewRoundLinkRecord {
  return {
    schemaVersion: 1,
    recordKind: "hypothesis_first_review_round_link",
    linkId: `link-${id}`,
    meetingRoundId: id,
    previousMeetingRoundId: roundIndex > 1 ? `r${roundIndex - 1}` : "",
    selectionId: "selection-1",
    collectionRequestId: "",
    questionId: "SCI-001",
    roundIndex,
    candidateId,
    createdAt: `2026-08-20T0${roundIndex}:00:01Z`,
  };
}

describe("buildHypothesisFirstReviewProjection", () => {
  it("uses lineage links when historical meetings have no round metadata", () => {
    const projection = buildHypothesisFirstReviewProjection(
      [
        meeting("r5", "2026-08-20T05:00:00Z"),
        meeting("r1", "2026-08-20T01:00:00Z"),
        meeting("r3", "2026-08-20T03:00:00Z"),
      ],
      [link("r1", 1), link("r3", 3), link("r5", 5)],
    );

    expect(projection.rounds.map((round) => round.nodeId)).toEqual([
      "hf_meeting_1_cand-r1",
      "hf_meeting_3_cand-r3",
      "hf_meeting_5_cand-r5",
    ]);
    expect(currentProjectedReview(projection)?.meeting.meetingRoundId).toBe("r5");
    expect(projection.byNodeId.get("hf_meeting_5_cand-r5")?.meeting.meetingRoundId).toBe("r5");
    expect(projection.unresolvedMeetingIds).toEqual([]);
  });

  it("keeps two candidates in the same round with stable distinct node ids", () => {
    const projection = buildHypothesisFirstReviewProjection(
      [meeting("r5-a", "2026-08-20T05:00:00Z"), meeting("r5-b", "2026-08-20T05:01:00Z")],
      [link("r5-a", 5, "cand-a"), link("r5-b", 5, "cand-b")],
    );

    expect(projection.rounds.map((round) => round.nodeId)).toEqual([
      "hf_meeting_5_cand-a",
      "hf_meeting_5_cand-b",
    ]);
    expect(projection.byNodeId.get("hf_meeting_5_cand-a")?.meeting.meetingRoundId).toBe("r5-a");
    expect(projection.byNodeId.get("hf_meeting_5_cand-b")?.meeting.meetingRoundId).toBe("r5-b");
    expect(projection.unresolvedMeetingIds).toEqual([]);
  });

  it("fails closed when a candidate is missing or duplicated within a selection round", () => {
    const missingCandidate = buildHypothesisFirstReviewProjection(
      [meeting("r5", "2026-08-20T05:00:00Z")],
      [{ ...link("r5", 5), candidateId: "" }],
    );
    expect(missingCandidate.rounds).toEqual([]);
    expect(missingCandidate.unresolvedMeetingIds).toEqual(["r5"]);

    const duplicateCandidate = buildHypothesisFirstReviewProjection(
      [meeting("r5-a", "2026-08-20T05:00:00Z"), meeting("r5-b", "2026-08-20T05:01:00Z")],
      [link("r5-a", 5, "cand-a"), link("r5-b", 5, "cand-a")],
    );
    expect(duplicateCandidate.rounds).toEqual([]);
    expect(duplicateCandidate.unresolvedMeetingIds).toEqual(["r5-a", "r5-b"]);
  });

  it("fails closed when one meeting has duplicate lineage links", () => {
    const projection = buildHypothesisFirstReviewProjection(
      [meeting("r5", "2026-08-20T05:00:00Z")],
      [link("r5", 5), { ...link("r5", 3), linkId: "link-r5-conflict" }],
    );

    expect(projection.byMeetingId.has("r5")).toBe(false);
    expect(projection.unresolvedMeetingIds).toEqual(["r5"]);
  });

  it("scopes the projection to the current selection when one question has multiple lineages", () => {
    const projection = buildHypothesisFirstReviewProjection(
      [
        { ...meeting("old-r9", "2026-08-20T09:00:00Z"), selectionId: "selection-1", roundIndex: 9 },
        { ...meeting("current-r1", "2026-08-20T01:00:00Z"), selectionId: "selection-2", roundIndex: 1 },
        { ...meeting("current-r2", "2026-08-20T02:00:00Z"), selectionId: "selection-2", roundIndex: 2 },
      ],
      [
        { ...link("old-r9", 9), selectionId: "selection-1" },
        { ...link("current-r1", 1), selectionId: "selection-2" },
        { ...link("current-r2", 2), selectionId: "selection-2", previousMeetingRoundId: "current-r1" },
      ],
      "selection-2",
    );

    expect(projection.rounds.map((round) => round.meeting.meetingRoundId)).toEqual([
      "current-r1",
      "current-r2",
    ]);
    expect(projection.byNodeId.has("hf_meeting_9_cand-old-r9")).toBe(false);
    expect(projection.unresolvedMeetingIds).toEqual([]);
  });
});
