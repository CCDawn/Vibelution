import { describe, expect, it } from "vitest";

import type {
  CollectionRequestRecord,
  HypothesisFirstChainState,
  HypothesisSelectionRecord,
  MeetingRoundRecord,
  ReviewRoundLinkRecord,
} from "../../../api/types/hypothesisFirst";
import {
  buildHypothesisFirstCanvasRegion,
  HYPOTHESIS_FIRST_COLLECTION_NODE_ID,
  HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
  HYPOTHESIS_FIRST_GENERATION_NODE_ID,
  HYPOTHESIS_FIRST_REVIEW_NODE_ID,
  HYPOTHESIS_FIRST_SELECTION_NODE_ID,
  HYPOTHESIS_FIRST_STAGE_ID,
  hypothesisFirstSemanticNodeId,
  isHypothesisFirstCanvasNode,
  summarizeHypothesisReviewMeetings,
  type HypothesisFirstCanvasRegionInput,
} from "./hypothesisFirstCanvasRegion";

const QUESTION_ID = "Q-01";

const scope = {
  program: "p",
  theme: "t",
  campaign: "c",
  question: QUESTION_ID,
  branch: "b",
  workflow: "w",
  agentId: "a",
};

function chainState(overrides: Partial<HypothesisFirstChainState> = {}): HypothesisFirstChainState {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    questionId: QUESTION_ID,
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
    ...overrides,
  };
}

function selection(overrides: Partial<HypothesisSelectionRecord> = {}): HypothesisSelectionRecord {
  return {
    ...scope,
    schemaVersion: 1,
    selectionId: "sel-1",
    selectionHash: "h",
    mode: "manual",
    scopeHash: "sh",
    questionId: QUESTION_ID,
    selectedCandidateIds: ["cand-1", "cand-2", "cand-3"],
    previousSelectionId: "",
    decidedBy: "leader",
    createdAt: "2026-08-19T00:00:00Z",
    ...overrides,
  };
}

function meeting(
  roundIndex: number,
  status: MeetingRoundRecord["status"],
  overrides: Partial<MeetingRoundRecord> = {},
): MeetingRoundRecord {
  return {
    ...scope,
    schemaVersion: 1,
    meetingRoundId: `hf-review-sel-1-r${roundIndex}`,
    meetingType: "hypothesis_review",
    mode: "review",
    scopeHash: "sh",
    participants: ["agent-1"],
    status,
    startedAt: `2026-08-19T0${roundIndex}:00:00Z`,
    roundIndex,
    ...overrides,
  };
}

function request(
  requestId: string,
  meetingRoundId: string,
  overrides: Partial<CollectionRequestRecord> = {},
): CollectionRequestRecord {
  return {
    ...scope,
    schemaVersion: 1,
    recordKind: "hypothesis_first_collection_request",
    requestId,
    requestHash: "rh",
    status: "pending",
    meetingRoundId,
    decisionId: `dec-${requestId}`,
    questionId: QUESTION_ID,
    mode: "review",
    scopeHash: "sh",
    searchEnvelope: {},
    requirements: {},
    writebackPolicy: {},
    collectionRunId: `run-${requestId}`,
    createdAt: "2026-08-19T02:30:00Z",
    ...overrides,
  };
}

function link(
  meetingRoundId: string,
  previousMeetingRoundId: string,
  collectionRequestId: string,
  roundIndex: number,
): ReviewRoundLinkRecord {
  return {
    schemaVersion: 1,
    recordKind: "hypothesis_first_review_round_link",
    linkId: `hf-link-${roundIndex}`,
    meetingRoundId,
    previousMeetingRoundId,
    selectionId: "sel-1",
    collectionRequestId,
    questionId: QUESTION_ID,
    roundIndex,
    createdAt: "2026-08-19T03:00:00Z",
  };
}

function regionOf(input: Partial<HypothesisFirstCanvasRegionInput>) {
  return buildHypothesisFirstCanvasRegion({
    chainState: chainState(),
    meetings: [],
    collectionRequests: [],
    reviewRoundLinks: [],
    selection: null,
    ...input,
  });
}

