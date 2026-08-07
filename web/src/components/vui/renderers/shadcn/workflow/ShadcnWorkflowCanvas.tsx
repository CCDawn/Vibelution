/**
 * @xyflow/react composition for VWorkflowCanvas.
 * Node/edge/layout/state live in sibling modules — this file only wires them.
 */
import {
  Background,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeTypes,
  type EdgeTypes,
  type OnSelectionChangeParams,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useMemo, useRef } from "react";

import { cn } from "../../../lib/cn";
import type { WorkflowLayoutInput } from "../../../product/workflow/workflowCanvasTypes";
import { layoutWorkflowCanvas } from "./workflowCanvasLayout";
import { WorkflowAgentTaskNode } from "./WorkflowAgentTaskNode";
import { WorkflowCanvasControls } from "./WorkflowCanvasControls";
import { WorkflowCanvasLegend } from "./WorkflowCanvasLegend";
import { WorkflowDecisionNode } from "./WorkflowDecisionNode";
import { WorkflowHumanGateNode } from "./WorkflowHumanGateNode";
import { WorkflowSemanticEdge } from "./WorkflowSemanticEdge";
import { WorkflowStageRegionNode } from "./WorkflowStageRegionNode";
import { WorkflowStartEndNode } from "./WorkflowStartEndNode";
import { WorkflowSystemTaskNode } from "./WorkflowSystemTaskNode";

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

const nodeTypes: NodeTypes = {
  stageRegion: WorkflowStageRegionNode,
  agentTask: WorkflowAgentTaskNode,
  humanGate: WorkflowHumanGateNode,
  systemTask: WorkflowSystemTaskNode,
  decision: WorkflowDecisionNode,
  startEnd: WorkflowStartEndNode,
};

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
  const layout = useMemo(() => layoutWorkflowCanvas(graph), [graph]);
  const currentSet = useMemo(() => new Set(runtimeCurrentNodeIds), [runtimeCurrentNodeIds]);
  const fitOnceRef = useRef(false);

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
          },
          style: { width: node.width, height: node.height },
          selectable: true,
          draggable: false,
          selected: node.id === selectedNodeId,
          zIndex: 1,
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
        },
        zIndex: 2,
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
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.08, minZoom: 0.45, maxZoom: 1.35 }}
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
          onInit={(instance) => {
            if (!fitOnceRef.current) {
              fitOnceRef.current = true;
              void instance.fitView({ padding: 0.08 });
            }
          }}
        >
          <Background gap={20} size={1} color="var(--vui-border, #e4e4e7)" />
          <WorkflowCanvasControls runtimeCurrentNodeIds={runtimeCurrentNodeIds} />
          {showLegend ? <WorkflowCanvasLegend /> : null}
        </ReactFlow>
      </div>
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
