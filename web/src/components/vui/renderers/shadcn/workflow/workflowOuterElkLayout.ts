/**
 * Outer ELK layout execution (spacer-node architecture).
 *
 * Runs the outer meta graph through ELK and parses:
 *  - stage meta positions (ELK owns the gap — no fixed STAGE_CHANNEL_GAP);
 *  - spacer (label) positions — the label anchor owner;
 *  - the two layout legs per cross-stage edge, recombined into one continuous
 *    chain of sections per domain edge.
 */
import type { ElkNode } from "elkjs/lib/elk-api";

import type { WorkflowEdgeSection, WorkflowLayoutPoint } from "../../../product/workflow/workflowCanvasTypes";
import type { OuterElkGraph } from "./workflowOuterElkGraphAdapter";

export type OuterLayoutResult = {
  /** stageId -> absolute meta position. */
  stagePositions: Map<string, { x: number; y: number }>;
  /** edgeId -> label rect (spacer position + label spec size). */
  labelPositions: Map<string, { x: number; y: number; width: number; height: number }>;
  /** edgeId -> recombined orthogonal sections (leg1 + leg2, continuous). */
  edgeSections: Map<string, WorkflowEdgeSection[]>;
  size: { width: number; height: number };
};

export async function layoutOuter(
  outer: OuterElkGraph,
  engine: { layout: (graph: ElkNode) => Promise<ElkNode> },
): Promise<OuterLayoutResult> {
  const laidOut = await engine.layout(outer.root);
  return consumeOuterLayout(outer, laidOut);
}

export function consumeOuterLayout(
  outer: OuterElkGraph,
  laidOut: ElkNode,
): OuterLayoutResult {
  const stagePositions = new Map<string, { x: number; y: number }>();
  const spacerById = new Map<string, { x: number; y: number; width: number; height: number }>();
  const edgeSectionsById = new Map<string, WorkflowEdgeSection[]>();
  let maxRight = 0;
  let maxBottom = 0;

  const stageIdOfElk = new Map<string, string>();
  for (const [stageId, elkId] of outer.stageElkIds) {
    stageIdOfElk.set(elkId, stageId);
  }

  for (const child of laidOut.children ?? []) {
    const x = child.x ?? 0;
    const y = child.y ?? 0;
    const width = child.width ?? 0;
    const height = child.height ?? 0;
    maxRight = Math.max(maxRight, x + width);
    maxBottom = Math.max(maxBottom, y + height);
    const stageId = stageIdOfElk.get(child.id);
    if (stageId != null) {
      stagePositions.set(stageId, { x, y });
      continue;
    }
    for (const [edgeId, spacerId] of outer.spacerOfEdge) {
      if (child.id === spacerId) {
        spacerById.set(spacerId, { x, y, width, height });
        void edgeId;
      }
    }
  }

  // Recombine the two legs of each domain edge into one continuous chain.
  const sectionByLeg = new Map<string, WorkflowEdgeSection[]>();
  for (const edge of laidOut.edges ?? []) {
    // Map old section ids -> new ids so incoming/outgoing references stay
    // valid after the rename.
    const idMap = new Map<string, string>();
    const sections = (edge.sections ?? []).map((s, i) => {
      const newId = `${edge.id}_s${i}`;
      idMap.set(s.id, newId);
      return {
        id: newId,
        start: point(s.startPoint),
        end: point(s.endPoint),
        bendPoints: (s.bendPoints ?? []).map(point),
        incomingSectionIds: [],
        outgoingSectionIds: [],
      } as WorkflowEdgeSection;
    });
    // Second pass: rewrite the references with the new ids.
    (edge.sections ?? []).forEach((s, i) => {
      sections[i]!.incomingSectionIds = (s.incomingSections ?? []).map((id) => idMap.get(id) ?? id);
      sections[i]!.outgoingSectionIds = (s.outgoingSections ?? []).map((id) => idMap.get(id) ?? id);
    });
    sectionByLeg.set(edge.id, sections);
  }

  const labelPositions = new Map<string, { x: number; y: number; width: number; height: number }>();
  for (const [edgeId, { leg1, leg2 }] of outer.legs) {
    const spacerId = outer.spacerOfEdge.get(edgeId);
    const spacer = spacerId ? spacerById.get(spacerId) : undefined;
    const legs1 = sectionByLeg.get(leg1) ?? [];
    const legs2 = sectionByLeg.get(leg2) ?? [];
    let combined = [...legs1, ...legs2];
    // The two ELK legs terminate at opposite sides of the virtual spacer.
    // They cannot be linked directly: the spacer width is a real gap in the
    // returned geometry. Add an explicit bridge over that occupied label
    // channel so the public edge remains one continuous, diagnosable chain.
    const lastOfFirst = legs1[legs1.length - 1];
    const firstOfSecond = legs2[0];
    if (lastOfFirst && firstOfSecond) {
      const bridge: WorkflowEdgeSection = {
        id: `${edgeId}__spacer_bridge`,
        start: { ...lastOfFirst.end },
        end: { ...firstOfSecond.start },
        bendPoints:
          Math.abs(lastOfFirst.end.x - firstOfSecond.start.x) <= 1e-3 ||
          Math.abs(lastOfFirst.end.y - firstOfSecond.start.y) <= 1e-3
            ? []
            : [{ x: firstOfSecond.start.x, y: lastOfFirst.end.y }],
        incomingSectionIds: [lastOfFirst.id],
        outgoingSectionIds: [firstOfSecond.id],
      };
      lastOfFirst.outgoingSectionIds = [bridge.id];
      firstOfSecond.incomingSectionIds = [bridge.id];
      combined = [...legs1, bridge, ...legs2];
    }
    edgeSectionsById.set(edgeId, combined);
    if (spacer) {
      labelPositions.set(edgeId, spacer);
    }
  }

  return { stagePositions, labelPositions, edgeSections: edgeSectionsById, size: { width: maxRight, height: maxBottom } };
}

function point(p: { x: number; y: number }): WorkflowLayoutPoint {
  return { x: p.x, y: p.y };
}
