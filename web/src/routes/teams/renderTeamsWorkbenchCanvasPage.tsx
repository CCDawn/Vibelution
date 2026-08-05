/**
 * Canvas-mode shell return for Teams workbench (R2-q extract).
 */
import type { CSSProperties, MutableRefObject, ReactNode } from "react";
import type { Team, TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import type { AgentConfigWorkspaceAgent } from "../../api/types";
import { TeamsCanvasComposer } from "./TeamsCanvasComposer";
import { TeamOrganizationCanvasSurface } from "./TeamOrganizationCanvasSurface";
import { TEAMS_LAYOUT_ID } from "./teamsWorkbenchChrome";
import type { PaneSpec } from "../../components/layout/paneLayoutPersistence";
import { teamWorkspaceRoute } from "./researchWorkspaceModel";
import { RESEARCH_TEAM_ID } from "../TeamsRoute.canvasData";
import { agentDisplayInfo } from "../agentDisplay";
import { teamChatRoomRoute } from "./researchStageAgentPresentation";

export type TeamsWorkbenchCanvasPageProps = {
  lang: "zh" | "en";
  styles: Record<string, string>;
  teamsRailResize: { sidebar: PaneSpec; aside: PaneSpec };
  selectedTeamContextTitle: string;
  teamShellRail: ReactNode;
  teamShellToolbar: ReactNode;
  researchWorkflowTeamSelected: boolean;
  researchCanvasReadOnly: boolean;
  validationValid: boolean;
  inspectorBody: ReactNode;
  selectedTeam: Team | null;
  selectedTeamReferenceName?: string;
  effectiveTeamId: string;
  teamDetailLoadMode: string;
  canvas: TeamOrganizationCanvas | null | undefined;
  displayCanvasNodes: TeamCanvasNode[];
  visibleEdges: any[];
  selectedNodeId: string;
  activeAgents: AgentConfigWorkspaceAgent[];
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
  canvasFrameRef: MutableRefObject<HTMLElement | null>;
  nodeToneClass: (node: TeamCanvasNode) => string;
  roleBadgeToneClass: (node: TeamCanvasNode, displayTone?: string) => string;
  completionFlowSlot: ReactNode;
  onSelectNode: (id: string) => void;
  onLayoutModeChange: (mode: any) => void;
  onToggleCommunicationEdges: () => void;
  onAddNode: () => void;
  onArchiveTeam: () => void;
  onSyncRoom: () => void;
  onNodePointerDown: any;
  onNodePointerMove: any;
  onNodePointerUp: any;
  onNodePointerCancel: any;
};

export function renderTeamsWorkbenchCanvasPage(props: TeamsWorkbenchCanvasPageProps) {
  const p = props;
  return (
    <TeamsCanvasComposer
      className={p.styles.route}
      layoutId={TEAMS_LAYOUT_ID}
      resize={p.teamsRailResize}
      ariaLabel={p.selectedTeamContextTitle}
      title={p.lang === "zh" ? "团队工作台" : "Team workbench"}
      rail={p.teamShellRail}
      toolbar={p.teamShellToolbar}
      styles={p.styles}
      researchWorkflowTeamSelected={p.researchWorkflowTeamSelected}
      researchCanvasReadOnly={p.researchCanvasReadOnly}
      validationValid={p.validationValid}
      inspectorTitle={
        p.researchCanvasReadOnly
          ? (p.lang === "zh" ? "组织画布" : "Organization canvas")
          : (p.lang === "zh" ? "节点绑定" : "Node binding")
      }
      inspectorBody={p.inspectorBody}
      canvas={(
        <TeamOrganizationCanvasSurface
          lang={p.lang}
          selectedTeam={p.selectedTeam}
          selectedTeamReferenceName={p.selectedTeamReferenceName}
          effectiveTeamId={p.effectiveTeamId}
          teamDetailLoadMode={p.teamDetailLoadMode as any}
          researchTeamId={RESEARCH_TEAM_ID}
          canvas={p.canvas as any}
          displayCanvasNodes={p.displayCanvasNodes}
          visibleEdges={p.visibleEdges}
          selectedNodeId={p.selectedNodeId}
          activeAgents={p.activeAgents}
          agentDisplay={agentDisplayInfo}
          researchCanvasReadOnly={p.researchCanvasReadOnly}
          researchCanvasAutoLayoutActive={p.researchCanvasAutoLayoutActive}
          showCommunicationEdges={p.showCommunicationEdges}
          organizationEdgeCount={p.organizationEdgeCount}
          communicationEdgeCount={p.communicationEdgeCount}
          communicationEdgeHint={p.communicationEdgeHint}
          communicationEdgeButtonLabel={p.communicationEdgeButtonLabel}
          saveLabel={p.saveLabel}
          hasWritableCanvas={p.hasWritableCanvas}
          linkedChatRoomId={p.linkedChatRoomId}
          activeTeamMemberCount={p.activeTeamMemberCount}
          teamSyncPending={p.teamSyncPending}
          teamArchivePending={p.teamArchivePending}
          teamArchiveDisabledReason={p.teamArchiveDisabledReason}
          conversationStatus={p.conversationStatus}
          conversationMissingAgentCount={p.conversationMissingAgentCount}
          showTeamLoadingSurface={p.showTeamLoadingSurface}
          teamWorkspaceLoadingTitle={p.teamWorkspaceLoadingTitle}
          teamWorkspaceLoadingMessage={p.teamWorkspaceLoadingMessage}
          teamDetailPending={p.teamDetailPending}
          teamCanvasPending={p.teamCanvasPending}
          teamDetailError={p.teamDetailError}
          teamCanvasError={p.teamCanvasError}
          canvasViewportStyle={p.canvasViewportStyle}
          canvasFrameRef={p.canvasFrameRef as any}
          nodeToneClass={p.nodeToneClass}
          roleBadgeToneClass={p.roleBadgeToneClass}
          nodeActiveClassName={p.styles.nodeActive}
          nodeReadOnlyClassName={p.styles.nodeReadOnly}
          styles={p.styles}
          completionFlowSlot={p.completionFlowSlot}
          teamWorkspaceRoute={teamWorkspaceRoute}
          teamChatRoomRoute={teamChatRoomRoute}
          onSelectNode={p.onSelectNode}
          onLayoutModeChange={p.onLayoutModeChange}
          onToggleCommunicationEdges={p.onToggleCommunicationEdges}
          onAddNode={p.onAddNode}
          onArchiveTeam={p.onArchiveTeam}
          onSyncRoom={p.onSyncRoom}
          onNodePointerDown={p.onNodePointerDown}
          onNodePointerMove={p.onNodePointerMove}
          onNodePointerUp={p.onNodePointerUp}
          onNodePointerCancel={p.onNodePointerCancel}
        />
      )}
    />
  );
}
