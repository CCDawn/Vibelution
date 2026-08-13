/**
 * Semantic port assignment for the ELK workflow graph.
 * Pure functions — no ELK, no React Flow. Deterministic for the same
 * topology: edge list order defines occurrence ordering, never object
 * iteration order.
 *
 * Contract (see layout design §4.3):
 * - decision `iteration_decision` exposes the FIVE capability outcomes
 *   (rerun/revise/promote/rollback/stop) as decisionOutcomeIds, but only the
 *   REAL current-run edges get ports in the ELK graph.
 * - `rerun` is the only feedback edge (WEST out -> EAST feedback input).
 * - `promote` vs `rollback` are parallel same-source same-target edges and
 *   must use distinct source and target ports.
 * - `revise` executes a child-run lineage; it has no current-run edge and is
 *   never fabricated into the layout.
 */
import type {
  WorkflowCanvasEdgeInput,
  WorkflowCanvasNodeInput,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import type { WorkflowCanvasLayoutMode } from "./workflowElkOptions";

export type EdgePortSide = WorkflowPortSide;

export type ElkPortSpec = { id: string; side: EdgePortSide };

export type PortAssignment = { sourcePortId: string; targetPortId: string };

export type PortResolution = {
  byEdgeId: ReadonlyMap<string, PortAssignment>;
  byNodeId: ReadonlyMap<string, readonly ElkPortSpec[]>;
};

/** The five decision outcomes, fixed order. */
export const DECISION_OUTCOME_IDS = [
  "rerun",
  "revise",
  "promote",
  "rollback",
  "stop",
] as const;

export type DecisionOutcome = (typeof DECISION_OUTCOME_IDS)[number];

/** Outcomes that may produce a current-run edge in the ELK graph. */
const CURRENT_OUTCOME_EDGE_KINDS = new Set<string>(["rerun", "promote", "rollback", "stop"]);

function outcomeForEdge(edge: WorkflowCanvasEdgeInput): DecisionOutcome {
  const handle = edge.sourceHandle;
  if (handle && (DECISION_OUTCOME_IDS as readonly string[]).includes(handle)) {
    if (handle === "revise") {
      throw new Error(
        `workflowElkPorts: edge "${edge.edgeId}" uses revise — revise is a child-run lineage ` +
          `outcome and must not own a current-run edge in this graph`,
      );
    }
    return handle as DecisionOutcome;
  }
  if (edge.semanticKind === "rerun") return "rerun";
  if (edge.semanticKind === "promote") return "promote";
  if (edge.semanticKind === "rollback") return "rollback";
  if (edge.semanticKind === "stop") return "stop";
  if (edge.semanticKind === "revise") {
    throw new Error(
      `workflowElkPorts: edge "${edge.edgeId}" is revise — must not be fabricated ` +
        `as a current-run edge`,
    );
  }
  throw new Error(
    `workflowElkPorts: decision edge "${edge.edgeId}" has no resolvable outcome ` +
      `(sourceHandle=${String(handle)}, semanticKind=${edge.semanticKind})`,
  );
}

function standardEdgeSides(options: {
  crossStage: boolean;
  layoutMode: WorkflowCanvasLayoutMode;
  sourceStageIndex: number;
}): { source: EdgePortSide; target: EdgePortSide } {
  if (options.layoutMode !== "serpentine") {
    return options.crossStage
      ? { source: "EAST", target: "WEST" }
      : { source: "SOUTH", target: "NORTH" };
  }
  if (options.crossStage) return { source: "SOUTH", target: "NORTH" };
  return options.sourceStageIndex % 2 === 0
    ? { source: "EAST", target: "WEST" }
    : { source: "WEST", target: "EAST" };
}

/**
 * Maps a current-run edge list to (a) per-edge source/target port ids and
 * (b) per-node ordered port specs. Port ids are globally unique; ordering
 * follows the input edge order (the definition order) — deterministic.
 */
export function resolveElkPorts(options: {
  nodes: FlowNodePortInput[];
  edges: WorkflowCanvasEdgeInput[];
  stageOrder?: readonly string[];
  layoutMode?: WorkflowCanvasLayoutMode;
}): PortResolution {
  const { nodes, edges, layoutMode = "stage-columns" } = options;
  const nodeById = new Map(nodes.map((n) => [n.nodeId, n] as const));
  const stageOf = new Map(nodes.map((n) => [n.nodeId, n.stageId] as const));
  const inferredStageOrder = Array.from(new Set(nodes.map((node) => node.stageId)));
  const stageIndex = new Map(
    (options.stageOrder ?? inferredStageOrder).map((stageId, index) => [stageId, index] as const),
  );

  const perNode = new Map<string, ElkPortSpec[]>();
  const occ = new Map<string, number>();

  const addPort = (nodeId: string, role: string, side: EdgePortSide): string => {
    const key = `${role}:${nodeId}`;
    const index = occ.get(key) ?? 0;
    occ.set(key, index + 1);
    const id = index === 0 ? key : `${key}:${index}`;
    const list = perNode.get(nodeId) ?? [];
    list.push({ id, side });
    perNode.set(nodeId, list);
    return id;
  };

  const byEdgeId = new Map<string, PortAssignment>();

  for (const edge of edges) {
    const sourceRef = nodeById.get(edge.fromNodeId);
    const targetRef = nodeById.get(edge.toNodeId);
    if (!sourceRef || !targetRef) {
      throw new Error(`workflowElkPorts: edge "${edge.edgeId}" references unknown node`);
    }
    const sourceStage = stageOf.get(edge.fromNodeId);
    const targetStage = stageOf.get(edge.toNodeId);

    if (sourceRef.visualKind === "decision") {
      const outcome = outcomeForEdge(edge);
      if (!CURRENT_OUTCOME_EDGE_KINDS.has(outcome)) {
        throw new Error(
          `workflowElkPorts: outcome "${outcome}" is not a current-run edge ` +
            `(revise executes a child run lineage and must not be fabricated)`,
        );
      }
      let sourcePortId: string;
      let targetPortId: string;
      if (outcome === "rerun") {
        sourcePortId = addPort(sourceRef.nodeId, "decision:rerun", "WEST");
        targetPortId = addPort(targetRef.nodeId, "feedback:in", "EAST");
      } else if (outcome === "promote" || outcome === "rollback") {
        sourcePortId = addPort(sourceRef.nodeId, `decision:${outcome}`, "SOUTH");
        targetPortId = addPort(targetRef.nodeId, `in:${outcome}`, "NORTH");
      } else {
        sourcePortId = addPort(sourceRef.nodeId, "decision:stop", "SOUTH");
        targetPortId = addPort(targetRef.nodeId, "in:north", "NORTH");
      }
      byEdgeId.set(edge.edgeId, { sourcePortId, targetPortId });
    } else {
      const cross = sourceStage !== targetStage;
      const index = stageIndex.get(sourceRef.stageId) ?? 0;
      const { source: sourceSide, target: targetSide } = standardEdgeSides({
        crossStage: cross,
        layoutMode,
        sourceStageIndex: index,
      });
      const sideRole = (side: EdgePortSide) => side.toLowerCase();
      const sourcePortId = addPort(
        sourceRef.nodeId,
        `out:${sideRole(sourceSide)}`,
        sourceSide,
      );
      const targetPortId = addPort(
        targetRef.nodeId,
        `in:${sideRole(targetSide)}`,
        targetSide,
      );
      byEdgeId.set(edge.edgeId, { sourcePortId, targetPortId });
    }
  }

  return { byEdgeId, byNodeId: perNode };
}

export type FlowNodePortInput = {
  nodeId: string;
  stageId: string;
  visualKind: WorkflowCanvasNodeInput["visualKind"];
};
