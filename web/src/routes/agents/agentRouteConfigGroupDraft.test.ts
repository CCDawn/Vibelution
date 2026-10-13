import { describe, expect, it } from "vitest";

import { draftFromAgent } from "./agentRouteDraftModel";
import {
  mergeAgentConfigDraftGroup,
  mergeCleanAgentConfigDraftGroups,
  sameAgentConfigDraftGroup,
} from "./agentRouteConfigGroupDraft";

const sourceAgent = {
  agentId: "research",
  displayName: "研究助手",
  status: "active",
  promptTemplateId: "prompt-v1",
  permissionPreset: "request_approval",
  llmBindings: { dialogue: { modelId: "model-v1" } },
  metadata: { llmReasoningEffort: { dialogue: "medium" } },
} as const;

describe("agentRouteConfigGroupDraft", () => {
  it("identifies model and basic dirtiness independently", () => {
    const source = draftFromAgent(sourceAgent as never);
    const changedModels = { ...source, llmBindings: { dialogue: { modelId: "model-v2" } } };
    const changedBasic = { ...source, displayName: "新的研究助手" };

    expect(sameAgentConfigDraftGroup(changedModels, source, "models")).toBe(false);
    expect(sameAgentConfigDraftGroup(changedModels, source, "basic")).toBe(true);
    expect(sameAgentConfigDraftGroup(changedBasic, source, "models")).toBe(true);
    expect(sameAgentConfigDraftGroup(changedBasic, source, "basic")).toBe(false);
  });

  it("merges a saved model group without replacing unsaved basic fields", () => {
    const current = {
      ...draftFromAgent(sourceAgent as never),
      llmBindings: { dialogue: { modelId: "model-v2" } },
      displayName: "未保存名称",
      promptTemplateId: "prompt-v2",
    };
    const saved = {
      ...draftFromAgent(sourceAgent as never),
      llmBindings: { dialogue: { modelId: "model-v2" } },
      reasoningEffortBySlot: { dialogue: "high" },
    };

    const next = mergeAgentConfigDraftGroup(current, saved, "models");
    expect(next.llmBindings).toEqual(saved.llmBindings);
    expect(next.reasoningEffortBySlot).toEqual({ dialogue: "high" });
    expect(next.displayName).toBe("未保存名称");
    expect(next.promptTemplateId).toBe("prompt-v2");
  });

  it("merges a saved basic group without replacing unsaved model fields", () => {
    const current = {
      ...draftFromAgent(sourceAgent as never),
      llmBindings: { dialogue: { modelId: "model-v2" } },
      reasoningEffortBySlot: { dialogue: "high" },
      displayName: "已保存名称",
    };
    const saved = {
      ...draftFromAgent(sourceAgent as never),
      displayName: "已保存名称",
      promptTemplateId: "prompt-v2",
    };

    const next = mergeAgentConfigDraftGroup(current, saved, "basic");
    expect(next.displayName).toBe("已保存名称");
    expect(next.promptTemplateId).toBe("prompt-v2");
    expect(next.llmBindings).toEqual(current.llmBindings);
    expect(next.reasoningEffortBySlot).toEqual(current.reasoningEffortBySlot);
  });

  it("refreshes clean groups while keeping dirty groups through workspace synchronization", () => {
    const previous = draftFromAgent(sourceAgent as never);
    const dirtyBasic = { ...previous, displayName: "未保存名称" };
    const nextSource = {
      ...draftFromAgent({ ...sourceAgent, llmBindings: { dialogue: { modelId: "model-v2" } } } as never),
      status: "paused",
    };

    const afterModelRefresh = mergeCleanAgentConfigDraftGroups(dirtyBasic, previous, nextSource);
    expect(afterModelRefresh.llmBindings).toEqual(nextSource.llmBindings);
    expect(afterModelRefresh.displayName).toBe("未保存名称");

    const dirtyModels = { ...previous, llmBindings: { dialogue: { modelId: "model-v3" } } };
    const afterBasicRefresh = mergeCleanAgentConfigDraftGroups(dirtyModels, previous, nextSource);
    expect(afterBasicRefresh.llmBindings).toEqual(dirtyModels.llmBindings);
    expect(afterBasicRefresh.status).toBe("paused");
  });
});
