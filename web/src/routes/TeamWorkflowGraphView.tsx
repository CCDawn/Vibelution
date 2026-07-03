import type { CSSProperties } from "react";

import type { TeamWorkflowCandidateGraphNode, TeamWorkflowCandidateGraphPayload } from "../api/types";
import styles from "./TeamsRoute.styles";

const WORKFLOW_GRAPH_WIDTH = 1120;
const WORKFLOW_GRAPH_MIN_HEIGHT = 320;
const WORKFLOW_GRAPH_NODE_WIDTH = 168;
const WORKFLOW_GRAPH_NODE_HEIGHT = 58;
const WORKFLOW_GRAPH_NODE_GAP = 30;
const WORKFLOW_GRAPH_MARGIN_X = 22;
const WORKFLOW_GRAPH_MARGIN_Y = 28;

type WorkflowGraphDynamicVariable =
  | "--workflow-graph-height"
  | "--workflow-graph-width"
  | "--workflow-graph-node-x"
  | "--workflow-graph-node-y";

type WorkflowGraphDynamicStyle = CSSProperties & Partial<Record<WorkflowGraphDynamicVariable, string>>;

type WorkflowGraphFrameStyle = WorkflowGraphDynamicStyle & Record<"--workflow-graph-height" | "--workflow-graph-width", string>;

type WorkflowGraphNodeStyle = WorkflowGraphDynamicStyle & Record<"--workflow-graph-node-x" | "--workflow-graph-node-y", string>;

export type TeamWorkflowGraphNodeView = TeamWorkflowCandidateGraphNode & {
  x: number;
  y: number;
};

export type TeamWorkflowGraphLayout = {
  nodes: TeamWorkflowGraphNodeView[];
  edges: TeamWorkflowCandidateGraphPayload["edges"];
  width: number;
  height: number;
};

type TeamWorkflowGraphViewProps = {
  layout: TeamWorkflowGraphLayout;
  markerId: string;
  stateLabel: (value: string) => string;
};

function workflowGraphFrameStyle(layout: Pick<TeamWorkflowGraphLayout, "height" | "width">): WorkflowGraphFrameStyle {
  return {
    "--workflow-graph-height": `${layout.height}px`,
    "--workflow-graph-width": `${layout.width}px`,
  };
}

function workflowGraphNodeStyle(node: Pick<TeamWorkflowGraphNodeView, "x" | "y">): WorkflowGraphNodeStyle {
  return {
    "--workflow-graph-node-x": `${node.x}px`,
    "--workflow-graph-node-y": `${node.y}px`,
  };
}

function workflowGraphTypeRank(candidateType: string) {
  const order: Record<string, number> = {
    source_manifest: 0,
    paper_note: 1,
    neuro_mechanism: 2,
    mechanism_mapping: 3,
    algorithm_hypothesis: 4,
    review_record: 5,
    candidate_graph: 6,
  };
  return order[candidateType] ?? 7;
}

export function workflowGraphLayout(graph: TeamWorkflowCandidateGraphPayload): TeamWorkflowGraphLayout {
  const columns = Math.max(
    1,
    Math.floor(
      (WORKFLOW_GRAPH_WIDTH - WORKFLOW_GRAPH_MARGIN_X * 2 + WORKFLOW_GRAPH_NODE_GAP) /
        (WORKFLOW_GRAPH_NODE_WIDTH + WORKFLOW_GRAPH_NODE_GAP),
    ),
  );
  const nodes = [...graph.nodes]
    .sort((left, right) => {
      const rankDelta = workflowGraphTypeRank(left.candidateType) - workflowGraphTypeRank(right.candidateType);
      if (rankDelta !== 0) {
        return rankDelta;
      }
      return String(left.title || left.candidateId).localeCompare(String(right.title || right.candidateId));
    })
    .map((node, index) => ({
      ...node,
      x: WORKFLOW_GRAPH_MARGIN_X + (index % columns) * (WORKFLOW_GRAPH_NODE_WIDTH + WORKFLOW_GRAPH_NODE_GAP),
      y: WORKFLOW_GRAPH_MARGIN_Y + Math.floor(index / columns) * (WORKFLOW_GRAPH_NODE_HEIGHT + WORKFLOW_GRAPH_NODE_GAP),
    }));
  const rows = Math.max(1, Math.ceil(nodes.length / columns));
  const height = Math.max(
    WORKFLOW_GRAPH_MIN_HEIGHT,
    WORKFLOW_GRAPH_MARGIN_Y * 2 + rows * WORKFLOW_GRAPH_NODE_HEIGHT + Math.max(0, rows - 1) * WORKFLOW_GRAPH_NODE_GAP,
  );
  return { nodes, edges: graph.edges, width: WORKFLOW_GRAPH_WIDTH, height };
}

