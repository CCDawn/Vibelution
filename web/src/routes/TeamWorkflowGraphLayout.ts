import type { TeamWorkflowCandidateGraphNode, TeamWorkflowCandidateGraphPayload } from "../api/types";

const WORKFLOW_GRAPH_WIDTH = 1120;
const WORKFLOW_GRAPH_MIN_HEIGHT = 320;
const WORKFLOW_GRAPH_NODE_WIDTH = 168;
const WORKFLOW_GRAPH_NODE_HEIGHT = 58;
const WORKFLOW_GRAPH_NODE_GAP = 30;
const WORKFLOW_GRAPH_MARGIN_X = 22;
const WORKFLOW_GRAPH_MARGIN_Y = 28;

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

/**
 * Pure layout geometry for the workflow graph.
 * Kept separate from `TeamWorkflowGraphView` so orchestration can compute layout
 * without pulling the SVG panel into the Teams shell chunk.
 */
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

export const workflowGraphViewMetrics = {
  width: WORKFLOW_GRAPH_WIDTH,
  minHeight: WORKFLOW_GRAPH_MIN_HEIGHT,
  nodeWidth: WORKFLOW_GRAPH_NODE_WIDTH,
  nodeHeight: WORKFLOW_GRAPH_NODE_HEIGHT,
  nodeGap: WORKFLOW_GRAPH_NODE_GAP,
  marginX: WORKFLOW_GRAPH_MARGIN_X,
  marginY: WORKFLOW_GRAPH_MARGIN_Y,
} as const;
