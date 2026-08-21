import type { CSSProperties } from "react";

import type { TeamWorkflowCandidateGraphNode, TeamWorkflowCandidateGraphPayload } from "../api/types";
import { VNativeButton } from "../components/vui";
import {
  type TeamWorkflowGraphLayout,
  type TeamWorkflowGraphNodeView,
  workflowGraphViewMetrics,
} from "./TeamWorkflowGraphLayout";
import styles from "./TeamWorkflowGraphView.styles";

export type { TeamWorkflowGraphLayout, TeamWorkflowGraphNodeView } from "./TeamWorkflowGraphLayout";
export { workflowGraphLayout } from "./TeamWorkflowGraphLayout";

type WorkflowGraphDynamicVariable =
  | "--workflow-graph-height"
  | "--workflow-graph-width"
  | "--workflow-graph-node-x"
  | "--workflow-graph-node-y";

type WorkflowGraphDynamicStyle = CSSProperties & Partial<Record<WorkflowGraphDynamicVariable, string>>;

type WorkflowGraphFrameStyle = WorkflowGraphDynamicStyle & Record<"--workflow-graph-height" | "--workflow-graph-width", string>;

type WorkflowGraphNodeStyle = WorkflowGraphDynamicStyle & Record<"--workflow-graph-node-x" | "--workflow-graph-node-y", string>;

