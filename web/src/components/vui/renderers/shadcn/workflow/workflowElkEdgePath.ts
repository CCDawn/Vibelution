/**
 * SVG path builder for engine-owned workflow edge geometry (T3).
 *
 * ELK already routes each edge into one or more ORTHOGONAL sections
 * (`WorkflowEdgeSection[]`). This module emits a plain SVG path string from
 * those sections so the canvas renders the engine's real geometry instead of
 * a re-routed smooth-step approximation.
 *
 * Contract:
 * - every vertex of the output path comes from a section start/end/bend point;
 * - consecutive sections are joined with `M` (move) when their endpoints do not
 *   coincide, so no fake connector segment is invented between sections — the
 *   renderer never draws a line the engine did not produce;
 * - coordinate space: sections are already normalized to absolute canvas space
 *   (root edges and stage-local edges unified by `fromElkLayout`).
 */
import type {
  WorkflowEdgeSection,
  WorkflowLabelBounds,
} from "../../../product/workflow/workflowCanvasTypes";

export function sectionsToSvgPath(sections: WorkflowEdgeSection[]): string {
  if (sections.length === 0) {
    return "";
  }
  const parts: string[] = [];
  for (const section of sections) {
    parts.push(`M ${section.start.x} ${section.start.y}`);
    for (const bend of section.bendPoints) {
      parts.push(`L ${bend.x} ${bend.y}`);
    }
    parts.push(`L ${section.end.x} ${section.end.y}`);
  }
  return parts.join(" ");
}

export type WorkflowEdgeLabelAnchor = { x: number; y: number };

/**
 * Label anchor for the work item. Engine-owned `labelBounds` win (centered);
 * otherwise falls back to the midpoint of the first section so the label keeps
 * a stable, geometry-derived anchor. Always returns a finite point or `null`
 * when there is no geometry to anchor to.
 */
export function resolveEdgeLabelAnchor(
  sections: WorkflowEdgeSection[],
  labelBounds?: WorkflowLabelBounds,
): WorkflowEdgeLabelAnchor | null {
  if (labelBounds) {
    return {
      x: labelBounds.x + labelBounds.width / 2,
      y: labelBounds.y + labelBounds.height / 2,
    };
  }
  if (sections.length === 0) {
    return null;
  }
  const first = sections[0];
  if (!first) {
    return null;
  }
  return {
    x: (first.start.x + first.end.x) / 2,
    y: (first.start.y + first.end.y) / 2,
  };
}
