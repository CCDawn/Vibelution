import type { AgentInstance, SessionSummary } from "../../api/types";

function isCompanionAgent(agent: AgentInstance) {
  return agent.metadata?.virtualHumanCompanion === true;
}

export function companionAgentIdForDirectSession(
  agents: readonly AgentInstance[] | undefined,
  sessionId: string,
) {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return "";
  }
  return String((agents ?? []).find((agent) => (
    isCompanionAgent(agent)
    && String(agent.directSessionId || "").trim() === normalizedSessionId
  ))?.agentId || "").trim();
}

export function sessionsForChatRoute(options: {
  sessions: readonly SessionSummary[] | undefined;
  agents: readonly AgentInstance[] | undefined;
  companionRouteVerified: boolean;
}): SessionSummary[] | undefined {
  if (!options.sessions) {
    return undefined;
  }
  if (options.companionRouteVerified) {
    return [...options.sessions];
  }
  if (!options.agents) {
    return undefined;
  }
  const companionSessionIds = new Set(
    options.agents
      .filter(isCompanionAgent)
      .map((agent) => String(agent.directSessionId || "").trim())
      .filter(Boolean),
  );
  if (!companionSessionIds.size) {
    return [...options.sessions];
  }
  return options.sessions.filter((session) => !companionSessionIds.has(String(session.id || "").trim()));
}
