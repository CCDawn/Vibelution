import ELK from "elkjs/lib/elk.bundled.js";
import { describe, expect, it } from "vitest";

import type {
  HypothesisFirstChainState,
  MeetingRoundRecord,
} from "../../../../../api/types/hypothesisFirst";
import {
  buildHypothesisFirstCanvasRegion,
  type HypothesisFirstCanvasRegionInput,
} from "../../../../../routes/teams/research-workflow/hypothesisFirstCanvasRegion";
import { composeHypothesisFirstGraph } from "../../../../../routes/teams/research-workflow/researchProcessGraphModel";
import { structuralWorkflowLayoutHash } from "./workflowLayoutHash";
import { resolveElkPorts } from "./workflowElkPorts";
import { challengeCupDefinition } from "./workflowElkLayout.test";
import { layoutTwoLevel } from "./workflowTwoLevelLayout";
import { resolveEdgeLabelSpec } from "./workflowEdgeLabelGeometry";

async function layoutSerpentine() {
  return layoutTwoLevel(challengeCupDefinition(), new ELK(), undefined, {
    layoutMode: "serpentine",
  });
}

describe("workflow serpentine layout", () => {
  it("stacks stage territories and alternates their task direction", async () => {
    const input = challengeCupDefinition();
    const result = await layoutSerpentine();
    const stages = result.nodes.filter((node) => node.kind === "stage");
    expect(stages.sort((a, b) => a.y - b.y).map((stage) => stage.stageId)).toEqual(
      input.stages.map((stage) => stage.stageId),
    );

    const xOf = (nodeId: string) => result.nodes.find((node) => node.id === nodeId)!.x;
    expect(xOf("source_finding")).toBeLessThan(xOf("knowledge_handoff"));
    expect(xOf("hypothesis_design")).toBeGreaterThan(xOf("smoke_gate"));
    expect(xOf("controlled_run")).toBeLessThan(xOf("iteration_decision"));
  });

  it("uses bottom-to-top stage handoff ports while keeping the decision feedback loop horizontal", () => {
    const input = challengeCupDefinition();
    const ports = resolveElkPorts({
      nodes: input.nodes,
      edges: input.edges,
      stageOrder: input.stages.map((stage) => stage.stageId),
      layoutMode: "serpentine",
    });
    const handoff = ports.byEdgeId.get("e_kc_hypothesis")!;
    expect(ports.byNodeId.get("knowledge_handoff")?.find((port) => port.id === handoff.sourcePortId)?.side).toBe("SOUTH");
    expect(ports.byNodeId.get("hypothesis_design")?.find((port) => port.id === handoff.targetPortId)?.side).toBe("NORTH");

    const rerun = ports.byEdgeId.get("e_decision_rerun")!;
    expect(ports.byNodeId.get("iteration_decision")?.find((port) => port.id === rerun.sourcePortId)?.side).toBe("WEST");
    expect(ports.byNodeId.get("controlled_run")?.find((port) => port.id === rerun.targetPortId)?.side).toBe("EAST");
  });

  it("places cross-stage labels inside the vertical channel between territories", async () => {
    const input = challengeCupDefinition();
    const result = await layoutSerpentine();
    const stageOf = new Map(input.nodes.map((node) => [node.nodeId, node.stageId] as const));
    const stageById = new Map(
      result.nodes.filter((node) => node.kind === "stage").map((stage) => [stage.stageId, stage] as const),
    );

    for (const edge of result.edges) {
      const sourceStageId = stageOf.get(edge.source);
      const targetStageId = stageOf.get(edge.target);
      if (!sourceStageId || !targetStageId || sourceStageId === targetStageId) continue;
      const sourceStage = stageById.get(sourceStageId)!;
      const targetStage = stageById.get(targetStageId)!;
      const label = edge.labelBounds;
      expect(label, edge.id).toBeDefined();
      expect(label!.y, edge.id).toBeGreaterThanOrEqual(sourceStage.y + sourceStage.height);
      expect(label!.y + label!.height, edge.id).toBeLessThanOrEqual(targetStage.y);
    }
  });

  it("places the knowledge-package label beside the vertical handoff", async () => {
    const result = await layoutSerpentine();
    const edge = result.edges.find((item) => item.id === "e_kc_hypothesis")!;
    const label = edge.labelBounds!;
    expect(edge.label).toBe("Knowledge Package");
    expect(label.width).toBe(resolveEdgeLabelSpec("Knowledge Package").width);
    expect(edge.sections.length).toBeGreaterThan(0);
    const strokeX = Math.max(
      ...edge.sections
        .filter((section) => Math.abs(section.start.x - section.end.x) < 1e-3)
        .map((section) => section.start.x),
    );
    expect(Number.isFinite(strokeX)).toBe(true);
    expect(label.x).toBeGreaterThan(strokeX);
  });

  it("uses a short narrative bridge for cross-stage handoffs", async () => {
    const result = await layoutSerpentine();
    for (const edgeId of ["e_kc_hypothesis", "e_smoke_run"]) {
      const edge = result.edges.find((item) => item.id === edgeId)!;
      expect(edge.sections.length, edgeId).toBeLessThanOrEqual(3);
      expect(edge.sections.every((section) => section.bendPoints.length === 0), edgeId).toBe(true);
    }
  });

  it("keeps rerun feedback on one local bottom rail", async () => {
    const result = await layoutSerpentine();
    const rerun = result.edges.find((edge) => edge.id === "e_decision_rerun")!;
    expect(rerun.sections.length).toBeLessThanOrEqual(5);
    const horizontalRail = rerun.sections.find(
      (section) => Math.abs(section.start.y - section.end.y) < 1e-3
        && Math.abs(section.start.x - section.end.x) > 200,
    );
    expect(horizontalRail).toBeDefined();
  });
});

