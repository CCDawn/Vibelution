/**
 * Auto-layout orchestration for the workflow canvas (layout design §6, §7).
 *
 * - structural hash caching: identical topology + sizes reuse the cached
 *   layout (zero ELK calls); runtime-only field updates merge into the
 *   cached geometry without relayout;
 * - monotonic token: stale async layouts never overwrite newer ones;
 * - recovery: a failed layout keeps the same-scope last-good result when
 *   available, otherwise it keeps deterministic graph-derived geometry and
 *   sets `degraded` without dropping business nodes;
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
  workflowEdgeKeepsNarrativeLabel,
  type WorkflowCanvasLayoutMode,
  workflowNodeDesignSize,
} from "./workflowElkOptions";
import { resolveEdgeLabelSpec } from "./workflowEdgeLabelGeometry";
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

type DisplayEntry = {
  layout: { nodes: WorkflowLayoutNode[]; edges: WorkflowLayoutResult["edges"] };
  /** Structure scope that produced this display geometry; null is fallback. */
  structure: string | null;
};

/**
 * ELK is an enhancement, not the source of truth for whether business nodes
 * exist. The fallback is intentionally short-lived presentation geometry:
 * it is derived from the graph input, carries no business mutations, and is
 * replaced by a committed ELK result when the worker responds.
 */
export const WORKFLOW_LAYOUT_RECOVERY_TIMEOUT_MS = 3_000;
const FALLBACK_STAGE_GAP = 96;
const FALLBACK_TASK_GAP = 24;
const FALLBACK_STAGE_PADDING_X = 32;
const FALLBACK_STAGE_PADDING_TOP = 56;
const FALLBACK_STAGE_PADDING_BOTTOM = 28;
const FALLBACK_MIN_STAGE_WIDTH = 320;
const FALLBACK_MIN_STAGE_HEIGHT = 128;

function designHeight(visualKind: string): number {
  return visualKind === "decision" ? 112 : 88;
}

