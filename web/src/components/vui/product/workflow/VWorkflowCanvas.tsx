/**
 * Product API: workflow canvas. Routes must import this, never the React Flow renderer.
 */
import type { ComponentProps } from "react";

import { ShadcnWorkflowCanvas } from "../../renderers/shadcn/ShadcnWorkflowCanvas";

export type VWorkflowCanvasProps = ComponentProps<typeof ShadcnWorkflowCanvas>;

export function VWorkflowCanvas(props: VWorkflowCanvasProps) {
  return <ShadcnWorkflowCanvas {...props} />;
}
