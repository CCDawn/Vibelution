import type { ConnectionLineComponentProps } from "@xyflow/react";

import {
  resolveWorkflowManualEdgeGeometry,
  type WorkflowEdgeTerminalSide,
} from "./workflowManualLayout";

function asTerminalSide(value: string): WorkflowEdgeTerminalSide {
  if (value === "left" || value === "right" || value === "top" || value === "bottom") {
    return value;
  }
  return "right";
}

/**
 * Reconnect / rubber-band preview. Uses the same live L/Z path as a dragged
 * settled edge (32px stubs, no bezier / smooth-step). Topology is still gated
 * by isValidConnection; this component only paints the preview.
 */
export function WorkflowOrthogonalConnectionLine({
  fromX,
  fromY,
  toX,
  toY,
  fromPosition,
  toPosition,
  connectionStatus,
  connectionLineStyle,
}: ConnectionLineComponentProps) {
  const geometry = resolveWorkflowManualEdgeGeometry(
    { x: fromX, y: fromY },
    { x: toX, y: toY },
    asTerminalSide(fromPosition),
    asTerminalSide(toPosition),
  );
  const stroke = connectionStatus === "invalid"
    ? "var(--state-error, #dc2626)"
    : "var(--accent-cool, #2563eb)";

  return (
    <g
      data-vui="workflow-connection-line"
      data-connection-status={connectionStatus ?? undefined}
      data-orthogonal="true"
    >
      <path
        fill="none"
        d={geometry.path}
        stroke={stroke}
        strokeWidth={2}
        style={connectionLineStyle}
      />
    </g>
  );
}