describe("hypothesisFirstCanvasRegion", () => {
  it("counts fan-out siblings as one logical review round", () => {
    const summary = summarizeHypothesisReviewMeetings([
      meeting(1, "closed", { meetingRoundId: "r1-a", digestId: "d1-a" }),
      meeting(1, "closed", { meetingRoundId: "r1-b", digestId: "d1-b" }),
      meeting(2, "awaiting_approval", { meetingRoundId: "r2-a" }),
    ]);

    expect(summary.effectiveRounds).toBe(2);
    expect(summary.latestRound).toBe(2);
  });

  it("does not fabricate round numbers for legacy meetings without roundIndex", () => {
    const summary = summarizeHypothesisReviewMeetings([
      meeting(1, "closed", { meetingRoundId: "r1-a", digestId: "d1-a" }),
      { ...meeting(1, "closed", { digestId: "d1-b" }), meetingRoundId: "legacy-a", roundIndex: undefined },
      { ...meeting(2, "closed", { recoveryReason: "discussion_has_no_completed_messages" }), meetingRoundId: "legacy-b", roundIndex: undefined },
    ]);

    // Legacy physical meetings must not become fabricated extra rounds, and
    // the latest round stays the max real roundIndex instead of list position.
    expect(summary.effectiveRounds).toBe(1);
    expect(summary.latestRound).toBe(1);
  });

  it("anchors the summary on the canonical round when provided", () => {
    const summary = summarizeHypothesisReviewMeetings([
      meeting(1, "closed", { meetingRoundId: "r1-a", digestId: "d1-a" }),
      meeting(1, "closed", { meetingRoundId: "r1-b", digestId: "d1-b" }),
    ], 5);

    expect(summary.effectiveRounds).toBe(1);
    expect(summary.latestRound).toBe(5);
  });

  it("caps legacy per-candidate roundIndex inflation at the canonical round", () => {
    // Old per-candidate writes produced ten distinct roundIndex values while
    // the canonical chain sits at round 5; neither count may exceed it.
    const inflated = Array.from({ length: 10 }, (_, index) =>
      meeting(index + 1, "closed", { meetingRoundId: `r${index + 1}`, digestId: `d${index + 1}` }));
    const summary = summarizeHypothesisReviewMeetings(inflated, 5);

    expect(summary.effectiveRounds).toBe(5);
    expect(summary.latestRound).toBe(5);
  });

  it("returns null only when the chain has no question identity", () => {
    expect(regionOf({ chainState: null })).toBeNull();
  });

  it("empty chain exposes candidate generation as the clear first step", () => {
    const region = regionOf({})!;
    expect(region).not.toBeNull();
    const generationNode = region.nodes.find(
      (node) => node.nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID,
    )!;
    expect(generationNode.status).toBe("waiting_human");
    expect(generationNode.description).toBe("尚未生成候选假说，点击卡片打开操作");
    const selectionNode = region.nodes.find(
      (node) => node.nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID,
    )!;
    expect(selectionNode.status).toBe("pending");
    expect(selectionNode.description).toBe("等待生成候选假说");
    expect(region.edges).toContainEqual(expect.objectContaining({
      edgeId: "hf_e_gen_sel",
      fromNodeId: HYPOTHESIS_FIRST_GENERATION_NODE_ID,
      toNodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
    }));
    expect(region.nodes.some((node) => node.nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID)).toBe(
      false,
    );
    expect(region.showDownstreamPipeline).toBe(false);
    expect(region.stage.progress).toEqual({ completed: 0, total: 2 });
    expect(region.stage.stageTone).toBe("attention");
  });

  it("open generation meeting renders the generation card before selection", () => {
    const generation = {
      ...meeting(1, "open"),
      meetingRoundId: "hf-gen-1",
      meetingType: "hypothesis_candidate_generation",
    };
    const region = regionOf({
      meetings: [generation],
      chainState: chainState({
        generationMeetingId: "hf-gen-1",
        generationMeetingStatus: "open",
      }),
    })!;
    const ids = region.nodes.map((node) => node.nodeId);
    expect(ids[0]).toBe(HYPOTHESIS_FIRST_GENERATION_NODE_ID);
    const generationNode = region.nodes[0]!;
    expect(generationNode.status).toBe("running");
    expect(generationNode.label).toBe("候选假说生成");
    const selectionNode = region.nodes.find(
      (node) => node.nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID,
    )!;
    expect(selectionNode.status).toBe("pending");
    expect(selectionNode.description).toBe("候选生成讨论进行中，产出后可选择");
    expect(
      region.edges.some(
        (edge) =>
          edge.edgeId === "hf_e_gen_sel"
          && edge.fromNodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID
          && edge.toNodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID,
      ),
    ).toBe(true);
  });

  it("closed generation meeting with candidates makes selection wait for a human", () => {
    const generation = {
      ...meeting(1, "closed"),
      meetingRoundId: "hf-gen-1",
      meetingType: "hypothesis_candidate_generation",
      digestRef: "digest/hf-gen-1",
    };
    const region = regionOf({
      meetings: [generation],
      chainState: chainState({
        candidateCount: 3,
        generationMeetingId: "hf-gen-1",
        generationMeetingStatus: "closed",
      }),
    })!;
    const generationNode = region.nodes.find(
      (node) => node.nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID,
    )!;
    expect(generationNode.status).toBe("succeeded");
    const selectionNode = region.nodes.find(
      (node) => node.nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID,
    )!;
    expect(selectionNode.status).toBe("waiting_human");
    expect(selectionNode.description).toBe("已产出 3 条候选，等待人工选择");
  });

  it("selection only: selection succeeds and the stable review card waits for its first round", () => {
    const region = regionOf({ selection: selection() })!;
    expect(region).not.toBeNull();
    expect(region.stage.stageId).toBe(HYPOTHESIS_FIRST_STAGE_ID);
    expect(region.stage.label).toBe("假说先行");
    expect(region.stage.index).toBe(0);
    expect(region.stage.progress).toEqual({ completed: 1, total: 2 });
    expect(region.stage.stageTone).toBe("idle");
    expect(region.showDownstreamPipeline).toBe(false);

    const ids = region.nodes.map((node) => node.nodeId);
    expect(ids).toEqual([HYPOTHESIS_FIRST_SELECTION_NODE_ID, HYPOTHESIS_FIRST_REVIEW_NODE_ID]);
    const selectionNode = region.nodes[0]!;
    expect(selectionNode.visualKind).toBe("human_gate");
    expect(selectionNode.status).toBe("succeeded");
    expect(selectionNode.description).toContain("3 个候选");
    expect(region.edges).toEqual([
      expect.objectContaining({
        edgeId: "hf_e_sel_review",
        fromNodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
        toNodeId: HYPOTHESIS_FIRST_REVIEW_NODE_ID,
      }),
    ]);
  });

  it("candidates without a generation meeting still show a completed generation card", () => {
    const region = regionOf({
      chainState: chainState({ candidateCount: 4 }),
    })!;
    const generationNode = region.nodes.find(
      (node) => node.nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID,
    )!;
    expect(generationNode.status).toBe("succeeded");
    expect(generationNode.description).toBe("已产出 4 条候选假说");
    expect(region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID)?.status).toBe(
      "waiting_human",
    );
    expect(region.stage.progress).toEqual({ completed: 1, total: 2 });
    expect(region.showDownstreamPipeline).toBe(false);
  });

  it("without candidates the selection card stays pending even if a review meeting exists", () => {
    const region = regionOf({ meetings: [meeting(1, "open")] })!;
    const selectionNode = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID)!;
    expect(selectionNode.status).toBe("pending");
    // No selection → no 选定假说 edge.
    expect(region.edges.some((edge) => edge.edgeId === "hf_e_sel_review")).toBe(false);
  });

  it("with candidates but no selection the selection card waits for a human", () => {
    const region = regionOf({
      meetings: [meeting(1, "open")],
      chainState: chainState({ candidateCount: 2 }),
    })!;
    const selectionNode = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID)!;
    expect(selectionNode.status).toBe("waiting_human");
    expect(region.edges.some((edge) => edge.edgeId === "hf_e_sel_review")).toBe(false);
  });

  it("projects an open first round as the single semantic review card", () => {
    const region = regionOf({
      selection: selection(),
      meetings: [meeting(1, "open")],
      chainState: chainState({ meetingCount: 1, firstMeetingId: "hf-review-sel-1-r1", openMeetingIds: ["hf-review-sel-1-r1"] }),
    })!;
    const reviewNode = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    expect(reviewNode.status).toBe("running");
    expect(reviewNode.visualKind).toBe("agent_task");
    expect(reviewNode.description).toBe("1 轮有效评审 · 0 次失败重试 · 最近第 1 轮");

    const edgeIds = region.edges.map((edge) => edge.edgeId);
    expect(edgeIds).toEqual(["hf_e_sel_review"]);
    expect(region.nodes.some((node) => node.nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID)).toBe(false);
    expect(region.showDownstreamPipeline).toBe(false);
    const entry = region.edges[0]!;
    expect(entry).toMatchObject({
      fromNodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
      toNodeId: HYPOTHESIS_FIRST_REVIEW_NODE_ID,
      label: "选定假说",
      // decision_branch keeps the label narrative-visible in serpentine mode.
      semanticKind: "decision_branch",
      labelAlwaysVisible: true,
    });
  });

  it("uses the latest attempt status while retaining all rounds in the summary", () => {
    const region = regionOf({
      meetings: [
        meeting(1, "summarizing"),
        meeting(2, "awaiting_approval", { previousMeetingRoundId: "hf-review-sel-1-r1" }),
        meeting(3, "closed", { previousMeetingRoundId: "hf-review-sel-1-r2" }),
      ],
    })!;
    const reviewNode = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    expect(reviewNode.status).toBe("blocked");
    expect(reviewNode.description).toBe("2 轮有效评审 · 1 次失败重试 · 最近第 3 轮");
    expect(region.nodes.filter((node) => node.label === "假说评审")).toHaveLength(1);
  });

  it("aggregates collection requests behind one semantic evidence card", () => {
    const region = regionOf({
      selection: selection(),
      meetings: [meeting(1, "closed", { digestRef: "digest-1", closedAt: "2026-08-19T02:00:00Z" })],
      collectionRequests: [request("req-1", "hf-review-sel-1-r1")],
      chainState: chainState({ meetingCount: 1, collectionRequestCount: 1, pendingCollectionCount: 1 }),
    })!;
    const reviewNode = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    expect(reviewNode.status).toBe("succeeded");
    const collectionNode = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_COLLECTION_NODE_ID)!;
    expect(collectionNode).toMatchObject({
      label: "资料补充",
      visualKind: "system_task",
      status: "pending",
    });
    const decision = region.edges.find((edge) => edge.edgeId === "hf_e_review_collection")!;
    expect(decision).toMatchObject({
      fromNodeId: HYPOTHESIS_FIRST_REVIEW_NODE_ID,
      toNodeId: HYPOTHESIS_FIRST_COLLECTION_NODE_ID,
      label: "补充证据",
      semanticKind: "main",
      labelAlwaysVisible: true,
    });
    expect(region.stage.progress).toEqual({ completed: 2, total: 4 });
    expect(region.showDownstreamPipeline).toBe(true);
  });

  it("projects child-run failure even when the durable request remains pending", () => {
    const region = regionOf({
      selection: selection(),
      meetings: [meeting(1, "closed", { digestRef: "digest-1" })],
      collectionRequests: [request("req-1", "hf-review-sel-1-r1", {
        status: "pending",
        collectionRunStatus: "needs_continue",
      })],
      chainState: chainState({ meetingCount: 1, collectionRequestCount: 1, pendingCollectionCount: 1 }),
    })!;
    const collectionNode = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_COLLECTION_NODE_ID)!;
    expect(collectionNode.status).toBe("failed");
    expect(collectionNode.description).toContain("需要恢复");
  });

  it("keeps multiple closed rounds and handoffs inside the semantic cards", () => {
    const region = regionOf({
      selection: selection(),
      meetings: [
        meeting(1, "closed", { digestRef: "digest-1", closedAt: "2026-08-19T02:00:00Z" }),
        meeting(2, "closed", {
          digestRef: "digest-2",
          closedAt: "2026-08-19T04:00:00Z",
          previousMeetingRoundId: "hf-review-sel-1-r1",
        }),
      ],
      collectionRequests: [
        request("req-1", "hf-review-sel-1-r1", {
          status: "handed_off",
          handedOffAt: "2026-08-19T03:00:00Z",
          handoffRef: "kp-1",
        }),
      ],
      reviewRoundLinks: [link("hf-review-sel-1-r2", "hf-review-sel-1-r1", "req-1", 2)],
      chainState: chainState({ meetingCount: 2, collectionRequestCount: 1, collectionReady: true }),
    })!;
    expect(region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_COLLECTION_NODE_ID)?.status).toBe("succeeded");
    expect(region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)?.description).toContain("2 轮有效评审");
    expect(region.nodes.filter((node) => node.nodeId.startsWith("hf_meeting_"))).toHaveLength(0);
    expect(region.edges.some((edge) => edge.edgeId === "hf_e_semantic_tail_gate")).toBe(true);
    expect(region.stage.progress).toEqual({ completed: 3, total: 4 });
    // All cards succeeded except the pending gate → no active/attention signal.
    expect(region.stage.stageTone).toBe("idle");
  });

  it("budget exhausted without convergence blocks the gate (human decision)", () => {
    const region = regionOf({
      selection: selection(),
      meetings: [meeting(1, "closed", { digestRef: "digest-1" })],
      chainState: chainState({ meetingCount: 1, roundBudget: 1, budgetExhausted: true }),
    })!;
    const gate = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID)!;
    expect(gate.status).toBe("blocked");
    expect(gate.description).toContain("预算耗尽");
    expect(region.stage.progress).toEqual({ completed: 2, total: 3 });
  });

  it("converged chain marks the gate succeeded and uses the convergence detail", () => {
    const region = regionOf({
      selection: selection(),
      meetings: [meeting(1, "closed", { digestRef: "digest-1" })],
      chainState: chainState({
        meetingCount: 1,
        hypothesisConverged: true,
        hypothesisRoundCount: 1,
        convergenceDetail: "评审收敛：候选 cand-1 胜出",
      }),
    })!;
    const gate = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID)!;
    expect(gate.status).toBe("succeeded");
    expect(gate.description).toBe("评审收敛：候选 cand-1 胜出");
  });

  it("filters out meetings and requests of other questions", () => {
    const region = regionOf({
      selection: selection(),
      meetings: [
        meeting(1, "open"),
        meeting(2, "open", { question: "Q-OTHER" }),
        { ...meeting(3, "open"), meetingType: "ad_hoc" },
      ],
      collectionRequests: [request("req-x", "hf-review-sel-1-r1", { questionId: "Q-OTHER" })],
    })!;
    expect(region.nodes.map((node) => node.nodeId)).toEqual([
      HYPOTHESIS_FIRST_SELECTION_NODE_ID,
      HYPOTHESIS_FIRST_REVIEW_NODE_ID,
    ]);
  });

  it("identifies region nodes by the hf_ prefix", () => {
    expect(isHypothesisFirstCanvasNode("hf_selection")).toBe(true);
    expect(isHypothesisFirstCanvasNode("hf_meeting_2")).toBe(true);
    expect(isHypothesisFirstCanvasNode("hf_collection_req-1")).toBe(true);
    expect(isHypothesisFirstCanvasNode("hf_convergence_gate")).toBe(true);
    expect(isHypothesisFirstCanvasNode("source_finding")).toBe(false);
    expect(isHypothesisFirstCanvasNode(null)).toBe(false);
  });

  it("maps ledger instance ids to stable canvas node ids", () => {
    expect(hypothesisFirstSemanticNodeId("hf_meeting_5")).toBe(HYPOTHESIS_FIRST_REVIEW_NODE_ID);
    expect(hypothesisFirstSemanticNodeId("hf_collection_req-1")).toBe(HYPOTHESIS_FIRST_COLLECTION_NODE_ID);
    expect(hypothesisFirstSemanticNodeId("source_finding")).toBe(HYPOTHESIS_FIRST_COLLECTION_NODE_ID);
    expect(hypothesisFirstSemanticNodeId("hf_selection")).toBe(HYPOTHESIS_FIRST_SELECTION_NODE_ID);
  });
});

