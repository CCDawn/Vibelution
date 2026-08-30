import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisFirstStateV2,
  fetchHypothesisSelections,
  fetchMeetingRounds,
  fetchReviewRoundLinks,
} from "../../../api/hypothesisFirst";
import { FetchJsonHttpError } from "../../../api/client";
import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";

vi.mock("../../../api/hypothesisFirst", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/hypothesisFirst")>();
  return {
    ...actual,
    fetchHypothesisFirstChainState: vi.fn(),
    fetchHypothesisFirstStateV2: vi.fn(),
    fetchMeetingRounds: vi.fn(),
    fetchHypothesisSelections: vi.fn(),
    fetchCollectionRequests: vi.fn(),
    fetchReviewRoundLinks: vi.fn(),
  };
});

const mockedState = vi.mocked(fetchHypothesisFirstChainState);
const mockedStateV2 = vi.mocked(fetchHypothesisFirstStateV2);
const mockedMeetings = vi.mocked(fetchMeetingRounds);
const mockedSelections = vi.mocked(fetchHypothesisSelections);
const mockedRequests = vi.mocked(fetchCollectionRequests);
const mockedReviewLinks = vi.mocked(fetchReviewRoundLinks);

function unavailableV2Error(status = 404): FetchJsonHttpError {
  return new FetchJsonHttpError("Not Found", {
    status,
    details: status === 404 ? { detail: "Not Found" } : undefined,
  });
}

function phase(overrides: Record<string, unknown> = {}) {
  return {
    lifecycle: "not_started",
    outcome: "none",
    actionability: "available",
    attempt: null,
    updatedAt: null,
    problems: [],
    ...overrides,
  };
}

function stateV2(overrides: Record<string, unknown> = {}) {
  const base = {
    schemaVersion: 2,
    contract: "hypothesis-first-state/v2",
    teamId: "team-1",
    questionId: "SCI-002",
    stateVersion: "state-1",
    representationVersion: "representation-1",
    computedAt: "2026-08-19T00:00:00Z",
    scope: {
      questionInOfficialCatalog: true,
      catalogId: "catalog-1",
      catalogSha256: "sha-1",
    },
    resetBoundary: {
      resetId: "origin",
      resetAt: null,
      source: "origin",
    },
    isInitial: true,
    awaitingHumanCount: 0,
    currentPhase: "generation",
    overall: phase(),
    generation: {
      ...phase(),
      generationMeetingId: null,
      candidateCount: 0,
      candidateIds: [],
    },
    selection: {
      ...phase(),
      selectionId: null,
      selectedCandidateIds: [],
    },
    review: {
      ...phase(),
      activeRoundIndex: null,
      aggregate: { total: 0, completed: 0, pending: 0, failed: 0, blocked: 0 },
      candidates: [],
    },
    collection: {
      ...phase(),
      aggregate: { total: 0, completed: 0, pending: 0, failed: 0, blocked: 0 },
      requests: [],
    },
    convergence: {
      ...phase(),
      latestHypothesisRoundId: null,
      accepted: false,
      roundIndex: 0,
      roundBudget: 0,
    },
    formalRuntime: {
      ...phase(),
      runId: null,
      runVersion: null,
      runStatus: null,
      completionKind: null,
      lineageDisposition: null,
      isCurrentRevision: true,
      parentRunId: null,
      childRunIds: [],
      currentNodeIds: [],
    },
    programDelivery: {
      ...phase(),
      deliveryStatus: "not_started",
      deliveryArtifactRef: null,
      handoffStatus: "not_started",
      outputRecordId: null,
      outputRunId: null,
      humanReviewStatus: "not_started",
      humanGates: {
        decisions: {
          H1_problem_understanding: "pending",
          H2_hypothesis_selection: "pending",
          H3_research_plan: "pending",
          H4_external_output: "pending",
        },
        reviewer: null,
        rationale: null,
        decidedAt: null,
      },
      approvedGateCount: 0,
      requiredGateCount: 4,
    },
    allowedActions: [],
    problems: [],
  };
  return { ...base, ...overrides } as never;
}