export function useWorkflowAutoLayout(
  graph: WorkflowLayoutInput,
  createEngine: () => WorkflowLayoutEngine,
  options: { fitAll?: () => void; layoutMode?: WorkflowCanvasLayoutMode } = {},
): UseWorkflowAutoLayoutResult {
  const layoutMode = options.layoutMode ?? "stage-columns";
  const [engine, setEngine] = useState<WorkflowLayoutEngine | null>(null);
  const [layoutRevision, setLayoutRevision] = useState(0);
  const [degraded, setDegraded] = useState<{ reason: string } | null>(null);
  const [initialFitRevision, setInitialFitRevision] = useState<number | null>(null);
  const fallback = useMemo(
    () => createDeterministicWorkflowLayout(graph, layoutMode),
    [graph, layoutMode],
  );
  const [display, setDisplay] = useState<DisplayEntry>({ layout: fallback, structure: null });

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

  const hash = useMemo(() => {
    const graphHash = structuralWorkflowLayoutHash(graph, sizesRef.current);
    return {
      ...graphHash,
      structure: `${graphHash.structure}|layout:${layoutMode}`,
      full: `${graphHash.full}|layout:${layoutMode}`,
    };
  }, [graph, layoutMode, sizesTick]);

  useEffect(() => {
    if (!engine) {
      return;
    }
    const cache = cacheRef.current;
    if (cache && cache.hash.full === hash.full) {
      setDisplay({
        layout: mergeRuntimeFields(cache, graph, layoutMode),
        structure: hash.structure,
      });
      return;
    }
    const structuralChange = !cache || cache.hash.structure !== hash.structure;
    if (!structuralChange && calibrationUsedRef.current) {
      // Calibration budget already spent: accept the measured sizes as the
      // new fact without rerunning ELK, so the hash converges.
      cacheRef.current = { ...cache!, hash };
      setDisplay({
        layout: mergeRuntimeFields(cacheRef.current, graph, layoutMode),
        structure: hash.structure,
      });
      return;
    }

    const token = ++tokenRef.current;
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const recover = () => resolveWorkflowLayoutRecovery(cache, hash, graph, layoutMode, fallback);
    if (graph.nodes.length > 0) {
      timeoutId = setTimeout(() => {
        if (cancelled || token !== tokenRef.current) {
          return;
        }
        setDegraded({
          reason: `layout engine timed out after ${WORKFLOW_LAYOUT_RECOVERY_TIMEOUT_MS}ms; showing deterministic fallback`,
        });
        setDisplay({ layout: recover(), structure: hash.structure });
      }, WORKFLOW_LAYOUT_RECOVERY_TIMEOUT_MS);
    }
    // A new topology starts a fresh recovery window. A previous error must
    // not mask the current graph while its replacement geometry is pending.
    setDegraded(null);
    const input = graphRef.current;
    // Measured DOM sizes (P1-5) feed the ELK graph so the calibration pass
    // lays out with real geometry, not the design-contract defaults again.
    runLayout(input, engine, sizesRef.current, layoutMode)
      .then((result) => {
        if (cancelled || token !== tokenRef.current) {
          return;
        }
        // Diagnose BEFORE committing anything: a faulty layout (bad geometry,
        // label without bounds, broken section chain) must NOT overwrite the
        // scoped last-good revision/cache/display — only degraded changes.
        if (timeoutId !== null) {
          clearTimeout(timeoutId);
          timeoutId = null;
        }
        const diagnostic = layoutDiagnostic(result, input);
        if (diagnostic) {
          setDegraded(diagnostic);
          setDisplay({ layout: recover(), structure: hash.structure });
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
        setDisplay({
          layout: mergeRuntimeFields(cacheRef.current, input, layoutMode),
          structure: hash.structure,
        });
      })
      .catch((error: unknown) => {
        if (cancelled || token !== tokenRef.current) {
          return;
        }
        if (timeoutId !== null) {
          clearTimeout(timeoutId);
          timeoutId = null;
        }
        setDegraded({ reason: error instanceof Error ? error.message : String(error) });
        setDisplay({ layout: recover(), structure: hash.structure });
      });
    return () => {
      cancelled = true;
      if (timeoutId !== null) {
        clearTimeout(timeoutId);
      }
    };
  }, [engine, fallback, hash, graph, layoutMode]);

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

  const visible = useMemo(() => {
    const cache = cacheRef.current;
    if (cache && cache.hash.structure === hash.structure && layoutMatchesGraph(cache, graph)) {
      return mergeRuntimeFields(cache, graph, layoutMode);
    }
    if (display.structure === hash.structure && layoutMatchesGraph(display.layout, graph)) {
      return mergeRuntimeFields(display.layout, graph, layoutMode);
    }
    // `display` can belong to the previous topology during the render that
    // observes a graph change. Never treat matching node ids alone as proof
    // that its geometry is in the current structure scope.
    return fallback;
  }, [display, fallback, graph, hash.structure, layoutMode]);

  return {
    nodes: visible.nodes,
    edges: visible.edges,
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
  layoutMode: WorkflowCanvasLayoutMode = "stage-columns",
): Promise<WorkflowLayoutResult> {
  // Two-level layout: per-stage DOWN + deterministic meta row + gateway
  // cross-stage routing (architecture replaces the single compound graph).
  return layoutTwoLevel(input, engine, sizes, { layoutMode });
}

/**
 * P1-5: engine-output diagnostics that must NOT be silently absorbed. A label
 * without engine labelBounds, or a section chain that is not well-formed
 * (cycle/branch/orphan/broken link), degrades the canvas with a reason while
 * the last-good layout keeps rendering.
 *
 * @internal exported for tests; not part of the hook's public surface.
 */
export function layoutDiagnostic(
  result: WorkflowLayoutResult,
  input?: WorkflowLayoutInput,
): { reason: string } | null {
  if (!Number.isFinite(result.width) || !Number.isFinite(result.height)) {
    return { reason: "layout result has non-finite canvas bounds" };
  }
  for (const node of result.nodes) {
    if (![node.x, node.y, node.width, node.height].every(Number.isFinite)) {
      return { reason: `node "${node.id}" has non-finite geometry` };
    }
    if (node.width <= 0 || node.height <= 0) {
      return { reason: `node "${node.id}" has invalid geometry bounds` };
    }
  }
  if (input && !layoutMatchesBusinessNodes(result, input)) {
    return { reason: "layout result omitted or changed business nodes" };
  }
  if (input && !layoutMatchesBusinessEdges(result, input)) {
    return { reason: "layout result omitted or changed business edges" };
  }
  for (const edge of result.edges) {
    for (const section of edge.sections) {
      if (
        ![section.start.x, section.start.y, section.end.x, section.end.y].every(Number.isFinite)
        || section.bendPoints.some((point) => ![point.x, point.y].every(Number.isFinite))
      ) {
        return { reason: `edge "${edge.id}" has non-finite geometry` };
      }
    }
    if (
      edge.labelBounds
      && ![
        edge.labelBounds.x,
        edge.labelBounds.y,
        edge.labelBounds.width,
        edge.labelBounds.height,
      ].every(Number.isFinite)
    ) {
      return { reason: `edge "${edge.id}" has non-finite label geometry` };
    }
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
  layoutMode: WorkflowCanvasLayoutMode = "stage-columns",
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
      knowledgeBadge: live.knowledgeBadge,
      description: live.description,
      primaryRoleKey: live.primaryRoleKey,
      primaryAgentId: live.primaryAgentId,
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
      label:
        layoutMode === "serpentine" && !workflowEdgeKeepsNarrativeLabel(live)
          ? ""
          : live.label,
      pathState: live.pathState,
      labelAlwaysVisible: live.labelAlwaysVisible,
      sourceHandle: live.sourceHandle ?? edge.sourceHandle,
      gateKind: live.gateKind,
      requiresHumanAccept: live.requiresHumanAccept,
    };
  });

  return { nodes, edges };
}

