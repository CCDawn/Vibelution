/**
 * Provider quick-setup orchestration (detect + pin + formal apply).
 * Network primitives come from useConfigProviderDraftActions + handleApply.
 */
import { useCallback, type Dispatch } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
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
import { classifyProviderQuickSetupErrorKind } from "./configProviderActionModel";

export type UseConfigProviderQuickSetupActionsOptions = {
  providerQuickSetupState: ProviderQuickSetupState;
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
  handlePinProviderModels: (providerId: string, models: ConfigCatalogModel[]) => Promise<void>;
  handleApply: (pendingLabel?: string, draftOverride?: ConfigApplyDraftOverride) => Promise<boolean>;
  readableErrorMessage: (error: unknown) => string;
};

export function useConfigProviderQuickSetupActions(options: UseConfigProviderQuickSetupActionsOptions) {
  const {
    providerQuickSetupState,
    providerPresetOptions,
    providerDraftRequestRef,
    queryClient,
    dispatchProviderQuickSetup,
    setProviderQuickCredential,
    handleSuggestProviderId,
    handleCreateProvider,
    handleDiscoverProvider,
    handlePinProviderModels,
    handleApply,
    readableErrorMessage,
  } = options;

  const handlePrepareProviderQuickSetup = useCallback(async (input: {
    provider: ProviderWizardState;
    credentialValue: string;
  }) => {
    dispatchProviderQuickSetup({ type: "start_check" });
    try {
      let provider = input.provider;
      if (!provider.providerId) {
        const template = providerPresetOptions.find((item) => item.provider_preset_id === provider.templateId);
        const suggestedProviderId = await handleSuggestProviderId(buildProviderWizardDraft(provider, template?.provider));
        provider = { ...provider, providerId: suggestedProviderId };
        dispatchProviderQuickSetup({ type: "set_provider", provider });
        dispatchProviderQuickSetup({ type: "start_check" });
      }
      await handleCreateProvider(provider, input.credentialValue);
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
      setProviderQuickCredential("");
    } catch (error) {
      dispatchProviderQuickSetup({
        type: "check_failed",
        errorKind: classifyProviderQuickSetupErrorKind(readableErrorMessage(error)),
        errorMessage: readableErrorMessage(error).slice(0, 320),
      });
    }
  }, [
    dispatchProviderQuickSetup,
    handleCreateProvider,
    handleDiscoverProvider,
    handleSuggestProviderId,
    providerPresetOptions,
    readableErrorMessage,
    setProviderQuickCredential,
  ]);

  const handleConfirmProviderQuickSetup = useCallback(async () => {
    const { provider, selectedModelRef, discoveredModels: quickModels } = providerQuickSetupState;
    const selectedModel = quickModels.find((model) => model.modelRef === selectedModelRef);
    if (providerQuickSetupState.phase !== "review" || !selectedModel || !selectedModelRef.startsWith(`${provider.providerId}/`)) {
      return;
    }
    dispatchProviderQuickSetup({ type: "start_save" });
    try {
      await handlePinProviderModels(provider.providerId, [selectedModel]);
      const snapshot = providerDraftRequestRef.current;
      const draftOverride: ConfigApplyDraftOverride | undefined = snapshot
        ? {
            publicConfig: snapshot.publicConfig,
            draftMeta: snapshot.draftMeta,
            baseHash: snapshot.baseHash,
          }
        : undefined;
      const applied = await handleApply("正在应用快速配置…", draftOverride);
      if (!applied) {
        dispatchProviderQuickSetup({
          type: "save_failed",
          errorKind: "partial_save",
          errorMessage: "Provider 草稿已保留，但正式配置尚未应用。请重试确认保存。",
        });
        return;
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() });
      setProviderQuickCredential("");
      dispatchProviderQuickSetup({ type: "save_succeeded" });
    } catch (error) {
      dispatchProviderQuickSetup({
        type: "save_failed",
        errorKind: "partial_save",
        errorMessage: readableErrorMessage(error).slice(0, 320),
      });
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
  };
}
