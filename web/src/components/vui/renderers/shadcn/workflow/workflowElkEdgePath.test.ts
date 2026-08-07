/**
 * T3 geometry invariants for engine-owned edge paths.
 *
 * Covers the §9.3 invariants that `workflowElkEdgePath` must hold:
 *  - paths are built only from section start/bend/end vertices;
 *  - disconnected sections are joined with a move, never a fake connector;
 *  - promote/rollback parallel edges stay distinguishable through their paths;
 *  - label anchors come from engine bounds or a geometry-derived fallback.
 */
import ELK from "elkjs/lib/elk.bundled.js";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import type {
  WorkflowEdgeSection,
  WorkflowLayoutInput,
} from "../../../product/workflow/workflowCanvasTypes";
import { toElkGraph } from "./workflowElkGraphAdapter";
import { fromElkLayout } from "./workflowElkLayout";
import {
  resolveEdgeLabelAnchor,
  sectionsToSvgPath,
  type WorkflowEdgeLabelAnchor,
} from "./workflowElkEdgePath";

type Point = { x: number; y: number };

function parsePathVertices(path: string): Point[] {
  const tokens = path.trim().split(/\s+/);
  const vertices: Point[] = [];
  for (let i = 0; i < tokens.length; i += 1) {
    if (tokens[i] === "M" || tokens[i] === "L") {
      const x = Number(tokens[i + 1]);
      const y = Number(tokens[i + 2]);
      if (Number.isFinite(x) && Number.isFinite(y)) {
        vertices.push({ x, y });
      }
    }
  }
  return vertices;
}

function hasVertex(vertices: Point[], point: Point): boolean {
  return vertices.some(
    (v) => Math.abs(v.x - point.x) < 1e-6 && Math.abs(v.y - point.y) < 1e-6,
  );
}

function fourDecisionEdges(): WorkflowLayoutInput {
  return {
    stages: [
      { stageId: "knowledge_collection", label: "知识搜集", nodeIds: ["protocol_design"] },
      { stageId: "execution_iteration", label: "执行迭代", nodeIds: ["controlled_run", "iteration_decision"] },
    ],
    nodes: [
      { nodeId: "protocol_design", stageId: "knowledge_collection", label: "协议设计", actorKind: "system", visualKind: "system_task", status: "pending" },
      { nodeId: "controlled_run", stageId: "execution_iteration", label: "受控执行", actorKind: "agent", visualKind: "agent_task", status: "pending" },
      { nodeId: "iteration_decision", stageId: "execution_iteration", label: "迭代决策", actorKind: "agent", visualKind: "decision", status: "pending" },
    ],
    edges: [
      { edgeId: "e_handoff", fromNodeId: "protocol_design", toNodeId: "controlled_run", label: "进入执行", gateKind: "human", semanticKind: "main", pathState: "idle", labelAlwaysVisible: false },
      { edgeId: "e_rerun", fromNodeId: "iteration_decision", toNodeId: "controlled_run", label: "同协议重跑", gateKind: "auto", semanticKind: "rerun", pathState: "idle", labelAlwaysVisible: true, sourceHandle: "rerun" },
      { edgeId: "e_promote", fromNodeId: "iteration_decision", toNodeId: "controlled_run", label: "晋升", gateKind: "auto", semanticKind: "promote", pathState: "idle", labelAlwaysVisible: false, sourceHandle: "promote" },
      { edgeId: "e_rollback", fromNodeId: "iteration_decision", toNodeId: "controlled_run", label: "回退", gateKind: "auto", semanticKind: "rollback", pathState: "idle", labelAlwaysVisible: false, sourceHandle: "rollback" },
    ],
  } as WorkflowLayoutInput;
}

async function layoutedSections(
  input: WorkflowLayoutInput,
): Promise<Record<string, WorkflowEdgeSection[]>> {
  const elk = new ELK();
  const { root } = toElkGraph(input);
  const layouted = (await elk.layout(root)) as never;
  const result = fromElkLayout(layouted, input);
  const map: Record<string, WorkflowEdgeSection[]> = {};
  for (const edge of result.edges) {
    map[edge.id] = edge.sections;
  }
  return map;
}