/**
 * Creates finite, stable presentation geometry directly from the graph. This
 * deliberately does not infer stage membership from coordinates: task
 * `stageId` stays exactly as supplied by the business projection, while
 * `stages[].nodeIds` only determines deterministic display order.
 */
export function createDeterministicWorkflowLayout(
  input: WorkflowLayoutInput,
  layoutMode: WorkflowCanvasLayoutMode = "stage-columns",
): WorkflowLayoutResult {
  const nodeById = new Map<string, WorkflowLayoutInput["nodes"][number]>();
  for (const node of input.nodes) {
    if (!nodeById.has(node.nodeId)) nodeById.set(node.nodeId, node);
  }
  const placedIds = new Set<string>();
  const positions = new Map<string, { x: number; y: number; width: number; height: number }>();
  const nodes: WorkflowLayoutNode[] = [];
  const isSerpentine = layoutMode === "serpentine";
  let stageCursorX = 0;
  let stageCursorY = 0;

  for (const [stageIndex, stage] of input.stages.entries()) {
    const stageTasks = orderedStageNodes(stage, input.nodes, nodeById, placedIds);
    const sizes = stageTasks.map((node) => workflowNodeDesignSize(layoutMode, node.visualKind));
    const taskWidth = sizes.reduce((total, size) => total + size.width, 0)
      + Math.max(0, sizes.length - 1) * FALLBACK_TASK_GAP;
    const taskHeight = sizes.reduce((total, size) => total + size.height, 0)
      + Math.max(0, sizes.length - 1) * FALLBACK_TASK_GAP;
    const maxTaskWidth = sizes.reduce((max, size) => Math.max(max, size.width), 0);
    const maxTaskHeight = sizes.reduce((max, size) => Math.max(max, size.height), 0);
    const stageWidth = Math.max(
      FALLBACK_MIN_STAGE_WIDTH,
      FALLBACK_STAGE_PADDING_X * 2 + (isSerpentine ? taskWidth : maxTaskWidth),
    );
    const stageHeight = Math.max(
      FALLBACK_MIN_STAGE_HEIGHT,
      FALLBACK_STAGE_PADDING_TOP
        + (isSerpentine ? maxTaskHeight : taskHeight)
        + FALLBACK_STAGE_PADDING_BOTTOM,
    );
    const stageX = isSerpentine ? 0 : stageCursorX;
    const stageY = isSerpentine ? stageCursorY : 0;
    nodes.push({
      id: `stage:${stage.stageId}`,
      stageId: stage.stageId,
      label: stage.label,
      actorKind: "system",
      visualKind: "stage_region",
      kind: "stage",
      x: stageX,
      y: stageY,
      width: stageWidth,
      height: stageHeight,
      stageTone: stage.stageTone,
    });

    let taskOffset = 0;
    for (const [taskIndex, task] of stageTasks.entries()) {
      const size = sizes[taskIndex]!;
      const x = isSerpentine && stageIndex % 2 === 1
        ? stageX + stageWidth - FALLBACK_STAGE_PADDING_X - taskOffset - size.width
        : stageX + FALLBACK_STAGE_PADDING_X + taskOffset;
      const y = isSerpentine
        ? stageY + FALLBACK_STAGE_PADDING_TOP
        : stageY + FALLBACK_STAGE_PADDING_TOP + taskOffset;
      const layoutNode: WorkflowLayoutNode = {
        id: task.nodeId,
        stageId: task.stageId,
        label: task.label,
        actorKind: task.actorKind,
        visualKind: task.visualKind,
        kind: "task",
        x,
        y,
        width: size.width,
        height: size.height,
        parentStageId: `stage:${stage.stageId}`,
        relativeX: x - stageX,
        relativeY: y - stageY,
        status: task.status,
        attempt: task.attempt,
        primaryAgentId: task.primaryAgentId,
        isRuntimeCurrent: task.isRuntimeCurrent,
        hasPendingHumanTask: task.hasPendingHumanTask,
        blockedReason: task.blockedReason,
        knowledgeBadge: task.knowledgeBadge,
        description: task.description,
        primaryRoleKey: task.primaryRoleKey,
        sourceHandleIds: uniqueSourceHandleIds(task.nodeId, input),
        decisionOutcomeIds: task.visualKind === "decision" ? [...DECISION_OUTCOME_IDS] : undefined,
      };
      nodes.push(layoutNode);
      positions.set(task.nodeId, { x, y, width: size.width, height: size.height });
      placedIds.add(task.nodeId);
      taskOffset += (isSerpentine ? size.width : size.height) + FALLBACK_TASK_GAP;
    }

    if (isSerpentine) {
      stageCursorY += stageHeight + FALLBACK_STAGE_GAP;
    } else {
      stageCursorX += stageWidth + FALLBACK_STAGE_GAP;
    }
  }

  // Keep malformed/in-progress projections visible too, without fabricating
  // a stage or rewriting their declared `stageId`.
  let orphanIndex = 0;
  for (const task of input.nodes) {
    if (placedIds.has(task.nodeId)) continue;
    const size = workflowNodeDesignSize(layoutMode, task.visualKind);
    const x = isSerpentine ? FALLBACK_STAGE_PADDING_X : stageCursorX + FALLBACK_STAGE_PADDING_X;
    const y = isSerpentine
      ? stageCursorY + FALLBACK_STAGE_PADDING_TOP + orphanIndex * (size.height + FALLBACK_TASK_GAP)
      : FALLBACK_STAGE_PADDING_TOP + orphanIndex * (size.height + FALLBACK_TASK_GAP);
    nodes.push({
      id: task.nodeId,
      stageId: task.stageId,
      label: task.label,
      actorKind: task.actorKind,
      visualKind: task.visualKind,
      kind: "task",
      x,
      y,
      width: size.width,
      height: size.height,
      status: task.status,
      attempt: task.attempt,
      primaryAgentId: task.primaryAgentId,
      isRuntimeCurrent: task.isRuntimeCurrent,
      hasPendingHumanTask: task.hasPendingHumanTask,
      blockedReason: task.blockedReason,
      knowledgeBadge: task.knowledgeBadge,
      description: task.description,
      primaryRoleKey: task.primaryRoleKey,
      sourceHandleIds: uniqueSourceHandleIds(task.nodeId, input),
      decisionOutcomeIds: task.visualKind === "decision" ? [...DECISION_OUTCOME_IDS] : undefined,
    });
    positions.set(task.nodeId, { x, y, width: size.width, height: size.height });
    orphanIndex += 1;
  }

  const edges = input.edges.map((edge) => {
    const source = positions.get(edge.fromNodeId);
    const target = positions.get(edge.toNodeId);
    const sections = source && target
      ? fallbackEdgeSections(edge.edgeId, source, target)
      : [];
    const label = isSerpentine && !workflowEdgeKeepsNarrativeLabel(edge) ? "" : edge.label;
    const labelSpec = resolveEdgeLabelSpec(label);
    const labelAnchor = source && target
      ? midpointOf(source, target)
      : null;
    return {
      id: edge.edgeId,
      source: edge.fromNodeId,
      target: edge.toNodeId,
      label,
      semanticKind: edge.semanticKind,
      pathState: edge.pathState,
      labelAlwaysVisible: edge.labelAlwaysVisible,
      sourceHandle: edge.sourceHandle,
      gateKind: edge.gateKind,
      requiresHumanAccept: edge.requiresHumanAccept,
      sections,
      labelBounds: labelAnchor
        ? {
            x: labelAnchor.x - labelSpec.width / 2,
            y: labelAnchor.y - labelSpec.height / 2,
            width: labelSpec.width,
            height: labelSpec.height,
          }
        : undefined,
    };
  });

  const width = nodes.reduce((max, node) => Math.max(max, node.x + node.width), 0);
  const height = nodes.reduce((max, node) => Math.max(max, node.y + node.height), 0);
  return { nodes, edges, width, height };
}

