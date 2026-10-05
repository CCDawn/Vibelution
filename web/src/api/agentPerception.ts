import { fetchJson } from "./client";
import type {
  AgentPerceptionCancelResult,
  AgentPerceptionConfiguration,
  AgentPerceptionPolicy,
  AgentPerceptionRuntime,
} from "./types/agentPerception";

export function fetchAgentPerceptionConfiguration(
  agentId: string,
  options?: { signal?: AbortSignal },
): Promise<AgentPerceptionConfiguration> {
  return fetchJson<AgentPerceptionConfiguration>(
    "/api/agents/" + encodeURIComponent(agentId) + "/perception/configuration",
    { signal: options?.signal },
  );
}

export function saveAgentPerceptionConfiguration(
  agentId: string,
  policy: AgentPerceptionPolicy,
  expectedAgentUpdatedAt: string,
): Promise<AgentPerceptionConfiguration> {
  return fetchJson<AgentPerceptionConfiguration>(
    "/api/agents/" + encodeURIComponent(agentId) + "/perception/configuration",
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ policy, expectedAgentUpdatedAt }),
    },
  );
}

export function fetchAgentPerceptionRuntime(
  agentId: string,
  options?: { signal?: AbortSignal },
): Promise<AgentPerceptionRuntime> {
  return fetchJson<AgentPerceptionRuntime>(
    "/api/agents/" + encodeURIComponent(agentId) + "/perception/runtime",
    { signal: options?.signal },
  );
}

export function cancelAgentPerceptionRun(
  agentId: string,
  runId?: string,
): Promise<AgentPerceptionCancelResult> {
  return fetchJson<AgentPerceptionCancelResult>(
    "/api/agents/" + encodeURIComponent(agentId) + "/perception/cancel",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(runId ? { runId } : {}),
    },
  );
}