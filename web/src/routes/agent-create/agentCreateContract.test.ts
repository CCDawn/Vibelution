import { describe, expect, it } from "vitest";

import {
  createAgentPayload,
  createDraftFromWorkspace,
  createToolBundleSummary,
} from "./agentCreateContract";

describe("agent create contract", () => {
  const bundles = [
    {
      bundleId: "core",
      label: "核心工具",
      description: "",
      toolNames: ["glob_tool", "grep_search_tool"],
      preferredToolNames: ["grep_search_tool"],
      toolCount: 2,
      preferredToolCount: 1,
      highRiskToolCount: 0,
      explicitAllowToolCount: 0,
    },
  ];

  it("keeps the chat default and payload tool policy derived from one selection", () => {
    const draft = createDraftFromWorkspace({
      agentModelChoices: [{
        modelId: "provider/model",
        label: "Model",
        model: "model",
        providerId: "provider",
        providerLabel: "Provider",
        providerKind: "openai",
        runtimeSelectable: true,
      }],
      promptTemplates: [{ promptTemplateId: "prompt-chat-default", name: "Chat", category: "chat" }],
    }, bundles, "zh");
    const summary = createToolBundleSummary(draft.selectedToolBundleIds, bundles, "zh");
    const payload = createAgentPayload(draft, bundles);

    expect(draft.primaryMode).toBe("chat");
    expect(draft.selectedToolBundleIds).toEqual(["core"]);
    expect(summary.allowedTools).toEqual(["glob_tool", "grep_search_tool"]);
    expect(payload.toolPolicy.allowedTools).toEqual(summary.allowedTools);
    expect(payload.toolPolicy.preferredTools).toEqual(["grep_search_tool"]);
    expect(payload.metadata.creationChannel).toBe("agent_center");
  });

  it("never includes a preferred tool that is not allowed", () => {
    const payload = createAgentPayload({
      displayName: "新会话 Agent",
      llmBindings: { dialogue: { modelId: "provider/model" } },
      primaryMode: "chat",
      roleKey: "",
      promptTemplateId: "prompt-chat-default",
      personaSummary: "",
      taskMission: "",
      selectedToolBundleIds: [],
      allowedTools: "agent_message_tool, glob_tool",
    }, []);

    expect(payload.toolPolicy.preferredTools.every((tool) => payload.toolPolicy.allowedTools.includes(tool))).toBe(true);
  });
});
