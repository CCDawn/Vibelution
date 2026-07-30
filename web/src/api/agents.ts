import { fetchJson } from "./client";
import type { AgentConfigWorkspaceAgent, AgentPermissionPreset } from "./types";

export type UpdateAgentPermissionPresetPayload = {
  agentId: string;
  permissionPreset: AgentPermissionPreset;
  expectedConfigRevision: number;
};

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
