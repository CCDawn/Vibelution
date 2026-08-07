/**
 * Auto-layout orchestration for the workflow canvas (layout design §6, §7).
 *
 * - structural hash caching: identical topology + sizes reuse the cached
 *   layout (zero ELK calls); runtime-only field updates merge into the
 *   cached geometry without relayout;
 * - monotonic token: stale async layouts never overwrite newer ones;
 * - last-good: a failed layout keeps the last committed result and sets
 *   `degraded` (never silently falls back to fixed coordinates);
 * - engine lifecycle: created once per canvas mount (StrictMode-safe:
 *   cleanup terminates the previous engine, remount creates a fresh one);
 * - fit protocol: `initialFitRevision` is set exactly once after the first
 *   layout commits; the canvas fits and calls `acknowledgeInitialFit()`.
 *   Topology updates do not auto-fit; `fitAll()` serves explicit controls;
 * - size calibration (D3): measured sizes trigger at most one relayout per
 *   structure, then converge on the accepted measurement.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  WorkflowLayoutInput,
  WorkflowLayoutNode,
  WorkflowLayoutResult,
} from "../../../product/workflow/workflowCanvasTypes";
import { analyzeEdgeSections } from "./workflowElkEdgePath";
import { DECISION_OUTCOME_IDS } from "./workflowElkPorts";
import type { WorkflowLayoutEngine } from "./workflowElkClient";
import { layoutTwoLevel } from "./workflowTwoLevelLayout";
import { isLayoutSettled } from "./workflowLayoutSettling";
import {
  structuralWorkflowLayoutHash,
  type WorkflowLayoutHash,
  type WorkflowNodeSize,
} from "./workflowLayoutHash";

export type UseWorkflowAutoLayoutResult = {
  nodes: WorkflowLayoutNode[];
  edges: WorkflowLayoutResult["edges"];
  /** Bumped once per committed layout; unchanged by runtime-only updates. */
  layoutRevision: number;
  /** null while healthy; non-null with a diagnostic reason when degraded. */
  degraded: { reason: string } | null;
  /** Set once to the first committed revision; consumed by the canvas. */
  initialFitRevision: number | null;
  /**
   * Structural identity (topology hash). Unchanged by runtime-only updates
   * and by size calibration; changes when the run topology switches. Used by
   * the initial-fit hook to tell "same structure, calibration bump" apart
   * from "new topology committed" (P1-1 race).
   */
  structureKey: string;
  acknowledgeInitialFit: () => void;
  /** Explicit fit-all action for WorkflowCanvasControls. */
  fitAll: () => void;
  /** D3 calibration: report measured node sizes (at most one relayout). */
  reportMeasuredSize: (nodeId: string, size: WorkflowNodeSize) => void;
};

type CacheEntry = {
  hash: WorkflowLayoutHash;
  nodes: WorkflowLayoutNode[];
  edges: WorkflowLayoutResult["edges"];
};

function designHeight(visualKind: string): number {
  return visualKind === "decision" ? 112 : 88;
}

