import {
  Blocks,
  ChevronRight,
  Image as ImageIcon,
  Pencil,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Trash2,
} from "lucide-react";
import { type Dispatch, type RefObject, type SetStateAction } from "react";

import {
  ConfigDiscoveredModel,
  ConfigLlmTestResult,
  ConfigModelOption,
  ConfigProviderPresetOption,
} from "../api/types";
import { VButton, VNativeInput, VNativeSelect, VNativeTextarea } from "../components/vui";
import {
  MODEL_CONTRACT_OPTIONS,
  MODEL_PROMPT_CACHE_MODE_OPTIONS,
  MODEL_TOOL_CALLING_MODE_OPTIONS,
  MODEL_TRANSPORT_OPTIONS,
  PROVIDER_COMPAT_MODE_OPTIONS,
  PROVIDER_KIND_OPTIONS,
  type ModelCenterInventoryRow,
  type ModelCenterSummary,
  type ModelScenarioId,
  type ProviderVendorGroup,
} from "./configRouteLogic";
import type { ConfigCopy, ModelDetailsDraft, ModelEditorState } from "./ConfigRoute";
import styles from "./ConfigModelLibraryPanel.styles";

type ImageInputStatusLabelInput =
  | ConfigLlmTestResult
  | { status: "supported" | "unsupported" | "unknown" | "failed"; checkedAt?: string; message?: string }
  | null
  | undefined;

export type ConfigModelLibraryPanelProps = {
  copy: ConfigCopy;
  eyebrow: string;
  modelCenterRows: ModelCenterInventoryRow[];
  modelCenterSummary: ModelCenterSummary;
  modelCapabilityIssueCount: number;
  selectedModelTestId: string;
  modelOptions: ConfigModelOption[];
  modelOptionsById: Map<string, ConfigModelOption>;
  setSelectedModelTestId: (value: string) => void;
  structuredActionsDisabled: boolean;
  busyAction: string;
  onTestSelectedLibraryModel: () => void;
  onCheckModelImageCapabilities: (modelIds: string[]) => void;
  modelEditorRef: RefObject<HTMLDivElement | null>;
  modelEditor: ModelEditorState;
  modelEditorExpanded: boolean;
  setModelEditorExpanded: Dispatch<SetStateAction<boolean>>;
  setModelEditor: Dispatch<SetStateAction<ModelEditorState>>;
  modelEditorError: string;
  setModelEditorError: Dispatch<SetStateAction<string>>;
  providerVendorGroups: ProviderVendorGroup[];
  selectedProviderVendorId: string;
  selectedProviderVendorTemplates: ConfigProviderPresetOption[];
  applyProviderVendor: (vendorId: string) => void;
  applyProviderTemplate: (templateId: string) => void;
  modelScenarioOptions: Array<{ id: ModelScenarioId; label: string }>;
  applyModelScenario: (scenario: ModelScenarioId) => void;
  modelDiscoveryAvailable: boolean;
  onDiscoverModels: () => void;
  discoveredModels: ConfigDiscoveredModel[];
  selectedDiscoveredModelId: string;
  applyDiscoveredModel: (model: ConfigDiscoveredModel) => void;
  modelDiscoveryError: string;
  canSubmitModelEditor: boolean;
  modelEditorRequiredFieldsReady: boolean;
  onSaveModel: () => void;
  onDeleteModel: (modelId: string) => void;
  emptyModelEditorState: () => ModelEditorState;
  hydrateModelEditorFromOption: (option: ConfigModelOption) => ModelEditorState;
  focusModelEditor: () => void;
  keyStateLabel: (state: string) => string;
  imageInputStatusLabel: (result: ImageInputStatusLabelInput) => string;
};

