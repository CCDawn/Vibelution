import type { CSSProperties } from "react";

import type { TeamCanvasNode } from "../../api/types";

export const NODE_WIDTH = 172;
export const NODE_HEIGHT = 92;
export const CANVAS_VIEWPORT_WIDTH = 1180;
export const CANVAS_VIEWPORT_HEIGHT = 760;
export const RESEARCH_CANVAS_AUTO_LAYOUT_START_X = 64;
export const RESEARCH_CANVAS_AUTO_LAYOUT_CENTER_Y = 250;
export const RESEARCH_CANVAS_AUTO_LAYOUT_LAYER_GAP = 216;
export const RESEARCH_CANVAS_AUTO_LAYOUT_ROW_GAP = 122;

export type TeamsRouteDynamicVariable =
  | "--canvas-offset-x"
  | "--canvas-offset-y"
  | "--canvas-scale"
  | "--node-x"
  | "--node-y";

export type TeamsRouteDynamicStyle = CSSProperties & Partial<Record<TeamsRouteDynamicVariable, string>>;

export type CanvasViewportStyle = TeamsRouteDynamicStyle & Record<
  "--canvas-offset-x" | "--canvas-offset-y" | "--canvas-scale",
  string
>;

export type NodePositionStyle = TeamsRouteDynamicStyle & Record<"--node-x" | "--node-y", string>;

export type CanvasFrameSize = {
  width: number;
  height: number;
};

export type ResearchCanvasLayoutMode = "auto" | "source";

export function isCommunicationEdge(edge: { type: string }) {
  return edge.type === "communication" || edge.type === "collaborates_with";
}

export function canvasNodeLayoutText(node: TeamCanvasNode) {
  return [
    node.id,
    node.label,
    node.role,
    node.purpose,
    node.agentCode,
    node.agentName,
    node.responsibilities?.join(" "),
  ].filter(Boolean).join(" ").toLowerCase();
}

export function researchCanvasRoleLayer(node: TeamCanvasNode) {
  const text = canvasNodeLayoutText(node);
  if (
    text.includes("ceo")
    || text.includes("lead")
    || text.includes("负责人")
    || text.includes("research_coordination")
    || text.includes("data_intake_coordinator")
  ) {
    return 0;
  }
  if (text.includes("organization") || text.includes("advisor") || text.includes("顾问")) {
    return 1;
  }
  if (
    text.includes("source_finder")
    || text.includes("资料寻找")
    || text.includes("寻找")
    || text.includes("下载")
    || text.includes("登记")
    || text.includes("search")
    || text.includes("搜集")
  ) {
    return 2;
  }
  if (
    text.includes("source_extractor")
    || text.includes("资料提炼")
    || text.includes("extract")
    || text.includes("抽取")
    || text.includes("提炼")
  ) {
    return 3;
  }
  if (
    text.includes("source_relation_mapper")
    || text.includes("资料关系")
    || text.includes("关系整理")
    || text.includes("mapping")
    || text.includes("映射")
  ) {
    return 4;
  }
  if (
    text.includes("source_ingestor")
    || text.includes("资料入库")
    || text.includes("入库")
  ) {
    return 5;
  }
  return null;
}

export function teamCanvasNodeSortKey(node: TeamCanvasNode) {
  return `${researchCanvasRoleLayer(node) ?? 99}:${node.label || ""}:${node.agentCode || ""}:${node.id}`;
}

