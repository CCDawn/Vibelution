import { describe, expect, it } from "vitest";

import type { KnowledgeInvocationBadge } from "../../../api/types/research-workflow/core";
import {
  buildKnowledgeSideflowCanvasRegion,
  composeKnowledgeSideflowGraph,
  definitionNeedsSideflowRegion,
  isKnowledgeSideflowCanvasNode,
  knowledgeSideflowCanvasNodeId,
  knowledgeSideflowSemanticNodeId,
  KNOWLEDGE_SIDEFLOW_NODE_PREFIX,
  sideflowNodeStatesFromBadges,
} from "./knowledgeSideflowCanvasRegion";
import type { WorkflowLayoutInput } from "../../../components/vui";

function badge(overrides: Partial<KnowledgeInvocationBadge> = {}): KnowledgeInvocationBadge {
  return {
    nodeId: "problem_understanding",
    totalCount: 1,
    runningCount: 0,
    awaitingHandoffCount: 0,
    absorbedCount: 0,
    ...overrides,
  };
}

function baseGraph(): WorkflowLayoutInput {
  const node = (nodeId: string) => ({
    nodeId,
    stageId: `stage_${nodeId}`,
    label: nodeId,
    actorKind: "agent" as const,
    visualKind: "agent_task" as const,
    status: "pending" as const,
  });
  return {
    stages: [{ stageId: "stage_a", label: "A", nodeIds: ["problem_understanding", "hypothesis_design"] }],
    nodes: [node("problem_understanding"), node("hypothesis_design")],
    edges: [
      {
        edgeId: "e1",
        fromNodeId: "problem_understanding",
        toNodeId: "hypothesis_design",
        label: "",
        gateKind: "auto",
        semanticKind: "main",
        pathState: "idle",
        labelAlwaysVisible: false,
      },
    ],
    run: {
      runId: "run-1",
      status: "running",
      runtimeCurrentNodeIds: [],
    },
  };
}

describe("knowledgeSideflowCanvasRegion ids", () => {
  it("round-trips canvas and semantic node ids", () => {
    const canvasId = knowledgeSideflowCanvasNodeId("source_finding");
    expect(canvasId).toBe(`${KNOWLEDGE_SIDEFLOW_NODE_PREFIX}source_finding`);
    expect(isKnowledgeSideflowCanvasNode(canvasId)).toBe(true);
    expect(isKnowledgeSideflowCanvasNode("source_finding")).toBe(false);
    expect(knowledgeSideflowSemanticNodeId(canvasId)).toBe("source_finding");
    expect(knowledgeSideflowSemanticNodeId("hf_generation")).toBeNull();
  });
});

describe("definitionNeedsSideflowRegion", () => {
  it("is true for definitions without an in-graph knowledge chain (main 3.0.0)", () => {
    expect(
      definitionNeedsSideflowRegion({ nodes: [{ nodeId: "problem_understanding" }, { nodeId: "hypothesis_design" }] }),
    ).toBe(true);
  });

  it("is false for the legacy 17-node definition (knowledge nodes are in-graph)", () => {
    expect(
      definitionNeedsSideflowRegion({ nodes: [{ nodeId: "knowledge_handoff" }] }),
    ).toBe(false);
  });

  it("is false without a definition", () => {
    expect(definitionNeedsSideflowRegion(null)).toBe(false);
  });
});

