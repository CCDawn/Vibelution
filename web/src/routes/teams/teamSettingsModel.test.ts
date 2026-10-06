import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent, Team } from "../../api/types";
import {
  buildTeamSettingsPayload,
  createTeamSettingsDraft,
  teamMemberModelStatus,
  teamSettingsAgentOptions,
  teamSettingsCopy,
  teamSettingsDirty,
} from "./teamSettingsModel";

function makeAgent(agentId: string, displayName: string, modelId = ""): AgentConfigWorkspaceAgent {
  return {
    agentId,
    agentCode: agentId.toUpperCase(),
    displayName,
    status: "active",
    llmBindings: modelId ? { dialogue: { modelId } } : {},
  } as AgentConfigWorkspaceAgent;
}

function makeTeam(patch: Partial<Team> = {}): Team {
  return {
    teamId: "team-a",
    name: "Alpha Team",
    description: "desc",
    purpose: "purpose",
    status: "active",
    teamKind: "custom",
    teamCategory: "自定义团队",
    teamSource: "manual",
    members: [],
    memberCount: 0,
    updatedAt: "2026-10-06T00:00:00Z",
    ...patch,
  } as Team;
}

describe("teamSettingsModel", () => {
  it("creates a draft from the team and reports clean state", () => {
    const team = makeTeam({
      members: [
        {
          memberId: "member-1",
          agentId: "agent-1",
          agentCode: "A1",
          agentName: "Alpha",
          role: "lead",
          purpose: "协调",
          agentStatus: "active",
        },
      ],
    });
    const draft = createTeamSettingsDraft(team);
    expect(draft.name).toBe("Alpha Team");
    expect(draft.members).toHaveLength(1);
    expect(draft.members[0]).toMatchObject({ memberId: "member-1", agentId: "agent-1", nextAgentId: "", remove: false });
    expect(teamSettingsDirty(draft, team)).toBe(false);
  });

  it("builds a basics-only payload until the roster changes", () => {
    const team = makeTeam({
      members: [
        {
          memberId: "member-1",
          agentId: "agent-1",
          agentCode: "A1",
          agentName: "Alpha",
          role: "lead",
          purpose: "",
          agentStatus: "active",
        },
      ],
    });
    const draft = createTeamSettingsDraft(team);
    draft.name = "Renamed";
    const payload = buildTeamSettingsPayload(draft, team);
    expect(payload).toEqual({ name: "Renamed" });
  });

  it("rebinds a member to another agent and keeps responsibilities", () => {
    const team = makeTeam({
      members: [
        {
          memberId: "member-1",
          agentId: "agent-1",
          agentCode: "A1",
          agentName: "Alpha",
          role: "lead",
          purpose: "",
          agentStatus: "active",
          responsibilities: ["收集证据"],
        },
      ],
    });
    const draft = createTeamSettingsDraft(team);
    draft.members[0].nextAgentId = "agent-2";
    const payload = buildTeamSettingsPayload(draft, team);
    expect(payload.members).toEqual([
      { memberId: "member-1", agentId: "agent-2", role: "lead", purpose: "", responsibilities: ["收集证据"] },
    ]);
    expect(teamSettingsDirty(draft, team)).toBe(true);
  });

  it("supports unbind and add for an empty team without a canvas", () => {
    const team = makeTeam();
    const draft = createTeamSettingsDraft(team);
    expect(draft.members).toHaveLength(0);
    draft.addRole = "reviewer";
    draft.addAgentId = "agent-9";
    const payload = buildTeamSettingsPayload(draft, team);
    expect(payload.members).toEqual([{ memberId: "", agentId: "agent-9", role: "reviewer", purpose: "" }]);

    const withMember = makeTeam({
      members: [
        {
          memberId: "member-1",
          agentId: "agent-1",
          agentCode: "A1",
          agentName: "Alpha",
          role: "lead",
          purpose: "",
          agentStatus: "active",
        },
      ],
    });
    const removeDraft = createTeamSettingsDraft(withMember);
    removeDraft.members[0].remove = true;
    expect(buildTeamSettingsPayload(removeDraft, withMember).members).toEqual([]);
  });

  it("filters agent options to active agents and marks agents bound to other teams", () => {
    const agents = [
      makeAgent("agent-1", "Alpha", "m1"),
      makeAgent("agent-2", "Beta"),
      makeAgent("agent-3", "Taken"),
    ];
    const otherTeam = makeTeam({
      teamId: "team-b",
      members: [
        { memberId: "m", agentId: "agent-3", agentCode: "", agentName: "", role: "", purpose: "", agentStatus: "active" },
      ],
    });
    const team = makeTeam();
    const options = teamSettingsAgentOptions({ agents, teams: [team, otherTeam], team });
    expect(options.map((option) => option.id)).toEqual(["agent-1", "agent-2", "agent-3"]);
    expect(options.find((option) => option.id === "agent-3")?.disabled).toBe(true);
    expect(options.find((option) => option.id === "agent-1")?.disabled).toBe(false);
  });

  it("derives model status from the detail projection with a config route", () => {
    const agentsById = new Map([
      ["agent-1", makeAgent("agent-1", "Alpha")],
      ["agent-catalog", makeAgent("agent-catalog", "Catalog", "prov/model-z")],
    ]);
    const configured = teamMemberModelStatus(
      { agentId: "agent-1", model: { dialogueModelId: "prov/model-a", configured: true } } as Team["members"][number],
      agentsById,
      "zh",
    );
    expect(configured.configured).toBe(true);
    expect(configured.label).toBe("已配模型");
    expect(configured.configRoute).toBe("/agents?pane=config&agent=agent-1");

    const unconfigured = teamMemberModelStatus(
      { agentId: "agent-1" } as Team["members"][number],
      agentsById,
      "zh",
    );
    expect(unconfigured.configured).toBe(false);
    expect(unconfigured.configRoute).toBe("/agents?pane=config&agent=agent-1");

    const fallbackToCatalog = teamMemberModelStatus(
      { agentId: "agent-catalog" } as Team["members"][number],
      agentsById,
      "en",
    );
    expect(fallbackToCatalog.configured).toBe(true);
  });

  it("provides the zh/en copy table", () => {
    expect(teamSettingsCopy("zh").title).toBe("团队设置");
    expect(teamSettingsCopy("en").title).toBe("Team settings");
    expect(teamSettingsCopy("zh").roomCreate).toBe("创建群聊房间");
    expect(teamSettingsCopy("en").roomParticipants(2)).toBe("2 participants");
  });
});