describe("workflowElkEdgePath (T3)", () => {
  it("builds a path only from section start/bend/end vertices", () => {
    const sections: WorkflowEdgeSection[] = [
      { id: "s1", start: { x: 0, y: 0 }, end: { x: 0, y: 40 }, bendPoints: [], incomingSectionIds: [], outgoingSectionIds: [] },
      { id: "s2", start: { x: 0, y: 40 }, end: { x: 120, y: 40 }, bendPoints: [{ x: 60, y: 40 }], incomingSectionIds: ["s1"], outgoingSectionIds: [] },
    ];
    const path = sectionsToSvgPath(sections);
    const vertices = parsePathVertices(path);
    expect(hasVertex(vertices, { x: 0, y: 0 })).toBe(true);
    expect(hasVertex(vertices, { x: 0, y: 40 })).toBe(true);
    expect(hasVertex(vertices, { x: 60, y: 40 })).toBe(true);
    expect(hasVertex(vertices, { x: 120, y: 40 })).toBe(true);
    expect(vertices.length).toBe(5);
  });

  it("joins disconnected sections with a move, never a fake connector line", () => {
    const sections: WorkflowEdgeSection[] = [
      { id: "s1", start: { x: 0, y: 0 }, end: { x: 0, y: 30 }, bendPoints: [], incomingSectionIds: [], outgoingSectionIds: [] },
      { id: "s2", start: { x: 50, y: 30 }, end: { x: 50, y: 60 }, bendPoints: [], incomingSectionIds: [], outgoingSectionIds: [] },
    ];
    const path = sectionsToSvgPath(sections);
    expect(path.match(/M /g)?.length).toBe(2);
  });

  it("uses engine labelBounds center as the anchor when present", () => {
    const sections: WorkflowEdgeSection[] = [
      { id: "s1", start: { x: 10, y: 10 }, end: { x: 100, y: 10 }, bendPoints: [], incomingSectionIds: [], outgoingSectionIds: [] },
    ];
    const anchor = resolveEdgeLabelAnchor(sections, { x: 40, y: 6, width: 40, height: 12 });
    expect(anchor).toEqual({ x: 60, y: 12 });
  });

  it("falls back to a geometry-derived midpoint anchor without engine bounds", () => {
    const sections: WorkflowEdgeSection[] = [
      { id: "s1", start: { x: 10, y: 10 }, end: { x: 100, y: 10 }, bendPoints: [], incomingSectionIds: [], outgoingSectionIds: [] },
    ];
    const anchor = resolveEdgeLabelAnchor(sections, undefined);
    expect(anchor).toEqual({ x: 55, y: 10 });
  });

  it("returns null anchor when there is no geometry at all", () => {
    expect(resolveEdgeLabelAnchor([], undefined)).toBeNull();
  });

  it("emits valid absolute paths for the real ELK graph", async () => {
    const byEdge = await layoutedSections(fourDecisionEdges());
    for (const [edgeId, sections] of Object.entries(byEdge)) {
      expect(sections.length).toBeGreaterThan(0);
      const path = sectionsToSvgPath(sections);
      const vertices = parsePathVertices(path);
      expect(vertices.length).toBeGreaterThan(1);
      for (const section of sections) {
        expect(hasVertex(vertices, section.start)).toBe(true);
        expect(hasVertex(vertices, section.end)).toBe(true);
      }
    }
  });

  it("keeps promote/rollback paths distinguishable through distinct sections", async () => {
    const byEdge = await layoutedSections(fourDecisionEdges());
    const promote = byEdge["e_promote"] ?? [];
    const rollback = byEdge["e_rollback"] ?? [];
    expect(promote.length).toBeGreaterThan(0);
    expect(rollback.length).toBeGreaterThan(0);
    expect(sectionsToSvgPath(promote)).not.toBe(sectionsToSvgPath(rollback));
  });

  it("keeps production edge renderer free of getSmoothStepPath", () => {
    // §4/§9.3: the edge must render engine sections, never re-route a
    // smooth-step approximation. The guard lives on the production source so a
    // naive revert cannot sneak the old renderer back in.
    const source = readFileSync(
      resolve(__dirname, "WorkflowSemanticEdge.tsx"),
      "utf8",
    );
    expect(source).not.toContain("getSmoothStepPath");
  });
});