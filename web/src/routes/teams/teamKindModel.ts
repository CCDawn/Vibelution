import type { Team } from "../../api/types";
import {
  AI_SEARCH_TEAM_ID,
  KNOWLEDGE_EXPANSION_TEAM_ID,
  RESEARCH_TEAM_ID,
} from "../TeamsRoute.canvasData";

export const EVOLUTION_SYSTEM_TEAM_IDS = new Set(["self-evolution-team", "supervised-evolution-team"]);

export const SOURCE_COLLECTION_DEFAULT_ROLES: string[] = [
  "source_finder",
  "source_extractor",
  "source_relation_mapper",
  "source_ingestor",
];

export const SOURCE_COLLECTION_KNOWLEDGE_EXPANSION_ROLES: string[] = SOURCE_COLLECTION_DEFAULT_ROLES;

/** Alias kept for existing TeamsRoute call sites (same pack as default roles). */
export const SOURCE_COLLECTION_TEAM_AGENT_ROLES: string[] = [...SOURCE_COLLECTION_DEFAULT_ROLES];

export function isChallengeCupResearchWorkflowTeam(team: Team | null | undefined) {
  if (!team) {
    return false;
  }
  return (
    team.teamId === RESEARCH_TEAM_ID
    || team.teamSource === "research_organization"
    || team.teamKind === "research"
  );
}

export function isKnowledgeExpansionWorkflowTeam(team: Team | null | undefined) {
  if (!team) {
    return false;
  }
  return (
    team.teamId === KNOWLEDGE_EXPANSION_TEAM_ID
    || team.teamSource === "knowledge_expansion"
    || team.teamKind === "knowledge_expansion"
  );
}

export function isResearchWorkflowTeam(team: Team | null | undefined) {
  return isChallengeCupResearchWorkflowTeam(team) || isKnowledgeExpansionWorkflowTeam(team);
}

export function isEvolutionSystemTeam(team: Team | null | undefined) {
  if (!team) {
    return false;
  }
  return (
    EVOLUTION_SYSTEM_TEAM_IDS.has(team.teamId)
    || team.teamKind === "self_evolution"
    || team.teamKind === "supervised_evolution"
    || team.teamSource === "self_evolution"
    || team.teamSource === "supervised_evolution"
  );
}

export function isAiSearchScopeTeam(team: Team | null | undefined) {
  if (!team) {
    return false;
  }
  return team.teamId === AI_SEARCH_TEAM_ID || team.teamKind === "ai_search" || team.teamSource === "ai_search";
}

export function isSystemManagedTeam(team: Team | null | undefined) {
  return isResearchWorkflowTeam(team) || isEvolutionSystemTeam(team) || isAiSearchScopeTeam(team);
}

export function sourceCollectionWorkflowKindForTeam(team: Team | null | undefined) {
  return isKnowledgeExpansionWorkflowTeam(team) ? "knowledge_expansion" : "challenge_cup_research";
}

export function sourceCollectionWorkflowPurposeForTeam(team: Team | null | undefined) {
  return isKnowledgeExpansionWorkflowTeam(team) ? "knowledge_expansion" : "challenge_cup_research";
}

export function sourceCollectionAgentRolesForTeam(team: Team | null | undefined) {
  return isKnowledgeExpansionWorkflowTeam(team)
    ? [...SOURCE_COLLECTION_KNOWLEDGE_EXPANSION_ROLES]
    : [...SOURCE_COLLECTION_DEFAULT_ROLES];
}

export function systemManagedTeamArchiveReason(team: Team | null | undefined, lang: "zh" | "en") {
  if (!team || !isSystemManagedTeam(team)) {
    return "";
  }
  return lang === "zh"
    ? "系统团队由工作流自动维护，不能在这里归档。"
    : "System teams are maintained by workflows and cannot be archived here.";
}
