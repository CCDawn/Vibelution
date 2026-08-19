/**
 * Workflow edge: renders the engine-owned ORTHOGONAL section geometry
 * (data.sections) until a manual visual node position is active. During that
 * local override it uses a small live orthogonal route from React Flow's
 * current endpoints; a smooth-step approximation is forbidden in production.
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
import { useSmartEdgePath } from "@tisoap/react-flow-smart-edge";
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
import {
  resolveWorkflowManualEdgeGeometry,
  workflowEdgeTerminalLead,
  type WorkflowEdgeTerminalSide,
} from "./workflowManualLayout";

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
  /** True once a manual visual position is active or a task is being dragged. */
  manualRouteActive?: boolean;
  /** Smart routing pauses during drag; the local terminal-safe path stays live. */
  manualDragging?: boolean;
};

export function WorkflowSemanticEdge({
  id,
  source,
  target,
  data,
  markerEnd,
  style,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
}: EdgeProps) {
  const [hovered, setHovered] = useState(false);
  const edgeData = data as WorkflowSemanticEdgeData | undefined;
  const semanticKind = edgeData?.semanticKind ?? "main";
  const pathState = edgeData?.pathState ?? "idle";
  const label = String(edgeData?.label ?? "");
  const always = Boolean(edgeData?.labelAlwaysVisible);
  const gateKind = String(edgeData?.gateKind ?? "");
  const stroke = resolveEdgeStroke(pathState, semanticKind);
  const sourceSide = sourcePosition as WorkflowEdgeTerminalSide;
  const targetSide = targetPosition as WorkflowEdgeTerminalSide;
  const smartWaypoints = useMemo(
    () => areFinite(sourceX, sourceY, targetX, targetY)
      ? [
          workflowEdgeTerminalLead({ x: sourceX, y: sourceY }, sourceSide),
          workflowEdgeTerminalLead({ x: targetX, y: targetY }, targetSide),
        ]
      : [],
    [sourceSide, sourceX, sourceY, targetSide, targetX, targetY],
  );
  const smartEdge = useSmartEdgePath({
    id,
    source,
    target,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    preset: "step",
    waypoints: smartWaypoints,
  });

  const sections = edgeData?.sections;
  const liveGeometry = useMemo(() => {
    if (!edgeData?.manualRouteActive || !areFinite(sourceX, sourceY, targetX, targetY)) {
      return null;
    }
    return resolveWorkflowManualEdgeGeometry(
      { x: sourceX, y: sourceY },
      { x: targetX, y: targetY },
      sourceSide,
      targetSide,
    );
  }, [edgeData?.manualRouteActive, sourceSide, sourceX, sourceY, targetSide, targetX, targetY]);
  const smartGeometry = edgeData?.manualRouteActive
    && !edgeData.manualDragging
    && smartEdge.route?.kind === "routed"
    ? {
        path: smartEdge.route.svgPathString,
        labelAnchor: { x: smartEdge.route.edgeCenterX, y: smartEdge.route.edgeCenterY },
      }
    : null;
  const manualGeometry = smartGeometry ?? liveGeometry;
  const edgePath = useMemo(
    () => manualGeometry?.path ?? sectionsToSvgPath(sections ?? []),
    [manualGeometry, sections],
  );
  const sectionFault = useMemo(
    () => (!manualGeometry && sections && sections.length > 0 ? !analyzeEdgeSections(sections).wellFormed : false),
    [manualGeometry, sections],
  );
  const labelAnchor = useMemo(
    () => manualGeometry?.labelAnchor ?? resolveEdgeLabelAnchor(edgeData?.labelBounds),
    [edgeData?.labelBounds, manualGeometry],
  );
  const labelFault = Boolean(label) && !manualGeometry && !edgeData?.labelBounds;
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
        data-manual-route={manualGeometry ? "true" : undefined}
        data-smart-route={smartGeometry ? "true" : undefined}
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
              backgroundColor: "var(--vui-surface-panel)",
              boxShadow: "0 0 0 3px var(--vui-surface-workspace)",
            }}
            className={cn(
              "truncate rounded-md border text-center text-[11px] font-medium leading-tight",
              "flex items-center justify-center px-1.5",
              "border-[var(--vui-border-subtle)] text-[var(--fg-secondary)]",
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

function areFinite(...values: number[]): boolean {
  return values.every((value) => Number.isFinite(value));
}
