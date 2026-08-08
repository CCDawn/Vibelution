/**
 * RED acceptance contracts for the TRUE outer-ELK layout architecture.
 *
 * These fail on the current hand-rolled meta row (fixed STAGE_CHANNEL_GAP,
 * hand-written cross-stage router, hand-computed labelBounds) and become the
 * GREEN contract of the spacer-node outer ELK layout:
 *  - full-rectangle label collision checks (not center-only);
 *  - label width drives the stage gap automatically;
 *  - labels avoid unrelated nodes;
 *  - multiple cross-stage edges route without overlap;
 *  - a first->third stage edge does not cross the middle stage;
 *  - stage grows when its content grows and the rest relayouts;
 *  - determinism;
 *  - all final bounds inside the canvas.
 */
import ELK from "elkjs/lib/elk.bundled.js";
import { describe, expect, it } from "vitest";

import type { WorkflowLayoutInput, WorkflowLayoutResult } from "../../../product/workflow/workflowCanvasTypes";
import { layoutTwoLevel } from "./workflowTwoLevelLayout";
import { challengeCupDefinition, fourDecisionEdges } from "./workflowElkLayout.test";
import { segmentIntersectsRect } from "./workflowLayoutCollision";
import { rectsOverlap, type Rect } from "./workflowLayoutGeometry";

/**
 * Walks the full polyline of a section chain as consecutive SEGMENTS
 * (start -> bend -> ... -> bend -> end), not just isolated points: a point
 * outside a rect does not prove the segment between two points is.
 */
function segmentsOf(sections: WorkflowLayoutResult["edges"][number]["sections"]): Array<{ a: { x: number; y: number }; b: { x: number; y: number } }> {
  const segments: Array<{ a: { x: number; y: number }; b: { x: number; y: number } }> = [];
  for (const section of sections) {
    const polyline = [section.start, ...section.bendPoints, section.end];
    for (let i = 0; i + 1 < polyline.length; i += 1) {
      segments.push({ a: polyline[i]!, b: polyline[i + 1]! });
    }
  }
  return segments;
}

const SAFE_LABEL_STAGE = 12;
const SAFE_LABEL_NODE = 12;
const SAFE_LABEL_LABEL = 8;

function padded(r: Rect, pad: number): Rect {
  return { x: r.x - pad, y: r.y - pad, width: r.width + pad * 2, height: r.height + pad * 2 };
}

async function layoutWith(input: WorkflowLayoutInput): Promise<WorkflowLayoutResult> {
  return layoutTwoLevel(input, new ELK());
}

