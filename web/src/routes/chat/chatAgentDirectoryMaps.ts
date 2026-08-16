import type { AgentInstance } from "../../api/types";

export function buildAgentsById(agents: readonly AgentInstance[] | undefined): Map<string, AgentInstance> {
  return new Map((agents ?? []).map((agent) => [agent.agentId, agent]));
}

export function buildAgentsByCode(agents: readonly AgentInstance[] | undefined): Map<string, AgentInstance> {
  const map = new Map<string, AgentInstance>();
  for (const agent of agents ?? []) {
    const code = String(agent.agentCode ?? "").trim();
    if (code) {
      map.set(code, agent);
    }
  }
  return map;
}

export function buildArchiveVisibleAgents(
  agents: readonly AgentInstance[] | undefined,
  pendingArchiveAgentIds: ReadonlySet<string>,
): AgentInstance[] {
  return (agents ?? []).filter((agent) => !pendingArchiveAgentIds.has(agent.agentId));
}
