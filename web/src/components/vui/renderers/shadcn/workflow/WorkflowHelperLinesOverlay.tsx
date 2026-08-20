import { useViewport } from "@xyflow/react";

import {
  workflowHelperLineToScreen,
  workflowHelperLinesActive,
  type WorkflowHelperLines,
} from "./workflowHelperLines";

export function WorkflowHelperLinesOverlay({ lines }: { lines: WorkflowHelperLines | null }) {
  const { x, y, zoom } = useViewport();
  if (!workflowHelperLinesActive(lines) || !lines) return null;

  return (
    <svg
      className="pointer-events-none absolute inset-0 z-[5] h-full w-full overflow-visible"
      data-vui="workflow-helper-lines"
      aria-hidden
    >
      {lines.vertical != null ? (
        <line
          x1={workflowHelperLineToScreen(lines.vertical, x, zoom)}
          x2={workflowHelperLineToScreen(lines.vertical, x, zoom)}
          y1={0}
          y2="100%"
          stroke="var(--accent-cool, #2563eb)"
          strokeDasharray="6 4"
          strokeWidth={1}
        />
      ) : null}
      {lines.horizontal != null ? (
        <line
          x1={0}
          x2="100%"
          y1={workflowHelperLineToScreen(lines.horizontal, y, zoom)}
          y2={workflowHelperLineToScreen(lines.horizontal, y, zoom)}
          stroke="var(--accent-cool, #2563eb)"
          strokeDasharray="6 4"
          strokeWidth={1}
        />
      ) : null}
    </svg>
  );
}
