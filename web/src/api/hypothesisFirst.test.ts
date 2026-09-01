import { describe, expect, it, vi } from "vitest";

import { clearControlToken, FetchJsonHttpError, seedControlTokenForTests } from "./client";
import {
  executeHypothesisFirstCommand,
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisFirstStateV2,
  fetchLatestHypothesisSelection,
  fetchHypothesisSelections,
  fetchHypothesisSelectionContext,
  fetchReviewRoundLinks,
  parseClaimBeliefGate,
  recordHypothesisSelection,
} from "./hypothesisFirst";
import { isHypothesisFirstStateV2EndpointUnavailable } from "./hypothesisFirst";
import apiSource from "./hypothesisFirst.ts?raw";
import typesSource from "./types/hypothesisFirst.ts?raw";
import selectionPanelSource from "../routes/teams/challenge-cup/HypothesisSelectionPanel.tsx?raw";
import meetingPanelSource from "../routes/teams/TeamMeetingRoundPanel.tsx?raw";
import timelineSource from "../routes/teams/TeamHypothesisRoundTimeline.tsx?raw";
import meetingOpsSource from "../routes/teams/research-workflow/HypothesisFirstMeetingOps.tsx?raw";
import selectionListSource from "../routes/teams/challenge-cup/HypothesisSelectionList.tsx?raw";

