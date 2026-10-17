// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { testConfigLlm } from "../../api/config";
import { queryKeys } from "../../api/queryKeys";
import type { ConfigCatalogModel, ConfigLlmTestResult } from "../../api/types";
import { initialProviderQuickSetupState } from "../configProviderLogic";
import { useConfigProviderQuickSetupActions, type UseConfigProviderQuickSetupActionsOptions } from "./useConfigProviderQuickSetupActions";
import { CONFIG_COPY } from "./configCopy";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("../../api/config", () => ({ testConfigLlm: vi.fn() }));

function options(): UseConfigProviderQuickSetupActionsOptions {
  const initial = initialProviderQuickSetupState();
  return {
    providerQuickSetupState: { ...initial, phase: "review", provider: { ...initial.provider, providerId: "test" }, selectedModelRef: "test/model",
      discoveredModels: [{ availability: "observed", modelRef: "test/model", modelKey: "model", label: "Test", upstreamId: "model", status: "observed", capabilities: {} }] },
    copy: CONFIG_COPY.zh,
    providerPresetOptions: [], providerDraftRequestRef: { current: null }, queryClient: new QueryClient(),
    dispatchProviderQuickSetup: vi.fn(), setProviderQuickCredential: vi.fn(), handleSuggestProviderId: vi.fn(),
    handleCreateProvider: vi.fn(), handleDiscoverProvider: vi.fn(), handlePinProviderModels: vi.fn().mockResolvedValue(true),
    handlePinManualProviderModel: vi.fn(),
    handleDiscardDraftProviders: vi.fn().mockResolvedValue(undefined),
    handleApply: vi.fn().mockResolvedValue(true), readableErrorMessage: String,
  };
}

async function run(input: UseConfigProviderQuickSetupActionsOptions, action?: (actions: ReturnType<typeof useConfigProviderQuickSetupActions>) => Promise<void>) {
  const container = document.createElement("div");
  const root = createRoot(container);
  let actions!: ReturnType<typeof useConfigProviderQuickSetupActions>;
  function Harness() { actions = useConfigProviderQuickSetupActions(input); return null; }
  try {
    await act(async () => root.render(<Harness />));
    await act(async () => action ? action(actions) : actions.handleConfirmProviderQuickSetup());
  } finally { await act(async () => root.unmount()); input.queryClient.clear(); }
}

describe("quick setup save recovery", () => {
  it("does not apply or report success when adding the model fails", async () => {
    const input = options(); vi.mocked(input.handlePinProviderModels).mockResolvedValue(false);
    await run(input);
    expect(input.handleApply).not.toHaveBeenCalled();
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith(expect.objectContaining({ type: "save_failed", errorKind: "save" }));
    expect(input.dispatchProviderQuickSetup).not.toHaveBeenCalledWith({ type: "save_succeeded" });
  });
  it("retries only formal save after a partial save failure", async () => {
    const input = options();
    input.providerQuickSetupState = { ...input.providerQuickSetupState, phase: "error", errorKind: "partial_save" };
    await run(input);
    expect(input.handlePinProviderModels).not.toHaveBeenCalled();
    expect(input.handleCreateProvider).not.toHaveBeenCalled();
    expect(input.handleDiscoverProvider).not.toHaveBeenCalled();
    expect(input.handleApply).toHaveBeenCalledOnce();
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith({ type: "save_succeeded" });
  });
  it("keeps a failed apply retryable without a false success", async () => {
    const input = options(); vi.mocked(input.handleApply).mockResolvedValue(false);
    await run(input);
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith(expect.objectContaining({ type: "save_failed", errorKind: "partial_save" }));
    expect(input.dispatchProviderQuickSetup).not.toHaveBeenCalledWith({ type: "save_succeeded" });
  });
});

