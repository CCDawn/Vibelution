import {
  Archive,
  Bot,
  Link2,
  Plus,
  RefreshCw,
  Users,
} from "lucide-react";
import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactNode, Ref } from "react";
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
  VNativeButton,
  VStateSurface,
  VSurface,
  VTooltip,
} from "../../components/vui";
import { edgeLine, isCommunicationEdge, teamCanvasNodeStyle } from "./canvasGeometry";
import { canvasNodeAgentLine } from "./teamCanvasNodePresentation";
import { teamNodeFunctionLabel } from "./teamRouteShellModel";

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
  canvasViewportStyle: CSSProperties;
  canvasFrameRef: Ref<HTMLDivElement>;
  nodeToneClass: (node: TeamCanvasNode) => string;
  roleBadgeToneClass: (node: TeamCanvasNode, displayTone?: string) => string;
  nodeActiveClassName: string;
  nodeReadOnlyClassName: string;
  styles: Record<string, string>;
  completionFlowSlot?: ReactNode;
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
    canvasFrameRef,
    nodeToneClass,
    roleBadgeToneClass,
    nodeActiveClassName,
    nodeReadOnlyClassName,
    styles,
    completionFlowSlot,
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
  } = props;

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
      {hideToolbar || researchCanvasReadOnly ? null : (
        <div className={styles.canvasToolbar} data-testid="team-canvas-toolbar">
          {/* Editable teams: actions only — no path / edge / room status walls. */}
          <div className="min-w-0" />
          <VActionGroup
            className={styles.toolbarActions}
            ariaLabel={lang === "zh" ? "团队画布操作" : "Team canvas actions"}
          >
            {saveLabel ? (
              <span className={styles.saveState}>{saveLabel}</span>
            ) : null}
            <VTooltip content={communicationEdgeHint}>
              <VNativeButton
                type="button"
                className={showCommunicationEdges ? styles.layerButtonActive : ""}
                onClick={onToggleCommunicationEdges}
                disabled={!canvas || communicationEdgeCount === 0}
              >
                <Link2 size={14} />
                {communicationEdgeButtonLabel}
              </VNativeButton>
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
            ) : (
              <VNativeButton
                type="button"
                onClick={onSyncRoom}
                disabled={!selectedTeam || activeTeamMemberCount === 0 || teamSyncPending}
              >
                <Link2 size={14} />
                {teamSyncPending
                  ? (lang === "zh" ? "同步中" : "Syncing")
                  : (lang === "zh" ? "同步群聊" : "Sync room")}
              </VNativeButton>
            )}
            <VNativeButton type="button" onClick={onAddNode} disabled={!hasWritableCanvas}>
              <Plus size={14} />
              {lang === "zh" ? "节点" : "Node"}
            </VNativeButton>
            <VNativeButton
              type="button"
              className={styles.dangerButton}
              onClick={onArchiveTeam}
              disabled={!selectedTeam || teamArchivePending || Boolean(teamArchiveDisabledReason)}
              title={teamArchiveDisabledReason || (lang === "zh" ? "归档当前团队" : "Archive this team")}
            >
              <Archive size={14} />
              {lang === "zh" ? "归档" : "Archive"}
            </VNativeButton>
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
        <div className={styles.canvas} ref={canvasFrameRef}>
          <div className={styles.canvasViewport} style={canvasViewportStyle}>
            <svg className={styles.edges} width="100%" height="100%" aria-hidden="true">
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
                return line ? (
                  <path
                    key={edge.id}
                    className={communication ? styles.edgeCommunication : styles.edgeOrganization}
                    d={`M ${line.x1} ${line.y1} Q ${line.cx} ${line.cy} ${line.x2} ${line.y2}`}
                    markerEnd={communication ? undefined : "url(#team-edge-arrow)"}
                  />
                ) : null;
              })}
            </svg>
            {displayCanvasNodes.map((node) => {
              const agent = activeAgents.find((item) => item.agentId === node.agentId);
              const display = agent ? agentDisplay(agent, lang) : null;
              const functionLabel = teamNodeFunctionLabel(node, display?.functionLabel, lang);
              const agentLine = canvasNodeAgentLine(node, display?.name, lang);
              const purpose = String(node.purpose || "").trim();
              return (
                <VNativeButton
                  key={node.id}
                  type="button"
                  className={[
                    styles.node,
                    nodeToneClass(node),
                    selectedNodeId === node.id ? nodeActiveClassName : "",
                    researchCanvasReadOnly ? nodeReadOnlyClassName : "",
                  ].filter(Boolean).join(" ")}
                  style={teamCanvasNodeStyle(node)}
                  title={
                    researchCanvasReadOnly
                      ? (lang === "zh" ? "点击查看节点详情" : "Click to inspect node")
                      : (lang === "zh" ? "拖动调整节点位置" : "Drag to reposition")
                  }
                  onPointerDown={researchCanvasReadOnly ? undefined : (event) => onNodePointerDown?.(event, node)}
                  onPointerMove={researchCanvasReadOnly ? undefined : onNodePointerMove}
                  onPointerUp={researchCanvasReadOnly ? undefined : onNodePointerUp}
                  onPointerCancel={researchCanvasReadOnly ? undefined : onNodePointerCancel}
                  onClick={() => onSelectNode(node.id)}
                >
                  <span className={styles.nodeIcon}>{node.agentId ? <Bot size={15} /> : <Users size={15} />}</span>
                  <strong>{node.label}</strong>
                  <span className={`${styles.nodeRoleBadge} ${roleBadgeToneClass(node, display?.tone)}`}>{functionLabel}</span>
                  <small>{agentLine}</small>
                  {purpose ? <small className={styles.nodePurpose}>{purpose}</small> : null}
                </VNativeButton>
              );
            })}
          </div>
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
