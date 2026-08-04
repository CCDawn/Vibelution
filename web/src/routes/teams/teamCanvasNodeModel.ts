/**
 * Pure organization-canvas node edits.
 * Drag frame scheduling and mutation.mutate stay outside this module.
 */
import type { TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import { nextNodeId } from "./canvasGeometry";
import type { NodeDraft } from "./useTeamsShellCanvasWorkspace";

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
