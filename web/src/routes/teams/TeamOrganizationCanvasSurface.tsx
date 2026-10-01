import {
  Archive,
  Bot,
  Check,
  Link2,
  Pencil,
  Plus,
  RefreshCw,
  Spline,
  Trash2,
  Users,
} from "lucide-react";
import { Fragment, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode, type Ref } from "react";
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
  VNativeInput,
  VStateSurface,
  VSurface,
  VTooltip,
} from "../../components/vui";
import { edgeLine, isCommunicationEdge, teamCanvasNodeStyle } from "./canvasGeometry";
import { canvasNodeAgentLine } from "./teamCanvasNodePresentation";
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
                  <VNativeButton
                    type="button"
                    className={authoring.connectSourceNodeId ? styles.layerButtonActive : ""}
                    onClick={authoring.connectSourceNodeId ? authoring.onCancelConnect : authoring.onBeginConnect}
                    disabled={!authoringEditable || !selectedNodeId || displayCanvasNodes.length < 2}
                    data-testid="team-canvas-connect-toggle"
                  >
                    <Spline size={14} />
                    {authoring.connectSourceNodeId
                      ? (lang === "zh" ? "取消连线" : "Cancel link")
                      : (lang === "zh" ? "连线" : "Link")}
                  </VNativeButton>
                </VTooltip>
                <VNativeButton
                  type="button"
                  className={authoring.renamingNodeId ? styles.layerButtonActive : ""}
                  onClick={authoring.onBeginNodeRename}
                  disabled={!authoringEditable || !selectedNodeId}
                  data-testid="team-canvas-rename-toggle"
                >
                  <Pencil size={14} />
                  {authoring.renamingNodeId
                    ? (lang === "zh" ? "改名中" : "Renaming")
                    : (lang === "zh" ? "改名" : "Rename")}
                </VNativeButton>
              </>
            ) : null}
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
                const purpose = String(node.purpose || "").trim();
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
                    aria-label={`${node.label}, ${functionLabel}, ${agentLine}`}
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
                    <strong>{node.label}</strong>
                    <span className={`${styles.nodeRoleBadge} ${roleBadgeToneClass(node, display?.tone)}`}>{functionLabel}</span>
                    <small>{agentLine}</small>
                    {purpose ? <small className={styles.nodePurpose}>{purpose}</small> : null}
                  </VNativeButton>
                );
              })}
              {authoringEditable && authoring && selectedAuthoringEdge && selectedAuthoringEdgeLine ? (
                <div
                  className={[
                    "absolute z-[2] flex -translate-x-1/2 -translate-y-[130%] items-center gap-1 rounded-md border",
                    "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1 shadow-sm",
                    "left-[calc(var(--canvas-offset-x,0px)+var(--overlay-x,0px))] top-[calc(var(--canvas-offset-y,0px)+var(--overlay-y,0px))]",
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
                  <VNativeButton
                    type="button"
                    onClick={authoring.onCommitEdgeLabel}
                    data-testid="team-canvas-edge-label-save"
                  >
                    <Check size={14} />
                    {lang === "zh" ? "保存" : "Save"}
                  </VNativeButton>
                  <VNativeButton
                    type="button"
                    className={styles.dangerButton}
                    onClick={() => authoring.onDeleteEdge(selectedAuthoringEdge.id)}
                    data-testid="team-canvas-edge-delete"
                  >
                    <Trash2 size={14} />
                    {lang === "zh" ? "删线" : "Delete"}
                  </VNativeButton>
                </div>
              ) : null}
              {authoringEditable && authoring && renamingNode ? (
                <div
                  className={[
                    "absolute z-[2] flex -translate-x-1/2 -translate-y-full items-center gap-1 rounded-md border",
                    "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1 shadow-sm",
                    "left-[calc(var(--canvas-offset-x,0px)+var(--overlay-x,0px))] top-[calc(var(--canvas-offset-y,0px)+var(--overlay-y,0px))]",
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
                  <VNativeButton
                    type="button"
                    onClick={authoring.onCommitNodeRename}
                    data-testid="team-canvas-node-rename-save"
                  >
                    <Check size={14} />
                    {lang === "zh" ? "保存" : "Save"}
                  </VNativeButton>
                </div>
              ) : null}
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
