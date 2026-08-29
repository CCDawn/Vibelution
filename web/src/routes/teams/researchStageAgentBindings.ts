/**
 * Pure: map Team member roles onto research-stage Agent binding tables.
 * Canvas data is accepted for call-site compatibility but is projection-only.
 * Extracted from useTeamsWorkbenchModel (behavior-conserving).
 */
import type { AgentConfigWorkspaceAgent, Team, TeamOrganizationCanvas } from "../../api/types";
import { normalizeAgentRoleKey } from "./researchStageAgentPresentation";
import {
  KNOWLEDGE_EXPANSION_STAGE_AGENT_ROLES,
  RESEARCH_STAGE_AGENT_ROLES,
  type ResearchStageAgentRoleDefinition,
} from "./researchStageRoles";
import type { ResearchStageType } from "./source-collection/stageProjection";

export type ResearchStageAgentBinding = ResearchStageAgentRoleDefinition & {
  agentId: string;
  agent: AgentConfigWorkspaceAgent | null;
  bindingLabel: string;
  bindingSource: "member" | "fallback" | "";
};

export type ResearchStageAgentBindingsByStage = Record<ResearchStageType, ResearchStageAgentBinding[]>;

export function buildResearchStageAgentBindingsByStage(options: {
  /** Read-only canvas projection; never a source for Agent identity. */
  canvas: TeamOrganizationCanvas | null | undefined;
  selectedTeam: Team | null | undefined;
  activeAgentsById: Map<string, AgentConfigWorkspaceAgent>;
  knowledgeExpansionWorkflowTeamSelected: boolean;
}): ResearchStageAgentBindingsByStage {
  const {
    selectedTeam,
    activeAgentsById,
    knowledgeExpansionWorkflowTeamSelected,
  } = options;

  // Team.members is the Agent SSOT for workflow role bindings. Canvas nodes
  // are a display projection and must never override the canonical member.
  const roleBindings = new Map<string, { agentId: string; label: string; source: "member" }>();
  const roleDefinitions = knowledgeExpansionWorkflowTeamSelected
    ? KNOWLEDGE_EXPANSION_STAGE_AGENT_ROLES
    : RESEARCH_STAGE_AGENT_ROLES;

  for (const member of selectedTeam?.members ?? []) {
    const role = normalizeAgentRoleKey(member.role);
    if (role && member.agentId && !roleBindings.has(role)) {
      roleBindings.set(role, {
        agentId: member.agentId,
        label: member.agentName || member.agentCode || member.agentId,
        source: "member",
      });
    }
  }

  return Object.fromEntries(
    (Object.keys(roleDefinitions) as ResearchStageType[]).map((stageType) => {
      const bindings = roleDefinitions[stageType].map((definition) => {
        const matched = definition.roleKeys
          .map((role) => roleBindings.get(normalizeAgentRoleKey(role)))
          .find(Boolean);
        const fallbackAgentId = knowledgeExpansionWorkflowTeamSelected
          && definition.fallbackAgentId
          && activeAgentsById.has(definition.fallbackAgentId)
          ? definition.fallbackAgentId
          : "";
        const agentId = matched?.agentId || fallbackAgentId || "";
        return {
          ...definition,
          agentId,
          agent: agentId ? activeAgentsById.get(agentId) ?? null : null,
          bindingLabel: matched?.label || "",
          bindingSource: matched?.source || (fallbackAgentId ? "fallback" : ""),
        };
      });
      return [stageType, bindings];
    }),
  ) as ResearchStageAgentBindingsByStage;
}
