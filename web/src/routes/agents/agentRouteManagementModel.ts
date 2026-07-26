/**
 * Agents management brief, setup filters, and list column pure helpers (structure M2).
 * Pure: no React hooks / Query / DOM.
 */
import type {
  AgentConfigWorkspaceAgent,
  AgentConfigWorkspaceGroup,
} from "../../api/types";
import type { AgentTeamIndexGroup } from "../agentWorkspaceCache";
import {
  agentHasTeamReference,
  hasModelAndPromptConfiguration,
  hasPersonaProfile,
  hasTaskProfile,
  hasToolPolicyConfiguration,
  hasWorkspaceConfiguration,
  isWorkSessionAgent,
  requiresPersonaProfile,
  requiresTaskProfile,
  requiresTeamMembership,
} from "./agentRouteDraftModel";

export type AgentConfigPaneId =
  | "overview"
  | "effective"
  | "relations"
  | "config"
  | "changes"
  | "activity";

export type AgentManagementAction = {
  id: string;
  label: string;
  detail: string;
  pane: AgentConfigPaneId;
  route?: string;
};

export type AgentManagementBrief = {
  score: number;
  completed: number;
  total: number;
  statusLabel: string;
  statusDetail: string;
  items: Array<{
    id: string;
    label: string;
    complete: boolean;
    pane: AgentConfigPaneId;
  }>;
  actions: AgentManagementAction[];
};

export type AgentManagementFilterGroup = {
  id: string;
  label: string;
  count: number;
  description?: string;
  healthCount?: number;
};

export type AgentFilterGroup = AgentConfigWorkspaceGroup | AgentTeamIndexGroup;

export type AgentListColumn = {
  id: string;
  label: string;
  description: string;
  agents: AgentConfigWorkspaceAgent[];
};

type ManagementCopy = {
  managementModelPrompt: string;
  managementTools: string;
  managementWorkspace: string;
  managementRuntime: string;
  managementIdentity: string;
  managementTask: string;
  managementMembership: string;
  nextSetupModelPrompt: string;
  nextSetupModelPromptHint: string;
  nextSetupIdentity: string;
  nextSetupIdentityHint: string;
  nextSetupTask: string;
  nextSetupTaskHint: string;
  nextSetupTools: string;
  nextSetupToolsHint: string;
  nextSetupWorkspace: string;
  nextSetupWorkspaceHint: string;
  nextSetupMembership: string;
  nextSetupMembershipHint: string;
  nextHandleInbox: string;
  nextHandleInboxHint: string;
  managementFilterMissingPersona: string;
  managementFilterMissingPersonaHint: string;
  managementFilterMissingTask: string;
  managementFilterMissingTaskHint: string;
  managementFilterMissingTools: string;
  managementFilterMissingToolsHint: string;
  managementFilterNoTeam: string;
  managementFilterNoTeamHint: string;
  managementFilterPendingInbox: string;
  managementFilterPendingInboxHint: string;
  managementFilterMaintenance: string;
  managementFilterMaintenanceHint: string;
  activeAgents: string;
  groupLabels: Record<string, string>;
  groupDescriptions: Record<string, string>;
  statusReminderShort: string;
  healthIssueShort: string;
  sessionAgentColumn: string;
  sessionAgentColumnHint: string;
  nonSessionAgentColumn: string;
  nonSessionAgentColumnHint: string;
  teamAgentColumnHint: string;
};

export function agentHasRuntimeSignal(agent: AgentConfigWorkspaceAgent | null | undefined) {
  const runtimeState = String(agent?.runtimeStatus?.state || "").trim();
  return Boolean(runtimeState && runtimeState !== "idle") || (agent?.agentInboxPendingCount ?? 0) > 0;
}

export function hasActionableHealthIssue(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return Boolean(agent?.health?.some((issue) => issue.severity === "blocking" || issue.severity === "warning"));
}

