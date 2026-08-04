/**
 * Config provider draft write actions:
 * create / discover / pin / suggest / unpin / delete / credential / context window / route preview.
 * Route still owns quick-setup orchestration, LLM test, migration, and formal apply.
 */
import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import type {
  ConfigCatalogModel,
  ConfigDraftMeta,
  ConfigWorkspace,
} from "../../api/types";
import { asRecord, clonePublicConfig } from "../configRouteLogic";
import type { PublicConfigShape } from "../configRouteLogic";
import {
  buildProviderWizardDraft,
  filterAlreadyPinnedModels,
  type ProviderWizardAction,
  type ProviderWizardState,
} from "../configProviderLogic";
import type {
  ConfigProviderRegistryTab,
  ProviderActionFeedback,
} from "../ConfigProviderRegistryPanel";
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

export type ProviderRouteImpact = {
  modelRef?: string;
  liveReferenceCount?: number;
  historicalReferenceCount?: number;
};

export type ProviderRoutePreview = {
  providerId: string;
  routeChanged: boolean;
  routePreviewToken: string;
  modelRefs: string[];
  impactedRefs: ProviderRouteImpact[];
  proposedProvider: Record<string, unknown>;
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
  setProviderActionFeedback: (value: ProviderActionFeedback | null) => void;
  setNotice: (value: { tone: NoticeTone; text: string }) => void;
  setSelectedProviderId: (value: string) => void;
  setSelectedProviderTab: Dispatch<SetStateAction<ConfigProviderRegistryTab>>;
  setProviderCredentialEditId: (value: string) => void;
  setProviderCredentialValue: (value: string) => void;
  setRouteEditProviderId: (value: string) => void;
  setRouteEditProvider: (value: Record<string, unknown>) => void;
  setRoutePreview: Dispatch<SetStateAction<ProviderRoutePreview | null>>;
  dispatchProviderWizard: Dispatch<ProviderWizardAction>;
  requestJson?: <T>(url: string, body?: unknown, method?: string) => Promise<T>;
  confirmDeleteProvider?: (providerId: string) => boolean;
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
    setProviderCredentialEditId,
    setProviderCredentialValue,
    setRouteEditProviderId,
    setRouteEditProvider,
    setRoutePreview,
    dispatchProviderWizard,
    requestJson = defaultRequestJson,
    confirmDeleteProvider = (providerId: string) => (
      typeof window === "undefined"
      || window.confirm(`删除 Provider ${providerId}？此操作只允许在没有固定模型时继续。`)
    ),
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

  const handleDeleteProvider = useCallback(async (providerId: string) => {
    if (!confirmDeleteProvider(providerId)) return;
    setBusyAction("正在删除 Provider…");
    try {
      const provider = asRecord(asRecord(asRecord(requireDraft().llm).providers)[providerId]);
      const response = await requestJson<ConfigWorkspace>(
        `/api/config/draft/providers/${encodeURIComponent(providerId)}`,
        buildProviderDraftRequest({ providerId, provider }),
        "DELETE",
      );
      syncWorkspace(response, "success", { resetBase: false });
      setSelectedProviderId("");
    } catch (error) {
      setProviderActionError(readableErrorMessage(error).slice(0, 480));
      markError(error);
    } finally {
      setBusyAction("");
    }
  }, [
    buildProviderDraftRequest,
    confirmDeleteProvider,
    markError,
    readableErrorMessage,
    requestJson,
    requireDraft,
    setBusyAction,
    setProviderActionError,
    setSelectedProviderId,
    syncWorkspace,
  ]);

  const handleUpdateProviderCredential = useCallback(async (providerId: string, credentialValue: string) => {
    if (!credentialValue.trim()) return;
    setBusyAction("正在更新 Provider API Key 草稿…");
    setProviderActionError("");
    setProviderActionFeedback({ kind: "credential", providerId, phase: "busy", message: "正在保存 API Key…" });
    try {
      const provider = asRecord(asRecord(asRecord(requireDraft().llm).providers)[providerId]);
      const response = await requestJson<ConfigWorkspace>(
        `/api/config/draft/providers/${encodeURIComponent(providerId)}`,
        buildProviderDraftRequest({ providerId, provider, credentialValue }),
        "PUT",
      );
      syncWorkspace(response, "success", { resetBase: false });
      setProviderCredentialEditId("");
      setProviderCredentialValue("");
      setProviderActionFeedback({ kind: "credential", providerId, phase: "success", message: "API Key 已更新到草稿" });
    } catch (error) {
      const message = readableErrorMessage(error).slice(0, 480);
      setProviderActionFeedback({ kind: "credential", providerId, phase: "error", message });
      markError(error);
    } finally {
      setBusyAction("");
    }
  }, [
    buildProviderDraftRequest,
    markError,
    readableErrorMessage,
    requestJson,
    requireDraft,
    setBusyAction,
    setProviderActionError,
    setProviderActionFeedback,
    setProviderCredentialEditId,
    setProviderCredentialValue,
    syncWorkspace,
  ]);

  const handleUpdateProviderContextWindow = useCallback(async (providerId: string, contextWindow: number | null) => {
    setBusyAction("正在更新上下文窗口草稿…");
    setProviderActionError("");
    setProviderActionFeedback({
      kind: "credential",
      providerId,
      phase: "busy",
      message: "正在保存上下文窗口…",
    });
    try {
      const provider = clonePublicConfig(asRecord(asRecord(asRecord(requireDraft().llm).providers)[providerId]));
      if (contextWindow && contextWindow > 0) {
        provider.context_window = contextWindow;
      } else {
        provider.context_window = null;
      }
      const response = await requestJson<ConfigWorkspace>(
        `/api/config/draft/providers/${encodeURIComponent(providerId)}`,
        buildProviderDraftRequest({ providerId, provider }),
        "PUT",
      );
      syncWorkspace(response, "success", { resetBase: false });
      setProviderActionFeedback({
        kind: "credential",
        providerId,
        phase: "success",
        message: contextWindow && contextWindow > 0
          ? `上下文窗口已设为 ${contextWindow}（草稿）；请点右上角保存到外部配置`
          : "已清除 Provider 上下文窗口草稿；请点右上角保存到外部配置",
      });
    } catch (error) {
      const message = readableErrorMessage(error).slice(0, 480);
      setProviderActionFeedback({ kind: "credential", providerId, phase: "error", message });
      setProviderActionError(message);
      markError(error);
    } finally {
      setBusyAction("");
    }
  }, [
    buildProviderDraftRequest,
    markError,
    readableErrorMessage,
    requestJson,
    requireDraft,
    setBusyAction,
    setProviderActionError,
    setProviderActionFeedback,
    syncWorkspace,
  ]);

  const handleBeginProviderRouteEdit = useCallback((providerId: string) => {
    const provider = clonePublicConfig(asRecord(asRecord(asRecord(requireDraft().llm).providers)[providerId]));
    setRouteEditProviderId(providerId);
    setRouteEditProvider(provider);
    setRoutePreview(null);
    setProviderActionFeedback(null);
  }, [requireDraft, setProviderActionFeedback, setRouteEditProvider, setRouteEditProviderId, setRoutePreview]);

  const handlePreviewProviderRoute = useCallback(async (providerId: string, provider: Record<string, unknown>) => {
    setBusyAction("正在预览路由影响…");
    setProviderActionError("");
    setProviderActionFeedback({ kind: "route", providerId, phase: "busy", message: "正在生成路由预览…" });
    try {
      const preview = await requestJson<Omit<ProviderRoutePreview, "proposedProvider">>(
        `/api/config/draft/providers/${encodeURIComponent(providerId)}/route-preview`,
        buildProviderDraftRequest({ providerId, provider }),
      );
      setRoutePreview({ ...preview, proposedProvider: provider });
      setProviderActionFeedback({
        kind: "route",
        providerId,
        phase: "success",
        message: preview.routeChanged ? "路由预览已生成" : "当前路由没有变化",
      });
    } catch (error) {
      const message = readableErrorMessage(error).slice(0, 480);
      setProviderActionFeedback({ kind: "route", providerId, phase: "error", message });
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
    setProviderActionFeedback,
    setRoutePreview,
  ]);

  const handleApplyProviderRoutePreview = useCallback(async (routePreview: ProviderRoutePreview | null) => {
    if (!routePreview?.routeChanged || !routePreview.routePreviewToken) return;
    const providerId = routePreview.providerId;
    setBusyAction("正在更新 Provider 路由…");
    setProviderActionError("");
    setProviderActionFeedback({ kind: "route", providerId, phase: "busy", message: "正在更新 Provider 路由…" });
    try {
      const response = await requestJson<ConfigWorkspace>(
        `/api/config/draft/providers/${encodeURIComponent(routePreview.providerId)}`,
        buildProviderDraftRequest({
          providerId: routePreview.providerId,
          provider: routePreview.proposedProvider,
          routePreviewToken: routePreview.routePreviewToken,
        }),
        "PUT",
      );
      syncWorkspace(response, "success", { resetBase: false });
      setRoutePreview(null);
      setRouteEditProviderId("");
      setRouteEditProvider({});
      setProviderActionFeedback({ kind: "route", providerId, phase: "success", message: "Provider 路由已更新到草稿" });
    } catch (error) {
      const message = readableErrorMessage(error).slice(0, 480);
      setProviderActionFeedback({ kind: "route", providerId, phase: "error", message });
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
    setProviderActionFeedback,
    setRouteEditProvider,
    setRouteEditProviderId,
    setRoutePreview,
    syncWorkspace,
  ]);

  return {
    buildProviderDraftRequest,
    handleDiscoverProvider,
    handleSuggestProviderId,
    handleCreateProvider,
    handlePinProviderModels,
    handleUnpinProviderModel,
    handleDeleteProvider,
    handleUpdateProviderCredential,
    handleUpdateProviderContextWindow,
    handleBeginProviderRouteEdit,
    handlePreviewProviderRoute,
    handleApplyProviderRoutePreview,
  };
}
