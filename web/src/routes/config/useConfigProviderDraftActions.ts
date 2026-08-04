/**
 * Config provider draft write actions (create / discover / pin / suggest / unpin).
 * Route still owns workspace sync, notices, and remaining credential/route handlers.
 */
import { useCallback, type Dispatch, type MutableRefObject } from "react";

import { fetchJson } from "../../api/client";
import type {
  ConfigCatalogModel,
  ConfigDraftMeta,
  ConfigWorkspace,
} from "../../api/types";
import { asRecord, filterAlreadyPinnedModels } from "../configRouteLogic";
import type { PublicConfigShape } from "../configRouteLogic";
import {
  buildProviderWizardDraft,
  type ProviderWizardState,
} from "../configProviderLogic";
import type { ProviderActionFeedback } from "../ConfigProviderRegistryPanel";
import {
  formatProviderPinBusyMessage,
  formatProviderPinErrorMessage,
  formatProviderPinSuccessMessage,
  isProviderModelAlreadyPinnedErrorMessage,
} from "./configProviderActionModel";

type NoticeTone = "neutral" | "success" | "error";

type ProviderDraftRequestSnapshot = {
  publicConfig: PublicConfigShape;
  draftMeta: ConfigDraftMeta;
  baseHash: string;
  modelCatalog?: ConfigWorkspace["modelCatalog"];
};

export type UseConfigProviderDraftActionsOptions = {
  baseHash: string;
  draftConfig: PublicConfigShape | null | undefined;
  draftMeta: ConfigDraftMeta;
  loadFailedMessage: string;
  editBaselineRef: MutableRefObject<{ baseConfig: PublicConfigShape | null; baseHash: string }>;
  providerDraftRequestRef: MutableRefObject<ProviderDraftRequestSnapshot | null>;
  activeWorkspace: ConfigWorkspace | null | undefined;
  providerPresetOptions: Array<{ provider_preset_id: string; provider?: Record<string, unknown> }>;
  requireDraft: () => PublicConfigShape;
  syncWorkspace: (workspace: ConfigWorkspace, tone?: NoticeTone, options?: { resetBase?: boolean }) => void;
  markError: (error: unknown) => string;
  readableErrorMessage: (error: unknown) => string;
  providerDiscoveryFailureDetail: (error: unknown) => { providerId: string; reasonCode: string; retryable: boolean } | null;
  providerDiscoveryFailureMessage: (detail: { providerId: string; reasonCode: string; retryable: boolean } | null) => string;
  setBusyAction: (value: string) => void;
  setProviderActionError: (value: string) => void;
  setProviderActionFeedback: (value: ProviderActionFeedback) => void;
  setNotice: (value: { tone: NoticeTone; text: string }) => void;
  setSelectedProviderId: (value: string) => void;
  setSelectedProviderTab: (value: "models" | "settings" | string) => void;
  dispatchProviderWizard: Dispatch<{ type: "pin_succeeded"; modelRef: string } | { type: string; [key: string]: unknown }>;
  requestJson?: <T>(url: string, body?: unknown, method?: string) => Promise<T>;
};

async function defaultRequestJson<T>(url: string, body?: unknown, method = "POST"): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: body == null ? undefined : JSON.stringify(body),
  });
}