export function buildAgentManagementBrief(
  agent: AgentConfigWorkspaceAgent | null | undefined,
  copy: ManagementCopy,
  lang: "zh" | "en",
): AgentManagementBrief {
  const workSession = isWorkSessionAgent(agent);
  const items = workSession
    ? [
        { id: "model_prompt", label: copy.managementModelPrompt, complete: hasModelAndPromptConfiguration(agent), pane: "config" as const },
        { id: "tools", label: copy.managementTools, complete: hasToolPolicyConfiguration(agent), pane: "config" as const },
        { id: "workspace", label: copy.managementWorkspace, complete: hasWorkspaceConfiguration(agent), pane: "config" as const },
        { id: "runtime", label: copy.managementRuntime, complete: agentHasRuntimeSignal(agent), pane: "activity" as const },
      ]
    : [
        { id: "identity", label: copy.managementIdentity, complete: !requiresPersonaProfile(agent) || hasPersonaProfile(agent), pane: "config" as const },
        { id: "task", label: copy.managementTask, complete: !requiresTaskProfile(agent) || hasTaskProfile(agent), pane: "config" as const },
        { id: "tools", label: copy.managementTools, complete: hasToolPolicyConfiguration(agent), pane: "config" as const },
        { id: "membership", label: copy.managementMembership, complete: !requiresTeamMembership(agent) || agentHasTeamReference(agent), pane: "config" as const },
        { id: "runtime", label: copy.managementRuntime, complete: agentHasRuntimeSignal(agent), pane: "activity" as const },
      ];
  const actions: AgentManagementAction[] = [];
  if (workSession && !items[0].complete) {
    actions.push({ id: "model_prompt", label: copy.nextSetupModelPrompt, detail: copy.nextSetupModelPromptHint, pane: "config" });
  }
  if (!workSession && !items[0].complete) {
    actions.push({ id: "identity", label: copy.nextSetupIdentity, detail: copy.nextSetupIdentityHint, pane: "config" });
  }
  if (!workSession && !items[1].complete) {
    actions.push({ id: "task", label: copy.nextSetupTask, detail: copy.nextSetupTaskHint, pane: "config" });
  }
  if (!items.find((item) => item.id === "tools")?.complete) {
    actions.push({ id: "tools", label: copy.nextSetupTools, detail: copy.nextSetupToolsHint, pane: "config" });
  }
  if (workSession && !items.find((item) => item.id === "workspace")?.complete) {
    actions.push({ id: "workspace", label: copy.nextSetupWorkspace, detail: copy.nextSetupWorkspaceHint, pane: "config" });
  }
  if (!workSession && !items.find((item) => item.id === "membership")?.complete) {
    actions.push({
      id: "membership",
      label: copy.nextSetupMembership,
      detail: copy.nextSetupMembershipHint,
      pane: "config",
      route: agent?.agentId ? `/teams?agent=${encodeURIComponent(agent.agentId)}` : "/teams",
    });
  }
  if ((agent?.agentInboxPendingCount ?? 0) > 0) {
    actions.unshift({ id: "inbox", label: copy.nextHandleInbox, detail: copy.nextHandleInboxHint, pane: "activity" });
  }
  const completed = items.filter((item) => item.complete).length;
  const score = items.length ? Math.round((completed / items.length) * 100) : 0;
  return {
    score,
    completed,
    total: items.length,
    statusLabel: lang === "zh" ? `${score}% 完整` : `${score}% complete`,
    statusDetail: lang === "zh" ? `${completed}/${items.length} 项已就绪` : `${completed}/${items.length} ready`,
    items,
    actions: actions.slice(0, 3),
  };
}

export function buildManagementFilterGroups(
  agents: AgentConfigWorkspaceAgent[],
  copy: ManagementCopy,
): AgentManagementFilterGroup[] {
  const activeAgents = agents.filter((agent) => agent.status !== "archived");
  const count = (predicate: (agent: AgentConfigWorkspaceAgent) => boolean) => activeAgents.filter(predicate).length;
  return [
    {
      id: "setup:persona",
      label: copy.managementFilterMissingPersona,
      count: count((agent) => requiresPersonaProfile(agent) && !hasPersonaProfile(agent)),
      description: copy.managementFilterMissingPersonaHint,
    },
    {
      id: "setup:task",
      label: copy.managementFilterMissingTask,
      count: count((agent) => requiresTaskProfile(agent) && !hasTaskProfile(agent)),
      description: copy.managementFilterMissingTaskHint,
    },
    {
      id: "setup:tools",
      label: copy.managementFilterMissingTools,
      count: count((agent) => !hasToolPolicyConfiguration(agent)),
      description: copy.managementFilterMissingToolsHint,
    },
    {
      id: "setup:membership",
      label: copy.managementFilterNoTeam,
      count: count((agent) => requiresTeamMembership(agent) && !agentHasTeamReference(agent)),
      description: copy.managementFilterNoTeamHint,
    },
    {
      id: "setup:inbox",
      label: copy.managementFilterPendingInbox,
      count: count((agent) => (agent.agentInboxPendingCount ?? 0) > 0),
      description: copy.managementFilterPendingInboxHint,
      healthCount: count((agent) => (agent.agentInboxPendingCount ?? 0) > 0),
    },
    {
      id: "setup:maintenance",
      label: copy.managementFilterMaintenance,
      count: count(hasActionableHealthIssue),
      description: copy.managementFilterMaintenanceHint,
      healthCount: count(hasActionableHealthIssue),
    },
  ];
}

