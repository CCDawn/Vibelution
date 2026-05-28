import { describe, expect, it } from "vitest";

import navSource from "./AgentManagementNav.tsx?raw";
import routeSource from "./TeamsRoute.tsx?raw";
import routerSource from "../app/router.tsx?raw";

describe("TeamsRoute layout contract", () => {
  it("is mounted under Agent management with a team nav item", () => {
    expect(routerSource).toContain('path: "agents/teams"');
    expect(routerSource).toContain("<TeamsRoute />");
    expect(navSource).toContain('"teams"');
    expect(navSource).toContain("/agents/teams");
    expect(routeSource).toContain('<AgentManagementNav active="teams" className={styles.managementNav} />');
  });

  it("uses Team APIs and Agent Center as the binding source", () => {
    expect(routeSource).toContain('fetchJson<TeamListPayload>("/api/teams")');
    expect(routeSource).toContain("fetchJson<Team>(`/api/teams/${encodeURIComponent(effectiveTeamId)}`)");
    expect(routeSource).toContain('fetchJson<AgentConfigWorkspace>("/api/agents/config-workspace")');
    expect(routeSource).toContain("fetchJson<Team>(`/api/teams/${encodeURIComponent(teamId)}`");
    expect(routeSource).toContain('method: "DELETE"');
    expect(routeSource).toContain("fetchJson<ProjectAgentBusEvent>(`/api/teams/${encodeURIComponent(payload.teamId)}/messages`");
    expect(routeSource).toContain('fetchJson<ProjectAgentBusTimeline>("/api/project-agent-bus?limit=120")');
    expect(routeSource).toContain("/api/project-agent-bus/messages/${encodeURIComponent(eventId)}/revoke");
    expect(routeSource).toContain("/api/teams/${encodeURIComponent(nextCanvas.teamId)}/canvas");
    expect(routeSource).toContain("Agent Center");
    expect(routeSource).toContain("team_organization_canvas");
    expect(routeSource).not.toContain("/api/research/flow-canvas");
    expect(routeSource).not.toContain("/api/chat-rooms");
  });

  it("can deep-link from Agent references to a selected Team", () => {
    expect(routeSource).toContain("useSearchParams");
    expect(routeSource).toContain('searchParams.get("team")');
    expect(routeSource).toContain("setSearchParams({ team: team.teamId })");
  });

  it("renders a dense list canvas inspector workflow", () => {
    expect(routeSource).toContain("teamList");
    expect(routeSource).toContain("canvasPanel");
    expect(routeSource).toContain("inspector");
    expect(routeSource).toContain("绑定 Agent");
    expect(routeSource).toContain("接入主干");
    expect(routeSource).toContain("保存节点");
    expect(routeSource).toContain("归档");
    expect(routeSource).toContain("解绑节点");
    expect(routeSource).toContain("删除节点");
    expect(routeSource).toContain("团队广播");
    expect(routeSource).toContain("发送给团队");
    expect(routeSource).toContain("最近团队广播");
    expect(routeSource).toContain("teamBusEvents");
    expect(routeSource).toContain("projectBusEventRevoked");
    expect(routeSource).toContain("revokeTeamMessageMutation");
    expect(routeSource).toContain("styles.teamHistoryPanel");
    expect(routeSource).toContain("interrupt_targets");
    expect(routeSource).toContain("edges: canvas.edges.filter((edge) => edge.source !== deletedNodeId && edge.target !== deletedNodeId)");
  });
});
