import { describe, expect, it } from "vitest";

import {
  CONFIG_COPY,
} from "./ConfigRoute";
import {
  applyModelOptionToProfileDraft,
  avatarCropSourceRect,
  clampAvatarCropOffset,
  collectModelDetailKeys,
  configInvalidationDomainsForApply,
  defaultModelApiKeyEnv,
  deriveConfigEditorSyncState,
  deriveModelCenterInventoryRows,
  deriveModelCenterSummary,
  groupConfigProfileCards,
  groupModelPresets,
  hasPendingSecretChanges,
  listSupervisedAgentInstances,
  modelLibraryIdFromParts,
  PROVIDER_KIND_OPTIONS,
  presetCategory,
  resolveImageInputCapabilityStatus,
  resolveProfileDisplayState,
  resolveConfigSectionUiStateOnSelect,
  resolveResearchAgentInstance,
  resolveModelEditability,
  selectModelScenarioPresetId,
  shouldBlockConfigLeave,
  supervisedAgentRole,
  supervisedAgentRoleLabel,
  type PublicConfigShape,
} from "./configRouteLogic";
import type { AgentInstance, ConfigModelOption, ConfigModelPresetOption, ConfigProfileCard } from "../api/types";

function preset(
  presetId: string,
  provider: Record<string, unknown>,
  category?: string,
): ConfigModelPresetOption {
  return {
    preset_id: presetId,
    label: presetId,
    category,
    provider_id: `${presetId}_provider`,
    model_id: presetId,
    provider,
    model: { model: presetId },
  };
}

function option(overrides: Partial<ConfigModelOption> = {}): ConfigModelOption {
  return {
    model_id: "relay_openai_gpt_5_5",
    source: "model_library",
    provider: {
      kind: "relay",
      base_url: "https://pixel.try-chatapi.com/v1",
      compat_mode: "openai",
      requires_api_key: true,
    },
    provider_kind: "relay",
    model: "gpt-5.5",
    label: "GPT-5.5 via relay",
    details: {
      transport: "chat_completions",
      contract: "tool_chat",
      streaming: true,
      timeout: 120,
    },
    api_key_env: "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
    api_key_configured: false,
    api_key_state: "missing",
    ...overrides,
  };
}

