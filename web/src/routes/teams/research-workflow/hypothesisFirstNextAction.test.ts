import { describe, expect, it } from "vitest";

import type {
  CollectionRequestRecord,
  HypothesisFirstChainState,
  HypothesisSelectionRecord,
  MeetingRoundRecord,
  ReviewRoundLinkRecord,
} from "../../../api/types/hypothesisFirst";
import {
  boundChatRoundsAreTerminal,
  boundChatRoundsFailedTerminal,
  chatRoundIsFailedTerminal,
  chatRoundIsTerminal,
  focusNodeFromNextAction,
  hasValidEvidenceRequestKeywords,
  reviewDigestConfirmBlocker,
} from "./hypothesisFirstNextAction";

function scope() {
  return {
    program: "p",
    theme: "t",
    campaign: "c",
    question: "SCI-002",
    branch: "b",
    workflow: "w",
    agentId: "a",
  };
}

function chain(overrides: Partial<HypothesisFirstChainState> = {}): HypothesisFirstChainState {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    questionId: "SCI-002",
    selectionId: "",
    meetingCount: 0,
    firstMeetingId: "",
    firstMeetingClosed: false,
    openMeetingIds: [],
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
    candidateCount: 0,
    ...overrides,
  };
}

function meeting(overrides: Partial<MeetingRoundRecord> = {}): MeetingRoundRecord {
  return {
    ...scope(),
    meetingRoundId: "mtg-1",
    meetingType: "hypothesis_review",
    mode: "review",
    scopeHash: "sh",
    participants: ["agent-1"],
    status: "open",
    startedAt: "2026-08-19T01:00:00Z",
    roundIndex: 1,
    ...overrides,
  };
}

function selection(overrides: Partial<HypothesisSelectionRecord> = {}): HypothesisSelectionRecord {
  return {
    ...scope(),
    schemaVersion: 1,
    selectionId: "sel-1",
    selectionHash: "h",
    mode: "manual",
    scopeHash: "sh",
    questionId: "SCI-002",
    selectedCandidateIds: ["cand-1"],
    previousSelectionId: "",
    decidedBy: "operator",
    createdAt: "2026-08-19T00:30:00Z",
    ...overrides,
  };
}

function request(overrides: Partial<CollectionRequestRecord> = {}): CollectionRequestRecord {
  return {
    ...scope(),
    schemaVersion: 1,
    recordKind: "hypothesis_first_collection_request",
    requestId: "req-1",
    requestHash: "rh",
    status: "pending",
    meetingRoundId: "mtg-1",
    decisionId: "dec-1",
    questionId: "SCI-002",
    mode: "review",
    scopeHash: "sh",
    searchEnvelope: { keywords: ["spike"] },
    requirements: {},
    writebackPolicy: {},
    collectionRunId: "run-collect-1",
    createdAt: "2026-08-19T02:00:00Z",
    ...overrides,
  };
}

function reviewLink(
  meetingRoundId: string,
  roundIndex: number,
  overrides: Partial<ReviewRoundLinkRecord> = {},
): ReviewRoundLinkRecord {
  return {
    schemaVersion: 1,
    recordKind: "hypothesis_first_review_round_link",
    linkId: `link-${meetingRoundId}`,
    meetingRoundId,
    previousMeetingRoundId: roundIndex > 1 ? `r${roundIndex - 1}` : "",
    selectionId: "sel-1",
    collectionRequestId: "",
    questionId: "SCI-002",
    roundIndex,
    candidateId: "cand-1",
    createdAt: `2026-08-19T0${roundIndex}:00:01Z`,
    ...overrides,
  };
}



describe("evidence request helpers", () => {
  it("requires at least one non-empty keyword", () => {
    expect(hasValidEvidenceRequestKeywords([])).toBe(false);
    expect(hasValidEvidenceRequestKeywords([{ searchEnvelope: { keywords: ["  "] } }])).toBe(false);
    expect(hasValidEvidenceRequestKeywords([{ searchEnvelope: { keywords: ["EEG"] } }])).toBe(true);
    expect(reviewDigestConfirmBlocker({
      summary: "x",
      agreements: ["marker consensus"],
      evidenceRequests: [{ searchEnvelope: { keywords: [] } }],
    })).toContain("有效搜集关键词");
    expect(reviewDigestConfirmBlocker({
      summary: "x",
      agreements: [],
      disagreements: [],
      actionItems: [],
      knowledgeCandidates: [],
      evidenceRequests: [],
    })).toBe("纪要未捕获讨论内容");
    // Zero requests with captured discussion is the legal convergence close:
    // the button must stay clickable so the chain can converge via UI.
    expect(reviewDigestConfirmBlocker({
      summary: "x",
      agreements: ["marker consensus"],
      evidenceRequests: [],
    })).toBeUndefined();
  });
});