export function managementFilterMatches(agent: AgentConfigWorkspaceAgent, activeFilter: string) {
  switch (activeFilter) {
    case "setup:persona":
      return requiresPersonaProfile(agent) && !hasPersonaProfile(agent);
    case "setup:task":
      return requiresTaskProfile(agent) && !hasTaskProfile(agent);
    case "setup:tools":
      return !hasToolPolicyConfiguration(agent);
    case "setup:membership":
      return requiresTeamMembership(agent) && !agentHasTeamReference(agent);
    case "setup:inbox":
      return (agent.agentInboxPendingCount ?? 0) > 0;
    case "setup:maintenance":
      return hasActionableHealthIssue(agent);
    default:
      return true;
  }
}

export function groupDisplayLabel(
  group: { id: string; label?: string } | undefined,
  copy: Pick<ManagementCopy, "activeAgents" | "groupLabels">,
) {
  if (!group) {
    return copy.activeAgents;
  }
  return copy.groupLabels[group.id] ?? group.label;
}

export function groupSectionId(group: AgentFilterGroup) {
  const section = String(group.section || "").trim();
  return section === "boundary"
    || section === "mode"
    || section === "reference"
    || section === "team_index"
    || section === "source_scope"
    ? section
    : "status";
}

export function groupDescription(
  group: { id: string; description?: string },
  copy: Pick<ManagementCopy, "groupDescriptions">,
) {
  return copy.groupDescriptions[group.id] ?? group.description ?? "";
}

export function groupAriaLabel(
  label: string,
  group: { id?: string; count: number; healthCount?: number },
  copy: Pick<ManagementCopy, "statusReminderShort" | "healthIssueShort">,
  lang: "zh" | "en",
) {
  if (!group.healthCount) {
    return lang === "zh" ? `${label}，${group.count} 个 Agent` : `${label}, ${group.count} Agents`;
  }
  const countLabel = group.id === "setup:inbox" ? copy.statusReminderShort : copy.healthIssueShort;
  return lang === "zh"
    ? `${label}，${group.count} 个 Agent，${countLabel} ${group.healthCount} 个`
    : `${label}, ${group.count} Agents, ${countLabel} ${group.healthCount}`;
}

export function buildVisibleAgentColumns(
  agents: AgentConfigWorkspaceAgent[],
  copy: Pick<
    ManagementCopy,
    | "sessionAgentColumn"
    | "sessionAgentColumnHint"
    | "nonSessionAgentColumn"
    | "nonSessionAgentColumnHint"
    | "teamAgentColumnHint"
  >,
  teamIndexGroups: AgentTeamIndexGroup[],
): AgentListColumn[] {
  const sessionAgents = agents.filter(isWorkSessionAgent);
  const nonSessionAgents = agents.filter((agent) => !isWorkSessionAgent(agent));
  const visibleNonSessionIds = new Set(nonSessionAgents.map((agent) => agent.agentId));
  const assignedTeamAgentIds = new Set<string>();
  const teamColumns = teamIndexGroups
    .filter((group) => group.section === "team_index")
    .map((group) => {
      const groupIds = new Set(group.agentIds);
      const teamAgents = nonSessionAgents.filter((agent) => {
        if (!groupIds.has(agent.agentId) || assignedTeamAgentIds.has(agent.agentId)) {
          return false;
        }
        return visibleNonSessionIds.has(agent.agentId);
      });
      teamAgents.forEach((agent) => assignedTeamAgentIds.add(agent.agentId));
      return {
        id: `team_agents:${group.id}`,
        label: group.label,
        description: group.description || copy.teamAgentColumnHint,
        agents: teamAgents,
      };
    })
    .filter((column) => column.agents.length > 0);
  const unassignedNonSessionAgents = nonSessionAgents.filter((agent) => !assignedTeamAgentIds.has(agent.agentId));
  return [
    {
      id: "session_agents",
      label: copy.sessionAgentColumn,
      description: copy.sessionAgentColumnHint,
      agents: sessionAgents,
    },
    ...teamColumns,
    {
      id: "non_session_agents",
      label: copy.nonSessionAgentColumn,
      description: copy.nonSessionAgentColumnHint,
      agents: unassignedNonSessionAgents,
    },
  ].filter((column) => column.agents.length > 0);
}

export function normalizeAgentConfigPane(value: string | null | undefined): AgentConfigPaneId {
  const normalized = String(value || "").trim();
  return normalized === "effective"
    || normalized === "relations"
    || normalized === "config"
    || normalized === "changes"
    || normalized === "activity"
    || normalized === "overview"
    ? normalized
    : "overview";
}