describe("fetchHypothesisFirstFocusNode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Existing V1 cases deliberately exercise the compatibility path.
    mockedStateV2.mockRejectedValue(unavailableV2Error());
  });

  it("uses the canonical V2 target node before touching V1 reads", async () => {
    mockedStateV2.mockResolvedValue(stateV2({
      currentPhase: "selection",
      selection: {
        ...phase(),
        selectionId: null,
        selectedCandidateIds: [],
      },
    }));

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_selection");
    expect(mockedStateV2).toHaveBeenCalledWith("team-1", "SCI-002", { runId: "" });
    expect(mockedState).not.toHaveBeenCalled();
    expect(mockedMeetings).not.toHaveBeenCalled();
  });

  it("uses the V2 collection target for a state with an active collection phase", async () => {
    mockedStateV2.mockResolvedValue(stateV2({
      currentPhase: "collection",
      collection: {
        ...phase({ actionability: "executing", lifecycle: "running" }),
        aggregate: { total: 1, completed: 0, pending: 1, failed: 0, blocked: 0 },
        requests: [],
      },
    }));

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_collection");
    expect(mockedState).not.toHaveBeenCalled();
  });

  it("propagates V2 server errors instead of presenting generation as initial", async () => {
    const error = new FetchJsonHttpError("Server failed", { status: 500, code: "internal_error" });
    mockedStateV2.mockRejectedValue(error);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).rejects.toBe(error);
    expect(mockedState).not.toHaveBeenCalled();
  });

  it("propagates a domain 404 instead of falling back to V1", async () => {
    const error = new FetchJsonHttpError("Catalog question unknown", {
      status: 404,
      code: "catalog_question_unknown",
    });
    mockedStateV2.mockRejectedValue(error);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).rejects.toBe(error);
    expect(mockedState).not.toHaveBeenCalled();
  });

  it("propagates malformed V2 DTO errors instead of falling back to generation", async () => {
    const error = new Error("Invalid hypothesis-first state V2 response");
    mockedStateV2.mockRejectedValue(error);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).rejects.toBe(error);
    expect(mockedState).not.toHaveBeenCalled();
  });

  it("propagates a fatal problem from a degraded V2 snapshot", async () => {
    mockedStateV2.mockResolvedValue(stateV2({
      problems: [{
        code: "state_source_unavailable",
        category: "integrity",
        severity: "fatal",
        message: "无法读取挑战杯流程事实",
        recoverable: true,
        sourceKind: "workflow_ledger",
        sourceId: null,
        detectedAt: "2026-08-19T00:00:00Z",
      }],
    }));

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002"))
      .rejects.toThrow("无法读取挑战杯流程事实");
    expect(mockedState).not.toHaveBeenCalled();
  });

  it("uses V1 only when the V2 route is explicitly unavailable", async () => {
    mockedStateV2.mockRejectedValue(unavailableV2Error(501));
    mockedState.mockResolvedValue({ candidateCount: 2 } as never);
    mockedMeetings.mockResolvedValue({ meetings: [] } as never);
    mockedSelections.mockResolvedValue({ selections: [] } as never);
    mockedRequests.mockResolvedValue({ requests: [] } as never);
    mockedReviewLinks.mockResolvedValue({ links: [] } as never);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_selection");
    expect(mockedState).toHaveBeenCalledWith("team-1", "SCI-002", { runId: "" });
  });

  it("keeps the compatibility focus reads and projection on the requested workflow run", async () => {
    const runId = "run-current";
    mockedState.mockResolvedValue({ candidateCount: 2 } as never);
    mockedMeetings.mockResolvedValue({
      meetings: [
        {
          question: "SCI-002",
          meetingType: "hypothesis_candidate_generation",
          status: "open",
          meetingRoundId: "gen-old",
          startedAt: "2026-08-19T00:00:00Z",
          workflowRunId: "run-old",
        },
        {
          question: "SCI-002",
          meetingType: "hypothesis_candidate_generation",
          status: "closed",
          meetingRoundId: "gen-current",
          startedAt: "2026-08-19T01:00:00Z",
          workflowRunId: runId,
        },
      ],
    } as never);
    mockedSelections.mockResolvedValue({
      selections: [{ selectionId: "sel-current", createdAt: "2026-08-19T02:00:00Z", workflowRunId: runId }],
    } as never);
    mockedRequests.mockResolvedValue({ requests: [] } as never);
    mockedReviewLinks.mockResolvedValue({ links: [] } as never);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002", runId)).resolves.toBe("hf_selection");
    expect(mockedStateV2).toHaveBeenCalledWith("team-1", "SCI-002", { runId });
    expect(mockedState).toHaveBeenCalledWith("team-1", "SCI-002", { runId });
    expect(mockedMeetings).toHaveBeenCalledWith("team-1");
    expect(mockedSelections).toHaveBeenCalledWith("team-1", "SCI-002", { runId });
    expect(mockedRequests).toHaveBeenCalledWith("team-1", "SCI-002", { runId });
    expect(mockedReviewLinks).toHaveBeenCalledWith("team-1", "SCI-002", { runId });
  });

  it("lands on generation when a candidate-generation meeting is open", async () => {
    mockedState.mockResolvedValue({ candidateCount: 0 } as never);
    mockedMeetings.mockResolvedValue({
      meetings: [{
        question: "SCI-002",
        meetingType: "hypothesis_candidate_generation",
        status: "open",
        meetingRoundId: "gen-1",
        startedAt: "2026-08-19T00:00:00Z",
      }],
    } as never);
    mockedSelections.mockResolvedValue({ selections: [] } as never);
    mockedRequests.mockResolvedValue({ requests: [] } as never);
    mockedReviewLinks.mockResolvedValue({ links: [] } as never);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_generation");
  });

  it("lands on selection when candidates exist and none are chosen", async () => {
    mockedState.mockResolvedValue({ candidateCount: 2 } as never);
    mockedMeetings.mockResolvedValue({
      meetings: [{
        question: "SCI-002",
        meetingType: "hypothesis_candidate_generation",
        status: "closed",
        meetingRoundId: "gen-1",
        startedAt: "2026-08-19T00:00:00Z",
      }],
    } as never);
    mockedSelections.mockResolvedValue({ selections: [] } as never);
    mockedRequests.mockResolvedValue({ requests: [] } as never);
    mockedReviewLinks.mockResolvedValue({ links: [] } as never);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_selection");
  });

  it("lands on the linked current review when historical meetings lack roundIndex", async () => {
    mockedState.mockResolvedValue({ candidateCount: 2, hypothesisConverged: true } as never);
    mockedMeetings.mockResolvedValue({
      meetings: [
        {
          question: "SCI-002",
          meetingType: "hypothesis_review",
          status: "closed",
          meetingRoundId: "r1",
          startedAt: "2026-08-19T01:00:00Z",
        },
        {
          question: "SCI-002",
          meetingType: "hypothesis_review",
          status: "summarizing",
          meetingRoundId: "r5",
          startedAt: "2026-08-19T05:00:00Z",
        },
      ],
    } as never);
    mockedSelections.mockResolvedValue({ selections: [{ selectionId: "sel-1", createdAt: "2026-08-19T00:00:00Z" }] } as never);
    mockedRequests.mockResolvedValue({ requests: [] } as never);
    mockedReviewLinks.mockResolvedValue({
      links: [
        { meetingRoundId: "r1", roundIndex: 1, candidateId: "cand-r1" },
        { meetingRoundId: "r5", roundIndex: 5, candidateId: "cand-r5" },
      ],
    } as never);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_meeting_5_cand-r5");
  });

  it("propagates a V1 compatibility read failure instead of presenting generation", async () => {
    mockedState.mockRejectedValue(new Error("offline"));
    mockedMeetings.mockRejectedValue(new Error("offline"));
    mockedSelections.mockRejectedValue(new Error("offline"));
    mockedRequests.mockRejectedValue(new Error("offline"));
    mockedReviewLinks.mockRejectedValue(new Error("offline"));
    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).rejects.toThrow("offline");
  });
});
