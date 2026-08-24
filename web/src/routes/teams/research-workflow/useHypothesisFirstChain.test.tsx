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
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisSelections,
  fetchMeetingRounds,
  fetchReviewRoundLinks,
} from "../../../api/hypothesisFirst";
import {
  useHypothesisFirstChain,
  useHypothesisFirstChainInvalidation,
  shouldPollQuestionScopedChain,
  type HypothesisFirstChainData,
} from "./useHypothesisFirstChain";

vi.mock("../../../api/hypothesisFirst", () => ({
  fetchHypothesisFirstChainState: vi.fn(),
  fetchHypothesisSelections: vi.fn(),
  fetchMeetingRounds: vi.fn(),
  fetchCollectionRequests: vi.fn(),
  fetchReviewRoundLinks: vi.fn(),
}));

const mocked = {
  chainState: vi.mocked(fetchHypothesisFirstChainState),
  selections: vi.mocked(fetchHypothesisSelections),
  meetings: vi.mocked(fetchMeetingRounds),
  requests: vi.mocked(fetchCollectionRequests),
  links: vi.mocked(fetchReviewRoundLinks),
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
    expect(latest!.questionScopeKey).toBe("team-1::no-question");
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
    expect(latest!.questionScopeKey).toBe("team-1::Q-01");
    expect(latest!.questionId).toBe("Q-01");
    expect(latest!.scopeMismatch).toBe(false);
    expect(latest!.chainState?.questionId).toBe("Q-01");
    expect(latest!.selection?.selectionId).toBe("sel-2");
    expect(latest!.meetings.map((meeting) => meeting.meetingRoundId)).toEqual(["hf-review-sel-2-r1"]);
    expect(latest!.collectionRequests.map((request) => request.requestId)).toEqual(["req-1"]);
    expect(latest!.reviewRoundLinks.map((link) => link.linkId)).toEqual(["hf-link-2"]);
    expect(mocked.chainState).toHaveBeenCalledWith("team-1", "Q-01", expect.anything());
    expect(mocked.requests).toHaveBeenCalledWith("team-1", "Q-01", expect.anything());
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

  it("fails closed when a question-keyed chain payload belongs to another question", async () => {
    mockAllResolved();
    mocked.chainState.mockResolvedValue({ ...chainStatePayload(), questionId: "Q-02" });
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.scopeMismatch).toBe(true);
    expect(latest!.chainState).toBeNull();
  });

  it("surfaces the first query error", async () => {
    mockAllResolved();
    mocked.chainState.mockRejectedValue(new Error("chain unavailable"));
    let latest: HypothesisFirstChainData | null = null;
    render(<Probe teamId="team-1" questionId="Q-01" onResult={(value) => { latest = value; }} />);
    await flushQueries();

    expect(latest!.error).toBe("chain unavailable");
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

describe("question-scoped hypothesis polling", () => {
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
  onResult: (value: HypothesisFirstChainData) => void;
}) {
  props.onResult(useHypothesisFirstChain(props.teamId, props.questionId));
  return null;
}

function InvalidationProbe(props: { teamId: string; questionId: string; lastSequence: number }) {
  useHypothesisFirstChainInvalidation(props.teamId, props.questionId, props.lastSequence);
  return null;
}
