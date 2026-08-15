import { describe, expect, it } from "vitest";

import apiSource from "./agents.ts?raw";
import mutationSource from "../routes/chat/useAgentPermissionPresetMutation.ts?raw";

describe("Agent permission preset API", () => {
  it("owns the revision-bound Agent permission transport", () => {
    expect(apiSource).toContain("/api/agents/");
    expect(apiSource).toContain("permissionPreset: payload.permissionPreset");
    expect(apiSource).toContain("expectedConfigRevision: payload.expectedConfigRevision");
    expect(apiSource).toContain("updateAgentPermissionPresetWithRevisionRetry");
    expect(apiSource).toContain("agent_update_conflict");
  });

  it("keeps React Query orchestration free of direct transport calls", () => {
    expect(mutationSource).toContain("updateAgentPermissionPresetWithRevisionRetry");
    expect(mutationSource).not.toContain('from "../../api/client"');
    expect(mutationSource).not.toContain("fetchJson");
    expect(mutationSource).not.toContain("/api/agents/");
  });

  it("owns chat-catalog agent summary, direct-session reset, and tool-governance transports", () => {
    expect(apiSource).toContain("search.set(\"detail\", \"summary\")");
    expect(apiSource).toContain("/reset");
    expect(apiSource).toContain("resetDirectSession: true");
    expect(apiSource).toContain("/tool-governance-requests/");
    expect(apiSource).toContain("resolvedBy: \"user\"");
  });

  it("owns agent catalog list, workspace, avatar-options, create, update, archive, and reset transports", () => {
    expect(apiSource).toContain("export function listAgentSummaries");
    expect(apiSource).toContain("export function fetchAgentConfigWorkspace");
    expect(apiSource).toContain("/api/agents/config-workspace");
    expect(apiSource).toContain("/api/agents/avatar-options");
    expect(apiSource).toContain("export function listAgentAvatarOptions");
    expect(apiSource).toContain("export function createAgent");
    expect(apiSource).toContain('fetchJson<AgentConfigWorkspaceAgent>("/api/agents"');
    expect(apiSource).toContain("export function updateAgent");
    expect(apiSource).toContain("export function archiveAgent");
    expect(apiSource).toContain("export function resetAgent");
    expect(apiSource).toContain("method: \"DELETE\"");
  });
});