export function autoLayoutResearchCanvasNodes(
  nodes: TeamCanvasNode[],
  edges: Array<{ source: string; target: string; type?: string }>,
) {
  if (nodes.length <= 1) {
    return nodes.map((node) => ({ ...node }));
  }
  const nodeIds = new Set(nodes.map((node) => node.id));
  const outgoing = new Map<string, string[]>();
  const incomingCount = new Map(nodes.map((node) => [node.id, 0]));
  edges
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target) && !isCommunicationEdge({ type: edge.type || "" }))
    .forEach((edge) => {
      outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target]);
      incomingCount.set(edge.target, (incomingCount.get(edge.target) ?? 0) + 1);
    });

  const graphDepth = new Map(nodes.map((node) => [node.id, 0]));
  const queue = nodes
    .filter((node) => (incomingCount.get(node.id) ?? 0) === 0)
    .sort((left, right) => teamCanvasNodeSortKey(left).localeCompare(teamCanvasNodeSortKey(right)))
    .map((node) => node.id);
  const visited = new Set<string>();

  while (queue.length) {
    const nodeId = queue.shift();
    if (!nodeId || visited.has(nodeId)) {
      continue;
    }
    visited.add(nodeId);
    for (const targetId of outgoing.get(nodeId) ?? []) {
      graphDepth.set(targetId, Math.max(graphDepth.get(targetId) ?? 0, (graphDepth.get(nodeId) ?? 0) + 1));
      incomingCount.set(targetId, Math.max(0, (incomingCount.get(targetId) ?? 0) - 1));
      if ((incomingCount.get(targetId) ?? 0) === 0) {
        queue.push(targetId);
      }
    }
  }

  const layers = new Map<number, TeamCanvasNode[]>();
  for (const node of nodes) {
    const roleLayer = researchCanvasRoleLayer(node);
    const layer = Math.max(roleLayer ?? 0, graphDepth.get(node.id) ?? 0);
    layers.set(layer, [...(layers.get(layer) ?? []), node]);
  }

  const positions = new Map<string, { x: number; y: number }>();
  Array.from(layers.entries())
    .sort(([leftLayer], [rightLayer]) => leftLayer - rightLayer)
    .forEach(([layer, layerNodes]) => {
      const sortedNodes = [...layerNodes].sort((left, right) => teamCanvasNodeSortKey(left).localeCompare(teamCanvasNodeSortKey(right)));
      const layerHeight = (sortedNodes.length - 1) * RESEARCH_CANVAS_AUTO_LAYOUT_ROW_GAP;
      const startY = Math.max(56, RESEARCH_CANVAS_AUTO_LAYOUT_CENTER_Y - layerHeight / 2);
      sortedNodes.forEach((node, index) => {
        positions.set(node.id, {
          x: Math.round(RESEARCH_CANVAS_AUTO_LAYOUT_START_X + layer * RESEARCH_CANVAS_AUTO_LAYOUT_LAYER_GAP),
          y: Math.round(startY + index * RESEARCH_CANVAS_AUTO_LAYOUT_ROW_GAP),
        });
      });
    });

  return nodes.map((node) => ({
    ...node,
    ...(positions.get(node.id) ?? {}),
  }));
}

export function canvasViewStyle(nodes: TeamCanvasNode[], frameSize?: CanvasFrameSize): CanvasViewportStyle {
  if (!nodes.length) {
    return {
      "--canvas-offset-x": "0px",
      "--canvas-offset-y": "0px",
      "--canvas-scale": "1",
    };
  }
  const minX = Math.min(...nodes.map((node) => node.x));
  const minY = Math.min(...nodes.map((node) => node.y));
  const maxX = Math.max(...nodes.map((node) => node.x + NODE_WIDTH));
  const maxY = Math.max(...nodes.map((node) => node.y + NODE_HEIGHT));
  const boundsWidth = maxX - minX;
  const boundsHeight = maxY - minY;
  const frameWidth = Math.max(420, Math.round(frameSize?.width || CANVAS_VIEWPORT_WIDTH));
  const frameHeight = Math.max(360, Math.round(frameSize?.height || CANVAS_VIEWPORT_HEIGHT));
  const scale = Math.min(
    1,
    Math.max(
      0.58,
      Math.min((frameWidth - 72) / Math.max(boundsWidth, 1), (frameHeight - 104) / Math.max(boundsHeight, 1)),
    ),
  );
  const targetX = Math.max(40, Math.round((frameWidth / scale - boundsWidth) / 2));
  const targetY = Math.max(54, Math.round((frameHeight / scale - boundsHeight) / 2));
  return {
    "--canvas-offset-x": `${Math.round(targetX - minX)}px`,
    "--canvas-offset-y": `${Math.round(targetY - minY)}px`,
    "--canvas-scale": scale.toFixed(3),
  };
}

