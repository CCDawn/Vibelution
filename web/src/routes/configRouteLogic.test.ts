import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  CONFIG_COPY,
} from "./ConfigRoute";
import {
  avatarCropSourceRect,
  buildConfigApplyPayload,
  canDiscoverModelsForProvider,
  clampAvatarCropOffset,
  configInvalidationDomainsForApply,
  defaultModelApiKeyEnv,
  deriveConfigEditorSyncState,
  deriveModelCenterInventoryRows,
  deriveModelCenterSummary,
  countModelCenterHealthIssues,
  groupModelPresets,
  groupProviderPresetsByVendor,
  hasPendingSecretChanges,
  listSupervisedAgentInstances,
  modelLibraryIdFromParts,
  mergeEditableConfigView,
  MODEL_CONTRACT_OPTIONS,
  MODEL_PROMPT_CACHE_MODE_OPTIONS,
  MODEL_TOOL_CALLING_MODE_OPTIONS,
  MODEL_TRANSPORT_OPTIONS,
  PROVIDER_KIND_OPTIONS,
  PROVIDER_COMPAT_MODE_OPTIONS,
  pickEditableConfigView,
  presetCategory,
  resolveImageInputCapabilityStatus,
  resolveConfigSectionUiStateOnSelect,
  resolveResearchAgentInstance,
  resolveModelEditability,
  selectModelScenarioProviderPresetId,
  selectModelScenarioPresetId,
  shouldBlockConfigLeave,
  supervisedAgentRole,
  supervisedAgentRoleLabel,
  type PublicConfigShape,
} from "./configRouteLogic";
import type { AgentInstance, ConfigModelOption, ConfigModelPresetOption, ConfigProviderPresetOption } from "../api/types";

const configRouteSource = readFileSync(fileURLToPath(new URL("./ConfigRoute.tsx", import.meta.url)), "utf8");

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

function providerPreset(
  providerPresetId: string,
  vendorId: string,
  vendorLabel: string,
  provider: Record<string, unknown>,
  category?: string,
): ConfigProviderPresetOption {
  return {
    provider_preset_id: providerPresetId,
    label: providerPresetId,
    vendor_id: vendorId,
    vendor_label: vendorLabel,
    category,
    provider_id: providerPresetId,
    source_preset_id: providerPresetId,
    provider,
    default_model: {},
  };
}

