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
 *
 * P1-3: `analyzeEdgeSections` parses the DIRECTED chain (incoming/outgoing
 * section ids) and diagnoses broken links — claimed joins that do not hold
 * geometrically, unknown ids, or asymmetric declarations — so layout faults
 * fail fast instead of being absorbed into a visually broken path.
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

export type EdgeSectionDiagnostic = {
  /** True when every directed relation (A.end == B.start) is geometrically held. */
  continuous: boolean;
  /** Human-readable diagnostics for any violated directed link. */
  diagnostics: string[];
};

const GEOMETRY_TOLERANCE = 1e-3;

/**
 * Parses the DIRECTED section chain of one edge and diagnoses continuity.
 *
 * Each section declares its neighbours through `incomingSectionIds` /
 * `outgoingSectionIds`; a valid chain requires the shared endpoint to coincide
 * geometrically (A.end == B.start, within tolerance). Anything else is a real
 * layout fault that would produce a visible corner/gap in the rendered path —
 * not something `sectionsToSvgPath` should silently absorb. The renderer keeps
 * rendering engine geometry as-is; this analysis exists so tests and tooling
 * can fail fast on broken chains.
 */
export function analyzeEdgeSections(sections: WorkflowEdgeSection[]): EdgeSectionDiagnostic {
  const diagnostics: string[] = [];
  const byId = new Map(sections.map((s) => [s.id, s] as const));

  const pointKey = (p: { x: number; y: number }) => `${p.x},${p.y}`;
  const pointsEqual = (a: { x: number; y: number }, b: { x: number; y: number }) =>
    Math.abs(a.x - b.x) <= GEOMETRY_TOLERANCE && Math.abs(a.y - b.y) <= GEOMETRY_TOLERANCE;

  // 1. Unknown ids referenced by the directed links.
  for (const section of sections) {
    for (const id of [...section.incomingSectionIds, ...section.outgoingSectionIds]) {
      if (!byId.has(id)) {
        diagnostics.push(
          `section "${section.id}" references unknown section "${id}"`,
        );
      }
    }
  }

  // 2. Every directed A -> B link must join geometrically (A.end == B.start).
  for (const section of sections) {
    for (const nextId of section.outgoingSectionIds) {
      const next = byId.get(nextId);
      if (!next) continue;
      if (!pointsEqual(section.end, next.start)) {
        diagnostics.push(
          `section "${section.id}" -> "${nextId}" joins at (${section.end.x},${section.end.y}) but ` +
            `"${nextId}" starts at (${next.start.x},${next.start.y})`,
        );
      }
    }
    for (const prevId of section.incomingSectionIds) {
      const prev = byId.get(prevId);
      if (!prev) continue;
      if (!pointsEqual(prev.end, section.start)) {
        diagnostics.push(
          `section "${prevId}" -> "${section.id}" joins at (${prev.end.x},${prev.end.y}) but ` +
            `"${section.id}" starts at (${section.start.x},${section.start.y})`,
        );
      }
    }
  }

  // 3. Symmetric declaration: B lists A as incoming iff A lists B as outgoing.
  for (const section of sections) {
    for (const nextId of section.outgoingSectionIds) {
      const next = byId.get(nextId);
      if (next && !next.incomingSectionIds.includes(section.id)) {
        diagnostics.push(
          `section "${section.id}" -> "${nextId}" is declared but "${nextId}" ` +
            `does not list "${section.id}" as incoming`,
        );
      }
    }
  }

  return { continuous: diagnostics.length === 0, diagnostics };
}

/**
 * Label anchor for the work item. Engine-owned `labelBounds` is the ONLY
 * authority (center of the engine-placed label); without it the edge has no
 * label anchor — no geometry-derived estimation is ever performed. Returns
 * `null` when the engine did not place a label (empty/auto-hidden edges).
 */
export function resolveEdgeLabelAnchor(
  labelBounds?: WorkflowLabelBounds,
): WorkflowEdgeLabelAnchor | null {
  if (!labelBounds) {
    return null;
  }
  return {
    x: labelBounds.x + labelBounds.width / 2,
    y: labelBounds.y + labelBounds.height / 2,
  };
}
