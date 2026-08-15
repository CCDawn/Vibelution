/**
 * Teams shell + organization canvas state machine.
 * Phase 3:
 * - useTeamsShellCanvasWorkspace: shell selection, communication drafts, canvas UI state/refs
 * - useTeamsCanvasProjection: canvas query + display projection + node-draft sync
 *
 * Mutations / drag commit / save remain in TeamsRoute and use setters/refs from here.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { queryKeys } from "../../api/queryKeys";
import { fetchTeamCanvas } from "../../api/teams";
import type { Team, TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import {
  canvasFromKnownTeamId,
  canvasFromTeamOrFallback,
  memberCanvasFromTeam,
} from "../TeamsRoute.canvasData";
import {
  CANVAS_VIEWPORT_HEIGHT,
  CANVAS_VIEWPORT_WIDTH,
  autoLayoutResearchCanvasNodes,
  canvasStyleScale,
  canvasViewStyle,
  isCommunicationEdge,
  type CanvasFrameSize,
  type CanvasViewportStyle,
  type ResearchCanvasLayoutMode,
} from "./canvasGeometry";
import { resolveTeamCanvasQueryEnabled } from "./teamDetailLoadPolicy";
import type { ResearchWorkspaceView } from "./researchWorkspaceModel";
import {
  parseTeamShellMode,
  teamShellModeFromResearchView,
  type TeamShellMode,
} from "./teamShellModel";

export type NodeDraft = {
  label: string;
  role: string;
  purpose: string;
  agentId: string;
};

export type NodeDragState = {
  nodeId: string;
  startClientX: number;
  startClientY: number;
  startX: number;
  startY: number;
  currentX: number;
  currentY: number;
  scale: number;
  moved: boolean;
};

export type UseTeamsShellCanvasWorkspaceInput = {
  forcedResearchWorkspaceView?: ResearchWorkspaceView;
  requestedResearchWorkspaceView: ResearchWorkspaceView | null;
  requestedTeamShellMode: TeamShellMode | null;
  requestedVisibleTeamId: string;
  requestedVisibleAgentTeamId: string;
  visibleTeamIds: Set<string>;
  fallbackVisibleTeamId: string;
};

const EMPTY_NODE_DRAFT: NodeDraft = { label: "", role: "", purpose: "", agentId: "" };

export function useTeamsShellCanvasWorkspace(input: UseTeamsShellCanvasWorkspaceInput) {
  const {
    forcedResearchWorkspaceView,
    requestedResearchWorkspaceView,
    requestedTeamShellMode,
    requestedVisibleTeamId,
    requestedVisibleAgentTeamId,
    visibleTeamIds,
    fallbackVisibleTeamId,
  } = input;

  const [selectedTeamId, setSelectedTeamId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [nodeDraft, setNodeDraft] = useState<NodeDraft>(EMPTY_NODE_DRAFT);
  const [teamMessage, setTeamMessage] = useState("");
  const [teamInterrupt, setTeamInterrupt] = useState(false);
  const [teamTaskTopic, setTeamTaskTopic] = useState("");
  const [showCommunicationEdges, setShowCommunicationEdges] = useState(false);
  const [researchCanvasLayoutMode, setResearchCanvasLayoutMode] = useState<ResearchCanvasLayoutMode>("auto");
  const [researchWorkspaceView, setResearchWorkspaceView] = useState<ResearchWorkspaceView>(
    // ADR 0006: process workflow is the default research home (not overview/org canvas).
    forcedResearchWorkspaceView ?? requestedResearchWorkspaceView ?? "workflow",
  );
  const [teamShellMode, setTeamShellMode] = useState<TeamShellMode>(
    () =>
      requestedTeamShellMode
      ?? teamShellModeFromResearchView(forcedResearchWorkspaceView ?? requestedResearchWorkspaceView)
      // End-user research home is board shell hosting the process workspace.
      ?? "board",
  );
  const [nodePositionDrafts, setNodePositionDrafts] = useState<Record<string, { x: number; y: number }>>({});
  const [canvasFrameSize, setCanvasFrameSize] = useState<CanvasFrameSize>({
    width: CANVAS_VIEWPORT_WIDTH,
    height: CANVAS_VIEWPORT_HEIGHT,
  });
  const [lockedCanvasViewportStyle, setLockedCanvasViewportStyle] = useState<CanvasViewportStyle | null>(null);

  const canvasFrameRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<NodeDragState | null>(null);
  const dragFrameRef = useRef(0);

  useEffect(() => {
    if (forcedResearchWorkspaceView) {
      setResearchWorkspaceView(forcedResearchWorkspaceView);
      return;
    }
    if (requestedResearchWorkspaceView) {
      if (
        requestedResearchWorkspaceView === "overview"
        || requestedResearchWorkspaceView === "canvas"
        || requestedResearchWorkspaceView === "experiment"
        || requestedResearchWorkspaceView === "iteration"
        || requestedResearchWorkspaceView === "knowledge_collection"
        || requestedResearchWorkspaceView === "source_collection"
        || requestedResearchWorkspaceView === "coordination"
        || requestedResearchWorkspaceView === "discussion"
      ) {
        setResearchWorkspaceView("workflow");
        return;
      }
      setResearchWorkspaceView(requestedResearchWorkspaceView);
    }
  }, [forcedResearchWorkspaceView, requestedResearchWorkspaceView]);

  // Process workflow home uses board shell (primary column = ResearchProcessWorkspace).
  useEffect(() => {
    if (
      (researchWorkspaceView === "workflow" || researchWorkspaceView === "overview")
      && teamShellMode !== "board"
    ) {
      setTeamShellMode("board");
    }
  }, [researchWorkspaceView, teamShellMode]);

  useEffect(() => {
    if (requestedVisibleTeamId) {
      setSelectedTeamId(requestedVisibleTeamId);
      return;
    }
    if (requestedVisibleAgentTeamId) {
      setSelectedTeamId(requestedVisibleAgentTeamId);
      return;
    }
    if (selectedTeamId && !visibleTeamIds.has(selectedTeamId)) {
      setSelectedTeamId(fallbackVisibleTeamId);
      return;
    }
    if (!selectedTeamId && fallbackVisibleTeamId) {
      setSelectedTeamId(fallbackVisibleTeamId);
    }
  }, [fallbackVisibleTeamId, requestedVisibleAgentTeamId, requestedVisibleTeamId, selectedTeamId, visibleTeamIds]);

  useEffect(() => {
    const element = canvasFrameRef.current;
    if (!element) {
      return;
    }
    const updateFrameSize = () => {
      setCanvasFrameSize({
        width: Math.max(420, Math.round(element.clientWidth)),
        height: Math.max(360, Math.round(element.clientHeight)),
      });
    };
    updateFrameSize();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateFrameSize);
      return () => window.removeEventListener("resize", updateFrameSize);
    }
    const observer = new ResizeObserver(updateFrameSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return {
    selectedTeamId,
    setSelectedTeamId,
    selectedNodeId,
    setSelectedNodeId,
    nodeDraft,
    setNodeDraft,
    teamMessage,
    setTeamMessage,
    teamInterrupt,
    setTeamInterrupt,
    teamTaskTopic,
    setTeamTaskTopic,
    showCommunicationEdges,
    setShowCommunicationEdges,
    researchCanvasLayoutMode,
    setResearchCanvasLayoutMode,
    researchWorkspaceView,
    setResearchWorkspaceView,
    teamShellMode,
    setTeamShellMode,
    nodePositionDrafts,
    setNodePositionDrafts,
    canvasFrameSize,
    setCanvasFrameSize,
    lockedCanvasViewportStyle,
    setLockedCanvasViewportStyle,
    canvasFrameRef,
    dragStateRef,
    dragFrameRef,
  };
}

export type TeamsShellCanvasWorkspaceApi = ReturnType<typeof useTeamsShellCanvasWorkspace>;

export type UseTeamsCanvasProjectionInput = {
  effectiveTeamId: string;
  selectedTeam: Team | null;
  researchWorkflowTeamSelected: boolean;
  researchWorkspaceView: ResearchWorkspaceView;
  teamShellMode: TeamShellMode;
  sourceCollectionStandalone: boolean;
  selectedNodeId: string;
  nodePositionDrafts: Record<string, { x: number; y: number }>;
  showCommunicationEdges: boolean;
  researchCanvasLayoutMode: ResearchCanvasLayoutMode;
  canvasFrameSize: CanvasFrameSize;
  lockedCanvasViewportStyle: CanvasViewportStyle | null;
  setNodeDraft: Dispatch<SetStateAction<NodeDraft>>;
  setNodePositionDrafts: Dispatch<SetStateAction<Record<string, { x: number; y: number }>>>;
  setLockedCanvasViewportStyle: Dispatch<SetStateAction<CanvasViewportStyle | null>>;
  dragStateRef: MutableRefObject<NodeDragState | null>;
  dragFrameRef: MutableRefObject<number>;
};

export function useTeamsCanvasProjection(input: UseTeamsCanvasProjectionInput) {
  const {
    effectiveTeamId,
    selectedTeam,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    teamShellMode,
    sourceCollectionStandalone,
    selectedNodeId,
    nodePositionDrafts,
    showCommunicationEdges,
    researchCanvasLayoutMode,
    canvasFrameSize,
    lockedCanvasViewportStyle,
    setNodeDraft,
    setNodePositionDrafts,
    setLockedCanvasViewportStyle,
    dragStateRef,
    dragFrameRef,
  } = input;

  const researchCanvasReadOnly =
    researchWorkflowTeamSelected
    && (researchWorkspaceView === "canvas" || teamShellMode === "canvas");

  const teamCanvasQueryEnabled = resolveTeamCanvasQueryEnabled({
    effectiveTeamId,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    sourceCollectionStandalone,
  });
  const teamCanvasQuery = useQuery({
    queryKey: queryKeys.teamCanvas(effectiveTeamId || "none"),
    queryFn: ({ signal }) => fetchTeamCanvas(effectiveTeamId, { signal }),
    enabled: teamCanvasQueryEnabled,
    staleTime: 10_000,
  });

  const durableCanvas = canvasFromTeamOrFallback(selectedTeam, teamCanvasQuery.data);
  const memberCanvas = useMemo(() => memberCanvasFromTeam(selectedTeam), [selectedTeam]);
  const knownTeamCanvas = useMemo(() => canvasFromKnownTeamId(effectiveTeamId), [effectiveTeamId]);
  const canvas = durableCanvas ?? memberCanvas ?? knownTeamCanvas;
  const hasWritableCanvas = Boolean(durableCanvas);
  const canvasNodes = useMemo(
    () =>
      (canvas?.nodes ?? []).map((node) => ({
        ...node,
        ...(nodePositionDrafts[node.id] ?? {}),
      })),
    [canvas, nodePositionDrafts],
  );
  const organizationEdges = useMemo(
    () => (canvas?.edges ?? []).filter((edge) => !isCommunicationEdge(edge)),
    [canvas],
  );
  const communicationEdges = useMemo(
    () => (canvas?.edges ?? []).filter((edge) => isCommunicationEdge(edge)),
    [canvas],
  );
  const autoLayoutCanvasNodes = useMemo(
    () => autoLayoutResearchCanvasNodes(canvasNodes, organizationEdges),
    [canvasNodes, organizationEdges],
  );
  const researchCanvasAutoLayoutActive = researchCanvasReadOnly && researchCanvasLayoutMode === "auto";
  const displayCanvasNodes = researchCanvasAutoLayoutActive ? autoLayoutCanvasNodes : canvasNodes;
  const selectedNode: TeamCanvasNode | null =
    displayCanvasNodes.find((node) => node.id === selectedNodeId) ?? displayCanvasNodes[0] ?? null;
  const visibleCommunicationEdges = useMemo(() => {
    if (!showCommunicationEdges) {
      return [];
    }
    if (!selectedNodeId) {
      return communicationEdges;
    }
    return communicationEdges.filter((edge) => edge.source === selectedNodeId || edge.target === selectedNodeId);
  }, [communicationEdges, selectedNodeId, showCommunicationEdges]);
  const visibleEdges = useMemo(
    () => [...organizationEdges, ...visibleCommunicationEdges],
    [organizationEdges, visibleCommunicationEdges],
  );
  const autoCanvasViewportStyle = useMemo(
    () => canvasViewStyle(displayCanvasNodes, canvasFrameSize),
    [canvasFrameSize, displayCanvasNodes],
  );
  const canvasViewportStyle = lockedCanvasViewportStyle ?? autoCanvasViewportStyle;
  const canvasScale = canvasStyleScale(canvasViewportStyle);

  useEffect(() => {
    if (selectedNode) {
      setNodeDraft({
        label: selectedNode.label,
        role: selectedNode.role,
        purpose: selectedNode.purpose,
        agentId: selectedNode.agentId,
      });
    }
  }, [selectedNode?.id, setNodeDraft]);

  useEffect(() => {
    setNodePositionDrafts({});
    dragStateRef.current = null;
    if (dragFrameRef.current) {
      window.cancelAnimationFrame(dragFrameRef.current);
      dragFrameRef.current = 0;
    }
  }, [selectedTeam?.teamId, canvas?.updatedAt, dragFrameRef, dragStateRef, setNodePositionDrafts]);

  useEffect(() => {
    setLockedCanvasViewportStyle(null);
  }, [selectedTeam?.teamId, setLockedCanvasViewportStyle]);

  return {
    researchCanvasReadOnly,
    teamCanvasQueryEnabled,
    teamCanvasQuery,
    durableCanvas,
    memberCanvas,
    knownTeamCanvas,
    canvas,
    hasWritableCanvas,
    canvasNodes,
    organizationEdges,
    communicationEdges,
    autoLayoutCanvasNodes,
    researchCanvasAutoLayoutActive,
    displayCanvasNodes,
    selectedNode,
    visibleCommunicationEdges,
    visibleEdges,
    autoCanvasViewportStyle,
    canvasViewportStyle,
    canvasScale,
  };
}

export type TeamsCanvasProjectionApi = ReturnType<typeof useTeamsCanvasProjection>;

/** Re-export for callers that previously parsed mode locally before shell hook. */
export { parseTeamShellMode };