type TeamWorkflowGraphViewProps = {
  layout: TeamWorkflowGraphLayout;
  markerId: string;
  stateLabel: (value: string) => string;
  /**
   * When set, only edges touching this candidate render at full strength.
   * Other edges stay muted or hidden so dense maps stay readable.
   */
  focusCandidateId?: string;
  /** Optional language for the empty-focus hint. */
  lang?: "zh" | "en";
  onFocusCandidate?: (candidateId: string) => void;
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

/**
 * Attach to nearest sides and fan curves by edge index so dense grids do not
 * all collapse into one black scribble through the middle of the canvas.
 */
export function workflowGraphEdgePath(
  edge: TeamWorkflowCandidateGraphPayload["edges"][number],
  nodes: TeamWorkflowGraphNodeView[],
  edgeIndex = 0,
  nodeById?: Map<string, TeamWorkflowGraphNodeView>,
) {
  const endpoints = workflowGraphVisualEndpoints(edge);
  const lookup = nodeById ?? new Map(nodes.map((node) => [node.candidateId, node]));
  const source = lookup.get(endpoints.sourceCandidateId);
  const target = lookup.get(endpoints.targetCandidateId);
  if (!source || !target) {
    return null;
  }
  const { nodeWidth, nodeHeight } = workflowGraphViewMetrics;
  const sx = source.x + nodeWidth / 2;
  const sy = source.y + nodeHeight / 2;
  const tx = target.x + nodeWidth / 2;
  const ty = target.y + nodeHeight / 2;
  const dx = tx - sx;
  const dy = ty - sy;
  let x1: number;
  let y1: number;
  let x2: number;
  let y2: number;
  if (Math.abs(dx) >= Math.abs(dy)) {
    if (dx >= 0) {
      x1 = source.x + nodeWidth;
      y1 = sy;
      x2 = target.x;
      y2 = ty;
    } else {
      x1 = source.x;
      y1 = sy;
      x2 = target.x + nodeWidth;
      y2 = ty;
    }
  } else if (dy >= 0) {
    x1 = sx;
    y1 = source.y + nodeHeight;
    x2 = tx;
    y2 = target.y;
  } else {
    x1 = sx;
    y1 = source.y;
    x2 = tx;
    y2 = target.y + nodeHeight;
  }
  // Fan control points so parallel edges do not stack into one stroke.
  const fan = ((edgeIndex % 9) - 4) * 10;
  const midX = (x1 + x2) / 2 + (Math.abs(dy) > Math.abs(dx) ? fan : 0);
  const midY = (y1 + y2) / 2 + (Math.abs(dx) >= Math.abs(dy) ? fan : fan * 0.35);
  return `M ${x1} ${y1} Q ${midX} ${midY} ${x2} ${y2}`;
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

function edgeTouchesCandidate(
  edge: TeamWorkflowCandidateGraphPayload["edges"][number],
  candidateId: string,
) {
  return edge.sourceCandidateId === candidateId || edge.targetCandidateId === candidateId;
}

export function TeamWorkflowGraphView({
  layout,
  markerId,
  stateLabel,
  focusCandidateId = "",
  lang = "zh",
  onFocusCandidate,
}: TeamWorkflowGraphViewProps) {
  const focus = String(focusCandidateId || "").trim();
  const dense = layout.edges.length >= 8;
  const neighborIds = new Set<string>();
  if (focus) {
    neighborIds.add(focus);
    for (const edge of layout.edges) {
      if (edgeTouchesCandidate(edge, focus)) {
        neighborIds.add(edge.sourceCandidateId);
        neighborIds.add(edge.targetCandidateId);
      }
    }
  }

  return (
    <div
      className={styles.workflowGraphFrame}
      style={workflowGraphFrameStyle(layout)}
      data-testid="workflow-graph-view"
      data-focus={focus || "none"}
      data-dense={dense ? "true" : "false"}
    >
      {dense ? (
        <p className={styles.workflowGraphHint} data-testid="workflow-graph-hint">
          {focus
            ? (lang === "zh"
              ? "已按选中节点过滤关系边；点空白卡片或下方列表可切换焦点。"
              : "Edges filtered to the focused node. Pick another card to change focus.")
            : (lang === "zh"
              ? "关系较多：默认淡化全部连线。点节点或下方列表，只高亮该节点相关关系。"
              : "Dense map: edges stay muted until you focus a node from the canvas or list.")}
        </p>
      ) : null}
      <div className={styles.workflowGraphCanvas}>
        <svg
          className={styles.workflowGraphSvg}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          preserveAspectRatio="xMinYMin meet"
          aria-hidden="true"
        >
          <defs>
            <marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto">
              <path d="M 0 0 L 10 5 L 0 10 z" className={styles.workflowGraphMarkerFill} />
            </marker>
            <marker id={`${markerId}-muted`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4" markerHeight="4" orient="auto">
              <path d="M 0 0 L 10 5 L 0 10 z" className={styles.workflowGraphMarkerFillMuted} />
            </marker>
          </defs>
          {(() => {
            const nodeById = new Map(layout.nodes.map((node) => [node.candidateId, node]));
            return layout.edges.map((edge, edgeIndex) => {
            const path = workflowGraphEdgePath(edge, layout.nodes, edgeIndex, nodeById);
            if (!path) {
              return null;
            }
            const focused = focus ? edgeTouchesCandidate(edge, focus) : !dense;
            // Dense + no focus: keep a whisper of structure; dense + focus: only related edges.
            if (dense && focus && !focused) {
              return null;
            }
            return (
              <path
                key={`${edge.sourceCandidateId}-${edge.targetCandidateId}-${edge.relation}-${edgeIndex}`}
                className={focused ? styles.workflowGraphEdgeFocus : styles.workflowGraphEdgeMuted}
                d={path}
                markerEnd={`url(#${focused ? markerId : `${markerId}-muted`})`}
              >
                <title>{edge.relation}</title>
              </path>
            );
            });
          })()}
        </svg>
        {layout.nodes.map((node) => {
          const isFocus = focus === node.candidateId;
          const isNeighbor = !focus || neighborIds.has(node.candidateId);
          return (
            <VNativeButton
              key={node.candidateId}
              type="button"
              className={[
                styles.workflowGraphNode,
                workflowGraphNodeTone(node),
                isFocus ? styles.workflowGraphNodeFocus : "",
                focus && !isNeighbor ? styles.workflowGraphNodeDim : "",
              ].filter(Boolean).join(" ")}
              style={workflowGraphNodeStyle(node)}
              title={`${node.candidateId} · ${node.currentState}`}
              data-testid={`workflow-graph-node-${node.candidateId}`}
              data-focus={isFocus ? "true" : "false"}
              data-vui="workflow-graph-node"
              onClick={() => onFocusCandidate?.(node.candidateId)}
            >
              <strong>{node.title || node.candidateId}</strong>
              <span>{stateLabel(node.currentState)}</span>
            </VNativeButton>
          );
        })}
      </div>
    </div>
  );
}
