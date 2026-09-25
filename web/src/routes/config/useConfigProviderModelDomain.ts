/**
 * Settings-align wave 3 — provider/model domain state machine for the
 * settings models page, extracted verbatim from ConfigRoute.tsx (zero
 * behavior changes): provider registry/route/credential UI state, model
 * editor drafts + discovery, model center summaries, and their handlers.
 * The route shell keeps quick-setup orchestration, formal apply,
 * navigation, and the composition wrappers that combine this domain with
 * the provider draft-write actions (useConfigProviderDraftActions).
 */

import { useEffect, useMemo, useReducer, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import {
  addDraftModel,
  checkDraftModelCapabilities,
  deleteDraftModel,
  discoverConfigModels,
  testConfigLlm,
  updateDraftModel,
} from "../../api/config";
import type {
  ConfigDiscoveredModel,
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
import {
  buildModelDetailsDraft,
  buildModelDetailsPayload,
  buildProviderDraft,
  buildProviderPayload,
  emptyModelDetailsDraft,
  emptyModelEditorState,
  emptyProviderDraft,
  readableErrorMessage,
  type ModelEditorState,
} from "./configEditorModel";
import {
  asRecord,
  canDiscoverModelsForProvider,
  countModelCenterHealthIssues,
  defaultModelApiKeyEnv,
  deriveModelCenterInventoryRows,
  deriveModelCenterSummary,
  groupProviderPresetsByVendor,
  modelLibraryIdFromParts,
  resolveImageInputCapabilityStatus,
  selectModelScenarioProviderPresetId,
  type ModelScenarioId,
  type PublicConfigShape,
  uniqueModelLibraryId,
} from "../configRouteLogic";
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
  workspace: ConfigWorkspace | null | undefined;
  modelOptions: ConfigWorkspace["modelOptions"];
  providerRows: ReturnType<typeof deriveProviderRegistryRows>;
  providerPresetOptions: ConfigWorkspace["providerPresetOptions"];
  draftConfig: PublicConfigShape | null;
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
  modelEditorRef: MutableRefObject<HTMLDivElement | null>;
  copy: ConfigCopy;
};

export function useConfigProviderModelDomain(options: UseConfigProviderModelDomainOptions) {
  const {
    workspaceQuery,
    workspace,
    modelOptions,
    providerRows,
    providerPresetOptions,
    draftConfig,
    draftMeta,
    baseHash,
    structuredActionsDisabled,
    setBusyAction,
    setNotice,
    markError,
    requireDraft,
    syncWorkspace,
    handleApply,
    providerDraftRequestRef,
    modelEditorRef,
    copy,
  } = options;
  const [modelEditor, setModelEditor] = useState<ModelEditorState>(emptyModelEditorState());
  const [selectedModelTestId, setSelectedModelTestId] = useState("");
  const [modelEditorError, setModelEditorError] = useState("");
  const [modelDiscoveryError, setModelDiscoveryError] = useState("");
  const [discoveredModels, setDiscoveredModels] = useState<ConfigDiscoveredModel[]>([]);
  const [selectedDiscoveredModelId, setSelectedDiscoveredModelId] = useState("");
  const [selectedProviderVendorId, setSelectedProviderVendorId] = useState("");
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
  const [modelEditorExpanded, setModelEditorExpanded] = useState(false);

  const liveReferenceCountByModelRef = useMemo(
    () => Object.fromEntries(
      (routePreview?.impactedRefs ?? [])
        .filter((impact): impact is ProviderRouteImpact & { modelRef: string } => Boolean(impact.modelRef))
        .map((impact) => [impact.modelRef, impact.liveReferenceCount ?? 0]),
    ),
    [routePreview],
  );
  const providerVendorGroups = useMemo(() => groupProviderPresetsByVendor(providerPresetOptions), [providerPresetOptions]);
  const selectedProviderVendorTemplates = useMemo(
    () => providerVendorGroups.find((group) => group.id === selectedProviderVendorId)?.templates ?? [],
    [providerVendorGroups, selectedProviderVendorId],
  );
  const modelScenarioOptions = useMemo(
    () =>
      [
        { id: "chat" as ModelScenarioId, label: copy.modelScenarioChat },
        { id: "relay" as ModelScenarioId, label: copy.modelScenarioRelay },
        { id: "image" as ModelScenarioId, label: copy.modelScenarioImage },
        { id: "local" as ModelScenarioId, label: copy.modelScenarioLocal },
        { id: "manual" as ModelScenarioId, label: copy.modelScenarioManual },
      ],
    [copy],
  );
  const modelCenterSummary = useMemo(
    () =>
      deriveModelCenterSummary({
        modelOptions,
        schemaVersion: workspace?.schemaVersion,
      }),
    [modelOptions, workspace?.schemaVersion],
  );
  const modelCenterRows = useMemo(() => deriveModelCenterInventoryRows(modelOptions), [modelOptions]);
  const modelOptionsById = useMemo(() => new Map(modelOptions.map((option) => [option.model_id, option])), [modelOptions]);
  useEffect(() => {
    if (!modelOptions.length) {
      if (selectedModelTestId) {
        setSelectedModelTestId("");
      }
      return;
    }
    if (!selectedModelTestId || !modelOptionsById.has(selectedModelTestId)) {
      setSelectedModelTestId(modelOptions[0]?.model_id ?? "");
    }
  }, [modelOptions, modelOptionsById, selectedModelTestId]);
  const modelCapabilityIssueCount = countModelCenterHealthIssues(modelCenterRows);
  const modelDiscoveryAvailable = canDiscoverModelsForProvider(modelEditor.provider);

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
  const modelEditorRequiredFieldsReady = Boolean(modelEditor.model.trim() && modelEditor.provider.base_url.trim());
  const canSubmitModelEditor = !structuredActionsDisabled && modelEditorRequiredFieldsReady;

  async function handleTestProviderModel(modelRef: string) {
    if (structuredActionsDisabled) return;
    setBusyAction(`正在测试 ${modelRef}…`);
    setProviderActionError("");
    setProviderActionFeedback({
      kind: "discover",
      providerId: modelRef.includes("/") ? modelRef.slice(0, modelRef.indexOf("/")) : selectedProviderId,
      phase: "busy",
      message: `正在真实调用测试 ${modelRef}…`,
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
          ? `${modelRef} 可调用${result.verification_persisted ? "（已写入真实调用状态）" : ""}`
          : `${modelRef} 调用失败：${result.message || result.verification_error_type || "unknown"}${
              result.verification_http_status ? ` · HTTP ${result.verification_http_status}` : ""
            }`,
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
        message: `${modelRef} 测试请求失败：${message}`,
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

  function applyProviderTemplate(templateId: string) {
    setModelEditorExpanded(true);
    setModelEditorError("");
    setModelDiscoveryError("");
    setDiscoveredModels([]);
    setSelectedDiscoveredModelId("");
    const template = providerPresetOptions.find((item) => item.provider_preset_id === templateId);
    if (!template) {
      setModelEditor((current) => ({ ...current, provider_template_id: templateId }));
      return;
    }
    const templateModel = asRecord(template.default_model);
    const templateDetails = {
      ...buildModelDetailsDraft(templateModel),
      supports_image_input: "unknown" as const,
    };
    setSelectedProviderVendorId(template.vendor_id);
    setModelEditor({
      mode: "create",
      preset_id: "",
      provider_template_id: templateId,
      model_id: "",
      label: "",
      model: "",
      api_key_env: "",
      api_key: "",
      clear_api_key: false,
      provider: buildProviderDraft(asRecord(template.provider)),
      details: templateDetails,
    });
  }

  function applyProviderVendor(vendorId: string) {
    setSelectedProviderVendorId(vendorId);
    const template = providerVendorGroups.find((group) => group.id === vendorId)?.templates[0];
    if (template) {
      applyProviderTemplate(template.provider_preset_id);
      return;
    }
    setModelEditor((current) => ({ ...current, provider_template_id: "" }));
  }

  function applyModelScenario(scenario: ModelScenarioId) {
    const templateId = selectModelScenarioProviderPresetId(scenario, providerPresetOptions);
    if (templateId) {
      applyProviderTemplate(templateId);
      return;
    }
    setModelEditorExpanded(true);
    setModelEditorError("");
    setModelDiscoveryError("");
    setDiscoveredModels([]);
    setSelectedDiscoveredModelId("");
    setSelectedProviderVendorId("");
    setModelEditor({
      ...emptyModelEditorState(),
      provider: {
        ...emptyProviderDraft(),
        kind: scenario === "local" ? "local" : scenario === "relay" || scenario === "image" ? "relay" : "openai_compatible",
      },
      details: {
        ...emptyModelDetailsDraft(),
        streaming: scenario !== "image",
        tool_calling_mode: scenario === "image" ? "disabled" : "auto",
      },
    });
  }

  function applyDiscoveredModel(model: ConfigDiscoveredModel) {
    const modelName = model.id;
    const nextLabel = model.label || modelName;
    const existingIds = modelOptions.map((option) => option.model_id);
    const nextModelId = modelLibraryIdFromParts(nextLabel, modelName);
    const uniqueModelId = uniqueModelLibraryId(nextModelId, existingIds);
    setSelectedDiscoveredModelId(modelName);
    setModelEditor((current) => ({
      ...current,
      model_id: current.mode === "edit" ? current.model_id : uniqueModelId,
      label: current.mode === "create" ? nextLabel : current.label.trim() || nextLabel,
      model: modelName,
      api_key_env: current.mode === "create" ? defaultModelApiKeyEnv(uniqueModelId) : current.api_key_env.trim() || defaultModelApiKeyEnv(uniqueModelId),
      provider: {
        ...current.provider,
        context_window:
          !current.provider.context_window.trim() && typeof model.contextWindow === "number"
            ? String(model.contextWindow)
            : current.provider.context_window,
      },
    }));
  }

  async function handleDiscoverModels() {
    if (structuredActionsDisabled || !modelDiscoveryAvailable) {
      if (!modelDiscoveryAvailable) {
        setModelDiscoveryError(copy.discoveryUnavailable);
      }
      return;
    }
    setBusyAction(copy.discoveryPending);
    setModelDiscoveryError("");
    setDiscoveredModels([]);
    try {
      const discoveryModelId =
        modelEditor.mode === "edit"
          ? modelEditor.model_id
          : modelEditor.model_id.trim() ||
            uniqueModelLibraryId(modelLibraryIdFromParts(modelEditor.label || modelEditor.model, modelEditor.model), modelOptions.map((option) => option.model_id));
      const discoveryApiKeyEnv = modelEditor.api_key_env.trim() || defaultModelApiKeyEnv(discoveryModelId);
      const response = await discoverConfigModels({
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        provider: buildProviderPayload(modelEditor.provider),
        modelId: discoveryModelId,
        apiKeyEnv: discoveryApiKeyEnv,
        apiKey: modelEditor.api_key,
      });
      setDiscoveredModels(response.models);
      if (response.models.length) {
        applyDiscoveredModel(response.models[0]);
      } else {
        setModelDiscoveryError(copy.discoveryEmpty);
      }
    } catch (error) {
      setModelDiscoveryError(markError(error));
    } finally {
      setBusyAction("");
    }
  }

  async function handleSaveModel() {
    if (structuredActionsDisabled) {
      return;
    }
    if (!modelEditorRequiredFieldsReady) {
      setModelEditorError(copy.modelRequiredFieldsMissing);
      setModelEditorExpanded(true);
      return;
    }
    setBusyAction(copy.modelSavePending);
    setModelEditorError("");
    try {
      const resolvedModelId =
        modelEditor.mode === "edit"
          ? modelEditor.model_id
          : modelEditor.model_id.trim() ||
            uniqueModelLibraryId(modelLibraryIdFromParts(modelEditor.label || modelEditor.model, modelEditor.model), modelOptions.map((option) => option.model_id));
      const resolvedApiKeyEnv = modelEditor.api_key_env.trim() || defaultModelApiKeyEnv(resolvedModelId);
      const draftModelBody = {
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        presetId: "",
        modelId: resolvedModelId,
        provider: buildProviderPayload(modelEditor.provider),
        model: modelEditor.model,
        label: modelEditor.label,
        details: buildModelDetailsPayload(modelEditor.details),
        apiKeyEnv: resolvedApiKeyEnv,
        apiKey: modelEditor.api_key,
        clearApiKey: modelEditor.clear_api_key,
      };
      const response = modelEditor.mode === "edit"
        ? await updateDraftModel(draftModelBody)
        : await addDraftModel(draftModelBody);
      syncWorkspace(response, "success", { resetBase: false });
      setModelEditorExpanded(false);
    } catch (error) {
      setModelEditorError(markError(error));
      setModelEditorExpanded(true);
    } finally {
      setBusyAction("");
    }
  }

  async function handleDeleteModel(modelId: string) {
    if (structuredActionsDisabled) {
      return;
    }
    if (typeof window !== "undefined" && !window.confirm(copy.deleteModelConfirm)) {
      return;
    }
    setBusyAction(copy.modelSavePending);
    try {
      const response = await deleteDraftModel({
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        modelId,
      });
      syncWorkspace(response, "success", { resetBase: false });
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
  }

  function focusModelEditor() {
    window.setTimeout(() => {
      modelEditorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      const firstFocusableControl = modelEditorRef.current?.querySelector<HTMLButtonElement | HTMLInputElement | HTMLTextAreaElement>(
        [
          'button[data-vui="select-trigger"]:not([data-disabled="true"]):not([disabled])',
          'input:not([disabled]):not([type="hidden"])',
          "textarea:not([disabled])",
        ].join(", "),
      );
      firstFocusableControl?.focus({ preventScroll: true });
    }, 0);
  }

  async function handleTestSelectedLibraryModel() {
    if (structuredActionsDisabled) {
      return;
    }
    if (!selectedModelTestId) {
      setNotice({ tone: "error", text: copy.modelTestRequired });
      return;
    }
    setBusyAction(copy.testPending);
    try {
      const result = await testConfigLlm({
        publicConfig: requireDraft(),
        draftMeta,
        baseHash,
        modelId: selectedModelTestId,
      });
      setNotice({
        tone: result.ok ? "success" : "error",
        text: formatTestNotice(result),
      });
    } catch (error) {
      markError(error);
    } finally {
      setBusyAction("");
    }
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

  function keyStateLabel(state: string) {
    switch (state) {
      case "pending":
        return copy.keyPending;
      case "clear_pending":
        return copy.keyClearPending;
      case "configured":
        return copy.keyConfigured;
      default:
        return copy.keyMissing;
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

  // Workspace sync must reset the model editors alongside the rest of the snapshot;
  // syncWorkspace (route) invokes this via modelEditorsSyncRef after the hook mounts.
  function syncModelEditors(workspace: ConfigWorkspace) {
    setModelEditor(emptyModelEditorState());
    setSelectedModelTestId((current) =>
      current && workspace.modelOptions.some((option) => option.model_id === current)
        ? current
        : workspace.modelOptions[0]?.model_id ?? "",
    );
    setModelEditorError("");
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
    syncModelEditors,
  };
}
