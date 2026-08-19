import { describe, expect, it } from "vitest";

import apiSource from "./hypothesisFirst.ts?raw";
import typesSource from "./types/hypothesisFirst.ts?raw";
import selectionPanelSource from "../routes/teams/challenge-cup/HypothesisSelectionPanel.tsx?raw";
import meetingPanelSource from "../routes/teams/TeamMeetingRoundPanel.tsx?raw";
import timelineSource from "../routes/teams/TeamHypothesisRoundTimeline.tsx?raw";
import meetingOpsSource from "../routes/teams/research-workflow/HypothesisFirstMeetingOps.tsx?raw";
import selectionListSource from "../routes/teams/challenge-cup/HypothesisSelectionList.tsx?raw";

describe("hypothesis-first API", () => {
  it("owns the hypothesis-first selection transports", () => {
    expect(apiSource).toContain("export function recordHypothesisSelection");
    expect(apiSource).toContain("export function fetchHypothesisSelections");
    expect(apiSource).toContain("export function fetchLatestHypothesisSelection");
    expect(apiSource).toContain("export function fetchHypothesisSelectionContext");
    expect(apiSource).toContain("/hypothesis-first/selections");
    expect(apiSource).toContain("/selection-context");
  });

  it("owns the meeting-round transports", () => {
    expect(apiSource).toContain("export function fetchMeetingRounds");
    expect(apiSource).toContain("export function fetchMeetingRoundSourceMessages");
    expect(apiSource).toContain("export function beginMeetingSummary");
    expect(apiSource).toContain("export function draftMeetingSummary");
    expect(apiSource).toContain("export function approveHypothesisDigest");
    expect(apiSource).toContain("export function submitMeetingDigestDraft");
    expect(apiSource).toContain("export function rejectMeetingDigestDraft");
    expect(apiSource).toContain("export function approveMeetingClosure");
    expect(apiSource).toContain("/meeting-rounds/");
    expect(apiSource).toContain("/summary-draft");
    expect(apiSource).toContain("/approve-digest");
    expect(apiSource).toContain("force: false");
    expect(apiSource).toContain("expectedDigestContentHash");
  });

  it("owns the hypothesis-round and chain transports", () => {
    expect(apiSource).toContain("export function fetchHypothesisRounds");
    expect(apiSource).toContain("export function fetchHypothesisFirstChainState");
    expect(apiSource).toContain("export function fetchCollectionRequests");
    expect(apiSource).toContain("export function fetchReviewRoundLinks");
    expect(apiSource).toContain("export function closeHypothesisReviewMeeting");
    expect(apiSource).toContain("export function recordCollectionHandoff");
    expect(apiSource).toContain("/hypothesis-rounds");
    expect(apiSource).toContain("/hypothesis-first/chain/state");
  });

  it("publishes typed DTOs for the flow records", () => {
    expect(typesSource).toContain("export type HypothesisSelectionRecord");
    expect(typesSource).toContain("export type HypothesisSelectionContext");
    expect(typesSource).toContain("export type MeetingRoundRecord");
    expect(typesSource).toContain("export type HypothesisRoundRecord");
    expect(typesSource).toContain("export type HypothesisFirstChainState");
    expect(typesSource).toContain("export type CollectionRequestRecord");
    expect(typesSource).toContain("export type MeetingProposedCandidate");
    expect(typesSource).toContain("export type MeetingEvidenceRequestDraft");
    expect(typesSource).toContain("proposedCandidates?: MeetingProposedCandidate[]");
    expect(typesSource).toContain("evidenceRequests?: MeetingEvidenceRequestDraft[]");
    expect(typesSource).toContain("requirements?: Record<string, unknown>");
    expect(typesSource).not.toContain("requirements?: string[]");
  });

  it("keeps consuming panels free of raw API paths", () => {
    for (const source of [selectionPanelSource, meetingPanelSource, timelineSource]) {
      expect(source).not.toContain("/api/teams/");
      expect(source).not.toContain("fetchJson");
    }
    expect(selectionPanelSource).toContain("fetchHypothesisSelectionContext");
    expect(meetingPanelSource).not.toContain("closeHypothesisReviewMeeting");
    expect(meetingPanelSource).not.toContain("beginMeetingSummary");
    expect(meetingPanelSource).not.toContain("submitMeetingDigestDraft");
    expect(selectionListSource).toContain("recordHypothesisSelection");
    expect(meetingOpsSource).toContain("draftMeetingSummary");
    expect(meetingOpsSource).toContain("approveHypothesisDigest");
    expect(meetingOpsSource).not.toContain("beginMeetingSummary");
    expect(meetingOpsSource).not.toContain("closeHypothesisReviewMeeting");
    expect(meetingOpsSource).not.toContain("submitMeetingDigestDraft");
    expect(timelineSource).toContain("fetchHypothesisRounds");
  });
});
