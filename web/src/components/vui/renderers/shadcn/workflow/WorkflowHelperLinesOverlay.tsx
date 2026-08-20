import { ViewportPortal, useViewport } from "@xyflow/react";

import {
  WORKFLOW_HELPER_LINE_SPAN,
  resolveWorkflowHelperOverlayStroke,
  workflowHelperLinesActive,
  type WorkflowHelperLines,
} from "./workflowHelperLines";

export function WorkflowHelperLinesOverlay({ lines }: { lines: WorkflowHelperLines | null }) {
  const { zoom } = useViewport();
  if (!workflowHelperLinesActive(lines) || !lines) return null;

  const stroke = resolveWorkflowHelperOverlayStroke(zoom);
  const span = WORKFLOW_HELPER_LINE_SPAN;

  return (
    <ViewportPortal>
      <svg
        className="pointer-events-none absolute left-0 top-0 overflow-visible"
        width={1}
        height={1}
        data-vui="workflow-helper-lines"
        aria-hidden
      >
        {lines.vertical != null ? (
          <line
            x1={lines.vertical}
            x2={lines.vertical}
            y1={-span}
            y2={span}
            stroke="var(--accent-cool, #2563eb)"
            strokeDasharray={stroke.dasharray}
            strokeWidth={stroke.strokeWidth}
          />
        ) : null}
        {lines.horizontal != null ? (
          <line
            x1={-span}
            x2={span}
            y1={lines.horizontal}
            y2={lines.horizontal}
            stroke="var(--accent-cool, #2563eb)"
            strokeDasharray={stroke.dasharray}
            strokeWidth={stroke.strokeWidth}
          />
        ) : null}
      </svg>
    </ViewportPortal>
  );
}
