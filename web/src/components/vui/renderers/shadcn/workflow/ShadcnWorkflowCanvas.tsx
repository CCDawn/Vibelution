/**
 * @xyflow/react composition for VWorkflowCanvas.
 * Node/edge/layout/state live in sibling modules — this file only wires them.
 *
 * Layout ownership: the auto-layout hook (production worker engine) drives
 * geometry; this component renders hook output and honors the fit protocol
 * (`initialFitRevision` once, explicit `fitAll` from controls).
 */
import {
  Background,
  ConnectionLineType,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useNodesInitialized,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
  type EdgeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";

import { cn } from "../../../lib/cn";
import type { WorkflowLayoutInput, WorkflowLayoutNode } from "../../../product/workflow/workflowCanvasTypes";
import type { WorkflowNodeSize } from "./workflowLayoutHash";
import { useWorkflowAutoLayout } from "./useWorkflowAutoLayout";
import { createWorkflowLayoutEngine } from "./workflowElkClient";
import { WorkflowAgentTaskNode } from "./WorkflowAgentTaskNode";
import { WorkflowCanvasControls } from "./WorkflowCanvasControls";
import { WorkflowCanvasLegend } from "./WorkflowCanvasLegend";
import { WorkflowDecisionNode } from "./WorkflowDecisionNode";
import { WorkflowHumanGateNode } from "./WorkflowHumanGateNode";
import { WorkflowHelperLinesOverlay } from "./WorkflowHelperLinesOverlay";
import { WorkflowNodeInteractionBoundary } from "./WorkflowNodeInteractionBoundary";
import { WorkflowOrthogonalConnectionLine } from "./WorkflowOrthogonalConnectionLine";
import { WorkflowSemanticEdge } from "./WorkflowSemanticEdge";
import { WorkflowStageRegionNode } from "./WorkflowStageRegionNode";
import { WorkflowStartEndNode } from "./WorkflowStartEndNode";
import { WorkflowSystemTaskNode } from "./WorkflowSystemTaskNode";
import { useWorkflowInitialFit } from "./useWorkflowInitialFit";
import { resolveRelatedEdgeStroke } from "./workflowCanvasState";
import type { WorkflowCanvasLayoutMode } from "./workflowElkOptions";
import { shouldRefitOnContainerResize } from "./workflowFitOnResize";
import {
  cloneWorkflowManualLayoutSnapshot,
  cloneWorkflowManualPositions,
  persistWorkflowManualLayout,
  readWorkflowManualLayout,
  resolveWorkflowStageLabelPosition,
  snapWorkflowManualPosition,
  WORKFLOW_MANUAL_LAYOUT_GRID,
  WORKFLOW_STAGE_LABEL_HEIGHT,
  WORKFLOW_STAGE_LABEL_WIDTH,
  type WorkflowManualLayoutScope,
  type WorkflowManualLayoutSnapshot,
  type WorkflowManualPositions,
} from "./workflowManualLayout";
import {
  applyWorkflowEdgeAnchorsToPortSides,
  resolveWorkflowEdgeAnchorPatch,
  workflowReconnectKeepsEndpoints,
  type WorkflowEdgeAnchors,
} from "./workflowEdgeAnchors";
import {
  resolveWorkflowManualCardDrag,
  workflowHelperLinesActive,
  workflowHelperLinesEqual,
  type WorkflowHelperLines,
  type WorkflowHelperRect,
  type WorkflowHelperSnapHold,
  type WorkflowManualCardDragResult,
} from "./workflowHelperLines";
import {
  resolveWorkflowNodeFocusCenter,
  shouldPanWorkflowSelectionIntoView,
  workflowEdgeTouchesNode,
} from "./workflowSelectionFocus";
import type { OrthogonalObstacle } from "./workflowOrthogonalRoute";

export function workflowCanvasInitialFitMinZoom(
  layoutMode: WorkflowCanvasLayoutMode,
  nodeCount: number,
): number | undefined {
  if (layoutMode === "serpentine" && nodeCount > 0 && nodeCount <= 5) return 0.8;
  return undefined;
}

export type ShadcnWorkflowCanvasProps = {
  graph: WorkflowLayoutInput;
  selectedNodeId?: string | null;
  runtimeCurrentNodeIds?: string[];
  onSelectNode?: (nodeId: string | null) => void;
  className?: string;
  /**
   * Canvas host size. Prefer `"100%"` inside a filled recipe cell.
   * Avoid fixed px heights in page shells.
   */
  height?: number | string;
  /** When true, show compact status legend. Default true. */
  showLegend?: boolean;
  /** Stable graph geometry variant; serpentine uses horizontal stage lanes. */
  layoutMode?: WorkflowCanvasLayoutMode;
  /** Secondary navigation overview for extendable production canvases. */
  showMiniMap?: boolean;
  /** Keep frequent navigation controls visible while grouping manual layout actions. */
  compactControls?: boolean;
};

type MeasuredNodeProps = {
  id: string;
  data: Record<string, unknown> & { nodeMeasureKey?: string };
  children?: ReactNode;
};

/**
 * Reports the rendered DOM size of a node to the auto-layout hook (P1-5).
 *
 * The outer React Flow node is styled with the ELK-committed size, so
 * `offsetWidth/Height` would just echo that forced size back. We instead
 * measure the CONTENT's natural size via `scrollWidth/scrollHeight` with
 * `overflow: visible`: when the label/badge grows beyond the committed box,
 * the scroll extent reflects the real minimum size the node needs, and
 * calibration can relayout with it. Zero sizes (unmeasured / SSR / hidden)
 * are skipped so calibration never feeds garbage into the layout hash.
 *
 * @internal exported for M-level tests only; not part of the VUI surface.
 */
export function NodeMeasureReporter({
  id,
  data,
  onMeasure,
  children,
}: MeasuredNodeProps & { onMeasure: (id: string, size: WorkflowNodeSize) => void }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const measureKey = data?.nodeMeasureKey ?? id;
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Natural content size (may exceed the ELK-committed box), floor at the
    // committed box so calibration never shrinks a node below what ELK placed.
    const width = Math.max(el.offsetWidth, el.scrollWidth);
    const height = Math.max(el.offsetHeight, el.scrollHeight);
    if (width <= 0 || height <= 0) return;
    onMeasure(measureKey, { width, height });
  });
  return (
    <div ref={ref} className="h-full w-full overflow-visible" data-node-measure={measureKey}>
      {children}
    </div>
  );
}

