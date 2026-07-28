import type {
  AgentConfigWorkspaceAgent,
  Team,
  TeamCanvasNode,
  TeamOrganizationCanvas,
} from "../../api/types";
import { SOURCE_COLLECTION_TEAM_AGENT_ROLES } from "./teamKindModel";

export function sourceCollectionAgentIdsFromCanvas(canvas: TeamOrganizationCanvas | null) {
  const agentIds: Record<string, string> = {};
  const roleSet = new Set(SOURCE_COLLECTION_TEAM_AGENT_ROLES);
  for (const node of canvas?.nodes ?? []) {
    const role = normalizeAgentRoleKey(node.role);
    if (roleSet.has(role) && node.agentId && !agentIds[role]) {
      agentIds[role] = node.agentId;
    }
  }
  return agentIds;
}

export function sourceCollectionAgentIdsFromTeam(team: Team | null | undefined, canvas: TeamOrganizationCanvas | null) {
  const agentIds = sourceCollectionAgentIdsFromCanvas(canvas);
  const roleSet = new Set(SOURCE_COLLECTION_TEAM_AGENT_ROLES);
  for (const member of team?.members ?? []) {
    const role = normalizeAgentRoleKey(member.role);
    if (roleSet.has(role) && member.agentId && !agentIds[role]) {
      agentIds[role] = member.agentId;
    }
  }
  return agentIds;
}

export function sourceCollectionOwnerAgentIdFromCanvas(canvas: TeamOrganizationCanvas | null) {
  const preferredRoles = ["research_coordination", "data_intake_coordinator", "source_finder", "source_ingestor", "ceo", "organization_coordinator"];
  for (const role of preferredRoles) {
    const node = canvas?.nodes.find((item) => normalizeAgentRoleKey(item.role) === role && item.agentId);
    if (node?.agentId) {
      return node.agentId;
    }
  }
  return "";
}

export function sourceCollectionOwnerAgentIdFromTeam(team: Team | null | undefined, canvas: TeamOrganizationCanvas | null) {
  const canvasOwnerAgentId = sourceCollectionOwnerAgentIdFromCanvas(canvas);
  if (canvasOwnerAgentId) {
    return canvasOwnerAgentId;
  }
  const preferredRoles = ["research_coordination", "data_intake_coordinator", "source_finder", "source_ingestor", "ceo", "organization_coordinator"];
  for (const role of preferredRoles) {
    const member = (team?.members ?? []).find((item) => normalizeAgentRoleKey(item.role) === role && item.agentId);
    if (member?.agentId) {
      return member.agentId;
    }
  }
  return "";
}

export function normalizeAgentRoleKey(value: string | undefined | null) {
  return String(value || "").trim().toLowerCase();
}

export function researchStageAgentManagementRoute(agentId: string) {
  const params = new URLSearchParams({ pane: "config" });
  const normalized = String(agentId || "").trim();
  if (normalized) {
    params.set("agent", normalized);
  }
  return `/agents?${params.toString()}`;
}

export function teamCanvasNodeAgentSourceRoute(node: TeamCanvasNode, fallbackAgentId = "") {
  const projectionRoute = String(node.agentProjectionEdit?.canonicalEditRoute || node.agentSourceRef?.canonicalEditRoute || "").trim();
  if (projectionRoute) {
    return projectionRoute;
  }
  return researchStageAgentManagementRoute(String(node.agentId || fallbackAgentId || "").trim());
}

export function writableTeamCanvasNode(node: TeamCanvasNode): TeamCanvasNode {
  const writableNode = { ...node };
  delete writableNode.agentSourceRef;
  delete writableNode.agentProjectionEdit;
  delete writableNode.agentProjectionCanWrite;
  return writableNode;
}

export function writableTeamCanvas(canvas: TeamOrganizationCanvas): TeamOrganizationCanvas {
  return {
    ...canvas,
    nodes: canvas.nodes.map(writableTeamCanvasNode),
  };
}

export function researchStageAgentDirectChatRoute(
  agent: AgentConfigWorkspaceAgent | null | undefined,
  returnTo?: string,
  returnLabel?: string,
) {
  return researchStageSessionChatRoute(agent?.directSessionId, returnTo, returnLabel);
}

export function researchStageSessionChatRoute(
  sessionIdValue: string | null | undefined,
  returnTo?: string,
  returnLabel?: string,
) {
  const sessionId = String(sessionIdValue || "").trim();
  if (!sessionId) {
    return "";
  }
  const params = new URLSearchParams({ session: sessionId });
  const normalizedReturnTo = String(returnTo || "").trim();
  const normalizedReturnLabel = String(returnLabel || "").trim();
  if (normalizedReturnTo) {
    params.set("returnTo", normalizedReturnTo);
  }
  if (normalizedReturnLabel) {
    params.set("returnLabel", normalizedReturnLabel);
  }
  return `/chat?${params.toString()}`;
}

export function teamChatRoomRoute(roomId: string, returnTo?: string, returnLabel?: string) {
  const normalizedRoomId = String(roomId || "").trim();
  if (!normalizedRoomId) {
    return "";
  }
  const params = new URLSearchParams({ room: normalizedRoomId });
  const normalizedReturnTo = String(returnTo || "").trim();
  const normalizedReturnLabel = String(returnLabel || "").trim();
  if (normalizedReturnTo) {
    params.set("returnTo", normalizedReturnTo);
  }
  if (normalizedReturnLabel) {
    params.set("returnLabel", normalizedReturnLabel);
  }
  return `/chat?${params.toString()}`;
}

export function researchStageAgentModelLabel(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  if (!agent) {
    return lang === "zh" ? "未绑定" : "not bound";
  }
  return agent.dialogueModel?.label
    || agent.llmBindings?.dialogue?.modelId
    || agent.llmBindings?.mentalModel?.modelId
    || (lang === "zh" ? "未配置模型" : "model missing");
}

export function researchStageAgentActionableHealthIssues(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return (agent?.health ?? []).filter((issue) => issue.severity !== "info");
}

export function researchStageAgentConfigStatusLabel(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  if (!agent) {
    return lang === "zh" ? "待绑定" : "missing";
  }
  const actionableIssues = researchStageAgentActionableHealthIssues(agent);
  if (actionableIssues.some((issue) => issue.severity === "blocking")) {
    return lang === "zh" ? "需修复" : "blocked";
  }
  if (actionableIssues.length) {
    return lang === "zh" ? "需检查" : "needs check";
  }
  return lang === "zh" ? "可用" : "ready";
}

export function researchStageAgentConfigTone(agent: AgentConfigWorkspaceAgent | null | undefined) {
  if (!agent) {
    return "missing";
  }
  const actionableIssues = researchStageAgentActionableHealthIssues(agent);
  if (actionableIssues.some((issue) => issue.severity === "blocking")) {
    return "blocked";
  }
  if (actionableIssues.length) {
    return "warning";
  }
  return "ready";
}
