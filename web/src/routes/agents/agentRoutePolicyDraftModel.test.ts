import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspace, AgentConfigWorkspaceAgent } from "../../api/types";
import {
  defaultMemoryPolicy,
  defaultToolPolicy,
  delegationPolicyDraftFromAgent,
  membershipDraftEqualsWorkspace,
  membershipDraftFromWorkspace,
  memoryPolicyDraftEqualsAgent,
  memoryPolicyDraftFromAgent,
  supervisionPolicyDraftFromAgent,
  toolPolicyDeltaFromDraft,
  toolPolicyDraftEqualsAgent,
  toolPolicyDraftFromAgent,
  toolPolicyMode,
  toolPolicyModeLabel,
} from "./agentRoutePolicyDraftModel";

describe("agentRoutePolicyDraftModel", () => {
  it("maps membership from mode bindings", () => {
    const workspace = {
      modeBindings: {
        chat: { defaultAgentId: "a1", availableAgentIds: ["a1", "a2"] },
        research: { pool: ["a1"] },
        supervised_evolution: { slots: { reviewer: "a1" } },
        self_evolution: { slots: {} },
      },
    } as AgentConfigWorkspace;
    const agent = { agentId: "a1" } as AgentConfigWorkspaceAgent;
    const draft = membershipDraftFromWorkspace(workspace, agent);
    expect(draft.chatDefault).toBe(true);
    expect(draft.chatAvailable).toBe(true);
    expect(draft.researchPool).toBe(true);
    expect(draft.supervisedSlot).toBe("reviewer");
    expect(membershipDraftEqualsWorkspace(draft, workspace, agent)).toBe(true);
  });

  it("normalizes tool policy draft and computes deltas", () => {
    const agent = {
      agentId: "a1",
      toolPolicy: {
        allowedTools: ["read_file"],
        preferredTools: ["read_file"],
        blockedTools: ["shell"],
        readScopes: ["private"],
        writeScopes: ["private"],
      },
    } as AgentConfigWorkspaceAgent;
    const draft = toolPolicyDraftFromAgent(agent);
    expect(toolPolicyMode(draft, "read_file")).toBe("allowed");
    expect(toolPolicyMode(draft, "shell")).toBe("blocked");
    expect(toolPolicyModeLabel("allowed", "zh")).toBe("允许");

    const next = {
      ...draft,
      allowedTools: ["read_file", "write_file"],
      blockedTools: [],
    };
    const delta = toolPolicyDeltaFromDraft(next, agent);
    expect(delta.grantTools).toEqual(["write_file"]);
    expect(delta.unblockTools).toEqual(["shell"]);
    expect(toolPolicyDraftEqualsAgent(draft, agent)).toBe(true);
  });

  it("maps memory and runtime policy drafts", () => {
    const agent = {
      agentId: "a1",
      memoryPolicy: {
        readSharedGroups: ["project"],
        writeSharedGroups: [],
        readKnowledgeBaseIds: ["kb1"],
        proposeKnowledgeBaseIds: [],
        reviewKnowledgeBaseIds: [],
        rateKnowledgeBaseIds: [],
      },
      metadata: {
        delegationPolicy: {
          allowSubagents: true,
          maxConcurrent: 2,
          maxDepth: 1,
          allowWakeMessages: true,
          allowedContextModes: ["isolated", "fork"],
        },
        supervisionPolicy: {
          supervisionEnabled: true,
          requiresReview: true,
          reviewMode: "required",
          evidenceLevel: "strict",
        },
      },
    } as AgentConfigWorkspaceAgent;

    const memory = memoryPolicyDraftFromAgent(agent);
    expect(memory.readSharedGroups).toEqual(["project"]);
    expect(memory.readKnowledgeBaseIds).toEqual(["kb1"]);
    expect(memoryPolicyDraftEqualsAgent(memory, agent)).toBe(true);

    const delegation = delegationPolicyDraftFromAgent(agent);
    expect(delegation.allowSubagents).toBe(true);
    expect(delegation.maxConcurrent).toBe(2);

    const supervision = supervisionPolicyDraftFromAgent(agent);
    expect(supervision.reviewMode).toBe("required");
    expect(supervision.evidenceLevel).toBe("strict");

    expect(defaultToolPolicy("x").policyId).toBe("x");
    expect(defaultMemoryPolicy("m").policyId).toBe("m");
  });
});