export function useConfigProviderDraftActions(options: UseConfigProviderDraftActionsOptions) {
  const {
    baseHash,
    draftConfig,
    draftMeta,
    loadFailedMessage,
    editBaselineRef,
    providerDraftRequestRef,
    activeWorkspace,
    providerPresetOptions,
    requireDraft,
    syncWorkspace,
    markError,
    readableErrorMessage,
    providerDiscoveryFailureDetail,
    providerDiscoveryFailureMessage,
    setBusyAction,
    setProviderActionError,
    setProviderActionFeedback,
    setNotice,
    setSelectedProviderId,
    setSelectedProviderTab,
    dispatchProviderWizard,
    requestJson = defaultRequestJson,
  } = options;

  const buildProviderDraftRequest = useCallback((extra: Record<string, unknown>) => {
    const baselineHash = editBaselineRef.current.baseHash || baseHash;
    const latestDraft = providerDraftRequestRef.current
      ?? (draftConfig ? { publicConfig: draftConfig, draftMeta, baseHash: baselineHash } : null);
    if (!latestDraft) {
      throw new Error(loadFailedMessage);
    }
    return {
      publicConfig: latestDraft.publicConfig,
      draftMeta: latestDraft.draftMeta,
      // Always prefer the frozen edit baseline hash over any draft response hash.
      baseHash: editBaselineRef.current.baseHash || latestDraft.baseHash || baselineHash,
      ...extra,
    };
  }, [baseHash, draftConfig, draftMeta, editBaselineRef, loadFailedMessage, providerDraftRequestRef]);

  const handleDiscoverProvider = useCallback(async (providerId: string, credentialValue = ""): Promise<ConfigCatalogModel[]> => {
    setBusyAction("正在发现 Provider 模型…");
    setProviderActionError("");
    setProviderActionFeedback({ kind: "discover", providerId, phase: "busy", message: "正在发现模型…" });
    try {
      const response = await requestJson<ConfigWorkspace>(
        `/api/config/draft/providers/${encodeURIComponent(providerId)}/discover`,
        buildProviderDraftRequest({ providerId, credentialValue }),
      );
      syncWorkspace(response, "success", { resetBase: false });
      const models = Object.values(response.modelCatalog.providers[providerId]?.models ?? {});
      setProviderActionFeedback({
        kind: "discover",
        providerId,
        phase: "success",
        message: models.length > 0 ? `发现 ${models.length} 个模型` : "目录已刷新",
      });
      return models;
    } catch (error) {
      const detail = providerDiscoveryFailureDetail(error);
      const message = providerDiscoveryFailureMessage(detail).slice(0, 480);
      try {
        const refreshed = await requestJson<ConfigWorkspace>("/api/config/workspace", undefined, "GET");
        // Full reload: disk is the new baseline after a failed discover reconciliation.
        syncWorkspace(refreshed, "neutral", { resetBase: true });
      } catch {
        // Preserve the scoped discovery failure; a workspace refresh is only a best-effort status reconciliation.
      }
      setProviderActionFeedback({ kind: "discover", providerId, phase: "error", message });
      throw new Error(message);
    } finally {
      setBusyAction("");
    }
  }, [
    buildProviderDraftRequest,
    providerDiscoveryFailureDetail,
    providerDiscoveryFailureMessage,
    requestJson,
    setBusyAction,
    setProviderActionError,
    setProviderActionFeedback,
    syncWorkspace,
  ]);

  const handleSuggestProviderId = useCallback(async (provider: Record<string, unknown>): Promise<string> => {
    const response = await requestJson<{ suggestedProviderId: string }>(
      "/api/config/draft/providers/id-suggestion",
      buildProviderDraftRequest({ provider }),
    );
    return response.suggestedProviderId;
  }, [buildProviderDraftRequest, requestJson]);

  const handleCreateProvider = useCallback(async (state: ProviderWizardState, credentialValue: string): Promise<void> => {
    setBusyAction("正在创建 Provider 草稿…");
    setProviderActionError("");
    const template = providerPresetOptions.find((item) => item.provider_preset_id === state.templateId);
    const provider = buildProviderWizardDraft(state, template?.provider);
    try {
      const response = await requestJson<ConfigWorkspace>(
        "/api/config/draft/providers",
        buildProviderDraftRequest({ providerId: state.providerId, provider, credentialValue }),
      );
      syncWorkspace(response, "success", { resetBase: false });
      setSelectedProviderId(state.providerId);
    } catch (error) {
      const message = readableErrorMessage(error).slice(0, 480);
      setProviderActionError(message);
      markError(error);
      throw error;
    } finally {
      setBusyAction("");
    }
  }, [
    buildProviderDraftRequest,
    markError,
    providerPresetOptions,
    readableErrorMessage,
    requestJson,
    setBusyAction,
    setProviderActionError,
    setSelectedProviderId,
    syncWorkspace,
  ]);

  const handlePinProviderModels = useCallback(async (providerId: string, models: ConfigCatalogModel[]): Promise<void> => {
    const report = (phase: "busy" | "success" | "error", message: string) => {
      setProviderActionFeedback({ kind: "pin", providerId, phase, message });
      setNotice({
        tone: phase === "error" ? "error" : phase === "success" ? "success" : "neutral",
        text: message,
      });
      if (phase === "error") {
        setProviderActionError(message);
      } else {
        setProviderActionError("");
      }
    };

    if (!models.length) {
      report("error", "没有可固定的模型。请先点「发现模型」，确认列表里有「已发现」状态的行。");
      return;
    }

    const pinBusy = formatProviderPinBusyMessage({
      modelCount: models.length,
      firstModelRef: models[0]?.modelRef,
    });
    setBusyAction(pinBusy);
    report("busy", pinBusy);

    const latestDraft = providerDraftRequestRef.current;
    let currentConfig = latestDraft?.publicConfig ?? requireDraft();
    let currentMeta = latestDraft?.draftMeta ?? draftMeta;
    // Pin must keep the frozen external baseline hash for the whole multi-model loop.
    let currentBaseHash = editBaselineRef.current.baseHash || latestDraft?.baseHash || baseHash;

    const catalogModels =
      activeWorkspace?.modelCatalog?.providers?.[providerId]?.models
      ?? latestDraft?.modelCatalog?.providers?.[providerId]?.models
      ?? {};
    const pinnedModelRefs = new Set(
      Object.values(catalogModels)
        .filter((model) => model.availability === "pinned" || model.availability === "missing_remote")
        .map((model) => model.modelRef),
    );
    const draftProvider = asRecord(asRecord(asRecord(currentConfig.llm).providers)[providerId]);
    const draftModels = asRecord(draftProvider.models);
    for (const modelKey of Object.keys(draftModels)) {
      pinnedModelRefs.add(`${providerId}/${modelKey}`);
    }

    const pendingModels = filterAlreadyPinnedModels(models, pinnedModelRefs);
    const skippedExisting = models.length - pendingModels.length;
    if (!pendingModels.length) {
      setBusyAction("");
      setSelectedProviderId(providerId);
      setSelectedProviderTab("models");
      report("success", "所选模型均已固定。已切换到「已固定」列表。");
      return;
    }

    let pinnedCount = 0;
    let skippedRuntime = 0;
    try {
      for (const model of pendingModels) {
        const modelKey = String(model.modelKey || model.upstreamId || "").trim();
        const upstreamId = String(model.upstreamId || model.modelKey || "").trim();
        if (!modelKey || !upstreamId) {
          skippedRuntime += 1;
          continue;
        }
        try {
          const response = await requestJson<ConfigWorkspace>(
            `/api/config/draft/providers/${encodeURIComponent(providerId)}/models`,
            {
              publicConfig: currentConfig,
              draftMeta: currentMeta,
              baseHash: currentBaseHash,
              providerId,
              upstreamId,
              modelKey,
              label: model.label || upstreamId,
              overrides: {},
            },
          );
          currentConfig = response.publicConfig;
          currentMeta = response.draftMeta;
          // Do not adopt response.hash (draft). Baseline hash stays frozen until apply/reload.
          currentBaseHash = editBaselineRef.current.baseHash || response.baseHash || currentBaseHash;
          // Keep ref in sync so subsequent pins see the new draft pin set.
          providerDraftRequestRef.current = {
            publicConfig: response.publicConfig,
            draftMeta: response.draftMeta,
            baseHash: currentBaseHash,
            modelCatalog: response.modelCatalog,
          };
          syncWorkspace(response, "success", { resetBase: false });
          dispatchProviderWizard({ type: "pin_succeeded", modelRef: model.modelRef || `${providerId}/${modelKey}` });
          pinnedCount += 1;
          pinnedModelRefs.add(model.modelRef || `${providerId}/${modelKey}`);
          if (pendingModels.length > 1) {
            report("busy", formatProviderPinBusyMessage({
              modelCount: pendingModels.length,
              completed: pinnedCount,
              total: pendingModels.length,
            }));
          }
        } catch (error) {
          const message = readableErrorMessage(error);
          if (isProviderModelAlreadyPinnedErrorMessage(message)) {
            skippedRuntime += 1;
            pinnedModelRefs.add(model.modelRef || `${providerId}/${modelKey}`);
            continue;
          }
          throw error;
        }
      }
      setSelectedProviderId(providerId);
      setSelectedProviderTab("models");
      const skippedTotal = skippedExisting + skippedRuntime;
      report(
        "success",
        formatProviderPinSuccessMessage({ pinnedCount, skippedTotal }),
      );
    } catch (error) {
      const message = readableErrorMessage(error).slice(0, 480);
      markError(error);
      report(
        "error",
        formatProviderPinErrorMessage({ pinnedCount, errorMessage: message }),
      );
    } finally {
      setBusyAction("");
    }
  }, [
    activeWorkspace,
    baseHash,
    dispatchProviderWizard,
    draftMeta,
    editBaselineRef,
    markError,
    providerDraftRequestRef,
    readableErrorMessage,
    requestJson,
    requireDraft,
    setBusyAction,
    setNotice,
    setProviderActionError,
    setProviderActionFeedback,
    setSelectedProviderId,
    setSelectedProviderTab,
    syncWorkspace,
  ]);

  const handleUnpinProviderModel = useCallback(async (modelRef: string, resolveUpstreamId: (modelRef: string) => string) => {
    const separator = modelRef.indexOf("/");
    if (separator <= 0) return;
    const providerId = modelRef.slice(0, separator);
    const modelKey = modelRef.slice(separator + 1);
    setBusyAction("正在取消固定模型…");
    try {
      const response = await requestJson<ConfigWorkspace>(
        `/api/config/draft/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelKey)}`,
        buildProviderDraftRequest({ providerId, upstreamId: resolveUpstreamId(modelRef), modelKey }),
        "DELETE",
      );
      syncWorkspace(response, "success", { resetBase: false });
    } catch (error) {
      setProviderActionError(readableErrorMessage(error).slice(0, 480));
      markError(error);
    } finally {
      setBusyAction("");
    }
  }, [
    buildProviderDraftRequest,
    markError,
    readableErrorMessage,
    requestJson,
    setBusyAction,
    setProviderActionError,
    syncWorkspace,
  ]);

  return {
    buildProviderDraftRequest,
    handleDiscoverProvider,
    handleSuggestProviderId,
    handleCreateProvider,
    handlePinProviderModels,
    handleUnpinProviderModel,
  };
}
