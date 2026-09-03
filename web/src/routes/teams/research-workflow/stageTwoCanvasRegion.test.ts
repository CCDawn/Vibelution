import { describe, expect, it } from "vitest";

import type { WorkflowLayoutInput } from "../../../components/vui";
import {
  STAGE_TWO_BOUNDARY_EDGE_ID,
  STAGE_TWO_INACTIVE_NODE_IDS,
  STAGE_TWO_INACTIVE_STAGE_ID,
  STAGE_TWO_INACTIVE_STAGE_LABEL,
  buildStageTwoInactiveCanvasRegion,
  composeStageTwoInactiveGraph,
  definitionNeedsStageTwoInactiveRegion,
  isStageTwoInactiveCanvasNode,
} from "./stageTwoCanvasRegion";

const SEVEN_NODE_DEFINITION = {
  nodes: [
    "problem_understanding",
    "source_finding",
    "source_extraction",
    "evidence_relations",
    "knowledge_ingestion",
    "knowledge_handoff",
    "hypothesis_design",
  ].map((nodeId) => ({ nodeId })),
};

const SEVENTEEN_NODE_DEFINITION = {
  nodes: [
    ...SEVEN_NODE_DEFINITION.nodes,
    ...["protocol_design", "result_package"].map((nodeId) => ({ nodeId })),
  ],
};

function baseGraph(): WorkflowLayoutInput {
  return {
    stages: [{
      stageId: "s1",
      label: "假说生成",
      nodeIds: ["hypothesis_design"],
      index: 0,
      stageTone: "done",
    }],
    nodes: [{
      nodeId: "hypothesis_design",
      stageId: "s1",
      label: "假设设计",
      actorKind: "agent",
      visualKind: "agent_task",
      status: "succeeded",
    }],
    edges: [],
    run: null,
  };
}

describe("stageTwoCanvasRegion", () => {
  it("carries exactly the ten stage-two contract nodes in canonical order", () => {
    expect(STAGE_TWO_INACTIVE_NODE_IDS).toEqual([
      "protocol_design",
      "protocol_review",
      "protocol_freeze",
      "smoke_gate",
      "controlled_run",
      "result_evaluation",
      "iteration_decision",
      "version_governance",
      "candidate_promotion",
      "result_package",
    ]);
    expect(isStageTwoInactiveCanvasNode("protocol_design")).toBe(true);
    expect(isStageTwoInactiveCanvasNode("result_package")).toBe(true);
    expect(isStageTwoInactiveCanvasNode("hypothesis_design")).toBe(false);
    expect(isStageTwoInactiveCanvasNode("hf_generation")).toBe(false);
    expect(isStageTwoInactiveCanvasNode(null)).toBe(false);
  });

  it("composes only for definitions truncated before stage two", () => {
    expect(definitionNeedsStageTwoInactiveRegion(SEVEN_NODE_DEFINITION)).toBe(true);
    expect(definitionNeedsStageTwoInactiveRegion(SEVENTEEN_NODE_DEFINITION)).toBe(false);
    expect(definitionNeedsStageTwoInactiveRegion(null)).toBe(false);
    expect(definitionNeedsStageTwoInactiveRegion(undefined)).toBe(false);
  });

  it("builds a static grayed fragment: all pending, idle stage, no runtime facts", () => {
    const region = buildStageTwoInactiveCanvasRegion();
    expect(region.stage.stageId).toBe(STAGE_TWO_INACTIVE_STAGE_ID);
    expect(region.stage.label).toBe(STAGE_TWO_INACTIVE_STAGE_LABEL);
    expect(region.stage.stageTone).toBe("idle");
    expect(region.stage.nodeIds).toEqual([...STAGE_TWO_INACTIVE_NODE_IDS]);
    expect(region.nodes).toHaveLength(10);
    for (const node of region.nodes) {
      expect(node.status).toBe("pending");
      expect(node.stageId).toBe(STAGE_TWO_INACTIVE_STAGE_ID);
      expect(node.description).toContain("第二阶段未激活，需按题显式开启");
      expect(node.isRuntimeCurrent).toBeFalsy();
      expect(node.hasPendingHumanTask).toBeFalsy();
    }
    // Linear chain inside the group; the boundary edge is not part of the region.
    expect(region.edges).toHaveLength(9);
    expect(region.edges.some((edge) => edge.edgeId === STAGE_TWO_BOUNDARY_EDGE_ID)).toBe(false);
  });

  it("appends the group after the base graph with an explanatory boundary edge", () => {
    const base = baseGraph();
    const composed = composeStageTwoInactiveGraph(base, buildStageTwoInactiveCanvasRegion());
    expect(composed.stages).toHaveLength(2);
    expect(composed.stages[1].stageId).toBe(STAGE_TWO_INACTIVE_STAGE_ID);
    expect(composed.stages[1].index).toBe(1);
    expect(composed.nodes).toHaveLength(base.nodes.length + 10);
    const boundary = composed.edges.filter((edge) => edge.edgeId === STAGE_TWO_BOUNDARY_EDGE_ID);
    expect(boundary).toHaveLength(1);
    expect(boundary[0].fromNodeId).toBe("hypothesis_design");
    expect(boundary[0].toNodeId).toBe("protocol_design");
    expect(boundary[0].label).toBe("需按题显式开启");
    expect(boundary[0].pathState).toBe("idle");
  });

  it("returns the base graph untouched when the region is absent", () => {
    const base = baseGraph();
    expect(composeStageTwoInactiveGraph(base, null)).toBe(base);
  });
});
