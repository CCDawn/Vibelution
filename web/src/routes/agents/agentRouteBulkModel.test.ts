import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent } from "../../api/types";
import {
  agentArchiveProtected,
  agentBulkActionSummary,
  agentCenterReturnLabel,
  bulkConfigDraftFromAgents,
  bulkConfigPatchFromDraft,
  bulkConfigReady,
  DEFAULT_BULK_CONFIG_APPLY,
  DEFAULT_BULK_CONFIG_DRAFT,
  optimisticArchivedAgent,
  safeAgentCenterReturnTo,
} from "./agentRouteBulkModel";

describe("agentRouteBulkModel", () => {
  it("builds bulk draft/patch and readiness", () => {
    const agents = [
      { agentId: "a1", promptTemplateId: "p1", primaryMode: "chat", roleKey: "r1", llmBindings: { dialogue: { modelId: "m1" } } },
      { agentId: "a2", promptTemplateId: "p1", primaryMode: "chat", roleKey: "r2", llmBindings: { dialogue: { modelId: "m1" } } },
    ] as AgentConfigWorkspaceAgent[];
    const draft = bulkConfigDraftFromAgents(agents);
    expect(draft.promptTemplateId).toBe("p1");
    expect(draft.roleKey).toBe("");
    expect(draft.dialogueModelId).toBe("m1");

    const apply = { ...DEFAULT_BULK_CONFIG_APPLY, promptTemplateId: true, dialogueModelId: true };
    const readyDraft = { ...DEFAULT_BULK_CONFIG_DRAFT, promptTemplateId: "p2", dialogueModelId: "m2" };
    expect(bulkConfigReady(readyDraft, apply)).toBe(true);
    expect(bulkConfigPatchFromDraft(readyDraft, apply)).toEqual({
      llmBindings: { dialogue: { modelId: "m2" } },
      promptTemplateId: "p2",
    });
  });

  it("protects system/research roles and builds archive optimistic agent", () => {
    const protectedAgent = {
      agentId: "ceo",
      metadata: { researchOrgRole: "ceo" },
    } as AgentConfigWorkspaceAgent;
    expect(agentArchiveProtected(protectedAgent)).toBe(true);
    expect(agentArchiveProtected({ agentId: "x", metadata: {} } as AgentConfigWorkspaceAgent)).toBe(false);

    const archived = optimisticArchivedAgent({
      agentId: "a1",
      status: "active",
      directSessionId: "s1",
      runtimeStatus: { state: "idle", label: "Idle", reason: "", runId: "", runKind: "", sessionId: "", summary: "", updatedAt: "" },
    } as AgentConfigWorkspaceAgent);
    expect(archived.status).toBe("archived");
    expect(archived.runtimeStatus?.state).toBe("archived");
  });

  it("formats bulk summary and center return labels", () => {
    expect(agentBulkActionSummary("archive", 2, 1, 0, ["ok"], "zh")).toContain("成功 2");
    expect(agentCenterReturnLabel("teams", "zh")).toBe("返回团队");
    expect(safeAgentCenterReturnTo("/teams?x=1")).toContain("/teams");
  });
});
