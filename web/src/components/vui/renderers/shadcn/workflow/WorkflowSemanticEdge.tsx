/**
 * Semantic workflow edge: arrow markers, path state colors, label surfaces.
 */
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react";
import { useState } from "react";

import { cn } from "../../../lib/cn";
import type { WorkflowEdgePathState, WorkflowEdgeSemanticKind } from "../../../product/workflow/workflowCanvasTypes";
import { resolveEdgeStroke } from "./workflowCanvasState";

export type WorkflowSemanticEdgeData = {
  label?: string;
  semanticKind?: WorkflowEdgeSemanticKind;
  pathState?: WorkflowEdgePathState;
  labelAlwaysVisible?: boolean;
};

export function WorkflowSemanticEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  markerEnd,
  style,
}: EdgeProps) {
  const [hovered, setHovered] = useState(false);
  const semanticKind = (data?.semanticKind as WorkflowEdgeSemanticKind) || "main";
  const pathState = (data?.pathState as WorkflowEdgePathState) || "idle";
  const label = String(data?.label ?? "");
  const always = Boolean(data?.labelAlwaysVisible);
  const stroke = resolveEdgeStroke(pathState, semanticKind);

  // Feedback loops: route outside via larger offset.
  const isLoop =
    semanticKind === "rerun"
    || semanticKind === "revise"
    || semanticKind === "rollback"
    || (sourceX > targetX + 40);

  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 12,
    offset: isLoop ? 36 : 18,
  });

  const showLabel = Boolean(label) && (always || hovered || pathState === "active" || pathState === "attention");

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
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
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
