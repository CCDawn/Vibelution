import { describe, expect, it } from "vitest";

import type { Team } from "../../api/types";
import {
  AI_SEARCH_TEAM_ID,
  KNOWLEDGE_EXPANSION_TEAM_ID,
  RESEARCH_TEAM_ID,
} from "../TeamsRoute.canvasData";
import {
  isAiSearchScopeTeam,
  isKnowledgeExpansionWorkflowTeam,
  isResearchWorkflowTeam,
  isSystemManagedTeam,
  sourceCollectionAgentRolesForTeam,
  sourceCollectionWorkflowKindForTeam,
} from "./teamKindModel";

function team(partial: Partial<Team> & Pick<Team, "teamId">): Team {
  return {
    teamId: partial.teamId,
    name: partial.name || partial.teamId,
    status: partial.status || "ready",
    members: partial.members || [],
    teamKind: partial.teamKind,
    teamSource: partial.teamSource,
  } as Team;
}

describe("teamKindModel", () => {
  it("classifies research, knowledge expansion, and AI search system teams", () => {
    expect(isResearchWorkflowTeam(team({ teamId: RESEARCH_TEAM_ID }))).toBe(true);
    expect(isKnowledgeExpansionWorkflowTeam(team({ teamId: KNOWLEDGE_EXPANSION_TEAM_ID }))).toBe(true);
    expect(isAiSearchScopeTeam(team({ teamId: AI_SEARCH_TEAM_ID }))).toBe(true);
    expect(isSystemManagedTeam(team({ teamId: RESEARCH_TEAM_ID }))).toBe(true);
    expect(isSystemManagedTeam(team({ teamId: "user-team-1" }))).toBe(false);
  });

  it("selects source-collection role packs by team kind", () => {
    expect(sourceCollectionWorkflowKindForTeam(team({ teamId: KNOWLEDGE_EXPANSION_TEAM_ID }))).toBe(
      "knowledge_expansion",
    );
    expect(sourceCollectionAgentRolesForTeam(team({ teamId: RESEARCH_TEAM_ID }))).toContain("source_finder");
  });
});