function workflowGraphVisualEndpoints(edge: TeamWorkflowCandidateGraphPayload["edges"][number]) {
  const evidenceToCandidateRelations = new Set([
    "supported_by_paper_note",
    "maps_from_neuro_mechanism",
    "inspired_by_mapping",
    "inspired_by_neuro_mechanism",
    "reviews_candidate",
  ]);
  return evidenceToCandidateRelations.has(edge.relation)
    ? { sourceCandidateId: edge.targetCandidateId, targetCandidateId: edge.sourceCandidateId }
    : { sourceCandidateId: edge.sourceCandidateId, targetCandidateId: edge.targetCandidateId };
}

function workflowGraphEdgePath(edge: TeamWorkflowCandidateGraphPayload["edges"][number], nodes: TeamWorkflowGraphNodeView[]) {
  const endpoints = workflowGraphVisualEndpoints(edge);
  const source = nodes.find((node) => node.candidateId === endpoints.sourceCandidateId);
  const target = nodes.find((node) => node.candidateId === endpoints.targetCandidateId);
  if (!source || !target) {
    return null;
  }
  const x1 = source.x + WORKFLOW_GRAPH_NODE_WIDTH;
  const y1 = source.y + WORKFLOW_GRAPH_NODE_HEIGHT / 2;
  const x2 = target.x;
  const y2 = target.y + WORKFLOW_GRAPH_NODE_HEIGHT / 2;
  const curve = Math.max(34, Math.abs(x2 - x1) * 0.42);
  return `M ${x1} ${y1} C ${x1 + curve} ${y1}, ${x2 - curve} ${y2}, ${x2} ${y2}`;
}

function workflowGraphNodeTone(node: TeamWorkflowCandidateGraphNode) {
  if (!node.valid || String(node.qualityStatus || "").includes("broken")) {
    return styles.workflowGraphNodeDanger;
  }
  if (node.requiresReview || String(node.currentState || "").includes("revision")) {
    return styles.workflowGraphNodeWarning;
  }
  if (String(node.currentState || "").includes("synced") || String(node.qualityStatus || "").includes("ready")) {
    return styles.workflowGraphNodeReady;
  }
  return styles.workflowGraphNodeNeutral;
}

export function TeamWorkflowGraphView({ layout, markerId, stateLabel }: TeamWorkflowGraphViewProps) {
  return (
    <div
      className={styles.workflowGraphFrame}
      style={workflowGraphFrameStyle(layout)}
    >
      <div className={styles.workflowGraphCanvas}>
        <svg
          className={styles.workflowGraphSvg}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          preserveAspectRatio="xMinYMin meet"
          aria-hidden="true"
        >
          <defs>
            <marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto">
              <path d="M 0 0 L 10 5 L 0 10 z" />
            </marker>
          </defs>
          {layout.edges.map((edge) => {
            const path = workflowGraphEdgePath(edge, layout.nodes);
            return path ? (
              <path
                key={`${edge.sourceCandidateId}-${edge.targetCandidateId}-${edge.relation}`}
                className={styles.workflowGraphEdge}
                d={path}
              >
                <title>{edge.relation}</title>
              </path>
            ) : null;
          })}
        </svg>
        {layout.nodes.map((node) => (
          <div
            key={node.candidateId}
            className={`${styles.workflowGraphNode} ${workflowGraphNodeTone(node)}`}
            style={workflowGraphNodeStyle(node)}
            title={`${node.candidateId} · ${node.currentState}`}
          >
            <strong>{node.title || node.candidateId}</strong>
            <span>{stateLabel(node.currentState)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