function orderedStageNodes(
  stage: WorkflowLayoutInput["stages"][number],
  inputNodes: WorkflowLayoutInput["nodes"],
  nodeById: Map<string, WorkflowLayoutInput["nodes"][number]>,
  placedIds: Set<string>,
): WorkflowLayoutInput["nodes"] {
  const ordered: WorkflowLayoutInput["nodes"] = [];
  for (const nodeId of stage.nodeIds) {
    const node = nodeById.get(nodeId);
    if (node && !placedIds.has(node.nodeId)) ordered.push(node);
  }
  for (const node of inputNodes) {
    if (node.stageId === stage.stageId && !placedIds.has(node.nodeId) && !ordered.some((item) => item.nodeId === node.nodeId)) {
      ordered.push(node);
    }
  }
  return ordered;
}

function uniqueSourceHandleIds(nodeId: string, input: WorkflowLayoutInput): string[] | undefined {
  const handles = input.edges
    .filter((edge) => edge.fromNodeId === nodeId && edge.sourceHandle)
    .map((edge) => edge.sourceHandle as string)
    .filter((handle, index, all) => all.indexOf(handle) === index);
  return handles.length > 0 ? handles : undefined;
}

function midpointOf(
  source: { x: number; y: number; width: number; height: number },
  target: { x: number; y: number; width: number; height: number },
): { x: number; y: number } {
  return {
    x: (source.x + source.width + target.x) / 2,
    y: (source.y + source.height / 2 + target.y + target.height / 2) / 2,
  };
}

