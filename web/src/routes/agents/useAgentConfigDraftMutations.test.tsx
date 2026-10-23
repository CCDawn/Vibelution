// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { discardAgentConfigDraft, promoteAgentModel, saveAgentConfigDraft, updateAgent } from "../../api/agents";
import type { AgentConfigWorkspaceAgent } from "../../api/types";
import type { AgentConfigDraft } from "../AgentCoreConfigPanel";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import {
  contextCompressionPolicyChangedInDraft,
  contextCompressionPolicyFromDraft,
  draftFromAgent,
} from "./agentRouteDraftModel";
import { normalizeAgentLlmBindings } from "./agentRouteLlmModel";
import { useAgentConfigDraftMutations } from "./useAgentConfigDraftMutations";

vi.mock("../../api/agents", () => ({ updateAgent: vi.fn(), saveAgentConfigDraft: vi.fn(), discardAgentConfigDraft: vi.fn(), promoteAgentModel: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({ startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn() }) }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const agent = {
  agentId: "finance", displayName: "炒股智能体", status: "active",
  toolPolicyId: "tool-finance", memoryPolicyId: "memory-finance",
  toolPolicy: { allowedTools: ["financial_market_snapshot_tool"], maxCallsPerTurn: 8 },
  memoryPolicy: { readKnowledgeBaseIds: ["agent:finance:kb-financial-reports"] },
  llmBindings: { dialogue: { modelId: "old-model" } }, permissionPreset: "request_approval",
  updatedAt: "2026-10-12T06:24:28Z", configRevision: 4,
} as AgentConfigWorkspaceAgent;
let root: Root, node: HTMLDivElement, client: QueryClient;
let mutations: ReturnType<typeof useAgentConfigDraftMutations>;
let setConfigDraft: ReturnType<typeof vi.fn>, setNotice: ReturnType<typeof vi.fn>;
let activeAgentId: string;
function Consumer() {
  mutations = useAgentConfigDraftMutations({
    lang: "zh", setNotice, chatWorkspaceCache: createChatWorkspaceCache(client),
    setConfigDraft, draftSyncSourceRef: { current: null }, getWorkspace: () => undefined,
    getSelectedAgentId: () => activeAgentId,
    draftFromAgent, draftSyncSourceFromAgent: () => null, normalizeAgentLlmBindings,
    contextCompressionPolicyFromDraft, contextCompressionPolicyChangedInDraft,
    agentMetadataWithReasoningEffort: () => ({}), agentLabel: row => row?.displayName ?? "",
    updatedAgentWorkspaceCache: current => current,
  });
  return null;
}
beforeEach(async () => {
  vi.clearAllMocks(); vi.mocked(updateAgent).mockResolvedValue(agent); setConfigDraft = vi.fn(); setNotice = vi.fn(); activeAgentId = agent.agentId;
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  node = document.createElement("div"); document.body.append(node); root = createRoot(node);
  await act(async () => root.render(<QueryClientProvider client={client}><Consumer /></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });

it.each(["save", "discard", "promote"] as const)("%s completes even when the following readback never settles", async kind => {
  vi.spyOn(client, "invalidateQueries").mockReturnValue(new Promise<void>(() => {}));
  vi.mocked(saveAgentConfigDraft).mockResolvedValue({ draftId: "draft" } as Awaited<ReturnType<typeof saveAgentConfigDraft>>);
  vi.mocked(discardAgentConfigDraft).mockResolvedValue({ draftId: "draft", status: "discarded" });
  vi.mocked(promoteAgentModel).mockResolvedValue({ agent, modelRef: "model" });
  let settled = false;
  await act(async () => {
    const pending = kind === "save"
      ? mutations.saveAgentConfigDraftMutation.mutateAsync({ agentId: agent.agentId, baseUpdatedAt: agent.updatedAt, snapshot: {} })
      : kind === "discard"
        ? mutations.discardAgentConfigDraftMutation.mutateAsync({ agentId: agent.agentId, draftId: "draft" })
        : mutations.promoteAgentModelMutation.mutateAsync({ agent, slot: { slot: "dialogue" }, candidate: { modelRef: "model" }, expectedBaseHash: "base" } as Parameters<typeof mutations.promoteAgentModelMutation.mutateAsync>[0]);
    void pending.then(() => { settled = true; });
    await Promise.resolve();
  });
  expect(settled).toBe(true);
});

it("a late model promotion does not overwrite the newly selected Agent's draft", async () => {
  let finish!: (value: { agent: AgentConfigWorkspaceAgent; modelRef: string }) => void;
  vi.mocked(promoteAgentModel).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  let pending!: Promise<unknown>;
  await act(async () => {
    pending = mutations.promoteAgentModelMutation.mutateAsync({ agent, slot: { slot: "dialogue" }, candidate: { modelRef: "model" }, expectedBaseHash: "base" } as Parameters<typeof mutations.promoteAgentModelMutation.mutateAsync>[0]);
  });
  activeAgentId = "other";
  await act(async () => { finish({ agent, modelRef: "model" }); await pending; });
  expect(setConfigDraft).not.toHaveBeenCalled();
});
async function save(changes: Partial<AgentConfigDraft>, group?: "models" | "basic") {
  await act(async () => mutations.updateAgentMutation.mutateAsync({
    agentId: agent.agentId, agent, draft: { ...draftFromAgent(agent), ...changes }, modelChoices: [], sourceDraftId: "", group,
  }));
  return vi.mocked(updateAgent).mock.calls[0][1];
}

it("model-group save submits only bindings and reasoning metadata with revision guards", async () => {
  const patch = await save({
    llmBindings: { dialogue: { modelId: "new-model" } },
    reasoningEffortBySlot: { dialogue: "high" },
  }, "models");

  expect(patch).toMatchObject({
    llmBindings: { dialogue: { modelId: "new-model" } },
    metadata: {},
    expectedUpdatedAt: agent.updatedAt,
    expectedConfigRevision: 4,
  });
  expect(patch).not.toHaveProperty("displayName");
  expect(patch).not.toHaveProperty("status");
  expect(patch).not.toHaveProperty("promptTemplateId");
  expect(patch).not.toHaveProperty("permissionPreset");
  expect(patch).not.toHaveProperty("toolPolicyId");
  expect(patch).not.toHaveProperty("memoryPolicyId");
  expect(patch).not.toHaveProperty("contextCompressionPolicy");
});

it("basic-group save submits basic fields without model fields", async () => {
  const patch = await save({
    displayName: "基本配置已更改",
    promptTemplateId: "prompt-next",
    status: "paused",
    permissionPreset: "allow_safe_tools",
  }, "basic");

  expect(patch).toMatchObject({
    displayName: "基本配置已更改",
    promptTemplateId: "prompt-next",
    status: "paused",
    permissionPreset: "allow_safe_tools",
    expectedUpdatedAt: agent.updatedAt,
    expectedConfigRevision: 4,
  });
  expect(patch).not.toHaveProperty("llmBindings");
  expect(patch).not.toHaveProperty("metadata");
  expect(patch).not.toHaveProperty("contextCompressionPolicy");
});

it("basic-group save sends only explicitly changed tool, memory, and compression settings", async () => {
  const baseline = draftFromAgent(agent);
  const patch = await save({
    toolPolicyId: "tool-selected",
    memoryPolicyId: "memory-selected",
    contextCompressionPolicy: { ...baseline.contextCompressionPolicy, maxTokenLimit: "16000" },
  }, "basic");

  expect(patch).toMatchObject({
    toolPolicyId: "tool-selected",
    memoryPolicyId: "memory-selected",
    contextCompressionPolicy: { mode: "custom", maxTokenLimit: 16000 },
  });
  expect(patch).not.toHaveProperty("llmBindings");
  expect(patch).not.toHaveProperty("metadata");
});

it("a model-save response keeps unsaved basic draft fields", async () => {
  const savedAgent = {
    ...agent,
    llmBindings: { dialogue: { modelId: "saved-model" } },
    metadata: { llmReasoningEffort: { dialogue: "high" } },
  } as AgentConfigWorkspaceAgent;
  vi.mocked(updateAgent).mockResolvedValue(savedAgent);
  const submittedDraft = {
    ...draftFromAgent(agent),
    llmBindings: { dialogue: { modelId: "saved-model" } },
    displayName: "未保存的名称",
  };

  await act(async () => mutations.updateAgentMutation.mutateAsync({
    agentId: agent.agentId, agent, draft: submittedDraft, modelChoices: [], sourceDraftId: "", group: "models",
  }));

  const updater = setConfigDraft.mock.calls.at(-1)?.[0] as (current: AgentConfigDraft) => AgentConfigDraft;
  const current = { ...submittedDraft, promptTemplateId: "unsaved-prompt" };
  const next = updater(current);
  expect(next.llmBindings).toEqual(savedAgent.llmBindings);
  expect(next.reasoningEffortBySlot).toEqual({ dialogue: "high" });
  expect(next.displayName).toBe("未保存的名称");
  expect(next.promptTemplateId).toBe("unsaved-prompt");
});

it("a basic-save response keeps unsaved model draft fields", async () => {
  const savedAgent = {
    ...agent,
    displayName: "已保存名称",
    promptTemplateId: "prompt-next",
  } as AgentConfigWorkspaceAgent;
  vi.mocked(updateAgent).mockResolvedValue(savedAgent);
  const submittedDraft = {
    ...draftFromAgent(agent),
    displayName: "已保存名称",
    promptTemplateId: "prompt-next",
    llmBindings: { dialogue: { modelId: "unsaved-model" } },
    reasoningEffortBySlot: { dialogue: "high" },
  };

  await act(async () => mutations.updateAgentMutation.mutateAsync({
    agentId: agent.agentId, agent, draft: submittedDraft, modelChoices: [], sourceDraftId: "", group: "basic",
  }));

  const updater = setConfigDraft.mock.calls.at(-1)?.[0] as (current: AgentConfigDraft) => AgentConfigDraft;
  const current = { ...submittedDraft, llmBindings: { dialogue: { modelId: "edited-while-saving" } } };
  const next = updater(current);
  expect(next.displayName).toBe("已保存名称");
  expect(next.promptTemplateId).toBe("prompt-next");
  expect(next.llmBindings).toEqual(current.llmBindings);
  expect(next.reasoningEffortBySlot).toEqual(current.reasoningEffortBySlot);
});

it("a save response keeps a newer edit made to the same group", async () => {
  const savedAgent = {
    ...agent,
    llmBindings: { dialogue: { modelId: "submitted-model" } },
  } as AgentConfigWorkspaceAgent;
  vi.mocked(updateAgent).mockResolvedValue(savedAgent);
  const submittedDraft = {
    ...draftFromAgent(agent),
    llmBindings: { dialogue: { modelId: "submitted-model" } },
  };

  await act(async () => mutations.updateAgentMutation.mutateAsync({
    agentId: agent.agentId, agent, draft: submittedDraft, modelChoices: [], sourceDraftId: "", group: "models",
  }));

  const updater = setConfigDraft.mock.calls.at(-1)?.[0] as (current: AgentConfigDraft) => AgentConfigDraft;
  const current = { ...submittedDraft, llmBindings: { dialogue: { modelId: "edited-while-saving" } } };
  expect(updater(current)).toBe(current);
});

it("a late response after switching Agents does not touch the newly selected draft", async () => {
  const savedAgent = {
    ...agent,
    llmBindings: { dialogue: { modelId: "saved-model" } },
  } as AgentConfigWorkspaceAgent;
  let resolveSave: ((value: AgentConfigWorkspaceAgent) => void) | undefined;
  vi.mocked(updateAgent).mockReturnValue(new Promise((resolve) => { resolveSave = resolve; }));
  const submittedDraft = {
    ...draftFromAgent(agent),
    llmBindings: { dialogue: { modelId: "saved-model" } },
  };

  await act(async () => {
    const pending = mutations.updateAgentMutation.mutateAsync({
      agentId: agent.agentId, agent, draft: submittedDraft, modelChoices: [], sourceDraftId: "", group: "models",
    });
    await vi.waitFor(() => expect(updateAgent).toHaveBeenCalled());
    activeAgentId = "another-agent";
    resolveSave?.(savedAgent);
    await pending;
  });

  const updater = setConfigDraft.mock.calls.at(-1)?.[0] as (current: AgentConfigDraft) => AgentConfigDraft;
  const otherAgentDraft = { ...draftFromAgent(agent), displayName: "另一个 Agent 的草稿" };
  expect(updater(otherAgentDraft)).toBe(otherAgentDraft);
  expect(setNotice).not.toHaveBeenCalled();
});

it("a late failure after switching Agents does not show a notice on the newly selected Agent", async () => {
  let rejectSave: ((reason?: unknown) => void) | undefined;
  vi.mocked(updateAgent).mockReturnValue(new Promise((_, reject) => { rejectSave = reject; }));

  await act(async () => {
    const pending = mutations.updateAgentMutation.mutateAsync({
      agentId: agent.agentId,
      agent,
      draft: { ...draftFromAgent(agent), llmBindings: { dialogue: { modelId: "unsaved-model" } } },
      modelChoices: [],
      sourceDraftId: "",
      group: "models",
    });
    await vi.waitFor(() => expect(updateAgent).toHaveBeenCalled());
    activeAgentId = "another-agent";
    rejectSave?.(new Error("save failed"));
    await expect(pending).rejects.toThrow("save failed");
  });

  expect(setNotice).not.toHaveBeenCalled();
});

it("a failed grouped save leaves the local draft untouched", async () => {
  vi.mocked(updateAgent).mockRejectedValue(new Error("network down"));
  await act(async () => {
    await expect(mutations.updateAgentMutation.mutateAsync({
      agentId: agent.agentId,
      agent,
      draft: { ...draftFromAgent(agent), llmBindings: { dialogue: { modelId: "unsaved-model" } } },
      modelChoices: [],
      sourceDraftId: "",
      group: "models",
    })).rejects.toThrow("network down");
  });
  expect(setConfigDraft).not.toHaveBeenCalled();
});
it("changing the model preserves inline tool and financial-library policies", async () => {
  const patch = await save({ llmBindings: { dialogue: { modelId: "qwen-flash" } } });
  expect(patch.llmBindings).toEqual({ dialogue: { modelId: "qwen-flash" } });
  expect(patch).not.toHaveProperty("toolPolicyId");
  expect(patch).not.toHaveProperty("memoryPolicyId");
  expect(patch).toMatchObject({ expectedUpdatedAt: agent.updatedAt, expectedConfigRevision: 4 });
});
it("changing the name does not rebind unchanged policy templates", async () => {
  const patch = await save({ displayName: "验收助手" });
  expect(patch.displayName).toBe("验收助手");
  expect(patch).not.toHaveProperty("toolPolicyId");
  expect(patch).not.toHaveProperty("memoryPolicyId");
});
it("an explicit tool-policy selection still rebinds that policy", async () => {
  const patch = await save({ toolPolicyId: "tool-selected" });
  expect(patch.toolPolicyId).toBe("tool-selected");
  expect(patch).not.toHaveProperty("memoryPolicyId");
});
it("an explicit memory-policy selection still rebinds that policy", async () => {
  const patch = await save({ memoryPolicyId: "memory-selected" });
  expect(patch.memoryPolicyId).toBe("memory-selected");
  expect(patch).not.toHaveProperty("toolPolicyId");
});
