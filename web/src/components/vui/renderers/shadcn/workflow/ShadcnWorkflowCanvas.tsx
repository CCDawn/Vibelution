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
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  useNodesInitialized,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
  type EdgeTypes,
  type OnSelectionChangeParams,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useLayoutEffect, useMemo, useRef, type ReactElement, type ReactNode } from "react";

import { cn } from "../../../lib/cn";
import type { WorkflowLayoutInput } from "../../../product/workflow/workflowCanvasTypes";
import type { WorkflowNodeSize } from "./workflowLayoutHash";
import { useWorkflowAutoLayout } from "./useWorkflowAutoLayout";
import { createWorkflowLayoutEngine } from "./workflowElkClient";
import { WorkflowAgentTaskNode } from "./WorkflowAgentTaskNode";
import { WorkflowCanvasControls } from "./WorkflowCanvasControls";
import { WorkflowCanvasLegend } from "./WorkflowCanvasLegend";
import { WorkflowDecisionNode } from "./WorkflowDecisionNode";
import { WorkflowHumanGateNode } from "./WorkflowHumanGateNode";
import { WorkflowSemanticEdge } from "./WorkflowSemanticEdge";
import { WorkflowStageRegionNode } from "./WorkflowStageRegionNode";
import { WorkflowStartEndNode } from "./WorkflowStartEndNode";
import { WorkflowSystemTaskNode } from "./WorkflowSystemTaskNode";
import { useWorkflowInitialFit } from "./useWorkflowInitialFit";

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
};

type MeasuredNodeProps = {
  id: string;
  data: Record<string, unknown> & { nodeMeasureKey?: string };
  children?: ReactNode;
};

