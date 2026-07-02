import { safeReturnToPath } from "../app/navigationReturn";

export type AgentCenterPane = "overview" | "config" | "activity";

export type AgentCenterReturnLabel =
  | "agents"
  | "tools"
  | "teams"
  | "chat"
  | "memory"
  | "research_flow"
  | "self_evolution"
  | "supervised_evolution";

type AgentCenterConfigRouteOptions = {
  agentId?: string | null;
  pane?: AgentCenterPane;
  returnLabel?: AgentCenterReturnLabel | string | null;
  returnTo?: string | null;
};

type AgentCenterToolsRouteOptions = {
  agentId?: string | null;
  returnLabel?: AgentCenterReturnLabel | string | null;
  returnTo?: string | null;
};

type AgentCenterPromptsRouteOptions = {
  agentId?: string | null;
  templateId?: string | null;
  focus?: string | null;
  returnLabel?: AgentCenterReturnLabel | string | null;
  returnTo?: string | null;
};

type AgentCenterModelsRouteOptions = {
  agentId?: string | null;
  section?: string | null;
  returnLabel?: AgentCenterReturnLabel | string | null;
  returnTo?: string | null;
};

type AgentCenterMemoryRouteOptions = {
  agentId?: string | null;
  teamId?: string | null;
  knowledgeBaseId?: string | null;
  nodeId?: string | null;
  view?: string | null;
  returnLabel?: AgentCenterReturnLabel | string | null;
  returnTo?: string | null;
};

type TeamMemoryRouteOptions = AgentCenterMemoryRouteOptions & {
  teamId: string;
};

export function safeAgentCenterReturnToPath(value: string | null | undefined) {
  return safeReturnToPath(value);
}

export function agentCenterConfigRoute({
  agentId,
  pane = "config",
  returnLabel,
  returnTo,
}: AgentCenterConfigRouteOptions) {
  const params = new URLSearchParams({ pane });
  const normalizedAgentId = String(agentId || "").trim();
  const normalizedReturnLabel = String(returnLabel || "").trim();
  const normalizedReturnTo = safeAgentCenterReturnToPath(returnTo);

  if (normalizedAgentId) {
    params.set("agent", normalizedAgentId);
  }
  if (normalizedReturnTo) {
    params.set("returnTo", normalizedReturnTo);
  }
  if (normalizedReturnLabel) {
    params.set("returnLabel", normalizedReturnLabel);
  }

  return `/agents?${params.toString()}`;
}

export function agentCenterToolsRoute({
  agentId,
  returnLabel,
  returnTo,
}: AgentCenterToolsRouteOptions) {
  const params = new URLSearchParams();
  const normalizedAgentId = String(agentId || "").trim();
  const normalizedReturnLabel = String(returnLabel || "").trim();
  const normalizedReturnTo = safeAgentCenterReturnToPath(returnTo);

  if (normalizedAgentId) {
    params.set("agent", normalizedAgentId);
  }
  if (normalizedReturnTo) {
    params.set("returnTo", normalizedReturnTo);
  }
  if (normalizedReturnLabel) {
    params.set("returnLabel", normalizedReturnLabel);
  }

  const query = params.toString();
  return query ? `/agents/tools?${query}` : "/agents/tools";
}

export function agentCenterPromptsRoute({
  agentId,
  templateId,
  focus,
  returnLabel,
  returnTo,
}: AgentCenterPromptsRouteOptions) {
  const params = new URLSearchParams();
  const normalizedAgentId = String(agentId || "").trim();
  const normalizedTemplateId = String(templateId || "").trim();
  const normalizedFocus = String(focus || "").trim();
  const normalizedReturnLabel = String(returnLabel || "").trim();
  const normalizedReturnTo = safeAgentCenterReturnToPath(returnTo);

  if (normalizedAgentId) {
    params.set("agent", normalizedAgentId);
  }
  if (normalizedTemplateId) {
    params.set("template", normalizedTemplateId);
  }
  if (normalizedFocus) {
    params.set("focus", normalizedFocus);
  }
  if (normalizedReturnTo) {
    params.set("returnTo", normalizedReturnTo);
  }
  if (normalizedReturnLabel) {
    params.set("returnLabel", normalizedReturnLabel);
  }

  const query = params.toString();
  return query ? `/agents/prompts?${query}` : "/agents/prompts";
}

