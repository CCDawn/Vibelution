import { describe, expect, it } from "vitest";

import type { KnowledgeInvocationBadge } from "../../../api/types/research-workflow/core";
import type { WorkflowLayoutInput } from "../../../components/vui";
import {
  buildKnowledgeSideflowCanvasRegion,
  composeKnowledgeSideflowGraph,
  isKnowledgeSideflowCanvasNode,
  KNOWLEDGE_SIDEFLOW_NODE_PREFIX,
  KNOWLEDGE_SIDEFLOW_RELATION_EDGE_ID,
  knowledgeSideflowCanvasNodeId,
  knowledgeSideflowRelationEdge,
  knowledgeSideflowSemanticNodeId,
  sideflowNodeStatesFromBadges,
} from "./knowledgeSideflowCanvasRegion";

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

describe("sideflowNodeStatesFromBadges", () => {
  it("marks unstarted descendants as waiting for recovery when the search is blocked", () => {
    const states = sideflowNodeStatesFromBadges({ hypothesis_design: badge({ latest: {
      invocationId: "inv-blocked", parentNodeId: "hypothesis_design", status: "child_created",
      handoffState: "pending", currentKnowledgeNodeId: "source_finding", updatedAtMs: 1,
      childNodeStates: { source_finding: "blocked", source_extraction: "pending" },
    } }) });
    expect(states.slice(1).map((node) => node.description)).toEqual(Array(4).fill("等待前置步骤恢复"));
    expect(states.slice(1).every((node) => node.status === "pending")).toBe(true);
  });

  it("preserves cancelled and waiting node facts without inferring completed predecessors", () => {
    const states = sideflowNodeStatesFromBadges({problem_understanding: badge({latest: {
      invocationId: "cancelled-1", parentNodeId: "problem_understanding", status: "cancelled", handoffState: null,
      currentKnowledgeNodeId: "source_extraction", childNodeStates: {source_extraction: "cancelled", evidence_relations: "pending", knowledge_handoff: "waiting_human"},
    }})});
    expect(states.map((node) => node.status)).toEqual(["pending", "cancelled", "pending", "pending", "waiting_human"]);
    expect(states[1].description).toContain("已取消");
    expect(states[2].description).toContain("未执行");
    expect(states[4].description).toContain("人工确认");
    expect(states.every((node) => !node.description.includes("进行中"))).toBe(true);
  });

  it("describes failed child nodes truthfully while the invocation can recover", () => {
    const states = sideflowNodeStatesFromBadges({ hypothesis_design: badge({ latest: {
      invocationId: "inv-failed", parentNodeId: "hypothesis_design", status: "child_created",
      handoffState: "pending", currentKnowledgeNodeId: "source_finding", updatedAtMs: 1,
      childNodeStates: { source_finding: "failed" },
    } }) });
    expect(states[0].status).toBe("failed");
    expect(states[0].description).toContain("失败");
    expect(states[0].description).not.toContain("进行中");
  });

  it("derives five cards from the most recent invocation only", () => {
    const states = sideflowNodeStatesFromBadges({
      problem_understanding: badge({
        latest: {
          invocationId: "inv-1",
          parentNodeId: "problem_understanding",
          status: "running",
          handoffState: null,
          currentKnowledgeNodeId: "evidence_relations",
          childNodeStates: {source_finding: "succeeded", source_extraction: "succeeded"},
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

  it("uses the child run's REAL per-node states when present", () => {
    const states = sideflowNodeStatesFromBadges({
      problem_understanding: badge({
        latest: {
          invocationId: "inv-3",
          parentNodeId: "problem_understanding",
          status: "running",
          handoffState: null,
          // Legacy summaries only knew the chain head; the child run's node
          // attempts prove work has reached the third node.
          currentKnowledgeNodeId: "source_finding",
          childNodeStates: {
            source_finding: "succeeded",
            source_extraction: "succeeded",
            evidence_relations: "running",
            knowledge_ingestion: "failed",
          },
          updatedAtMs: 40,
        },
      }),
    });
    expect(states.map((state) => state.status)).toEqual([
      "succeeded",
      "succeeded",
      "running",
      "failed",
      "pending",
    ]);
  });

  it("shows waiting_human at the gate only while the handoff is awaiting", () => {
    const states = sideflowNodeStatesFromBadges({
      problem_understanding: badge({
        awaitingHandoffCount: 1,
        latest: {
          invocationId: "inv-4",
          parentNodeId: "problem_understanding",
          status: "awaiting_handoff",
          handoffState: "awaiting_human",
          currentKnowledgeNodeId: "knowledge_handoff",
          childNodeStates: {
            source_finding: "succeeded",
            source_extraction: "succeeded",
            evidence_relations: "succeeded",
            knowledge_ingestion: "succeeded",
            knowledge_handoff: "succeeded",
          },
          updatedAtMs: 50,
        },
      }),
    });
    expect(states[4].status).toBe("waiting_human");
  });
});

describe("buildKnowledgeSideflowCanvasRegion", () => {
  it("returns null without invocation activity (no permanent N×5 fan-out)", () => {
    expect(buildKnowledgeSideflowCanvasRegion(null)).toBeNull();
    expect(
      buildKnowledgeSideflowCanvasRegion({ problem_understanding: badge({ latest: null }) }),
    ).toBeNull();
  });

  it("draws only the four intra-chain edges — no permanent boundary edges", () => {
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
    // Exactly the 4 chain edges; the main↔sideflow relation is the
    // selection-driven temporary line, never a permanent edge.
    expect(region?.edges).toHaveLength(4);
    expect(region?.edges.map((edge) => edge.edgeId)).toEqual([
      "ksf_e_source_finding_source_extraction",
      "ksf_e_source_extraction_evidence_relations",
      "ksf_e_evidence_relations_knowledge_ingestion",
      "ksf_e_knowledge_ingestion_knowledge_handoff",
    ]);
  });
});

describe("knowledgeSideflowRelationEdge", () => {
  const badges = {
    problem_understanding: badge({
      latest: {
        invocationId: "inv-1",
        parentNodeId: "problem_understanding",
        status: "completed",
        handoffState: "accepted",
        currentKnowledgeNodeId: "knowledge_handoff",
        updatedAtMs: 1,
      },
    }),
  };

  it("is absent without a ksf_ selection or an invocation", () => {
    expect(knowledgeSideflowRelationEdge(badges, "problem_understanding")).toBeNull();
    expect(knowledgeSideflowRelationEdge(null, "ksf_source_finding")).toBeNull();
    expect(
      knowledgeSideflowRelationEdge(
        { problem_understanding: badge({ latest: null }) },
        "ksf_source_finding",
      ),
    ).toBeNull();
  });

  it("draws the request line from the invocation's parentNodeId", () => {
    const edge = knowledgeSideflowRelationEdge(badges, "ksf_source_finding");
    expect(edge).not.toBeNull();
    expect(edge?.edgeId).toBe(KNOWLEDGE_SIDEFLOW_RELATION_EDGE_ID);
    expect(edge?.fromNodeId).toBe("problem_understanding");
    expect(edge?.toNodeId).toBe("ksf_source_finding");
    expect(edge?.label).toBe("知识请求");
  });

  it("draws the write-back line into the invocation's parentNodeId at the gate", () => {
    const edge = knowledgeSideflowRelationEdge(badges, "ksf_knowledge_handoff");
    expect(edge).not.toBeNull();
    expect(edge?.fromNodeId).toBe("ksf_knowledge_handoff");
    // Write-back target is the invocation's own parentNodeId — never a
    // fixed downstream node.
    expect(edge?.toNodeId).toBe("problem_understanding");
    expect(edge?.label).toBe("写回节点");
  });

  it("composer drops the line when the parent node is missing from the graph", () => {
    const base = baseGraph();
    const region = buildKnowledgeSideflowCanvasRegion({
      result_evaluation: badge({
        nodeId: "result_evaluation",
        latest: {
          invocationId: "inv-2",
          parentNodeId: "result_evaluation",
          status: "running",
          handoffState: null,
          currentKnowledgeNodeId: "source_finding",
          updatedAtMs: 2,
        },
      }),
    });
    const composed = composeKnowledgeSideflowGraph(
      base,
      region,
      knowledgeSideflowRelationEdge(
        {
          result_evaluation: badge({
            nodeId: "result_evaluation",
            latest: {
              invocationId: "inv-2",
              parentNodeId: "result_evaluation",
              status: "running",
              handoffState: null,
              currentKnowledgeNodeId: "source_finding",
              updatedAtMs: 2,
            },
          }),
        },
        "ksf_source_finding",
      ),
    );
    const composedIds = new Set(composed.edges.map((edge) => edge.edgeId));
    expect(composedIds.has(KNOWLEDGE_SIDEFLOW_RELATION_EDGE_ID)).toBe(false);
  });
});

describe("composeKnowledgeSideflowGraph", () => {
  it("returns the base graph untouched for a null region", () => {
    const base = baseGraph();
    expect(composeKnowledgeSideflowGraph(base, null)).toBe(base);
  });

  it("appends the sideflow stage and drops relation edges with missing endpoints", () => {
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
    // Remove hypothesis_design; the relation edge targets only existing nodes.
    const composed = composeKnowledgeSideflowGraph(
      { ...base, nodes: base.nodes.filter((node) => node.nodeId !== "hypothesis_design") },
      region,
      knowledgeSideflowRelationEdge(
        {
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
        },
        "ksf_source_finding",
      ),
    );
    expect(composed.stages.map((stage) => stage.stageId)).toEqual([
      "stage_a",
      "knowledge_sideflow",
    ]);
    expect(composed.nodes).toHaveLength(6); // 1 base + 5 ksf
    const composedIds = new Set(composed.edges.map((edge) => edge.edgeId));
    expect(composedIds.has(KNOWLEDGE_SIDEFLOW_RELATION_EDGE_ID)).toBe(true);
    expect(composed.edges).toHaveLength(6); // 1 base + 4 chain + 1 relation
  });
});