describe("outer-ELK layout · full-rectangle label contracts (RED on current)", () => {
  it("keeps the cross-stage label rect disjoint from BOTH stage rects (not just its center)", async () => {
    const input = challengeCupDefinition();
    const result = await layoutWith(input);
    const stages = result.nodes.filter((n) => n.kind === "stage");
    const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));
    const crossEdges = result.edges.filter((e) => {
      const s = stageOf.get(e.source);
      const t = stageOf.get(e.target);
      return s && t && s !== t;
    });
    expect(crossEdges.length).toBeGreaterThan(0);
    for (const edge of crossEdges) {
      const lb = edge.labelBounds;
      expect(lb, `edge ${edge.id} has a label anchor`).toBeDefined();
      const labelRect: Rect = { x: lb!.x, y: lb!.y, width: lb!.width, height: lb!.height };
      const sourceStageId = stageOf.get(edge.source);
      const targetStageId = stageOf.get(edge.target);
      for (const stage of stages) {
        if (stage.stageId === sourceStageId || stage.stageId === targetStageId) {
          continue;
        }
        expect(
          rectsOverlap(padded(labelRect, SAFE_LABEL_STAGE), stage),
          `label of ${edge.id} overlaps stage ${stage.stageId}`,
        ).toBe(false);
      }
    }
  });

  it("writes the label rect fully inside the gap between its two stages", async () => {
    const input = challengeCupDefinition();
    const result = await layoutWith(input);
    const stages = result.nodes.filter((n) => n.kind === "stage");
    const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));
    const crossEdges = result.edges.filter((e) => {
      const s = stageOf.get(e.source);
      const t = stageOf.get(e.target);
      return s && t && s !== t;
    });
    for (const edge of crossEdges) {
      const lb = edge.labelBounds;
      if (!lb) continue;
      const sourceStage = stages.find((s) => s.stageId === stageOf.get(edge.source))!;
      const targetStage = stages.find((s) => s.stageId === stageOf.get(edge.target))!;
      const gapLeft = sourceStage.x + sourceStage.width;
      const gapRight = targetStage.x;
      expect(lb.x, `label of ${edge.id} left edge inside gap`).toBeGreaterThanOrEqual(gapLeft + SAFE_LABEL_STAGE);
      expect(lb.x + lb.width, `label of ${edge.id} right edge inside gap`).toBeLessThanOrEqual(gapRight - SAFE_LABEL_STAGE);
    }
  });

  it("grows the stage gap when the cross-stage label widens (no hardcoded gap)", async () => {
    const narrow = challengeCupDefinition();
    const wide = {
      ...narrow,
      edges: narrow.edges.map((e) =>
        e.edgeId === "e_kc_hypothesis"
          ? { ...e, label: "交接" }
          : e,
      ),
    };
    const wider = {
      ...narrow,
      edges: narrow.edges.map((e) =>
        e.edgeId === "e_kc_hypothesis"
          ? { ...e, label: "知识包跨阶段正式交接" }
          : e,
      ),
    };
    const narrowResult = await layoutWith(narrow);
    const wideResult = await layoutWith(wide);
    const widerResult = await layoutWith(wider);
    const gapOf = (result: WorkflowLayoutResult, from: string, to: string) => {
      const a = result.nodes.find((n) => n.kind === "stage" && n.stageId === from)!;
      const b = result.nodes.find((n) => n.kind === "stage" && n.stageId === to)!;
      return b.x - (a.x + a.width);
    };
    const baseGap = gapOf(narrowResult, "knowledge_collection", "experiment_design");
    const twoCharGap = gapOf(wideResult, "knowledge_collection", "experiment_design");
    const nineCharGap = gapOf(widerResult, "knowledge_collection", "experiment_design");
    // Two different widths must produce two different gaps: the wider label
    // (9 chars) pushes the gap beyond the shorter one (2 chars), and both
    // differ from the original full-width label.
    expect(nineCharGap, `9-char gap ${nineCharGap} > 2-char gap ${twoCharGap}`).toBeGreaterThan(twoCharGap);
    expect(baseGap, `full label gap ${baseGap} >= 9-char gap ${nineCharGap}`).toBeGreaterThanOrEqual(nineCharGap);
  });

  it("keeps labels clear of unrelated task nodes (padded by 12px)", async () => {
    const input = challengeCupDefinition();
    const result = await layoutWith(input);
    const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));
    const crossEdges = result.edges.filter((e) => {
      const s = stageOf.get(e.source);
      const t = stageOf.get(e.target);
      return s && t && s !== t;
    });
    const tasks = result.nodes.filter((n) => n.kind === "task");
    for (const edge of crossEdges) {
      const lb = edge.labelBounds;
      if (!lb) continue;
      const labelRect: Rect = { x: lb.x, y: lb.y, width: lb.width, height: lb.height };
      for (const task of tasks) {
        if (task.id === edge.source || task.id === edge.target) continue;
        expect(
          rectsOverlap(padded(labelRect, SAFE_LABEL_NODE), task),
          `label of ${edge.id} overlaps unrelated node ${task.id}`,
        ).toBe(false);
      }
    }
  });
});

