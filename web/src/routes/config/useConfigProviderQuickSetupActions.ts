/**
 * Provider quick-setup orchestration (detect + pin + formal apply).
 * Network primitives come from useConfigProviderDraftActions + handleApply.
 */
import { useCallback, useRef, type Dispatch } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import { testConfigLlm } from "../../api/config";
import type { ConfigCatalogModel } from "../../api/types";
import { asRecord, getString } from "../configRouteLogic";
import {
  buildProviderWizardDraft,
  recommendProviderModel,
  type ProviderQuickSetupAction,
  type ProviderQuickSetupState,
  type ProviderWizardState,
} from "../configProviderLogic";
import type { ConfigApplyDraftOverride } from "./configApplyModel";
import { type ConfigCopy } from "./configCopy";
import { classifyProviderQuickSetupErrorKind } from "./configProviderActionModel";

export type UseConfigProviderQuickSetupActionsOptions = {
  providerQuickSetupState: ProviderQuickSetupState;
  /** Bilingual copy table (wave 4): quick-setup failure + busy copy. */
  copy: ConfigCopy;
  providerPresetOptions: Array<{
    provider_preset_id: string;
    provider?: Record<string, unknown>;
    default_model?: Record<string, unknown>;
  }>;
  providerDraftRequestRef: { current: ConfigApplyDraftOverride | null | { publicConfig: ConfigApplyDraftOverride["publicConfig"]; draftMeta: ConfigApplyDraftOverride["draftMeta"]; baseHash: string } };
  queryClient: QueryClient;
  dispatchProviderQuickSetup: Dispatch<ProviderQuickSetupAction>;
  setProviderQuickCredential: (value: string) => void;
  handleSuggestProviderId: (provider: Record<string, unknown>) => Promise<string>;
  handleCreateProvider: (state: ProviderWizardState, credentialValue: string) => Promise<void>;
  handleDiscoverProvider: (providerId: string, credentialValue?: string) => Promise<ConfigCatalogModel[]>;
  handlePinProviderModels: (providerId: string, models: ConfigCatalogModel[]) => Promise<boolean>;
  handlePinManualProviderModel: (providerId: string, upstreamId: string, overrides?: Record<string, unknown>) => Promise<ConfigCatalogModel>;
  handleDiscardDraftProviders: (providerIds: string[]) => Promise<void>;
  handleApply: (pendingLabel?: string, draftOverride?: ConfigApplyDraftOverride) => Promise<boolean>;
  readableErrorMessage: (error: unknown) => string;
};

function manualModelOverrides(provider: ProviderWizardState, upstreamId: string, defaultModel: Record<string, unknown>): Record<string, unknown> {
  const overrides: Record<string, unknown> = { wire_protocol: provider.defaultProtocol };
  if (upstreamId !== getString(defaultModel.model)) return overrides;
  const source = { ...defaultModel, ...asRecord(defaultModel.defaults) };
  const defaults: Record<string, unknown> = {};
  for (const key of [
    "temperature", "max_output_tokens", "timeout", "connect_timeout", "streaming", "tool_calling_mode",
    "default_reasoning_effort", "reasoning_effort_adapter", "reasoning_state_field", "thinking_type", "thinking_display",
    "strict_compatibility", "discovery_enabled",
  ]) {
    const value = source[key];
    if (["string", "number", "boolean"].includes(typeof value)) defaults[key] = value;
  }
  if (Array.isArray(source.reasoning_effort_values)) {
    defaults.reasoning_effort_values = source.reasoning_effort_values.filter((value) => typeof value === "string");
  }
  const promptCache = asRecord(source.prompt_cache);
  const cache = Object.fromEntries(["mode", "key", "retention"]
    .filter((key) => typeof promptCache[key] === "string").map((key) => [key, promptCache[key]]));
  if (Object.keys(cache).length) defaults.prompt_cache = cache;
  const contract = getString(defaultModel.interaction_contract) || getString(defaultModel.contract);
  const protocol = getString(defaultModel.model_protocol) || getString(defaultModel.protocol);
  if (contract) overrides.interaction_contract = contract;
  if (protocol) overrides.model_protocol = protocol;
  if (typeof defaultModel.context_window === "number") overrides.context_window = defaultModel.context_window;
  if (Object.keys(defaults).length) overrides.defaults = defaults;
  return overrides;
}