function fallbackEdgeSections(
  edgeId: string,
  source: { x: number; y: number; width: number; height: number },
  target: { x: number; y: number; width: number; height: number },
): WorkflowLayoutResult["edges"][number]["sections"] {
  const start = { x: source.x + source.width, y: source.y + source.height / 2 };
  const end = { x: target.x, y: target.y + target.height / 2 };
  const middleX = start.x + (end.x - start.x) / 2;
  const points = [
    start,
    { x: middleX, y: start.y },
    { x: middleX, y: end.y },
    end,
  ].filter((point, index, all) => index === 0 || point.x !== all[index - 1]!.x || point.y !== all[index - 1]!.y);
  return points.slice(0, -1).map((point, index) => ({
    id: `${edgeId}_fallback_${index}`,
    start: point,
    end: points[index + 1]!,
    bendPoints: [],
    incomingSectionIds: index > 0 ? [`${edgeId}_fallback_${index - 1}`] : [],
    outgoingSectionIds: index + 1 < points.length - 1 ? [`${edgeId}_fallback_${index + 1}`] : [],
  }));
}

function layoutMatchesGraph(
  layout: { nodes: WorkflowLayoutNode[]; edges: WorkflowLayoutResult["edges"] },
  input: WorkflowLayoutInput,
): boolean {
  return layoutMatchesBusinessNodes(layout, input) && layoutMatchesBusinessEdges(layout, input);
}

function layoutMatchesBusinessNodes(
  layout: { nodes: WorkflowLayoutNode[] },
  input: WorkflowLayoutInput,
): boolean {
  const expectedTasks = new Map(input.nodes.map((node) => [node.nodeId, node.stageId] as const));
  const actualTasks = layout.nodes.filter((node) => node.kind === "task");
  if (expectedTasks.size !== actualTasks.length) return false;
  for (const task of actualTasks) {
    if (expectedTasks.get(task.id) !== task.stageId) return false;
  }
  const expectedStages = new Set(input.stages.map((stage) => stage.stageId));
  const actualStages = new Set(layout.nodes.filter((node) => node.kind === "stage").map((node) => node.stageId));
  return expectedStages.size === actualStages.size && [...expectedStages].every((stageId) => actualStages.has(stageId));
}

function layoutMatchesBusinessEdges(
  layout: { edges: WorkflowLayoutResult["edges"] },
  input: WorkflowLayoutInput,
): boolean {
  const expectedEdges = new Map(input.edges.map((edge) => [edge.edgeId, edge] as const));
  if (expectedEdges.size !== layout.edges.length) return false;
  return layout.edges.every((edge) => {
    const expected = expectedEdges.get(edge.id);
    return expected?.fromNodeId === edge.source && expected.toNodeId === edge.target;
  });
}

function resolveWorkflowLayoutRecovery(
  cache: CacheEntry | null,
  hash: WorkflowLayoutHash,
  graph: WorkflowLayoutInput,
  layoutMode: WorkflowCanvasLayoutMode,
  fallback: WorkflowLayoutResult,
): { nodes: WorkflowLayoutNode[]; edges: WorkflowLayoutResult["edges"] } {
  if (cache && cache.hash.structure === hash.structure && layoutMatchesGraph(cache, graph)) {
    return mergeRuntimeFields(cache, graph, layoutMode);
  }
  return fallback;
}

export { designHeight };
