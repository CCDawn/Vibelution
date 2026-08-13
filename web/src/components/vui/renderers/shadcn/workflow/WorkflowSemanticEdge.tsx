/**
 * Workflow edge: renders the engine-owned ORTHOGONAL section geometry
 * (data.sections) with path-state colors and label bounds. It never re-routes
 * the edge itself; a smooth-step approximation is forbidden in production.
 *
 * Diagnostics (P1-3/P1-5): a section chain that is not well-formed (cycles,
 * branches, orphans, geometrically broken links) or a label without engine
 * labelBounds surfaces `data-section-fault` / `data-label-fault` on the DOM
 * and a console warning instead of silently rendering a broken edge.
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
import { resolveEdgeLabelSpec } from "./workflowEdgeLabelGeometry";
import {
  analyzeEdgeSections,
  resolveEdgeLabelAnchor,
  sectionsToSvgPath,
} from "./workflowElkEdgePath";
import { workflowEdgeKeepsNarrativeLabel } from "./workflowElkOptions";

export type WorkflowSemanticEdgeData = {
  label?: string;
  semanticKind?: WorkflowEdgeSemanticKind;
  pathState?: WorkflowEdgePathState;
  labelAlwaysVisible?: boolean;
  gateKind?: string;
  /** Engine-owned ORTHOGONAL route. Absent only on legacy/defensive fixtures. */
  sections?: WorkflowEdgeSection[];
  /** Engine-owned label anchor; without it the label is not rendered. */
  labelBounds?: WorkflowLabelBounds;
};

export function WorkflowSemanticEdge({ id, data, markerEnd, style }: EdgeProps) {
  const [hovered, setHovered] = useState(false);
  const edgeData = data as WorkflowSemanticEdgeData | undefined;
  const semanticKind = edgeData?.semanticKind ?? "main";
  const pathState = edgeData?.pathState ?? "idle";
  const label = String(edgeData?.label ?? "");
  const always = Boolean(edgeData?.labelAlwaysVisible);
  const gateKind = String(edgeData?.gateKind ?? "");
  const stroke = resolveEdgeStroke(pathState, semanticKind);

  const sections = edgeData?.sections;
  const edgePath = useMemo(() => sectionsToSvgPath(sections ?? []), [sections]);
  const sectionFault = useMemo(
    () => (sections && sections.length > 0 ? !analyzeEdgeSections(sections).wellFormed : false),
    [sections],
  );
  const labelAnchor = useMemo(
    () => resolveEdgeLabelAnchor(edgeData?.labelBounds),
    [edgeData?.labelBounds],
  );
  const labelFault = Boolean(label) && !edgeData?.labelBounds;
  // Shared label geometry contract: the rendered box is exactly the box the
  // layout claimed (spacer size), and long text is truncated the same way in
  // layout and render.
  const labelSpec = useMemo(() => resolveEdgeLabelSpec(label), [label]);

  const semanticTransition = workflowEdgeKeepsNarrativeLabel({ semanticKind, gateKind });
  const showLabel = Boolean(label)
    && ((always && semanticTransition) || hovered || pathState === "active" || pathState === "attention")
    && labelAnchor !== null;

  if ((sectionFault || labelFault) && import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.warn(
      `workflow edge "${id}" diagnostic:${sectionFault ? " section-chain fault" : ""}${labelFault ? " label without engine bounds" : ""}`,
    );
  }

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        data-section-fault={sectionFault ? "true" : undefined}
        data-label-fault={labelFault ? "true" : undefined}
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
              width: labelSpec.width,
              height: labelSpec.height,
            }}
            className={cn(
              "truncate rounded-md border text-center text-[11px] font-medium leading-tight shadow-sm",
              "flex items-center justify-center px-1.5",
              "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] text-[var(--fg-secondary)]",
              pathState === "active" ? "border-[color-mix(in_srgb,var(--accent-cool)_40%,var(--vui-border-subtle))] text-[var(--accent-cool)]" : "",
              pathState === "attention" ? "border-[color-mix(in_srgb,var(--state-warning)_40%,var(--vui-border-subtle))] text-[var(--state-warning)]" : "",
              pathState === "danger" ? "border-[color-mix(in_srgb,var(--state-error)_40%,var(--vui-border-subtle))] text-[var(--state-error)]" : "",
            )}
            data-vui="workflow-edge-label"
            data-semantic={semanticKind}
            data-gate-kind={gateKind || undefined}
            data-path-state={pathState}
            title={labelFault ? undefined : label}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
          >
            {labelFault ? label : labelSpec.displayText}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
