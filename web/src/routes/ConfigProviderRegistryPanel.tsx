import { AlertTriangle, Database, Image as ImageIcon, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { applyProviderMerge, previewProviderMerge, rollbackProviderMerge, testConfigLlm } from "../api/config";
import {
  VActionGroup,
  VButton,
  VCheckbox,
  VDenseTable,
  VDialog,
  type VDenseTableColumn,
  VEntityList,
  VInput,
  VPanelHeader,
  VSection,
  VSettingsGroupCard,
  VSettingsRow,
  VSplitWorkspace,
  VStateSurface,
  VStatusChip,
  VSurface,
  VSwitch,
  VTooltip,
  type VStatusTone,
} from "../components/vui";
import type {
  ConfigCapabilityObservation,
  ConfigCatalogModel,
  ConfigProviderMergePreview,
  ConfigProviderMergeResult,
} from "../api/types";
import { type ConfigCopy, formatConfigCopy } from "./config/configCopy";
import {
  buildProviderSetupChecklist,
  canTestProviderModel,
  defaultProviderModelFilter,
  deriveProviderListRows,
  deriveProviderMergeCandidate,
  deriveProviderModelActionState,
  filterProviderModels,
  pinnableProviderModels,
  sortProviderRegistryRows,
  summarizeProviderModels,
  type ProviderDotClass,
  type ProviderListRow,
  type ProviderModelFilter,
  type ProviderRegistryRow,
} from "./configProviderLogic";
import styles from "./ConfigProviderRegistryPanel.styles";

export type ConfigProviderRegistryTab = "connection" | "models" | "protocols" | "diagnostics";

export type ProviderActionKind = "discover" | "credential" | "route" | "pin";

export type ProviderActionFeedback = {
  kind: ProviderActionKind;
  providerId: string;
  phase: "busy" | "success" | "error";
  message: string;
} | null;

export type ConfigProviderRegistryPanelProps = {
  /** Bilingual copy table (wave 4): every user-facing string comes from here. */
  copy: ConfigCopy;
  rows: ProviderRegistryRow[];
  selectedProviderId: string;
  selectedTab: ConfigProviderRegistryTab;
  disabled: boolean;
  activeCredentialProviderId: string;
  credentialValue: string;
  activeRouteProviderId: string;
  imageCapabilityBusy: boolean;
  actionFeedback: ProviderActionFeedback;
  liveReferenceCountByModelRef: Record<string, number>;
  /** Draft has pending external save (pin / key / window / etc.). */
  hasPendingApply?: boolean;
  canSaveConfig?: boolean;
  saveBusy?: boolean;
  onSaveExternal?: () => void;
  onSelectProvider: (providerId: string) => void;
  onSelectTab: (tab: ConfigProviderRegistryTab) => void;
  onDiscover: (providerId: string) => void;
  onEditCredential: (providerId: string) => void;
  onCredentialValueChange: (value: string) => void;
  onCancelCredential: () => void;
  onSaveCredential: (providerId: string) => void;
  onSaveContextWindow: (providerId: string, contextWindow: number | null) => void;
  onEditRoute: (providerId: string) => void;
  routeEditor?: ReactNode;
  onCancelRoute?: () => void;
  onPin: (providerId: string, models: ConfigCatalogModel[]) => void;
  onUnpin: (modelRef: string) => void;
  onTestModel: (modelRef: string) => void;
  onProbeImageInput: (modelRef: string) => void;
  onDeleteProvider: (providerId: string) => void;
  onAddConnection?: () => void;
  /**
   * Wave 2 row-level enable switch. Must flow through the config draft chain —
   * the toggle only edits the draft; the「保存到外部配置」prompt persists it.
   * Selection-surface semantics only: no running call is cut off.
   */
  onToggleEnabled?: (providerId: string, enabled: boolean) => void;
};

const TABS: Array<{ id: ConfigProviderRegistryTab; copyKey: "registryTabConnection" | "registryTabModels" | "registryTabProtocols" | "registryTabDiagnostics" }> = [
  { id: "connection", copyKey: "registryTabConnection" },
  { id: "models", copyKey: "registryTabModels" },
  { id: "protocols", copyKey: "registryTabProtocols" },
  { id: "diagnostics", copyKey: "registryTabDiagnostics" },
];

const MODEL_FILTERS: Array<{
  id: ProviderModelFilter;
  copyKey: "registryFilterAll" | "registryFilterPinned" | "registryFilterDiscovered";
  countKey: "total" | "pinned" | "discovered" | "unavailable";
}> = [
  { id: "all", copyKey: "registryFilterAll", countKey: "total" },
  { id: "pinned", copyKey: "registryFilterPinned", countKey: "pinned" },
  { id: "discovered", copyKey: "registryFilterDiscovered", countKey: "discovered" },
];

export type ModelTestRecoveryLabels = {
  testRecoveryAuth: string;
  testRecoveryRateLimited: string;
  testRecoveryNetwork: string;
  testRecoveryTimeout: string;
  testRecoveryUnavailable: string;
  testRecoveryNotFound: string;
  testRecoveryDefault: string;
};

export function modelTestRecoveryHint(kind: string, labels: ModelTestRecoveryLabels): string {
  if (["auth_failed", "missing_credential"].includes(kind)) return labels.testRecoveryAuth;
  if (kind === "rate_limited") return labels.testRecoveryRateLimited;
  if (kind === "network") return labels.testRecoveryNetwork;
  if (kind === "timeout") return labels.testRecoveryTimeout;
  if (["service_unavailable", "upstream_unavailable"].includes(kind)) return labels.testRecoveryUnavailable;
  if (kind === "not_found") return labels.testRecoveryNotFound;
  return labels.testRecoveryDefault;
}

type ProviderStatusLabels = {
  providerStatusReachable: string;
  providerStatusStale: string;
  providerStatusNotDiscovered: string;
  providerStatusConfigured: string;
  providerStatusAuthFailed: string;
  providerStatusDiscoveryFailed: string;
  providerStatusProtocolMismatch: string;
  providerStatusBlocked: string;
  providerStatusObserved: string;
  providerStatusPinned: string;
  providerStatusMissingRemote: string;
  providerStatusDisabled: string;
};

function providerStatusLabel(status: string, labels: ProviderStatusLabels): string {
  const labelsByStatus: Record<string, string> = {
    reachable: labels.providerStatusReachable,
    stale: labels.providerStatusStale,
    not_discovered: labels.providerStatusNotDiscovered,
    configured: labels.providerStatusConfigured,
    auth_failed: labels.providerStatusAuthFailed,
    discovery_failed: labels.providerStatusDiscoveryFailed,
    protocol_mismatch: labels.providerStatusProtocolMismatch,
    blocked: labels.providerStatusBlocked,
    observed: labels.providerStatusObserved,
    pinned: labels.providerStatusPinned,
    missing_remote: labels.providerStatusMissingRemote,
    disabled: labels.providerStatusDisabled,
  };
  return labelsByStatus[status] || status;
}

/**
 * Dot tooltip text (P0 consensus: error words live here, never as row text).
 * ok → 可用；off → 已停用；warn 且无具体异常 → 异常或未检测；其余 → 具体异常短语（如「认证失败」）。
 */
function providerDotTitle(dotClass: ProviderDotClass, status: string, copy: ConfigCopy): string {
  if (dotClass === "ok") return copy.providerDotOk;
  if (dotClass === "off") return copy.providerDotOff;
  const healthyStatuses = new Set(["reachable", "configured", "stale", ""]);
  if (healthyStatuses.has(status)) return copy.providerDotWarn;
  const statusText = providerStatusLabel(status, copy);
  return statusText && statusText !== status ? statusText : copy.providerDotWarn;
}

function providerDotClassName(dotClass: ProviderDotClass): string {
  if (dotClass === "ok") return `${styles.providerDot} ${styles.providerDotOk}`;
  if (dotClass === "warn") return `${styles.providerDot} ${styles.providerDotWarn}`;
  return `${styles.providerDot} ${styles.providerDotOff}`;
}

/** Sidebar list row (P0): dot + name + in-use badge; Wave 2 adds the inline enable switch. */
function ProviderListRowItem({
  row,
  selected,
  inspecting,
  disabled,
  copy,
  onSelect,
  onToggle,
}: {
  row: ProviderListRow & { status: string; dotTitle: string };
  selected: boolean;
  inspecting: boolean;
  disabled: boolean;
  copy: ConfigCopy;
  onSelect: () => void;
  onToggle?: (providerId: string, enabled: boolean) => void;
}) {
  return (
    <div
      className={styles.providerRow}
      data-active={selected ? "true" : "false"}
      data-inspecting={inspecting ? "true" : "false"}
      data-provider-status={row.status}
      data-provider-enabled={row.enabled ? "true" : "false"}
    >
      <VButton
        className={styles.providerButton}
        contentLayout="plain"
        variant="ghost"
        aria-pressed={selected}
        isDisabled={disabled}
        title={`${row.name}\n${row.providerId}`}
        onPress={onSelect}
      >
        <span
          className={providerDotClassName(row.dotClass)}
          data-provider-dot={row.dotClass}
          title={row.dotTitle}
        />
        <span className={styles.providerLabel}>{row.name}</span>
        {row.inUse ? (
          <span className={styles.providerInUseBadge} data-provider-inuse="true">{copy.inUseBadge}</span>
        ) : null}
      </VButton>
      {onToggle ? (
        <VSwitch
          className={styles.providerSwitch}
          isSelected={row.enabled}
          isDisabled={disabled}
          data-provider-switch="true"
          aria-label={`${row.name} · ${copy.providerSwitchAriaSuffix}`}
          title={copy.providerSwitchHint}
          onChange={(next) => onToggle(row.providerId, next)}
        />
      ) : null}
    </div>
  );
}

type DiscoveryErrorLabels = {
  discoveryErrTimeout: string;
  discoveryErrNetwork: string;
  discoveryErrCredentialMissing: string;
  discoveryErrAuthFailed: string;
  discoveryErrEndpointInvalid: string;
  discoveryErrProtocolMismatch: string;
  discoveryErrInvalidResponse: string;
  discoveryErrRateLimited: string;
  discoveryErrUpstreamRejected: string;
  discoveryErrUnavailable: string;
  discoveryErrBlocked: string;
  discoveryErrOther: string;
  discoveryErrNone: string;
};

function discoveryErrorLabel(errorType: string, labels: DiscoveryErrorLabels): string {
  switch (errorType) {
    case "timeout": return labels.discoveryErrTimeout;
    case "network": return labels.discoveryErrNetwork;
    case "credential_missing": return labels.discoveryErrCredentialMissing;
    case "credential_rejected":
    case "auth_failed": return labels.discoveryErrAuthFailed;
    case "endpoint_invalid": return labels.discoveryErrEndpointInvalid;
    case "protocol_mismatch": return labels.discoveryErrProtocolMismatch;
    case "invalid_response": return labels.discoveryErrInvalidResponse;
    case "rate_limited": return labels.discoveryErrRateLimited;
    case "upstream_rejected": return labels.discoveryErrUpstreamRejected;
    case "service_unavailable":
    case "upstream_unavailable":
    case "discovery_unavailable": return labels.discoveryErrUnavailable;
    case "blocked": return labels.discoveryErrBlocked;
    case "other": return labels.discoveryErrOther;
    default: return errorType || labels.discoveryErrNone;
  }
}

function capabilityTone(observation: ConfigCapabilityObservation): VStatusTone {
  if (observation.value === "supported") return "success";
  if (observation.value === "unsupported") return "danger";
  return "warning";
}

function CapabilityList({ model, copy }: { model: ConfigCatalogModel; copy: ConfigCopy }) {
  const capabilities = Object.entries(model.capabilities);
  const reasoningValues = model.reasoningEffortValues ?? [];
  const reasoningSource = String(model.reasoningCapabilitySource || "");
  const isPinned = model.availability === "pinned" || model.availability === "missing_remote";
  const reasoningRows: Array<{ key: string; label: string; detail: string; tone: VStatusTone }> = [];
  // Only surface reasoning contract guidance for pinned models — never spam full discovery dumps.
  if (reasoningValues.length > 0) {
    const isOperator = reasoningSource === "operator_override" || model.reasoningVerificationStatus === "declared";
    reasoningRows.push({
      key: "reasoning_effort",
      label: `${copy.reasoningDepthPrefix}${reasoningValues.join("/")}`,
      detail: isOperator
        ? formatConfigCopy(copy.reasoningDeclaredDetail, { default: model.defaultReasoningEffort || "-", adapter: model.reasoningAdapter || "none" })
        : formatConfigCopy(copy.reasoningVerifiedDetail, { adapter: model.reasoningAdapter || "none" }),
      tone: "success",
    });
  } else if (isPinned) {
    reasoningRows.push({
      key: "reasoning_effort_missing",
      label: copy.reasoningMissingLabel,
      detail: copy.reasoningMissingDetail,
      tone: "warning",
    });
  }
  if (!capabilities.length && !reasoningRows.length) {
    return <span className={styles.capabilityUnknown}>{isPinned ? copy.capabilityUnobserved : "—"}</span>;
  }
  return (
    <div className={styles.capabilityList}>
      {reasoningRows.map((row) => (
        <VTooltip key={row.key} content={row.detail} width="wide">
          <span className={styles.providerIdentity} data-capability="reasoning_effort">
            <VStatusChip tone={row.tone}>{row.label}</VStatusChip>
          </span>
        </VTooltip>
      ))}
      {capabilities.map(([name, observation]) => (
        <VTooltip
          key={name}
          content={`${observation.source} · ${observation.confidence || "confidence unknown"} · ${observation.checked_at || copy.capabilityCheckedAtMissing}`}
          width="wide"
        >
          <span className={styles.providerIdentity}>
            <VStatusChip tone={capabilityTone(observation)}>
              {name}: {observation.value === "unknown" ? copy.capabilityValueUnknown : observation.value === "unsupported" ? copy.capabilityValueUnsupported : "supported"}
            </VStatusChip>
          </span>
        </VTooltip>
      ))}
    </div>
  );
}

function ProviderSetupChecklist({ provider, copy }: { provider: ProviderRegistryRow; copy: ConfigCopy }) {
  const items = buildProviderSetupChecklist(provider, copy);
  const next = items.find((item) => !item.done);
  return (
    <div className={styles.setupChecklist} data-provider-checklist="true" aria-label={copy.checklistAria}>
      <div className={styles.setupChecklistItems}>
        {items.map((item) => (
          <span
            key={item.id}
            className={styles.setupChecklistItem}
            data-done={item.done ? "true" : "false"}
            data-optional={item.optional ? "true" : "false"}
          >
            <VStatusChip tone={item.done ? "success" : item.optional ? "neutral" : "warning"}>
              {item.done ? copy.checklistDone : item.optional ? copy.checklistOptional : copy.checklistTodo}
            </VStatusChip>
            <small className={styles.muted}>{item.label}</small>
          </span>
        ))}
      </div>
      {next ? (
        <p className={styles.setupChecklistNext} role="status">
          {copy.checklistNextPrefix}{next.label}
          {next.id === "pin" ? copy.checklistNextPinHint : ""}
          {next.id === "credential" ? copy.checklistNextCredentialHint : ""}
          {next.id === "connection" ? copy.checklistNextConnectionHint : ""}
        </p>
      ) : (
        <p className={styles.setupChecklistNext} role="status">
          {copy.checklistAllDone}
        </p>
      )}
    </div>
  );
}

function ConnectionTab({
  provider,
  contextWindowDraft,
  credentialActive,
  credentialValue,
  disabled,
  copy,
  onContextWindowDraftChange,
  onSaveContextWindow,
  onEditCredential,
  onCredentialValueChange,
  onCancelCredential,
  onSaveCredential,
}: {
  provider: ProviderRegistryRow;
  contextWindowDraft: string;
  credentialActive: boolean;
  credentialValue: string;
  disabled: boolean;
  copy: ConfigCopy;
  onContextWindowDraftChange: (value: string) => void;
  onSaveContextWindow: () => void;
  onEditCredential: () => void;
  onCredentialValueChange: (value: string) => void;
  onCancelCredential: () => void;
  onSaveCredential: () => void;
}) {
  const needsKey = provider.credentialState !== "not_required";
  return (
    <VSettingsGroupCard>
      <VSettingsRow label={copy.apiKeyRowLabel}
        description={needsKey ? copy.apiKeySharedHint : copy.apiKeyNotRequiredHint}
        control={needsKey ? <VButton variant="secondary" isDisabled={disabled} onPress={onEditCredential}>
          {provider.credentialState === "configured" ? copy.updateApiKey : copy.enterApiKey}
        </VButton> : <span className={styles.muted}>{copy.noKeyNeeded}</span>}
        footer={needsKey && credentialActive ? (
          <div className={styles.inlineCredential}>
            <label className={styles.inlineCredentialField}>
              <span>API Key</span>
              <VInput type="password" autoComplete="new-password" value={credentialValue}
                disabled={disabled} placeholder={copy.newApiKeyPlaceholder}
                onChange={(event) => onCredentialValueChange(event.target.value)} />
            </label>
            <VActionGroup ariaLabel={copy.apiKeyActionsAria}>
              <VButton isDisabled={disabled} onPress={onCancelCredential}>{copy.cancel}</VButton>
              <VButton variant="primary" isDisabled={disabled || !credentialValue.trim()}
                onPress={onSaveCredential}>{copy.saveKey}</VButton>
            </VActionGroup>
          </div>
        ) : undefined} />
      <VSettingsRow label={copy.contextLimitRowLabel}
        description={copy.contextLimitRowHint}
        control={<span className={styles.muted}>{provider.contextWindow ? `${provider.contextWindow.toLocaleString()} token` : copy.useModelDeclared}</span>}
        footer={<details>
          <summary className={styles.verificationDetails}>{copy.adjustContextDetails}</summary>
          <div className={styles.connectionCardBody}>
            <label className={styles.inlineCredentialField}>
              <span>{copy.contextWindowFieldLabel}</span>
              <VInput type="number" min={1} step={1} value={contextWindowDraft} disabled={disabled}
                placeholder={copy.contextWindowExample} onChange={(event) => onContextWindowDraftChange(event.target.value)} />
            </label>
            <VButton variant="secondary" isDisabled={disabled || (contextWindowDraft.trim() !== "" && (!Number.isFinite(Number(contextWindowDraft)) || Number(contextWindowDraft) <= 0))}
              onPress={onSaveContextWindow}>{copy.saveContextWindow}</VButton>
            <span className={styles.muted}>{copy.driverPrefix}{provider.driver || copy.notConfigured} · {provider.serviceClass || copy.notConfigured}</span>
            {provider.serviceClass === "local_runtime" ? <span className={styles.connectionAddress}>
              {copy.runtimeFrameworkPrefix}{provider.runtimeFramework || copy.unknownValue} · {copy.artifactFilePrefix}{provider.artifactPath || copy.notConfigured}
            </span> : null}
          </div>
        </details>} />
    </VSettingsGroupCard>
  );
}

export type ProviderModelsTabProps = {
  copy: ConfigCopy;
  toolbarIdentity?: ReactNode;
  toolbarActions?: ReactNode;
  provider: ProviderRegistryRow;
  disabled: boolean;
  modelQuery: string;
  modelFilter: ProviderModelFilter;
  liveReferenceCountByModelRef: Record<string, number>;
  onQueryChange: (query: string) => void;
  onFilterChange: (filter: ProviderModelFilter) => void;
  onPin: (providerId: string, models: ConfigCatalogModel[]) => void;
  onUnpin: (modelRef: string) => void;
  onTestModel: (modelRef: string) => void;
  imageCapabilityBusy?: boolean;
  pinBusy?: boolean;
  onProbeImageInput?: (modelRef: string) => void;
  reasoningFeedbackByModelRef?: Record<string, {
    phase: "busy" | "success" | "error";
    values: string[];
    message: string;
  }>;
  onProbeReasoning?: (modelRef: string) => void;
};

export function ProviderModelsTab({
  copy,
  toolbarIdentity,
  toolbarActions,
  provider,
  disabled,
  modelQuery,
  modelFilter,
  liveReferenceCountByModelRef,
  onQueryChange,
  onFilterChange,
  onPin,
  onUnpin,
  onTestModel,
  imageCapabilityBusy = false,
  pinBusy = false,
  onProbeImageInput,
  reasoningFeedbackByModelRef = {},
  onProbeReasoning,
}: ProviderModelsTabProps) {
  const summary = useMemo(() => summarizeProviderModels(provider.models), [provider.models]);
  const pinnableModels = useMemo(
    () => pinnableProviderModels(filterProviderModels(provider.models, modelQuery, "discovered")),
    [provider.models, modelQuery],
  );
  const visibleModels = useMemo(
    () => filterProviderModels(provider.models, modelQuery, modelFilter),
    [modelFilter, modelQuery, provider.models],
  );
  const emptyText = provider.models.length === 0
    ? copy.modelsEmptyCatalog
    : modelFilter === "pinned" && summary.pinned === 0
      ? copy.modelsEmptyPinned
      : modelFilter === "discovered" && summary.discovered === 0
        ? copy.modelsEmptyDiscovered
        : copy.modelsEmptyNoMatch;

  const [detailModelRef, setDetailModelRef] = useState("");
  const detailModel = provider.models.find((model) => model.modelRef === detailModelRef);
  const verificationColumn: VDenseTableColumn<ConfigCatalogModel> = {
    id: "verification",
    header: copy.verificationHeader,
    render: (model) => {
      const verificationStatus = model.verificationStatus || "unverified";
      const errorLabel = (() => {
        const kind = String(model.verificationErrorType || "").trim();
        if (!kind) return "";
        if (kind === "timeout") return copy.verifyErrTimeout;
        if (kind === "bad_request") return copy.verifyErrBadRequest;
        if (kind === "auth_failed") return copy.verifyErrAuthFailed;
        if (kind === "rate_limited") return copy.verifyErrRateLimited;
        if (kind === "not_found") return copy.verifyErrNotFound;
        if (kind === "network") return copy.verifyErrNetwork;
        if (kind === "missing_credential") return copy.verifyErrMissingCredential;
        if (kind === "service_unavailable" || kind === "upstream_unavailable") return copy.verifyErrUnavailable;
        return kind;
      })();
      const detail = [
        model.verificationHttpStatus ? `HTTP ${model.verificationHttpStatus}` : "",
        errorLabel,
        model.verificationMessage || "",
        model.verificationCheckedAt || (verificationStatus === "unverified" ? copy.verifyUntested : ""),
      ].filter(Boolean).join(" · ");
      return (
        <div className={styles.verification}>
          <VStatusChip tone={verificationStatus === "verified" ? "success" : verificationStatus === "failed" ? "danger" : "neutral"}>
            {verificationStatus === "verified" ? copy.verifyPassed : verificationStatus === "failed" ? copy.verifyFailed : copy.verifyUntested}
          </VStatusChip>
          {verificationStatus === "failed" ? <>
            <small className={styles.verificationError}>{errorLabel || copy.verifyRequestFailed}{model.verificationHttpStatus ? ` · HTTP ${model.verificationHttpStatus}` : ""}</small>
            <small className={styles.muted}>{modelTestRecoveryHint(model.verificationErrorType || "", copy)}</small>
            <details><summary className={styles.verificationDetails}>{copy.verifyErrorDetails}</summary><p className={styles.verificationMessage}>{detail}</p></details>
          </> : model.verificationCheckedAt ? <small className={styles.muted}>{model.verificationCheckedAt}</small> : null}
        </div>
      );
    },
  };
  const detailColumns: VDenseTableColumn<ConfigCatalogModel>[] = [

    {
      id: "model-ref",
      header: copy.columnModelRef,
      render: (model) => (
        <span className={styles.modelIdentity} data-model-availability={model.availability}>
          <strong className={styles.ellipsis} title={model.modelRef}>{model.modelRef}</strong>
          <small className={styles.muted}>{model.label || model.modelKey}</small>
        </span>
      ),
    },
    {
      id: "upstream",
      header: copy.columnUpstreamId,
      render: (model) => <span className={styles.ellipsis} title={model.upstreamId}>{model.upstreamId}</span>,
    },
    { id: "availability", header: copy.columnAvailability, render: (model) => <VStatusChip tone={model.availability === "disabled" ? "danger" : "neutral"}>{providerStatusLabel(model.availability, copy)}</VStatusChip> },
    verificationColumn,
    { id: "capabilities", header: copy.columnCapabilities, render: (model) => <CapabilityList model={model} copy={copy} /> },
    {
      id: "actions",
      header: copy.columnActions,
      render: (model) => {
        const action = deriveProviderModelActionState(
          provider,
          model,
          liveReferenceCountByModelRef[model.modelRef] ?? 0,
          disabled,
          copy,
        );
        const testAvailable = canTestProviderModel(model);
        const imageCapability = model.capabilities?.image_input;
        const imageProbeAvailable = (
          ["observed", "pinned"].includes(model.availability)
          && !provider.refreshDue
        );
        const reasoningFeedback = reasoningFeedbackByModelRef[model.modelRef];
        const reasoningValues = reasoningFeedback?.phase === "success"
          ? reasoningFeedback.values
          : model.reasoningEffortValues ?? [];
        const reasoningSource = String(model.reasoningCapabilitySource || "");
        const reasoningDeclared = (
          reasoningValues.length > 0
          && (
            reasoningSource === "operator_override"
            || model.reasoningVerificationStatus === "declared"
          )
        );
        const reasoningVerified = reasoningFeedback?.phase === "success"
          || model.reasoningVerificationStatus === "verified";
        const reasoningHasContract = reasoningDeclared || reasoningVerified || reasoningValues.length > 0;
        // T6: probe is optional evidence; operator declaration already enables UI (D1).
        const reasoningProbeAvailable = (
          provider.defaultProtocol === "responses"
          && ["observed", "pinned"].includes(model.availability)
          && !reasoningHasContract
          && !provider.refreshDue
        );
        return (
          <VActionGroup ariaLabel={`${model.modelRef}${copy.modelActionsAriaSuffix}`}>
            {imageProbeAvailable ? (
              <VButton
                data-model-capability-action="image_input"
                density="compact"
                icon={<ImageIcon size={14} />}
                isDisabled={disabled || imageCapabilityBusy}
                title={copy.imageProbeHint}
                onPress={() => onProbeImageInput?.(model.modelRef)}
              >
                {imageCapabilityBusy
                  ? copy.imageProbeBusy
                  : imageCapability?.value === "supported" || imageCapability?.value === "unsupported"
                    ? copy.imageProbeRetry
                    : copy.imageProbeAction}
              </VButton>
            ) : null}
            {reasoningHasContract ? (
              <span
                className={styles.modelActionState}
                data-model-reasoning={reasoningDeclared && !reasoningVerified ? "declared" : "verified"}
                title={
                  reasoningDeclared && !reasoningVerified
                    ? copy.reasoningDeclaredTooltip
                    : copy.reasoningVerifiedTooltip
                }
              >
                {reasoningDeclared && !reasoningVerified
                  ? `${copy.reasoningDeclaredPrefix}${reasoningValues.join(" / ")}`
                  : formatConfigCopy(copy.reasoningVerifiedTemplate, { values: reasoningValues.join(" / ") })}
              </span>
            ) : reasoningProbeAvailable ? (
              <VButton
                density="compact"
                isDisabled={disabled || reasoningFeedback?.phase === "busy"}
                title={copy.reasoningProbeHint}
                onPress={() => onProbeReasoning?.(model.modelRef)}
              >
                {reasoningFeedback?.phase === "busy" ? copy.reasoningProbeBusy : copy.reasoningProbeAction}
              </VButton>
            ) : null}
            {action.kind === "pin" ? (
              <VButton
                variant="primary"
                density="compact"
                data-model-action="pin"
                isDisabled={action.disabled || pinBusy}
                title={action.reason}
                onPress={() => onPin(provider.providerId, [model])}
              >
                {pinBusy ? copy.pinAdding : copy.pinToAdd}
              </VButton>
            ) : null}
            {testAvailable ? (
              <VButton
                density="compact"
                isDisabled={disabled}
                title={copy.testCallHint}
                onPress={() => onTestModel(model.modelRef)}
              >
                {copy.testCall}
              </VButton>
            ) : null}
            {action.kind === "unpin" ? (
              <VButton
                variant="danger"
                density="compact"
                isDisabled={action.disabled}
                title={action.reason || undefined}
                onPress={() => onUnpin(model.modelRef)}
              >
                {copy.unpinAction}
              </VButton>
            ) : action.kind === "in_use" || action.kind === "unavailable" ? (
              <span className={styles.modelActionState} data-model-action={action.kind}>
                {action.label}{action.kind === "in_use" ? ` · ${action.referenceCount}${copy.referenceCountUnit}` : ""}
              </span>
            ) : null}
            {reasoningFeedback?.phase === "error" ? (
              <small className={styles.critical} role="alert">{reasoningFeedback.message}</small>
            ) : null}
          </VActionGroup>
        );
      },
    },
  ];

  return (
    <div className={styles.modelsWorkspace}>
      <div className={styles.modelChrome}>
      <div className={styles.modelToolbar}>
        {toolbarIdentity}
        <VInput
          aria-label={copy.searchModelsAria}
          className={styles.modelSearch}
          placeholder={copy.searchModelsPlaceholder}
          value={modelQuery}
          onChange={(event) => onQueryChange(event.currentTarget.value)}
        />
        <VActionGroup ariaLabel={copy.modelFiltersAria} className={styles.modelFilters}>
          {MODEL_FILTERS.map((filter) => (
            <VButton
              key={filter.id}
              density="compact"
              variant={modelFilter === filter.id ? "primary" : "ghost"}
              aria-pressed={modelFilter === filter.id}
              onPress={() => onFilterChange(filter.id)}
            >
              {copy[filter.copyKey]} {summary[filter.countKey]}
            </VButton>
          ))}
        </VActionGroup>
        {toolbarActions}
      </div>
      {modelFilter === "discovered" && pinnableModels.length > 0 ? (
        <div className={styles.pinBanner} role="region" aria-label={copy.pinBannerAria}>
          <VActionGroup ariaLabel={copy.pinBannerActionsAria} className={styles.pinBannerActions}>
            <VButton
              variant="primary"
              data-model-action="pin-all"
              isDisabled={disabled || pinBusy}
              tooltip={
                pinBusy
                  ? copy.pinAllBusy
                  : [
                      copy.pinAllHint,
                      provider.refreshDue
                        ? formatConfigCopy(copy.pinAllStaleHint, { count: pinnableModels.length })
                        : "",
                    ].filter(Boolean).join(" ")
              }
              onPress={() => onPin(provider.providerId, pinnableModels)}
            >
              {pinBusy ? copy.pinAdding : formatConfigCopy(copy.pinAllTemplate, { count: pinnableModels.length })}
            </VButton>

          </VActionGroup>
        </div>
      ) : null}
      </div>
      <div className={styles.tableScroll}>
        <VDenseTable
          ariaLabel={`${provider.label}${copy.catalogTableAriaSuffix}`}
          className={styles.table}
          rows={visibleModels}
          getRowKey={(model) => model.modelRef}
          emptyText={emptyText}
          columns={[
            { id: "model", header: copy.columnModel, className: "w-auto", render: (model) => (
              <span className={styles.modelIdentity} data-model-availability={model.availability}>
                <strong className={styles.modelName} title={model.modelRef}>{model.label || model.modelKey}</strong>
                <small className={styles.muted}>{providerStatusLabel(model.availability, copy)}</small>
              </span>
            ) },
            { ...verificationColumn, className: "w-[16rem]" },
            { id: "actions", header: copy.columnActions, className: "w-[12rem]", render: (model) => (
              <div className={styles.compactModelActions}>
                {(() => {
                  const action = deriveProviderModelActionState(provider, model, liveReferenceCountByModelRef[model.modelRef] ?? 0, disabled, copy);
                  return action.kind === "pin" ? <VButton density="compact" variant="primary" isDisabled={action.disabled || pinBusy} title={action.reason} onPress={() => onPin(provider.providerId, [model])}>{copy.pinCompact}</VButton> : null;
                })()}
                <VButton density="compact" variant="ghost" onPress={() => setDetailModelRef(model.modelRef)} aria-label={`${model.label || model.modelKey}${copy.detailAriaSuffix}`}>{copy.detailsAction}</VButton>
                {canTestProviderModel(model) ? <VButton density="compact" isDisabled={disabled} title={copy.testCallHint} onPress={() => onTestModel(model.modelRef)}>{copy.testCall}</VButton> : null}
              </div>
            ) },
          ]}
        />
      </div>
      <VDialog open={Boolean(detailModel)} onOpenChange={(open) => { if (!open) setDetailModelRef(""); }} title={detailModel?.label || detailModel?.modelKey || copy.modelDetailTitle} description={copy.modelDetailDescription}>
        {detailModel ? <div className={styles.modelDetails}>
          {detailColumns.map((column) => <section key={column.id} className={styles.modelDetailSection}>
            <h3>{column.header}</h3>
            {column.render(detailModel)}
          </section>)}
        </div> : null}
      </VDialog>
    </div>
  );
}

function ProtocolsTab({ provider, copy }: { provider: ProviderRegistryRow; copy: ConfigCopy }) {
  return (
    <div className={styles.tabSurface}>
      <span className={styles.fact}>
        <small className={styles.factLabel}>{copy.wireProtocolLabel}</small>
        <strong className={styles.factValue}>{provider.defaultProtocol || "unknown"}</strong>
      </span>
      {provider.models.length ? provider.models.map((model) => (
        <span key={model.modelRef} className={styles.fact} data-model-availability={model.availability}>
          <small className={styles.factLabel} title={model.modelRef}>{model.modelRef}</small>
          <CapabilityList model={model} copy={copy} />
        </span>
      )) : <VStateSurface tone="empty" title={copy.noCapabilityTitle}>{copy.noCapabilityBody}</VStateSurface>}
    </div>
  );
}

function DiagnosticsTab({
  provider,
  disabled,
  copy,
  onDiscover,
}: {
  provider: ProviderRegistryRow;
  disabled: boolean;
  copy: ConfigCopy;
  onDiscover: (providerId: string) => void;
}) {
  const isCritical = ["auth_failed", "protocol_mismatch", "blocked", "discovery_failed"].includes(provider.status);
  return (
    <div className={styles.tabSurface}>
      {isCritical ? (
        <p className={styles.critical} role="alert">
          {copy.providerCriticalPrefix}{providerStatusLabel(provider.status, copy)}{copy.providerCriticalSuffix}
        </p>
      ) : null}
      <VStateSurface
        tone={isCritical ? "error" : provider.refreshDue ? "unavailable" : "info"}
        title={provider.refreshDue ? copy.refreshDueTitle : copy.registryDiagnosticsTitle}
        facts={[
          { key: "attempt", label: copy.factLastAttempt, value: provider.lastAttemptAt || copy.valueNever },
          { key: "success", label: copy.factLastSuccess, value: provider.lastSuccessAt || copy.valueNever },
          { key: "failure", label: copy.factLastFailure, value: discoveryErrorLabel(provider.lastErrorType ?? "", copy) },
          { key: "auth", label: copy.factAuth, value: provider.status === "auth_failed" ? copy.valueFailed : provider.credentialState },
          { key: "protocol", label: copy.factProtocol, value: provider.status === "protocol_mismatch" ? copy.valueMismatch : provider.defaultProtocol || "unknown" },
        ]}
        actions={(
          <VButton
            variant="primary"
            icon={<RefreshCw size={14} />}
            isDisabled={disabled}
            onPress={() => onDiscover(provider.providerId)}
          >
            {copy.rediscover}
          </VButton>
        )}
      >
        {copy.registryDiagnosticsBody}
      </VStateSurface>
    </div>
  );
}

export function ConfigProviderRegistryPanel({
  copy,
  rows,
  selectedProviderId,
  selectedTab,
  disabled,
  activeCredentialProviderId,
  credentialValue,
  activeRouteProviderId,
  imageCapabilityBusy,
  actionFeedback,
  liveReferenceCountByModelRef,
  hasPendingApply = false,
  canSaveConfig = false,
  saveBusy = false,
  onSaveExternal,
  onSelectProvider,
  onSelectTab,
  onDiscover,
  onEditCredential,
  onCredentialValueChange,
  onCancelCredential,
  onSaveCredential,
  onSaveContextWindow,
  onEditRoute,
  routeEditor,
  onCancelRoute,
  onPin,
  onUnpin,
  onTestModel,
  onProbeImageInput,
  onDeleteProvider,
  onAddConnection,
  onToggleEnabled,
}: ConfigProviderRegistryPanelProps) {
  const orderedRows = useMemo(() => sortProviderRegistryRows(rows), [rows]);
  // P0 single list: every provider shows once; dot carries availability, in-use sorts first.
  const listRows = useMemo(
    () => deriveProviderListRows(rows, liveReferenceCountByModelRef),
    [liveReferenceCountByModelRef, rows],
  );
  const listItems = useMemo(
    () => listRows.map((listRow) => {
      const full = rows.find((row) => row.providerId === listRow.providerId);
      return {
        ...listRow,
        id: listRow.providerId,
        status: full?.status ?? "",
        dotTitle: providerDotTitle(listRow.dotClass, full?.status ?? "", copy),
      };
    }),
    [copy, listRows, rows],
  );
  const provider =
    rows.find((row) => row.providerId === selectedProviderId)
    ?? (listRows[0]
      ? rows.find((row) => row.providerId === listRows[0].providerId) ?? null
      : null);
  const [modelQuery, setModelQuery] = useState("");
  const [contextWindowDraft, setContextWindowDraft] = useState("");
  const [modelFilter, setModelFilter] = useState<ProviderModelFilter>(() =>
    defaultProviderModelFilter(provider?.models ?? []),
  );
  const [showAdvancedTools, setShowAdvancedTools] = useState(false);

  useEffect(() => {
    if (!provider) {
      setContextWindowDraft("");
      return;
    }
    setContextWindowDraft(provider.contextWindow ? String(provider.contextWindow) : "");
  }, [provider?.providerId, provider?.contextWindow]);

  // Keep the selection on a listed provider; default to the first list row (in-use first).
  useEffect(() => {
    if (!listRows.length) return;
    if (selectedProviderId && rows.some((row) => row.providerId === selectedProviderId)) return;
    onSelectProvider(listRows[0].providerId);
  }, [listRows, onSelectProvider, rows, selectedProviderId]);

  const [mergePreview, setMergePreview] = useState<ConfigProviderMergePreview | null>(null);
  const [mergeResult, setMergeResult] = useState<ConfigProviderMergeResult | null>(null);
  const [mergeConfirmed, setMergeConfirmed] = useState(false);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [mergeError, setMergeError] = useState("");
  const [reasoningFeedbackByModelRef, setReasoningFeedbackByModelRef] = useState<Record<string, {
    phase: "busy" | "success" | "error";
    values: string[];
    message: string;
  }>>({});
  const mergeCandidate = useMemo(
    () => deriveProviderMergeCandidate(orderedRows, provider?.providerId ?? ""),
    [provider?.providerId, orderedRows],
  );
  const providerLiveReferenceCount = provider?.models.reduce(
    (total, model) => total + (liveReferenceCountByModelRef[model.modelRef] ?? 0),
    0,
  ) ?? 0;
  const providerDeleteBlocked = Boolean(provider && (provider.pinnedCount > 0 || providerLiveReferenceCount > 0));
  const visibleFeedback = actionFeedback?.providerId === provider?.providerId ? actionFeedback : null;
  const discoverBusy = visibleFeedback?.kind === "discover" && visibleFeedback.phase === "busy";
  const pinBusy = visibleFeedback?.kind === "pin" && visibleFeedback.phase === "busy";
  const credentialActive = activeCredentialProviderId === provider?.providerId;
  const routeActive = activeRouteProviderId === provider?.providerId;

  useEffect(() => {
    setModelQuery("");
    setModelFilter(defaultProviderModelFilter(provider?.models ?? []));
    setMergePreview(null);
    setMergeResult(null);
    setMergeConfirmed(false);
    setMergeError("");
    setReasoningFeedbackByModelRef({});
    // Reset table tools when switching Provider only — keep user filter while discovering on same Provider.
  }, [provider?.providerId]);

  // After a successful pin batch, force the「已固定」filter so users see the full pinned set.
  useEffect(() => {
    if (actionFeedback?.kind !== "pin" || actionFeedback.phase !== "success") return;
    if (actionFeedback.providerId !== provider?.providerId) return;
    setModelFilter("pinned");
    setModelQuery("");
  }, [actionFeedback, provider?.providerId]);

  const probeReasoning = async (modelRef: string) => {
    setReasoningFeedbackByModelRef((current) => ({
      ...current,
      [modelRef]: { phase: "busy", values: [], message: copy.reasoningProbePending },
    }));
    try {
      const result = await testConfigLlm({ modelId: modelRef, capability: "reasoning_effort" });
      if (!result.ok || !result.reasoning_contract_persisted) {
        throw new Error(result.message || copy.reasoningProbeFailed);
      }
      const values = result.reasoning_effort_values ?? [];
      setReasoningFeedbackByModelRef((current) => ({
        ...current,
        [modelRef]: {
          phase: "success",
          values,
          message: formatConfigCopy(copy.reasoningProbeSuccess, { values: values.join(" / ") }),
        },
      }));
    } catch (error) {
      setReasoningFeedbackByModelRef((current) => ({
        ...current,
        [modelRef]: {
          phase: "error",
          values: [],
          message: error instanceof Error ? error.message : String(error),
        },
      }));
    }
  };

  const previewMerge = async () => {
    if (!mergeCandidate) return;
    setMergeBusy(true);
    setMergeError("");
    try {
      const credentialDecisions = Object.fromEntries(
        mergeCandidate.duplicateProviderIds.map((providerId) => [providerId, "use_canonical"]),
      );
      const preview = await previewProviderMerge({
        ...mergeCandidate,
        credentialDecisions,
      });
      setMergePreview(preview);
      setMergeConfirmed(false);
    } catch (error) {
      setMergeError(error instanceof Error ? error.message : String(error));
    } finally {
      setMergeBusy(false);
    }
  };

  const applyMerge = async () => {
    if (!mergePreview || !mergeConfirmed) return;
    setMergeBusy(true);
    setMergeError("");
    try {
      const result = await applyProviderMerge({
        previewId: mergePreview.previewId,
        baseHash: mergePreview.baseHash,
        confirmed: true,
      });
      setMergeResult(result);
    } catch (error) {
      setMergeError(error instanceof Error ? error.message : String(error));
    } finally {
      setMergeBusy(false);
    }
  };

  const rollbackMerge = async () => {
    if (!mergeResult) return;
    setMergeBusy(true);
    setMergeError("");
    try {
      const result = await rollbackProviderMerge(mergeResult.migrationId, {
        migrationId: mergeResult.migrationId,
        baseHash: mergeResult.hash,
      });
      setMergeResult(result);
      setMergePreview(null);
      setMergeConfirmed(false);
    } catch (error) {
      setMergeError(error instanceof Error ? error.message : String(error));
    } finally {
      setMergeBusy(false);
    }
  };

  const [inspectorOpen, setInspectorOpen] = useState(false);
  const inspectorProvider = inspectorOpen ? provider : null;

  function openInspector(providerId: string) {
    onSelectProvider(providerId);
    onSelectTab("connection");
    setInspectorOpen(true);
  }

  function closeInspector() {
    setInspectorOpen(false);
  }

  const saveContextWindowFor = (target: ProviderRegistryRow) => {
    const raw = contextWindowDraft.trim();
    if (!raw) {
      onSaveContextWindow(target.providerId, null);
      return;
    }
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || parsed <= 0) return;
    onSaveContextWindow(target.providerId, Math.round(parsed));
  };

  return (
    <VSurface as="section" id="config-models" className={styles.sectionSurface} padding="none">
      {hasPendingApply ? (
        <div className={styles.savePrompt} role="status" data-save-prompt="pending" aria-live="polite">
          <div className={styles.savePromptCopy}>
            <strong>{copy.unsavedModelsTitle}</strong>
          </div>
          <VButton
            variant="primary"
            data-save-prompt-action="apply"
            icon={<Save size={14} />}
            isDisabled={!canSaveConfig || disabled || saveBusy}
            tooltip={copy.savePromptTooltip}
            onPress={() => onSaveExternal?.()}
          >
            {saveBusy ? copy.saveBusy : copy.saveConfig}
          </VButton>
        </div>
      ) : null}
      <VSplitWorkspace
        className={styles.registryWorkspace}
        resize={{
          layoutId: WORKBENCH_LAYOUT_IDS.configModelAssets,
          sidebar: { defaultWidth: 224, minWidth: 180, maxWidth: 300 },
          collapse: {
            sidebar: { separatorLabel: copy.navResizeSeparator, collapseLabel: copy.navCollapse, expandLabel: copy.navExpand },
          },
        }}
        sidebar={(
          <div className={styles.providerRail}>
            <div className={styles.providerListSection}>
              <p className={styles.providerListHeading}>{copy.configuredProvidersHeading} · {listRows.length}</p>
              <VEntityList
                ariaLabel={copy.configuredListAria}
                activeId={provider?.providerId}
                className={styles.providerList}
                items={listItems}
                empty={(
                  <VStateSurface tone="empty" title={copy.emptyConfiguredTitle}>
                    {copy.emptyConfiguredNormal}
                  </VStateSurface>
                )}
                renderItem={(row) => (
                  <ProviderListRowItem
                    row={row}
                    selected={provider?.providerId === row.providerId}
                    inspecting={inspectorOpen && provider?.providerId === row.providerId}
                    disabled={disabled}
                    copy={copy}
                    onSelect={() => onSelectProvider(row.providerId)}
                    onToggle={onToggleEnabled}
                  />
                )}
              />
            </div>
            {onAddConnection ? (
              <VButton
                className={styles.providerAddRow}
                variant="ghost"
                contentLayout="plain"
                data-provider-action="add-provider"
                isDisabled={disabled}
                tooltip={copy.addProviderHint}
                onPress={onAddConnection}
              >
                <Plus size={14} />
                <span>{copy.addProvider}</span>
              </VButton>
            ) : null}
          </div>
        )}
        main={provider ? (
          <div className={styles.modelsColumn} data-provider-status={provider.status} data-vui-region="config-models-main">
            {visibleFeedback ? (
              <p
                className={
                  visibleFeedback.phase === "error"
                    ? styles.actionFeedbackError
                    : visibleFeedback.phase === "success"
                      ? styles.actionFeedbackSuccess
                      : styles.actionFeedback
                }
                data-feedback-phase={visibleFeedback.phase}
                data-feedback-kind={visibleFeedback.kind}
                role={visibleFeedback.phase === "error" ? "alert" : "status"}
                aria-live="polite"
              >
                {visibleFeedback.message}
              </p>
            ) : null}
            <div className={styles.providerSettings} data-vui-region="config-provider-connection">
              <VPanelHeader title={provider.label || provider.providerId} headingLevel={3}
                actions={(
                  <VActionGroup ariaLabel={copy.providerHeaderActionsAria} className={styles.actions}>
                    <VButton
                      data-provider-action="detect"
                      variant="secondary"
                      icon={<RefreshCw size={14} />}
                      isDisabled={disabled}
                      title={copy.detectHint}
                      onPress={() => onDiscover(provider.providerId)}
                    >
                      {discoverBusy ? copy.detectBusy : copy.detectAction}
                    </VButton>
                    <VButton data-provider-action="edit-asset" variant="ghost" isDisabled={disabled}
                      onPress={() => openInspector(provider.providerId)}>{copy.advancedManage}</VButton>
                  </VActionGroup>
                )} />
              <p
                className={styles.providerFreshness}
                data-provider-freshness={provider.refreshDue ? "stale" : "fresh"}
              >
                {provider.refreshDue ? copy.catalogStaleLine : copy.catalogFreshLine}
              </p>
              <VSettingsGroupCard>
                <VSettingsRow label={copy.baseUrlRowLabel} description={provider.baseUrl || copy.notConfigured}
                  control={<VButton data-provider-action="route" variant="secondary" isDisabled={disabled}
                    onPress={() => onEditRoute(provider.providerId)}>{copy.editRouteAction}</VButton>}
                  footer={routeActive ? routeEditor : undefined} />
                <VSettingsRow label={copy.protocolRowLabel} description={copy.protocolRowHint}
                  control={<span className={styles.muted}>{provider.defaultProtocol || copy.notConfigured}</span>} />
              </VSettingsGroupCard>
              <ConnectionTab key={provider.providerId}
                provider={provider} contextWindowDraft={contextWindowDraft}
                credentialActive={credentialActive} credentialValue={credentialValue} disabled={disabled}
                copy={copy}
                onContextWindowDraftChange={setContextWindowDraft}
                onSaveContextWindow={() => saveContextWindowFor(provider)}
                onEditCredential={() => onEditCredential(provider.providerId)}
                onCredentialValueChange={onCredentialValueChange} onCancelCredential={onCancelCredential}
                onSaveCredential={() => onSaveCredential(provider.providerId)} />
            </div>
            <div className={styles.detailBody} data-provider-tab="models">
              <ProviderModelsTab
                copy={copy}
                toolbarIdentity={(
              <span className={styles.detailIdentity}>
                <strong title={provider.providerId}>{provider.label || provider.providerId}</strong>
                <small className={styles.muted}>
                  {formatConfigCopy(copy.pinnedModelsTemplate, { count: provider.pinnedCount })}

                </small>
              </span>
                )}
                provider={provider}
                disabled={disabled}
                modelQuery={modelQuery}
                modelFilter={modelFilter}
                liveReferenceCountByModelRef={liveReferenceCountByModelRef}
                onQueryChange={setModelQuery}
                onFilterChange={setModelFilter}
                onPin={onPin}
                onUnpin={onUnpin}
                onTestModel={onTestModel}
                imageCapabilityBusy={imageCapabilityBusy}
                pinBusy={pinBusy}
                onProbeImageInput={onProbeImageInput}
                reasoningFeedbackByModelRef={reasoningFeedbackByModelRef}
                onProbeReasoning={(modelRef) => void probeReasoning(modelRef)}
              />
            </div>
          </div>
        ) : (
          <VStateSurface tone="empty" icon={<Database size={16} />} title={copy.pickProviderTitle}>{copy.pickProviderBody}</VStateSurface>
        )}
      />
      <VDialog
        open={Boolean(inspectorProvider)}
        onOpenChange={(open) => { if (!open) closeInspector(); }}
        title={inspectorProvider ? `${copy.inspectorTitlePrefix}${inspectorProvider.label || inspectorProvider.providerId}` : copy.inspectorTitle}
        description={copy.inspectorDescription}
        size="lg"
      >
        {inspectorProvider ? (
          <div className={styles.inspectorPanel} data-vui-region="config-asset-inspector" data-provider-id={inspectorProvider.providerId}>
            <div className={styles.inspectorBody}>
              {visibleFeedback ? <p className={visibleFeedback.phase === "error" ? styles.actionFeedbackError : styles.actionFeedback} role="status">{visibleFeedback.message}</p> : null}
              <VActionGroup ariaLabel={copy.advancedOpsAria} className={styles.actions}>

                <VButton
                  density="compact"
                  variant="ghost"
                  isDisabled={disabled}
                  onPress={() => setShowAdvancedTools((open) => !open)}
                >
                  {showAdvancedTools ? copy.collapseDiagnostics : copy.diagnosticsMergeAdvanced}
                </VButton>
              </VActionGroup>
              {showAdvancedTools ? (
                <div className={styles.inspectorAdvanced}>
                  <DiagnosticsTab provider={inspectorProvider} disabled={disabled} copy={copy} onDiscover={onDiscover} />
                  {mergeCandidate ? (
                    <VSection
                      className={styles.mergeSection}
                      title={copy.mergeSectionTitle}
                      meta={copy.mergeSectionMeta}
                    >
                      <div className={styles.mergeContent} data-provider-merge-status={mergePreview?.status ?? "idle"}>
                        <p className={styles.muted}>
                          {formatConfigCopy(copy.mergeKeepTemplate, {
                            canonical: mergeCandidate.canonicalProviderId,
                            duplicates: mergeCandidate.duplicateProviderIds.join("、"),
                          })}
                        </p>
                        {mergePreview ? (
                          <div className={styles.mergeFacts}>
                            <VStatusChip tone={mergePreview.status === "READY" ? "success" : "warning"}>{mergePreview.status}</VStatusChip>
                            <span>{formatConfigCopy(copy.mergeModelsToAddTemplate, { count: mergePreview.modelsToAdd.length })}</span>
                          </div>
                        ) : null}
                        {mergeError ? <p className={styles.actionFeedbackError} role="alert">{mergeError}</p> : null}
                        <VActionGroup ariaLabel={copy.mergeActionsAria}>
                          {!mergeResult ? (
                            <VButton isDisabled={disabled || mergeBusy} onPress={() => void previewMerge()}>
                              {mergeBusy ? copy.mergePreviewBusy : copy.mergePreviewAction}
                            </VButton>
                          ) : null}
                          {mergePreview?.status === "READY" && !mergeResult ? (
                            <VButton
                              variant="danger"
                              isDisabled={disabled || mergeBusy || !mergeConfirmed}
                              onPress={() => void applyMerge()}
                            >
                              {copy.applyMerge}
                            </VButton>
                          ) : null}
                        </VActionGroup>
                        {mergePreview?.status === "READY" && !mergeResult ? (
                          <VCheckbox
                            className={styles.mergeConfirmation}
                            isSelected={mergeConfirmed}
                            isDisabled={disabled || mergeBusy}
                            onChange={setMergeConfirmed}
                          >
                            {copy.mergeConfirmLabel}
                          </VCheckbox>
                        ) : null}
                      </div>
                    </VSection>
                  ) : null}
                </div>
              ) : null}
              <div className={styles.dangerZone} data-provider-danger-zone="true">
                <VButton
                  variant="danger"
                  icon={<Trash2 size={14} />}
                  isDisabled={disabled || providerDeleteBlocked}
                  title={providerDeleteBlocked ? copy.deleteProviderBlockedHint : copy.deleteProviderDraftHint}
                  onPress={() => onDeleteProvider(inspectorProvider.providerId)}
                >
                  {copy.deleteProviderAction}
                </VButton>
              </div>
            </div>
          </div>
        ) : null}
      </VDialog>
    </VSurface>
  );
}