describe("manual model test and save", () => {
  beforeEach(() => { vi.mocked(testConfigLlm).mockReset(); });

  function manualOptions() {
    const input = options();
    const model: ConfigCatalogModel = {
      upstreamId: "Vendor/Model-A", modelRef: "test/vendor-model-a-1234", modelKey: "vendor-model-a-1234",
      availability: "pinned", status: "pinned", label: "Vendor/Model-A", capabilities: {},
    };
    input.providerDraftRequestRef.current = { publicConfig: { llm: { providers: {} } }, draftMeta: {}, baseHash: "baseline" };
    vi.mocked(input.handleCreateProvider).mockImplementation(async (provider) => {
      input.providerDraftRequestRef.current = {
        publicConfig: { llm: { providers: { [provider.providerId]: {} } } }, draftMeta: {}, baseHash: "baseline",
      };
    });
    vi.mocked(input.handlePinManualProviderModel).mockImplementation(async () => {
      input.providerDraftRequestRef.current = {
        publicConfig: { marker: "latest-pinned-config", llm: { providers: { test: {} } } },
        draftMeta: { pending_api_keys: { test: "opaque-pending-token" } }, baseHash: "baseline",
      };
      return model;
    });
    return input;
  }

  it("tests the backend model ref with latest pending credentials and saves without discovering a catalog", async () => {
    const input = manualOptions();
    const invalidate = vi.spyOn(input.queryClient, "invalidateQueries").mockResolvedValue();
    vi.mocked(testConfigLlm).mockResolvedValue({ ok: true } as ConfigLlmTestResult);
    await run(input, async (actions) => {
      await actions.handleTestAndSaveProviderQuickSetup({ provider: input.providerQuickSetupState.provider, credentialValue: "new-key", modelId: "Vendor/Model-A" });
    });
    const snapshot = input.providerDraftRequestRef.current!;
    expect(input.handleDiscoverProvider).not.toHaveBeenCalled();
    expect(input.handlePinManualProviderModel).toHaveBeenCalledWith("test", "Vendor/Model-A", expect.any(Object));
    expect(testConfigLlm).toHaveBeenCalledWith({
      publicConfig: snapshot.publicConfig, draftMeta: snapshot.draftMeta, baseHash: "baseline",
      modelId: "test/vendor-model-a-1234", capability: "text",
    });
    expect(input.handleApply).toHaveBeenCalledWith(input.copy.quickSetupApplyBusy, snapshot);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.configWorkspace() });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.agentConfigWorkspace() });
    expect(input.setProviderQuickCredential).toHaveBeenCalledWith("");
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith({ type: "save_succeeded" });
  });

  it("preserves the form and never saves when the real model test fails", async () => {
    const input = manualOptions();
    vi.mocked(testConfigLlm).mockResolvedValue({ ok: false, message: "text capability unsupported" } as ConfigLlmTestResult);
    await run(input, async (actions) => {
      await actions.handleTestAndSaveProviderQuickSetup({ provider: input.providerQuickSetupState.provider, credentialValue: "key", modelId: "Vendor/Model-A" });
    });
    expect(input.handleApply).not.toHaveBeenCalled();
    expect(input.setProviderQuickCredential).not.toHaveBeenCalled();
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith(expect.objectContaining({ type: "check_failed", errorMessage: expect.stringContaining("text capability unsupported") }));
    expect(input.dispatchProviderQuickSetup).not.toHaveBeenCalledWith({ type: "save_succeeded" });
  });

  it("keeps cancellation pending during a real call and applies only the tested snapshot", async () => {
    const input = manualOptions();
    let completeTest!: (result: ConfigLlmTestResult) => void;
    let signalStarted!: () => void;
    const started = new Promise<void>((resolve) => { signalStarted = resolve; });
    vi.mocked(testConfigLlm).mockImplementation(() => {
      signalStarted();
      return new Promise<ConfigLlmTestResult>((resolve) => { completeTest = resolve; });
    });
    await run(input, async (actions) => {
      const request = actions.handleTestAndSaveProviderQuickSetup({
        provider: input.providerQuickSetupState.provider, credentialValue: "key", modelId: "Vendor/Model-A",
      });
      await started;
      expect(await actions.handleCancelProviderQuickSetup()).toBe(false);
      expect(input.handleDiscardDraftProviders).not.toHaveBeenCalled();
      const testedSnapshot = input.providerDraftRequestRef.current;
      input.providerDraftRequestRef.current = { ...testedSnapshot!, publicConfig: { marker: "untested concurrent edit" } };
      completeTest({ ok: true } as ConfigLlmTestResult);
      await request;
      expect(input.handleApply).toHaveBeenCalledWith(input.copy.quickSetupApplyBusy, testedSnapshot);
    });
  });

  it("can test the same input again after a failed apply without creating another identity", async () => {
    const input = manualOptions();
    vi.mocked(testConfigLlm).mockResolvedValue({ ok: true } as ConfigLlmTestResult);
    vi.mocked(input.handleApply).mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    await run(input, async (actions) => {
      const request = { provider: input.providerQuickSetupState.provider, credentialValue: "key", modelId: "Vendor/Model-A" };
      await actions.handleTestAndSaveProviderQuickSetup(request);
      expect(input.setProviderQuickCredential).not.toHaveBeenCalled();
      await actions.handleTestAndSaveProviderQuickSetup(request);
    });
    expect(input.handleSuggestProviderId).not.toHaveBeenCalled();
    expect(testConfigLlm).toHaveBeenCalledTimes(2);
    expect(input.handleApply).toHaveBeenCalledTimes(2);
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith({ type: "save_succeeded" });
  });

  it.each(["Vendor/Model-A", "other-model"])("copies safe preset defaults only for the matching upstream model (%s)", async (modelId) => {
    const input = manualOptions();
    input.providerPresetOptions = [{
      provider_preset_id: "preset", default_model: {
        model: "Vendor/Model-A", contract: "reasoning_chat", protocol: "preset_protocol",
        temperature: 0.2, max_output_tokens: 8192, prompt_cache: { mode: "automatic", api_key: "forbidden" },
        api_key_env: "FORBIDDEN_KEY", credential_ref: "forbidden", arbitrary_metadata: { secret: "forbidden" },
      },
    }];
    vi.mocked(testConfigLlm).mockResolvedValue({ ok: false, message: "stop before save" } as ConfigLlmTestResult);
    await run(input, async (actions) => {
      await actions.handleTestAndSaveProviderQuickSetup({
        provider: { ...input.providerQuickSetupState.provider, templateId: "preset", defaultProtocol: "responses" },
        credentialValue: "key", modelId,
      });
    });
    const overrides = vi.mocked(input.handlePinManualProviderModel).mock.calls[0][2];
    expect(overrides).toEqual(modelId === "Vendor/Model-A" ? {
      wire_protocol: "responses", interaction_contract: "reasoning_chat", model_protocol: "preset_protocol",
      defaults: { temperature: 0.2, max_output_tokens: 8192, prompt_cache: { mode: "automatic" } },
    } : { wire_protocol: "responses" });
  });
});