describe("hypothesis-first API", () => {
  it("keeps every run-scoped read and command transport on the requested workflow run", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();

    const action = {
      kind: "command",
      command: "record_selection",
      actionId: "action:record-selection",
      idempotencyKey: "idem:record-selection",
      expectedStateVersion: "state-1",
      payload: {
        questionId: "SCI-002",
        generationAttemptId: "generation-1",
        workflowRunId: "run-current",
      },
    } as never;

    try {
      await Promise.allSettled([
        fetchHypothesisSelections("team-1", "SCI-002", { runId: "run-current" }),
        fetchLatestHypothesisSelection("team-1", "SCI-002", { runId: "run-current" }),
        fetchHypothesisSelectionContext("team-1", "SCI-002", { runId: "run-current" }),
        fetchHypothesisFirstChainState("team-1", "SCI-002", { runId: "run-current" }),
        fetchHypothesisFirstStateV2("team-1", "SCI-002", { runId: "run-current" }),
        fetchCollectionRequests("team-1", "SCI-002", { runId: "run-current" }),
        fetchReviewRoundLinks("team-1", "SCI-002", { runId: "run-current" }),
        recordHypothesisSelection("team-1", {
          workflowRunId: "run-current",
          questionId: "SCI-002",
          selectedCandidateIds: ["candidate-1"],
        } as never),
        executeHypothesisFirstCommand("team-1", "SCI-002", action, { candidateIds: ["candidate-1"] }),
      ]);

      const urls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(urls).toContain("/api/teams/team-1/workflow-orchestration/hypothesis-first/selections?questionId=SCI-002&runId=run-current");
      expect(urls).toContain("/api/teams/team-1/workflow-orchestration/hypothesis-first/selections/latest?questionId=SCI-002&runId=run-current");
      expect(urls).toContain("/api/teams/team-1/workflow-orchestration/hypothesis-first/questions/SCI-002/selection-context?runId=run-current");
      expect(urls).toContain("/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/state?questionId=SCI-002&runId=run-current");
      expect(urls).toContain("/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/state-v2?questionId=SCI-002&runId=run-current");
      expect(urls).toContain("/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/collection-requests?questionId=SCI-002&runId=run-current");
      expect(urls).toContain("/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/review-round-links?questionId=SCI-002&runId=run-current");
      expect(urls).toContain("/api/teams/team-1/workflow-orchestration/hypothesis-first/chain/commands?questionId=SCI-002&runId=run-current");
      const selectionWrite = fetchMock.mock.calls.find(([input, init]) => (
        String(input).endsWith("/hypothesis-first/selections")
        && String((init as RequestInit | undefined)?.method).toUpperCase() === "POST"
      ));
      expect(selectionWrite).toBeDefined();
      expect(JSON.parse(String((selectionWrite?.[1] as RequestInit).body))).toEqual(
        expect.objectContaining({ workflowRunId: "run-current" }),
      );
    } finally {
      clearControlToken();
      vi.unstubAllGlobals();
    }
  });

  it("falls back only for an absent route, not a domain 404", () => {
    expect(isHypothesisFirstStateV2EndpointUnavailable(new FetchJsonHttpError(
      JSON.stringify({ detail: "Not Found" }),
      { status: 404, details: { detail: "Not Found" } },
    ))).toBe(true);
    expect(isHypothesisFirstStateV2EndpointUnavailable(new FetchJsonHttpError(
      JSON.stringify({ detail: { code: "catalog_question_unknown" } }),
      {
        status: 404,
        code: "catalog_question_unknown",
        details: { detail: { code: "catalog_question_unknown" } },
      },
    ))).toBe(false);
  });

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
    expect(apiSource).toContain("export function fetchHypothesisFirstStateV2");
    expect(apiSource).toContain("export function executeHypothesisFirstCommand");
    expect(apiSource).toContain("export function fetchCollectionRequests");
    expect(apiSource).toContain("export function fetchReviewRoundLinks");
    expect(apiSource).toContain("export function closeHypothesisReviewMeeting");
    expect(apiSource).toContain("export function recordCollectionHandoff");
    expect(apiSource).toContain("export function recoverCollectionRequest");
    expect(apiSource).toContain("/collection-requests/");
    expect(apiSource).toContain("/recover");
    expect(apiSource).toContain("/hypothesis-rounds");
    expect(apiSource).toContain("/hypothesis-first/chain/state");
    expect(apiSource).toContain("/hypothesis-first/chain/state-v2");
    expect(apiSource).toContain("/hypothesis-first/chain/commands");
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

describe("parseClaimBeliefGate", () => {
  it("returns null when the gate did not run", () => {
    expect(parseClaimBeliefGate(null)).toBeNull();
    expect(parseClaimBeliefGate(undefined)).toBeNull();
  });

  it("normalizes a blocked verdict with its claims and evidence gaps", () => {
    const gate = parseClaimBeliefGate({
      decisionPoint: "converge_question",
      roundId: "hr-2",
      candidateId: "cand-1",
      status: "blocked",
      reason: "claim_belief_state_blocked",
      claims: [{ claimId: "claim-1", beliefState: "contradicted", acceptedSupportCount: 1 }],
      blockedClaims: [
        { claimId: "claim-1", beliefState: "contradicted", counterEvidenceIds: ["ev-9"] },
        { beliefState: "disputed" },
        "noise",
      ],
      evidenceGaps: [{ claimId: "claim-1", gap: "accepted_support_missing" }, { gap: "" }],
    });
    expect(gate?.status).toBe("blocked");
    expect(gate?.reason).toBe("claim_belief_state_blocked");
    expect(gate?.candidateId).toBe("cand-1");
    expect(gate?.claims).toEqual([
      { claimId: "claim-1", beliefState: "contradicted", acceptedSupportCount: 1 },
    ]);
    expect(gate?.blockedClaims).toEqual([
      { claimId: "claim-1", beliefState: "contradicted", counterEvidenceIds: ["ev-9"] },
    ]);
    expect(gate?.evidenceGaps).toEqual([{ claimId: "claim-1", gap: "accepted_support_missing" }]);
  });

  it("fails closed to status unknown for malformed payloads instead of throwing", () => {
    for (const malformed of ["noise", 42, {}, { status: 42, blockedClaims: "x" }]) {
      const gate = parseClaimBeliefGate(malformed);
      expect(gate?.status).toBe("unknown");
      expect(gate?.claims).toEqual([]);
      expect(gate?.blockedClaims).toEqual([]);
      expect(gate?.evidenceGaps).toEqual([]);
    }
  });
});
