/**
 * Settings-align wave 3 — provider/model domain state machine for the
 * settings models page, extracted verbatim from ConfigRoute.tsx (zero
 * behavior changes): provider registry/route/credential UI state and their
 * handlers, model connection tests, and capability checks.
 * The route shell keeps quick-setup orchestration, formal apply,
 * navigation, and the composition wrappers that combine this domain with
 * the provider draft-write actions (useConfigProviderDraftActions).
 *
 * Wave 4: the unreachable v1 model-editor leftovers were removed —
 * handleSaveModel / handleDiscoverModels / handleDeleteModel /
 * applyProviderTemplate / applyProviderVendor / applyModelScenario /
 * applyDiscoveredModel / focusModelEditor / handleTestSelectedLibraryModel /
 * keyStateLabel / modelCenterSummary / modelCenterRows /
 * modelCapabilityIssueCount / modelDiscoveryAvailable / canSubmitModelEditor,
 * plus the editor draft state (modelEditor / modelEditorError /
 * selectedModelTestId / discoveredModels / selectedDiscoveredModelId /
 * selectedProviderVendorId / modelEditorExpanded) and the
 * syncModelEditors reset plumbing that only those consumers ever read.
 */

import { useEffect, useMemo, useReducer, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import {
  checkDraftModelCapabilities,
  testConfigLlm,
} from "../../api/config";
import type {
  ConfigDraftMeta,
  ConfigLlmTestResult,
  ConfigWorkspace,
} from "../../api/types";
import type { ConfigProviderRegistryTab, ProviderActionFeedback } from "../ConfigProviderRegistryPanel";
import { type ConfigApplyDraftOverride } from "./configApplyModel";
import {
  type ProviderRouteImpact,
  type ProviderRoutePreview,
} from "./useConfigProviderDraftActions";
import type { ConfigCopy } from "./configCopy";
import { formatConfigCopy } from "./configCopy";
import { resolveImageInputCapabilityStatus, type PublicConfigShape } from "../configRouteLogic";
import {
  deriveProviderRegistryRows,
  initialProviderWizardState,
  providerWizardReducer,
} from "../configProviderLogic";

type NoticeTone = "neutral" | "success" | "error";

type NoticeState = { tone: NoticeTone; text: string };

type ProviderDraftRequestSnapshot = {
  publicConfig: PublicConfigShape;
  draftMeta: ConfigDraftMeta;
  baseHash: string;
  modelCatalog: ConfigWorkspace["modelCatalog"];
};

export type UseConfigProviderModelDomainOptions = {
  workspaceQuery: { refetch: () => Promise<{ data?: ConfigWorkspace }> };
  providerRows: ReturnType<typeof deriveProviderRegistryRows>;
  draftMeta: ConfigDraftMeta;
  baseHash: string;
  structuredActionsDisabled: boolean;
  setBusyAction: (value: string) => void;
  setNotice: Dispatch<SetStateAction<NoticeState>>;
  markError: (error: unknown) => string;
  requireDraft: () => PublicConfigShape;
  syncWorkspace: (workspace: ConfigWorkspace, tone?: NoticeTone, options?: { resetBase?: boolean }) => void;
  readableErrorMessage: (error: unknown) => string;
  handleApply: (pendingLabel?: string, draftOverride?: ConfigApplyDraftOverride) => Promise<boolean>;
  providerDraftRequestRef: MutableRefObject<ProviderDraftRequestSnapshot | null>;
  copy: ConfigCopy;
};

export function useConfigProviderModelDomain(options: UseConfigProviderModelDomainOptions) {
  const {
    workspaceQuery,
    providerRows,
    draftMeta,
    baseHash,
    structuredActionsDisabled,
    setBusyAction,
    setNotice,
    markError,
    requireDraft,
    syncWorkspace,
    readableErrorMessage,
    handleApply,
    providerDraftRequestRef,
    copy,
  } = options;
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [selectedProviderTab, setSelectedProviderTab] = useState<ConfigProviderRegistryTab>("connection");

  const [providerWizardState, dispatchProviderWizard] = useReducer(providerWizardReducer, undefined, initialProviderWizardState);

  const [routePreview, setRoutePreview] = useState<ProviderRoutePreview | null>(null);
  const [routeEditProviderId, setRouteEditProviderId] = useState("");
  const [routeEditProvider, setRouteEditProvider] = useState<Record<string, unknown>>({});
  const [providerCredentialEditId, setProviderCredentialEditId] = useState("");
  const [providerCredentialValue, setProviderCredentialValue] = useState("");
  const [providerActionError, setProviderActionError] = useState("");
  const [providerActionFeedback, setProviderActionFeedback] = useState<ProviderActionFeedback>(null);

  const liveReferenceCountByModelRef = useMemo(
    () => Object.fromEntries(
      (routePreview?.impactedRefs ?? [])
        .filter((impact): impact is ProviderRouteImpact & { modelRef: string } => Boolean(impact.modelRef))
        .map((impact) => [impact.modelRef, impact.liveReferenceCount ?? 0]),
    ),
    [routePreview],
  );

  useEffect(() => {
    if (!providerRows.length) {
      if (selectedProviderId) setSelectedProviderId("");
      return;
    }
    if (!selectedProviderId || !providerRows.some((row) => row.providerId === selectedProviderId)) {
      setSelectedProviderId(providerRows[0].providerId);
    }
  }, [providerRows, selectedProviderId]);

  useEffect(() => {
    if (providerCredentialEditId && providerCredentialEditId !== selectedProviderId) {
      setProviderCredentialEditId("");
      setProviderCredentialValue("");
    }
  }, [providerCredentialEditId, selectedProviderId]);

  const credentialProvider = providerRows.find((row) => row.providerId === providerCredentialEditId);

  async function handleTestProviderModel(modelRef: string) {
    if (structuredActionsDisabled) return;
    setBusyAction(formatConfigCopy(copy.testModelBusyTemplate, { ref: modelRef }));
    setProviderActionError("");
    setProviderActionFeedback({
      kind: "discover",
      providerId: modelRef.includes("/") ? modelRef.slice(0, modelRef.indexOf("/")) : selectedProviderId,
      phase: "busy",
      message: formatConfigCopy(copy.testRealCallTemplate, { ref: modelRef }),
    });
    try {
      const result = await testConfigLlm({
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        modelId: modelRef,
        capability: "text",
      });
      const noticeText = formatTestNotice(result);
      setNotice({ tone: result.ok ? "success" : "error", text: noticeText });
      setProviderActionFeedback({
        kind: "discover",
        providerId: result.provider_id || (modelRef.includes("/") ? modelRef.slice(0, modelRef.indexOf("/")) : selectedProviderId),
        phase: result.ok ? "success" : "error",
        message: result.ok
          ? formatConfigCopy(copy.testCallOkTemplate, { ref: modelRef })
            + (result.verification_persisted ? copy.testCallPersistedSuffix : "")
          : formatConfigCopy(copy.testCallFailedTemplate, {
              ref: modelRef,
              reason: result.message || result.verification_error_type || "unknown",
            }) + (result.verification_http_status ? ` · HTTP ${result.verification_http_status}` : ""),
      });
      // Reload catalog so「真实调用」column picks up persisted verification (draft or saved).
      const refreshed = await workspaceQuery.refetch();
      if (refreshed.data) {
        syncWorkspace(refreshed.data, result.ok ? "success" : "error", { resetBase: false });
        // Keep the test notice after syncWorkspace overwrites message from workspace.
        setNotice({ tone: result.ok ? "success" : "error", text: noticeText });
      }
    } catch (error) {
      const message = readableErrorMessage(error).slice(0, 480);
      setProviderActionError(message);
      setProviderActionFeedback({
        kind: "discover",
        providerId: modelRef.includes("/") ? modelRef.slice(0, modelRef.indexOf("/")) : selectedProviderId,
        phase: "error",
        message: formatConfigCopy(copy.testRequestFailedTemplate, { ref: modelRef, message }),
      });
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  function snapshotDraftOverride(): ConfigApplyDraftOverride | undefined {
    const snapshot = providerDraftRequestRef.current;
    if (!snapshot) return undefined;
    return {
      publicConfig: snapshot.publicConfig,
      draftMeta: snapshot.draftMeta,
      baseHash: snapshot.baseHash,
    };
  }

  async function persistImmediateDraft(pendingLabel: string): Promise<boolean> {
    return handleApply(pendingLabel, snapshotDraftOverride());
  }

  async function handleCheckModelImageCapabilities(modelIds: string[] = []) {
    if (structuredActionsDisabled) {
      return;
    }
    setBusyAction(copy.imageCapabilityCheckPending);
    try {
      const response = await checkDraftModelCapabilities({
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        modelIds,
      });
      syncWorkspace(response, "success", { resetBase: false });
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  function testScopeLabel(scope: ConfigLlmTestResult["config_scope"]) {
    return scope === "saved" ? copy.testScopeSaved : copy.testScopeDraft;
  }

  function formatTestKeyDetail(result: ConfigLlmTestResult) {
    if (!result.requires_api_key) {
      return `${copy.testKeyNotRequired}${result.api_key_source ? ` (${copy.testKeySourceLabel}: ${result.api_key_source})` : ""}`;
    }
    return result.api_key_source || "-";
  }

  function formatTestNotice(result: ConfigLlmTestResult) {
    const detailParts = [
      testScopeLabel(result.config_scope),
      `${copy.testRouteLabel}: ${[result.provider_kind, result.base_url].filter(Boolean).join(" · ") || "-"}`,
      `${copy.testRuntimeLabel}: ${[result.transport, result.contract].filter(Boolean).join(" · ") || "-"}`,
      `${copy.testKeyLabel}: ${formatTestKeyDetail(result)}`,
    ];
    if (result.capability === "image_input") {
      detailParts.push(`${copy.testCapabilityLabel}: ${imageInputStatusLabel(result)}`);
    }
    return `${result.model_id} / ${result.model}: ${result.message} [${detailParts.join(" | ")}]`;
  }

  function imageInputStatusFromResult(result: ConfigLlmTestResult): "supported" | "unsupported" | "unknown" {
    return resolveImageInputCapabilityStatus({
      supportsImageInput: result.supports_image_input,
      capabilityStatus: result.capability_status,
    });
  }

  function imageInputStatusLabel(
    result: ConfigLlmTestResult | { status: "supported" | "unsupported" | "unknown" | "failed"; checkedAt?: string } | null | undefined,
  ) {
    const status = !result
      ? "unknown"
      : "ok" in result
        ? imageInputStatusFromResult(result)
        : result.status;
    switch (status) {
      case "supported":
        return copy.imageInputStatusSupported;
      case "unsupported":
        return copy.imageInputStatusUnsupported;
      case "failed":
        return copy.imageInputStatusFailed;
      default:
        return copy.imageInputStatusUnknown;
    }
  }

  return {
    // state read by the route shell
    selectedProviderId,
    selectedProviderTab,
    providerWizardState,
    routePreview,
    routeEditProviderId,
    routeEditProvider,
    providerCredentialEditId,
    providerCredentialValue,
    providerActionError,
    providerActionFeedback,
    credentialProvider,
    liveReferenceCountByModelRef,
    // setters consumed by route wrappers, provider draft actions, and JSX
    setSelectedProviderId,
    setSelectedProviderTab,
    setProviderCredentialEditId,
    setProviderCredentialValue,
    setRouteEditProviderId,
    setRouteEditProvider,
    setRoutePreview,
    setProviderActionError,
    setProviderActionFeedback,
    dispatchProviderWizard,
    // handlers consumed by the route shell
    persistImmediateDraft,
    handleTestProviderModel,
    handleCheckModelImageCapabilities,
  };
}
