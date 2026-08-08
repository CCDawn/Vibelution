/**
 * Structural hash for the workflow canvas auto-layout.
 *
 * Two keys:
 * - `structure`: topology only (stages + order, node membership + kind,
 *   edges + sourceHandle) plus the resolved label geometry of every edge.
 *   Used to decide whether a relayout is mandatory.
 * - `full`: structure + measured node sizes. Used as the layout cache key.
 *
 * Runtime-only fields never enter the hash: status / pathState / stageTone /
 * attempt / isRuntimeCurrent / primaryAgentId / blockedReason / edge label
 * TEXT. Label text only enters through its RESOLVED GEOMETRY
 * (resolveEdgeLabelSpec width/height): the outer spacer node is sized by that
 * geometry, so a text change that widens/narrows the label MUST relayout
 * (stage channel grows/shrinks), while a same-geometry text change stays a
 * runtime-only merge.
 */
import type { WorkflowLayoutInput } from "../../../product/workflow/workflowCanvasTypes";
import { resolveEdgeLabelSpec } from "./workflowEdgeLabelGeometry";
import {
  WORKFLOW_DECISION_DESIGN_HEIGHT,
  WORKFLOW_NODE_DESIGN_HEIGHT,
  WORKFLOW_NODE_DESIGN_WIDTH,
} from "./workflowElkOptions";

export type WorkflowNodeSize = { width: number; height: number };

export type WorkflowLayoutHash = {
  structure: string;
  full: string;
};

function stableStringify(value: unknown): string {
  if (value === null || value === undefined || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(",")}}`;
}

/** Node order is defined by the stages' `nodeIds`; unknown ids sort after. */
function nodeRank(stages: WorkflowLayoutInput["stages"]): Map<string, number> {
  const rank = new Map<string, number>();
  stages.forEach((stage, stageIndex) => {
    stage.nodeIds.forEach((nodeId, index) => {
      if (!rank.has(nodeId)) {
        rank.set(nodeId, stageIndex * 10_000 + index);
      }
    });
  });
  return rank;
}

function designHeight(visualKind: string): number {
  return visualKind === "decision" ? WORKFLOW_DECISION_DESIGN_HEIGHT : WORKFLOW_NODE_DESIGN_HEIGHT;
}

export function structuralWorkflowLayoutHash(
  input: WorkflowLayoutInput,
  sizes: ReadonlyMap<string, WorkflowNodeSize> = new Map(),
): WorkflowLayoutHash {
  const rank = nodeRank(input.stages);
  const sortedNodes = [...input.nodes].sort(
    (left, right) => (rank.get(left.nodeId) ?? Number.MAX_SAFE_INTEGER) - (rank.get(right.nodeId) ?? Number.MAX_SAFE_INTEGER),
  );

  const structure = {
    stages: input.stages.map((stage) => ({ id: stage.stageId, nodeIds: stage.nodeIds })),
    nodes: sortedNodes.map((node) => ({
      id: node.nodeId,
      stageId: node.stageId,
      visualKind: node.visualKind,
    })),
    // Resolved label geometry enters the STRUCTURE hash too: the outer
    // spacer node is sized by it, so a wider label forces a relayout even
    // after the calibration budget was spent (the stage channel must grow).
    edges: input.edges.map((edge) => {
      const label = resolveEdgeLabelSpec(edge.label);
      return {
        source: edge.fromNodeId,
        target: edge.toNodeId,
        sourceHandle: edge.sourceHandle ?? null,
        semanticKind: edge.semanticKind,
        labelWidth: label.width,
        labelHeight: label.height,
      };
    }),
  };

  const full = {
    stages: structure.stages,
    nodes: sortedNodes.map((node) => {
      const measured = sizes.get(node.nodeId);
      return {
        id: node.nodeId,
        stageId: node.stageId,
        visualKind: node.visualKind,
        width: measured?.width ?? WORKFLOW_NODE_DESIGN_WIDTH,
        height: measured?.height ?? designHeight(node.visualKind),
      };
    }),
    edges: structure.edges,
  };

  return {
    structure: stableStringify(structure),
    full: stableStringify(full),
  };
}
