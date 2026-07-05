import type { Team, TeamCanvasNode, TeamOrganizationCanvas } from "../api/types";

export const RESEARCH_TEAM_ID = "research-team";
export const AI_SEARCH_TEAM_ID = "ai-search-team";
export const KNOWLEDGE_EXPANSION_TEAM_ID = "knowledge-expansion-team";
export const TEAM_ORGANIZATION_CANVAS_KIND = "team_organization_canvas";
export const TEAM_PICKER_TEAM_IDS = [AI_SEARCH_TEAM_ID, KNOWLEDGE_EXPANSION_TEAM_ID, RESEARCH_TEAM_ID] as const;

const TEAM_PICKER_TEAM_ID_SET: ReadonlySet<string> = new Set(TEAM_PICKER_TEAM_IDS);
const AI_SEARCH_CANVAS_SKELETON_ROLES = [
  {
    id: "ai-search-skeleton-lead",
    label: "搜索范围负责人",
    role: "ai_search_scope_lead",
    purpose: "维护搜索边界、可信度分层和默认启用规则。",
    x: 120,
    y: 210,
  },
  {
    id: "ai-search-skeleton-global",
    label: "全球官方源维护",
    role: "global_primary_sources",
    purpose: "维护全球 AI 一手源。",
    x: 420,
    y: 80,
  },
  {
    id: "ai-search-skeleton-cn",
    label: "中国 AI 源维护",
    role: "cn_primary_sources",
    purpose: "维护中国 AI 一手源。",
    x: 420,
    y: 340,
  },
  {
    id: "ai-search-skeleton-quality",
    label: "信号源质检",
    role: "signal_quality_gate",
    purpose: "要求信号回链到一手证据。",
    x: 720,
    y: 210,
  },
] as const;

export type TeamsRouteEffectiveTeamIdInput = {
  forcedTeamId: string;
  selectedTeamId: string;
  requestedTeamId: string;
  requestedAgentTeamId: string;
  visibleTeamIds: Iterable<string>;
  fallbackTeamId: string;
};

export function resolveKnownRouteTeamId(requestedTeamId: string, visibleTeamIds: ReadonlySet<string>) {
  return requestedTeamId && (visibleTeamIds.has(requestedTeamId) || TEAM_PICKER_TEAM_ID_SET.has(requestedTeamId))
    ? requestedTeamId
    : "";
}

export function resolveTeamsRouteEffectiveTeamId(input: TeamsRouteEffectiveTeamIdInput) {
  const visibleTeamIds = input.visibleTeamIds instanceof Set
    ? input.visibleTeamIds
    : new Set(input.visibleTeamIds);
  const selectedVisibleTeamId = input.selectedTeamId && visibleTeamIds.has(input.selectedTeamId) ? input.selectedTeamId : "";
  const requestedKnownTeamId = resolveKnownRouteTeamId(input.requestedTeamId, visibleTeamIds);
  const requestedVisibleAgentTeamId =
    input.requestedAgentTeamId && visibleTeamIds.has(input.requestedAgentTeamId) ? input.requestedAgentTeamId : "";
  return (
    input.forcedTeamId
    || selectedVisibleTeamId
    || requestedKnownTeamId
    || requestedVisibleAgentTeamId
    || input.fallbackTeamId
    || ""
  );
}

export function canvasFromTeam(team: Team | null): TeamOrganizationCanvas | null {
  if (!team || !team.canvas || !("nodes" in team.canvas)) {
    return null;
  }
  return team.canvas as TeamOrganizationCanvas;
}

export function canvasFromTeamOrFallback(
  team: Pick<Team, "canvas"> | null,
  fallbackCanvas: TeamOrganizationCanvas | null | undefined,
  memberCanvas?: TeamOrganizationCanvas | null,
): TeamOrganizationCanvas | null {
  return canvasFromTeam(team as Team | null) ?? fallbackCanvas ?? memberCanvas ?? null;
}

export function memberCanvasFromTeam(team: Pick<Team, "teamId" | "name" | "canvasPath" | "members"> | null | undefined): TeamOrganizationCanvas | null {
  const members = team?.members ?? [];
  if (!team || members.length === 0) {
    return null;
  }
  const nodes: TeamCanvasNode[] = members.map((member, index) => ({
    id: `member-${member.agentId || member.memberId || index}`,
    label: member.purpose || member.role || member.agentName || member.agentCode || member.agentId,
    type: member.agentId ? "agent" : "role",
    status: member.agentStatus === "stale" ? "stale" : member.agentId ? "bound" : "unbound",
    x: 96 + index * 196,
    y: index === 0 ? 180 : 300,
    agentId: member.agentId,
    agentCode: member.agentCode,
    agentName: member.agentName,
    role: member.role,
    purpose: member.purpose,
    responsibilities: member.responsibilities,
  }));
  return {
    schemaVersion: 1,
    canvasKind: TEAM_ORGANIZATION_CANVAS_KIND,
    teamId: team.teamId,
    updatedAt: "",
    path: team.canvasPath || `workspace/teams/${team.teamId}/canvas.json`,
    viewport: { x: 0, y: 0, zoom: 1 },
    nodes,
    edges: nodes.slice(1).map((node) => ({
      id: `${nodes[0].id}-${node.id}`,
      source: nodes[0].id,
      target: node.id,
      label: "",
      type: "reports_to",
    })),
    validation: {
      valid: true,
      summary: { errorCount: 0, warningCount: 0, issueCount: 0 },
      issues: [],
    },
  };
}

export function canvasFromKnownTeamId(teamId: string): TeamOrganizationCanvas | null {
  if (teamId !== AI_SEARCH_TEAM_ID) {
    return null;
  }
  const nodes: TeamCanvasNode[] = AI_SEARCH_CANVAS_SKELETON_ROLES.map((role) => ({
    id: role.id,
    label: role.label,
    type: "role",
    status: "unbound",
    x: role.x,
    y: role.y,
    agentId: "",
    agentCode: "",
    agentName: "",
    role: role.role,
    purpose: role.purpose,
  }));
  const nodeByRole = new Map(nodes.map((node) => [node.role, node]));
  const edgeSpecs = [
    ["ai_search_scope_lead", "global_primary_sources", "全球源边界"],
    ["ai_search_scope_lead", "cn_primary_sources", "中国源边界"],
    ["global_primary_sources", "signal_quality_gate", "一手源回链"],
    ["cn_primary_sources", "signal_quality_gate", "一手源回链"],
  ] as const;
  return {
    schemaVersion: 1,
    canvasKind: TEAM_ORGANIZATION_CANVAS_KIND,
    teamId,
    updatedAt: "",
    path: `workspace/teams/${teamId}/canvas.json`,
    viewport: { x: 0, y: 0, zoom: 1 },
    nodes,
    edges: edgeSpecs.flatMap(([sourceRole, targetRole, label]) => {
      const source = nodeByRole.get(sourceRole);
      const target = nodeByRole.get(targetRole);
      return source && target
        ? [{
            id: `${source.id}-${target.id}`,
            source: source.id,
            target: target.id,
            label,
            type: "reports_to",
          }]
        : [];
    }),
    validation: {
      valid: true,
      summary: { errorCount: 0, warningCount: 0, issueCount: 0 },
      issues: [],
    },
  };
}
