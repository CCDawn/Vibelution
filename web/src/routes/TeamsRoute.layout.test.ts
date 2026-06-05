import { describe, expect, it } from "vitest";

import { resolveLegacyTeamsRedirect } from "./LegacyTeamsRedirect";
import routeSource from "./TeamsRoute.tsx?raw";
import routeStyles from "./TeamsRoute.module.css";
import routerSource from "../app/router.tsx?raw";

describe("TeamsRoute layout contract", () => {
  it("is mounted as the top-level Team workspace with legacy redirects", () => {
    expect(routerSource).toContain('path: "teams"');
    expect(routerSource).toContain("lazyElement(<TeamsRoute />)");
    expect(routerSource).toContain('path: "agents/teams"');
    expect(routerSource).toContain('path: "research"');
    expect(routerSource).toContain("<LegacyTeamsRedirect />");
    expect(routeSource).not.toContain("AgentManagementNav");
    expect(routeSource).toContain("团队工作台 / 组织画布");
    expect(routeSource).toContain("Team Workspace / Canvas");
  });

  it("preserves selected Team deep links from legacy routes", () => {
    expect(resolveLegacyTeamsRedirect("")).toBe("/teams");
    expect(resolveLegacyTeamsRedirect("?team=research-core")).toBe("/teams?team=research-core");
  });

  it("uses Team APIs and Agent Center as the binding source", () => {
    expect(routeSource).toContain('fetchJson<TeamListPayload>("/api/teams")');
    expect(routeSource).toContain('fetchJson<TeamTemplateListPayload>("/api/team-templates")');
    expect(routeSource).toContain("/api/team-templates/${encodeURIComponent(templateId)}/instantiate");
    expect(routeSource).toContain("instantiateTeamTemplateMutation");
    expect(routeSource).toContain("fetchJson<Team>(`/api/teams/${encodeURIComponent(effectiveTeamId)}`)");
    expect(routeSource).toContain('fetchJson<AgentConfigWorkspace>("/api/agents/config-workspace")');
    expect(routeSource).toContain("fetchJson<Team>(`/api/teams/${encodeURIComponent(teamId)}`");
    expect(routeSource).toContain('method: "DELETE"');
    expect(routeSource).toContain("sendTeamProjectBusMessage(payload)");
    expect(routeSource).toContain("listProjectAgentBusTimeline(PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT)");
    expect(routeSource).toContain("revokeProjectAgentBusMessage({");
    expect(routeSource).toContain("/api/teams/${encodeURIComponent(teamId)}/chat-room/sync");
    expect(routeSource).toContain("syncTeamChatRoomMutation");
    expect(routeSource).toContain("fetchJson<ChatRoomDetail>(`/api/chat-rooms/${payload.roomId}/rounds`");
    expect(routeSource).toContain("fetchJson<ChatRoomDetail>(`/api/chat-rooms/${encodeURIComponent(linkedChatRoomId)}`)");
    expect(routeSource).toContain("linkedRoomRefetchInterval(pageVisible");
    expect(routeSource).toContain("latestChatRoomRound(linkedRoomDetail)");
    expect(routeSource).toContain('source: "team_workspace"');
    expect(routeSource).toContain("teamId: payload.teamId");
    expect(routeSource).toContain("startTeamRoundMutation");
    expect(routeSource).toContain("chatWorkspaceCache.afterTeamRoomMembershipChanged(variables.teamId, room.roomId)");
    expect(routeSource).toContain("chatWorkspaceCache.afterTeamRoomMembershipChanged(team.teamId, team.linkedChatRoom.roomId)");
    expect(routeSource).toContain("teamConversationStatusLabel");
    expect(routeSource).toContain("selectedTeam?.conversation");
    expect(routeSource).toContain("/api/teams/${encodeURIComponent(nextCanvas.teamId)}/canvas");
    expect(routeSource).toContain("成员源");
    expect(routeSource).toContain("Member source");
    expect(routeSource).toContain("Agent Center");
    expect(routeSource).toContain("team_organization_canvas");
    expect(routeSource).not.toContain("/api/research/flow-canvas");
  });

  it("can deep-link from Agent references to a selected Team", () => {
    expect(routeSource).toContain("useSearchParams");
    expect(routeSource).toContain('searchParams.get("team")');
    expect(routeSource).toContain('searchParams.get("agent")');
    expect(routeSource).toContain("requestedAgentTeamId");
    expect(routeSource).toContain("setSearchParams({ team: team.teamId })");
  });

  it("renders a dense list canvas inspector workflow", () => {
    expect(routeSource).toContain("teamList");
    expect(routeSource).toContain("canvasPanel");
    expect(routeSource).toContain("inspector");
    expect(routeSource).toContain("teamNameInputRef");
    expect(routeSource).toContain("从模板创建");
    expect(routeSource).toContain("创建 Demo 团队");
    expect(routeSource).toContain("selectedTemplate.chatRoom.mode");
    expect(routeSource).toContain("styles.templatePanel");
    expect(routeSource).toContain("styles.templatePicker");
    expect(routeSource).toContain("styles.templateSelect");
    expect(routeSource).toContain("styles.templatePreview");
    expect(routeSource).not.toContain("styles.templateCard");
    expect(routeSource).toContain("先填写团队名称，再创建团队。");
    expect(routeSource).toContain("styles.formError");
    expect(routeSource).toContain("styles.formHint");
    expect(routeSource).toContain("绑定 Agent");
    expect(routeSource).toContain("styles.nodeBindingSection");
    expect(routeSource).toContain("styles.nodeBindingPlaceholder");
    expect(routeSource).toContain("正在读取团队节点");
    expect(routeSource).toContain("agentTeamMembership");
    expect(routeSource).toContain("membership.teamId !== selectedTeam?.teamId");
    expect(routeSource).toContain("disabled={ownedByOtherTeam}");
    expect(routeSource).toContain("已属于");
    expect(routeSource).toContain("接入主干");
    expect(routeSource).toContain("保存节点");
    expect(routeSource).toContain("归档");
    expect(routeSource).toContain("解绑节点");
    expect(routeSource).toContain("删除节点");
    expect(routeSource).toContain("团队任务");
    expect(routeSource).toContain("启动团队讨论");
    expect(routeSource).toContain("teamTaskTopic");
    expect(routeSource).toContain("linkedRoomBusy");
    expect(routeSource).toContain("最近团队任务");
    expect(routeSource).toContain("styles.teamRoundPanel");
    expect(routeSource).toContain("styles.teamRoundCard");
    expect(routeSource).toContain("查看完整群聊");
    expect(routeSource).toContain("styles.teamTaskForm");
    expect(routeSource).toContain("团队广播");
    expect(routeSource).toContain("发送给团队");
    expect(routeSource).toContain("最近团队广播");
    expect(routeSource).toContain("已衔接群聊");
    expect(routeSource).toContain("to={`/chat?room=${encodeURIComponent(selectedTeamStartRoundResult.roomId)}`}");
    expect(routeSource).toContain("to={`/chat?room=${encodeURIComponent(latestTeamRound.roomId)}`}");
    expect(routeSource).toContain("styles.linkedRoomLine");
    expect(routeSource).toContain("styles.toolbarLink");
    expect(routeSource).toContain("teamBusEvents");
    expect(routeSource).toContain("isProjectAgentBusEventRevoked");
    expect(routeSource).toContain("projectAgentBusEventsForTeam");
    expect(routeSource).toContain("revokeTeamMessageMutation");
    expect(routeSource).toContain("styles.teamHistoryPanel");
    expect(routeSource).toContain("interrupt_targets");
    expect(routeSource).toContain("edges: canvas.edges.filter((edge) => edge.source !== deletedNodeId && edge.target !== deletedNodeId)");
    expect(routeStyles.templatePanel).toBeTypeOf("string");
    expect(routeStyles.templatePicker).toBeTypeOf("string");
    expect(routeStyles.templateSelect).toBeTypeOf("string");
    expect(routeStyles.templatePreview).toBeTypeOf("string");
    expect(routeStyles.nodeBindingSection).toBeTypeOf("string");
    expect(routeStyles.nodeBindingPlaceholder).toBeTypeOf("string");
  });

  it("keeps Team actions scoped to the selected Team or message event", () => {
    expect(routeSource).toContain("canvasSavePendingForTeam");
    expect(routeSource).toContain("saveCanvasMutation.variables?.teamId === teamId");
    expect(routeSource).toContain("selectedTeamSyncPending");
    expect(routeSource).toContain("syncTeamChatRoomMutation.variables === selectedTeam?.teamId");
    expect(routeSource).toContain("selectedTeamStartRoundPending");
    expect(routeSource).toContain("startTeamRoundMutation.variables?.teamId === selectedTeam?.teamId");
    expect(routeSource).toContain("selectedTeamMessagePending");
    expect(routeSource).toContain("sendTeamMessageMutation.variables?.teamId === selectedTeam?.teamId");
    expect(routeSource).toContain("revokeTeamMessageMutation.variables?.eventId === event.eventId");
    expect(routeSource).toContain("revokeTeamMessageMutation.mutate({ teamId: selectedTeam.teamId, eventId: event.eventId })");
    expect(routeSource).not.toContain("chatWorkspaceCache.afterTeamChanged(selectedTeamId || undefined)");
    expect(routeSource).not.toContain("revokeTeamMessageMutation.mutate(event.eventId)");
  });

  it("renders visible directional communication edges on the Team canvas", () => {
    expect(routeSource).toContain("<marker");
    expect(routeSource).toContain('id="team-edge-arrow"');
    expect(routeSource).toContain("key={edge.id}");
    expect(routeSource).toContain("Q ${line.cx} ${line.cy}");
    expect(routeSource).toContain("nodeBoundaryPoint");
    expect(routeSource).toContain("distanceToRectEdge");
    expect(routeSource).toContain("edgeLine(edge, canvasNodes, visibleEdges)");
    expect(routeSource).not.toContain("<line key={edge.id}");
    expect(routeSource).toContain("className={styles.edges}");
  });

  it("separates organization lines from information lines by default", () => {
    expect(routeSource).toContain("showCommunicationEdges");
    expect(routeSource).toContain("isCommunicationEdge(edge)");
    expect(routeSource).toContain("organizationEdges");
    expect(routeSource).toContain("communicationEdges");
    expect(routeSource).toContain("visibleCommunicationEdges");
    expect(routeSource).toContain("visibleCommunicationEdgeCount");
    expect(routeSource).toContain("visibleEdges");
    expect(routeSource).toContain("edge.type === \"communication\"");
    expect(routeSource).toContain("edge.type === \"collaborates_with\"");
    expect(routeSource).toContain("styles.edgeOrganization");
    expect(routeSource).toContain("styles.edgeCommunication");
    expect(routeSource).toContain("信息线");
    expect(routeSource).toContain("信息线已收起（");
    expect(routeSource).toContain("展开信息线");
    expect(routeSource).toContain("收起信息线");
    expect(routeSource).toContain("Info");
    expect(routeSource).toContain('type: "reports_to"');
    expect(routeSource).not.toContain("canvas?.edges.map((edge)");
  });

  it("centers compact Team canvases and renders function role badges", () => {
    expect(routeSource).toContain("canvasViewStyle");
    expect(routeSource).toContain("CANVAS_VIEWPORT_WIDTH");
    expect(routeSource).toContain("CANVAS_VIEWPORT_HEIGHT");
    expect(routeSource).toContain("canvasViewportStyle");
    expect(routeSource).toContain("lockedCanvasViewportStyle");
    expect(routeSource).toContain("setLockedCanvasViewportStyle(canvasViewportStyle)");
    expect(routeSource).toContain("canvasFrameSize");
    expect(routeSource).toContain("ResizeObserver");
    expect(routeSource).toContain("styles.canvasViewport");
    expect(routeSource).toContain("--canvas-offset-x");
    expect(routeSource).toContain("--canvas-scale");
    expect(routeSource).toContain("--node-x");
    expect(routeSource).toContain("roleBadgeTone");
    expect(routeSource).toContain("teamNodeFunctionLabel");
    expect(routeSource).toContain("能力管家");
    expect(routeSource).toContain("styles.nodeRoleBadge");
    expect(routeSource).toContain("styles.nodeRoleBadgeLead");
    expect(routeSource).toContain("styles.nodeRoleBadgeAdvisor");
    expect(routeSource).toContain("styles.nodeRoleBadgeSteward");
  });

  it("lets users drag canvas nodes and persist their positions", () => {
    expect(routeSource).toContain("nodePositionDrafts");
    expect(routeSource).toContain("dragStateRef");
    expect(routeSource).toContain("dragFrameRef");
    expect(routeSource).toContain("startNodeDrag");
    expect(routeSource).toContain("moveNodeDrag");
    expect(routeSource).toContain("finishNodeDrag");
    expect(routeSource).toContain("requestNodeDragFrame");
    expect(routeSource).toContain("window.requestAnimationFrame");
    expect(routeSource).toContain("window.cancelAnimationFrame");
    expect(routeSource).toContain("commitNodeDragPosition(dragState)");
    expect(routeSource).toContain("setPointerCapture(event.pointerId)");
    expect(routeSource).toContain("releasePointerCapture(event.pointerId)");
    expect(routeSource).toContain("nodes: canvas.nodes.map((node) => (node.id === dragState.nodeId");
    expect(routeSource).toContain("onPointerDown={(event) => startNodeDrag(event, node)}");
    expect(routeSource).toContain("onPointerMove={moveNodeDrag}");
    expect(routeSource).toContain("onPointerUp={finishNodeDrag}");
    expect(routeSource).toContain("edgeLine(edge, canvasNodes, visibleEdges)");
  });
});