export function ConfigModelLibraryPanel({
  copy,
  eyebrow,
  modelCenterRows,
  modelCenterSummary,
  modelCapabilityIssueCount,
  selectedModelTestId,
  modelOptions,
  modelOptionsById,
  setSelectedModelTestId,
  structuredActionsDisabled,
  busyAction,
  onTestSelectedLibraryModel: handleTestSelectedLibraryModel,
  onCheckModelImageCapabilities: handleCheckModelImageCapabilities,
  modelEditorRef,
  modelEditor,
  modelEditorExpanded,
  setModelEditorExpanded,
  setModelEditor,
  modelEditorError,
  setModelEditorError,
  providerVendorGroups,
  selectedProviderVendorId,
  selectedProviderVendorTemplates,
  applyProviderVendor,
  applyProviderTemplate,
  modelScenarioOptions,
  applyModelScenario,
  modelDiscoveryAvailable,
  onDiscoverModels: handleDiscoverModels,
  discoveredModels,
  selectedDiscoveredModelId,
  applyDiscoveredModel,
  modelDiscoveryError,
  canSubmitModelEditor,
  modelEditorRequiredFieldsReady,
  onSaveModel: handleSaveModel,
  onDeleteModel: handleDeleteModel,
  emptyModelEditorState,
  hydrateModelEditorFromOption,
  focusModelEditor,
  keyStateLabel,
  imageInputStatusLabel,
}: ConfigModelLibraryPanelProps) {
  return (
    <section id="config-models" className={`${styles.sectionSurface} ${styles.modelLibrarySection}`}>
      <div className={styles.sectionHeader}>
        <div>
          <p className={styles.eyebrow}>{eyebrow}</p>
          <h2 className={styles.sectionTitle}>{copy.modelsTitle}</h2>
        </div>
        <Blocks size={16} className={styles.sectionIcon} />
      </div>
      <p className={styles.sectionText} title={copy.modelsBody}>
        {copy.modelsBodyShort}
      </p>
      <div className={styles.modelCenterSummaryBar}>
        <span>
          <strong>{modelCenterRows.length}</strong> {copy.modelCenterModels}
        </span>
        <span>
          <strong>{modelCenterSummary.accounts.length}</strong> {copy.modelCenterAccounts}
        </span>
        <span className={modelCapabilityIssueCount ? styles.summaryBarWarning : undefined}>
          <strong>{modelCapabilityIssueCount}</strong> {copy.modelCenterCapabilityIssues}
        </span>
      </div>
      <div className={styles.modelLibraryTestBar}>
        <label className={`${styles.field} ${styles.modelLibraryTestSelect}`}>
          <span>{copy.modelTestSelect}</span>
          <VNativeSelect
            value={selectedModelTestId}
            disabled={structuredActionsDisabled || !modelOptions.length}
            onChange={(event) => setSelectedModelTestId(event.target.value)}
          >
            {modelOptions.length ? null : <option value="">{copy.modelTestPlaceholder}</option>}
            {modelOptions.map((option) => (
              <option key={option.model_id} value={option.model_id}>
                {option.label || option.model || option.model_id}
              </option>
            ))}
          </VNativeSelect>
        </label>
        <VButton
          type="button"
          className={styles.primaryButton}
          isDisabled={structuredActionsDisabled || busyAction === copy.testPending || !selectedModelTestId}
          title={selectedModelTestId ? copy.testSelectedLibraryModel : copy.modelTestRequired}
          onClick={handleTestSelectedLibraryModel}
        >
          <Play size={14} />
          {busyAction === copy.testPending ? copy.testPending : copy.testSelectedLibraryModel}
        </VButton>
        <VButton
          type="button"
          className={styles.actionButton}
          isDisabled={structuredActionsDisabled || busyAction === copy.imageCapabilityCheckPending || !selectedModelTestId}
          title={selectedModelTestId ? copy.checkSavedImageCapabilities : copy.modelTestRequired}
          onClick={() => handleCheckModelImageCapabilities([selectedModelTestId])}
        >
          <ImageIcon size={14} />
          {busyAction === copy.imageCapabilityCheckPending ? copy.imageCapabilityCheckPending : copy.checkSavedImageCapabilities}
        </VButton>
      </div>
      <div
        ref={modelEditorRef}
        className={styles.formSurface}
        onChange={() => (modelEditorError ? setModelEditorError("") : undefined)}
      >
        <div className={styles.formHeader}>
          <div className={styles.formHeaderIntro}>
            <Pencil size={16} />
            <span>{modelEditor.mode === "edit" ? copy.modelEditorEdit : copy.modelEditorCreate}</span>
          </div>
          <VButton
            type="button"
            className={`${styles.actionButton} ${styles.compactButton}`}
            aria-expanded={modelEditorExpanded}
            isDisabled={structuredActionsDisabled}
            onClick={() => setModelEditorExpanded((current) => !current)}
          >
            <ChevronRight size={14} className={modelEditorExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
            {modelEditorExpanded ? copy.collapseSection : copy.expandSection}
          </VButton>
        </div>
        {modelEditorExpanded ? (
          <>
            {modelEditor.mode === "create" ? (
              <>
                <div className={styles.modelScenarioPicker}>
                  <span>{copy.modelScenario}</span>
                  <div className={styles.modelScenarioButtons}>
                    {modelScenarioOptions.map((scenario) => (
                      <VButton
                        key={scenario.id}
                        type="button"
                        className={styles.actionButton}
                        onClick={() => applyModelScenario(scenario.id)}
                      >
                        {scenario.id === "image" ? <ImageIcon size={14} /> : <Blocks size={14} />}
                        {scenario.label}
                      </VButton>
                    ))}
                  </div>
                </div>
                <p className={styles.fieldHint}>{copy.modelScenarioHint}</p>
              </>
            ) : null}
            <div className={styles.formGridWide}>
              <label className={styles.field}>
                <span>{copy.providerVendor}</span>
                <VNativeSelect value={selectedProviderVendorId} onChange={(event) => applyProviderVendor(event.target.value)}>
                  <option value="">{copy.customEntry}</option>
                  {providerVendorGroups.map((group) => (
                    <option key={group.id} value={group.id}>
                      {group.label}
                    </option>
                  ))}
                </VNativeSelect>
              </label>
              <label className={styles.field}>
                <span>{copy.providerTemplate}</span>
                <VNativeSelect
                  value={modelEditor.provider_template_id}
                  disabled={!selectedProviderVendorTemplates.length}
                  onChange={(event) => applyProviderTemplate(event.target.value)}
                >
                  <option value="">{copy.providerTemplatePlaceholder}</option>
                  {selectedProviderVendorTemplates.map((template: ConfigProviderPresetOption) => (
                    <option key={template.provider_preset_id} value={template.provider_preset_id}>
                      {template.label}
                    </option>
                  ))}
                </VNativeSelect>
              </label>
              <label className={styles.field}>
                <span>{copy.modelId}</span>
                <VNativeInput
                  value={modelEditor.model_id}
                  onChange={(event) => setModelEditor((current) => ({ ...current, model_id: event.target.value }))}
                  disabled={modelEditor.mode === "edit"}
                  placeholder={copy.autoValue}
                />
              </label>
              <label className={styles.field}>
                <span>{copy.label}</span>
                <VNativeInput value={modelEditor.label} onChange={(event) => setModelEditor((current) => ({ ...current, label: event.target.value }))} />
              </label>
              <label className={styles.field}>
                <span>{copy.modelName}</span>
                <VNativeInput value={modelEditor.model} onChange={(event) => setModelEditor((current) => ({ ...current, model: event.target.value }))} />
              </label>
              <label className={styles.field}>
                <span>{copy.providerKind}</span>
                <VNativeSelect
                  value={modelEditor.provider.kind}
                  onChange={(event) =>
                    setModelEditor((current) => ({
                      ...current,
                      provider: { ...current.provider, kind: event.target.value },
                    }))
                  }
                >
                  {PROVIDER_KIND_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </VNativeSelect>
              </label>
              <label className={styles.field}>
                <span>{copy.baseUrl}</span>
                <VNativeInput
                  value={modelEditor.provider.base_url}
                  onChange={(event) =>
                    setModelEditor((current) => ({
                      ...current,
                      provider: { ...current.provider, base_url: event.target.value },
                    }))
                  }
                />
              </label>
              <label className={styles.field}>
                <span>{copy.modelKeyInput}</span>
                <VNativeInput
                  type="password"
                  value={modelEditor.api_key}
                  onChange={(event) => setModelEditor((current) => ({ ...current, api_key: event.target.value }))}
                  placeholder={modelEditor.api_key_env || copy.autoValue}
                />
              </label>
            </div>
            <p className={styles.fieldHint}>{copy.keyStorageHint}</p>

            <div className={styles.actionsRow}>
              <VButton
                type="button"
                className={styles.actionButton}
                isDisabled={structuredActionsDisabled || busyAction === copy.discoveryPending || !modelDiscoveryAvailable}
                title={modelDiscoveryAvailable ? copy.discoverModels : copy.discoveryUnavailable}
                onClick={handleDiscoverModels}
              >
                <RefreshCw size={14} />
                {busyAction === copy.discoveryPending ? copy.discoveryPending : copy.discoverModels}
              </VButton>
              {!modelDiscoveryAvailable && modelEditor.provider.base_url.trim() ? (
                <span className={styles.helperText}>{copy.discoveryUnavailable}</span>
              ) : null}
              {discoveredModels.length ? (
                <label className={`${styles.field} ${styles.profileTableSelect}`}>
                  <span>{copy.discoveredModel}</span>
                  <VNativeSelect
                    value={selectedDiscoveredModelId}
                    onChange={(event) => {
                      const selected = discoveredModels.find((item) => item.id === event.target.value);
                      if (selected) {
                        applyDiscoveredModel(selected);
                      }
                    }}
                  >
                    {discoveredModels.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.label || model.id}
                      </option>
                    ))}
                  </VNativeSelect>
                </label>
              ) : null}
              {modelDiscoveryError ? (
                <span className={styles.inlineFormError}>
                  {copy.discoveryFailed}: {modelDiscoveryError}
                </span>
              ) : null}
            </div>

            <details className={styles.advancedEditorPanel}>
              <summary>
                <span>{copy.modelEditorAdvancedTitle}</span>
                <small>{copy.modelEditorAdvancedHint}</small>
              </summary>
              <p className={styles.fieldHint}>{copy.keyEnvAdvancedHint}</p>
              <div className={styles.formGridWide}>
                <label className={styles.field}>
                  <span>{copy.providerKeyEnv}</span>
                  <code className={styles.readonlyCodeField} aria-readonly="true">
                    {modelEditor.provider.api_key_env || copy.autoValue}
                  </code>
                </label>
                <label className={styles.field}>
                  <span>{copy.modelKeyEnv}</span>
                  <code className={styles.readonlyCodeField} aria-readonly="true">
                    {modelEditor.api_key_env || copy.autoValue}
                  </code>
                </label>
                <label className={styles.field}>
                  <span>{copy.compatMode}</span>
                  <VNativeSelect
                    value={modelEditor.provider.compat_mode}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        provider: { ...current.provider, compat_mode: event.target.value },
                      }))
                    }
                  >
                    {PROVIDER_COMPAT_MODE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </VNativeSelect>
                </label>
                <label className={styles.field}>
                  <span>{copy.providerApi}</span>
                  <VNativeInput
                    value={modelEditor.provider.api}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        provider: { ...current.provider, api: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className={styles.field}>
                  <span>{copy.contextWindow}</span>
                  <VNativeInput
                    value={modelEditor.provider.context_window}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        provider: { ...current.provider, context_window: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className={styles.field}>
                  <span>{copy.transport}</span>
                  <VNativeSelect
                    value={modelEditor.details.transport}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: { ...current.details, transport: event.target.value },
                      }))
                    }
                  >
                    {MODEL_TRANSPORT_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </VNativeSelect>
                </label>
                <label className={styles.field}>
                  <span>{copy.contract}</span>
                  <VNativeSelect
                    value={modelEditor.details.contract}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: { ...current.details, contract: event.target.value },
                      }))
                    }
                  >
                    {MODEL_CONTRACT_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </VNativeSelect>
                </label>
                <label className={styles.field}>
                  <span>{copy.modelProtocol}</span>
                  <VNativeInput
                    value={modelEditor.details.protocol}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: { ...current.details, protocol: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className={styles.field}>
                  <span>{copy.reasoningStateField}</span>
                  <VNativeInput
                    value={modelEditor.details.reasoning_state_field}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: { ...current.details, reasoning_state_field: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className={styles.field}>
                  <span>{copy.toolCallingMode}</span>
                  <VNativeSelect
                    value={modelEditor.details.tool_calling_mode}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: { ...current.details, tool_calling_mode: event.target.value },
                      }))
                    }
                  >
                    {MODEL_TOOL_CALLING_MODE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </VNativeSelect>
                </label>
                <label className={styles.field}>
                  <span>{copy.promptCacheMode}</span>
                  <VNativeSelect
                    value={modelEditor.details.prompt_cache_mode}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: {
                          ...current.details,
                          prompt_cache_mode: event.target.value,
                          prompt_cache_configured: true,
                        },
                      }))
                    }
                  >
                    {MODEL_PROMPT_CACHE_MODE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </VNativeSelect>
                </label>
                <label className={`${styles.field} ${styles.formGridWideSpan}`}>
                  <span>{copy.modelCompat}</span>
                  <VNativeTextarea
                    value={modelEditor.details.compat}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: { ...current.details, compat: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className={styles.field}>
                  <span>{copy.temperature}</span>
                  <VNativeInput
                    value={modelEditor.details.temperature}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: { ...current.details, temperature: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className={styles.field}>
                  <span>{copy.maxOutputTokens}</span>
                  <VNativeInput
                    value={modelEditor.details.max_output_tokens}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: { ...current.details, max_output_tokens: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className={styles.field}>
                  <span>{copy.timeout}</span>
                  <VNativeInput
                    value={modelEditor.details.timeout}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: { ...current.details, timeout: event.target.value },
                      }))
                    }
                  />
                </label>
                <label className={styles.field}>
                  <span>{copy.connectTimeout}</span>
                  <VNativeInput
                    value={modelEditor.details.connect_timeout}
                    onChange={(event) =>
                      setModelEditor((current) => ({
                        ...current,
                        details: { ...current.details, connect_timeout: event.target.value },
                      }))
                    }
                  />
                </label>
              </div>
            </details>

            <div className={styles.toggleGrid}>
              <label className={styles.toggleField}>
                <VNativeInput
                  type="checkbox"
                  checked={modelEditor.provider.requires_api_key}
                  onChange={(event) =>
                    setModelEditor((current) => ({
                      ...current,
                      provider: { ...current.provider, requires_api_key: event.target.checked },
                    }))
                  }
                />
                <span>{copy.requiresApiKey}</span>
              </label>
              <label className={styles.field}>
                <span>{copy.imageInputSupport}</span>
                <VNativeSelect
                  value={modelEditor.details.supports_image_input}
                  onChange={(event) =>
                    setModelEditor((current) => ({
                      ...current,
                      details: {
                        ...current.details,
                        supports_image_input: event.target.value as ModelDetailsDraft["supports_image_input"],
                      },
                    }))
                  }
                >
                  <option value="unknown">{copy.imageInputSupportUnknown}</option>
                  <option value="supported">{copy.imageInputSupportSupported}</option>
                  <option value="unsupported">{copy.imageInputSupportUnsupported}</option>
                </VNativeSelect>
              </label>
              <label className={styles.toggleField}>
                <VNativeInput
                  type="checkbox"
                  checked={modelEditor.details.strict_compatibility}
                  onChange={(event) =>
                    setModelEditor((current) => ({
                      ...current,
                      details: { ...current.details, strict_compatibility: event.target.checked },
                    }))
                  }
                />
                <span>{copy.strictCompatibility}</span>
              </label>
              <label className={styles.toggleField}>
                <VNativeInput
                  type="checkbox"
                  checked={modelEditor.details.streaming}
                  onChange={(event) =>
                    setModelEditor((current) => ({
                      ...current,
                      details: { ...current.details, streaming: event.target.checked },
                    }))
                  }
                />
                <span>{copy.streaming}</span>
              </label>
              <label className={styles.toggleField}>
                <VNativeInput
                  type="checkbox"
                  checked={modelEditor.details.discovery_enabled}
                  onChange={(event) =>
                    setModelEditor((current) => ({
                      ...current,
                      details: { ...current.details, discovery_enabled: event.target.checked },
                    }))
                  }
                />
                <span>{copy.discoveryEnabled}</span>
              </label>
              <label className={styles.toggleField}>
                <VNativeInput
                  type="checkbox"
                  checked={modelEditor.clear_api_key}
                  onChange={(event) => setModelEditor((current) => ({ ...current, clear_api_key: event.target.checked }))}
                />
                <span>{copy.clearSecret}</span>
              </label>
            </div>
            <p className={styles.fieldHint}>{copy.deleteModelHint}</p>

            <div className={styles.actionsRow}>
              <VButton
                type="button"
                className={styles.primaryButton}
                isDisabled={!canSubmitModelEditor}
                title={modelEditorRequiredFieldsReady ? undefined : copy.modelRequiredFieldsMissing}
                onClick={handleSaveModel}
              >
                <Save size={14} />
                {copy.saveModel}
              </VButton>
              <VButton
                type="button"
                className={styles.actionButton}
                isDisabled={structuredActionsDisabled}
                onClick={() => {
                  setModelEditorError("");
                  setModelEditor(emptyModelEditorState());
                  setModelEditorExpanded(false);
                }}
              >
                <RotateCcw size={14} />
                {copy.cancelEditing}
              </VButton>
              {modelEditor.mode === "edit" ? (
                <VButton
                  type="button"
                  className={styles.dangerButton}
                  isDisabled={structuredActionsDisabled}
                  onClick={() => handleDeleteModel(modelEditor.model_id)}
                >
                  <Trash2 size={14} />
                  {copy.deleteModel}
                </VButton>
              ) : null}
            </div>
            {modelEditorError ? (
              <p className={styles.inlineFormError} role="alert" aria-live="assertive">
                <strong>{copy.modelSaveFailed}</strong> {modelEditorError}
              </p>
            ) : null}
          </>
        ) : null}
      </div>

      <div className={styles.profileTableWrap}>
        <table className={`${styles.profileTable} ${styles.modelInventoryTable}`}>
          <thead>
            <tr>
              <th>{copy.modelCenterInventory}</th>
              <th>{copy.providerKind}</th>
              <th>{copy.modelId}</th>
              <th>{copy.modelCenterHealth}</th>
              <th>{copy.modelCenterProtocol}</th>
              <th>{copy.modelCenterActions}</th>
            </tr>
          </thead>
          <tbody>
            {modelCenterRows.map((row) => {
              const option = modelOptionsById.get(row.modelId);
              return (
                <tr key={row.modelId}>
                  <td className={styles.profileTaskCell}>
                    <strong>{row.label}</strong>
                    <span>{row.model}</span>
                  </td>
                  <td className={styles.profileMetaCell}>
                    <strong>{row.providerKind}</strong>
                    <span>{row.baseUrl || "-"}</span>
                  </td>
                  <td className={styles.profileMetaCell}>
                    <strong>{row.modelId}</strong>
                    <span>{row.apiKeyEnv || copy.autoValue}</span>
                  </td>
                  <td className={styles.profileMetaCell}>
                    <span
                      className={
                        row.apiKeyState === "missing" || row.apiKeyState === "clear_pending"
                          ? `${styles.inlineBadge} ${styles.inlineBadgeWarning}`
                          : styles.inlineBadge
                      }
                    >
                      {keyStateLabel(row.apiKeyState)}
                    </span>
                    <span
                      className={
                        row.imageInputStatus === "supported"
                          ? `${styles.inlineBadge} ${styles.inlineBadgeSuccess}`
                          : row.imageInputStatus === "unsupported"
                            ? `${styles.inlineBadge} ${styles.inlineBadgeWarning}`
                            : styles.inlineBadge
                      }
                      title={row.capabilityError || row.capabilityCheckedAt || row.capabilitySource || copy.imageCapabilityStatus}
                    >
                      {imageInputStatusLabel({
                        status: row.imageInputStatus,
                        message: row.capabilityError,
                        checkedAt: row.capabilityCheckedAt,
                      })}
                    </span>
                  </td>
                  <td className={styles.profileMetaCell}>
                    <strong>{row.resolvedProtocol}</strong>
                    <span>{row.protocolSource}</span>
                    <span>{row.providerApi || "-"}</span>
                    {row.compatSummary ? <span>{row.compatSummary}</span> : null}
                    {row.protocolWarnings.length ? (
                      <span className={`${styles.inlineBadge} ${styles.inlineBadgeWarning}`} title={row.protocolWarnings.join("\n")}>
                        {row.protocolWarnings.length}
                      </span>
                    ) : null}
                  </td>
                  <td>
                    <div className={styles.profileTableActions}>
                      <VButton
                        type="button"
                        className={`${styles.actionButton} ${styles.compactButton}`}
                        isDisabled={structuredActionsDisabled || !row.editable || !option}
                        onClick={() => {
                          if (!option) {
                            return;
                          }
                          setModelEditorError("");
                          setModelEditor(hydrateModelEditorFromOption(option));
                          setModelEditorExpanded(true);
                          focusModelEditor();
                        }}
                      >
                        <Pencil size={14} />
                        {copy.modelEditorEdit}
                      </VButton>
                      <VButton
                        type="button"
                        className={`${styles.dangerButton} ${styles.compactButton}`}
                        isDisabled={structuredActionsDisabled || !row.deletable}
                        onClick={() => handleDeleteModel(row.modelId)}
                      >
                        <Trash2 size={14} />
                        {copy.deleteModel}
                      </VButton>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