/**
 * Wraps a node renderer so it reports its rendered DOM size back to the
 * auto-layout hook (P1-5).
 *
 * @internal exported for M-level tests only; not part of the VUI surface.
 */
export function wrapNodeForMeasurement(
  Base: (props: NodeProps) => ReactElement,
  onMeasure: (id: string, size: WorkflowNodeSize) => void,
): (props: NodeProps) => ReactElement {
  return function MeasuredNode(props: NodeProps) {
    return (
      <NodeMeasureReporter id={props.id} data={(props.data ?? {}) as never} onMeasure={onMeasure}>
        <Base {...props} />
      </NodeMeasureReporter>
    );
  };
}

function wrapInteractiveNodeForMeasurement(
  Base: (props: NodeProps) => ReactElement,
  onMeasure: (id: string, size: WorkflowNodeSize) => void,
  onActivate?: (id: string) => void,
): (props: NodeProps) => ReactElement {
  const MeasuredNode = wrapNodeForMeasurement(Base, onMeasure);
  return function InteractiveMeasuredNode(props: NodeProps) {
    return (
      <WorkflowNodeInteractionBoundary
        onActivate={onActivate ? () => onActivate(props.id) : undefined}
      >
        <MeasuredNode {...props} />
      </WorkflowNodeInteractionBoundary>
    );
  };
}

const edgeTypes: EdgeTypes = {
  workflowSemantic: WorkflowSemanticEdge,
};

function visualToRfType(visualKind: string): string {
  switch (visualKind) {
    case "human_gate":
      return "humanGate";
    case "system_task":
      return "systemTask";
    case "decision":
      return "decision";
    case "start":
    case "end":
      return "startEnd";
    case "agent_task":
    default:
      return "agentTask";
  }
}

const MANUAL_LAYOUT_HISTORY_LIMIT = 20;

function resolveDraggedTaskPosition(
  node: Node,
  layoutNodes: readonly WorkflowLayoutNode[],
  positions: WorkflowManualPositions,
  hold?: WorkflowHelperSnapHold | null,
): WorkflowManualCardDragResult {
  const layoutNode = layoutNodes.find((item) => item.id === node.id);
  const width = layoutNode?.width
    ?? (typeof node.measured?.width === "number" ? node.measured.width : undefined)
    ?? (typeof node.style?.width === "number" ? node.style.width : undefined);
  const height = layoutNode?.height
    ?? (typeof node.measured?.height === "number" ? node.measured.height : undefined)
    ?? (typeof node.style?.height === "number" ? node.style.height : undefined);
  const others: WorkflowHelperRect[] = [];
  for (const item of layoutNodes) {
    if (item.id === node.id || item.kind !== "task") continue;
    const pos = positions[item.id] ?? { x: item.x, y: item.y };
    others.push({ x: pos.x, y: pos.y, width: item.width, height: item.height });
  }
  return resolveWorkflowManualCardDrag({
    position: node.position,
    width: width ?? 0,
    height: height ?? 0,
    others,
    hold,
  });
}

