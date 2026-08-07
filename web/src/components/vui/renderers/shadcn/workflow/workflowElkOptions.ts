/**
 * ELK layout options for the workflow compound graph.
 *
 * Key names and value formats are pinned against `elkjs` 0.12 `knownLayoutOptions`
 * by the probe tests in `workflowElkLayout.test.ts`; do not edit a value here
 * without re-running the probe.
 */

/** Design-contract sizes used when the node reports no measured height yet. */
export const WORKFLOW_NODE_DESIGN_WIDTH = 248;
export const WORKFLOW_NODE_DESIGN_HEIGHT = 88;
export const WORKFLOW_DECISION_DESIGN_HEIGHT = 112;
export const WORKFLOW_NODE_LABEL_WIDTH = WORKFLOW_NODE_DESIGN_WIDTH - 24;
export const WORKFLOW_NODE_LABEL_HEIGHT = 20;
export const WORKFLOW_EDGE_LABEL_WIDTH = 152;
export const WORKFLOW_EDGE_LABEL_HEIGHT = 26;

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