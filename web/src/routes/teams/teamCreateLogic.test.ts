import { describe, expect, it } from "vitest";

import type { Team, TeamTemplateSummary } from "../../api/types";
import { TEAM_PICKER_TEAM_IDS } from "../TeamsRoute.canvasData";
import {
  TEAM_NAME_MAX_LENGTH,
  createTeamCreateDraft,
  defaultTeamNameForOption,
  isVisibleRouteTeam,
  resolveTemplateOptions,
  selectVisibleTeams,
  teamCreateReady,
} from "./teamCreateLogic";

const devTeamTemplate: TeamTemplateSummary = {
  templateId: "dev-team",
  name: "开发团队",
  description: "四角色开发团队",
  purpose: "协作完成开发任务",
  defaultTeamName: "开发团队",
  roleCount: 4,
  safetyLevel: "standard",
  chatRoom: { mode: "collaborative", purpose: "team_coordination" },
};

function makeTeam(overrides: Partial<Team> & Pick<Team, "teamId">): Team {
  return {
    name: overrides.teamId,
    description: "",
    purpose: "",
    status: "active",
    teamKind: "custom",
    teamCategory: "",
    teamSource: "manual",
    members: [],
    memberCount: 0,
    canvasPath: "",
    createdAt: "",
    updatedAt: "",
    canvas: { path: "", nodeCount: 0, edgeCount: 0 },
    ...overrides,
  };
}

describe("team create draft readiness", () => {
  it("starts at the template select step with nothing selected", () => {
    const draft = createTeamCreateDraft();
    expect(draft.step).toBe("select");
    expect(draft.templateId).toBe("");
    expect(draft.name).toBe("");
    expect(teamCreateReady(draft)).toBe(false);
  });

  it("blank teams only need a non-empty name within the backend limit", () => {
    expect(teamCreateReady({ templateId: "", name: "  开发团队 " })).toBe(true);
    expect(teamCreateReady({ templateId: "", name: "   " })).toBe(false);
    expect(teamCreateReady({ templateId: "", name: "a".repeat(TEAM_NAME_MAX_LENGTH) })).toBe(true);
    expect(teamCreateReady({ templateId: "", name: "a".repeat(TEAM_NAME_MAX_LENGTH + 1) })).toBe(false);
  });

  it("template teams additionally need a known template id", () => {
    const templates = [devTeamTemplate];
    expect(teamCreateReady({ templateId: "dev-team", name: "开发团队" }, templates)).toBe(true);
    expect(teamCreateReady({ templateId: "dev-team", name: "" }, templates)).toBe(false);
    expect(teamCreateReady({ templateId: "unknown-template", name: "开发团队" }, templates)).toBe(false);
    expect(teamCreateReady({ templateId: "", name: "空白团队" }, templates)).toBe(true);
  });
});

describe("resolveTemplateOptions", () => {
  it("puts the blank virtual entry first and maps template fields", () => {
    const options = resolveTemplateOptions([devTeamTemplate]);
    expect(options).toHaveLength(2);
    expect(options[0]).toMatchObject({ templateId: "", blank: true, name: "" });
    expect(options[1]).toMatchObject({
      templateId: "dev-team",
      name: "开发团队",
      description: "四角色开发团队",
      roleCount: 4,
      defaultTeamName: "开发团队",
      blank: false,
    });
  });

  it("prefills the name field from the template default (empty for blank)", () => {
    expect(defaultTeamNameForOption("dev-team", [devTeamTemplate])).toBe("开发团队");
    expect(defaultTeamNameForOption("", [devTeamTemplate])).toBe("");
  });
});

describe("route picker visibility (fixed boards ∪ user-created)", () => {
  it("keeps the three fixed board teams visible", () => {
    for (const teamId of TEAM_PICKER_TEAM_IDS) {
      expect(isVisibleRouteTeam(makeTeam({ teamId }), TEAM_PICKER_TEAM_IDS)).toBe(true);
    }
  });

  it("shows user-created blank and template teams", () => {
    expect(isVisibleRouteTeam(
      makeTeam({ teamId: "team-20260927-a", teamSource: "manual", teamKind: "custom" }),
      TEAM_PICKER_TEAM_IDS,
    )).toBe(true);
    expect(isVisibleRouteTeam(
      makeTeam({ teamId: "team-20260927-b", teamSource: "team_template", teamKind: "template_demo" }),
      TEAM_PICKER_TEAM_IDS,
    )).toBe(true);
  });

  it("hides evolution system teams even with a manual-looking shape", () => {
    expect(isVisibleRouteTeam(
      makeTeam({ teamId: "self-evolution-team", teamSource: "manual", teamKind: "custom" }),
      TEAM_PICKER_TEAM_IDS,
    )).toBe(false);
    expect(isVisibleRouteTeam(
      makeTeam({ teamId: "team-evolution", teamSource: "self_evolution", teamKind: "supervised_evolution" }),
      TEAM_PICKER_TEAM_IDS,
    )).toBe(false);
  });

  it("hides workflow-owned teams that are not fixed picker boards", () => {
    expect(isVisibleRouteTeam(
      makeTeam({ teamId: "research-org-x", teamSource: "research_organization", teamKind: "research" }),
      TEAM_PICKER_TEAM_IDS,
    )).toBe(false);
    expect(isVisibleRouteTeam(
      makeTeam({ teamId: "ai-search-scope-x", teamSource: "ai_search", teamKind: "ai_search" }),
      TEAM_PICKER_TEAM_IDS,
    )).toBe(false);
  });

  it("newly created template team joins visibleTeams while evolution stays out", () => {
    const teams: Team[] = [
      makeTeam({ teamId: "research-team", teamSource: "research_organization", teamKind: "research" }),
      makeTeam({ teamId: "self-evolution-team", teamSource: "self_evolution", teamKind: "self_evolution" }),
      makeTeam({ teamId: "team-created-blank", teamSource: "manual", teamKind: "custom" }),
      makeTeam({ teamId: "team-created-template", teamSource: "team_template", teamKind: "template_demo" }),
    ];
    const visible = selectVisibleTeams(teams, TEAM_PICKER_TEAM_IDS);
    expect(visible.map((team) => team.teamId)).toEqual([
      "research-team",
      "team-created-blank",
      "team-created-template",
    ]);
  });

  it("keeps fixed board rail order ahead of user-created teams", () => {
    const teams: Team[] = [
      makeTeam({ teamId: "team-user-1", teamSource: "manual", teamKind: "custom" }),
      makeTeam({ teamId: "ai-search-team", teamSource: "ai_search", teamKind: "ai_search" }),
      makeTeam({ teamId: "knowledge-expansion-team", teamSource: "knowledge_expansion", teamKind: "knowledge_expansion" }),
      makeTeam({ teamId: "research-team", teamSource: "research_organization", teamKind: "research" }),
    ];
    const visible = selectVisibleTeams(teams, TEAM_PICKER_TEAM_IDS);
    expect(visible.map((team) => team.teamId)).toEqual([
      "research-team",
      "ai-search-team",
      "knowledge-expansion-team",
      "team-user-1",
    ]);
  });
});
