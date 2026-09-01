import type {
  AgentInstance,
  SessionSummary,
  VirtualHumanCompanion,
  VirtualHumanCompanionActivity,
} from "../../api/types";

function isCompanionAgent(agent: AgentInstance) {
  return agent.metadata?.virtualHumanCompanion === true;
}

export function companionRouteBindingIsVerified(
  companions: readonly Pick<VirtualHumanCompanion, "agentId" | "directSessionId">[] | undefined,
  agentId: string,
  sessionId: string,
) {
  const normalizedAgentId = String(agentId || "").trim();
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedAgentId || !normalizedSessionId) {
    return false;
  }
  return (companions ?? []).some((companion) => (
    String(companion.agentId || "").trim() === normalizedAgentId
    && String(companion.directSessionId || "").trim() === normalizedSessionId
  ));
}

export function companionAgentIdForDirectSession(
  companions: readonly Pick<VirtualHumanCompanionActivity, "agentId" | "directSessionId">[] | undefined,
  sessionId: string,
) {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return "";
  }
  return String((companions ?? []).find((companion) => (
    String(companion.directSessionId || "").trim() === normalizedSessionId
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