describe("configRouteLogic", () => {
  it("scopes config apply invalidation domains to changed config areas", () => {
    expect(configInvalidationDomainsForApply({ ui: { language: "zh" } })).toEqual([
      "config",
      "runtime",
      "sessions",
      "reset",
    ]);
    expect(configInvalidationDomainsForApply({ evolution: { intake_mode: "reviewed" } })).toEqual([
      "config",
      "runtime",
      "sessions",
      "reset",
      "evolution",
    ]);
  });

  it("classifies model presets from explicit category before provider heuristics", () => {
    expect(presetCategory(preset("relay", { kind: "openai" }, "relay"))).toBe("relay");
    expect(presetCategory(preset("local", { kind: "openai", base_url: "http://127.0.0.1:11434/v1" }))).toBe("local");
    expect(presetCategory(preset("official", { kind: "openai", base_url: "https://api.openai.com/v1" }))).toBe("official");
  });

  it("groups presets in stable official relay local order and drops empty groups", () => {
    const groups = groupModelPresets(
      [
        preset("local_model", { kind: "local", base_url: "http://localhost:11434/v1" }),
        preset("compatible_model", { kind: "openai_compatible", base_url: "https://relay.example.com/v1" }),
        preset("relay_model", { kind: "relay", base_url: "https://pixel.try-chatapi.com/v1" }),
      ],
      {
        official: "Official",
        relay: "Relay",
        openai_compatible: "OpenAI Compatible",
        local: "Local",
      },
    );

    expect(groups.map((group) => group.id)).toEqual(["relay", "openai_compatible", "local"]);
    expect(groups.map((group) => group.label)).toEqual(["Relay", "OpenAI Compatible", "Local"]);
    expect(groups[0].presets.map((item) => item.preset_id)).toEqual(["relay_model"]);
    expect(groups[1].presets.map((item) => item.preset_id)).toEqual(["compatible_model"]);
    expect(groups[2].presets.map((item) => item.preset_id)).toEqual(["local_model"]);
  });

  it("groups LLM configs by mode before rendering the settings table", () => {
    const profiles = [
      { profileId: "research_broad", label: "科研广搜" },
      { profileId: "primary", label: "主智能体" },
      { profileId: "supervised_candidate", label: "监督候选" },
      { profileId: "subagent_worker", label: "子代理 Worker" },
      { profileId: "compression", label: "压缩配置" },
      { profileId: "custom_writer", label: "自定义" },
    ].map((item) => ({
      ...item,
      modelRef: "",
      selectedModelId: "",
      selectedModelLabel: "",
      model: "",
      providerKind: "",
      baseUrl: "",
      apiKeyEnv: "",
      apiKeyConfigured: false,
      apiKeyState: "missing",
      apiKeySource: "",
      requiredModelMissing: false,
    })) satisfies ConfigProfileCard[];

    const groups = groupConfigProfileCards(profiles, {
      chat: "对话模式",
      support: "心智与压缩",
      subagents: "子代理模式",
      evolution: "进化模式",
      research: "科研模型配置",
      other: "其他模型配置",
    });

    expect(groups.map((group) => group.id)).toEqual(["chat", "support", "subagents", "evolution", "research", "other"]);
    expect(groups.map((group) => group.profiles.map((profile) => profile.profileId))).toEqual([
      ["primary"],
      ["compression"],
      ["subagent_worker"],
      ["supervised_candidate"],
      ["research_broad"],
      ["custom_writer"],
    ]);
  });

  it("resolves research agents to persistent AgentInstances by id or metadata key", () => {
    const instances: AgentInstance[] = [
      {
        agentId: "agent-paper",
        agentCode: "A001",
        displayName: "Paper Reader",
        kind: "persistent",
        primaryMode: "research",
        roleKey: "research_paper_reader",
        templateId: "research_broad",
        profileId: "research_broad",
        promptTemplateId: "prompt-research-paper-reader",
        directSessionId: "session-paper",
        workspacePath: "workspace/agents/agent-paper",
        toolPolicyId: "default",
        memoryPolicyId: "memory-agent-paper",
        createdBy: "research_agent_pool",
        status: "active",
        metadata: { researchAgentKey: "paper_reader" },
        createdAt: "",
        updatedAt: "",
      },
    ];

    expect(resolveResearchAgentInstance({ key: "other", agentId: "agent-paper" }, instances)?.directSessionId).toBe(
      "session-paper",
    );
    expect(resolveResearchAgentInstance({ key: "paper_reader", roleKey: "research_paper_reader" }, instances)?.agentId).toBe("agent-paper");
    expect(resolveResearchAgentInstance({ key: "paper_reader" }, instances)?.agentId).toBe("agent-paper");
    expect(resolveResearchAgentInstance({ key: "missing" }, instances)).toBeNull();
  });

  it("lists supervised evolution AgentInstances by fixed role order", () => {
    const makeAgent = (agentId: string, role: string, label = ""): AgentInstance => ({
      agentId,
      agentCode: `A-${agentId}`,
      displayName: label || agentId,
      kind: "persistent",
      primaryMode: role ? "supervised_evolution" : "general",
      roleKey: role,
      templateId: "primary",
      profileId: "primary",
      promptTemplateId: role ? `prompt-supervised-${role}` : "",
      directSessionId: `session-${agentId}`,
      workspacePath: `workspace/agents/${agentId}`,
      toolPolicyId: "default",
      memoryPolicyId: `memory-${agentId}`,
      createdBy: "supervised_evolution",
      status: "active",
      metadata: role ? { supervisedRole: role, supervisedRoleLabel: label } : {},
      createdAt: "",
      updatedAt: "",
    });
    const instances = [
      makeAgent("agent-judge", "judge", "裁决"),
      makeAgent("agent-research", ""),
      makeAgent("agent-baseline", "baseline", "基线"),
      makeAgent("agent-candidate", "candidate", "候选"),
    ];

    const supervised = listSupervisedAgentInstances(instances);

    expect(supervised.map((agent) => supervisedAgentRole(agent))).toEqual(["baseline", "candidate", "judge"]);
    expect(supervisedAgentRoleLabel(supervised[0])).toBe("基线");
  });

  it("applies a model option to a profile draft and removes stale model binding fields", () => {
    const publicConfig: PublicConfigShape = {
      llm: {
        profiles: {
          primary: {
            model_ref: "old_model",
            provider_id: "legacy_provider",
            provider: { kind: "deepseek", base_url: "https://api.deepseek.com" },
            model: "deepseek-v4-pro",
            api_key_env: "OLD_KEY",
            overrides: { temperature: 0.2 },
            transport: "old_transport",
            contract: "old_contract",
            timeout: 5,
          },
        },
      },
    };
    const selected = option();
    const detailKeys = collectModelDetailKeys([selected]);

    applyModelOptionToProfileDraft(publicConfig, "primary", selected, detailKeys);

    const profile = (publicConfig.llm as Record<string, unknown>).profiles as Record<string, Record<string, unknown>>;
    expect(profile.primary.model_ref).toBe("relay_openai_gpt_5_5");
    expect(profile.primary.provider_id).toBeUndefined();
    expect(profile.primary.overrides).toEqual({});
    expect(profile.primary.provider).toBeUndefined();
    expect(profile.primary.model).toBeUndefined();
    expect(profile.primary.api_key_env).toBeUndefined();
    expect(profile.primary.transport).toBeUndefined();
    expect(profile.primary.contract).toBeUndefined();
    expect(profile.primary.timeout).toBeUndefined();
  });

  it("derives the backend default model api key env for custom relay presets", () => {
    expect(defaultModelApiKeyEnv("custom_openai_compatible_relay")).toBe(
      "VIBELUTION_LLM_CUSTOM_OPENAI_COMPATIBLE_RELAY_API_KEY",
    );
    expect(defaultModelApiKeyEnv("custom-relay.gpt")).toBe("VIBELUTION_LLM_CUSTOM_RELAY_GPT_API_KEY");
  });

  it("derives readable internal model ids and exposes provider kind choices", () => {
    expect(modelLibraryIdFromParts("pixel-open", "gpt-5.5")).toBe("pixel_open_gpt_5_5");
    expect(modelLibraryIdFromParts("", "gpt-5.5")).toBe("gpt_5_5");
    expect(PROVIDER_KIND_OPTIONS.map((item) => item.value)).toContain("openai_compatible");
    expect(PROVIDER_KIND_OPTIONS.map((item) => item.value)).toContain("relay");
    expect(PROVIDER_KIND_OPTIONS.map((item) => item.value)).toContain("xiaomi");
    expect(PROVIDER_KIND_OPTIONS[0].value).toBe("relay");
  });

  it("removes profile api_key_env when the selected model has none", () => {
    const publicConfig: PublicConfigShape = {
      llm: {
        profiles: {
          primary: {
            api_key_env: "OLD_KEY",
          },
        },
      },
    };
    const selected = option({ api_key_env: "" });

    applyModelOptionToProfileDraft(publicConfig, "primary", selected, collectModelDetailKeys([selected]));

    const profile = (publicConfig.llm as Record<string, unknown>).profiles as Record<string, Record<string, unknown>>;
    expect(profile.primary.model_ref).toBe("relay_openai_gpt_5_5");
    expect(profile.primary.api_key_env).toBeUndefined();
  });

  it("shows the newly selected model details while a profile edit is staged", () => {
    const profile: ConfigProfileCard = {
      profileId: "primary",
      label: "聊天模型",
      modelRef: "old_model",
      selectedModelId: "old_model",
      selectedModelLabel: "Old label",
      model: "old-model",
      providerKind: "openai",
      baseUrl: "https://api.openai.com/v1",
      apiKeyEnv: "OLD_KEY",
      apiKeyConfigured: true,
      apiKeyState: "configured",
      apiKeySource: "OLD_KEY",
      requiredModelMissing: false,
    };
    const selected = option({
      model_id: "relay_openai_gpt_5_5",
      provider_kind: "relay",
      model: "gpt-5.5",
      label: "GPT-5.5 via relay",
      api_key_env: "NEW_KEY",
      api_key_state: "missing",
      provider: {
        kind: "relay",
        base_url: "https://pixel.try-chatapi.com/v1",
        compat_mode: "openai",
        requires_api_key: true,
      },
    });

    const view = resolveProfileDisplayState(profile, "relay_openai_gpt_5_5", selected, true);

    expect(view.selectionDirty).toBe(true);
    expect(view.selectedModelId).toBe("relay_openai_gpt_5_5");
    expect(view.selectedModelLabel).toBe("GPT-5.5 via relay");
    expect(view.providerKind).toBe("relay");
    expect(view.model).toBe("gpt-5.5");
    expect(view.baseUrl).toBe("https://pixel.try-chatapi.com/v1");
    expect(view.apiKeyEnv).toBe("NEW_KEY");
    expect(view.apiKeyState).toBe("missing");
    expect(view.apiKeySource).toBe("NEW_KEY");
  });

  it("preserves a manually collapsed config section when it is selected again", () => {
    const collapsedState = {
      expanded: false,
      editing: false,
      expandedPaths: { "runtime.ui": true },
    };
    const defaultState = {
      expanded: true,
      editing: false,
      expandedPaths: {},
    };

    expect(resolveConfigSectionUiStateOnSelect(collapsedState, defaultState)).toBe(collapsedState);
    expect(resolveConfigSectionUiStateOnSelect(undefined, defaultState)).toBe(defaultState);
  });

  it("only allows editing and deleting real model-library entries", () => {
    expect(resolveModelEditability(option({ source: "model_library" }))).toEqual({
      editable: true,
      deletable: true,
    });
    expect(resolveModelEditability(option({ source: "profile" }))).toEqual({
      editable: false,
      deletable: false,
    });
  });

  it("derives model center accounts and usage from profiles and image2 tool binding", () => {
    const imageModel = option({
      model_id: "relay_image2",
      label: "Relay image2",
      model: "image2",
      api_key_state: "configured",
      api_key_configured: true,
      api_key_env: "VIBELUTION_LLM_RELAY_IMAGE2_API_KEY",
      provider: {
        kind: "relay",
        base_url: "https://ai-pixel.online",
        compat_mode: "openai",
        requires_api_key: true,
      },
    });
    const chatModel = option({
      model_id: "relay_openai_gpt_5_5",
      label: "GPT-5.5 via relay",
      model: "gpt-5.5",
      api_key_state: "missing",
      api_key_configured: false,
      provider: {
        kind: "relay",
        base_url: "https://ai-pixel.online",
        compat_mode: "openai",
        requires_api_key: true,
      },
    });
    const profiles: ConfigProfileCard[] = [
      {
        profileId: "primary",
        label: "主聊天",
        modelRef: "relay_openai_gpt_5_5",
        selectedModelId: "relay_openai_gpt_5_5",
        selectedModelLabel: "GPT-5.5 via relay",
        model: "gpt-5.5",
        providerKind: "relay",
        baseUrl: "https://ai-pixel.online",
        apiKeyEnv: "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
        apiKeyConfigured: false,
        apiKeyState: "missing",
        apiKeySource: "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
        requiredModelMissing: false,
      },
    ];

    const summary = deriveModelCenterSummary({
      modelOptions: [imageModel, chatModel],
      profiles,
      publicConfig: { tools: { image2: { default_model_ref: "relay_image2" } } },
      labels: {
        chat: "对话模式",
        support: "心智与压缩",
        subagents: "子代理模式",
        evolution: "进化模式",
        research: "科研模型配置",
        other: "其他",
        image2Tool: "image2 生图工具",
        gitCommitModel: "Git 提交模型",
      },
    });

    expect(summary.accounts).toHaveLength(2);
    expect(summary.accounts.map((account) => account.apiKeyState).sort()).toEqual(["configured", "missing"]);
    expect(summary.usageCountsByModelId.relay_openai_gpt_5_5).toBe(1);
    expect(summary.usageCountsByModelId.relay_image2).toBe(1);
    expect(summary.usagesByModelId.relay_image2[0]).toMatchObject({
      kind: "tool",
      label: "image2 生图工具",
      detail: "image2_generate_tool",
    });
    expect(summary.unresolvedUsageCount).toBe(0);
  });

  it("builds compact model inventory rows with usage and editability in one place", () => {
    const libraryModel = option({
      model_id: "relay_openai_gpt_5_5",
      source: "model_library",
      api_key_state: "configured",
      api_key_configured: true,
    });
    const generatedModel = option({
      model_id: "profile_inline_primary",
      source: "profile",
      label: "Inline primary model",
      model: "inline-gpt",
      api_key_env: "",
      api_key_state: "missing",
      provider: {
        kind: "openai_compatible",
        base_url: "https://relay.example.com",
      },
    });
    const profiles: ConfigProfileCard[] = [
      {
        profileId: "primary",
        label: "主聊天",
        modelRef: "relay_openai_gpt_5_5",
        selectedModelId: "relay_openai_gpt_5_5",
        selectedModelLabel: "GPT-5.5 via relay",
        model: "gpt-5.5",
        providerKind: "relay",
        baseUrl: "https://pixel.try-chatapi.com/v1",
        apiKeyEnv: "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
        apiKeyConfigured: true,
        apiKeyState: "configured",
        apiKeySource: "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
        requiredModelMissing: false,
      },
      {
        profileId: "research_writer",
        label: "科研写作",
        modelRef: "profile_inline_primary",
        selectedModelId: "profile_inline_primary",
        selectedModelLabel: "Inline primary model",
        model: "inline-gpt",
        providerKind: "openai_compatible",
        baseUrl: "https://relay.example.com",
        apiKeyEnv: "",
        apiKeyConfigured: false,
        apiKeyState: "missing",
        apiKeySource: "",
        requiredModelMissing: false,
      },
    ];
    const summary = deriveModelCenterSummary({
      modelOptions: [libraryModel, generatedModel],
      profiles,
      publicConfig: { tools: { image2: { default_model_ref: "relay_openai_gpt_5_5" } } },
      labels: {
        chat: "对话模式",
        support: "心智与压缩",
        subagents: "子代理模式",
        evolution: "进化模式",
        research: "科研模型配置",
        other: "其他",
        image2Tool: "image2 生图工具",
        gitCommitModel: "Git 提交模型",
      },
    });

    const rows = deriveModelCenterInventoryRows([libraryModel, generatedModel], summary);

    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      modelId: "relay_openai_gpt_5_5",
      usageCount: 2,
      editable: true,
      deletable: true,
      apiKeyState: "configured",
    });
    expect(rows[0].usages.map((usage) => usage.label)).toEqual(["主聊天", "image2 生图工具"]);
    expect(rows[1]).toMatchObject({
      modelId: "profile_inline_primary",
      source: "profile",
      usageCount: 1,
      editable: false,
      deletable: false,
      apiKeyEnv: "",
    });
    expect(rows[1].usages[0]).toMatchObject({
      groupLabel: "科研模型配置",
      label: "科研写作",
    });
  });

  it("tracks git commit message model usage through its selected call profile", () => {
    const chatModel = option({
      model_id: "relay_openai_gpt_5_5",
      label: "GPT-5.5 via relay",
      model: "gpt-5.5",
    });
    const profiles: ConfigProfileCard[] = [
      {
        profileId: "primary",
        label: "主聊天",
        modelRef: "relay_openai_gpt_5_5",
        selectedModelId: "relay_openai_gpt_5_5",
        selectedModelLabel: "GPT-5.5 via relay",
        model: "gpt-5.5",
        providerKind: "relay",
        baseUrl: "https://pixel.try-chatapi.com/v1",
        apiKeyEnv: "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
        apiKeyConfigured: true,
        apiKeyState: "configured",
        apiKeySource: "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
        requiredModelMissing: false,
      },
    ];

    const summary = deriveModelCenterSummary({
      modelOptions: [chatModel],
      profiles,
      publicConfig: { git: { commit_message_profile: "primary" } },
      labels: {
        chat: "对话 / 主智能体",
        support: "心智与压缩",
        subagents: "Agent 管理",
        evolution: "监督进化",
        research: "科研 / Team",
        other: "其他调用档案",
        image2Tool: "image2 生图工具",
        gitCommitModel: "Git 提交模型",
      },
    });

    expect(summary.usageCountsByModelId.relay_openai_gpt_5_5).toBe(2);
    expect(summary.usagesByModelId.relay_openai_gpt_5_5.map((usage) => usage.label)).toEqual([
      "主聊天",
      "Git 提交模型",
    ]);
    expect(summary.usagesByModelId.relay_openai_gpt_5_5[1]).toMatchObject({
      kind: "feature",
      detail: "primary",
      groupLabel: "Git 提交模型",
    });
  });

  it("keeps image input support conservative when status and boolean disagree", () => {
    expect(
      resolveImageInputCapabilityStatus({
        supportsImageInput: null,
        capabilityStatus: "supported",
      }),
    ).toBe("unknown");
    expect(
      resolveImageInputCapabilityStatus({
        supportsImageInput: true,
        capabilityStatus: "supported",
      }),
    ).toBe("supported");
    expect(
      resolveImageInputCapabilityStatus({
        supportsImageInput: false,
        capabilityStatus: "supported",
      }),
    ).toBe("unsupported");
    expect(
      resolveImageInputCapabilityStatus({
        supportsImageInput: null,
        capabilityStatus: "unsupported",
      }),
    ).toBe("unsupported");
  });

  it("does not mark DeepSeek-like inventory rows as image-capable without boolean support", () => {
    const rows = deriveModelCenterInventoryRows(
      [
        option({
          model_id: "deepseek_v4_pro",
          provider_kind: "deepseek",
          model: "deepseek-v4-pro",
          label: "DeepSeek V4 Pro",
          supports_image_input: null,
          capability_status: "supported",
        }),
        option({
          model_id: "xiaomi_mimo_v2_5_multimodal",
          provider_kind: "xiaomi",
          model: "mimo-v2.5",
          label: "小米 MiMo V2.5 多模态",
          supports_image_input: true,
          capability_status: "supported",
        }),
      ],
      {
        usagesByModelId: {},
        usageCountsByModelId: {},
      },
    );

    expect(rows[0]).toMatchObject({
      modelId: "deepseek_v4_pro",
      supportsImageInput: null,
      capabilityStatus: "supported",
      imageInputStatus: "unknown",
    });
    expect(rows[1]).toMatchObject({
      modelId: "xiaomi_mimo_v2_5_multimodal",
      supportsImageInput: true,
      capabilityStatus: "supported",
      imageInputStatus: "supported",
    });
  });

  it("reports usage bindings that point to missing models", () => {
    const summary = deriveModelCenterSummary({
      modelOptions: [option()],
      profiles: [],
      publicConfig: { tools: { image2: { default_model_ref: "missing_image_model" } } },
      labels: {
        chat: "chat",
        support: "support",
        subagents: "subagents",
        evolution: "evolution",
        research: "research",
        other: "other",
        image2Tool: "image2",
        gitCommitModel: "Git commit model",
      },
    });

    expect(summary.usages).toHaveLength(1);
    expect(summary.unresolvedUsageCount).toBe(1);
    expect(summary.usagesByModelId.missing_image_model).toBeUndefined();
  });

  it("maps model creation scenarios to extensible preset defaults", () => {
    const presets = [
      preset("openai_gpt_5_5", { kind: "openai" }, "official"),
      preset("relay_openai_gpt_5_5", { kind: "relay", base_url: "https://ai-pixel.online" }, "relay"),
      preset("relay_image2", { kind: "relay", base_url: "https://ai-pixel.online" }, "relay"),
      preset("local_llama", { kind: "local", base_url: "http://localhost:11434/v1" }, "local"),
    ];

    expect(selectModelScenarioPresetId("chat", presets)).toBe("relay_openai_gpt_5_5");
    expect(selectModelScenarioPresetId("relay", presets)).toBe("relay_openai_gpt_5_5");
    expect(selectModelScenarioPresetId("image", presets)).toBe("relay_image2");
    expect(selectModelScenarioPresetId("local", presets)).toBe("local_llama");
    expect(selectModelScenarioPresetId("manual", presets)).toBe("");
  });

  it("treats pending secret writes and clears as unsaved user changes", () => {
    expect(hasPendingSecretChanges({ pending_api_keys: {}, pending_cleared_api_keys: [] })).toBe(false);
    expect(
      hasPendingSecretChanges({
        pending_api_keys: { VIBELUTION_LLM_TEST_API_KEY: "pending-secret:token" },
        pending_cleared_api_keys: [],
      }),
    ).toBe(true);
    expect(
      hasPendingSecretChanges({
        pending_api_keys: {},
        pending_cleared_api_keys: ["VIBELUTION_LLM_TEST_API_KEY"],
      }),
    ).toBe(true);
  });

  it("locks structured edits while advanced config text has unchecked changes and exposes recovery actions", () => {
    const dirtyState = deriveConfigEditorSyncState({
      editorText: "{\n  \"ui\": {}\n}",
      formattedConfigText: "{\n  \"ui\": {\"language\":\"zh\"}\n}",
      configLoaded: true,
      hasUnsavedConfigChanges: false,
      hasPendingSecretChanges: false,
      busy: false,
    });

    expect(dirtyState.hasEditorChanges).toBe(true);
    expect(dirtyState.hasPendingApply).toBe(true);
    expect(dirtyState.structuredActionsDisabled).toBe(true);
    expect(dirtyState.canSaveConfig).toBe(false);
    expect(dirtyState.canCheckCurrentChanges).toBe(true);
    expect(dirtyState.canRestoreEditorText).toBe(true);

    const cleanState = deriveConfigEditorSyncState({
      editorText: "{\n  \"ui\": {}\n}",
      formattedConfigText: "{\n  \"ui\": {}\n}",
      configLoaded: true,
      hasUnsavedConfigChanges: false,
      hasPendingSecretChanges: true,
      busy: false,
    });

    expect(cleanState.hasEditorChanges).toBe(false);
    expect(cleanState.hasPendingApply).toBe(true);
    expect(cleanState.structuredActionsDisabled).toBe(false);
    expect(cleanState.canSaveConfig).toBe(true);
    expect(cleanState.canRestoreEditorText).toBe(false);
  });

  it("blocks leaving config only when persisted changes are unsaved", () => {
    expect(
      shouldBlockConfigLeave({
        hasPendingApply: true,
        busy: false,
        currentPathname: "/config",
        nextPathname: "/chat",
      }),
    ).toBe(true);

    expect(
      shouldBlockConfigLeave({
        hasPendingApply: false,
        busy: false,
        currentPathname: "/config",
        nextPathname: "/chat",
      }),
    ).toBe(false);
    expect(
      shouldBlockConfigLeave({
        hasPendingApply: true,
        busy: true,
        currentPathname: "/config",
        nextPathname: "/chat",
      }),
    ).toBe(false);
    expect(
      shouldBlockConfigLeave({
        hasPendingApply: true,
        busy: false,
        currentPathname: "/config",
        nextPathname: "/config",
      }),
    ).toBe(false);
  });

  it("keeps avatar crop movement inside the visible square", () => {
    const offset = clampAvatarCropOffset({
      imageWidth: 1200,
      imageHeight: 800,
      frameSize: 320,
      zoom: 1,
      offsetX: 999,
      offsetY: -999,
    });

    expect(offset.offsetX).toBe(80);
    expect(offset.offsetY).toBe(0);
  });

  it("derives the avatar crop source rect from zoom and offset", () => {
    const rect = avatarCropSourceRect({
      imageWidth: 1200,
      imageHeight: 800,
      frameSize: 320,
      zoom: 2,
      offsetX: 80,
      offsetY: 0,
    });

    expect(rect.size).toBe(400);
    expect(rect.sx).toBe(300);
    expect(rect.sy).toBe(200);
  });
});