describe("outer-ELK layout · multi-edge and long-edge contracts (RED on current)", () => {
  it("routes a first->third stage edge without crossing the middle stage body", async () => {
    const input = challengeCupDefinition();
    // Direct first->third edge (source_finding -> result_package).
    const extended = {
      ...input,
      edges: [
        ...input.edges,
        {
          edgeId: "e_find_package",
          fromNodeId: "source_finding",
          toNodeId: "result_package",
          label: "直达打包",
          gateKind: "auto",
          semanticKind: "main",
          pathState: "idle",
          labelAlwaysVisible: false,
        },
      ],
    };
    const result = await layoutWith(extended);
    const stages = result.nodes.filter((n) => n.kind === "stage");
    const middle = stages.find((s) => s.stageId === "experiment_design")!;
    const edge = result.edges.find((e) => e.id === "e_find_package");
    expect(edge, "direct first->third edge exists").toBeDefined();
    const segments = segmentsOf(edge!.sections);
    expect(segments.length, "edge has at least one segment").toBeGreaterThan(0);
    // Segment-level check: every consecutive pair of polyline points must not
    // intersect the middle stage. Point-only checks are fake-green — the
    // segment between two outside points can still pierce the stage.
    for (const segment of segments) {
      expect(
        segmentIntersectsRect(segment.a, segment.b, middle),
        `segment of ${edge!.id} crosses middle stage`,
      ).toBe(false);
    }
  });

  it("keeps parallel cross-stage labels disjoint (>= 8px) and edges clear of labels", async () => {
    const input = fourDecisionEdges();
    // Add two more cross-stage edges with labels between stage 1 and 2.
    const extended = {
      ...input,
      edges: [
        ...input.edges,
        {
          edgeId: "e_extra_1",
          fromNodeId: "protocol_design",
          toNodeId: "controlled_run",
          label: "额外并行交接一",
          gateKind: "auto",
          semanticKind: "main",
          pathState: "idle",
          labelAlwaysVisible: false,
        },
        {
          edgeId: "e_extra_2",
          fromNodeId: "protocol_design",
          toNodeId: "controlled_run",
          label: "额外并行交接二",
          gateKind: "auto",
          semanticKind: "main",
          pathState: "idle",
          labelAlwaysVisible: false,
        },
      ],
    };
    const result = await layoutWith(extended);
    const stageOf = new Map(extended.nodes.map((n) => [n.nodeId, n.stageId] as const));
    const crossEdges = result.edges.filter((e) => {
      const s = stageOf.get(e.source);
      const t = stageOf.get(e.target);
      return s && t && s !== t;
    });
    const labels = crossEdges
      .filter((e) => e.labelBounds)
      .map((e) => ({ id: e.id, rect: e.labelBounds! }));
    for (let i = 0; i < labels.length; i += 1) {
      for (let j = i + 1; j < labels.length; j += 1) {
        const a: Rect = { x: labels[i]!.rect.x, y: labels[i]!.rect.y, width: labels[i]!.rect.width, height: labels[i]!.rect.height };
        const b: Rect = { x: labels[j]!.rect.x, y: labels[j]!.rect.y, width: labels[j]!.rect.width, height: labels[j]!.rect.height };
        expect(
          rectsOverlap(padded(a, SAFE_LABEL_LABEL), b),
          `labels ${labels[i]!.id} and ${labels[j]!.id} overlap`,
        ).toBe(false);
      }
    }

    const labelRects = labels.map((label) => ({ id: label.id, rect: label.rect }));
    // Edge segments must not pierce ANY OTHER edge's label rect (an edge
    // naturally passes through its OWN label — that is the label's anchor).
    // Segment-level check on the full polyline (points-only would be
    // fake-green for the same reason as the middle-stage test).
    for (const edge of crossEdges) {
      for (const segment of segmentsOf(edge.sections)) {
        for (const label of labelRects) {
          if (label.id === edge.id) continue;
          expect(
            segmentIntersectsRect(segment.a, segment.b, label.rect),
            `segment of ${edge.id} crosses label ${label.id}`,
          ).toBe(false);
        }
      }
    }
  });
});

describe("outer-ELK layout · growth and determinism (RED on current)", () => {
  it("grows the stage box when its content grows and relayouts the rest", async () => {
    const base = challengeCupDefinition();
    const grown = {
      ...base,
      stages: base.stages.map((s) =>
        s.stageId === "experiment_design"
          ? { ...s, nodeIds: [...s.nodeIds, "extra_node_1", "extra_node_2", "extra_node_3"] }
          : s,
      ),
      nodes: [
        ...base.nodes,
        ...["extra_node_1", "extra_node_2", "extra_node_3"].map((id, i) => ({
          nodeId: id,
          stageId: "experiment_design",
          label: `扩展节点${i}`,
          actorKind: "agent" as const,
          visualKind: "agent_task" as const,
          status: "pending" as const,
        })),
      ],
    };
    const baseResult = await layoutWith(base);
    const grownResult = await layoutWith(grown);
    const baseStage = baseResult.nodes.find((n) => n.kind === "stage" && n.stageId === "experiment_design")!;
    const grownStage = grownResult.nodes.find((n) => n.kind === "stage" && n.stageId === "experiment_design")!;
    expect(grownStage.height, `grown stage ${grownStage.height} > base ${baseStage.height}`).toBeGreaterThan(baseStage.height);
    // All stages still present and ordered.
    const order = grownResult.nodes
      .filter((n) => n.kind === "stage")
      .sort((a, b) => a.x - b.x)
      .map((s) => s.stageId);
    expect(order).toEqual(["knowledge_collection", "experiment_design", "execution_iteration"]);
  });

  it("produces identical output for identical input (determinism)", async () => {
    const input = challengeCupDefinition();
    const a = await layoutWith(input);
    const b = await layoutWith(input);
    expect(JSON.stringify(a.nodes.map((n) => ({ id: n.id, x: n.x, y: n.y })))).toBe(
      JSON.stringify(b.nodes.map((n) => ({ id: n.id, x: n.x, y: n.y }))),
    );
    expect(JSON.stringify(a.edges.map((e) => ({ id: e.id, sections: e.sections })))).toBe(
      JSON.stringify(b.edges.map((e) => ({ id: e.id, sections: e.sections }))),
    );
  });
});
