import { describe, expect, it, vi } from "vitest";

import selectionListSource from "../routes/teams/challenge-cup/HypothesisSelectionList.tsx?raw";
import selectionPanelSource from "../routes/teams/challenge-cup/HypothesisSelectionPanel.tsx?raw";
import meetingOpsSource from "../routes/teams/research-workflow/HypothesisFirstMeetingOps.tsx?raw";
import timelineSource from "../routes/teams/TeamHypothesisRoundTimeline.tsx?raw";
import meetingPanelSource from "../routes/teams/TeamMeetingRoundPanel.tsx?raw";
import { clearControlToken, seedControlTokenForTests } from "./client";
import {
  executeHypothesisFirstCommand,
  fetchCollectionRequests,
  fetchHypothesisFirstStateV2,
  fetchHypothesisSelectionContext,
  fetchHypothesisSelections,
  fetchLatestHypothesisSelection,
  fetchReviewRoundLinks,
  parseClaimBeliefGate,
  recordHypothesisSelection,
} from "./hypothesisFirst";
import apiSource from "./hypothesisFirst.ts?raw";
import typesSource from "./types/hypothesisFirst.ts?raw";

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
    expect(apiSource).not.toContain("export function fetchHypothesisFirstChainState");
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
    // SCI-049 async command window transports.
    expect(apiSource).toContain("export function fetchHypothesisFirstCommandAttempt");
    expect(apiSource).toContain("/hypothesis-first/chain/command-attempts/");
  });

  it("polls an accepted command attempt to its terminal envelope (SCI-049)", async () => {
    vi.useFakeTimers();
    const action = {
      kind: "command",
      command: "record_selection",
      actionId: "action:record-selection",
      idempotencyKey: "idem:record-selection",
      expectedStateVersion: "state-1",
      payload: {
        questionId: "SCI-002",
        generationAttemptId: "generation-1",
      },
    } as never;
    const responses: Array<() => Response> = [
      () => Response.json({
        schemaVersion: 2,
        teamId: "team-1",
        questionId: "SCI-002",
        command: "record_selection",
        actionId: "action:record-selection",
        idempotencyKey: "idem:record-selection",
        acceptedStateVersion: "state-1",
        status: "accepted",
        commandAttemptId: "hf2-attempt-1",
      }),
      () => Response.json({
        schemaVersion: 1,
        contract: "hypothesis-first-command-attempt/v1",
        teamId: "team-1",
        attemptId: "hf2-attempt-1",
        questionId: "SCI-002",
        command: "record_selection",
        actionId: "action:record-selection",
        idempotencyKey: "idem:record-selection",
        status: "running",
      }),
      () => Response.json({
        schemaVersion: 1,
        contract: "hypothesis-first-command-attempt/v1",
        teamId: "team-1",
        attemptId: "hf2-attempt-1",
        questionId: "SCI-002",
        command: "record_selection",
        actionId: "action:record-selection",
        idempotencyKey: "idem:record-selection",
        status: "succeeded",
        result: { selectionId: "hsel-1" },
      }),
    ];
    const fetchMock = vi.fn(async () => {
      const next = responses.shift();
      return next ? next() : new Response("{}", { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();
    try {
      const pending = executeHypothesisFirstCommand("team-1", "SCI-002", action, { candidateIds: ["candidate-1"] });
      const settled = vi.fn();
      pending.then(settled, settled);
      // First window spans exactly one poll cycle (poll fires at t=1.5s and
      // still reports "running"): a non-terminal attempt must not settle the
      // accepted POST.
      await vi.advanceTimersByTimeAsync(2_000);
      expect(settled).toHaveBeenCalledTimes(0);
      // Second cycle (t=3s) reports "succeeded"; only the terminal poll
      // resolves the envelope with the stored result.
      await vi.advanceTimersByTimeAsync(5_000);
      const [resolution] = settled.mock.calls[0];
      expect(resolution).toEqual(
        expect.objectContaining({ status: "executed", result: { selectionId: "hsel-1" } }),
      );
      const attemptUrls = fetchMock.mock.calls.map(([input]) => String(input))
        .filter((url) => url.includes("/chain/command-attempts/hf2-attempt-1"));
      expect(attemptUrls.length).toBeGreaterThanOrEqual(2);
      await expect(pending).resolves.toEqual(
        expect.objectContaining({ status: "executed", result: { selectionId: "hsel-1" } }),
      );
    } finally {
      vi.useRealTimers();
      clearControlToken();
      vi.unstubAllGlobals();
    }
  });

  it("rejects with the stored domain error when the attempt fails (SCI-049)", async () => {
    vi.useFakeTimers();
    const action = {
      kind: "command",
      command: "approve_summary",
      actionId: "action:approve-summary:hyp-a",
      idempotencyKey: "idem:approve-summary",
      expectedStateVersion: "state-1",
      payload: { meetingRoundId: "meeting-1" },
    } as never;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json({
        schemaVersion: 2,
        teamId: "team-1",
        questionId: "SCI-002",
        command: "approve_summary",
        actionId: "action:approve-summary:hyp-a",
        idempotencyKey: "idem:approve-summary",
        acceptedStateVersion: "state-1",
        status: "accepted",
        commandAttemptId: "hf2-attempt-2",
      }))
      .mockResolvedValue(Response.json({
        schemaVersion: 1,
        contract: "hypothesis-first-command-attempt/v1",
        teamId: "team-1",
        attemptId: "hf2-attempt-2",
        questionId: "SCI-002",
        command: "approve_summary",
        actionId: "action:approve-summary:hyp-a",
        idempotencyKey: "idem:approve-summary",
        status: "failed",
        error: {
          code: "state_version_conflict",
          message: "流程状态已更新，请刷新当前题目后重新确认。",
          statusCode: 409,
        },
      }));
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();
    try {
      const pending = executeHypothesisFirstCommand("team-1", "SCI-002", action, { decision: "accepted" });
      const captured: unknown[] = [];
      pending.catch((error) => captured.push(error));
      await vi.advanceTimersByTimeAsync(5_000);
      const error = captured[0] as Error & { status?: number; code?: string };
      expect(error).toBeInstanceOf(Error);
      expect(error.status).toBe(409);
      expect(error.code).toBe("state_version_conflict");
      // The domain error shape must stay classifier-compatible so panels can
      // render the state-conflict copy instead of a generic failure.
      await expect(pending).rejects.toMatchObject({ code: "state_version_conflict", status: 409 });
    } finally {
      vi.useRealTimers();
      clearControlToken();
      vi.unstubAllGlobals();
    }
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
    expect(selectionListSource).toContain("executeHypothesisFirstCommand");
    expect(meetingOpsSource).toContain("executeHypothesisFirstCommand");
    expect(meetingOpsSource).not.toContain("draftMeetingSummary");
    expect(meetingOpsSource).not.toContain("approveHypothesisDigest");
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