export function useWorkflowAutoLayout(
  graph: WorkflowLayoutInput,
  createEngine: () => WorkflowLayoutEngine,
  options: { fitAll?: () => void } = {},
): UseWorkflowAutoLayoutResult {
  const [engine, setEngine] = useState<WorkflowLayoutEngine | null>(null);
  const [layoutRevision, setLayoutRevision] = useState(0);
  const [degraded, setDegraded] = useState<{ reason: string } | null>(null);
  const [initialFitRevision, setInitialFitRevision] = useState<number | null>(null);
  const [display, setDisplay] = useState<{ nodes: WorkflowLayoutNode[]; edges: WorkflowLayoutResult["edges"] }>({
    nodes: [],
    edges: [],
  });

  const revisionRef = useRef(0);
  const tokenRef = useRef(0);
  const calibrationUsedRef = useRef(false);
  const cacheRef = useRef<CacheEntry | null>(null);
  const sizesRef = useRef<Map<string, WorkflowNodeSize>>(new Map());
  const settlingRef = useRef<"design" | "calibration" | "settled">("design");
  const [sizesTick, setSizesTick] = useState(0);
  const graphRef = useRef(graph);
  graphRef.current = graph;

  useEffect(() => {
    const created = createEngine();
    setEngine(created);
    return () => {
      tokenRef.current += 1;
      created.terminate();
    };
    // createEngine is expected to be referentially stable per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hash = useMemo(
    () => structuralWorkflowLayoutHash(graph, sizesRef.current),
    [graph, sizesTick],
  );

  useEffect(() => {
    if (!engine) {
      return;
    }
    const cache = cacheRef.current;
    if (cache && cache.hash.full === hash.full) {
      setDisplay(mergeRuntimeFields(cache, graph));
      return;
    }
    const structuralChange = !cache || cache.hash.structure !== hash.structure;
    if (!structuralChange && calibrationUsedRef.current) {
      // Calibration budget already spent: accept the measured sizes as the
      // new fact without rerunning ELK, so the hash converges.
      cacheRef.current = { ...cache!, hash };
      setDisplay(mergeRuntimeFields(cacheRef.current, graph));
      return;
    }

    const token = ++tokenRef.current;
    let cancelled = false;
    const input = graphRef.current;
    // Measured DOM sizes (P1-5) feed the ELK graph so the calibration pass
    // lays out with real geometry, not the design-contract defaults again.
    runLayout(input, engine, sizesRef.current)
      .then((result) => {
        if (cancelled || token !== tokenRef.current) {
          return;
        }
        // Diagnose BEFORE committing anything: a faulty layout (label without
        // bounds, broken section chain) must NOT overwrite the last-good
        // revision/cache/display — only the degraded flag changes.
        const diagnostic = layoutDiagnostic(result);
        if (diagnostic) {
          setDegraded(diagnostic);
          if (cache) {
            setDisplay(mergeRuntimeFields(cache, graph));
          }
          return;
        }
        const previousRevision = revisionRef.current;
        const nextRevision = previousRevision + 1;
        revisionRef.current = nextRevision;
        setLayoutRevision(nextRevision);
        // Settling protocol: the initial fit may only arm on the SETTLED
        // revision. A design/calibration layout that still disagrees with the
        // measured content sizes must NOT arm the fit — the calibration
        // relayout that follows may change the viewport bounds.
        const settled = isLayoutSettled(result.nodes, sizesRef.current, settlingRef.current);
        settlingRef.current = settled ? "settled" : settlingRef.current === "settled" ? "settled" : "design";
        if (previousRevision === 0 && settled) {
          setInitialFitRevision(nextRevision);
        }
        calibrationUsedRef.current = structuralChange ? false : true;
        cacheRef.current = {
          hash,
          nodes: result.nodes,
          edges: result.edges,
        };
        setDegraded(null);
        setDisplay(mergeRuntimeFields(cacheRef.current, input));
      })
      .catch((error: unknown) => {
        if (cancelled || token !== tokenRef.current) {
          return;
        }
        setDegraded({ reason: error instanceof Error ? error.message : String(error) });
        if (cache) {
          setDisplay(mergeRuntimeFields(cache, graph));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [engine, hash, graph]);

  const reportMeasuredSize = useCallback((nodeId: string, size: WorkflowNodeSize) => {
    const previous = sizesRef.current.get(nodeId);
    if (previous && previous.width === size.width && previous.height === size.height) {
      return;
    }
    sizesRef.current.set(nodeId, size);
    setSizesTick((tick) => tick + 1);
  }, []);

  const acknowledgeInitialFit = useCallback(() => {
    setInitialFitRevision(null);
  }, []);

  const fitAll = useCallback(() => {
    options.fitAll?.();
  }, [options.fitAll]);

  return {
    nodes: display.nodes,
    edges: display.edges,
    layoutRevision,
    degraded,
    initialFitRevision,
    structureKey: hash.structure,
    acknowledgeInitialFit,
    fitAll,
    reportMeasuredSize,
  };
}

async function runLayout(
  input: WorkflowLayoutInput,
  engine: WorkflowLayoutEngine,
  sizes?: ReadonlyMap<string, WorkflowNodeSize>,
): Promise<WorkflowLayoutResult> {
  // Two-level layout: per-stage DOWN + deterministic meta row + gateway
  // cross-stage routing (architecture replaces the single compound graph).
  return layoutTwoLevel(input, engine, sizes);
}

/**
 * P1-5: engine-output diagnostics that must NOT be silently absorbed. A label
 * without engine labelBounds, or a section chain that is not well-formed
 * (cycle/branch/orphan/broken link), degrades the canvas with a reason while
 * the last-good layout keeps rendering.
 *
 * @internal exported for tests; not part of the hook's public surface.
 */
export function layoutDiagnostic(result: WorkflowLayoutResult): { reason: string } | null {
  for (const edge of result.edges) {
    if (edge.label.length > 0 && !edge.labelBounds) {
      return {
        reason: `edge "${edge.id}" has a label but the engine did not place label bounds`,
      };
    }
    if (edge.sections.length > 0 && !analyzeEdgeSections(edge.sections).wellFormed) {
      return {
        reason: `edge "${edge.id}" section chain is not well-formed`,
      };
    }
  }
  return null;
}

/**
 * Merges the latest runtime-only fields (status, pathState, labels, tone,
 * handles) into cached layout geometry. Geometry (positions/sections) stays
 * from the last committed ELK run; everything displayed can refresh without
 * a second layout.
 */
export function mergeRuntimeFields(
  layout: { nodes: WorkflowLayoutNode[]; edges: WorkflowLayoutResult["edges"] },
  input: WorkflowLayoutInput,
): { nodes: WorkflowLayoutNode[]; edges: WorkflowLayoutResult["edges"] } {
  const nodeById = new Map(input.nodes.map((n) => [n.nodeId, n] as const));
  const edgeById = new Map(input.edges.map((e) => [e.edgeId, e] as const));
  const stageById = new Map(input.stages.map((s) => [s.stageId, s] as const));

  const nodes = layout.nodes.map((node) => {
    const live = nodeById.get(node.id);
    if (!live) {
      return node;
    }
    const sourceHandleIds = input.edges
      .filter((edge) => edge.fromNodeId === node.id && edge.sourceHandle)
      .map((edge) => edge.sourceHandle as string);
    return {
      ...node,
      status: live.status,
      attempt: live.attempt,
      isRuntimeCurrent: live.isRuntimeCurrent,
      hasPendingHumanTask: live.hasPendingHumanTask,
      blockedReason: live.blockedReason,
      description: live.description,
      primaryRoleKey: live.primaryRoleKey,
      sourceHandleIds: sourceHandleIds.length > 0 ? sourceHandleIds : undefined,
      decisionOutcomeIds:
        node.visualKind === "decision" ? [...DECISION_OUTCOME_IDS] : undefined,
    } satisfies WorkflowLayoutNode;
  }).map((node) => {
    if (node.kind !== "stage") {
      return node;
    }
    const tone = stageById.get(node.stageId)?.stageTone;
    return tone ? { ...node, stageTone: tone } : node;
  });

  const edges = layout.edges.map((edge) => {
    const live = edgeById.get(edge.id);
    if (!live) {
      return edge;
    }
    return {
      ...edge,
      label: live.label,
      pathState: live.pathState,
      labelAlwaysVisible: live.labelAlwaysVisible,
      sourceHandle: live.sourceHandle ?? edge.sourceHandle,
      gateKind: live.gateKind,
      requiresHumanAccept: live.requiresHumanAccept,
    };
  });

  return { nodes, edges };
}

export { designHeight };