function option(overrides: Partial<ConfigModelOption> = {}): ConfigModelOption {
  return {
    model_id: "relay_openai_gpt_5_5",
    source: "model_library",
    provider: {
      kind: "relay",
      api: "openai-responses",
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
      protocol: "relay_responses",
      compat: { streamUsageOptions: true },
      streaming: true,
      timeout: 120,
    },
    api_key_env: "VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY",
    api_key_configured: false,
    api_key_state: "missing",
    provider_api: "openai-responses",
    protocol: "relay_responses",
    compat: { streamUsageOptions: true },
    resolved_protocol: "relay_responses",
    protocol_source: "explicit_model",
    resolved_provider_api: "openai-responses",
    resolved_compat: { streamUsageOptions: true, toolChoiceMode: "auto" },
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

  it("limits the advanced config editor to editable settings sections", () => {
    const config: PublicConfigShape = {
      runtime: { profile: "safe_local" },
      workbench: { backend_port: 8000 },
      avatar: { preset: "ember" },
      log: { max_entries: 300 },
      agent: { name: "Should stay hidden" },
      tools: { image2: { default_model_ref: "relay_image2" } },
      memory: { enabled: true },
    };
    const sections = [{ path: "avatar" }, { path: "log" }];

    const view = pickEditableConfigView(config, sections);

    expect(view).toEqual({
      avatar: { preset: "ember" },
      log: { max_entries: 300 },
    });
    expect(view.runtime).toBeUndefined();
    expect(view.workbench).toBeUndefined();
    expect(view.agent).toBeUndefined();
    expect(view.tools).toBeUndefined();
    expect(view.memory).toBeUndefined();
  });

  it("merges editable config editor changes without touching hidden domains", () => {
    const config: PublicConfigShape = {
      runtime: { profile: "safe_local" },
      workbench: { backend_port: 8000 },
      avatar: { preset: "ember" },
      agent: { name: "Persistent Agent" },
      tools: { image2: { default_model_ref: "relay_image2" } },
      memory: { enabled: true },
    };
    const editorView: PublicConfigShape = {
      avatar: { preset: "ocean" },
      tools: { image2: { default_model_ref: "hijacked" } },
    };

    const merged = mergeEditableConfigView(config, editorView, [{ path: "avatar" }]);

    expect(merged).toEqual({
      runtime: { profile: "safe_local" },
      workbench: { backend_port: 8000 },
      avatar: { preset: "ocean" },
      agent: { name: "Persistent Agent" },
      tools: { image2: { default_model_ref: "relay_image2" } },
      memory: { enabled: true },
    });
  });

  it("builds config apply payload with the original edit baseline", () => {
    const baseConfig: PublicConfigShape = {
      llm: {
        model_library: {
          relay: {
            provider: { base_url: "https://old.example/v1" },
            model: "gpt-5.5",
          },
          deleted: { model: "claude-opus-4-7" },
        },
      },
    };
    const draftConfig: PublicConfigShape = {
      llm: {
        model_library: {
          relay: {
            provider: { base_url: "https://old.example/v1" },
            model: "gpt-5.5",
          },
        },
      },
    };

    const payload = buildConfigApplyPayload({
      draftConfig,
      draftMeta: { pending_api_keys: {}, pending_cleared_api_keys: [] },
      baseHash: "base-hash",
      baseConfig,
      editorText: "{}",
      hasEditorChanges: false,
      editorSections: [],
      loadFailedMessage: "load failed",
    });

    expect(payload.baseConfig).toEqual(baseConfig);
    expect(payload.publicConfig).toEqual(draftConfig);
  });

  it("limits advanced editor apply payload to editable section diffs", () => {
    const draftConfig: PublicConfigShape = {
      avatar: { preset: "ember" },
      llm: {
        model_library: {
          relay: { provider: { base_url: "https://draft.example/v1" } },
        },
      },
    };
    const baseConfig: PublicConfigShape = {
      avatar: { preset: "ember" },
      llm: {
        model_library: {
          relay: { provider: { base_url: "https://base.example/v1" } },
        },
      },
    };

    const payload = buildConfigApplyPayload({
      draftConfig,
      draftMeta: { pending_api_keys: {}, pending_cleared_api_keys: [] },
      baseHash: "base-hash",
      baseConfig,
      editorText: JSON.stringify({
        avatar: { preset: "ocean" },
        llm: { model_library: { relay: { provider: { base_url: "https://hijack.example/v1" } } } },
      }),
      hasEditorChanges: true,
      editorSections: [{ path: "avatar" }],
      loadFailedMessage: "load failed",
    });

    expect(payload.publicConfig).toEqual({
      avatar: { preset: "ocean" },
      llm: {
        model_library: {
          relay: { provider: { base_url: "https://draft.example/v1" } },
        },
      },
    });
    expect(payload.baseConfig).toEqual(baseConfig);
  });

  it("classifies model presets from explicit category before provider heuristics", () => {
    expect(presetCategory(preset("relay", { kind: "openai" }, "relay"))).toBe("relay");
    expect(presetCategory(preset("local", { kind: "openai", base_url: "http://127.0.0.1:11434/v1" }))).toBe("local");
    expect(presetCategory(preset("llamacpp", { kind: "llamacpp", base_url: "http://192.168.20.46:8081/v1" }))).toBe("local");
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

  it("groups provider templates under stable vendor headings", () => {
    const groups = groupProviderPresetsByVendor([
      providerPreset("openai_main", "openai", "OpenAI", { kind: "openai" }, "official"),
      providerPreset("openai_image", "openai", "OpenAI", { kind: "openai" }, "official"),
      providerPreset("relay_openai", "relay", "中转站 / Relay", { kind: "relay" }, "relay"),
    ]);

    expect(groups.map((group) => group.id)).toEqual(["openai", "relay"]);
    expect(groups[0].label).toBe("OpenAI");
    expect(groups[0].templates.map((item) => item.provider_preset_id)).toEqual(["openai_main", "openai_image"]);
    expect(groups[1].templates.map((item) => item.provider_preset_id)).toEqual(["relay_openai"]);
  });

  it("only exposes model discovery for OpenAI-compatible provider routes", () => {
    expect(canDiscoverModelsForProvider({ kind: "local", base_url: "http://127.0.0.1:11434/v1", compat_mode: "openai" })).toBe(true);
    expect(canDiscoverModelsForProvider({ kind: "llamacpp", base_url: "http://192.168.20.46:8081/v1", compat_mode: "openai" })).toBe(true);
    expect(canDiscoverModelsForProvider({ kind: "openai_compatible", base_url: "https://relay.example.com/v1", compat_mode: "openai" })).toBe(true);
    expect(canDiscoverModelsForProvider({ kind: "anthropic", base_url: "https://api.anthropic.com", compat_mode: "native" })).toBe(false);
    expect(canDiscoverModelsForProvider({ kind: "google", base_url: "https://generativelanguage.googleapis.com", compat_mode: "native" })).toBe(false);
    expect(canDiscoverModelsForProvider({ kind: "custom", base_url: "https://example.com/v1", compat_mode: "openai" })).toBe(true);
    expect(canDiscoverModelsForProvider({ kind: "local", base_url: "", compat_mode: "openai" })).toBe(false);
  });

  it("keeps advanced model protocol fields constrained to supported enum values", () => {
    expect(MODEL_TRANSPORT_OPTIONS.map((item) => item.value)).toEqual(["chat_completions", "responses"]);
    expect(MODEL_CONTRACT_OPTIONS.map((item) => item.value)).toEqual([
      "basic_chat",
      "tool_chat",
      "reasoning_chat",
      "responses_agent",
    ]);
    expect(MODEL_TOOL_CALLING_MODE_OPTIONS.map((item) => item.value)).toEqual(["disabled", "auto", "parallel"]);
    expect(MODEL_PROMPT_CACHE_MODE_OPTIONS.map((item) => item.value)).toEqual([
      "automatic",
      "explicit_cache_control",
      "disabled",
      "unsupported",
    ]);
    expect(PROVIDER_COMPAT_MODE_OPTIONS.map((item) => item.value)).toEqual(["openai", "openai_compatible", "native"]);
  });

  it("derives model protocol route evidence for inventory rows", () => {
    const rows = deriveModelCenterInventoryRows([option()]);

    expect(rows[0]).toMatchObject({
      providerApi: "openai-responses",
      configuredProtocol: "relay_responses",
      resolvedProtocol: "relay_responses",
      protocolSource: "explicit_model",
      compatSummary: "streamUsageOptions=true · toolChoiceMode=auto",
    });
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

  it("derives the backend default model api key env for custom relay presets", () => {
    expect(defaultModelApiKeyEnv("custom_openai_compatible_relay")).toBe(
      "VIBELUTION_LLM_MODEL_CUSTOM_OPENAI_COMPATIBLE_RELAY_API_KEY",
    );
    expect(defaultModelApiKeyEnv("custom-relay.gpt")).toBe("VIBELUTION_LLM_MODEL_CUSTOM_RELAY_GPT_API_KEY");
    expect(defaultModelApiKeyEnv("gpt_5_5_gpt_5_5")).toBe("VIBELUTION_LLM_MODEL_GPT_5_5_API_KEY");
  });

  it("derives readable internal model ids and exposes provider kind choices", () => {
    expect(modelLibraryIdFromParts("pixel-open", "gpt-5.5")).toBe("pixel_open_gpt_5_5");
    expect(modelLibraryIdFromParts("", "gpt-5.5")).toBe("gpt_5_5");
    expect(modelLibraryIdFromParts("GPT-5.5", "gpt-5.5")).toBe("gpt_5_5");
    expect(PROVIDER_KIND_OPTIONS.map((item) => item.value)).toContain("openai_compatible");
    expect(PROVIDER_KIND_OPTIONS.map((item) => item.value)).toContain("relay");
    expect(PROVIDER_KIND_OPTIONS.map((item) => item.value)).toContain("xiaomi");
    expect(PROVIDER_KIND_OPTIONS.map((item) => item.value)).toContain("llamacpp");
    expect(PROVIDER_KIND_OPTIONS[0].value).toBe("relay");
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

  it("derives model center accounts without surfacing usage bindings", () => {
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
    const summary = deriveModelCenterSummary({
      modelOptions: [imageModel, chatModel],
    });

    expect(summary.accounts).toHaveLength(2);
    expect(summary.accounts.map((account) => account.apiKeyState).sort()).toEqual(["configured", "missing"]);
  });

  it("builds compact model inventory rows with asset editability in one place", () => {
    const libraryModel = option({
      model_id: "relay_openai_gpt_5_5",
      source: "model_library",
      api_key_state: "configured",
      api_key_configured: true,
    });
    const summary = deriveModelCenterSummary({
      modelOptions: [libraryModel],
    });

    const rows = deriveModelCenterInventoryRows([libraryModel]);

    expect(summary.accounts).toHaveLength(1);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      modelId: "relay_openai_gpt_5_5",
      editable: true,
      deletable: true,
      apiKeyState: "configured",
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
    const rows = deriveModelCenterInventoryRows([
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
    ]);

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

  it("counts only key and failed runtime probe issues in the model library", () => {
    const rows = deriveModelCenterInventoryRows([
      option({
        model_id: "missing_key",
        api_key_state: "missing",
        supports_image_input: true,
        capability_status: "supported",
      }),
      option({
        model_id: "text_only",
        api_key_state: "configured",
        supports_image_input: false,
        capability_status: "unsupported",
        capability_source: "runtime_probe",
      }),
      option({
        model_id: "not_checked",
        api_key_state: "configured",
        supports_image_input: null,
        capability_status: "unknown",
      }),
      option({
        model_id: "probe_failed",
        api_key_state: "configured",
        supports_image_input: null,
        capability_status: "unknown",
        capability_source: "runtime_probe",
        capability_error: "connection refused",
      }),
    ]);

    expect(countModelCenterHealthIssues(rows)).toBe(2);
  });

  it("exposes manual image input support in the model editor payload", () => {
    expect(CONFIG_COPY.zh.imageInputSupport).toBe("图像输入");
    expect(CONFIG_COPY.en.imageInputSupport).toBe("Image input");
    expect(configRouteSource).toContain('supports_image_input: "unknown"');
    expect(configRouteSource).toContain("payload.supports_image_input = true");
    expect(configRouteSource).toContain("payload.supports_image_input = false");
    expect(configRouteSource).toContain("modelEditorRef.current?.scrollIntoView");
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

  it("maps model creation scenarios to provider templates before concrete models", () => {
    const presets = [
      providerPreset("openai_main", "openai", "OpenAI", { kind: "openai" }, "official"),
      providerPreset("relay_openai", "relay", "中转站 / Relay", { kind: "relay" }, "relay"),
      providerPreset("relay_image", "relay", "中转站 / Relay", { kind: "relay" }, "relay"),
      providerPreset("local_main", "local", "本地模型服务", { kind: "local" }, "local"),
    ];

    expect(selectModelScenarioProviderPresetId("chat", presets)).toBe("relay_openai");
    expect(selectModelScenarioProviderPresetId("relay", presets)).toBe("relay_openai");
    expect(selectModelScenarioProviderPresetId("image", presets)).toBe("relay_image");
    expect(selectModelScenarioProviderPresetId("local", presets)).toBe("local_main");
    expect(selectModelScenarioProviderPresetId("manual", presets)).toBe("");
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

    expect(CONFIG_COPY.zh.openEnvironment).toBe("打开系统环境变量");
    expect(CONFIG_COPY.en.openEnvironment).toBe("Open system environment variables");
    expect("profilesTitle" in CONFIG_COPY.zh).toBe(false);
    expect("profilesTitle" in CONFIG_COPY.en).toBe(false);
    expect("editProfiles" in CONFIG_COPY.zh).toBe(false);
    expect("editProfiles" in CONFIG_COPY.en).toBe(false);
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

  it("points startup settings to Launcher instead of generic config", () => {
    const zhCopy = Object.values(CONFIG_COPY.zh).join("\n");
    const enCopy = Object.values(CONFIG_COPY.en).join("\n");

    expect(CONFIG_COPY.zh.subtitle).toContain("启动设置在 Launcher 面板维护");
    expect(CONFIG_COPY.en.subtitle).toContain("Startup settings are maintained in Launcher");
    expect(CONFIG_COPY.zh.groupWorkbenchSummary).toContain("启动设置移到 Launcher");
    expect(CONFIG_COPY.en.groupWorkbenchSummary).toContain("Startup settings moved to Launcher");
    expect(zhCopy).not.toContain("唯一配置网页入口");
    expect(enCopy).not.toContain("single config web entry");
    expect(CONFIG_COPY.zh.groupWorkbenchSummary).not.toContain("前后端端口");
    expect(CONFIG_COPY.en.groupWorkbenchSummary).not.toContain("frontend/backend ports");
  });

  it("splits model assets and git tooling into separate areas", () => {
    expect(CONFIG_COPY.zh.groupModelingTitle).toBe("模型库");
    expect(CONFIG_COPY.en.groupModelingTitle).toBe("Model Library");

    const visibleCopy = `${Object.values(CONFIG_COPY.zh).join("\n")}\n${Object.values(CONFIG_COPY.en).join("\n")}`;
    expect(visibleCopy).not.toContain("Git 提交模型");
    expect(visibleCopy).not.toContain("Git commit model");
  });

  it("exposes the settings model library as asset-oriented inventory", () => {
    expect(CONFIG_COPY.zh.modelsTitle).toBe("模型库");
    expect(CONFIG_COPY.en.modelsTitle).toBe("Model Library");
    expect(CONFIG_COPY.zh.modelCenterAccounts).toBe("服务商账号");
    expect(CONFIG_COPY.zh.modelScenarioChat).toBe("通用对话模型");
    expect(CONFIG_COPY.zh.modelScenarioImage).toBe("图片工具模型");
    expect(CONFIG_COPY.en.modelScenarioChat).toBe("General chat model");
    expect(CONFIG_COPY.en.modelScenarioImage).toBe("Image tool model");

    const allCopy = `${Object.values(CONFIG_COPY.zh).join("\n")}\n${Object.values(CONFIG_COPY.en).join("\n")}`;
    expect("modelCenterSource" in CONFIG_COPY.zh).toBe(false);
    expect("modelCenterSource" in CONFIG_COPY.en).toBe(false);
    expect("sourceLibrary" in CONFIG_COPY.zh).toBe(false);
    expect("sourceLibrary" in CONFIG_COPY.en).toBe(false);
    expect("modelLibrary" in CONFIG_COPY.zh).toBe(false);
    expect("modelLibrary" in CONFIG_COPY.en).toBe(false);
    expect("modelCenterIssues" in CONFIG_COPY.zh).toBe(false);
    expect("modelCenterIssues" in CONFIG_COPY.en).toBe(false);
    expect("modelCenterAccountModels" in CONFIG_COPY.zh).toBe(false);
    expect("modelCenterAccountModels" in CONFIG_COPY.en).toBe(false);
    expect("image2ToolUsage" in CONFIG_COPY.zh).toBe(false);
    expect("image2ToolUsage" in CONFIG_COPY.en).toBe(false);
    expect(allCopy).not.toContain("聊天 Agent");
    expect(allCopy).not.toContain("Chat agent");
    expect(allCopy).not.toContain("LLM 槽位绑定");
    expect(allCopy).not.toMatch(/\bslot bindings?\b/i);
    expect(allCopy).not.toContain("模型绑定");
    expect(allCopy).not.toContain("内部键");
    expect(allCopy).not.toMatch(/\bmodel bindings?\b/i);
    expect(allCopy).not.toMatch(/\binternal key\b/i);
  });

  it("keeps research agent editing copy out of generic config", () => {
    const visibleCopy = `${Object.values(CONFIG_COPY.zh).join("\n")}\n${Object.values(CONFIG_COPY.en).join("\n")}`;
    expect("researchAgentPrompt" in CONFIG_COPY.zh).toBe(false);
    expect("researchAgentPrompt" in CONFIG_COPY.en).toBe(false);
    expect("researchAgentLlm" in CONFIG_COPY.zh).toBe(false);
    expect("researchAgentLlm" in CONFIG_COPY.en).toBe(false);
    expect(visibleCopy).not.toContain("提示词文件");
    expect(visibleCopy).not.toContain("Prompt file");
  });

  it("keeps Agent prompt center copy out of generic config", () => {
    const visibleCopy = `${Object.values(CONFIG_COPY.zh).join("\n")}\n${Object.values(CONFIG_COPY.en).join("\n")}`;
    expect(visibleCopy).not.toContain("Agent 提示词中心");
    expect(visibleCopy).not.toContain("Agent prompt center");
    expect(visibleCopy).not.toContain("打开提示词中心");
    expect(visibleCopy).not.toContain("Open prompt center");
    expect("groupPromptTitle" in CONFIG_COPY.zh).toBe(false);
    expect("groupPromptTitle" in CONFIG_COPY.en).toBe(false);
  });

  it("keeps the settings sidebar status focused on save readiness", () => {
    expect(CONFIG_COPY.zh.settingsStatusTitle).toBe("设置状态");
    expect(CONFIG_COPY.zh.settingsCanSave).toBe("可以保存");
    expect(CONFIG_COPY.zh.settingsNeedsCheck).toBe("先检查高级配置");
    expect(CONFIG_COPY.en.settingsStatusTitle).toBe("Settings status");
    expect(CONFIG_COPY.en.settingsCanSave).toBe("Ready to save");
    expect(CONFIG_COPY.en.settingsNeedsCheck).toBe("Check advanced config first");
  });

  it("names evolution intake separately from runtime mode", () => {
    expect(CONFIG_COPY.zh.runtimeProfile).toBe("运行档位");
    expect(CONFIG_COPY.zh.defaultMode).toBe("默认模式");
    expect(CONFIG_COPY.zh.intakeMode).toBe("进化审核");
    expect(CONFIG_COPY.en.runtimeProfile).toBe("Runtime mode");
    expect(CONFIG_COPY.en.defaultMode).toBe("Default mode");
    expect(CONFIG_COPY.en.intakeMode).toBe("Review intake");
  });

  it("keeps agent editing copy out of generic config", () => {
    const visibleCopy = `${Object.values(CONFIG_COPY.zh).join("\n")}\n${Object.values(CONFIG_COPY.en).join("\n")}`;
    expect("agentConfigCenterTitle" in CONFIG_COPY.zh).toBe(false);
    expect("agentConfigCenterTitle" in CONFIG_COPY.en).toBe(false);
    expect("openAgentManagement" in CONFIG_COPY.zh).toBe(false);
    expect("openAgentManagement" in CONFIG_COPY.en).toBe(false);
    expect("modeBindingTitle" in CONFIG_COPY.zh).toBe(false);
    expect("modeBindingTitle" in CONFIG_COPY.en).toBe(false);
    expect("researchAgentPoolBody" in CONFIG_COPY.zh).toBe(false);
    expect("researchAgentPoolBody" in CONFIG_COPY.en).toBe(false);
    expect(visibleCopy).not.toContain("Agent 管理入口");
    expect(visibleCopy).not.toContain("Agent management entry");
    expect(visibleCopy).not.toContain("模式里的 Agent 分配");
    expect(visibleCopy).not.toContain("Agent assignments by mode");
    expect(visibleCopy).not.toContain("ModeBinding");
    expect(visibleCopy).not.toContain("Persistent Agent");
    expect(visibleCopy).not.toContain("Persistent agent");
    expect(visibleCopy).not.toContain("execution-chain binding follows");
  });

  it("distinguishes terminal avatar settings from the Web user avatar", () => {
    expect(CONFIG_COPY.zh.groupAvatarPetTitle).toBe("用户、终端形象与陪伴体");
    expect(CONFIG_COPY.zh.groupAvatarPetSummary).toContain("Web 用户头像在用户信息里维护");
    expect(CONFIG_COPY.en.groupAvatarPetTitle).toBe("User, Terminal Avatar, and Companion");
    expect(CONFIG_COPY.en.groupAvatarPetSummary).toContain("Web user avatar lives under User Info");
  });

  it("keeps Web user avatar image copy explicit and separate from raw config paths", () => {
    expect(CONFIG_COPY.zh.avatarImageCurrent).toBe("当前头像");
    expect(CONFIG_COPY.zh.avatarImageEmpty).toBe("未设置头像图片");
    expect(CONFIG_COPY.zh.avatarImageClickToUpload).toBe("点击头像上传");
    expect(CONFIG_COPY.zh.userProfileAvatarGroupTitle).toBe("头像设置");
    expect(CONFIG_COPY.zh.userProfileAvatarGroupHint).toContain("不会把图片内容传给模型");
    expect(CONFIG_COPY.en.avatarImageCurrent).toBe("Current avatar");
    expect(CONFIG_COPY.en.avatarImageEmpty).toBe("No avatar image set");
    expect(CONFIG_COPY.en.avatarImageClickToUpload).toBe("Click avatar to upload");
    expect(CONFIG_COPY.en.userProfileAvatarGroupTitle).toBe("Avatar settings");
    expect(CONFIG_COPY.en.userProfileAvatarGroupHint).toContain("Image content is not sent to the model");
  });
});