function WorkflowCanvasInner({
  graph,
  selectedNodeId = null,
  runtimeCurrentNodeIds = [],
  onSelectNode,
  className,
  height = "100%",
  showLegend = true,
  layoutMode = "stage-columns",
  showMiniMap = false,
  compactControls = false,
}: ShadcnWorkflowCanvasProps) {
  const rf = useReactFlow();
  const hostRef = useRef<HTMLDivElement | null>(null);
  const userMovedViewportRef = useRef(false);
  const programmaticFitRef = useRef(false);
  const canvasOriginSelectionRef = useRef<string | null>(null);
  const lastPannedSelectionRef = useRef<string | null>(null);
  const initialFitWasPendingRef = useRef(false);
  const lastHostSizeRef = useRef({ width: 0, height: 0 });
  const initialFitMinZoom = workflowCanvasInitialFitMinZoom(layoutMode, graph.nodes.length);
  const fitCanvas = useCallback((padding: number, duration = 0, minZoom?: number) => {
    programmaticFitRef.current = true;
    void Promise.resolve(rf.fitView({ padding, duration, minZoom })).finally(() => {
      programmaticFitRef.current = false;
    });
  }, [rf]);
  const fitAll = useCallback(() => {
    userMovedViewportRef.current = false;
    fitCanvas(0.1, 200);
  }, [fitCanvas]);

  const layout = useWorkflowAutoLayout(graph, createWorkflowLayoutEngine, { layoutMode });
  const currentSet = useMemo(() => new Set(runtimeCurrentNodeIds), [runtimeCurrentNodeIds]);
  const nodesInitialized = useNodesInitialized();
  const manualLayoutEnabled = layoutMode === "serpentine";
  const manualNodeIdsKey = useMemo(
    () => graph.nodes.map((node) => node.nodeId).sort().join("\u0001"),
    [graph.nodes],
  );
  const manualStageIdsKey = useMemo(
    () => graph.stages.map((stage) => stage.stageId).sort().join("\u0001"),
    [graph.stages],
  );
  const manualScope = useMemo<WorkflowManualLayoutScope>(
    () => ({
      structureKey: layout.structureKey,
      runId: graph.run?.runId ?? null,
      nodeIds: manualNodeIdsKey ? manualNodeIdsKey.split("\u0001") : [],
      stageIds: manualStageIdsKey ? manualStageIdsKey.split("\u0001") : [],
    }),
    [graph.run?.runId, layout.structureKey, manualNodeIdsKey, manualStageIdsKey],
  );
  const [manualPositions, setManualPositions] = useState<WorkflowManualPositions>({});
  const [stageLabelOffsets, setStageLabelOffsets] = useState<WorkflowManualPositions>({});
  const [edgeAnchors, setEdgeAnchors] = useState<WorkflowEdgeAnchors>({});
  const [manualLayoutLocked, setManualLayoutLocked] = useState(false);
  const [manualHistory, setManualHistory] = useState<WorkflowManualLayoutSnapshot[]>([]);
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [helperLines, setHelperLines] = useState<WorkflowHelperLines | null>(null);
  const [reconnectSession, setReconnectSession] = useState<{
    edgeId: string;
    handleType: "source" | "target";
    source: string;
    target: string;
  } | null>(null);
  const manualPositionsRef = useRef<WorkflowManualPositions>({});
  const stageLabelOffsetsRef = useRef<WorkflowManualPositions>({});
  const edgeAnchorsRef = useRef<WorkflowEdgeAnchors>({});
  const reconnectSessionRef = useRef<{
    edgeId: string;
    handleType: "source" | "target";
    source: string;
    target: string;
  } | null>(null);
  const stageAnchorByIdRef = useRef<Record<string, { x: number; y: number }>>({});
  const layoutNodesRef = useRef(layout.nodes);
  const manualLockedRef = useRef(false);
  const manualHistoryRef = useRef<WorkflowManualLayoutSnapshot[]>([]);
  const manualDragFrameRef = useRef<number | null>(null);
  const helperLinesRef = useRef<WorkflowHelperLines | null>(null);
  const helperSnapHoldRef = useRef<WorkflowHelperSnapHold>({});
  const lastPublishedDragRef = useRef<{
    id: string;
    x: number;
    y: number;
    lines: WorkflowHelperLines | null;
  } | null>(null);

  useEffect(() => {
    const saved = manualLayoutEnabled
      ? readWorkflowManualLayout(manualScope)
      : { positions: {}, stageLabelOffsets: {}, edgeAnchors: {}, locked: false };
    manualPositionsRef.current = saved.positions;
    stageLabelOffsetsRef.current = saved.stageLabelOffsets;
    edgeAnchorsRef.current = saved.edgeAnchors;
    reconnectSessionRef.current = null;
    manualLockedRef.current = saved.locked;
    manualHistoryRef.current = [];
    setManualPositions(saved.positions);
    setStageLabelOffsets(saved.stageLabelOffsets);
    setEdgeAnchors(saved.edgeAnchors);
    setReconnectSession(null);
    setManualLayoutLocked(saved.locked);
    setManualHistory([]);
    setDraggingNodeId(null);
    helperLinesRef.current = null;
    helperSnapHoldRef.current = {};
    lastPublishedDragRef.current = null;
    setHelperLines(null);
  }, [manualLayoutEnabled, manualScope]);

  useEffect(() => {
    manualPositionsRef.current = manualPositions;
  }, [manualPositions]);

  useEffect(() => {
    stageLabelOffsetsRef.current = stageLabelOffsets;
  }, [stageLabelOffsets]);

  useEffect(() => {
    edgeAnchorsRef.current = edgeAnchors;
  }, [edgeAnchors]);

  useEffect(() => {
    layoutNodesRef.current = layout.nodes;
  }, [layout.nodes]);

  useEffect(() => {
    manualLockedRef.current = manualLayoutLocked;
  }, [manualLayoutLocked]);

  useEffect(() => {
    manualHistoryRef.current = manualHistory;
  }, [manualHistory]);

  useEffect(() => () => {
    if (manualDragFrameRef.current !== null) {
      cancelAnimationFrame(manualDragFrameRef.current);
    }
  }, []);

  const commitManualLayout = useCallback((snapshot: WorkflowManualLayoutSnapshot, locked = manualLockedRef.current) => {
    const next = cloneWorkflowManualLayoutSnapshot(snapshot);
    manualPositionsRef.current = next.positions;
    stageLabelOffsetsRef.current = next.stageLabelOffsets;
    edgeAnchorsRef.current = next.edgeAnchors;
    manualLockedRef.current = locked;
    setManualPositions(next.positions);
    setStageLabelOffsets(next.stageLabelOffsets);
    setEdgeAnchors(next.edgeAnchors);
    setManualLayoutLocked(locked);
    persistWorkflowManualLayout(manualScope, { ...next, locked });
  }, [manualScope]);

  const rememberManualLayout = useCallback(() => {
    const next = [
      ...manualHistoryRef.current,
      cloneWorkflowManualLayoutSnapshot({
        positions: manualPositionsRef.current,
        stageLabelOffsets: stageLabelOffsetsRef.current,
        edgeAnchors: edgeAnchorsRef.current,
      }),
    ].slice(-MANUAL_LAYOUT_HISTORY_LIMIT);
    manualHistoryRef.current = next;
    setManualHistory(next);
  }, []);

  const onNodeDragStart = useCallback((_event: unknown, node: Node) => {
    if (!manualLayoutEnabled || manualLockedRef.current) return;
    rememberManualLayout();
    setDraggingNodeId(node.id);
    helperLinesRef.current = null;
    helperSnapHoldRef.current = {};
    lastPublishedDragRef.current = null;
    setHelperLines(null);
  }, [manualLayoutEnabled, rememberManualLayout]);

  const onNodeDrag = useCallback((_event: unknown, node: Node) => {
    if (!manualLayoutEnabled || manualLockedRef.current) return;
    if (node.type === "stageRegion") {
      const stageId = String(node.data?.stageId ?? "");
      const anchor = stageAnchorByIdRef.current[stageId];
      if (!stageId || !anchor) return;
      stageLabelOffsetsRef.current = {
        ...stageLabelOffsetsRef.current,
        [stageId]: snapWorkflowManualPosition({ x: node.position.x - anchor.x, y: node.position.y - anchor.y }),
      };
      helperLinesRef.current = null;
      helperSnapHoldRef.current = {};
    } else {
      const snapped = resolveDraggedTaskPosition(
        node,
        layoutNodesRef.current,
        manualPositionsRef.current,
        helperSnapHoldRef.current,
      );
      helperSnapHoldRef.current = snapped.hold;
      node.position = snapped.position;
      manualPositionsRef.current = {
        ...manualPositionsRef.current,
        [node.id]: snapped.position,
      };
      helperLinesRef.current = workflowHelperLinesActive(snapped.lines) ? snapped.lines : null;
      const published = lastPublishedDragRef.current;
      if (
        published
        && published.id === node.id
        && published.x === snapped.position.x
        && published.y === snapped.position.y
        && workflowHelperLinesEqual(published.lines, helperLinesRef.current)
      ) {
        return;
      }
      lastPublishedDragRef.current = {
        id: node.id,
        x: snapped.position.x,
        y: snapped.position.y,
        lines: helperLinesRef.current,
      };
    }
    if (manualDragFrameRef.current !== null) return;
    manualDragFrameRef.current = requestAnimationFrame(() => {
      manualDragFrameRef.current = null;
      setManualPositions(cloneWorkflowManualPositions(manualPositionsRef.current));
      setStageLabelOffsets(cloneWorkflowManualPositions(stageLabelOffsetsRef.current));
      setHelperLines(helperLinesRef.current);
    });
  }, [manualLayoutEnabled]);

  const onNodeDragStop = useCallback((_event: unknown, node: Node) => {
    if (!manualLayoutEnabled) return;
    if (manualDragFrameRef.current !== null) {
      cancelAnimationFrame(manualDragFrameRef.current);
      manualDragFrameRef.current = null;
    }
    if (node.type === "stageRegion") {
      const stageId = String(node.data?.stageId ?? "");
      const anchor = stageAnchorByIdRef.current[stageId];
      if (stageId && anchor) {
        stageLabelOffsetsRef.current = {
          ...stageLabelOffsetsRef.current,
          [stageId]: snapWorkflowManualPosition({ x: node.position.x - anchor.x, y: node.position.y - anchor.y }),
        };
      }
    } else {
      const snapped = resolveDraggedTaskPosition(
        node,
        layoutNodesRef.current,
        manualPositionsRef.current,
        helperSnapHoldRef.current,
      );
      node.position = snapped.position;
      manualPositionsRef.current = {
        ...manualPositionsRef.current,
        [node.id]: snapped.position,
      };
    }
    setHelperLines(null);
    helperLinesRef.current = null;
    helperSnapHoldRef.current = {};
    lastPublishedDragRef.current = null;
    commitManualLayout({
      positions: manualPositionsRef.current,
      stageLabelOffsets: stageLabelOffsetsRef.current,
      edgeAnchors: edgeAnchorsRef.current,
    });
    setDraggingNodeId(null);
  }, [commitManualLayout, manualLayoutEnabled]);

  const undoManualLayout = useCallback(() => {
    const previous = manualHistoryRef.current.at(-1);
    if (!previous) return;
    const nextHistory = manualHistoryRef.current.slice(0, -1);
    manualHistoryRef.current = nextHistory;
    setManualHistory(nextHistory);
    commitManualLayout(previous);
  }, [commitManualLayout]);

  const autoArrangeManualLayout = useCallback(() => {
    if (
      Object.keys(manualPositionsRef.current).length > 0
      || Object.keys(stageLabelOffsetsRef.current).length > 0
      || Object.keys(edgeAnchorsRef.current).length > 0
    ) {
      rememberManualLayout();
      commitManualLayout({ positions: {}, stageLabelOffsets: {}, edgeAnchors: {} });
    }
    requestAnimationFrame(() => fitAll());
  }, [commitManualLayout, fitAll, rememberManualLayout]);

  const toggleManualLayoutLock = useCallback(() => {
    commitManualLayout({
      positions: manualPositionsRef.current,
      stageLabelOffsets: stageLabelOffsetsRef.current,
      edgeAnchors: edgeAnchorsRef.current,
    }, !manualLockedRef.current);
  }, [commitManualLayout]);

  const manualRouteActive = manualLayoutEnabled
    && (
      draggingNodeId !== null
      || Object.keys(manualPositions).length > 0
      || Object.keys(stageLabelOffsets).length > 0
      || Object.keys(edgeAnchors).length > 0
    );

  const selectFromCanvas = useCallback((id: string | null) => {
    canvasOriginSelectionRef.current = id;
    onSelectNode?.(id);
  }, [onSelectNode]);

  // P1-5: measured node types report rendered DOM sizes back to the layout
  // hook so the second pass of the layout uses real geometry.
  const measuredNodeTypes: NodeTypes = useMemo(
    () => ({
      stageRegion: wrapNodeForMeasurement(WorkflowStageRegionNode, layout.reportMeasuredSize),
      agentTask: wrapInteractiveNodeForMeasurement(WorkflowAgentTaskNode, layout.reportMeasuredSize, selectFromCanvas),
      humanGate: wrapInteractiveNodeForMeasurement(WorkflowHumanGateNode, layout.reportMeasuredSize, selectFromCanvas),
      systemTask: wrapInteractiveNodeForMeasurement(WorkflowSystemTaskNode, layout.reportMeasuredSize, selectFromCanvas),
      decision: wrapInteractiveNodeForMeasurement(WorkflowDecisionNode, layout.reportMeasuredSize, selectFromCanvas),
      startEnd: wrapInteractiveNodeForMeasurement(WorkflowStartEndNode, layout.reportMeasuredSize, selectFromCanvas),
    }),
    [layout.reportMeasuredSize, selectFromCanvas],
  );

  // Fit protocol: fit exactly once when the first layout commits AND the committed
  // nodes have entered React Flow internals. Never re-fit for runtime-only updates
  // (status/selection/run events). `fitAll` from controls stays explicit.
  const { pendingInitialFit } = useWorkflowInitialFit({
    initialFitRevision: layout.initialFitRevision,
    layoutRevision: layout.layoutRevision,
    structureKey: layout.structureKey,
    nodesInitialized,
    fit: () => {
      fitCanvas(0.08, 0, initialFitMinZoom);
    },
    acknowledgeInitialFit: layout.acknowledgeInitialFit,
  });

  useEffect(() => {
    if (pendingInitialFit) {
      initialFitWasPendingRef.current = true;
      return;
    }
    if (initialFitWasPendingRef.current) {
      initialFitWasPendingRef.current = false;
      lastPannedSelectionRef.current = null;
    }
  }, [pendingInitialFit]);

  useEffect(() => {
    userMovedViewportRef.current = false;
    lastHostSizeRef.current = { width: 0, height: 0 };
    lastPannedSelectionRef.current = null;
  }, [layout.structureKey]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (!box) return;
      const previous = lastHostSizeRef.current;
      if (!shouldRefitOnContainerResize({
        width: box.width,
        height: box.height,
        previousWidth: previous.width,
        previousHeight: previous.height,
        userMovedViewport: userMovedViewportRef.current,
      })) {
        return;
      }
      lastHostSizeRef.current = { width: box.width, height: box.height };
      fitCanvas(0.08, 0, initialFitMinZoom);
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, [fitCanvas, initialFitMinZoom]);

  const markUserMovedViewport = useCallback(() => {
    if (!programmaticFitRef.current) {
      userMovedViewportRef.current = true;
    }
  }, []);

  const stageIndexById = useMemo(() => {
    const map = new Map<string, number>();
    graph.stages.forEach((s, i) => map.set(s.stageId, i));
    return map;
  }, [graph.stages]);

  const stageAnchorById = useMemo(() => {
    const anchors: Record<string, { x: number; y: number }> = {};
    for (const stage of graph.stages) {
      const stageLayout = layout.nodes.find((node) => node.kind === "stage" && node.stageId === stage.stageId);
      const members = layout.nodes
        .filter((node) => node.kind === "task" && (stage.nodeIds.includes(node.id) || node.stageId === stage.stageId))
        .map((node) => ({
          ...(manualPositions[node.id] ?? { x: node.x, y: node.y }),
          width: node.width,
          height: node.height,
        }));
      anchors[stage.stageId] = resolveWorkflowStageLabelPosition(
        members,
        { x: 0, y: 0 },
        stageLayout ? { x: stageLayout.x, y: stageLayout.y } : { x: 0, y: 0 },
      );
    }
    return anchors;
  }, [graph.stages, layout.nodes, manualPositions]);

  useEffect(() => {
    stageAnchorByIdRef.current = stageAnchorById;
  }, [stageAnchorById]);

  const nodes: Node[] = useMemo(
    () =>
      layout.nodes
        .filter((node) => !(layoutMode === "serpentine" && node.kind === "stage"))
        .map((node) => {
        if (node.kind === "stage") {
          const stageInput = graph.stages.find((stage) => stage.stageId === node.stageId);
          const stageAnchor = stageAnchorById[node.stageId] ?? { x: node.x, y: node.y };
          const stageOffset = stageLabelOffsets[node.stageId] ?? { x: 0, y: 0 };
          return {
            id: node.id,
            type: "stageRegion",
            position: manualLayoutEnabled
              ? { x: stageAnchor.x + stageOffset.x, y: stageAnchor.y + stageOffset.y }
              : { x: node.x, y: node.y },
            data: {
              stageId: node.stageId,
              label: node.label,
              stageTone: node.stageTone,
              stageIndex: stageIndexById.get(node.stageId) ?? 0,
              // Stage input may override the header counter (e.g. the
              // hypothesis-first region shows 已闭环轮次/预算, not card counts).
              taskCount: stageInput?.progress?.total ?? stageInput?.nodeIds.length ?? 0,
              completedCount: stageInput?.progress?.completed ?? graph.nodes.filter(
                (task) => task.stageId === node.stageId && task.status === "succeeded",
              ).length,
              layoutMode,
            },
            // React Flow uses the intrinsic node dimensions to decide when a
            // node is initialized and therefore eligible for painting/fitView.
            // Keep these in sync with the committed layout box instead of
            // relying on style alone (style is not part of nodeHasDimensions).
            width: manualLayoutEnabled ? WORKFLOW_STAGE_LABEL_WIDTH : node.width,
            height: manualLayoutEnabled ? WORKFLOW_STAGE_LABEL_HEIGHT : node.height,
            style: {
              width: manualLayoutEnabled ? WORKFLOW_STAGE_LABEL_WIDTH : node.width,
              height: manualLayoutEnabled ? WORKFLOW_STAGE_LABEL_HEIGHT : node.height,
            },
            selectable: false,
            draggable: manualLayoutEnabled && !manualLayoutLocked,
            zIndex: manualLayoutEnabled ? 3 : 0,
          } satisfies Node;
        }
        const parentId = node.parentStageId;
        const manualPosition = manualLayoutEnabled ? manualPositions[node.id] : undefined;
        return {
          id: node.id,
          type: visualToRfType(node.visualKind),
          position: {
            x: manualPosition?.x ?? (manualLayoutEnabled ? node.x : parentId != null ? (node.relativeX ?? 0) : node.x),
            y: manualPosition?.y ?? (manualLayoutEnabled ? node.y : parentId != null ? (node.relativeY ?? 0) : node.y),
          },
          parentId: manualLayoutEnabled ? undefined : parentId,
          extent: manualLayoutEnabled ? undefined : parentId ? ("parent" as const) : undefined,
          data: {
            label: node.label,
            actorKind: node.actorKind,
            visualKind: node.visualKind,
            status: node.status ?? "pending",
            attempt: node.attempt,
            primaryAgentId: node.primaryAgentId,
            isRuntimeCurrent: Boolean(node.isRuntimeCurrent || currentSet.has(node.id)),
            hasPendingHumanTask: node.hasPendingHumanTask,
            blockedReason: node.blockedReason,
            description: node.description,
            primaryRoleKey: node.primaryRoleKey,
            portSides: applyWorkflowEdgeAnchorsToPortSides(
              node.id,
              node.portSides,
              layout.edges,
              edgeAnchors,
            ),
            sourceHandleIds: node.sourceHandleIds,
            decisionOutcomeIds: node.decisionOutcomeIds,
            layoutMode,
            reconnectMagnets:
              reconnectSession?.handleType === "target" && reconnectSession.target === node.id
                ? { type: "target" as const }
                : reconnectSession?.handleType === "source" && reconnectSession.source === node.id
                  ? { type: "source" as const }
                  : undefined,
          },
          // ELK commits the geometry before React Flow measures the DOM. The
          // width/height fields make that geometry visible to React Flow on
          // the first render, including after a refresh or narrow resize.
          width: node.width,
          height: node.height,
          style: { width: node.width, height: node.height },
          selectable: true,
          draggable: manualLayoutEnabled && !manualLayoutLocked,
          selected: node.id === selectedNodeId,
          zIndex: 2,
        } satisfies Node;
      }),
    [
      layout.nodes,
      currentSet,
      graph.nodes,
      graph.stages,
      layoutMode,
      manualLayoutEnabled,
      manualLayoutLocked,
      manualPositions,
      selectedNodeId,
      stageIndexById,
      stageAnchorById,
      stageLabelOffsets,
      edgeAnchors,
      reconnectSession,
      layout.edges,
    ],
  );

  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  const focusableNodeCount = nodes.length;

  const obstacleRects = useMemo(() => {
    if (!manualLayoutEnabled) return [] as OrthogonalObstacle[];
    const rects: OrthogonalObstacle[] = [];
    for (const node of nodes) {
      if (node.type === "stageRegion") continue;
      const width = typeof node.measured?.width === "number"
        ? node.measured.width
        : typeof node.style?.width === "number" ? node.style.width : undefined;
      const height = typeof node.measured?.height === "number"
        ? node.measured.height
        : typeof node.style?.height === "number" ? node.style.height : undefined;
      if (!width || !height) continue;
      rects.push({ id: node.id, x: node.position.x, y: node.position.y, width, height });
    }
    return rects;
  }, [manualLayoutEnabled, nodes]);

  const edges: Edge[] = useMemo(
    () =>
      layout.edges.map((edge) => {
        const relatedToSelection = workflowEdgeTouchesNode(edge.source, edge.target, selectedNodeId);
        const stroke = resolveRelatedEdgeStroke(edge.pathState, edge.semanticKind, relatedToSelection);
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
          type: "workflowSemantic",
          animated: edge.pathState === "active" || edge.pathState === "attention",
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 16,
            height: 16,
            color: stroke.stroke,
          },
          data: {
            label: edge.label,
            semanticKind: edge.semanticKind,
            pathState: edge.pathState,
            labelAlwaysVisible: edge.labelAlwaysVisible,
            gateKind: edge.gateKind,
            sections: edge.sections,
            labelBounds: edge.labelBounds,
            manualRouteActive: manualRouteActive || Boolean(edgeAnchors[edge.id]),
            manualDragging: draggingNodeId !== null,
            obstacleRects,
            relatedToSelection,
          },
          zIndex: 1,
        };
      }),
    [draggingNodeId, edgeAnchors, layout.edges, manualRouteActive, obstacleRects, selectedNodeId],
  );

  useEffect(() => {
    if (!selectedNodeId) {
      lastPannedSelectionRef.current = null;
      return;
    }
    if (!shouldPanWorkflowSelectionIntoView({
      selectedNodeId,
      canvasOriginNodeId: canvasOriginSelectionRef.current,
      lastPannedNodeId: lastPannedSelectionRef.current,
      pendingInitialFit,
      nodesInitialized,
    })) {
      return;
    }
    const currentNodes = nodesRef.current;
    const node = rf.getNode(selectedNodeId) ?? currentNodes.find((item) => item.id === selectedNodeId);
    if (!node) return;
    const getNode = (id: string) => rf.getNode(id) ?? currentNodes.find((item) => item.id === id);
    const center = resolveWorkflowNodeFocusCenter(node, getNode);
    programmaticFitRef.current = true;
    userMovedViewportRef.current = true;
    void Promise.resolve(rf.setCenter(center.x, center.y, {
      zoom: rf.getZoom(),
      duration: 220,
    })).finally(() => {
      programmaticFitRef.current = false;
    });
    lastPannedSelectionRef.current = selectedNodeId;
  }, [focusableNodeCount, nodesInitialized, pendingInitialFit, rf, selectedNodeId]);

  const onNodeClick = useCallback(
    (_event: unknown, node: Node) => {
      if (node.type !== "stageRegion") selectFromCanvas(node.id);
    },
    [selectFromCanvas],
  );

  const onPaneClick = useCallback(() => {
    selectFromCanvas(null);
  }, [selectFromCanvas]);

  const edgeReconnectEnabled = manualLayoutEnabled && !manualLayoutLocked;

  const isValidConnection = useCallback((connection: Connection | Edge) => {
    const session = reconnectSessionRef.current;
    if (!session) return false;
    return connection.source === session.source && connection.target === session.target;
  }, []);

  const onReconnectStart = useCallback((
    _event: unknown,
    edge: Edge,
    handleType: "source" | "target",
  ) => {
    if (!edgeReconnectEnabled) return;
    const session = {
      edgeId: edge.id,
      handleType,
      source: edge.source,
      target: edge.target,
    };
    reconnectSessionRef.current = session;
    setReconnectSession(session);
  }, [edgeReconnectEnabled]);

  const onReconnect = useCallback((oldEdge: Edge, connection: Connection) => {
    const session = reconnectSessionRef.current;
    if (!session || session.edgeId !== oldEdge.id) return;
    if (!workflowReconnectKeepsEndpoints(oldEdge, connection)) return;
    const nodeId = session.handleType === "source" ? oldEdge.source : oldEdge.target;
    const layoutNode = layout.nodes.find((node) => node.id === nodeId);
    const portSides = applyWorkflowEdgeAnchorsToPortSides(
      nodeId,
      layoutNode?.portSides,
      layout.edges,
      edgeAnchorsRef.current,
    );
    const patch = resolveWorkflowEdgeAnchorPatch({
      handleType: session.handleType,
      connection,
      portSides,
    });
    if (!patch) return;
    rememberManualLayout();
    commitManualLayout({
      positions: manualPositionsRef.current,
      stageLabelOffsets: stageLabelOffsetsRef.current,
      edgeAnchors: {
        ...edgeAnchorsRef.current,
        [oldEdge.id]: { ...edgeAnchorsRef.current[oldEdge.id], ...patch },
      },
    });
  }, [commitManualLayout, layout.edges, layout.nodes, rememberManualLayout]);

  const onReconnectEnd = useCallback(() => {
    reconnectSessionRef.current = null;
    setReconnectSession(null);
  }, []);

  const fillHost = height === "100%";

  return (
    <div
      ref={hostRef}
      className={cn(
        "relative min-h-0 w-full overflow-hidden rounded-xl border border-vui-border bg-vui-surface-workspace",
        fillHost ? "h-full min-h-0 w-full flex-1" : null,
        className,
      )}
      style={fillHost ? { height: "100%", minHeight: 0 } : { height }}
      data-vui="workflow-canvas"
      data-layout-mode={layoutMode}
    >
      <div
        className={fillHost ? "absolute inset-0 min-h-0" : "h-full w-full"}
        style={fillHost ? { width: "100%", height: "100%" } : undefined}
      >
          <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={measuredNodeTypes}
          edgeTypes={edgeTypes}
          minZoom={layoutMode === "serpentine" ? 0.28 : 0.35}
          maxZoom={1.6}
          nodesDraggable={manualLayoutEnabled && !manualLayoutLocked}
          nodesConnectable={reconnectSession !== null}
          edgesReconnectable={edgeReconnectEnabled}
          reconnectRadius={24}
          isValidConnection={isValidConnection}
          onReconnectStart={onReconnectStart}
          onReconnect={onReconnect}
          onReconnectEnd={onReconnectEnd}
          elementsSelectable
          snapToGrid={false}
          panOnDrag
          panOnScroll
          zoomOnScroll
          zoomOnPinch
          onNodeClick={onNodeClick}
          onNodeDragStart={onNodeDragStart}
          onNodeDrag={onNodeDrag}
          onNodeDragStop={onNodeDragStop}
          onPaneClick={onPaneClick}
          onMoveStart={markUserMovedViewport}
          proOptions={{ hideAttribution: true }}
          style={{ width: "100%", height: "100%" }}
          className={fillHost ? "h-full w-full" : undefined}
          defaultEdgeOptions={{ type: "workflowSemantic" }}
          connectionLineType={ConnectionLineType.Step}
          connectionLineComponent={WorkflowOrthogonalConnectionLine}
          >
          <Background
            gap={layoutMode === "serpentine" ? WORKFLOW_MANUAL_LAYOUT_GRID : 20}
            size={1}
            color="var(--vui-border-strong)"
          />
          <WorkflowHelperLinesOverlay lines={helperLines} />
          <WorkflowCanvasControls
            runtimeCurrentNodeIds={runtimeCurrentNodeIds}
            onFitAll={fitAll}
            manualLayoutPresentation={compactControls ? "menu" : "inline"}
            manualLayout={manualLayoutEnabled ? {
              canUndo: manualHistory.length > 0,
              locked: manualLayoutLocked,
              onAutoArrange: autoArrangeManualLayout,
              onUndo: undoManualLayout,
              onToggleLock: toggleManualLayoutLock,
            } : undefined}
          />
          {showLegend ? <WorkflowCanvasLegend /> : null}
          {showMiniMap ? (
            <MiniMap
              pannable
              zoomable
              position="bottom-right"
              ariaLabel="科研流程小地图"
              className="!h-[96px] !w-[158px] !rounded-xl !border !border-[var(--vui-border-subtle)] !bg-[color-mix(in_srgb,var(--vui-surface-panel)_94%,transparent)] !shadow-sm"
              maskColor="color-mix(in srgb, var(--vui-surface-workspace) 76%, transparent)"
              nodeColor={(node) => {
                if (node.type === "stageRegion") return "color-mix(in srgb, var(--accent-cool) 8%, transparent)";
                const status = String(node.data?.status ?? "pending");
                if (status === "failed" || status === "blocked") return "var(--state-error)";
                if (status === "waiting_human") return "var(--state-warning)";
                if (status === "running" || status === "ready") return "var(--accent-cool)";
                if (status === "succeeded") return "var(--state-success)";
                return "var(--vui-border-strong)";
              }}
              nodeStrokeWidth={2}
            />
          ) : null}
          </ReactFlow>
      </div>
      {graph.nodes.length > 0 && layout.nodes.length === 0 && !layout.degraded ? (
        <div
          className="pointer-events-none absolute inset-0 z-10 grid place-items-center bg-[color-mix(in_srgb,var(--vui-surface-workspace)_82%,transparent)] px-6 text-center [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]"
          data-vui="workflow-layout-pending"
          role="status"
        >
          正在整理流程布局…
        </div>
      ) : null}
      {graph.nodes.length === 0 ? (
        <div
          className="pointer-events-none absolute inset-0 z-10 grid place-items-center px-6 text-center [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]"
          data-vui="workflow-empty"
          role="status"
        >
          当前流程暂无可显示的任务
        </div>
      ) : null}
      {layout.degraded ? (
        <div
          className="absolute right-3 top-3 z-20 max-w-[16rem] rounded-md border border-[var(--state-warning,#d97706)]/50 bg-[var(--vui-surface-panel)] px-2.5 py-1.5 text-[11px] leading-snug text-[var(--state-warning,#d97706)] shadow-sm"
          data-vui="workflow-degraded"
          role="status"
        >
          <span className="font-semibold">布局降级</span>
          <span className="block truncate text-[var(--fg-secondary)]" title={layout.degraded.reason}>
            {layout.degraded.reason}
          </span>
        </div>
      ) : null}
    </div>
  );
}

export function ShadcnWorkflowCanvas(props: ShadcnWorkflowCanvasProps) {
  return (
    <ReactFlowProvider>
      <WorkflowCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
