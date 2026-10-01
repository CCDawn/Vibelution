/**
 * Pure organization-canvas node/edge edits.
 * Drag frame scheduling and mutation.mutate stay outside this module.
 */
import type { TeamCanvasEdge, TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import { nextNodeId } from "./canvasGeometry";
import type { NodeDraft } from "./useTeamsShellCanvasWorkspace";

/** Mirror of core canvas_primitives.EDGE_TYPES; backend silently demotes unknown types. */
export const TEAM_CANVAS_EDGE_TYPES = [
  "reports_to",
  "communication",
  "collaborates_with",
  "delegates_to",
  "observes",
  "supports",
] as const;

export type TeamCanvasEdgeType = (typeof TEAM_CANVAS_EDGE_TYPES)[number];

export type CanvasNodeAgent = {
  agentId: string;
  agentCode?: string;
  displayName?: string;
};

export function buildCanvasWithNewNode(options: {
  canvas: TeamOrganizationCanvas;
  lang: "zh" | "en";
}): { canvas: TeamOrganizationCanvas; selectedNodeId: string } {
  const { canvas, lang } = options;
  const id = nextNodeId(canvas.nodes);
  return {
    selectedNodeId: id,
    canvas: {
      ...canvas,
      nodes: [
        ...canvas.nodes,
        {
          id,
          label: lang === "zh" ? "新角色" : "New role",
          type: "role",
          status: "unbound",
          x: 140 + canvas.nodes.length * 54,
          y: 150 + canvas.nodes.length * 36,
          agentId: "",
          agentCode: "",
          agentName: "",
          role: "",
          purpose: "",
        },
      ],
    },
  };
}

export function buildCanvasWithAppliedNodeDraft(options: {
  canvas: TeamOrganizationCanvas;
  selectedNode: TeamCanvasNode;
  nodeDraft: NodeDraft;
  agent: CanvasNodeAgent | undefined;
}): TeamOrganizationCanvas {
  const { canvas, selectedNode, nodeDraft, agent } = options;
  return {
    ...canvas,
    nodes: canvas.nodes.map((node) =>
      node.id === selectedNode.id
        ? {
            ...node,
            label: nodeDraft.label.trim() || agent?.displayName || node.label,
            role: nodeDraft.role.trim(),
            purpose: nodeDraft.purpose.trim(),
            agentId: nodeDraft.agentId,
            agentCode: agent?.agentCode ?? "",
            agentName: agent?.displayName ?? "",
            type: nodeDraft.agentId ? "agent" : "role",
            status: nodeDraft.agentId ? "bound" : "unbound",
          }
        : node,
    ),
  };
}

export function buildCanvasWithUnboundNode(options: {
  canvas: TeamOrganizationCanvas;
  selectedNodeId: string;
}): TeamOrganizationCanvas {
  const { canvas, selectedNodeId } = options;
  return {
    ...canvas,
    nodes: canvas.nodes.map((node) =>
      node.id === selectedNodeId
        ? {
            ...node,
            agentId: "",
            agentCode: "",
            agentName: "",
            type: "role",
            status: "unbound",
          }
        : node,
    ),
  };
}

export function buildCanvasWithDeletedNode(options: {
  canvas: TeamOrganizationCanvas;
  selectedNodeId: string;
}): { canvas: TeamOrganizationCanvas; selectedNodeId: string } | null {
  const { canvas, selectedNodeId } = options;
  if (canvas.nodes.length <= 1) {
    return null;
  }
  const nextNodes = canvas.nodes.filter((node) => node.id !== selectedNodeId);
  return {
    selectedNodeId: nextNodes[0]?.id ?? "",
    canvas: {
      ...canvas,
      nodes: nextNodes,
      edges: canvas.edges.filter((edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId),
    },
  };
}

export function buildCanvasWithLeadConnection(options: {
  canvas: TeamOrganizationCanvas;
  selectedNodeId: string;
}): TeamOrganizationCanvas | null {
  const { canvas, selectedNodeId } = options;
  if (canvas.nodes.length < 2) {
    return null;
  }
  const source = canvas.nodes[0];
  if (
    !source
    || source.id === selectedNodeId
    || canvas.edges.some((edge) => edge.source === source.id && edge.target === selectedNodeId)
  ) {
    return null;
  }
  return {
    ...canvas,
    edges: [
      ...canvas.edges,
      {
        id: `${source.id}-${selectedNodeId}`,
        source: source.id,
        target: selectedNodeId,
        label: "",
        type: "reports_to",
      },
    ],
  };
}

export function buildCanvasWithDraggedNode(options: {
  canvas: TeamOrganizationCanvas;
  nodeId: string;
  x: number;
  y: number;
}): TeamOrganizationCanvas {
  const { canvas, nodeId, x, y } = options;
  return {
    ...canvas,
    nodes: canvas.nodes.map((node) => (node.id === nodeId ? { ...node, x, y } : node)),
  };
}

/**
 * Deterministic edge id in the backend style (`edge-<source>-<target>`), with a
 * numeric suffix when the base id is already taken.
 */
export function nextEdgeId(edges: TeamCanvasEdge[], sourceNodeId: string, targetNodeId: string) {
  const ids = new Set(edges.map((edge) => edge.id));
  const base = `edge-${sourceNodeId}-${targetNodeId}`;
  if (!ids.has(base)) {
    return base;
  }
  let index = 2;
  while (ids.has(`${base}-${index}`)) {
    index += 1;
  }
  return `${base}-${index}`;
}

/**
 * Connect two existing nodes with a new edge.
 * Returns null when endpoints are missing/identical, the type is outside the
 * backend whitelist, or a same-direction edge already exists (duplicate
 * connects are rejected, not silently merged).
 */
export function buildCanvasWithEdge(options: {
  canvas: TeamOrganizationCanvas;
  sourceNodeId: string;
  targetNodeId: string;
  type?: string;
  label?: string;
}): TeamOrganizationCanvas | null {
  const { canvas, sourceNodeId, targetNodeId, type, label } = options;
  const nodeIds = new Set(canvas.nodes.map((node) => node.id));
  if (!sourceNodeId || !targetNodeId || sourceNodeId === targetNodeId) {
    return null;
  }
  if (!nodeIds.has(sourceNodeId) || !nodeIds.has(targetNodeId)) {
    return null;
  }
  const requestedType = type || "communication";
  if (!(TEAM_CANVAS_EDGE_TYPES as readonly string[]).includes(requestedType)) {
    return null;
  }
  const edgeType = requestedType as TeamCanvasEdgeType;
  if (canvas.edges.some((edge) => edge.source === sourceNodeId && edge.target === targetNodeId)) {
    return null;
  }
  return {
    ...canvas,
    edges: [
      ...canvas.edges,
      {
        id: nextEdgeId(canvas.edges, sourceNodeId, targetNodeId),
        source: sourceNodeId,
        target: targetNodeId,
        label: String(label || "").trim(),
        type: edgeType,
      },
    ],
  };
}

export function buildCanvasWithoutEdge(options: {
  canvas: TeamOrganizationCanvas;
  edgeId: string;
}): TeamOrganizationCanvas | null {
  const { canvas, edgeId } = options;
  if (!canvas.edges.some((edge) => edge.id === edgeId)) {
    return null;
  }
  return {
    ...canvas,
    edges: canvas.edges.filter((edge) => edge.id !== edgeId),
  };
}

export function buildCanvasWithRelabeledEdge(options: {
  canvas: TeamOrganizationCanvas;
  edgeId: string;
  label: string;
}): TeamOrganizationCanvas | null {
  const { canvas, edgeId, label } = options;
  if (!canvas.edges.some((edge) => edge.id === edgeId)) {
    return null;
  }
  const nextLabel = String(label || "").trim();
  return {
    ...canvas,
    edges: canvas.edges.map((edge) => (edge.id === edgeId ? { ...edge, label: nextLabel } : edge)),
  };
}

/**
 * Rename a canvas node's display label only.
 *
 * `label` is the one node field that survives both backend normalize
 * (trim_lines max_lines=1, non-empty kept verbatim) and the member-binding
 * projection (`_project_member_bindings_onto_nodes` only rewrites agentId/role,
 * never label). An empty label is rejected because the backend would replace it
 * with the agent displayName or a positional default.
 */
export function buildCanvasWithRelabeledNode(options: {
  canvas: TeamOrganizationCanvas;
  nodeId: string;
  label: string;
}): TeamOrganizationCanvas | null {
  const { canvas, nodeId, label } = options;
  const node = canvas.nodes.find((item) => item.id === nodeId);
  const nextLabel = String(label || "").trim();
  if (!node || !nextLabel) {
    return null;
  }
  if (nextLabel === node.label) {
    return canvas;
  }
  return {
    ...canvas,
    nodes: canvas.nodes.map((item) => (item.id === nodeId ? { ...item, label: nextLabel } : item)),
  };
}

export function applyNodeDragDeltas(options: {
  startX: number;
  startY: number;
  startClientX: number;
  startClientY: number;
  clientX: number;
  clientY: number;
  scale: number;
}): { x: number; y: number; moved: boolean } {
  const { startX, startY, startClientX, startClientY, clientX, clientY, scale } = options;
  const safeScale = scale > 0 ? scale : 1;
  const deltaX = (clientX - startClientX) / safeScale;
  const deltaY = (clientY - startClientY) / safeScale;
  return {
    x: Math.max(0, Math.round(startX + deltaX)),
    y: Math.max(0, Math.round(startY + deltaY)),
    moved: Math.abs(deltaX) > 2 || Math.abs(deltaY) > 2,
  };
}
