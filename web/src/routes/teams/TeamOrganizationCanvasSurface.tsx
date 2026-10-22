import {
  Archive,
  Bot,
  Check,
  Link2,
  Minus,
  Pencil,
  Plus,
  RefreshCw,
  Spline,
  Trash2,
  Users,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode, type Ref } from "react";
import { Link } from "react-router-dom";

import type {
  AgentConfigWorkspaceAgent,
  Team,
  TeamCanvasEdge,
  TeamCanvasNode,
  TeamOrganizationCanvas,
} from "../../api/types";
import {
  VActionGroup,
  VButton,
  VNativeButton,
  VNativeInput,
  VStateSurface,
  VSurface,
  VTooltip,
} from "../../components/vui";
import { CANVAS_MAX_ZOOM, CANVAS_MIN_ZOOM, canvasStyleScale, canvasViewStyle, edgeLine, isCommunicationEdge, panCanvasViewport, resolveCanvasFrameSize, teamCanvasNodeStyle, zoomCanvasViewport, type CanvasFrameSize, type CanvasViewportStyle } from "./canvasGeometry";
import { canvasNodeAgentLine, canvasNodeSecondaryLines, canvasNodeTitle } from "./teamCanvasNodePresentation";
import nodeStyles from "./TeamOrganizationCanvasSurface.styles";
import { teamNodeFunctionLabel } from "./teamRouteShellModel";

/** Canvas authoring interactions owned by the shell phase (state + save wiring). */
export type TeamCanvasAuthoringProps = {
  selectedEdgeId: string;
  connectSourceNodeId: string;
  renamingNodeId: string;
  edgeLabelDraft: string;
  nodeRenameDraft: string;
  onSelectEdge: (edgeId: string) => void;
  onBeginConnect: () => void;
  onCancelConnect: () => void;
  onConnectNodes: (sourceNodeId: string, targetNodeId: string) => void;
  onDeleteEdge: (edgeId: string) => void;
  onEdgeLabelDraftChange: (value: string) => void;
  onCommitEdgeLabel: () => void;
  onBeginNodeRename: () => void;
  onNodeRenameDraftChange: (value: string) => void;
  onCommitNodeRename: () => void;
};

export type TeamOrganizationCanvasSurfaceProps = {
  lang: "zh" | "en";
  selectedTeam: Team | null;
  selectedTeamReferenceName?: string;
  effectiveTeamId: string;
  teamDetailLoadMode: string;
  researchTeamId: string;
  canvas: TeamOrganizationCanvas | null;
  displayCanvasNodes: TeamCanvasNode[];
  visibleEdges: TeamCanvasEdge[];
  selectedNodeId: string;
  activeAgents: AgentConfigWorkspaceAgent[];
  agentDisplay: (agent: AgentConfigWorkspaceAgent, lang: "zh" | "en") => { name: string; functionLabel?: string; tone?: string };
  researchCanvasReadOnly: boolean;
  /**
   * When true, no canvas-local chrome (path / stats / actions).
   * Research home merges layout actions into the flow strip above.
   */
  hideToolbar?: boolean;
  researchCanvasAutoLayoutActive: boolean;
  showCommunicationEdges: boolean;
  organizationEdgeCount: number;
  communicationEdgeCount: number;
  communicationEdgeHint: string;
  communicationEdgeButtonLabel: string;
  saveLabel: string;
  hasWritableCanvas: boolean;
  linkedChatRoomId: string;
  activeTeamMemberCount: number;
  teamSyncPending: boolean;
  teamArchivePending: boolean;
  teamArchiveDisabledReason: string;
  conversationStatus?: string;
  conversationMissingAgentCount?: number;
  showTeamLoadingSurface: boolean;
  teamWorkspaceLoadingTitle: string;
  teamWorkspaceLoadingMessage: string;
  teamDetailPending: boolean;
  teamCanvasPending: boolean;
  teamDetailError: boolean;
  teamCanvasError: boolean;
  canvasViewportStyle: CanvasViewportStyle;
  canvasFrameSize?: CanvasFrameSize;
  onCanvasViewportChange?: (style: CanvasViewportStyle | null) => void;
  canvasFrameRef: Ref<HTMLDivElement>;
  nodeToneClass: (node: TeamCanvasNode) => string;
  roleBadgeToneClass: (node: TeamCanvasNode, displayTone?: string) => string;
  nodeActiveClassName: string;
  nodeReadOnlyClassName: string;
  styles: Record<string, string>;
  completionFlowSlot?: ReactNode;
  toolbarLeadingAction?: ReactNode;
  teamWorkspaceRoute: (teamId: string) => string;
  teamChatRoomRoute: (roomId: string, backHref: string, backLabel: string) => string;
  onSelectNode: (nodeId: string) => void;
  onLayoutModeChange: (mode: "auto" | "source") => void;
  onToggleCommunicationEdges: () => void;
  onAddNode: () => void;
  onArchiveTeam: () => void;
  onSyncRoom: () => void;
  onNodePointerDown?: (event: ReactPointerEvent<HTMLButtonElement>, node: TeamCanvasNode) => void;
  onNodePointerMove?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onNodePointerUp?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onNodePointerCancel?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  canvasAuthoring?: TeamCanvasAuthoringProps;
};

