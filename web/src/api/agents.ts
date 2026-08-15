import { fetchJson } from "./client";
import type {
  AgentAvatarOptionsPayload,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentInstance,
  AgentPermissionPreset,
  AgentToolGovernanceRequest,
} from "./types";

export type AgentDirectSessionResetResponse = {
  agent: AgentInstance;
  resetSummary: {
    resetDirectSession?: boolean;
    previousDirectSessionId?: string;
    replacementDirectSessionId?: string;
  };
};

export function listAgentSummaries<T = AgentInstance>(options?: {
  includeArchived?: boolean;
  signal?: AbortSignal;
}): Promise<T[]> {
  const search = new URLSearchParams();
  search.set("detail", "summary");
  if (options?.includeArchived) {
    search.set("includeArchived", "true");
  }
  return fetchJson<T[]>(`/api/agents?${search.toString()}`, {
    signal: options?.signal,
  });
}

export function fetchAgentConfigWorkspace<T = AgentConfigWorkspace>(options?: {
  includeRuntime?: boolean;
  signal?: AbortSignal;
}): Promise<T> {
  const search = new URLSearchParams();
  if (options?.includeRuntime === false) {
    search.set("includeRuntime", "false");
  }
  const suffix = search.toString();
  return fetchJson<T>(suffix ? `/api/agents/config-workspace?${suffix}` : "/api/agents/config-workspace", {
    signal: options?.signal,
  });
}

export function listAgentAvatarOptions(options?: {
  modelId?: string;
}): Promise<AgentAvatarOptionsPayload> {
  const search = new URLSearchParams();
  if (options?.modelId) {
    search.set("modelId", options.modelId);
  }
  const suffix = search.toString();
  return fetchJson<AgentAvatarOptionsPayload>(
    suffix ? `/api/agents/avatar-options?${suffix}` : "/api/agents/avatar-options",
  );
}

export function createAgent(payload: object): Promise<AgentConfigWorkspaceAgent> {
  return fetchJson<AgentConfigWorkspaceAgent>("/api/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateAgent(
  agentId: string,
  payload: Record<string, unknown>,
): Promise<AgentConfigWorkspaceAgent> {
  return fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(agentId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function archiveAgent(agentId: string): Promise<AgentConfigWorkspaceAgent> {
  return fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(agentId)}`, {
    method: "DELETE",
  });
}

export function resetAgent<T = AgentDirectSessionResetResponse>(
  agentId: string,
  payload: object,
): Promise<T> {
  return fetchJson<T>(`/api/agents/${encodeURIComponent(agentId)}/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function resetAgentDirectSession(
  agentId: string,
  sessionId: string,
): Promise<AgentDirectSessionResetResponse> {
  return resetAgent(agentId, {
    clearRuntimeState: false,
    resetDirectSession: true,
    directSessionId: sessionId,
    resetPersonaProfile: false,
    resetTaskProfile: false,
    resetToolPolicy: false,
    resetMemoryPolicy: false,
    resetRuntimePolicy: false,
  });
}

export function resolveAgentToolGovernanceRequest(
  request: AgentToolGovernanceRequest,
  decision: "approve" | "reject",
): Promise<AgentToolGovernanceRequest> {
  return fetchJson<AgentToolGovernanceRequest>(
    `/api/agents/${encodeURIComponent(request.targetAgentId)}/tool-governance-requests/${encodeURIComponent(request.requestId)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        decision,
        resolvedBy: "user",
        resolutionNote: decision === "approve" ? "会话内批准" : "会话内拒绝",
      }),
    },
  );
}

export type UpdateAgentPermissionPresetPayload = {
  agentId: string;
  permissionPreset: AgentPermissionPreset;
  expectedConfigRevision: number;
};

function isAgentConfigRevisionConflict(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return (
    message.includes("agent_update_conflict")
    || message.includes("configuration revision changed")
    || message.includes("Agent configuration revision changed")
  );
}

export function updateAgentPermissionPreset(
  payload: UpdateAgentPermissionPresetPayload,
) {
  return fetchJson<AgentConfigWorkspaceAgent>(
    `/api/agents/${encodeURIComponent(payload.agentId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        permissionPreset: payload.permissionPreset,
        expectedConfigRevision: payload.expectedConfigRevision,
      }),
    },
  );
}

/**
 * Patch permission preset; on revision conflict refresh the Agent once and retry.
 * Covers chat composer snapshots lagging behind mid-turn acceptAlways grants.
 */
export async function updateAgentPermissionPresetWithRevisionRetry(
  payload: UpdateAgentPermissionPresetPayload,
): Promise<AgentConfigWorkspaceAgent> {
  try {
    return await updateAgentPermissionPreset(payload);
  } catch (error) {
    if (!isAgentConfigRevisionConflict(error)) {
      throw error;
    }
    const latest = await fetchJson<AgentConfigWorkspaceAgent>(
      `/api/agents/${encodeURIComponent(payload.agentId)}`,
    );
    const latestRevision = Number(latest.configRevision);
    if (!Number.isFinite(latestRevision) || latestRevision < 1) {
      throw error;
    }
    if (latestRevision === payload.expectedConfigRevision) {
      throw error;
    }
    return updateAgentPermissionPreset({
      agentId: payload.agentId,
      permissionPreset: payload.permissionPreset,
      expectedConfigRevision: latestRevision,
    });
  }
}
