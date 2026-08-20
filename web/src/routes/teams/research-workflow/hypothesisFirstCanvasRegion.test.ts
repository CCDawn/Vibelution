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
  HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
  HYPOTHESIS_FIRST_GENERATION_NODE_ID,
  HYPOTHESIS_FIRST_SELECTION_NODE_ID,
  HYPOTHESIS_FIRST_STAGE_ID,
  isHypothesisFirstCanvasNode,
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
  it("returns null only when the chain has no question identity", () => {
    expect(regionOf({ chainState: null })).toBeNull();
  });

  it("empty chain still renders the region: selection card waits for candidate generation", () => {
    const region = regionOf({})!;
    expect(region).not.toBeNull();
    const selectionNode = region.nodes.find(
      (node) => node.nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID,
    )!;
    expect(selectionNode.status).toBe("pending");
    expect(selectionNode.description).toBe("等待生成候选假说");
    expect(region.nodes.some((node) => node.nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID)).toBe(
      false,
    );
    expect(region.nodes.some((node) => node.nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID)).toBe(
      false,
    );
    expect(region.showDownstreamPipeline).toBe(false);
    expect(region.stage.progress).toEqual({ completed: 0, total: 1 });
    expect(region.stage.stageTone).toBe("idle");
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

  it("selection only: selection card succeeded, no future gate, no pipeline", () => {
    const region = regionOf({ selection: selection() })!;
    expect(region).not.toBeNull();
    expect(region.stage.stageId).toBe(HYPOTHESIS_FIRST_STAGE_ID);
    expect(region.stage.label).toBe("假说先行");
    expect(region.stage.index).toBe(0);
    expect(region.stage.progress).toEqual({ completed: 1, total: 1 });
    expect(region.stage.stageTone).toBe("done");
    expect(region.showDownstreamPipeline).toBe(false);

    const ids = region.nodes.map((node) => node.nodeId);
    expect(ids).toEqual([HYPOTHESIS_FIRST_SELECTION_NODE_ID]);
    const selectionNode = region.nodes[0]!;
    expect(selectionNode.visualKind).toBe("human_gate");
    expect(selectionNode.status).toBe("succeeded");
    expect(selectionNode.description).toContain("3 个候选");
    expect(region.edges).toEqual([]);
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
    expect(region.edges.some((edge) => edge.edgeId === "hf_e_sel_m1")).toBe(false);
  });

  it("with candidates but no selection the selection card waits for a human", () => {
    const region = regionOf({
      meetings: [meeting(1, "open")],
      chainState: chainState({ candidateCount: 2 }),
    })!;
    const selectionNode = region.nodes.find((node) => node.nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID)!;
    expect(selectionNode.status).toBe("waiting_human");
    expect(region.edges.some((edge) => edge.edgeId === "hf_e_sel_m1")).toBe(false);
  });

  it("first round open: meeting card running, no future gate or pipeline", () => {
    const region = regionOf({
      selection: selection(),
      meetings: [meeting(1, "open")],
      chainState: chainState({ meetingCount: 1, firstMeetingId: "hf-review-sel-1-r1", openMeetingIds: ["hf-review-sel-1-r1"] }),
    })!;
    const meetingNode = region.nodes.find((node) => node.nodeId === "hf_meeting_1")!;
    expect(meetingNode.status).toBe("running");
    expect(meetingNode.visualKind).toBe("agent_task");

    const edgeIds = region.edges.map((edge) => edge.edgeId);
    expect(edgeIds).toEqual(["hf_e_sel_m1"]);
    expect(region.nodes.some((node) => node.nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID)).toBe(false);
    expect(region.showDownstreamPipeline).toBe(false);
    const entry = region.edges[0]!;
    expect(entry).toMatchObject({
      fromNodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
      toNodeId: "hf_meeting_1",
      label: "选定假说",
      // decision_branch keeps the label narrative-visible in serpentine mode.
      semanticKind: "decision_branch",
      labelAlwaysVisible: true,
    });
  });

  it("maps meeting statuses: summarizing/awaiting_approval wait on humans, closed without digest is blocked", () => {
    const region = regionOf({
      meetings: [
        meeting(1, "summarizing"),
        meeting(2, "awaiting_approval", { previousMeetingRoundId: "hf-review-sel-1-r1" }),
        meeting(3, "closed", { previousMeetingRoundId: "hf-review-sel-1-r2" }),
      ],
    })!;
    expect(region.nodes.find((node) => node.nodeId === "hf_meeting_1")?.status).toBe("waiting_human");
    expect(region.nodes.find((node) => node.nodeId === "hf_meeting_2")?.status).toBe("waiting_human");
    // fail-closed: closed round without digestRef is NOT succeeded.
    expect(region.nodes.find((node) => node.nodeId === "hf_meeting_3")?.status).toBe("blocked");
    // Direct continuations (no collection bridge) carry the 再讨论 label.
    const continuations = region.edges.filter((edge) => edge.label === "再讨论");
    expect(continuations.map((edge) => edge.edgeId)).toEqual(["hf_e_m1_m2", "hf_e_m2_m3"]);
    expect(continuations.every((edge) => edge.semanticKind === "main")).toBe(true);
    expect(continuations.every((edge) => !edge.labelAlwaysVisible)).toBe(true);
  });

  it("collection in flight: decision_branch edge from the meeting to a pending collection card", () => {
    const region = regionOf({
      selection: selection(),
      meetings: [meeting(1, "closed", { digestRef: "digest-1", closedAt: "2026-08-19T02:00:00Z" })],
      collectionRequests: [request("req-1", "hf-review-sel-1-r1")],
      chainState: chainState({ meetingCount: 1, collectionRequestCount: 1, pendingCollectionCount: 1 }),
    })!;
    const meetingNode = region.nodes.find((node) => node.nodeId === "hf_meeting_1")!;
    expect(meetingNode.status).toBe("succeeded");
    const collectionNode = region.nodes.find((node) => node.nodeId === "hf_collection_req-1")!;
    expect(collectionNode).toMatchObject({
      label: "资料搜集 · 缺口 1",
      visualKind: "system_task",
      status: "pending",
    });
    const decision = region.edges.find((edge) => edge.edgeId === "hf_e_m1_creq-1")!;
    expect(decision).toMatchObject({
      fromNodeId: "hf_meeting_1",
      toNodeId: "hf_collection_req-1",
      label: "搜集决策",
      semanticKind: "decision_branch",
      labelAlwaysVisible: true,
    });
    // No handoff yet → no 知识包交接 edge, no second round.
    expect(region.edges.some((edge) => edge.label === "知识包交接")).toBe(false);
    expect(region.nodes.some((node) => node.nodeId === "hf_meeting_2")).toBe(false);
    expect(region.stage.progress).toEqual({ completed: 2, total: 4 });
    expect(region.showDownstreamPipeline).toBe(true);
  });

  it("two closed rounds: handoff edge bridges collection to round 2 and progress counts completed cards", () => {
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
    expect(region.nodes.find((node) => node.nodeId === "hf_collection_req-1")?.status).toBe("succeeded");
    const handoff = region.edges.find((edge) => edge.edgeId === "hf_e_creq-1_m2")!;
    expect(handoff).toMatchObject({
      fromNodeId: "hf_collection_req-1",
      toNodeId: "hf_meeting_2",
      label: "知识包交接",
      semanticKind: "main",
      // knowledge_package gate kind keeps the handoff label narrative-visible.
      gateKind: "knowledge_package",
      labelAlwaysVisible: true,
    });
    // Bridged continuation must NOT also draw a direct 再讨论 edge.
    expect(region.edges.some((edge) => edge.edgeId === "hf_e_m1_m2")).toBe(false);
    // Latest meeting feeds the convergence gate.
    expect(region.edges.some((edge) => edge.edgeId === "hf_e_m2_gate")).toBe(true);
    expect(region.stage.progress).toEqual({ completed: 4, total: 5 });
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
      "hf_meeting_1",
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
});

describe("superseded review attempts fold into the next round (GitHub Actions attempt pattern)", () => {
  it("folds an empty superseded round into the successor's retry badge", () => {
    const region = regionOf({
      meetings: [
        meeting(1, "closed", { digestRef: "digest-1" }),
        meeting(2, "closed", { recoveryReason: "discussion_has_no_completed_messages" }),
        meeting(3, "open"),
      ],
    });
    const labels = region!.nodes.map((node) => node.label);
    expect(labels).toContain("第 1 轮讨论·评审");
    expect(labels).not.toContain("第 2 轮讨论·评审");
    expect(labels).toContain("第 3 轮讨论·评审");

    const round3 = region!.nodes.find((node) => node.label === "第 3 轮讨论·评审")!;
    expect(round3.description).toContain("含 1 次失败重试");
    expect(round3.status).toBe("running");

    // The chain edge hops over the folded round: r1 → r3, never a dangling r2.
    const edgePairs = region!.edges.map((edge) => `${edge.fromNodeId}->${edge.toNodeId}`);
    expect(edgePairs).toContain("hf_meeting_1->hf_meeting_3");
    expect(edgePairs.join(" ")).not.toContain("hf_meeting_2");
  });

  it("keeps a trailing superseded round visible when no successor opened yet", () => {
    const region = regionOf({
      meetings: [
        meeting(1, "closed", { digestRef: "digest-1" }),
        meeting(2, "closed", { recoveryReason: "discussion_has_no_completed_messages" }),
      ],
    });
    const round2 = region!.nodes.find((node) => node.label === "第 2 轮讨论·评审");
    expect(round2).toBeDefined();
    expect(round2!.description).toContain("发言失败已跳过，等待重试");
    expect(round2!.status).toBe("blocked");
  });

  it("does not fold normal closed rounds", () => {
    const region = regionOf({
      meetings: [
        meeting(1, "closed", { digestRef: "digest-1" }),
        meeting(2, "closed", { digestRef: "digest-2" }),
      ],
    });
    const labels = region!.nodes.map((node) => node.label);
    expect(labels).toContain("第 1 轮讨论·评审");
    expect(labels).toContain("第 2 轮讨论·评审");
    const round2 = region!.nodes.find((node) => node.label === "第 2 轮讨论·评审")!;
    expect(round2.description).not.toContain("失败重试");
  });

  it("treats digestId (the real ledger field) as a closed round's digest", () => {
    const region = regionOf({
      meetings: [meeting(1, "closed", { digestId: "digest-2323357103026cb8", closedAt: "2026-08-20T03:41:47Z" })],
    });
    const round1 = region!.nodes.find((node) => node.label === "第 1 轮讨论·评审")!;
    expect(round1.status).toBe("succeeded");
    expect(round1.description).toContain("已闭环");
  });

  it("folds a closed round without any digest into the successor as a failed attempt", () => {
    const region = regionOf({
      meetings: [
        meeting(1, "closed", { closedAt: "2026-08-20T07:56:48Z" }),
        meeting(2, "closed", { recoveryReason: "discussion_has_no_completed_messages" }),
        meeting(3, "summarizing"),
      ],
    });
    const labels = region!.nodes.map((node) => node.label);
    expect(labels).not.toContain("第 1 轮讨论·评审");
    expect(labels).not.toContain("第 2 轮讨论·评审");
    expect(labels).toContain("第 3 轮讨论·评审");
    const round3 = region!.nodes.find((node) => node.label === "第 3 轮讨论·评审")!;
    expect(round3.description).toContain("含 2 次失败重试");
    expect(round3.status).toBe("waiting_human");
  });

  it("keeps a trailing closed round without a digest visible as blocked", () => {
    const region = regionOf({
      meetings: [meeting(1, "closed", { closedAt: "2026-08-20T07:56:48Z" })],
    });
    const round1 = region!.nodes.find((node) => node.label === "第 1 轮讨论·评审");
    expect(round1).toBeDefined();
    expect(round1!.status).toBe("blocked");
    expect(round1!.description).toContain("已关闭但缺少纪要");
  });
});
