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

/**
 * Emits a plain SVG path string from the engine sections.
 *
 * Walks the DIRECTED chain: starts at every section with no incoming links
 * and follows `outgoingSectionIds`. Geometrically joined sections (A.end ==
 * B.start) continue the same subpath with `L`; a chain break starts a new `M`
 * subpath so the renderer never draws a line the engine did not produce. The
 * result is ONE subpath per directed chain, so an arrow marker can only land
 * on the true final section of each chain, never mid-chain.
 */
export function sectionsToSvgPath(sections: WorkflowEdgeSection[]): string {
  if (sections.length === 0) {
    return "";
  }
  const byId = new Map(sections.map((s) => [s.id, s] as const));
  const visited = new Set<string>();
  const parts: string[] = [];

  // Emits one subpath starting at `start.id` and following the directed chain.
  // Joined sections continue with `L`; declared-but-broken links start a new
  // subpath at the next section (never a fabricated connector).
  const walkChain = (start: WorkflowEdgeSection) => {
    let current = start;
    let subpathOpen = false;
    while (current && !visited.has(current.id)) {
      if (!subpathOpen) {
        visited.add(current.id);
        parts.push(`M ${current.start.x} ${current.start.y}`);
        subpathOpen = true;
      }
      for (const bend of current.bendPoints) {
        parts.push(`L ${bend.x} ${bend.y}`);
      }
      parts.push(`L ${current.end.x} ${current.end.y}`);
      visited.add(current.id);
      const nextId = current.outgoingSectionIds.find(
        (id) => byId.has(id) && !visited.has(id),
      );
      if (!nextId) {
        break;
      }
      const next = byId.get(nextId)!;
      if (Math.abs(current.end.x - next.start.x) > GEOMETRY_TOLERANCE ||
          Math.abs(current.end.y - next.start.y) > GEOMETRY_TOLERANCE) {
        // Declared link but geometric break: close this subpath, open a new
        // one at the next section without inventing a connector.
        current = next;
        subpathOpen = false;
        continue;
      }
      current = next;
    }
  };

  // Entry points: sections without incoming links, in definition order.
  const starts = sections.filter((s) => s.incomingSectionIds.length === 0);
  for (const start of starts.length > 0 ? starts : sections) {
    walkChain(start);
  }
  return parts.join(" ");
}

export type WorkflowEdgeLabelAnchor = { x: number; y: number };

export type EdgeSectionDiagnostic = {
  /** True when every directed relation (A.end == B.start) is geometrically held. */
  continuous: boolean;
  /** True when the chain is a single path with no cycle/branch/orphan faults. */
  wellFormed: boolean;
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
 *
 * P1-3: also flags structural faults — cycles (a section reachable again),
 * branches (a section with >1 outgoing), and orphans (a section unreachable
 * from any entry point) — so a multi-section edge is verifiably a chain.
 */
export function analyzeEdgeSections(sections: WorkflowEdgeSection[]): EdgeSectionDiagnostic {
  const diagnostics: string[] = [];
  const byId = new Map(sections.map((s) => [s.id, s] as const));

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

  // 4. Structural faults: branches, cycles, orphans.
  const entryIds = new Set(
    sections.filter((s) => s.incomingSectionIds.length === 0).map((s) => s.id),
  );
  for (const section of sections) {
    if (section.outgoingSectionIds.length > 1) {
      diagnostics.push(
        `section "${section.id}" branches into ${section.outgoingSectionIds.length} outgoing sections ` +
          `(${section.outgoingSectionIds.join(", ")}) — a chain must be linear`,
      );
    }
    if (section.incomingSectionIds.length > 1) {
      diagnostics.push(
        `section "${section.id}" merges ${section.incomingSectionIds.length} incoming sections — ` +
          `a chain must be linear`,
      );
    }
  }

  // Cycle detection: DFS with recursion stack on the directed links.
  {
    const state = new Map<string, "visiting" | "done">();
    const visiting: string[] = [];
    const hasCycle = (id: string): boolean => {
      const current = state.get(id);
      if (current === "done") return false;
      if (current === "visiting") return true;
      state.set(id, "visiting");
      visiting.push(id);
      const section = byId.get(id);
      for (const nextId of section?.outgoingSectionIds ?? []) {
        if (byId.has(nextId) && hasCycle(nextId)) return true;
      }
      state.set(id, "done");
      return false;
    };
    for (const section of sections) {
      if (hasCycle(section.id)) {
        diagnostics.push(`section chain contains a cycle at "${section.id}"`);
        break;
      }
    }
  }

  // Orphans: sections unreachable from any entry point (excluding chains that
  // form their own cycle — already reported).
  if (sections.length > 0) {
    const reachable = new Set<string>();
    const stack = [...entryIds];
    while (stack.length > 0) {
      const id = stack.pop()!;
      if (reachable.has(id)) continue;
      reachable.add(id);
      const section = byId.get(id);
      for (const nextId of section?.outgoingSectionIds ?? []) {
        if (byId.has(nextId)) stack.push(nextId);
      }
    }
    for (const section of sections) {
      if (!reachable.has(section.id)) {
        diagnostics.push(
          `section "${section.id}" is orphaned (unreachable from any entry point)`,
        );
      }
    }
  }

  return {
    continuous: diagnostics.every((d) => !/joins at|unknown section/.test(d)),
    wellFormed: diagnostics.length === 0,
    diagnostics,
  };
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