describe("bound chat terminal detection", () => {
  it("trusts the server flag when present, otherwise requires every bound round to be terminal", () => {
    expect(boundChatRoundsAreTerminal({
      meeting: meeting({ boundChatRoundsTerminal: true }),
    })).toBe(true);
    expect(boundChatRoundsAreTerminal({
      meeting: meeting({ chatRoomRoundIds: ["r1", "r2"] }),
      chatRounds: [
        { roundId: "r1", status: "completed" },
        { roundId: "r2", status: "running" },
      ],
    })).toBe(false);
    expect(boundChatRoundsAreTerminal({
      meeting: meeting({ chatRoomRoundIds: ["r1"] }),
      chatRounds: [{ roundId: "r1", status: "completed" }],
    })).toBe(true);
  });
});

describe("legacy chat round terminal taxonomy", () => {
  // Mirrors core/web/services/team_workflow/research_runtime/
  // hypothesis_first_state_v2.py: _CHAT_ROOM_ROUND_TERMINAL_STATUSES unified
  // with _CHAT_ROOM_ROUND_TERMINAL_RUNTIME_STATUSES.
  const BACKEND_TERMINAL_STATUSES = [
    "completed",
    "done",
    "ready",
    "routed",
    "success",
    "succeeded",
    "partial",
    "needs_continue",
    "paused_limit",
    "closed",
    "cancelled",
    "canceled",
    "idle",
    "stopped",
    "stopped_by_user",
    "superseded",
    "terminated",
    "force_stopped",
    "orphan_reconciled",
    "orphaned_room_reconciled",
    "error",
    "failed",
    "failed_provider",
    "failed_runtime",
    "stop_failed",
  ];
  const FAILED_TERMINAL_STATUSES = new Set([
    "error",
    "failed",
    "failed_provider",
    "failed_runtime",
    "stop_failed",
  ]);

  it("treats every backend terminal round status as ended", () => {
    for (const status of BACKEND_TERMINAL_STATUSES) {
      expect(chatRoundIsTerminal(status), status).toBe(true);
      expect(boundChatRoundsAreTerminal({
        meeting: meeting({ chatRoomRoundIds: ["r1"] }),
        chatRounds: [{ roundId: "r1", status }],
      }), status).toBe(true);
    }
  });

  it("keeps non-terminal and unknown round statuses open", () => {
    for (const status of ["queued", "running", "stopping", "", "unknown_new_status"]) {
      expect(chatRoundIsTerminal(status), status).toBe(false);
    }
    expect(chatRoundIsTerminal(undefined)).toBe(false);
  });

  it("replays legacy spellings (partial, finished) as terminal", () => {
    expect(chatRoundIsTerminal("partial")).toBe(true);
    expect(chatRoundIsTerminal(" Finished ")).toBe(true);
  });

  it("classifies failed endings apart from normal endings", () => {
    for (const status of BACKEND_TERMINAL_STATUSES) {
      expect(chatRoundIsFailedTerminal(status), status)
        .toBe(FAILED_TERMINAL_STATUSES.has(status));
    }
    expect(chatRoundIsFailedTerminal("partial")).toBe(false);
  });

  it("flags an abnormal close when any bound round failed", () => {
    expect(boundChatRoundsFailedTerminal({
      meeting: meeting({ chatRoomRoundIds: ["r1", "r2"] }),
      chatRounds: [
        { roundId: "r1", status: "completed" },
        { roundId: "r2", status: "failed_provider" },
      ],
    })).toBe(true);
    // A user stop is an intentional end, not an abnormal one.
    expect(boundChatRoundsFailedTerminal({
      meeting: meeting({ chatRoomRoundIds: ["r1", "r2"] }),
      chatRounds: [
        { roundId: "r1", status: "completed" },
        { roundId: "r2", status: "stopped_by_user" },
      ],
    })).toBe(false);
    expect(boundChatRoundsFailedTerminal({ meeting: meeting() })).toBe(false);
  });
});

describe("canonical task focus", () => {
  it("uses the V2 target without inferring a phase", () => {
    expect(focusNodeFromNextAction({stage: "review_running", targetNodeId: "hf_meeting_5", navigationLabel: "评审"})).toBe("hf_meeting_5");
  });
});
