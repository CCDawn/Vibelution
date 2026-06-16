export type AgentCenterPane = "overview" | "config" | "activity";

export type AgentCenterReturnLabel =
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

function safeAgentCenterReturnToPath(value: string | null | undefined) {
  const normalized = String(value || "").trim();
  if (!normalized || !normalized.startsWith("/") || normalized.startsWith("//")) {
    return "";
  }
  return normalized;
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
