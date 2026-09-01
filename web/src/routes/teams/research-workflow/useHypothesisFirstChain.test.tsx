/**
 * Behavioral tests for useHypothesisFirstChain (HFC-3): empty questionId stays
 * idle, chain data maps through, latest selection wins, errors surface, and run
 * SSE sequence bumps invalidate the hypothesis-first queries (debounced).
 *
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import {
  executeHypothesisFirstCommand,
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisFirstStateV2,
  fetchHypothesisSelections,
  fetchMeetingRounds,
  fetchReviewRoundLinks,
  recoverCollectionRequest,
} from "../../../api/hypothesisFirst";
import type { HypothesisFirstStateV2 } from "../../../api/types/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import {
  HYPOTHESIS_FIRST_REVIEW_ROUND_LIMIT,
  hypothesisFirstChainCollectionRequestsKey,
  hypothesisFirstChainReviewRoundLinksKey,
  resolveHypothesisFirstRoundBudget,
  useHypothesisFirstChain,
  useHypothesisFirstChainInvalidation,
  shouldPollQuestionScopedChain,
  shouldPollHypothesisFirstStateV2,
  type HypothesisFirstChainData,
} from "./useHypothesisFirstChain";

vi.mock("../../../api/hypothesisFirst", () => ({
  executeHypothesisFirstCommand: vi.fn(),
  fetchHypothesisFirstChainState: vi.fn(),
  fetchHypothesisFirstStateV2: vi.fn(),
  isHypothesisFirstStateV2EndpointUnavailable: (error: unknown) => {
    if (!error || typeof error !== "object") return false;
    const candidate = error as { status?: number; code?: string };
    return candidate.status === 501
      || (
        candidate.status === 404
        && ["endpoint_not_found", "endpoint_unavailable", "contract_not_supported", "route_not_found"]
          .includes(String(candidate.code || ""))
      );
  },
  fetchHypothesisSelections: vi.fn(),
  fetchMeetingRounds: vi.fn(),
  fetchCollectionRequests: vi.fn(),
  fetchReviewRoundLinks: vi.fn(),
  recoverCollectionRequest: vi.fn(),
  isHypothesisFirstCommandStateConflict: vi.fn().mockReturnValue(false),
}));

const mocked = {
  executeCommand: vi.mocked(executeHypothesisFirstCommand),
  chainState: vi.mocked(fetchHypothesisFirstChainState),
  stateV2: vi.mocked(fetchHypothesisFirstStateV2),
  selections: vi.mocked(fetchHypothesisSelections),
  meetings: vi.mocked(fetchMeetingRounds),
  requests: vi.mocked(fetchCollectionRequests),
  links: vi.mocked(fetchReviewRoundLinks),
  recoverCollection: vi.mocked(recoverCollectionRequest),
};

const scope = {
  program: "p",
  theme: "t",
  campaign: "c",
  question: "Q-01",
  branch: "b",
  workflow: "w",
  agentId: "a",
};

function chainStatePayload() {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    questionId: "Q-01",
    selectionId: "sel-2",
    meetingCount: 1,
    firstMeetingId: "hf-review-sel-2-r1",
    firstMeetingClosed: false,
    openMeetingIds: ["hf-review-sel-2-r1"],
    collectionRequests: [],
    collectionRequestCount: 0,
    pendingCollectionCount: 0,
    collectionReady: false,
    hypothesisRoundCount: 0,
    latestHypothesisRoundId: "",
    hypothesisConverged: false,
    convergenceDetail: "",
    roundBudget: 3,
    budgetExhausted: false,
    templateBaselineExists: false,
    templateBaselineIds: [],
  };
}

function stateV2Payload(): HypothesisFirstStateV2 {
  return {
    schemaVersion: 2,
    contract: "hypothesis-first-state/v2" as const,
    teamId: "team-1",
    questionId: "Q-01",
    stateVersion: "hf2-action:reset-1:state-1",
    representationVersion: "hf2-repr:reset-1:repr-1",
    computedAt: "2026-08-25T00:00:00Z",
    scope: { questionInOfficialCatalog: true, catalogId: "challenge-cup", catalogSha256: "sha" },
    resetBoundary: { resetId: "origin", resetAt: null, source: "origin" as const },
    isInitial: false,
    awaitingHumanCount: 1,
    currentPhase: "review" as const,
    overall: { lifecycle: "running" as const, outcome: "none" as const, actionability: "waiting_human" as const, attempt: null, updatedAt: null, problems: [] },
    generation: { lifecycle: "completed" as const, outcome: "succeeded" as const, actionability: "terminal" as const, attempt: null, updatedAt: null, problems: [], generationMeetingId: "gen-1", candidateCount: 1, candidateIds: ["cand-1"] },
    selection: { lifecycle: "completed" as const, outcome: "succeeded" as const, actionability: "terminal" as const, attempt: null, updatedAt: null, problems: [], selectionId: "sel-2", selectedCandidateIds: ["cand-1"] },
    review: { lifecycle: "waiting_human" as const, outcome: "none" as const, actionability: "waiting_user" as const, attempt: null, updatedAt: null, problems: [], activeRoundIndex: 1, aggregate: { total: 1, completed: 0, pending: 1, failed: 0, blocked: 0 }, candidates: [] },
    collection: { lifecycle: "not_started" as const, outcome: "none" as const, actionability: "idle" as const, attempt: null, updatedAt: null, problems: [], aggregate: { total: 0, completed: 0, pending: 0, failed: 0, blocked: 0 }, requests: [] },
    convergence: { lifecycle: "not_started" as const, outcome: "none" as const, actionability: "idle" as const, attempt: null, updatedAt: null, problems: [], latestHypothesisRoundId: null, accepted: false, roundIndex: 0, roundBudget: 3 },
    formalRuntime: { lifecycle: "not_started" as const, outcome: "none" as const, actionability: "idle" as const, attempt: null, updatedAt: null, problems: [], runId: null, runVersion: null, runStatus: null, completionKind: null, lineageDisposition: null, isCurrentRevision: false, parentRunId: null, childRunIds: [], currentNodeIds: [] },
    programDelivery: { lifecycle: "not_started" as const, outcome: "none" as const, actionability: "idle" as const, attempt: null, updatedAt: null, problems: [], deliveryStatus: "not_started" as const, deliveryArtifactRef: null, handoffStatus: "not_started" as const, outputRecordId: null, outputRunId: null, humanReviewStatus: "not_started" as const, humanGates: { decisions: { H1_problem_understanding: "pending" as const, H2_hypothesis_selection: "pending" as const, H3_research_plan: "pending" as const, H4_external_output: "pending" as const }, reviewer: null, rationale: null, decidedAt: null }, approvedGateCount: 0, requiredGateCount: 4 },
    allowedActions: [],
    problems: [],
  };
}

function selectionRecord(selectionId: string, createdAt: string) {
  return {
    ...scope,
    schemaVersion: 1,
    selectionId,
    selectionHash: "h",
    mode: "manual",
    scopeHash: "sh",
    questionId: "Q-01",
    selectedCandidateIds: ["cand-1"],
    previousSelectionId: "",
    decidedBy: "leader",
    createdAt,
  };
}

function meetingRecord(meetingRoundId: string) {
  return {
    ...scope,
    schemaVersion: 1,
    meetingRoundId,
    meetingType: "hypothesis_review",
    mode: "review",
    scopeHash: "sh",
    participants: ["agent-1"],
    status: "open",
    startedAt: "2026-08-19T01:00:00Z",
    roundIndex: 1,
  };
}

function requestRecord(requestId: string) {
  return {
    ...scope,
    schemaVersion: 1,
    recordKind: "hypothesis_first_collection_request",
    requestId,
    requestHash: "rh",
    status: "pending",
    meetingRoundId: "hf-review-sel-2-r1",
    decisionId: "dec-1",
    questionId: "Q-01",
    mode: "review",
    scopeHash: "sh",
    searchEnvelope: {},
    requirements: {},
    writebackPolicy: {},
    collectionRunId: "run-1",
    createdAt: "2026-08-19T02:00:00Z",
  };
}

function linkRecord() {
  return {
    schemaVersion: 1,
    recordKind: "hypothesis_first_review_round_link",
    linkId: "hf-link-2",
    meetingRoundId: "hf-review-sel-2-r2",
    previousMeetingRoundId: "hf-review-sel-2-r1",
    selectionId: "sel-2",
    collectionRequestId: "req-1",
    questionId: "Q-01",
    roundIndex: 2,
    createdAt: "2026-08-19T03:00:00Z",
  };
}

function mockAllResolved() {
  mocked.chainState.mockResolvedValue(chainStatePayload());
  mocked.stateV2.mockResolvedValue(stateV2Payload());
  mocked.selections.mockResolvedValue({
    schemaVersion: 1,
    teamId: "team-1",
    selectionCount: 2,
    selections: [
      selectionRecord("sel-1", "2026-08-18T00:00:00Z"),
      selectionRecord("sel-2", "2026-08-19T00:00:00Z"),
    ],
  });
  mocked.meetings.mockResolvedValue({
    schemaVersion: 1,
    teamId: "team-1",
    meetingCount: 1,
    meetings: [meetingRecord("hf-review-sel-2-r1")],
  });
  mocked.requests.mockResolvedValue({
    schemaVersion: 1,
    teamId: "team-1",
    requestCount: 1,
    requests: [requestRecord("req-1")],
  });
  mocked.links.mockResolvedValue({
    schemaVersion: 1,
    teamId: "team-1",
    linkCount: 1,
    links: [linkRecord()],
  });
}

let container: HTMLDivElement;
let root: Root;
let queryClient: QueryClient;

function render(ui: React.ReactElement) {
  act(() => {
    root.render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
  });
}

async function flushQueries() {
  // React Query batches notifications on a macro-task boundary; microtask-only
  // flushing races it. A few real timer rounds settle deterministically.
  for (let index = 0; index < 5; index += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

describe("useHypothesisFirstChain", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("stays idle and issues no request when questionId is empty", async () => {
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.loading).toBe(false);
    expect(latest!.questionScopeKey).toBe("team-1::no-question::no-run");
    expect(latest!.questionId).toBe("");
    expect(latest!.scopeMismatch).toBe(false);
    expect(latest!.chainState).toBeNull();
    expect(latest!.selection).toBeNull();
    expect(mocked.chainState).not.toHaveBeenCalled();
    expect(mocked.selections).not.toHaveBeenCalled();
    expect(mocked.meetings).not.toHaveBeenCalled();
    expect(mocked.requests).not.toHaveBeenCalled();
    expect(mocked.links).not.toHaveBeenCalled();
  });

  it("loads chain state, picks the latest selection, and maps ledger lists", async () => {
    mockAllResolved();
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.error).toBeNull();
    expect(latest!.loading).toBe(false);
    expect(latest!.questionScopeKey).toBe("team-1::Q-01::no-run");
    expect(latest!.questionId).toBe("Q-01");
    expect(latest!.scopeMismatch).toBe(false);
    expect(latest!.chainState?.questionId).toBe("Q-01");
    expect(latest!.stateV2?.contract).toBe("hypothesis-first-state/v2");
    expect(latest!.stateSource).toBe("v2_canonical");
    expect(latest!.selection?.selectionId).toBe("sel-2");
    expect(latest!.meetings.map((meeting) => meeting.meetingRoundId)).toEqual(["hf-review-sel-2-r1"]);
    expect(latest!.collectionRequests.map((request) => request.requestId)).toEqual(["req-1"]);
    expect(latest!.reviewRoundLinks.map((link) => link.linkId)).toEqual(["hf-link-2"]);
    expect(mocked.stateV2).toHaveBeenCalledWith("team-1", "Q-01", expect.anything());
    expect(mocked.chainState).not.toHaveBeenCalled();
    expect(mocked.requests).toHaveBeenCalledWith("team-1", "Q-01", expect.anything());
  });

  it("isolates every chain read, cache entry, and ledger projection by workflow run", async () => {
    const runId = "run-current";
    const oldRunId = "run-old";
    const canonical = stateV2Payload();
    mocked.stateV2.mockResolvedValue({
      ...canonical,
      workflowRunId: runId,
      scope: { ...canonical.scope, workflowRunId: runId },
    } as never);
    mocked.chainState.mockResolvedValue({ ...chainStatePayload(), workflowRunId: runId } as never);
    mocked.selections.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      selectionCount: 2,
      // The stale selection is newer on purpose: question-only filtering would
      // incorrectly make it the active selection for run-current.
      selections: [
        { ...selectionRecord("sel-old", "2026-08-20T00:00:00Z"), workflowRunId: oldRunId },
        { ...selectionRecord("sel-current", "2026-08-19T00:00:00Z"), workflowRunId: runId },
      ],
    });
    mocked.meetings.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingCount: 2,
      meetings: [
        { ...meetingRecord("meeting-old"), workflowRunId: oldRunId },
        { ...meetingRecord("meeting-current"), workflowRunId: runId },
      ],
    });
    mocked.requests.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      requestCount: 2,
      requests: [
        { ...requestRecord("request-old"), workflowRunId: oldRunId, meetingRoundId: "meeting-old" },
        { ...requestRecord("request-current"), workflowRunId: runId, meetingRoundId: "meeting-current" },
      ],
    });
    mocked.links.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      linkCount: 2,
      links: [
        { ...linkRecord(), linkId: "link-old", workflowRunId: oldRunId, meetingRoundId: "meeting-old" },
        { ...linkRecord(), linkId: "link-current", workflowRunId: runId, meetingRoundId: "meeting-current" },
      ],
    });

    let latest: HypothesisFirstChainData | null = null;
    render(
      <Probe
        teamId="team-1"
        questionId="Q-01"
        runId={runId}
        onResult={(value) => { latest = value; }}
      />,
    );
    await flushQueries();

    expect(latest!.questionScopeKey).toContain(runId);
    expect(latest!.selection?.selectionId).toBe("sel-current");
    expect(latest!.meetings.map((meeting) => meeting.meetingRoundId)).toEqual(["meeting-current"]);
    expect(latest!.collectionRequests.map((request) => request.requestId)).toEqual(["request-current"]);
    expect(latest!.reviewRoundLinks.map((link) => link.linkId)).toEqual(["link-current"]);

    expect(mocked.stateV2).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      expect.objectContaining({ runId }),
    );
    expect(mocked.chainState).not.toHaveBeenCalled();
    expect(mocked.selections).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      expect.objectContaining({ runId }),
    );
    expect(mocked.meetings).toHaveBeenCalledWith("team-1", expect.anything());
    expect(mocked.requests).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      expect.objectContaining({ runId }),
    );
    expect(mocked.links).toHaveBeenCalledWith(
      "team-1",
      "Q-01",
      expect.objectContaining({ runId }),
    );

    expect(queryClient.getQueryCache().find({
      queryKey: queryKeys.hypothesisFirstChainStateV2("team-1", "Q-01", runId),
    })).toBeDefined();
    expect(queryClient.getQueryCache().find({
      queryKey: queryKeys.hypothesisFirstSelections("team-1", "Q-01", runId),
    })).toBeDefined();
    expect(queryClient.getQueryCache().find({
      queryKey: hypothesisFirstChainCollectionRequestsKey("team-1", "Q-01", runId),
    })).toBeDefined();
    expect(queryClient.getQueryCache().find({
      queryKey: hypothesisFirstChainReviewRoundLinksKey("team-1", "Q-01", runId),
    })).toBeDefined();
  });

  it("treats the meeting receipt as the run authority over conflicting legacy fields", async () => {
    const runId = "run-current";
    const oldRunId = "run-old";
    const canonical = stateV2Payload();
    mocked.stateV2.mockResolvedValue({
      ...canonical,
      workflowRunId: runId,
      scope: { ...canonical.scope, workflowRunId: runId },
    } as never);
    mocked.chainState.mockResolvedValue({ ...chainStatePayload(), workflowRunId: runId } as never);
    mocked.selections.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      selectionCount: 0,
      selections: [],
    });
    mocked.meetings.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingCount: 1,
      meetings: [{
        ...meetingRecord("meeting-conflict"),
        workflowRunId: runId,
        discussionScope: { workflowRunId: runId },
        modelInvocationReceiptAuthority: { workflowRunId: oldRunId },
      }],
    } as never);
    mocked.requests.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", requestCount: 0, requests: [] });
    mocked.links.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", linkCount: 0, links: [] });

    let latest: HypothesisFirstChainData | null = null;
    render(
      <Probe
        teamId="team-1"
        questionId="Q-01"
        runId={runId}
        onResult={(value) => { latest = value; }}
      />,
    );
    await flushQueries();

    expect(latest!.scopeMismatch).toBe(false);
    expect(latest!.meetings).toEqual([]);
    expect(latest!.collectionRequests).toEqual([]);
    expect(latest!.reviewRoundLinks).toEqual([]);
  });

  it("filters team-scoped ledgers to the requested question", async () => {
    mockAllResolved();
    mocked.meetings.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      meetingCount: 2,
      meetings: [
        meetingRecord("hf-review-sel-2-r1"),
        { ...meetingRecord("hf-review-other-r1"), question: "Q-02" },
      ],
    });
    mocked.links.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      linkCount: 2,
      links: [linkRecord(), { ...linkRecord(), linkId: "other", questionId: "Q-02" }],
    });
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.meetings.map((meeting) => meeting.meetingRoundId)).toEqual(["hf-review-sel-2-r1"]);
    expect(latest!.reviewRoundLinks.map((link) => link.linkId)).toEqual(["hf-link-2"]);
  });

  it("keeps decorated ledger list identities stable across unrelated re-renders", async () => {
    mockAllResolved();
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    const before = {
      meetings: latest!.meetings,
      collectionRequests: latest!.collectionRequests,
      reviewRoundLinks: latest!.reviewRoundLinks,
    };
    expect(before.meetings.length).toBeGreaterThan(0);

    // A parent re-render (new element identity, unchanged query data) must not
    // rebuild the memoized lists that downstream canvas composition depends on.
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.meetings).toBe(before.meetings);
    expect(latest!.collectionRequests).toBe(before.collectionRequests);
    expect(latest!.reviewRoundLinks).toBe(before.reviewRoundLinks);
  });

  it("mirrors a raised V2 convergence budget into the compatibility projection", async () => {
    mockAllResolved();
    const raised = { ...stateV2Payload().convergence, roundBudget: 5 };
    mocked.stateV2.mockResolvedValue({ ...stateV2Payload(), convergence: raised });
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    // After a budget raise the next canonical read carries the larger value;
    // the display resolver reads it through stateV2 first.
    expect(latest!.stateSource).toBe("v2_canonical");
    expect(latest!.chainState?.roundBudget).toBe(5);
    expect(latest!.stateV2?.convergence.roundBudget).toBe(5);
  });

  it("configures every mounted chain query to refresh on focus and reconnect", async () => {
    mockAllResolved();
    render(<Probe teamId="team-1" questionId="Q-01" onResult={() => undefined} />);
    await flushQueries();

    // Per-query override of the global refetchOnWindowFocus:false default:
    // returning to the tab must not wait for the next gated poll tick.
    const alwaysFreshKeys = [
      queryKeys.hypothesisFirstChainStateV2("team-1", "Q-01"),
      queryKeys.hypothesisFirstSelections("team-1", "Q-01"),
      queryKeys.teamMeetingRounds("team-1"),
      hypothesisFirstChainCollectionRequestsKey("team-1", "Q-01"),
      hypothesisFirstChainReviewRoundLinksKey("team-1", "Q-01"),
    ];
    expect(alwaysFreshKeys).toHaveLength(5);
    for (const queryKey of alwaysFreshKeys) {
      const query = queryClient.getQueryCache().find({ queryKey });
      expect(query?.options.refetchOnWindowFocus, String(queryKey)).toBe("always");
      expect(query?.options.refetchOnReconnect, String(queryKey)).toBe("always");
      // The existing bounded poll gating stays intact.
      if (!String(queryKey).includes("selections")
        && !String(queryKey).includes("review-round-links")) {
        expect(query?.options.refetchInterval, String(queryKey)).toBeTypeOf("function");
      }
    }
  });

  it("keeps the legacy fallback read fresh on focus too", async () => {
    mockAllResolved();
    mocked.stateV2.mockRejectedValue(Object.assign(new Error("route missing"), {
      status: 404,
      code: "endpoint_not_found",
    }));
    render(<Probe teamId="team-1" questionId="Q-01" onResult={() => undefined} />);
    await flushQueries();

    const legacy = queryClient.getQueryCache().find({
      queryKey: queryKeys.hypothesisFirstChainState("team-1", "Q-01"),
    });
    expect(legacy).not.toBeNull();
    expect(legacy?.options.refetchOnWindowFocus).toBe("always");
    expect(legacy?.options.refetchOnReconnect).toBe("always");
  });

  it("fails closed when a question-keyed chain payload belongs to another question", async () => {
    mockAllResolved();
    mocked.stateV2.mockResolvedValue({ ...stateV2Payload(), questionId: "Q-02" });
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.scopeMismatch).toBe(true);
    expect(latest!.chainState).toBeNull();
  });

  it("marks a plain V2 read failure as v2_error and surfaces the first query error", async () => {
    mockAllResolved();
    mocked.stateV2.mockRejectedValue(new Error("chain unavailable"));
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.error).toBe("chain unavailable");
    expect(latest!.v2ReadState).toBe("v2_error");
    expect(latest!.stateSource).toBe("v2_error");
    expect(mocked.chainState).not.toHaveBeenCalled();
  });

  it("falls back to V1 only when V2 endpoint is unavailable", async () => {
    mockAllResolved();
    mocked.stateV2.mockRejectedValue(Object.assign(new Error("route missing"), {
      status: 404,
      code: "endpoint_not_found",
    }));
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.v2ReadState).toBe("route_unavailable");
    expect(latest!.stateSource).toBe("v1_legacy");
    expect(latest!.stateV2).toBeNull();
    expect(latest!.chainState?.questionId).toBe("Q-01");
    expect(mocked.chainState).toHaveBeenCalledWith("team-1", "Q-01", expect.anything());
  });

  it("does not fallback a domain 404 or a V2 500 into legacy initial state", async () => {
    mockAllResolved();
    mocked.stateV2.mockRejectedValue(Object.assign(new Error("catalog question unknown"), {
      status: 404,
      code: "catalog_question_unknown",
    }));
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.v2ReadState).toBe("v2_error");
    expect(latest!.stateSource).toBe("v2_error");
    expect(latest!.chainState).toBeNull();
    expect(latest!.error).toBe("catalog question unknown");
    expect(mocked.chainState).not.toHaveBeenCalled();

    mocked.stateV2.mockReset();
    mocked.stateV2.mockRejectedValue(Object.assign(new Error("server failed"), { status: 500, code: "internal_error" }));
    latest = null;
    render(<Probe teamId="team-1" questionId="Q-02" onResult={(value) => { latest = value; }} />);
    await flushQueries();
    expect(latest!.v2ReadState).toBe("v2_error");
    expect(latest!.stateSource).toBe("v2_error");
    expect(latest!.chainState).toBeNull();
    expect(latest!.error).toBe("server failed");
    expect(mocked.chainState).not.toHaveBeenCalledWith("team-1", "Q-02", expect.anything());
  });

  it("does not fallback a malformed V2 DTO into legacy initial state", async () => {
    mockAllResolved();
    mocked.stateV2.mockRejectedValue(new Error("Invalid hypothesis-first state V2 response"));
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.v2ReadState).toBe("v2_error");
    expect(latest!.stateSource).toBe("v2_error");
    expect(latest!.stateV2).toBeNull();
    expect(latest!.chainState).toBeNull();
    expect(latest!.error).toBe("Invalid hypothesis-first state V2 response");
    expect(mocked.chainState).not.toHaveBeenCalled();
  });

  it("stays pending with no phase data while the V2 snapshot is still loading", async () => {
    // A cached question-scoped list may already resolve before the canonical
    // snapshot arrives; that half-data must never become business state.
    queryClient.setQueryData(queryKeys.teamMeetingRounds("team-1"), {
      schemaVersion: 1,
      teamId: "team-1",
      meetingCount: 1,
      meetings: [meetingRecord("hf-review-sel-2-r1")],
    });
    const never = new Promise(() => undefined);
    mocked.chainState.mockReturnValue(never);
    mocked.stateV2.mockImplementation(() => never);
    mocked.selections.mockImplementation(() => never);
    mocked.meetings.mockImplementation(() => never);
    mocked.requests.mockImplementation(() => never);
    mocked.links.mockImplementation(() => never);
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.loading).toBe(true);
    expect(latest!.v2ReadState).toBe("pending");
    expect(latest!.stateSource).toBe("pending");
    expect(latest!.stateV2).toBeNull();
    expect(latest!.chainState).toBeNull();
    // The cached meeting stays available as evidence, not as an inference input.
    expect(latest!.meetings.map((meeting) => meeting.meetingRoundId)).toEqual(["hf-review-sel-2-r1"]);
  });

  it("fails closed instead of using the legacy recovery mutation when V2 has no signed action", async () => {
    mockAllResolved();
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    await act(async () => {
      await latest!.recoverCollection("req-1");
    });

    expect(mocked.executeCommand).not.toHaveBeenCalled();
    expect(mocked.recoverCollection).not.toHaveBeenCalled();
    expect(latest!.recoveryError).toBe("canonical_action_unavailable");
  });

  it("invalidates hypothesis-first queries (debounced) when the run event sequence advances", async () => {
    vi.useFakeTimers();
    try {
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
      render(<InvalidationProbe teamId="team-1" questionId="Q-01" lastSequence={3} />);
      await act(async () => {
        vi.advanceTimersByTime(100);
      });
      expect(invalidateSpy).not.toHaveBeenCalled();

      await act(async () => {
        vi.advanceTimersByTime(300);
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["teams", "team-1", "hypothesis-first"],
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ["teams", "team-1", "meeting-rounds"],
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not invalidate for an empty question or the initial zero sequence", async () => {
    vi.useFakeTimers();
    try {
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
      render(<InvalidationProbe teamId="team-1" questionId="" lastSequence={5} />);
      await act(async () => {
        vi.advanceTimersByTime(500);
      });
      expect(invalidateSpy).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("hypothesis-first round budget display contract", () => {
  function v2WithRoundBudget(roundBudget: number): Pick<HypothesisFirstStateV2, "convergence"> {
    return { convergence: { ...stateV2Payload().convergence, roundBudget } };
  }

  it("prefers the V2 snapshot budget, then the V1 chain-state value", () => {
    expect(resolveHypothesisFirstRoundBudget({
      stateV2: v2WithRoundBudget(4),
      chainState: { roundBudget: 3 },
    })).toBe(4);
    expect(resolveHypothesisFirstRoundBudget({
      stateV2: null,
      chainState: { roundBudget: 2 },
    })).toBe(2);
  });

  it("publishes the single server-owned hard limit as the fallback", () => {
    expect(HYPOTHESIS_FIRST_REVIEW_ROUND_LIMIT).toBe(5);
    expect(resolveHypothesisFirstRoundBudget({ stateV2: null, chainState: null })).toBe(5);
    expect(resolveHypothesisFirstRoundBudget({})).toBe(5);
    // 非法值（0/负数/NaN）与旧 V1 快照的缺省 0 一样回落到稳定硬上限。
    expect(resolveHypothesisFirstRoundBudget({
      stateV2: null,
      chainState: { roundBudget: 0 },
    })).toBe(5);
    expect(resolveHypothesisFirstRoundBudget({
      stateV2: v2WithRoundBudget(Number.NaN),
      chainState: { roundBudget: -1 },
    })).toBe(5);
  });
});

describe("question-scoped hypothesis polling", () => {
  it("polls every canonical system-owned live phase and stops at human review", () => {
    const generation = stateV2Payload();
    generation.currentPhase = "generation";
    generation.generation.lifecycle = "running";
    generation.generation.actionability = "waiting_system";
    expect(shouldPollHypothesisFirstStateV2(generation)).toBe(true);

    const review = stateV2Payload();
    review.review.lifecycle = "waiting_human";
    review.review.actionability = "waiting_user";
    review.review.candidates = [];
    expect(shouldPollHypothesisFirstStateV2(review)).toBe(false);

    const delivery = stateV2Payload();
    delivery.currentPhase = "program_delivery";
    delivery.programDelivery.lifecycle = "running";
    delivery.programDelivery.actionability = "waiting_system";
    expect(shouldPollHypothesisFirstStateV2(delivery)).toBe(true);
  });

  it("does not poll a chain payload from another question", () => {
    expect(shouldPollQuestionScopedChain({
      questionId: "Q-01",
      state: {
        ...chainStatePayload(),
        questionId: "Q-02",
        collectionReady: true,
        pendingCollectionCount: 1,
      },
    })).toBe(false);
  });

  it("ignores live collection requests from other questions", () => {
    expect(shouldPollQuestionScopedChain({
      questionId: "Q-01",
      requests: [{ ...requestRecord("other"), questionId: "Q-02" }],
    })).toBe(false);
    expect(shouldPollQuestionScopedChain({
      questionId: "Q-01",
      requests: [requestRecord("req-1")],
    })).toBe(true);
  });

  it("stops polling when a child run reports a terminal status", () => {
    expect(shouldPollQuestionScopedChain({
      questionId: "Q-01",
      requests: [{ ...requestRecord("failed"), collectionRunStatus: "failed" }],
    })).toBe(false);
    expect(shouldPollQuestionScopedChain({
      questionId: "Q-01",
      requests: [{ ...requestRecord("completed"), collectionRunStatus: "completed" }],
    })).toBe(false);
  });
});

function Probe(props: {
  teamId: string;
  questionId: string;
  runId?: string;
  onResult: (value: HypothesisFirstChainData) => void;
}) {
  props.onResult(useHypothesisFirstChain(props.teamId, props.questionId, props.runId));
  return null;
}

function InvalidationProbe(props: { teamId: string; questionId: string; lastSequence: number; runId?: string }) {
  useHypothesisFirstChainInvalidation(props.teamId, props.questionId, props.runId ?? "", props.lastSequence);
  return null;
}
