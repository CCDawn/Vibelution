import { fetchJson } from "./client";
import type {
  AgentPluginBinding,
  AgentPluginBindingUpdate,
  AgentPluginCatalogEntry,
  AgentPluginList,
  VirtualHumanCompanion,
} from "./types";

export function listAgentPluginCatalog(options?: { signal?: AbortSignal }): Promise<AgentPluginCatalogEntry[]> {
  return fetchJson<AgentPluginCatalogEntry[]>("/api/agent-plugins/catalog", {
    signal: options?.signal,
  });
}

export function listAgentPlugins(
  agentId: string,
  options?: { signal?: AbortSignal },
): Promise<AgentPluginList> {
  return fetchJson<AgentPluginList>(`/api/agents/${encodeURIComponent(agentId)}/plugins`, {
    signal: options?.signal,
  });
}

export function updateAgentPluginBinding(
  agentId: string,
  pluginId: string,
  payload: AgentPluginBindingUpdate,
  options?: { signal?: AbortSignal },
): Promise<AgentPluginBinding> {
  return fetchJson<AgentPluginBinding>(
    `/api/agents/${encodeURIComponent(agentId)}/plugins/${encodeURIComponent(pluginId)}/binding`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: options?.signal,
    },
  );
}

export function listVirtualHumanCompanions(options?: { signal?: AbortSignal }): Promise<VirtualHumanCompanion[]> {
  return fetchJson<VirtualHumanCompanion[]>(
    "/api/agent-plugins/virtual-human-life/companions",
    { signal: options?.signal },
  );
}
