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

  it("owns config-changes, config-draft, and model-promotion transports", () => {
    expect(apiSource).toContain("export function fetchAgentConfigChanges");
    expect(apiSource).toContain("/config-changes");
    expect(apiSource).toContain("export function saveAgentConfigDraft");
    expect(apiSource).toContain("/config-drafts");
    expect(apiSource).toContain("export function discardAgentConfigDraft");
    expect(apiSource).toContain("export function promoteAgentModel");
    expect(apiSource).toContain("/llm-bindings/");
    expect(apiSource).toContain("/promote");
  });

  it("owns agent activity run, inbox, and runtime-evidence transports", () => {
    expect(apiSource).toContain("export function fetchAgentRunHistory");
    expect(apiSource).toContain("/runs");
    expect(apiSource).toContain("export function fetchAgentInboxMessages");
    expect(apiSource).toContain("/messages");
    expect(apiSource).toContain("export function fetchAgentRuntimeEvidence");
    expect(apiSource).toContain("/runtime-evidence");
  });

  it("owns agent bulk archive, purge, config, and prompt-template transports", () => {
    expect(apiSource).toContain("export function bulkUpdateAgentConfig");
    expect(apiSource).toContain("/api/agents/bulk-config");
    expect(apiSource).toContain("export function bulkUpdateAgentPromptTemplate");
    expect(apiSource).toContain("/api/agents/bulk-prompt-template");
    expect(apiSource).toContain("export function bulkArchiveAgents");
    expect(apiSource).toContain("/api/agents/bulk-archive");
    expect(apiSource).toContain("export function bulkPurgeAgents");
    expect(apiSource).toContain("/api/agents/bulk-purge");
  });

  it("owns Agent Center workbench write transports", () => {
    expect(apiSource).toContain("export function updateAgentAvatar");
    expect(apiSource).toContain("/avatar");
    expect(apiSource).toContain("export function uploadAgentAvatarImage");
    expect(apiSource).toContain("/avatar-image");
    expect(apiSource).toContain("export function updateAgentModeMembership");
    expect(apiSource).toContain("/mode-membership");
    expect(apiSource).toContain("export function createAgentToolGovernanceRequest");
    expect(apiSource).toContain("export function resolveAgentCenterToolGovernanceRequest");
    expect(apiSource).toContain("resolutionNote: decision");
    expect(apiSource).toContain("export function consumeAgentInboxMessage");
    expect(apiSource).toContain("/consume");
    expect(apiSource).toContain("export function consumeAllAgentInboxMessages");
    expect(apiSource).toContain("/messages/consume-all");
    expect(apiSource).toContain("export function purgeArchivedAgent");
    expect(apiSource).toContain("/purge");
  });

  it("owns prompt-template, tool-policy, and project-memory transports", () => {
    expect(apiSource).toContain("export function listPromptTemplates");
    expect(apiSource).toContain("/api/prompt-templates");
    expect(apiSource).toContain("export function fetchPromptTemplate");
    expect(apiSource).toContain("export function updatePromptTemplate");
    expect(apiSource).toContain("export function resetPromptTemplate");
    expect(apiSource).toContain("/reset");
    expect(apiSource).toContain("export function validateAgentToolPolicy");
    expect(apiSource).toContain("/tool-policy/validate");
    expect(apiSource).toContain("export function updateAgentToolPolicy");
    expect(apiSource).toContain("export function listAgentProjectMemoryUpdates");
    expect(apiSource).toContain("/api/agents/project-memory-updates");
    expect(apiSource).toContain("export function resolveAgentProjectMemoryUpdate");
  });
});