/**
 * Reports the rendered DOM size of a node to the auto-layout hook (P1-5).
 * Zero sizes (unmeasured / SSR / hidden) are skipped so calibration never
 * feeds garbage into the layout hash.
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
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    if (width <= 0 || height <= 0) return;
    onMeasure(measureKey, { width, height });
  });
  return (
    <div ref={ref} className="h-full w-full" data-node-measure={measureKey}>
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

function WorkflowCanvasInner({
  graph,
  selectedNodeId = null,
  runtimeCurrentNodeIds = [],
  onSelectNode,
  className,
  height = "100%",
  showLegend = true,
}: ShadcnWorkflowCanvasProps) {
  const rf = useReactFlow();
  const fitAll = useCallback(() => {
    void rf.fitView({ padding: 0.1, duration: 200 });
  }, [rf]);

  const layout = useWorkflowAutoLayout(graph, createWorkflowLayoutEngine);
  const currentSet = useMemo(() => new Set(runtimeCurrentNodeIds), [runtimeCurrentNodeIds]);
  const nodesInitialized = useNodesInitialized();

  // P1-5: measured node types report rendered DOM sizes back to the layout
  // hook so the second pass of the layout uses real geometry.
  const measuredNodeTypes: NodeTypes = useMemo(
    () => ({
      stageRegion: wrapNodeForMeasurement(WorkflowStageRegionNode, layout.reportMeasuredSize),
      agentTask: wrapNodeForMeasurement(WorkflowAgentTaskNode, layout.reportMeasuredSize),
      humanGate: wrapNodeForMeasurement(WorkflowHumanGateNode, layout.reportMeasuredSize),
      systemTask: wrapNodeForMeasurement(WorkflowSystemTaskNode, layout.reportMeasuredSize),
      decision: wrapNodeForMeasurement(WorkflowDecisionNode, layout.reportMeasuredSize),
      startEnd: wrapNodeForMeasurement(WorkflowStartEndNode, layout.reportMeasuredSize),
    }),
    [layout.reportMeasuredSize],
  );

  // Fit protocol: fit exactly once when the first layout commits AND the committed
  // nodes have entered React Flow internals. Never re-fit for runtime-only updates
  // (status/selection/run events). `fitAll` from controls stays explicit.
  useWorkflowInitialFit({
    initialFitRevision: layout.initialFitRevision,
    layoutRevision: layout.layoutRevision,
    nodesInitialized,
    fit: () => {
      void rf.fitView({ padding: 0.08 });
    },
    acknowledgeInitialFit: layout.acknowledgeInitialFit,
  });

  const stageIndexById = useMemo(() => {
    const map = new Map<string, number>();
    graph.stages.forEach((s, i) => map.set(s.stageId, i));
    return map;
  }, [graph.stages]);

  const nodes: Node[] = useMemo(
    () =>
      layout.nodes.map((node) => {
        if (node.kind === "stage") {
          return {
            id: node.id,
            type: "stageRegion",
            position: { x: node.x, y: node.y },
            data: {
              label: node.label,
              stageTone: node.stageTone,
              stageIndex: stageIndexById.get(node.stageId) ?? 0,
            },
            style: { width: node.width, height: node.height },
            selectable: false,
            draggable: false,
            zIndex: 0,
          } satisfies Node;
        }
        const parentId = node.parentStageId;
        return {
          id: node.id,
          type: visualToRfType(node.visualKind),
          position: {
            x: parentId != null ? (node.relativeX ?? 0) : node.x,
            y: parentId != null ? (node.relativeY ?? 0) : node.y,
          },
          parentId,
          extent: parentId ? ("parent" as const) : undefined,
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
            portSides: node.portSides,
          },
          style: { width: node.width, height: node.height },
          selectable: true,
          draggable: false,
          selected: node.id === selectedNodeId,
          zIndex: 2,
        } satisfies Node;
      }),
    [layout.nodes, currentSet, selectedNodeId, stageIndexById],
  );

  const edges: Edge[] = useMemo(
    () =>
      layout.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        type: "workflowSemantic",
        animated: edge.pathState === "active" || edge.pathState === "attention",
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 16,
          height: 16,
          color:
            edge.pathState === "danger"
              ? "var(--state-error, #dc2626)"
              : edge.pathState === "attention"
                ? "var(--state-warning, #d97706)"
                : edge.pathState === "active"
                  ? "var(--accent-cool, #2563eb)"
                  : edge.pathState === "traversed"
                    ? "var(--fg-secondary, #52525b)"
                    : "var(--vui-border-strong, #a1a1aa)",
        },
        data: {
          label: edge.label,
          semanticKind: edge.semanticKind,
          pathState: edge.pathState,
          labelAlwaysVisible: edge.labelAlwaysVisible,
          sections: edge.sections,
          labelBounds: edge.labelBounds,
        },
        zIndex: 1,
      })),
    [layout.edges],
  );

  const onSelectionChange = useCallback(
    (params: OnSelectionChangeParams) => {
      const task = params.nodes.find((n: Node) => n.type !== "stageRegion");
      onSelectNode?.(task?.id ?? null);
    },
    [onSelectNode],
  );

  const onPaneClick = useCallback(() => {
    onSelectNode?.(null);
  }, [onSelectNode]);

  const fillHost = height === "100%";

  return (
    <div
      className={cn(
        "relative min-h-0 w-full overflow-hidden rounded-xl border border-vui-border bg-vui-surface-workspace",
        fillHost ? "h-full min-h-0 w-full flex-1" : null,
        className,
      )}
      style={fillHost ? { height: "100%", minHeight: 0 } : { height }}
      data-vui="workflow-canvas"
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
          minZoom={0.35}
          maxZoom={1.6}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          panOnScroll
          zoomOnScroll
          onSelectionChange={onSelectionChange}
          onPaneClick={onPaneClick}
          proOptions={{ hideAttribution: true }}
          style={{ width: "100%", height: "100%" }}
          className={fillHost ? "h-full w-full" : undefined}
          defaultEdgeOptions={{ type: "workflowSemantic" }}
        >
          <Background gap={20} size={1} color="var(--vui-border, #e4e4e7)" />
          <WorkflowCanvasControls
            runtimeCurrentNodeIds={runtimeCurrentNodeIds}
            onFitAll={fitAll}
          />
          {showLegend ? <WorkflowCanvasLegend /> : null}
        </ReactFlow>
      </div>
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
