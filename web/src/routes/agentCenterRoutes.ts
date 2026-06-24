import { safeReturnToPath } from "../app/navigationReturn";

export type AgentCenterPane = "overview" | "config" | "activity";

export type AgentCenterReturnLabel =
  | "agents"
  | "tools"
  | "teams"
  | "chat"
  | "memory"
  | "research_flow"
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
  view?: string | null;
  returnLabel?: AgentCenterReturnLabel | string | null;
  returnTo?: string | null;
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
  view = "agents",
  returnLabel,
  returnTo,
}: AgentCenterMemoryRouteOptions) {
  const params = new URLSearchParams();
  const normalizedAgentId = String(agentId || "").trim();
  const normalizedView = String(view || "").trim();
  const normalizedReturnLabel = String(returnLabel || "").trim();
  const normalizedReturnTo = safeAgentCenterReturnToPath(returnTo);

  if (normalizedAgentId) {
    params.set("agentId", normalizedAgentId);
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
