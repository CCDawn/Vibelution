/**
 * Workflow edge: renders the engine-owned ORTHOGONAL section geometry
 * (data.sections) with path-state colors and label bounds. It never re-routes
 * the edge itself; a smooth-step approximation is forbidden in production.
 */
import {
  BaseEdge,
  EdgeLabelRenderer,
  type EdgeProps,
} from "@xyflow/react";
import { useMemo, useState } from "react";

import { cn } from "../../../lib/cn";
import type {
  WorkflowEdgePathState,
  WorkflowEdgeSemanticKind,
  WorkflowEdgeSection,
  WorkflowLabelBounds,
} from "../../../product/workflow/workflowCanvasTypes";
import { resolveEdgeStroke } from "./workflowCanvasState";
import { resolveEdgeLabelAnchor, sectionsToSvgPath } from "./workflowElkEdgePath";

export type WorkflowSemanticEdgeData = {
  label?: string;
  semanticKind?: WorkflowEdgeSemanticKind;
  pathState?: WorkflowEdgePathState;
  labelAlwaysVisible?: boolean;
  /** Engine-owned ORTHOGONAL route. Absent only on legacy/defensive fixtures. */
  sections?: WorkflowEdgeSection[];
  /** Engine-owned label anchor; falls back to a section midpoint. */
  labelBounds?: WorkflowLabelBounds;
};

export function WorkflowSemanticEdge({ id, data, markerEnd, style }: EdgeProps) {
  const [hovered, setHovered] = useState(false);
  const edgeData = data as WorkflowSemanticEdgeData | undefined;
  const semanticKind = edgeData?.semanticKind ?? "main";
  const pathState = edgeData?.pathState ?? "idle";
  const label = String(edgeData?.label ?? "");
  const always = Boolean(edgeData?.labelAlwaysVisible);
  const stroke = resolveEdgeStroke(pathState, semanticKind);

  const sections = edgeData?.sections;
  const edgePath = useMemo(() => sectionsToSvgPath(sections ?? []), [sections]);
  const labelAnchor = useMemo(
    () => resolveEdgeLabelAnchor(edgeData?.labelBounds),
    [edgeData?.labelBounds],
  );

  const showLabel = Boolean(label) && (always || hovered || pathState === "active" || pathState === "attention") && labelAnchor !== null;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: stroke.stroke,
          strokeWidth: stroke.strokeWidth,
          strokeDasharray: stroke.dasharray,
        }}
        interactionWidth={20}
        className={stroke.animated ? "workflow-edge-active" : undefined}
      />
      {/* Invisible wider hit target for hover labels */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={18}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      />
      {showLabel ? (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelAnchor.x}px,${labelAnchor.y}px)`,
              pointerEvents: "all",
            }}
            className={cn(
              "max-w-[9.5rem] truncate rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-tight shadow-sm",
              "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] text-[var(--fg-secondary)]",
              pathState === "active" ? "border-[color-mix(in_srgb,var(--accent-cool)_40%,var(--vui-border-subtle))] text-[var(--accent-cool)]" : "",
              pathState === "attention" ? "border-[color-mix(in_srgb,var(--state-warning)_40%,var(--vui-border-subtle))] text-[var(--state-warning)]" : "",
              pathState === "danger" ? "border-[color-mix(in_srgb,var(--state-error)_40%,var(--vui-border-subtle))] text-[var(--state-error)]" : "",
            )}
            data-vui="workflow-edge-label"
            data-semantic={semanticKind}
            data-path-state={pathState}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
