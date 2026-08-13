/**
 * ELK layout options for the workflow compound graph.
 *
 * Key names and value formats are pinned against `elkjs` 0.12 `knownLayoutOptions`
 * by the option-keys tests in `workflowElkLayout.test.ts`; do not edit a value
 * here without re-running those tests.
 */

/** Design-contract sizes used when the node reports no measured height yet. */
export const WORKFLOW_NODE_DESIGN_WIDTH = 248;
export const WORKFLOW_NODE_DESIGN_HEIGHT = 88;
export const WORKFLOW_DECISION_DESIGN_HEIGHT = 112;
export const WORKFLOW_SERPENTINE_NODE_DESIGN_WIDTH = 244;
export const WORKFLOW_SERPENTINE_NODE_DESIGN_HEIGHT = 102;
export const WORKFLOW_SERPENTINE_DECISION_DESIGN_HEIGHT = 102;
export const WORKFLOW_NODE_LABEL_WIDTH = WORKFLOW_NODE_DESIGN_WIDTH - 24;
export const WORKFLOW_NODE_LABEL_HEIGHT = 20;

/** Stable VUI layout variants. Routes select a variant through VWorkflowCanvas. */
export type WorkflowCanvasLayoutMode = "stage-columns" | "serpentine";

/** Labels that carry a real transition or decision, rather than restating the adjacent cards. */
export function workflowEdgeKeepsNarrativeLabel(edge: {
  semanticKind?: string;
  gateKind?: string;
}): boolean {
  return edge.gateKind === "knowledge_package"
    || edge.gateKind === "smoke"
    || edge.gateKind === "promotion"
    || edge.semanticKind === "decision_branch"
    || edge.semanticKind === "rerun"
    || edge.semanticKind === "revise"
    || edge.semanticKind === "promote"
    || edge.semanticKind === "rollback"
    || edge.semanticKind === "stop";
}

export function workflowStageDirection(
  layoutMode: WorkflowCanvasLayoutMode,
  stageIndex: number,
): "DOWN" | "RIGHT" | "LEFT" {
  if (layoutMode !== "serpentine") return "DOWN";
  return stageIndex % 2 === 0 ? "RIGHT" : "LEFT";
}

export function workflowStageInternalOptions(
  layoutMode: WorkflowCanvasLayoutMode,
  stageIndex: number,
): Record<string, string> {
  return {
    ...WORKFLOW_ELK_STAGE_INTERNAL_OPTIONS,
    "elk.direction": workflowStageDirection(layoutMode, stageIndex),
    ...(layoutMode === "serpentine"
      ? {
          "elk.spacing.nodeNode": "34",
          "elk.spacing.edgeNode": "22",
          "elk.spacing.edgeEdge": "10",
        }
      : {}),
  };
}

export function workflowNodeDesignSize(
  layoutMode: WorkflowCanvasLayoutMode,
  visualKind: string,
): { width: number; height: number } {
  if (layoutMode === "serpentine") {
    return {
      width: WORKFLOW_SERPENTINE_NODE_DESIGN_WIDTH,
      height:
        visualKind === "decision"
          ? WORKFLOW_SERPENTINE_DECISION_DESIGN_HEIGHT
          : WORKFLOW_SERPENTINE_NODE_DESIGN_HEIGHT,
    };
  }
  return {
    width: WORKFLOW_NODE_DESIGN_WIDTH,
    height: visualKind === "decision" ? WORKFLOW_DECISION_DESIGN_HEIGHT : WORKFLOW_NODE_DESIGN_HEIGHT,
  };
}

/** Stage title reserved band height; geometry tests assert edges avoid it. */
export const WORKFLOW_STAGE_TITLE_HEIGHT = 40;

/** Root compound graph: three stages flow left to right. */
export const WORKFLOW_ELK_ROOT_OPTIONS = {
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
  "org.eclipse.elk.portConstraints": "FIXED_ORDER",
  "elk.separateConnectedComponents": "false",
  "elk.spacing.componentComponent": "36",
  "elk.edgeLabels.placement": "CENTER",
} as const;

/** Each stage: tasks flow top to bottom inside the compound region. */
export const WORKFLOW_ELK_STAGE_OPTIONS = {
  "elk.direction": "DOWN",
  "elk.padding": "[top=56,left=12,bottom=28,right=12]",
  "elk.spacing.nodeNode": "18",
  "elk.spacing.edgeNode": "24",
  "elk.nodeLabels.placement": "INSIDE V_TOP H_LEFT",
} as const;

/**
 * Stage-internal subgraph options (two-level layout, phase A): NO padding —
 * the stage box and its padding/title band are computed explicitly by
 * `workflowStageLayout`, so ELK's own padding cannot drift the children from
 * the box we declare to the meta layout.
 */
export const WORKFLOW_ELK_STAGE_INTERNAL_OPTIONS = {
  "elk.direction": "DOWN",
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.spacing.nodeNode": "18",
  "elk.spacing.edgeNode": "24",
  "elk.spacing.edgeEdge": "8",
  "elk.nodeLabels.placement": "INSIDE V_TOP H_LEFT",
} as const;
