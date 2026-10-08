import { describe, expect, it } from "vitest";

import type { Team } from "../../api/types";
import {
  AI_SEARCH_TEAM_ID,
  KNOWLEDGE_EXPANSION_TEAM_ID,
  RESEARCH_TEAM_ID,
} from "../TeamsRoute.canvasData";
import {
  isAiSearchScopeTeam,
  isEvolutionSystemTeam,
  isKnowledgeExpansionWorkflowTeam,
  isResearchWorkflowTeam,
  isSystemManagedTeam,
  sourceCollectionAgentRolesForTeam,
  sourceCollectionWorkflowKindForTeam,
  systemManagedTeamArchiveReason,
} from "./teamKindModel";

function team(partial: Partial<Team> & Pick<Team, "teamId">): Team {
  return {
    teamId: partial.teamId,
    name: partial.name || partial.teamId,
    status: partial.status || "ready",
    members: partial.members || [],
    teamKind: partial.teamKind,
    teamSource: partial.teamSource,
    systemManaged: partial.systemManaged,
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

  it("keys system-managed judgment on the backend flag with legacy fallback", () => {
    // Flag alone decides, without kind/source/id enumerations.
    expect(isSystemManagedTeam(team({ teamId: "self-evolution-team", systemManaged: true }))).toBe(true);
    expect(isSystemManagedTeam(team({ teamId: "user-team-1", systemManaged: true }))).toBe(true);
    // An explicit non-managed flag overrides stale kind enumerations.
    expect(isSystemManagedTeam(team({ teamId: "user-team-1", teamKind: "research", systemManaged: false }))).toBe(false);
    // Missing flag (pre-flag payloads) falls back to the workflow composition.
    expect(isSystemManagedTeam(team({ teamId: "user-team-1", teamKind: "self_evolution" }))).toBe(true);
  });

  it("keeps evolution-system judgment evolution-scoped under the flag", () => {
    expect(isEvolutionSystemTeam(team({ teamId: "self-evolution-team", systemManaged: true }))).toBe(true);
    expect(isEvolutionSystemTeam(team({ teamId: RESEARCH_TEAM_ID, systemManaged: true }))).toBe(false);
    expect(isEvolutionSystemTeam(team({ teamId: "user-team-1", teamKind: "self_evolution", systemManaged: false }))).toBe(false);
    expect(systemManagedTeamArchiveReason(team({ teamId: "self-evolution-team", systemManaged: true }), "zh")).not.toBe("");
    expect(systemManagedTeamArchiveReason(team({ teamId: "user-team-1", systemManaged: false }), "zh")).toBe("");
  });

  it("selects source-collection role packs by team kind", () => {
    expect(sourceCollectionWorkflowKindForTeam(team({ teamId: KNOWLEDGE_EXPANSION_TEAM_ID }))).toBe(
      "knowledge_expansion",
    );
    expect(sourceCollectionAgentRolesForTeam(team({ teamId: RESEARCH_TEAM_ID }))).toContain("source_finder");
  });
});
