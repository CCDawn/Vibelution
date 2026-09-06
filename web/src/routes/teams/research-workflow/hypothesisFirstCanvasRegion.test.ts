import { describe, expect, it } from "vitest";
import type { MeetingRoundRecord, PhaseState } from "../../../api/types/hypothesisFirst";
import { stateV2 } from "./hypothesisFirstV2.fixture";
import { buildHypothesisFirstCanvasRegion, hypothesisFirstSemanticNodeId, isHypothesisFirstCanvasNode, summarizeHypothesisReviewMeetings } from "./hypothesisFirstCanvasRegion";
const scope = { program: "p", theme: "t", campaign: "c", question: "Q-01", branch: "b", workflow: "w", agentId: "a" };
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


function region(state: ReturnType<typeof stateV2> | null, meetings: MeetingRoundRecord[] = []) {
  return buildHypothesisFirstCanvasRegion({ stateV2: state, meetings });
}

describe("canonical V2 canvas", () => {
  it("has no inferred region when V2 is absent", () => {
    expect(region(null, [meeting(1, "open")])).toBeNull();
  });
  it.each([
    [{ lifecycle: "running", actionability: "executing" }, "running"],
    [{ lifecycle: "running", actionability: "waiting_system" }, "running"],
    [{ lifecycle: "waiting_human", actionability: "waiting_user" }, "waiting_human"],
    [{ lifecycle: "failed", actionability: "blocked" }, "failed"],
    [{ lifecycle: "running", actionability: "blocked" }, "blocked"],
    [{ lifecycle: "cancelled", actionability: "terminal" }, "cancelled"],
    [{ lifecycle: "queued", actionability: "waiting_system" }, "pending"],
    [{ lifecycle: "completed", outcome: "succeeded", actionability: "terminal" }, "succeeded"],
  ] as [Partial<PhaseState>, string][])("uses V2 generation phase %j despite a stale closed meeting", (phase, expected) => {
    const graph = region(stateV2({generation: {...phase, generationMeetingId: "canonical-generation"}}), [meeting(0, "closed", {meetingType: "hypothesis_candidate_generation", digestId: "old"})])!;
    expect(graph.nodes.find(node => node.nodeId === "hf_generation")?.status).toBe(expected);
  });
  it("shows canonical committed selection before its auxiliary record arrives", () => {
    const graph = region(stateV2({selection: {selectionId: "sel", selectedCandidateIds: ["a", "b"], lifecycle: "completed", outcome: "succeeded", actionability: "terminal"}}))!;
    expect(graph.nodes.find(node => node.nodeId === "hf_selection")).toMatchObject({status: "succeeded", description: "已选 2 个候选假说"});
    expect(graph.nodes.some(node => node.nodeId === "hf_review")).toBe(true);
  });
  it("shows aggregate review status when candidate meetings have different outcomes", () => {
    const graph = region(stateV2({review: {lifecycle: "running", actionability: "executing", activeRoundIndex: 2}}), [meeting(1,"closed",{digestId:"d"}), meeting(2,"failed")])!;
    expect(graph.nodes.find(node => node.nodeId === "hf_review")?.status).toBe("running");
  });
  it("shows collection without waiting for request details", () => {
    const graph = region(stateV2({collection: {lifecycle: "failed", actionability: "blocked", aggregate: {total: 2, completed: 1, failed: 1, pending: 0, blocked: 0}}}))!;
    expect(graph.nodes.find(node => node.nodeId === "hf_collection")).toMatchObject({status:"failed", description:"2 个资料请求 · 当前步骤执行失败"});
    expect(graph.showDownstreamPipeline).toBe(true);
  });
  it("projects convergence gates and semantic edges from V2", () => {
    const graph = region(stateV2({selection: {selectionId:"s", selectedCandidateIds:["a"], lifecycle:"completed", outcome:"succeeded"}, review: {lifecycle:"completed", outcome:"succeeded"}, convergence: {lifecycle:"waiting_human", actionability:"blocked", outcome:"exhausted"}}))!;
    expect(graph.nodes.find(node => node.nodeId === "hf_convergence_gate")?.status).toBe("blocked");
    expect(graph.edges.some(edge => edge.fromNodeId === "hf_review" && edge.toNodeId === "source_finding")).toBe(true);
    expect(graph.edges.some(edge => edge.fromNodeId === "hf_convergence_gate" && edge.toNodeId === "hypothesis_design")).toBe(true);
  });
  it("keeps business canvas IDs distinct from history IDs", () => {
    expect(isHypothesisFirstCanvasNode("hf_review")).toBe(true);
    expect(isHypothesisFirstCanvasNode("hypothesis_design")).toBe(false);
    expect(hypothesisFirstSemanticNodeId("hf_meeting_2_a")).toBe("hf_review");
    expect(hypothesisFirstSemanticNodeId("hf_collection_req")).toBe("hf_collection");
  });
});

describe("review history summaries", () => {
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
});


it("renders a rejected convergence as terminal failure instead of pending", () => {
  const graph = region(stateV2({convergence: {lifecycle: "completed", outcome: "rejected", actionability: "terminal"}}))!;
  expect(graph.nodes.find(node => node.nodeId === "hf_convergence_gate"))
    .toMatchObject({status: "failed", description: "本轮已结束，假说未收敛"});
});
