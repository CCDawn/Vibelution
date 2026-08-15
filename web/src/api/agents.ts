import { fetchJson } from "./client";
import type {
  AgentAvatarOptionsPayload,
  AgentAvatarUploadResponse,
  AgentConfigChanges,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentInboxMessage,
  AgentInstance,
  AgentModeBindings,
  AgentPermissionPreset,
  AgentPurgeResponse,
  AgentRunHistory,
  AgentRuntimeEvidence,
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

export function fetchAgentConfigChanges<T = AgentConfigChanges>(
  agentId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/agents/${encodeURIComponent(agentId)}/config-changes`,
    { signal: options?.signal },
  );
}

export function saveAgentConfigDraft(
  agentId: string,
  payload: {
    baseUpdatedAt: string;
    snapshot: Record<string, unknown>;
    summary: string;
  },
): Promise<NonNullable<AgentConfigChanges["activeDraft"]>> {
  return fetchJson<NonNullable<AgentConfigChanges["activeDraft"]>>(
    `/api/agents/${encodeURIComponent(agentId)}/config-drafts`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function discardAgentConfigDraft(
  agentId: string,
  draftId: string,
): Promise<{ draftId: string; status: string }> {
  return fetchJson<{ draftId: string; status: string }>(
    `/api/agents/${encodeURIComponent(agentId)}/config-drafts/${encodeURIComponent(draftId)}`,
    { method: "DELETE" },
  );
}

export function promoteAgentModel<T = { agent: AgentConfigWorkspaceAgent; modelRef: string }>(
  agentId: string,
  slot: string,
  payload: object,
): Promise<T> {
  return fetchJson<T>(
    `/api/agents/${encodeURIComponent(agentId)}/llm-bindings/${encodeURIComponent(slot)}/promote`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function fetchAgentRunHistory(
  agentId: string,
  options?: { limit?: number; signal?: AbortSignal },
): Promise<AgentRunHistory> {
  const search = new URLSearchParams();
  if (options?.limit != null) {
    search.set("limit", String(options.limit));
  }
  const suffix = search.toString();
  const path = `/api/agents/${encodeURIComponent(agentId)}/runs`;
  return fetchJson<AgentRunHistory>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}

export function fetchAgentInboxMessages(
  agentId: string,
  options?: { status?: string; limit?: number; signal?: AbortSignal },
): Promise<AgentInboxMessage[]> {
  const search = new URLSearchParams();
  if (options?.status) {
    search.set("status", options.status);
  }
  if (options?.limit != null) {
    search.set("limit", String(options.limit));
  }
  const suffix = search.toString();
  const path = `/api/agents/${encodeURIComponent(agentId)}/messages`;
  return fetchJson<AgentInboxMessage[]>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}

export function fetchAgentRuntimeEvidence(
  agentId: string,
  options?: { sessionId?: string; runId?: string; limit?: number; signal?: AbortSignal },
): Promise<AgentRuntimeEvidence> {
  const search = new URLSearchParams();
  if (options?.sessionId !== undefined) {
    search.set("sessionId", options.sessionId);
  }
  if (options?.runId) {
    search.set("runId", options.runId);
  }
  if (options?.limit != null) {
    search.set("limit", String(options.limit));
  }
  const suffix = search.toString();
  const path = `/api/agents/${encodeURIComponent(agentId)}/runtime-evidence`;
  return fetchJson<AgentRuntimeEvidence>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}

export function bulkUpdateAgentConfig<T>(payload: {
  agentIds: string[];
  applyFields: string[];
  patch: Record<string, unknown>;
}): Promise<T> {
  return fetchJson<T>("/api/agents/bulk-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function bulkUpdateAgentPromptTemplate<T>(payload: {
  agentIds: string[];
  promptTemplateId: string;
}): Promise<T> {
  return fetchJson<T>("/api/agents/bulk-prompt-template", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function bulkArchiveAgents<T>(agentIds: string[]): Promise<T> {
  return fetchJson<T>("/api/agents/bulk-archive", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agentIds }),
  });
}

export function bulkPurgeAgents<T>(agentIds: string[]): Promise<T> {
  return fetchJson<T>("/api/agents/bulk-purge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agentIds }),
  });
}

export function updateAgentAvatar(
  agentId: string,
  payload: { avatarImagePath?: string; resetToDefault?: boolean },
): Promise<AgentConfigWorkspaceAgent> {
  return fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(agentId)}/avatar`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      avatarImagePath: payload.avatarImagePath ?? "",
      resetToDefault: Boolean(payload.resetToDefault),
    }),
  });
}

export function uploadAgentAvatarImage(
  agentId: string,
  payload: { filename: string; contentType: string; dataBase64: string },
): Promise<AgentAvatarUploadResponse> {
  return fetchJson<AgentAvatarUploadResponse>(`/api/agents/${encodeURIComponent(agentId)}/avatar-image`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateAgentModeMembership<T = AgentModeBindings>(
  agentId: string,
  draft: Record<string, unknown>,
): Promise<T> {
  return fetchJson<T>(`/api/agents/${encodeURIComponent(agentId)}/mode-membership`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  });
}

export function createAgentToolGovernanceRequest(
  agentId: string,
  payload: {
    proposedByAgentId: string;
    grantTools: string[];
    revokeTools: string[];
    blockTools: string[];
    unblockTools: string[];
    reason: string;
    applyMode: string;
  },
): Promise<AgentToolGovernanceRequest> {
  return fetchJson<AgentToolGovernanceRequest>(
    `/api/agents/${encodeURIComponent(agentId)}/tool-governance-requests`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function resolveAgentCenterToolGovernanceRequest(
  agentId: string,
  requestId: string,
  decision: "approve" | "reject",
): Promise<AgentToolGovernanceRequest> {
  return fetchJson<AgentToolGovernanceRequest>(
    `/api/agents/${encodeURIComponent(agentId)}/tool-governance-requests/${encodeURIComponent(requestId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        resolvedBy: "user",
        resolutionNote: decision,
      }),
    },
  );
}

export function consumeAgentInboxMessage(
  agentId: string,
  messageId: string,
  payload: { consumedBySessionId: string; consumedByTurnId: string },
): Promise<AgentInboxMessage> {
  return fetchJson<AgentInboxMessage>(
    `/api/agents/${encodeURIComponent(agentId)}/messages/${encodeURIComponent(messageId)}/consume`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function consumeAllAgentInboxMessages<T>(
  agentId: string,
  payload: { consumedBySessionId: string; consumedByTurnId: string },
): Promise<T> {
  return fetchJson<T>(
    `/api/agents/${encodeURIComponent(agentId)}/messages/consume-all`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function purgeArchivedAgent<T = AgentPurgeResponse>(agentId: string): Promise<T> {
  return fetchJson<T>(`/api/agents/${encodeURIComponent(agentId)}/purge`, {
    method: "DELETE",
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
