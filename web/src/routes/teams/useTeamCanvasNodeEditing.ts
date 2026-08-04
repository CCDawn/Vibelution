/**
 * Organization canvas node edit + drag commit helpers for TeamsRoute.
 * Pure canvas transforms live in teamCanvasNodeModel.
 */
import type { MutableRefObject, PointerEvent as ReactPointerEvent } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { AgentInstance, TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import type { CanvasViewportStyle } from "./canvasGeometry";
import {
  applyNodeDragDeltas,
  buildCanvasWithAppliedNodeDraft,
  buildCanvasWithDeletedNode,
  buildCanvasWithDraggedNode,
  buildCanvasWithLeadConnection,
  buildCanvasWithNewNode,
  buildCanvasWithUnboundNode,
} from "./teamCanvasNodeModel";
import type { NodeDraft, NodeDragState } from "./useTeamsShellCanvasWorkspace";

export type TeamCanvasNodeEditingContext = {
  lang: "zh" | "en";
  durableCanvas: TeamOrganizationCanvas | null | undefined;
  researchCanvasReadOnly: boolean;
  selectedNode: TeamCanvasNode | null | undefined;
  selectedTeamId: string | null | undefined;
  nodeDraft: NodeDraft;
  activeAgents: AgentInstance[];
  agentTeamMembership: Map<string, { teamId: string; teamName?: string }>;
  canvasScale: number;
  canvasViewportStyle: CanvasViewportStyle;
  dragStateRef: MutableRefObject<NodeDragState | null>;
  dragFrameRef: MutableRefObject<number>;
  setSelectedNodeId: (nodeId: string) => void;
  setNodePositionDrafts: Dispatch<SetStateAction<Record<string, { x: number; y: number }>>>;
  setLockedCanvasViewportStyle: (style: CanvasViewportStyle | null) => void;
  canvasSavePendingForTeam: (teamId: string | null | undefined) => boolean;
  saveCanvas: (nextCanvas: TeamOrganizationCanvas | null) => void;
};

export function createTeamCanvasNodeEditing(ctx: TeamCanvasNodeEditingContext) {
  const {
    lang,
    durableCanvas,
    researchCanvasReadOnly,
    selectedNode,
    selectedTeamId,
    nodeDraft,
    activeAgents,
    agentTeamMembership,
    canvasScale,
    canvasViewportStyle,
    dragStateRef,
    dragFrameRef,
    setSelectedNodeId,
    setNodePositionDrafts,
    setLockedCanvasViewportStyle,
    canvasSavePendingForTeam,
    saveCanvas,
  } = ctx;

  function addNode() {
    if (!durableCanvas || researchCanvasReadOnly) {
      return;
    }
    const next = buildCanvasWithNewNode({ canvas: durableCanvas, lang });
    saveCanvas(next.canvas);
    setSelectedNodeId(next.selectedNodeId);
  }

  function applyNodeDraft() {
    if (!durableCanvas || !selectedNode || researchCanvasReadOnly) {
      return;
    }
    const membership = nodeDraft.agentId ? agentTeamMembership.get(nodeDraft.agentId) : undefined;
    if (membership && membership.teamId !== selectedTeamId) {
      return;
    }
    const agent = activeAgents.find((item) => item.agentId === nodeDraft.agentId);
    saveCanvas(buildCanvasWithAppliedNodeDraft({
      canvas: durableCanvas,
      selectedNode,
      nodeDraft,
      agent,
    }));
  }

  function unbindSelectedNode() {
    if (!durableCanvas || !selectedNode || researchCanvasReadOnly) {
      return;
    }
    saveCanvas(buildCanvasWithUnboundNode({
      canvas: durableCanvas,
      selectedNodeId: selectedNode.id,
    }));
  }

  function deleteSelectedNode() {
    if (!durableCanvas || !selectedNode || researchCanvasReadOnly) {
      return;
    }
    const next = buildCanvasWithDeletedNode({
      canvas: durableCanvas,
      selectedNodeId: selectedNode.id,
    });
    if (!next) {
      return;
    }
    saveCanvas(next.canvas);
    setSelectedNodeId(next.selectedNodeId);
  }

  function connectFromLead() {
    if (!durableCanvas || !selectedNode || researchCanvasReadOnly) {
      return;
    }
    const next = buildCanvasWithLeadConnection({
      canvas: durableCanvas,
      selectedNodeId: selectedNode.id,
    });
    if (!next) {
      return;
    }
    saveCanvas(next);
  }

  function commitNodeDragPosition(dragState: NodeDragState) {
    setNodePositionDrafts((current) => {
      const currentPosition = current[dragState.nodeId];
      if (currentPosition?.x === dragState.currentX && currentPosition?.y === dragState.currentY) {
        return current;
      }
      return {
        ...current,
        [dragState.nodeId]: { x: dragState.currentX, y: dragState.currentY },
      };
    });
  }

  function requestNodeDragFrame(dragState: NodeDragState) {
    if (dragFrameRef.current) {
      return;
    }
    dragFrameRef.current = window.requestAnimationFrame(() => {
      dragFrameRef.current = 0;
      const activeDrag = dragStateRef.current;
      commitNodeDragPosition(activeDrag ?? dragState);
    });
  }

  function startNodeDrag(event: ReactPointerEvent<HTMLButtonElement>, node: TeamCanvasNode) {
    if (!durableCanvas || canvasSavePendingForTeam(durableCanvas.teamId) || researchCanvasReadOnly) {
      return;
    }
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setSelectedNodeId(node.id);
    setLockedCanvasViewportStyle(canvasViewportStyle);
    dragStateRef.current = {
      nodeId: node.id,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: node.x,
      startY: node.y,
      currentX: node.x,
      currentY: node.y,
      scale: canvasScale,
      moved: false,
    };
  }

  function moveNodeDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const dragState = dragStateRef.current;
    if (!dragState) {
      return;
    }
    const next = applyNodeDragDeltas({
      startX: dragState.startX,
      startY: dragState.startY,
      startClientX: dragState.startClientX,
      startClientY: dragState.startClientY,
      clientX: event.clientX,
      clientY: event.clientY,
      scale: dragState.scale,
    });
    dragState.moved = dragState.moved || next.moved;
    dragState.currentX = next.x;
    dragState.currentY = next.y;
    requestNodeDragFrame(dragState);
  }

  function finishNodeDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || !durableCanvas) {
      return;
    }
    event.currentTarget.releasePointerCapture(event.pointerId);
    dragStateRef.current = null;
    if (dragFrameRef.current) {
      window.cancelAnimationFrame(dragFrameRef.current);
      dragFrameRef.current = 0;
    }
    if (!dragState.moved) {
      return;
    }
    commitNodeDragPosition(dragState);
    saveCanvas(buildCanvasWithDraggedNode({
      canvas: durableCanvas,
      nodeId: dragState.nodeId,
      x: dragState.currentX,
      y: dragState.currentY,
    }));
  }

  return {
    addNode,
    applyNodeDraft,
    unbindSelectedNode,
    deleteSelectedNode,
    connectFromLead,
    startNodeDrag,
    moveNodeDrag,
    finishNodeDrag,
  };
}