/* ------------------------------------------------------------------ */
/* HFC-5 · hypothesis-first region (4-stage serpentine)                */
/* ------------------------------------------------------------------ */

const HF_SCOPE = {
  program: "p",
  theme: "t",
  campaign: "c",
  question: "Q-01",
  branch: "b",
  workflow: "w",
  agentId: "a",
};

function hfChainState(overrides: Partial<HypothesisFirstChainState> = {}): HypothesisFirstChainState {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    questionId: "Q-01",
    selectionId: "sel-1",
    meetingCount: 1,
    firstMeetingId: "hf-review-sel-1-r1",
    firstMeetingClosed: false,
    openMeetingIds: ["hf-review-sel-1-r1"],
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

function hfMeeting(
  roundIndex: number,
  status: MeetingRoundRecord["status"],
  overrides: Partial<MeetingRoundRecord> = {},
): MeetingRoundRecord {
  return {
    ...HF_SCOPE,
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

function hfRegionInput(rounds: 1 | 2): HypothesisFirstCanvasRegionInput {
  const base: HypothesisFirstCanvasRegionInput = {
    chainState: hfChainState(),
    meetings: [hfMeeting(1, "closed", { digestRef: "digest-1", closedAt: "2026-08-19T02:00:00Z" })],
    collectionRequests: [],
    reviewRoundLinks: [],
    selection: {
      ...HF_SCOPE,
      schemaVersion: 1,
      selectionId: "sel-1",
      selectionHash: "h",
      mode: "manual",
      scopeHash: "sh",
      questionId: "Q-01",
      selectedCandidateIds: ["cand-1"],
      previousSelectionId: "",
      decidedBy: "leader",
      createdAt: "2026-08-19T00:00:00Z",
    },
  };
  if (rounds === 2) {
    base.meetings = [
      ...base.meetings,
      hfMeeting(2, "open", { previousMeetingRoundId: "hf-review-sel-1-r1" }),
    ];
    base.collectionRequests = [{
      ...HF_SCOPE,
      schemaVersion: 1,
      recordKind: "hypothesis_first_collection_request",
      requestId: "req-1",
      requestHash: "rh",
      status: "handed_off",
      meetingRoundId: "hf-review-sel-1-r1",
      decisionId: "dec-1",
      questionId: "Q-01",
      mode: "review",
      scopeHash: "sh",
      searchEnvelope: {},
      requirements: {},
      writebackPolicy: {},
      collectionRunId: "run-req-1",
      createdAt: "2026-08-19T02:30:00Z",
      handedOffAt: "2026-08-19T03:00:00Z",
      handoffRef: "kp-1",
    }];
    base.reviewRoundLinks = [{
      schemaVersion: 1,
      recordKind: "hypothesis_first_review_round_link",
      linkId: "hf-link-2",
      meetingRoundId: "hf-review-sel-1-r2",
      previousMeetingRoundId: "hf-review-sel-1-r1",
      selectionId: "sel-1",
      collectionRequestId: "req-1",
      questionId: "Q-01",
      roundIndex: 2,
      createdAt: "2026-08-19T03:00:00Z",
    }];
    base.chainState = hfChainState({
      meetingCount: 2,
      collectionRequestCount: 1,
      collectionReady: true,
    });
  }
  return base;
}

function composedHypothesisFirstGraph(rounds: 1 | 2) {
  const region = buildHypothesisFirstCanvasRegion(hfRegionInput(rounds));
  return composeHypothesisFirstGraph(challengeCupDefinition(), region);
}

async function layoutHypothesisFirstSerpentine(rounds: 1 | 2) {
  return layoutTwoLevel(composedHypothesisFirstGraph(rounds), new ELK(), undefined, {
    layoutMode: "serpentine",
  });
}

function rectsOverlap(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number },
): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

describe("hypothesis-first region serpentine layout (HFC-5)", () => {
  it("stacks four stage territories in order and alternates R/L/R/L", async () => {
    const input = composedHypothesisFirstGraph(1);
    const result = await layoutHypothesisFirstSerpentine(1);
    const stages = result.nodes.filter((node) => node.kind === "stage");
    expect(stages.sort((a, b) => a.y - b.y).map((stage) => stage.stageId)).toEqual([
      "hypothesis_first",
      "knowledge_collection",
      "experiment_design",
      "execution_iteration",
    ]);
    expect(input.stages.map((stage) => stage.stageId)).toEqual([
      "hypothesis_first",
      "knowledge_collection",
      "experiment_design",
      "execution_iteration",
    ]);

    const xOf = (nodeId: string) => result.nodes.find((node) => node.id === nodeId)!.x;
    // Stage 0 (region) flows RIGHT: selection → meeting → gate.
    expect(xOf("hf_selection")).toBeLessThan(xOf("hf_meeting_1"));
    expect(xOf("hf_meeting_1")).toBeLessThan(xOf("hf_convergence_gate"));
    // Existing stages flip once: knowledge_collection now runs LEFT.
    expect(xOf("source_finding")).toBeGreaterThan(xOf("knowledge_handoff"));
    // experiment_design RIGHT, execution_iteration LEFT.
    expect(xOf("hypothesis_design")).toBeLessThan(xOf("smoke_gate"));
    expect(xOf("controlled_run")).toBeGreaterThan(xOf("iteration_decision"));
  });

  it("routes region gate edges across stages with labels inside the vertical channel", async () => {
    const input = composedHypothesisFirstGraph(1);
    const result = await layoutHypothesisFirstSerpentine(1);
    const stageOf = new Map(input.nodes.map((node) => [node.nodeId, node.stageId] as const));
    const stageById = new Map(
      result.nodes.filter((node) => node.kind === "stage").map((stage) => [stage.stageId, stage] as const),
    );

    for (const edgeId of ["hf_e_m1_stage1", "hf_e_gate_stage2"]) {
      const edge = result.edges.find((item) => item.id === edgeId)!;
      expect(edge, edgeId).toBeDefined();
      expect(edge.sections.length, edgeId).toBeGreaterThan(0);
      const sourceStage = stageById.get(stageOf.get(edge.source)!)!;
      const targetStage = stageById.get(stageOf.get(edge.target)!)!;
      const label = edge.labelBounds;
      expect(label, edgeId).toBeDefined();
      expect(label!.y, edgeId).toBeGreaterThanOrEqual(sourceStage.y + sourceStage.height);
      expect(label!.y + label!.height, edgeId).toBeLessThanOrEqual(targetStage.y);
    }
  });

  it("adding a round changes the structure hash and relayouts without overlap or stage drift", async () => {
    const before = composedHypothesisFirstGraph(1);
    const after = composedHypothesisFirstGraph(2);

    // Round growth = topology change → relayout; a status-only flip is not one.
    expect(structuralWorkflowLayoutHash(after).structure)
      .not.toBe(structuralWorkflowLayoutHash(before).structure);
    const statusFlip = composedHypothesisFirstGraph(1);
    statusFlip.nodes = statusFlip.nodes.map((node) =>
      node.nodeId === "hf_convergence_gate" ? { ...node, status: "succeeded" as const } : node);
    expect(structuralWorkflowLayoutHash(statusFlip).structure)
      .toBe(structuralWorkflowLayoutHash(before).structure);

    const result = await layoutHypothesisFirstSerpentine(2);
    const stageById = new Map(
      result.nodes.filter((node) => node.kind === "stage").map((stage) => [stage.stageId, stage] as const),
    );
    const stageOf = new Map(after.nodes.map((node) => [node.nodeId, node.stageId] as const));
    const tasks = result.nodes.filter((node) => node.kind === "task");

    // No card overlaps any other card.
    for (let i = 0; i < tasks.length; i += 1) {
      for (let j = i + 1; j < tasks.length; j += 1) {
        expect(rectsOverlap(tasks[i]!, tasks[j]!), `${tasks[i]!.id} vs ${tasks[j]!.id}`).toBe(false);
      }
    }

    // Bounded movement: every task stays inside its own stage territory.
    for (const task of tasks) {
      const stage = stageById.get(stageOf.get(task.id)!)!;
      expect(task.x, task.id).toBeGreaterThanOrEqual(stage.x - 1e-3);
      expect(task.x + task.width, task.id).toBeLessThanOrEqual(stage.x + stage.width + 1e-3);
      expect(task.y, task.id).toBeGreaterThanOrEqual(stage.y - 1e-3);
      expect(task.y + task.height, task.id).toBeLessThanOrEqual(stage.y + stage.height + 1e-3);
    }

    // The region chain keeps its ledger order along the stage direction.
    const xOf = (nodeId: string) => result.nodes.find((node) => node.id === nodeId)!.x;
    expect(xOf("hf_selection")).toBeLessThan(xOf("hf_meeting_1"));
    expect(xOf("hf_meeting_1")).toBeLessThan(xOf("hf_collection_req-1"));
    expect(xOf("hf_collection_req-1")).toBeLessThan(xOf("hf_meeting_2"));
    expect(xOf("hf_meeting_2")).toBeLessThan(xOf("hf_convergence_gate"));
  });
});
