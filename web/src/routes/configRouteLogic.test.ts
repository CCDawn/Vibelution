import { describe, expect, it } from "vitest";

import {
  CONFIG_COPY,
} from "./ConfigRoute";
import {
  applyModelOptionToProfileDraft,
  collectModelDetailKeys,
  deriveConfigEditorSyncState,
  groupModelPresets,
  hasPendingSecretChanges,
  presetCategory,
  resolveProfileDisplayState,
  shouldBlockConfigLeave,
  type PublicConfigShape,
} from "./configRouteLogic";
import type { ConfigModelOption, ConfigModelPresetOption, ConfigProfileCard } from "../api/types";

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
  it("classifies model presets from explicit category before provider heuristics", () => {
    expect(presetCategory(preset("relay", { kind: "openai" }, "relay"))).toBe("relay");
    expect(presetCategory(preset("local", { kind: "openai", base_url: "http://127.0.0.1:11434/v1" }))).toBe("local");
    expect(presetCategory(preset("official", { kind: "openai", base_url: "https://api.openai.com/v1" }))).toBe("official");
  });

  it("groups presets in stable official relay local order and drops empty groups", () => {
    const groups = groupModelPresets(
      [
        preset("local_model", { kind: "local", base_url: "http://localhost:11434/v1" }),
        preset("relay_model", { kind: "relay", base_url: "https://pixel.try-chatapi.com/v1" }),
      ],
      {
        official: "Official",
        relay: "Relay",
        local: "Local",
      },
    );

    expect(groups.map((group) => group.id)).toEqual(["relay", "local"]);
    expect(groups.map((group) => group.label)).toEqual(["Relay", "Local"]);
    expect(groups[0].presets.map((item) => item.preset_id)).toEqual(["relay_model"]);
    expect(groups[1].presets.map((item) => item.preset_id)).toEqual(["local_model"]);
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
    expect(profile.primary.model_ref).toBeUndefined();
    expect(profile.primary.provider_id).toBeUndefined();
    expect(profile.primary.overrides).toBeUndefined();
    expect(profile.primary.provider).toEqual(selected.provider);
    expect(profile.primary.model).toBe("gpt-5.5");
    expect(profile.primary.api_key_env).toBe("VIBELUTION_LLM_RELAY_OPENAI_GPT_5_5_API_KEY");
    expect(profile.primary.transport).toBe("chat_completions");
    expect(profile.primary.contract).toBe("tool_chat");
    expect(profile.primary.timeout).toBe(120);
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
});

describe("config route copy", () => {
  it("uses task-model language instead of exposing profile jargon", () => {
    const zhCopy = JSON.stringify(CONFIG_COPY.zh);
    const enCopy = Object.entries(CONFIG_COPY.en)
      .filter(([key]) => !["runtimeProfile"].includes(key))
      .map(([, value]) => value)
      .join("\n");

    expect(CONFIG_COPY.zh.profilesTitle).toBe("任务模型");
    expect(CONFIG_COPY.en.profilesTitle).toBe("Task Models");
    expect(CONFIG_COPY.zh.openEnvironment).toBe("打开系统环境变量");
    expect(CONFIG_COPY.en.openEnvironment).toBe("Open system environment variables");
    expect(zhCopy).not.toContain("配置档");
    expect(zhCopy).not.toContain("模型档案");
    expect(enCopy).not.toMatch(/\bprofiles?\b/i);
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
});
