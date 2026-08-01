import { fetchJson } from "./client";
import type { AgentConfigWorkspaceAgent, AgentPermissionPreset } from "./types";

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