export function useConfigProviderQuickSetupActions(options: UseConfigProviderQuickSetupActionsOptions) {
  const {
    providerQuickSetupState,
    copy,
    providerPresetOptions,
    providerDraftRequestRef,
    queryClient,
    dispatchProviderQuickSetup,
    setProviderQuickCredential,
    handleSuggestProviderId,
    handleCreateProvider,
    handleDiscoverProvider,
    handlePinProviderModels,
    handlePinManualProviderModel,
    handleDiscardDraftProviders,
    handleApply,
    readableErrorMessage,
  } = options;
  // Discovery failures leave this hook's provider in the shared unsaved draft.
  const createdProviderIdsRef = useRef(new Set<string>());
  const inFlightRef = useRef(false);

  const ensureProviderQuickSetup = useCallback(async (input: {
    provider: ProviderWizardState;
    credentialValue: string;
  }) => {
      let provider = input.provider;
      const draftProviders = asRecord(asRecord(providerDraftRequestRef.current?.publicConfig.llm).providers);
      const collidesWithAnotherProvider = Object.prototype.hasOwnProperty.call(draftProviders, provider.providerId)
        && !createdProviderIdsRef.current.has(provider.providerId);
      if (!provider.providerId || collidesWithAnotherProvider) {
        const template = providerPresetOptions.find((item) => item.provider_preset_id === provider.templateId);
        const suggestedProviderId = await handleSuggestProviderId(buildProviderWizardDraft(provider, template?.provider));
        provider = { ...provider, providerId: suggestedProviderId };
      }
      if (input.credentialValue && provider.authKind !== "none") {
        const usedRefs = new Set(Object.entries(draftProviders).filter(([id]) => id !== provider.providerId)
          .map(([, item]) => getString(asRecord(item).credential_ref)));
        if (!provider.credentialRef.startsWith("env:") || usedRefs.has(provider.credentialRef)) {
          const currentRef = getString(asRecord(draftProviders[provider.providerId]).credential_ref);
          const pendingKeys = asRecord(providerDraftRequestRef.current?.draftMeta.pending_api_keys);
          const stem = `VIBELUTION_LLM_PROVIDER_${provider.providerId.toUpperCase().replace(/[^A-Z0-9]+/g, "_")}`;
          let envName = `${stem}_API_KEY`;
          let suffix = 2;
          while (usedRefs.has(`env:${envName}`) || (pendingKeys[envName] && currentRef !== `env:${envName}`)) {
            envName = `${stem}_${suffix++}_API_KEY`;
          }
          provider = { ...provider, credentialRef: `env:${envName}` };
        }
      }
      if (provider !== input.provider) {
        dispatchProviderQuickSetup({ type: "set_provider", provider });
        dispatchProviderQuickSetup({ type: "start_check" });
      }
      await handleCreateProvider(provider, input.credentialValue);
      createdProviderIdsRef.current.add(provider.providerId);
      return provider;
  }, [dispatchProviderQuickSetup, handleCreateProvider, handleSuggestProviderId, providerDraftRequestRef, providerPresetOptions]);

  const handlePrepareProviderQuickSetup = useCallback(async (input: {
    provider: ProviderWizardState;
    credentialValue: string;
  }) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    dispatchProviderQuickSetup({ type: "start_check" });
    try {
      const provider = await ensureProviderQuickSetup(input);
      const models = await handleDiscoverProvider(provider.providerId, input.credentialValue);
      const template = providerPresetOptions.find((item) => item.provider_preset_id === provider.templateId);
      const defaultModel = asRecord(template?.default_model);
      const templateDefaultModelRef = getString(defaultModel.model_ref)
        || getString(defaultModel.modelRef)
        || (getString(defaultModel.model) ? `${provider.providerId}/${getString(defaultModel.model)}` : "");
      const recommendation = recommendProviderModel(models, {
        templateDefaultModelRef,
        allowedProtocols: provider.allowedProtocols,
      });
      dispatchProviderQuickSetup({
        type: "check_succeeded",
        models,
        selectedModelRef: recommendation.modelRef,
        recommendationReason: recommendation.reason,
      });
    } catch (error) {
      dispatchProviderQuickSetup({
        type: "check_failed",
        errorKind: classifyProviderQuickSetupErrorKind(readableErrorMessage(error)),
        errorMessage: readableErrorMessage(error).slice(0, 320),
      });
    } finally {
      inFlightRef.current = false;
    }
  }, [
    dispatchProviderQuickSetup,
    ensureProviderQuickSetup,
    handleDiscoverProvider,
    providerPresetOptions,
    readableErrorMessage,
    setProviderQuickCredential,
  ]);

  const handleTestAndSaveProviderQuickSetup = useCallback(async (input: {
    provider: ProviderWizardState;
    credentialValue: string;
    modelId: string;
  }): Promise<void> => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    dispatchProviderQuickSetup({ type: "start_check" });
    let tested = false;
    try {
      const upstreamId = input.modelId.trim();
      if (!upstreamId) throw new Error(copy.quickSetupFillModelFirst);
      const provider = await ensureProviderQuickSetup(input);
      const template = providerPresetOptions.find((item) => item.provider_preset_id === provider.templateId);
      const model = await handlePinManualProviderModel(provider.providerId, upstreamId,
        manualModelOverrides(provider, upstreamId, asRecord(template?.default_model)));
      const latest = providerDraftRequestRef.current;
      if (!latest) throw new Error(copy.quickSetupPinFailedMessage);
      // Apply exactly the draft that passed the real call, including pending credentials.
      const snapshot: ConfigApplyDraftOverride = {
        publicConfig: latest.publicConfig, draftMeta: latest.draftMeta, baseHash: latest.baseHash,
      };
      const result = await testConfigLlm({ ...snapshot, modelId: model.modelRef, capability: "text" });
      if (!result.ok) throw new Error(result.message || copy.quickSetupErrorFallback);
      tested = true;
      dispatchProviderQuickSetup({ type: "start_save" });
      const applied = await handleApply(copy.quickSetupApplyBusy, snapshot);
      if (!applied) {
        dispatchProviderQuickSetup({ type: "save_failed", errorKind: "partial_save", errorMessage: copy.quickSetupPartialSaveMessage });
        return;
      }
      createdProviderIdsRef.current.clear();
      await Promise.allSettled([
        queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() }),
      ]);
      setProviderQuickCredential("");
      dispatchProviderQuickSetup({ type: "save_succeeded" });
    } catch (error) {
      const errorMessage = readableErrorMessage(error).slice(0, 320);
      dispatchProviderQuickSetup(tested
        ? { type: "save_failed", errorKind: "partial_save", errorMessage }
        : { type: "check_failed", errorKind: classifyProviderQuickSetupErrorKind(errorMessage), errorMessage });
    } finally {
      inFlightRef.current = false;
    }
  }, [copy, dispatchProviderQuickSetup, ensureProviderQuickSetup, handleApply, handlePinManualProviderModel,
    providerDraftRequestRef, providerPresetOptions, queryClient, readableErrorMessage, setProviderQuickCredential]);

  const handleCancelProviderQuickSetup = useCallback(async (): Promise<boolean> => {
    // Wait for pending creates/tests to settle so cancel cannot leave a late orphan.
    if (inFlightRef.current) return false;
    inFlightRef.current = true;
    try {
      await handleDiscardDraftProviders([...createdProviderIdsRef.current]);
      createdProviderIdsRef.current.clear();
      setProviderQuickCredential("");
      dispatchProviderQuickSetup({ type: "reset" });
      return true;
    } catch (error) {
      const errorMessage = readableErrorMessage(error).slice(0, 320);
      dispatchProviderQuickSetup({ type: "check_failed", errorKind: classifyProviderQuickSetupErrorKind(errorMessage), errorMessage });
      return false;
    } finally {
      inFlightRef.current = false;
    }
  }, [dispatchProviderQuickSetup, handleDiscardDraftProviders, readableErrorMessage, setProviderQuickCredential]);

  const handleConfirmProviderQuickSetup = useCallback(async () => {
    const { provider, selectedModelRef, discoveredModels: quickModels } = providerQuickSetupState;
    const selectedModel = quickModels.find((model) => model.modelRef === selectedModelRef);
    const retrySave = providerQuickSetupState.phase === "error" && ["partial_save", "save"].includes(providerQuickSetupState.errorKind);
    if ((providerQuickSetupState.phase !== "review" && !retrySave) || !selectedModel || !selectedModelRef.startsWith(`${provider.providerId}/`)) {
      return;
    }
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    dispatchProviderQuickSetup({ type: "start_save" });
    let modelAdded = providerQuickSetupState.errorKind === "partial_save";
    try {
      if (providerQuickSetupState.errorKind !== "partial_save") {
        const pinned = await handlePinProviderModels(provider.providerId, [selectedModel]);
        if (!pinned) {
          dispatchProviderQuickSetup({ type: "save_failed", errorKind: "save", errorMessage: copy.quickSetupPinFailedMessage });
          return;
        }
        modelAdded = true;
      }
      const snapshot = providerDraftRequestRef.current;
      const draftOverride: ConfigApplyDraftOverride | undefined = snapshot
        ? {
            publicConfig: snapshot.publicConfig,
            draftMeta: snapshot.draftMeta,
            baseHash: snapshot.baseHash,
          }
        : undefined;
      const applied = await handleApply(copy.quickSetupApplyBusy, draftOverride);
      if (!applied) {
        dispatchProviderQuickSetup({
          type: "save_failed",
          errorKind: "partial_save",
          errorMessage: copy.quickSetupPartialSaveMessage,
        });
        return;
      }
      createdProviderIdsRef.current.clear();
      await queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() });
      setProviderQuickCredential("");
      dispatchProviderQuickSetup({ type: "save_succeeded" });
    } catch (error) {
      dispatchProviderQuickSetup({
        type: "save_failed",
        errorKind: modelAdded ? "partial_save" : "save",
        errorMessage: readableErrorMessage(error).slice(0, 320),
      });
    } finally {
      inFlightRef.current = false;
    }
  }, [
    dispatchProviderQuickSetup,
    handleApply,
    handlePinProviderModels,
    providerDraftRequestRef,
    providerQuickSetupState,
    queryClient,
    readableErrorMessage,
    setProviderQuickCredential,
  ]);

  return {
    handlePrepareProviderQuickSetup,
    handleConfirmProviderQuickSetup,
    handleTestAndSaveProviderQuickSetup,
    handleCancelProviderQuickSetup,
  };
}
