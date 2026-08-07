/**
 * Compatibility re-export — layout lives under ./workflow/.
 */
export {
  boxesOverlap,
  layoutWorkflowCanvas,
} from "./workflow/workflowCanvasLayout";

export type {
  WorkflowLayoutEdge,
  WorkflowLayoutInput,
  WorkflowLayoutNode,
} from "../../product/workflow/workflowCanvasTypes";