/**
 * Organization canvas surface: toolbar + optional loading + graph / empty state.
 */
export function TeamOrganizationCanvasSurface(props: TeamOrganizationCanvasSurfaceProps) {
  const {
    lang,
    selectedTeam,
    selectedTeamReferenceName,
    effectiveTeamId,
    teamDetailLoadMode,
    researchTeamId,
    canvas,
    displayCanvasNodes,
    visibleEdges,
    selectedNodeId,
    activeAgents,
    agentDisplay,
    researchCanvasReadOnly,
    hideToolbar = false,
    showCommunicationEdges,
    communicationEdgeCount,
    communicationEdgeHint,
    communicationEdgeButtonLabel,
    saveLabel,
    hasWritableCanvas,
    linkedChatRoomId,
    activeTeamMemberCount,
    teamSyncPending,
    teamArchivePending,
    teamArchiveDisabledReason,
    showTeamLoadingSurface,
    teamWorkspaceLoadingTitle,
    teamWorkspaceLoadingMessage,
    teamDetailPending,
    teamCanvasPending,
    teamDetailError,
    teamCanvasError,
    canvasViewportStyle,
    canvasFrameSize,
    onCanvasViewportChange,
    canvasFrameRef,
    nodeToneClass,
    roleBadgeToneClass,
    nodeActiveClassName,
    nodeReadOnlyClassName,
    styles,
    completionFlowSlot,
    toolbarLeadingAction,
    teamWorkspaceRoute,
    teamChatRoomRoute,
    onSelectNode,
    onToggleCommunicationEdges,
    onAddNode,
    onArchiveTeam,
    onSyncRoom,
    onNodePointerDown,
    onNodePointerMove,
    onNodePointerUp,
    onNodePointerCancel,
    canvasAuthoring,
  } = props;
  const authoring = canvasAuthoring;
  const authoringEditable = Boolean(
    authoring && !researchCanvasReadOnly && hasWritableCanvas && canvas,
  );
  const connectSourceLabel = displayCanvasNodes.find(
    (node) => authoring && node.id === authoring.connectSourceNodeId,
  )?.label;
  const selectedAuthoringEdge: TeamCanvasEdge | undefined = authoring
    ? visibleEdges.find((edge) => edge.id === authoring.selectedEdgeId)
    : undefined;
  const selectedAuthoringEdgeLine = selectedAuthoringEdge
    ? edgeLine(selectedAuthoringEdge, displayCanvasNodes, visibleEdges)
    : null;
  const renamingNode = authoring
    ? displayCanvasNodes.find((node) => node.id === authoring.renamingNodeId)
    : undefined;
  const localFrameRef = useRef<HTMLDivElement | null>(null);
  const panRef = useRef<{ pointerId: number; x: number; y: number; style: CanvasViewportStyle } | null>(null);
  const [panning, setPanning] = useState(false);
  const setFrameRef = useCallback((frame: HTMLDivElement | null) => {
    localFrameRef.current = frame;
    if (typeof canvasFrameRef === "function") canvasFrameRef(frame);
    else if (canvasFrameRef) canvasFrameRef.current = frame;
  }, [canvasFrameRef]);
  // Narrow canvas event boundary: background gestures only; nodes, SVG edges and authoring controls keep their own handlers.
  const isInteractiveTarget = (target: EventTarget | null) => target instanceof Element
    && Boolean(target.closest('button, a, input, textarea, select, [role="button"], [contenteditable="true"], [data-composer], [data-testid="team-canvas-view-controls"]'));
  useEffect(() => {
    const frame = localFrameRef.current;
    if (!frame || !canvas || !onCanvasViewportChange) return;
    // React delegates wheel listeners as passive; the canvas must consume wheel without scrolling/zooming the page.
    const onWheel = (event: WheelEvent) => {
      if (isInteractiveTarget(event.target) || panRef.current) return;
      event.preventDefault();
      const rect = frame.getBoundingClientRect();
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rect.height : 1);
      onCanvasViewportChange(zoomCanvasViewport(canvasViewportStyle, canvasStyleScale(canvasViewportStyle) * Math.exp(-Math.max(-240, Math.min(240, delta)) * 0.002), {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      }));
    };
    frame.addEventListener("wheel", onWheel, { passive: false });
    return () => frame.removeEventListener("wheel", onWheel);
  }, [canvas, canvasViewportStyle, onCanvasViewportChange]);
  function zoomFromCenter(factor: number) {
    const size = resolveCanvasFrameSize(canvasFrameSize);
    onCanvasViewportChange?.(zoomCanvasViewport(canvasViewportStyle, canvasStyleScale(canvasViewportStyle) * factor, { x: size.width / 2, y: size.height / 2 }));
  }
  function finishPan(event: ReactPointerEvent<HTMLDivElement>) {
    if (panRef.current?.pointerId !== event.pointerId) return;
    panRef.current = null;
    setPanning(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  return (
    <VSurface
      as="main"
      className={[styles.canvasPanel, "min-h-0 flex-1 !border-0 !rounded-none"].filter(Boolean).join(" ")}
      elevation="panel"
      padding="none"
      tone="rail"
      id="research-organization-canvas"
      data-vui-region="teams-canvas"
      data-testid="team-organization-canvas-surface"
    >
      {hideToolbar ? (
        <div className={styles.canvasToolbar} data-testid="team-canvas-relationship-toolbar">
          <span className={styles.saveState}>{lang === "zh" ? "组织关系" : "Organization"}{researchCanvasReadOnly ? (lang === "zh" ? " · 节点只读" : " · Read-only nodes") : ""}</span>
          <VTooltip content={communicationEdgeHint}>
            <VButton type="button" variant="secondary" aria-pressed={showCommunicationEdges}
              className={showCommunicationEdges ? styles.layerButtonActive : ""}
              onClick={onToggleCommunicationEdges} isDisabled={!canvas || communicationEdgeCount === 0}
              disabledReason={communicationEdgeCount === 0 ? (lang === "zh" ? "暂无通信关系" : "No communication relationships") : undefined}>
              <Link2 size={14} />
              {lang === "zh" ? `通信关系 · ${showCommunicationEdges ? "已显示" : "已隐藏"}` : `Communication · ${showCommunicationEdges ? "Shown" : "Hidden"}`}
            </VButton>
          </VTooltip>
        </div>
      ) : null}
      {hideToolbar ? null : (
        <div className={styles.canvasToolbar} data-testid="team-canvas-toolbar">
          {/* View controls (edge layer, room link) stay reachable in read-only
              canvas mode; the edit cluster renders only for authoring surfaces. */}
          <div className="min-w-0">{toolbarLeadingAction}</div>
          <VActionGroup
            className={styles.toolbarActions}
            ariaLabel={lang === "zh" ? "团队画布操作" : "Team canvas actions"}
          >
            {!researchCanvasReadOnly && saveLabel ? (
              <span className={styles.saveState}>{saveLabel}</span>
            ) : null}
            <VTooltip content={communicationEdgeHint}>
              <VButton
                type="button"
                className={showCommunicationEdges ? styles.layerButtonActive : ""}
                onClick={onToggleCommunicationEdges}
                aria-pressed={showCommunicationEdges}
                isDisabled={!canvas || communicationEdgeCount === 0}
              >
                <Link2 size={14} />
                {communicationEdgeButtonLabel}
              </VButton>
            </VTooltip>
            {linkedChatRoomId ? (
              <Link
                className={styles.toolbarLink}
                to={teamChatRoomRoute(
                  linkedChatRoomId,
                  teamWorkspaceRoute(selectedTeam?.teamId || researchTeamId),
                  lang === "zh" ? "返回团队页面" : "Back to team",
                )}
              >
                {lang === "zh" ? "打开群聊" : "Open room"}
              </Link>
            ) : null}
            {researchCanvasReadOnly ? null : (
              <>
                {linkedChatRoomId ? null : (
                  <VButton
                    type="button"
                    onClick={onSyncRoom}
                    isDisabled={!selectedTeam || activeTeamMemberCount === 0 || teamSyncPending}
                  >
                    <Link2 size={14} />
                    {teamSyncPending
                      ? (lang === "zh" ? "同步中" : "Syncing")
                      : (lang === "zh" ? "同步群聊" : "Sync room")}
                  </VButton>
                )}
                <VButton type="button" onClick={onAddNode} isDisabled={!hasWritableCanvas} icon={<Plus size={14} />}>
                  {lang === "zh" ? "节点" : "Node"}
                </VButton>
                {authoring ? (
                  <>
                    <VTooltip
                      content={
                        connectSourceLabel
                          ? (lang === "zh"
                            ? `连线中：从「${connectSourceLabel}」点击目标节点完成，Esc 或再点源节点取消`
                            : `Linking from "${connectSourceLabel}": click a target node, Esc or click the source to cancel`)
                          : (lang === "zh" ? "从选中节点出发连接任意节点" : "Link the selected node to any node")
                      }
                    >
                      <VButton
                        type="button"
                        className={authoring.connectSourceNodeId ? styles.layerButtonActive : ""}
                        onClick={authoring.connectSourceNodeId ? authoring.onCancelConnect : authoring.onBeginConnect}
                        isDisabled={!authoringEditable || !selectedNodeId || displayCanvasNodes.length < 2}
                        data-testid="team-canvas-connect-toggle"
                      >
                        <Spline size={14} />
                        {authoring.connectSourceNodeId
                          ? (lang === "zh" ? "取消连线" : "Cancel link")
                          : (lang === "zh" ? "连线" : "Link")}
                      </VButton>
                    </VTooltip>
                    <VButton
                      type="button"
                      className={authoring.renamingNodeId ? styles.layerButtonActive : ""}
                      onClick={authoring.onBeginNodeRename}
                      isDisabled={!authoringEditable || !selectedNodeId}
                      data-testid="team-canvas-rename-toggle"
                      icon={<Pencil size={14} />}
                    >
                      {authoring.renamingNodeId
                        ? (lang === "zh" ? "改名中" : "Renaming")
                        : (lang === "zh" ? "改名" : "Rename")}
                    </VButton>
                  </>
                ) : null}
                <VButton
                  type="button"
                  className={styles.dangerButton}
                  onClick={onArchiveTeam}
                  isDisabled={!selectedTeam || teamArchivePending || Boolean(teamArchiveDisabledReason)}
                  title={teamArchiveDisabledReason || (lang === "zh" ? "归档当前团队" : "Archive this team")}
                >
                  <Archive size={14} />
                  {lang === "zh" ? "归档" : "Archive"}
                </VButton>
              </>
            )}
          </VActionGroup>
        </div>
      )}
      {showTeamLoadingSurface ? (
        <VStateSurface
          className={styles.teamLoadingInlineSurface}
          icon={<RefreshCw size={15} />}
          role="status"
          skeletonLines
          title={teamWorkspaceLoadingTitle}
          tone="loading"
          facts={[
            { key: "team", label: lang === "zh" ? "团队" : "Team", value: selectedTeamReferenceName ?? effectiveTeamId },
            { key: "detail", label: lang === "zh" ? "详情" : "Details", value: teamDetailLoadMode },
            { key: "source", label: lang === "zh" ? "来源" : "Source", value: "Team detail API" },
          ]}
        >
          {teamWorkspaceLoadingMessage}
        </VStateSurface>
      ) : null}
      {completionFlowSlot}
      {canvas ? (
        <div
          className={[styles.canvas, onCanvasViewportChange ? nodeStyles.interactiveFrame : "", panning ? nodeStyles.panningFrame : ""].filter(Boolean).join(" ")}
          ref={setFrameRef}
          data-testid="team-canvas-frame"
          role="region"
          aria-label={lang === "zh" ? "组织画布：拖动空白处平移，滚轮缩放；方向键平移，加减键缩放，Home 适应全部" : "Organization canvas: drag background to pan, wheel to zoom; arrow keys pan, plus/minus zoom, Home fits all"}
          tabIndex={onCanvasViewportChange ? 0 : undefined}
          onPointerDown={(event) => {
            if (!onCanvasViewportChange || event.button !== 0 || event.isPrimary === false || isInteractiveTarget(event.target)) return;
            event.preventDefault();
            event.currentTarget.focus({ preventScroll: true });
            event.currentTarget.setPointerCapture(event.pointerId);
            panRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, style: canvasViewportStyle };
            setPanning(true);
          }}
          onPointerMove={(event) => {
            const pan = panRef.current;
            if (!pan || pan.pointerId !== event.pointerId) return;
            onCanvasViewportChange?.(panCanvasViewport(pan.style, { x: event.clientX - pan.x, y: event.clientY - pan.y }));
          }}
          onPointerUp={finishPan}
          onPointerCancel={finishPan}
          onLostPointerCapture={finishPan}
          onKeyDown={(event) => {
            if (!onCanvasViewportChange || event.target !== event.currentTarget || event.ctrlKey || event.metaKey || event.altKey) return;
            const step = event.shiftKey ? 120 : 40;
            const directions: Record<string, { x: number; y: number }> = { ArrowLeft: { x: step, y: 0 }, ArrowRight: { x: -step, y: 0 }, ArrowUp: { x: 0, y: step }, ArrowDown: { x: 0, y: -step } };
            const delta = directions[event.key];
            if (delta) onCanvasViewportChange(panCanvasViewport(canvasViewportStyle, delta));
            else if (event.key === "+" || event.key === "=") zoomFromCenter(1.2);
            else if (event.key === "-") zoomFromCenter(1 / 1.2);
            else if (event.key === "Home") onCanvasViewportChange(null);
            else return;
            event.preventDefault();
          }}
        >
          <div className={styles.canvasViewport} style={canvasViewportStyle} data-testid="team-canvas-world">
            <svg className={styles.edges} width="100%" height="100%" data-testid="team-canvas-edges">
              <defs>
                <marker
                  id="team-edge-arrow"
                  viewBox="0 0 10 10"
                  refX="10"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke" />
                </marker>
              </defs>
              {visibleEdges.map((edge) => {
                const line = edgeLine(edge, displayCanvasNodes, visibleEdges);
                const communication = isCommunicationEdge(edge);
                if (!line) {
                  return null;
                }
                const edgeSelected = authoring?.selectedEdgeId === edge.id;
                const sourceLabel = displayCanvasNodes.find((node) => node.id === edge.source)?.label || edge.source;
                const targetLabel = displayCanvasNodes.find((node) => node.id === edge.target)?.label || edge.target;
                const pathD = `M ${line.x1} ${line.y1} Q ${line.cx} ${line.cy} ${line.x2} ${line.y2}`;
                return (
                  <Fragment key={edge.id}>
                    <path
                      className={communication ? styles.edgeCommunication : styles.edgeOrganization}
                      d={pathD}
                      markerEnd={communication ? undefined : "url(#team-edge-arrow)"}
                      style={edgeSelected ? { strokeWidth: 3.25, opacity: 1 } : undefined}
                      data-edge-selected={edgeSelected ? "true" : undefined}
                    />
                    <path
                      d={pathD}
                      role="button"
                      tabIndex={authoringEditable ? 0 : undefined}
                      aria-pressed={edgeSelected}
                      aria-label={
                        lang === "zh"
                          ? `关系线：${sourceLabel} → ${targetLabel}${edge.label ? `（${edge.label}）` : ""}`
                          : `Edge: ${sourceLabel} → ${targetLabel}${edge.label ? ` (${edge.label})` : ""}`
                      }
                      data-testid={`team-canvas-edge-${edge.id}`}
                      style={{
                        stroke: "transparent",
                        strokeWidth: 14,
                        fill: "none",
                        pointerEvents: authoringEditable ? "stroke" : "none",
                        cursor: authoringEditable ? "pointer" : "default",
                      }}
                      onClick={authoringEditable && authoring ? () => authoring.onSelectEdge(edge.id) : undefined}
                      onKeyDown={
                        authoringEditable && authoring
                          ? (event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                authoring.onSelectEdge(edge.id);
                              }
                            }
                          : undefined
                      }
                    />
                    {edge.label ? (
                      <text
                        x={(line.x1 + 2 * line.cx + line.x2) / 4}
                        y={(line.y1 + 2 * line.cy + line.y2) / 4}
                        textAnchor="middle"
                        fontSize={10}
                        fill="currentColor"
                        className="[paint-order:stroke] [stroke:var(--vui-surface-base)] [stroke-width:3px] opacity-90"
                        style={{ pointerEvents: "none" }}
                      >
                        {edge.label}
                      </text>
                    ) : null}
                  </Fragment>
                );
              })}
            </svg>
              {displayCanvasNodes.map((node) => {
                const agent = activeAgents.find((item) => item.agentId === node.agentId);
                const display = agent ? agentDisplay(agent, lang) : null;
                const functionLabel = teamNodeFunctionLabel(node, display?.functionLabel, lang);
                const agentLine = canvasNodeAgentLine(node, display?.name, lang);
                const title = canvasNodeTitle(node, display?.name);
                const secondary = canvasNodeSecondaryLines(node, agentLine, functionLabel, title);
                const nodeSelected = selectedNodeId === node.id;
                const connectActive = Boolean(authoring?.connectSourceNodeId);
                const nodeIsConnectSource = authoring?.connectSourceNodeId === node.id;
                return (
                  <VNativeButton
                    key={node.id}
                    type="button"
                    className={[
                      styles.node,
                      nodeToneClass(node),
                      nodeSelected || nodeIsConnectSource ? nodeActiveClassName : "",
                      nodeIsConnectSource ? "animate-pulse ring-2 ring-[var(--accent-cool)]" : "",
                      researchCanvasReadOnly ? nodeReadOnlyClassName : "",
                    ].filter(Boolean).join(" ")}
                    style={teamCanvasNodeStyle(node)}
                    aria-label={`${title}, ${functionLabel}, ${agentLine}`}
                    aria-pressed={nodeSelected}
                    data-connect-source={nodeIsConnectSource ? "true" : undefined}
                    title={
                      researchCanvasReadOnly
                        ? (lang === "zh" ? "点击查看节点详情" : "Click to inspect node")
                        : connectActive
                          ? (lang === "zh"
                            ? (nodeIsConnectSource ? "再点源节点取消连线" : "点击完成连线")
                            : (nodeIsConnectSource ? "Click the source again to cancel" : "Click to finish the link"))
                          : (lang === "zh" ? "拖动调整节点位置" : "Drag to reposition")
                    }
                    onPointerDown={
                      researchCanvasReadOnly || connectActive ? undefined : (event) => onNodePointerDown?.(event, node)
                    }
                    onPointerMove={researchCanvasReadOnly || connectActive ? undefined : onNodePointerMove}
                    onPointerUp={researchCanvasReadOnly || connectActive ? undefined : onNodePointerUp}
                    onPointerCancel={researchCanvasReadOnly || connectActive ? undefined : onNodePointerCancel}
                    onClick={() => {
                      if (authoringEditable && connectActive && authoring) {
                        if (nodeIsConnectSource) {
                          authoring.onCancelConnect();
                        } else {
                          authoring.onConnectNodes(authoring.connectSourceNodeId, node.id);
                        }
                        return;
                      }
                      onSelectNode(node.id);
                    }}
                  >
                    <span className={styles.nodeIcon}>{node.agentId ? <Bot size={15} /> : <Users size={15} />}</span>
                    <strong className={nodeStyles.title}>{title}</strong>
                    <span className={`${styles.nodeRoleBadge} ${roleBadgeToneClass(node, display?.tone)}`}>{functionLabel}</span>
                    {secondary.agent ? <small className={nodeStyles.secondary}>{secondary.agent}</small> : null}
                    {secondary.purpose ? <small className={styles.nodePurpose}>{secondary.purpose}</small> : null}
                  </VNativeButton>
                );
              })}
              {authoringEditable && authoring && selectedAuthoringEdge && selectedAuthoringEdgeLine ? (
                <div
                  className={[
                    "absolute z-[2] flex -translate-x-1/2 -translate-y-[130%] items-center gap-1 rounded-md border",
                    "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1 shadow-sm",
                    "left-[var(--overlay-x,0px)] top-[var(--overlay-y,0px)]",
                  ].join(" ")}
                  style={{
                    "--overlay-x": `${(selectedAuthoringEdgeLine.x1 + 2 * selectedAuthoringEdgeLine.cx + selectedAuthoringEdgeLine.x2) / 4}px`,
                    "--overlay-y": `${(selectedAuthoringEdgeLine.y1 + 2 * selectedAuthoringEdgeLine.cy + selectedAuthoringEdgeLine.y2) / 4}px`,
                  } as CSSProperties}
                  data-testid="team-canvas-edge-editor"
                  data-composer="teams-canvas-edge-editor"
                >
                  <VNativeInput
                    aria-label={lang === "zh" ? "关系线标签" : "Edge label"}
                    value={authoring.edgeLabelDraft}
                    onChange={(event) => authoring.onEdgeLabelDraftChange(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        authoring.onCommitEdgeLabel();
                      }
                    }}
                    placeholder={lang === "zh" ? "边标签" : "Edge label"}
                    className="w-36"
                    data-testid="team-canvas-edge-label-input"
                  />
                  <VButton
                    type="button"
                    onClick={authoring.onCommitEdgeLabel}
                    data-testid="team-canvas-edge-label-save"
                    icon={<Check size={14} />}
                  >
                    {lang === "zh" ? "保存" : "Save"}
                  </VButton>
                  <VButton
                    type="button"
                    className={styles.dangerButton}
                    onClick={() => authoring.onDeleteEdge(selectedAuthoringEdge.id)}
                    data-testid="team-canvas-edge-delete"
                  >
                    <Trash2 size={14} />
                    {lang === "zh" ? "删线" : "Delete"}
                  </VButton>
                </div>
              ) : null}
              {authoringEditable && authoring && renamingNode ? (
                <div
                  className={[
                    "absolute z-[2] flex -translate-x-1/2 -translate-y-full items-center gap-1 rounded-md border",
                    "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1 shadow-sm",
                    "left-[var(--overlay-x,0px)] top-[var(--overlay-y,0px)]",
                  ].join(" ")}
                  style={{
                    "--overlay-x": `${renamingNode.x + 86}px`,
                    "--overlay-y": `${renamingNode.y - 8}px`,
                  } as CSSProperties}
                  data-testid="team-canvas-node-rename-editor"
                  data-composer="teams-canvas-node-rename-editor"
                >
                  <VNativeInput
                    aria-label={lang === "zh" ? "节点名称" : "Node label"}
                    value={authoring.nodeRenameDraft}
                    onChange={(event) => authoring.onNodeRenameDraftChange(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        authoring.onCommitNodeRename();
                      }
                    }}
                    placeholder={lang === "zh" ? "节点名称" : "Node label"}
                    className="w-40"
                    data-testid="team-canvas-node-rename-input"
                  />
                  <VButton
                    type="button"
                    onClick={authoring.onCommitNodeRename}
                    data-testid="team-canvas-node-rename-save"
                    icon={<Check size={14} />}
                  >
                    {lang === "zh" ? "保存" : "Save"}
                  </VButton>
                </div>
              ) : null}
          </div>
          {onCanvasViewportChange ? (
            <VActionGroup className={nodeStyles.viewControls} ariaLabel={lang === "zh" ? "画布视图" : "Canvas view"} data-testid="team-canvas-view-controls">
              <VButton density="compact" variant="secondary" onClick={() => zoomFromCenter(1 / 1.2)} isDisabled={canvasStyleScale(canvasViewportStyle) <= CANVAS_MIN_ZOOM} aria-label={lang === "zh" ? "缩小画布" : "Zoom out"} title={lang === "zh" ? "缩小画布" : "Zoom out"}>
                <Minus size={14} />
              </VButton>
              <VButton density="compact" variant="secondary" onClick={() => zoomFromCenter(1.2)} isDisabled={canvasStyleScale(canvasViewportStyle) >= CANVAS_MAX_ZOOM} aria-label={lang === "zh" ? "放大画布" : "Zoom in"} title={lang === "zh" ? "放大画布" : "Zoom in"}>
                <Plus size={14} />
              </VButton>
              <VButton density="compact" variant="secondary" onClick={() => onCanvasViewportChange(null)} isDisabled={!displayCanvasNodes.length}>
                {lang === "zh" ? "适应全部" : "Fit all"}
              </VButton>
              <VButton density="compact" variant="secondary" onClick={() => onCanvasViewportChange(canvasViewStyle(displayCanvasNodes, canvasFrameSize, { scale: 1 }))} isDisabled={!displayCanvasNodes.length}>
                100%
              </VButton>
              <VButton density="compact" variant="secondary" onClick={() => onCanvasViewportChange(canvasViewStyle(displayCanvasNodes, canvasFrameSize, { scale: canvasStyleScale(canvasViewportStyle), selectedNodeId }))} isDisabled={!displayCanvasNodes.some((node) => node.id === selectedNodeId)}>
                {lang === "zh" ? "定位选中" : "Focus selected"}
              </VButton>
              <span className={nodeStyles.zoomLabel} aria-label={lang === "zh" ? "当前缩放" : "Current zoom"}>
                {Math.round(canvasStyleScale(canvasViewportStyle) * 100)}%
              </span>
            </VActionGroup>
          ) : null}
        </div>
      ) : (
        <div className={styles.emptyCanvasPanel} ref={canvasFrameRef}>
          <div className={styles.emptyCanvasContent}>
            <span className={styles.emptyCanvasKicker}>{lang === "zh" ? "组织画布" : "Organization canvas"}</span>
            <strong>
              {teamDetailPending || teamCanvasPending
                ? (lang === "zh" ? "正在读取画布" : "Loading canvas")
                : (lang === "zh" ? "暂无画布数据" : "No canvas data")}
            </strong>
            <p>
              {lang === "zh"
                ? "刷新团队数据后会自动恢复。"
                : "Refresh team data to restore the canvas."}
            </p>
            <div className={styles.emptyCanvasSteps}>
              <span>{lang === "zh" ? "团队" : "Team"}</span>
              <span>{selectedTeam?.name ?? (lang === "zh" ? "未选择" : "Not selected")}</span>
              <span>
                {teamDetailError || teamCanvasError
                  ? (lang === "zh" ? "读取失败" : "Failed")
                  : (lang === "zh" ? "等待数据" : "Waiting")}
              </span>
            </div>
          </div>
        </div>
      )}
    </VSurface>
  );
}
