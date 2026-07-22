import { describe, expect, it } from "vitest";

import type { AgentModelChoice } from "../../api/types";
import {
  buildAgentModelChoices,
  buildAgentProviderChoices,
  createAgentPayload,
  createDraftFromWorkspace,
  createDraftReady,
  createToolBundleSummary,
  firstAvailableModelId,
} from "./agentCreateContract";

function modelChoice(partial: Partial<AgentModelChoice> & Pick<AgentModelChoice, "modelId" | "providerId">): AgentModelChoice {
  return {
    modelRef: partial.modelId,
    modelKey: partial.modelId.split("/")[1] || partial.modelId,
    upstreamId: partial.model || partial.modelId,
    label: partial.label || partial.modelId,
    model: partial.model || partial.modelId,
    providerLabel: partial.providerLabel || partial.providerId,
    providerKind: partial.providerKind || "openai",
    providerBaseUrl: partial.providerBaseUrl || "https://example.com/v1",
    transport: partial.transport || "chat_completions",
    source: partial.source || "pinned",
    runtimeSelectable: partial.runtimeSelectable ?? true,
    availability: partial.availability || "pinned",
    verificationStatus: partial.verificationStatus || "unverified",
    catalogStale: partial.catalogStale ?? false,
    slotCompatibility: partial.slotCompatibility || { dialogue: { allowed: true, reasonCode: "" } },
    capabilities: partial.capabilities || {},
    apiKeyEnv: partial.apiKeyEnv || "",
    apiKeyConfigured: partial.apiKeyConfigured ?? true,
    apiKeyState: partial.apiKeyState || "configured",
    requiresApiKey: partial.requiresApiKey ?? true,
    missingApiKey: partial.missingApiKey ?? false,
    capabilityStatus: partial.capabilityStatus || "unknown",
    capabilitySource: partial.capabilitySource || "preset",
    ...partial,
  };
}

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
      agentModelChoices: [modelChoice({
        modelId: "provider/model",
        label: "Model",
        model: "model",
        providerId: "provider",
        providerLabel: "Provider",
        providerKind: "openai",
        runtimeSelectable: true,
        apiKeyConfigured: true,
        missingApiKey: false,
      })],
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

  it("marks missing-key models unavailable and prefers available defaults", () => {
    const choices = buildAgentModelChoices([
      modelChoice({
        modelId: "deepseek_main/deepseek-v4-pro",
        providerId: "deepseek_main",
        providerLabel: "DeepSeek",
        label: "DeepSeek V4 Pro",
        model: "deepseek-v4-pro",
        apiKeyConfigured: false,
        missingApiKey: true,
        requiresApiKey: true,
        apiKeyState: "missing",
      }),
      modelChoice({
        modelId: "xiaomi_mimo_token_plan_cn/mimo-v2.5-pro",
        providerId: "xiaomi_mimo_token_plan_cn",
        providerLabel: "MiMo",
        label: "MiMo V2.5 Pro",
        model: "mimo-v2.5-pro",
        apiKeyConfigured: true,
        missingApiKey: false,
        requiresApiKey: true,
      }),
    ], "zh");
    const providers = buildAgentProviderChoices(choices, "zh");

    expect(choices.find((item) => item.modelId.includes("deepseek"))?.available).toBe(false);
    expect(choices.find((item) => item.modelId.includes("xiaomi"))?.available).toBe(true);
    expect(choices.find((item) => item.modelId.includes("xiaomi"))?.probeUsable).toBe(false);
    expect(choices[0].modelId).toContain("xiaomi");
    expect(firstAvailableModelId(choices)).toContain("xiaomi");
    expect(providers.find((item) => item.id === "deepseek_main")?.label).toContain("不可用");
    expect(providers.find((item) => item.id === "xiaomi_mimo_token_plan_cn")?.label).toContain("已配密钥");
    expect(providers.find((item) => item.id === "deepseek_main")?.available).toBe(false);

    const probed = buildAgentModelChoices([
      modelChoice({
        modelId: "xiaomi_mimo_token_plan_cn/mimo-v2.5-pro",
        providerId: "xiaomi_mimo_token_plan_cn",
        apiKeyConfigured: true,
        missingApiKey: false,
      }),
    ], "zh", {
      "xiaomi_mimo_token_plan_cn/mimo-v2.5-pro": {
        status: "ok",
        message: "ok",
        checkedAt: new Date().toISOString(),
      },
    });
    expect(probed[0]?.probeUsable).toBe(true);
    expect(probed[0]?.label).toContain("探测通过");

    const draft = createDraftFromWorkspace({
      agentModelChoices: [
        modelChoice({
          modelId: "deepseek_main/deepseek-v4-pro",
          providerId: "deepseek_main",
          apiKeyConfigured: false,
          missingApiKey: true,
        }),
        modelChoice({
          modelId: "xiaomi_mimo_token_plan_cn/mimo-v2.5-pro",
          providerId: "xiaomi_mimo_token_plan_cn",
          apiKeyConfigured: true,
          missingApiKey: false,
        }),
      ],
      promptTemplates: [{ promptTemplateId: "prompt-chat-default", name: "Chat", category: "chat" }],
    }, bundles, "zh");
    expect(draft.llmBindings.dialogue?.modelId).toContain("xiaomi");
    expect(createDraftReady(draft, bundles, new Set([draft.llmBindings.dialogue?.modelId || ""]))).toBe(true);
    expect(createDraftReady({
      ...draft,
      llmBindings: { dialogue: { modelId: "deepseek_main/deepseek-v4-pro" } },
    }, bundles, new Set(["xiaomi_mimo_token_plan_cn/mimo-v2.5-pro"]))).toBe(false);
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