export function teamCanvasNodeStyle(node: Pick<TeamCanvasNode, "x" | "y">): NodePositionStyle {
  return {
    "--node-x": `${node.x}px`,
    "--node-y": `${node.y}px`,
  };
}

export function canvasStyleScale(style: CanvasViewportStyle) {
  const parsed = Number(style["--canvas-scale"]);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

export function nodeBoundaryPoint(center: { x: number; y: number }, direction: { x: number; y: number }) {
  const halfWidth = NODE_WIDTH / 2;
  const halfHeight = NODE_HEIGHT / 2;
  const scaleX = Math.abs(direction.x) > 0.0001 ? halfWidth / Math.abs(direction.x) : Number.POSITIVE_INFINITY;
  const scaleY = Math.abs(direction.y) > 0.0001 ? halfHeight / Math.abs(direction.y) : Number.POSITIVE_INFINITY;
  const distanceToRectEdge = Math.min(scaleX, scaleY);
  return {
    x: center.x + direction.x * distanceToRectEdge,
    y: center.y + direction.y * distanceToRectEdge,
  };
}

export function edgeLine(
  edge: { id?: string; source: string; target: string; type?: string },
  nodes: TeamCanvasNode[],
  visiblePeerEdges: Array<{ id?: string; source: string; target: string; type?: string }> = [],
) {
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  if (!source || !target) {
    return null;
  }
  const sourceCenter = {
    x: source.x + NODE_WIDTH / 2,
    y: source.y + NODE_HEIGHT / 2,
  };
  const targetCenter = {
    x: target.x + NODE_WIDTH / 2,
    y: target.y + NODE_HEIGHT / 2,
  };
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const distance = Math.hypot(dx, dy) || 1;
  const unitX = dx / distance;
  const unitY = dy / distance;
  const sourcePoint = nodeBoundaryPoint(sourceCenter, { x: unitX, y: unitY });
  const targetPoint = nodeBoundaryPoint(targetCenter, { x: -unitX, y: -unitY });
  const x1 = sourcePoint.x;
  const y1 = sourcePoint.y;
  const x2 = targetPoint.x;
  const y2 = targetPoint.y;
  const normalX = -unitY;
  const normalY = unitX;
  const peerEdges = visiblePeerEdges.filter(
    (peerEdge) =>
      (peerEdge.source === edge.source && peerEdge.target === edge.target)
      || (peerEdge.source === edge.target && peerEdge.target === edge.source),
  );
  const peerIndex = Math.max(0, peerEdges.findIndex((peerEdge) => peerEdge.id === edge.id));
  const pairSpread = peerEdges.length > 1 ? (peerIndex - (peerEdges.length - 1) / 2) * 20 : 0;
  const sourcePeerEdges = visiblePeerEdges.filter((peerEdge) => peerEdge.source === edge.source);
  const sourcePeerIndex = Math.max(0, sourcePeerEdges.findIndex((peerEdge) => peerEdge.id === edge.id));
  const sourceFanSpread = sourcePeerEdges.length > 1 ? (sourcePeerIndex - (sourcePeerEdges.length - 1) / 2) * 8 : 0;
  const curve = (isCommunicationEdge({ type: edge.type || "" }) ? 42 : 24) + pairSpread + sourceFanSpread;
  const cx = (x1 + x2) / 2 + normalX * curve;
  const cy = (y1 + y2) / 2 + normalY * curve;
  return { x1, y1, x2, y2, cx, cy };
}

export function nextNodeId(nodes: TeamCanvasNode[]) {
  const ids = new Set(nodes.map((node) => node.id));
  let index = nodes.length + 1;
  let candidate = `node-${index}`;
  while (ids.has(candidate)) {
    index += 1;
    candidate = `node-${index}`;
  }
  return candidate;
}