describe("review attempts aggregate behind one semantic card", () => {
  it("summarizes effective rounds, retries and the latest round", () => {
    const region = regionOf({
      meetings: [
        meeting(1, "closed", { digestRef: "digest-1" }),
        meeting(2, "closed", { recoveryReason: "discussion_has_no_completed_messages" }),
        meeting(3, "open"),
      ],
    });
    const review = region!.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    expect(review.description).toBe("2 轮有效评审 · 1 次失败重试 · 最近第 3 轮");
    expect(review.status).toBe("running");
    expect(region!.nodes.filter((node) => node.label === "假说评审")).toHaveLength(1);
  });

  it("surfaces a trailing failed attempt as the aggregate card status", () => {
    const region = regionOf({
      meetings: [
        meeting(1, "closed", { digestRef: "digest-1" }),
        meeting(2, "closed", { recoveryReason: "discussion_has_no_completed_messages" }),
      ],
    });
    const review = region!.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    expect(review.description).toBe("1 轮有效评审 · 1 次失败重试 · 最近第 2 轮");
    expect(review.status).toBe("blocked");
  });

  it("counts normal closed rounds as effective", () => {
    const region = regionOf({
      meetings: [
        meeting(1, "closed", { digestRef: "digest-1" }),
        meeting(2, "closed", { digestRef: "digest-2" }),
      ],
    });
    const review = region!.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    expect(review.description).toBe("2 轮有效评审 · 0 次失败重试 · 最近第 2 轮");
    expect(review.status).toBe("succeeded");
  });

  it("treats digestId (the real ledger field) as a closed round's digest", () => {
    const region = regionOf({
      meetings: [meeting(1, "closed", { digestId: "digest-2323357103026cb8", closedAt: "2026-08-20T03:41:47Z" })],
    });
    const review = region!.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    expect(review.status).toBe("succeeded");
    expect(review.description).toContain("1 轮有效评审");
  });

  it("folds a closed round without any digest into the successor as a failed attempt", () => {
    const region = regionOf({
      meetings: [
        meeting(1, "closed", { closedAt: "2026-08-20T07:56:48Z" }),
        meeting(2, "closed", { recoveryReason: "discussion_has_no_completed_messages" }),
        meeting(3, "summarizing"),
      ],
    });
    const review = region!.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    expect(review.description).toBe("1 轮有效评审 · 2 次失败重试 · 最近第 3 轮");
    expect(review.status).toBe("waiting_human");
  });

  it("keeps a trailing closed round without a digest visible as blocked", () => {
    const region = regionOf({
      meetings: [meeting(1, "closed", { closedAt: "2026-08-20T07:56:48Z" })],
    });
    const review = region!.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    expect(review.status).toBe("blocked");
    expect(review.description).toBe("0 轮有效评审 · 1 次失败重试 · 最近第 1 轮");
  });

  it("degrades the review card copy when legacy data has no round numbers", () => {
    const region = regionOf({
      meetings: [
        { ...meeting(1, "closed", { digestId: "d-legacy" }), meetingRoundId: "legacy-a", roundIndex: undefined },
        { ...meeting(1, "closed"), meetingRoundId: "legacy-b", roundIndex: undefined },
      ],
    })!;
    const review = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    expect(review.description).toBe("有效轮数未知 · 1 次失败重试 · 最近轮次未知");
  });

  it("uses the canonical round for the review card when meetings lack roundIndex", () => {
    const region = regionOf({
      meetings: [
        { ...meeting(1, "closed", { digestId: "d-legacy" }), meetingRoundId: "legacy-a", roundIndex: undefined },
      ],
      activeRoundIndex: 5,
    })!;
    const review = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID)!;
    // The latest round is known (canonical) but the effective count of
    // numberless meetings is not — never show a fabricated or false-zero count.
    expect(review.description).toBe("有效轮数未知 · 0 次失败重试 · 最近第 5 轮");
  });
});