export function agentCenterModelsRoute({
  agentId,
  section = "models-profiles",
  returnLabel,
  returnTo,
}: AgentCenterModelsRouteOptions) {
  const params = new URLSearchParams();
  const normalizedAgentId = String(agentId || "").trim();
  const normalizedSection = String(section || "").trim();
  const normalizedReturnLabel = String(returnLabel || "").trim();
  const normalizedReturnTo = safeAgentCenterReturnToPath(returnTo);

  if (normalizedAgentId) {
    params.set("agent", normalizedAgentId);
  }
  if (normalizedSection) {
    params.set("section", normalizedSection);
  }
  if (normalizedReturnTo) {
    params.set("returnTo", normalizedReturnTo);
  }
  if (normalizedReturnLabel) {
    params.set("returnLabel", normalizedReturnLabel);
  }

  const query = params.toString();
  return query ? `/config?${query}` : "/config";
}

export function agentCenterMemoryRoute({
  agentId,
  teamId,
  knowledgeBaseId,
  nodeId,
  view = "agents",
  returnLabel,
  returnTo,
}: AgentCenterMemoryRouteOptions) {
  const params = new URLSearchParams();
  const normalizedAgentId = String(agentId || "").trim();
  const normalizedTeamId = String(teamId || "").trim();
  const normalizedKnowledgeBaseId = String(knowledgeBaseId || "").trim();
  const normalizedNodeId = String(nodeId || "").trim();
  const normalizedView = String(view || "").trim();
  const normalizedReturnLabel = String(returnLabel || "").trim();
  const normalizedReturnTo = safeAgentCenterReturnToPath(returnTo);

  if (normalizedAgentId) {
    params.set("agentId", normalizedAgentId);
  }
  if (normalizedTeamId) {
    params.set("teamId", normalizedTeamId);
  }
  if (normalizedKnowledgeBaseId) {
    params.set("knowledgeBaseId", normalizedKnowledgeBaseId);
  }
  if (normalizedNodeId) {
    params.set("nodeId", normalizedNodeId);
  }
  if (normalizedView) {
    params.set("view", normalizedView);
  }
  if (normalizedReturnTo) {
    params.set("returnTo", normalizedReturnTo);
  }
  if (normalizedReturnLabel) {
    params.set("returnLabel", normalizedReturnLabel);
  }

  const query = params.toString();
  return query ? `/memory/agents?${query}` : "/memory/agents";
}

export function teamMemoryRoute({
  teamId,
  agentId,
  knowledgeBaseId,
  nodeId,
  view = "knowledge",
  returnLabel,
  returnTo,
}: TeamMemoryRouteOptions) {
  const normalizedView = String(view || "knowledge").trim();
  const path = normalizedView ? `/memory/${encodeURIComponent(normalizedView)}` : "/memory";
  const params = new URLSearchParams();
  const normalizedTeamId = String(teamId || "").trim();
  const normalizedAgentId = String(agentId || "").trim();
  const normalizedKnowledgeBaseId = String(knowledgeBaseId || "").trim();
  const normalizedNodeId = String(nodeId || "").trim();
  const normalizedReturnLabel = String(returnLabel || "").trim();
  const normalizedReturnTo = safeAgentCenterReturnToPath(returnTo);

  if (normalizedTeamId) {
    params.set("teamId", normalizedTeamId);
  }
  if (normalizedAgentId) {
    params.set("agentId", normalizedAgentId);
  }
  if (normalizedKnowledgeBaseId) {
    params.set("knowledgeBaseId", normalizedKnowledgeBaseId);
  }
  if (normalizedNodeId) {
    params.set("nodeId", normalizedNodeId);
  }
  if (normalizedView) {
    params.set("view", normalizedView);
  }
  if (normalizedReturnTo) {
    params.set("returnTo", normalizedReturnTo);
  }
  if (normalizedReturnLabel) {
    params.set("returnLabel", normalizedReturnLabel);
  }

  const query = params.toString();
  return query ? `${path}?${query}` : path;
}