describe("sideflowNodeStatesFromBadges", () => {
  it("derives five cards from the most recent invocation only", () => {
    const states = sideflowNodeStatesFromBadges({
      problem_understanding: badge({
        latest: {
          invocationId: "inv-1",
          parentNodeId: "problem_understanding",
          status: "running",
          handoffState: null,
          currentKnowledgeNodeId: "evidence_relations",
          knowledgeChildRunId: "child-1",
          updatedAtMs: 20,
        },
      }),
      source_finding: badge({
        nodeId: "source_finding",
        latest: {
          invocationId: "inv-0",
          parentNodeId: "source_finding",
          status: "completed",
          handoffState: "completed",
          currentKnowledgeNodeId: "knowledge_handoff",
          updatedAtMs: 10,
        },
      }),
    });
    expect(states.map((state) => state.status)).toEqual([
      "succeeded",
      "succeeded",
      "running",
      "pending",
      "pending",
    ]);
    expect(states[0].latest?.invocationId).toBe("inv-1");
  });

  it("maps awaiting_handoff to waiting_human at the handoff gate", () => {
    const states = sideflowNodeStatesFromBadges({
      problem_understanding: badge({
        awaitingHandoffCount: 1,
        latest: {
          invocationId: "inv-2",
          parentNodeId: "problem_understanding",
          status: "awaiting_handoff",
          handoffState: "awaiting_human",
          currentKnowledgeNodeId: "knowledge_handoff",
          updatedAtMs: 30,
        },
      }),
    });
    expect(states[4].status).toBe("waiting_human");
  });

  it("keeps all cards pending without any invocation", () => {
    const states = sideflowNodeStatesFromBadges({
      problem_understanding: badge({ latest: null }),
    });
    expect(states.every((state) => state.status === "pending")).toBe(true);
  });
});

describe("buildKnowledgeSideflowCanvasRegion", () => {
  it("returns null without invocation activity (no permanent N×5 fan-out)", () => {
    expect(buildKnowledgeSideflowCanvasRegion(null)).toBeNull();
    expect(
      buildKnowledgeSideflowCanvasRegion({ problem_understanding: badge({ latest: null }) }),
    ).toBeNull();
  });

  it("draws four chain edges plus two boundary edges for active runs", () => {
    const region = buildKnowledgeSideflowCanvasRegion({
      problem_understanding: badge({
        latest: {
          invocationId: "inv-1",
          parentNodeId: "problem_understanding",
          status: "running",
          handoffState: null,
          currentKnowledgeNodeId: "source_finding",
          updatedAtMs: 1,
        },
      }),
    });
    expect(region).not.toBeNull();
    expect(region?.nodes).toHaveLength(5);
    expect(region?.nodes.map((node) => node.nodeId)).toEqual([
      "ksf_source_finding",
      "ksf_source_extraction",
      "ksf_evidence_relations",
      "ksf_knowledge_ingestion",
      "ksf_knowledge_handoff",
    ]);
    expect(region?.nodes[4].visualKind).toBe("human_gate");
    expect(region?.edges).toHaveLength(6);
    const labels = region?.edges.map((edge) => edge.label);
    expect(labels).toContain("知识请求");
    expect(labels).toContain("知识包交接");
  });
});

describe("composeKnowledgeSideflowGraph", () => {
  it("returns the base graph untouched for a null region", () => {
    const base = baseGraph();
    expect(composeKnowledgeSideflowGraph(base, null)).toBe(base);
  });

  it("appends the sideflow stage and drops boundary edges with missing endpoints", () => {
    const base = baseGraph();
    const region = buildKnowledgeSideflowCanvasRegion({
      problem_understanding: badge({
        latest: {
          invocationId: "inv-1",
          parentNodeId: "problem_understanding",
          status: "running",
          handoffState: null,
          currentKnowledgeNodeId: "source_finding",
          updatedAtMs: 1,
        },
      }),
    });
    expect(region).not.toBeNull();
    // Remove hypothesis_design so the handoff boundary edge loses its endpoint.
    const composed = composeKnowledgeSideflowGraph(
      { ...base, nodes: base.nodes.filter((node) => node.nodeId !== "hypothesis_design") },
      region,
    );
    expect(composed.stages.map((stage) => stage.stageId)).toEqual([
      "stage_a",
      "knowledge_sideflow",
    ]);
    expect(composed.nodes).toHaveLength(6); // 1 base + 5 ksf
    const composedIds = new Set(composed.edges.map((edge) => edge.edgeId));
    expect(composedIds.has("ksf_e_entry")).toBe(true);
    expect(composedIds.has("ksf_e_handoff")).toBe(false); // endpoint missing
    expect(composed.edges).toHaveLength(6); // 1 base + 4 chain + 1 boundary
  });
});
