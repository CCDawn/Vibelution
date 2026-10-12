// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { updateAgent } from "../../api/agents";
import type { AgentConfigWorkspaceAgent } from "../../api/types";
import type { AgentConfigDraft } from "../AgentCoreConfigPanel";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { draftFromAgent, contextCompressionPolicyFromDraft } from "./agentRouteDraftModel";
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
function Consumer() {
  mutations = useAgentConfigDraftMutations({
    lang: "zh", setNotice: vi.fn(), chatWorkspaceCache: createChatWorkspaceCache(client),
    setConfigDraft: vi.fn(), draftSyncSourceRef: { current: null }, getWorkspace: () => undefined,
    draftFromAgent, draftSyncSourceFromAgent: () => null, normalizeAgentLlmBindings,
    contextCompressionPolicyFromDraft, contextCompressionPolicyChangedInDraft: () => false,
    agentMetadataWithReasoningEffort: () => ({}), agentLabel: row => row?.displayName ?? "",
    updatedAgentWorkspaceCache: current => current,
  });
  return null;
}
beforeEach(async () => {
  vi.clearAllMocks(); vi.mocked(updateAgent).mockResolvedValue(agent);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  node = document.createElement("div"); document.body.append(node); root = createRoot(node);
  await act(async () => root.render(<QueryClientProvider client={client}><Consumer /></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });
async function save(changes: Partial<AgentConfigDraft>) {
  await act(async () => mutations.updateAgentMutation.mutateAsync({
    agentId: agent.agentId, agent, draft: { ...draftFromAgent(agent), ...changes }, modelChoices: [], sourceDraftId: "",
  }));
  return vi.mocked(updateAgent).mock.calls[0][1];
}
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