describe("quick setup preparation recovery", () => {
  it("isolates a new key from another provider's env reference and avoids reference collisions", async () => {
    const input = options();
    input.providerDraftRequestRef.current = {
      publicConfig: { llm: { providers: {
        saved: { credential_ref: "env:OPENAI_API_KEY" },
        other: { credential_ref: "env:VIBELUTION_LLM_PROVIDER_TEST_API_KEY" },
      } } }, draftMeta: {}, baseHash: "baseline",
    };
    const original = structuredClone(input.providerDraftRequestRef.current);
    vi.mocked(input.handleDiscoverProvider).mockRejectedValue(new Error("failed probe"));
    await run(input, async (actions) => {
      const provider = { ...input.providerQuickSetupState.provider, credentialRef: "env:OPENAI_API_KEY" };
      await actions.handlePrepareProviderQuickSetup({ provider, credentialValue: "new-key" });
      await actions.handlePrepareProviderQuickSetup({ provider, credentialValue: "fixed-key" });
    });
    for (const [provider] of vi.mocked(input.handleCreateProvider).mock.calls) {
      expect(provider.credentialRef).toBe("env:VIBELUTION_LLM_PROVIDER_TEST_2_API_KEY");
    }
    expect(input.providerDraftRequestRef.current).toEqual(original);
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith(expect.objectContaining({
      type: "set_provider", provider: expect.objectContaining({ credentialRef: "env:VIBELUTION_LLM_PROVIDER_TEST_2_API_KEY" }),
    }));
  });

  it.each([true, false])("discards only owned draft IDs on cancel and closes only after cleanup succeeds (%s)", async (success) => {
    const input = options();
    vi.mocked(input.handleDiscoverProvider).mockRejectedValue(new Error("failed probe"));
    if (!success) vi.mocked(input.handleDiscardDraftProviders).mockRejectedValueOnce(new Error("preview failed"));
    await run(input, async (actions) => {
      await actions.handlePrepareProviderQuickSetup({ provider: input.providerQuickSetupState.provider, credentialValue: "key" });
      expect(await actions.handleCancelProviderQuickSetup()).toBe(success);
      if (!success) {
        expect(input.setProviderQuickCredential).not.toHaveBeenCalled();
        expect(input.dispatchProviderQuickSetup).not.toHaveBeenCalledWith({ type: "reset" });
        vi.mocked(input.handleDiscardDraftProviders).mockResolvedValueOnce(undefined);
        expect(await actions.handleCancelProviderQuickSetup()).toBe(true);
      }
    });
    expect(input.handleDiscardDraftProviders).toHaveBeenCalledWith(["test"]);
    expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith({ type: "reset" });
  });

  it("suggests a fresh ID for a saved collision and reuses its own draft after failed discovery", async () => {
    const input = options();
    input.providerDraftRequestRef.current = {
      publicConfig: { llm: { providers: { test: { label: "Saved service" } } } },
      draftMeta: {}, baseHash: "baseline",
    };
    vi.mocked(input.handleSuggestProviderId).mockResolvedValue("test-2");
    vi.mocked(input.handleCreateProvider).mockImplementation(async (provider) => {
      input.providerDraftRequestRef.current!.publicConfig = {
        llm: { providers: { test: { label: "Saved service" }, [provider.providerId]: {} } },
      };
    });
    vi.mocked(input.handleDiscoverProvider)
      .mockRejectedValueOnce(new Error("invalid API key"))
      .mockResolvedValueOnce([]);
    await run(input, async (actions) => {
      await actions.handlePrepareProviderQuickSetup({ provider: input.providerQuickSetupState.provider, credentialValue: "first-key" });
      expect(input.setProviderQuickCredential).not.toHaveBeenCalled();
      expect(input.dispatchProviderQuickSetup).toHaveBeenCalledWith(expect.objectContaining({ type: "check_failed" }));
      await actions.handlePrepareProviderQuickSetup({
        provider: { ...input.providerQuickSetupState.provider, providerId: "test-2", baseUrl: "https://fixed.example/v1" },
        credentialValue: "fixed-key",
      });
    });
    expect(input.handleSuggestProviderId).toHaveBeenCalledOnce();
    expect(vi.mocked(input.handleCreateProvider).mock.calls.map(([provider]) => provider.providerId)).toEqual(["test-2", "test-2"]);
    expect(input.handleCreateProvider).toHaveBeenLastCalledWith(expect.objectContaining({ baseUrl: "https://fixed.example/v1" }), "fixed-key");
    expect(input.handleDiscoverProvider).toHaveBeenLastCalledWith("test-2", "fixed-key");
    expect(input.setProviderQuickCredential).not.toHaveBeenCalled();
  });

  it.each([true, false])("releases draft ownership only when formal save succeeds (%s)", async (applied) => {
    const input = options();
    input.providerDraftRequestRef.current = { publicConfig: { llm: { providers: {} } }, draftMeta: {}, baseHash: "baseline" };
    vi.mocked(input.handleSuggestProviderId).mockResolvedValue("test-2");
    vi.mocked(input.handleDiscoverProvider).mockResolvedValue([]);
    vi.mocked(input.handleApply).mockResolvedValue(applied);
    vi.mocked(input.handleCreateProvider).mockImplementation(async (provider) => {
      input.providerDraftRequestRef.current!.publicConfig = { llm: { providers: { [provider.providerId]: {} } } };
    });
    await run(input, async (actions) => {
      await actions.handlePrepareProviderQuickSetup({ provider: input.providerQuickSetupState.provider, credentialValue: "key" });
      await actions.handleConfirmProviderQuickSetup();
      await actions.handlePrepareProviderQuickSetup({ provider: input.providerQuickSetupState.provider, credentialValue: "new-key" });
    });
    expect(input.handleSuggestProviderId).toHaveBeenCalledTimes(applied ? 1 : 0);
    expect(input.handleCreateProvider).toHaveBeenLastCalledWith(expect.objectContaining({ providerId: applied ? "test-2" : "test" }), "new-key");
  });
});
