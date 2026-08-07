/**
 * @xyflow/react renderer for VWorkflowCanvas — only place React Flow may be imported.
 */
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type OnSelectionChangeParams,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useMemo } from "react";

import { cn } from "../../lib/cn";
import {
  layoutWorkflowCanvas,
  type WorkflowLayoutInput,
} from "./workflowCanvasLayout";

export type ShadcnWorkflowCanvasProps = {
  graph: WorkflowLayoutInput;
  selectedNodeId?: string | null;
  runtimeCurrentNodeIds?: string[];
  onSelectNode?: (nodeId: string | null) => void;
  className?: string;
  /**
   * Canvas host size. Prefer `"100%"` inside a filled recipe cell (min-h-0 + h-full).
   * Avoid fixed px heights in page shells — that leaves dead space below the graph.
   */
  height?: number | string;
};

function StageNodeView(props: NodeProps) {
  const label = String(props.data.label ?? "");
  return (
    <div
      className="h-full w-full rounded-xl border border-vui-border bg-vui-surface-region/80"
      data-vui="workflow-stage-region"
    >
      <div className="border-b border-vui-border px-3 py-2 text-xs font-semibold tracking-wide text-vui-fg">
        {label}
      </div>
    </div>
  );
}

function TaskNodeView(props: NodeProps) {
  const label = String(props.data.label ?? "");
  const actorKind = String(props.data.actorKind ?? "agent");
  const isCurrent = Boolean(props.data.isCurrent);
  const isSelected = Boolean(props.selected);
  return (
    <div
      className={cn(
        "relative h-full w-full rounded-lg border bg-vui-surface-card px-3 py-2 shadow-sm",
        isCurrent ? "border-vui-fg ring-2 ring-vui-fg/30" : "border-vui-border",
        isSelected ? "outline outline-1 outline-vui-fg" : "",
      )}
      data-vui="workflow-task-node"
      data-actor={actorKind}
      data-current={isCurrent ? "true" : "false"}
    >
      <Handle type="target" position={Position.Left} className="!bg-vui-fg/40 !h-2 !w-2 !border-0" />
      <div className="text-[10px] uppercase tracking-wide text-vui-muted">{actorKind}</div>
      <div className="text-sm font-semibold text-vui-fg">{label}</div>
      <Handle type="source" position={Position.Right} className="!bg-vui-fg/40 !h-2 !w-2 !border-0" />
    </div>
  );
}

const nodeTypes = {
  stageRegion: StageNodeView,
  taskNode: TaskNodeView,
};

export function ShadcnWorkflowCanvas({
  graph,
  selectedNodeId = null,
  runtimeCurrentNodeIds = [],
  onSelectNode,
  className,
  height = "100%",
}: ShadcnWorkflowCanvasProps) {
  const layout = useMemo(() => layoutWorkflowCanvas(graph), [graph]);
  const currentSet = useMemo(() => new Set(runtimeCurrentNodeIds), [runtimeCurrentNodeIds]);

  const nodes: Node[] = useMemo(
    () =>
      layout.nodes.map((node) => ({
        id: node.id,
        type: node.kind === "stage" ? "stageRegion" : "taskNode",
        position: { x: node.x, y: node.y },
        data: {
          label: node.label,
          actorKind: node.actorKind,
          isCurrent: currentSet.has(node.id),
        },
        style: { width: node.width, height: node.height },
        selectable: node.kind === "task",
        draggable: false,
        selected: node.kind === "task" && node.id === selectedNodeId,
        parentId: node.kind === "task" ? undefined : undefined,
        zIndex: node.kind === "stage" ? 0 : 1,
      })),
    [layout.nodes, currentSet, selectedNodeId],
  );

  const edges: Edge[] = useMemo(
    () =>
      layout.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.label,
        type: "smoothstep",
        animated: currentSet.has(edge.source) || currentSet.has(edge.target),
        style: { stroke: "var(--vui-border-strong, #a1a1aa)", strokeWidth: 1.5 },
        labelStyle: { fill: "var(--vui-muted, #71717a)", fontSize: 10 },
      })),
    [layout.edges, currentSet],
  );

  const onSelectionChange = useCallback(
    (params: OnSelectionChangeParams) => {
      const task = params.nodes.find((n: Node) => n.type === "taskNode");
      onSelectNode?.(task?.id ?? null);
    },
    [onSelectNode],
  );

  // Fill host like other workbench canvases: percentage height only works when
  // the parent chain has a real height; absolute inset fills the host cell.
  const fillHost = height === "100%";
  return (
    <div
      className={cn(
        "relative min-h-0 w-full overflow-hidden rounded-xl border border-vui-border bg-vui-surface-workspace",
        fillHost ? "h-full min-h-0 flex-1" : null,
        className,
      )}
      style={fillHost ? undefined : { height }}
      data-vui="workflow-canvas"
    >
      <div className={fillHost ? "absolute inset-0" : "h-full w-full"}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          minZoom={0.35}
          maxZoom={1.6}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          panOnScroll
          zoomOnScroll
          onSelectionChange={onSelectionChange}
          proOptions={{ hideAttribution: true }}
          style={{ width: "100%", height: "100%" }}
        >
          <Background gap={18} size={1} color="var(--vui-border, #e4e4e7)" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
