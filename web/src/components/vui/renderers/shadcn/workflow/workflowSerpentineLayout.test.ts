import ELK from "elkjs/lib/elk.bundled.js";
import { describe, expect, it } from "vitest";

import { resolveElkPorts } from "./workflowElkPorts";
import { challengeCupDefinition } from "./workflowElkLayout.test";
import { layoutTwoLevel } from "./workflowTwoLevelLayout";

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