describe("config route copy", () => {
  it("uses call-profile language instead of exposing model-dossier jargon", () => {
    const zhCopy = JSON.stringify(CONFIG_COPY.zh);
    const enCopy = Object.entries(CONFIG_COPY.en)
      .filter(([key]) => !["runtimeProfile"].includes(key))
      .map(([, value]) => value)
      .join("\n");

    expect(CONFIG_COPY.zh.profilesTitle).toBe("调用档案");
    expect(CONFIG_COPY.en.profilesTitle).toBe("Call Profiles");
    expect(CONFIG_COPY.zh.profileTableActions).toBe("连接");
    expect(CONFIG_COPY.en.profileTableActions).toBe("Connection");
    expect(CONFIG_COPY.zh.editProfiles).toBe("编辑调用档案");
    expect(CONFIG_COPY.en.editProfiles).toBe("Edit call profiles");
    expect(CONFIG_COPY.zh.openEnvironment).toBe("打开系统环境变量");
    expect(CONFIG_COPY.en.openEnvironment).toBe("Open system environment variables");
    expect(zhCopy).not.toContain("配置档");
    expect(zhCopy).not.toContain("模型档案");
    expect(enCopy).not.toMatch(/\bdossiers?\b/i);
    expect(enCopy).not.toMatch(/\bmodel profiles?\b/i);
  });

  it("keeps internal draft and JSON editor jargon out of visible copy", () => {
    const visibleCopy = {
      zh: Object.values(CONFIG_COPY.zh).join("\n"),
      en: Object.values(CONFIG_COPY.en).join("\n"),
    };

    expect(CONFIG_COPY.zh.draftTitle).toBe("高级配置检查");
    expect(CONFIG_COPY.en.draftTitle).toBe("Advanced Config Check");
    expect(CONFIG_COPY.zh.validateDraft).toBe("检查当前修改");
    expect(CONFIG_COPY.en.validateDraft).toBe("Check changes");
    expect(visibleCopy.zh).not.toContain("草稿");
    expect(visibleCopy.zh).not.toContain("JSON");
    expect(visibleCopy.en).not.toMatch(/\bdrafts?\b/i);
    expect(visibleCopy.en).not.toMatch(/\bJSON\b/i);
    expect(visibleCopy.en).not.toMatch(/\bJSON editor\b/i);
  });

  it("splits model assets, call profiles, and git tooling into separate areas", () => {
    expect(CONFIG_COPY.zh.groupModelingTitle).toBe("模型中心");
    expect(CONFIG_COPY.en.groupModelingTitle).toBe("Model Center");
    expect(CONFIG_COPY.zh.groupProfileBindingsTitle).toBe("调用档案");
    expect(CONFIG_COPY.en.groupProfileBindingsTitle).toBe("Call Profiles");
    expect(CONFIG_COPY.zh.groupPromptTitle).toBe("系统提示词");
    expect(CONFIG_COPY.en.groupPromptTitle).toBe("System Prompts");

    const visibleCopy = `${Object.values(CONFIG_COPY.zh).join("\n")}\n${Object.values(CONFIG_COPY.en).join("\n")}`;
    expect(visibleCopy).toContain("Git 提交模型");
    expect(visibleCopy).toContain("Git commit model");
  });

  it("exposes the settings model library as a task-oriented model center", () => {
    expect(CONFIG_COPY.zh.modelsTitle).toBe("模型中心");
    expect(CONFIG_COPY.en.modelsTitle).toBe("Model Center");
    expect(CONFIG_COPY.zh.modelCenterAccounts).toBe("服务商账号");
    expect(CONFIG_COPY.zh.modelCenterUsage).toBe("使用位置");
    expect(CONFIG_COPY.zh.modelCenterSource).toBe("来源");
    expect(CONFIG_COPY.zh.modelScenarioImage).toBe("图片工具模型");
    expect(CONFIG_COPY.en.modelCenterSource).toBe("Source");
    expect(CONFIG_COPY.en.modelScenarioImage).toBe("Image tool model");
  });

  it("keeps research agent settings aligned to user-facing agent concepts", () => {
    expect(CONFIG_COPY.zh.researchAgentPrompt).toBe("提示词模板");
    expect(CONFIG_COPY.zh.researchAgentTemplate).toBe("Agent 类型");
    expect(CONFIG_COPY.zh.researchAgentLlm).toBe("模型配置");
    expect(CONFIG_COPY.en.researchAgentPrompt).toBe("Prompt template");
    expect(CONFIG_COPY.en.researchAgentTemplate).toBe("Agent type");
    expect(CONFIG_COPY.en.researchAgentLlm).toBe("Model config");

    const visibleCopy = `${Object.values(CONFIG_COPY.zh).join("\n")}\n${Object.values(CONFIG_COPY.en).join("\n")}`;
    expect(visibleCopy).not.toContain("提示词文件");
    expect(visibleCopy).not.toContain("Prompt file");
  });

  it("points configuration users to the Agent prompt center", () => {
    expect(CONFIG_COPY.zh.promptTemplateCenterTitle).toBe("Agent 提示词中心");
    expect(CONFIG_COPY.en.promptTemplateCenterTitle).toBe("Agent prompt center");
    expect(CONFIG_COPY.zh.promptTemplateOpenCenter).toBe("打开提示词中心");
    expect(CONFIG_COPY.en.promptTemplateOpenCenter).toBe("Open prompt center");
  });

  it("keeps the settings sidebar status focused on save readiness", () => {
    expect(CONFIG_COPY.zh.settingsStatusTitle).toBe("设置状态");
    expect(CONFIG_COPY.zh.settingsCanSave).toBe("可以保存");
    expect(CONFIG_COPY.zh.settingsNeedsCheck).toBe("先检查高级配置");
    expect(CONFIG_COPY.en.settingsStatusTitle).toBe("Settings status");
    expect(CONFIG_COPY.en.settingsCanSave).toBe("Ready to save");
    expect(CONFIG_COPY.en.settingsNeedsCheck).toBe("Check advanced config first");
  });

  it("keeps agent editing centralized in Agent management from the config page", () => {
    expect(CONFIG_COPY.zh.agentConfigCenterTitle).toBe("Agent 管理入口");
    expect(CONFIG_COPY.en.agentConfigCenterTitle).toBe("Agent management entry");
    expect(CONFIG_COPY.zh.openAgentManagement).toBe("打开 Agent 管理");
    expect(CONFIG_COPY.en.openAgentManagement).toBe("Open Agent management");
    expect(CONFIG_COPY.zh.modeBindingTitle).toBe("模式里的 Agent 分配");
    expect(CONFIG_COPY.en.modeBindingTitle).toBe("Agent assignments by mode");
    expect(CONFIG_COPY.zh.modeBindingBody).toContain("只读展示");
    expect(CONFIG_COPY.en.modeBindingBody).toContain("read-only");
    expect(CONFIG_COPY.zh.researchAgentPoolBody).toContain("Agent 引用详情已收口到 Agent 管理");
    expect(CONFIG_COPY.en.researchAgentPoolBody).toContain("Agent reference details now live in Agent management");
    expect(CONFIG_COPY.zh.groupAgentEvolutionSummary).toContain("具体 Agent 绑定在 Agent 管理中维护");
    expect(CONFIG_COPY.en.groupAgentEvolutionSummary).toContain("edit Agent bindings in Agent management");
    const visibleCopy = `${Object.values(CONFIG_COPY.zh).join("\n")}\n${Object.values(CONFIG_COPY.en).join("\n")}`;
    expect(visibleCopy).not.toContain("ModeBinding");
    expect(visibleCopy).not.toContain("Persistent Agent");
    expect(visibleCopy).not.toContain("Persistent agent");
    expect(visibleCopy).not.toContain("execution-chain binding follows");
  });
});
