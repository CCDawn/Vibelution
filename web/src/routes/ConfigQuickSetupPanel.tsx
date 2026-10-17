import { useEffect, useId, useRef, useState } from "react";
import { CheckCircle2, Search } from "lucide-react";

import type { ConfigProviderPresetOption } from "../api/types";
import { VButton, VFieldRow, VInput, VNativeSelect, VSection } from "../components/vui";
import {
  providerPresetToWizardState,
  type ProviderAuthKind,
  type ProviderQuickSetupState,
  type ProviderWizardState,
} from "./configProviderLogic";
import type { ConfigCopy } from "./config/configCopy";
import styles from "./ConfigQuickSetupPanel.styles";

export type ConfigQuickSetupPanelProps = {
  copy: ConfigCopy;
  state: ProviderQuickSetupState;
  templates: ConfigProviderPresetOption[];
  credentialValue: string;
  disabled: boolean;
  onCredentialChange: (value: string) => void;
  onProviderChange: (provider: ProviderWizardState) => void;
  onDetect: (input: { provider: ProviderWizardState; credentialValue: string }) => void;
  onModelChange: (modelRef: string) => void;
  onConfirm: () => void;
  onReset: () => void;
  onConfigureAgent?: () => void;
  onTestAndSave?: (input: { provider: ProviderWizardState; credentialValue: string; modelId: string }) => void;
  onCancel?: () => void;
};

function templateModelId(template?: ConfigProviderPresetOption): string {
  return typeof template?.default_model.model === "string" ? template.default_model.model : "";
}

// Kept for callers that imported the old panel helper.
export const templateToProvider = providerPresetToWizardState;

export function ConfigQuickSetupPanel({
  copy, state, templates, credentialValue, disabled, onCredentialChange,
  onProviderChange, onDetect, onModelChange, onConfirm, onReset,
  onConfigureAgent, onTestAndSave, onCancel,
}: ConfigQuickSetupPanelProps) {
  const id = useId();
  const selectedTemplate = templates.find((template) => template.provider_preset_id === state.provider.templateId);
  const customTemplate = templates.find((template) => template.provider_preset_id === "custom_openai_compatible_relay");
  const [modelDraft, setModelDraft] = useState({ templateId: state.provider.templateId, value: templateModelId(selectedTemplate) });
  const submittedModelId = useRef("");
  const modelId = modelDraft.templateId === state.provider.templateId ? modelDraft.value : templateModelId(selectedTemplate);
  // Provider IDs may be suggested asynchronously. Only a different template resets user input.
  useEffect(() => {
    setModelDraft((current) => current.templateId === state.provider.templateId
      ? current : { templateId: state.provider.templateId, value: templateModelId(selectedTemplate) });
  }, [state.provider.templateId, selectedTemplate]);

  const busy = state.phase === "checking" || state.phase === "saving";
  const locked = disabled || busy;
  const requiresCredential = state.provider.authKind !== "none";
  const missingConnection = !state.provider.templateId ? copy.quickSetupPickProviderFirst
    : !state.provider.label.trim() ? copy.quickSetupFillNameFirst
      : !state.provider.baseUrl.trim() ? copy.quickSetupFillBaseUrlFirst
        : requiresCredential && !credentialValue.trim() ? copy.quickSetupFillKeyFirst : "";
  const disabledReason = disabled ? copy.quickSetupDisabledReason : busy ? copy.quickSetupBusyReason
    : missingConnection || (!modelId.trim() ? copy.quickSetupFillModelFirst : undefined);
  const error = state.phase === "error" ? state.errorMessage || copy.quickSetupErrorFallback : "";
  const credentialError = state.errorKind === "auth" ? error : "";
  const endpointError = state.errorKind === "endpoint" ? error : "";
  const modelError = ["discovery", "no_recommendation"].includes(state.errorKind) ? error : "";
  const saveError = error && !credentialError && !endpointError && !modelError ? error : "";
  const savedModelId = submittedModelId.current
    || state.discoveredModels.find((model) => model.modelRef === state.selectedModelRef)?.upstreamId || modelId;
  const selectedCatalogModel = state.discoveredModels.find((model) => model.upstreamId === modelId);

  function submit() {
    if (disabledReason) return;
    submittedModelId.current = modelId.trim();
    if (onTestAndSave) onTestAndSave({ provider: state.provider, credentialValue, modelId: modelId.trim() });
    else if (state.phase === "review" || ["partial_save", "save"].includes(state.errorKind)) onConfirm();
    else onDetect({ provider: state.provider, credentialValue });
  }

  return <VSection className={styles.root} title={copy.quickSetupTitle}>
    <form className={styles.workspace} onSubmit={(event) => { event.preventDefault(); submit(); }} noValidate>
      <fieldset className={styles.inputPanel} disabled={locked}>
        <legend className="sr-only">{copy.quickSetupTitle}</legend>
        <div className={styles.twoFields}>
          <VFieldRow label={copy.quickSetupProviderLabel} htmlFor={`${id}-provider`}>
            <VNativeSelect className={styles.control} id={`${id}-provider`} value={state.provider.templateId} onChange={(event) => {
              const templateId = event.target.value;
              const template = templateId === "custom" ? customTemplate : templates.find((item) => item.provider_preset_id === templateId);
              if (!template) return;
              const provider = templateToProvider(template);
              onProviderChange(templateId === "custom" ? { ...provider, label: "", baseUrl: "" } : provider);
            }}>
              <option value="" disabled>{copy.quickSetupProviderPlaceholder}</option>
              {templates.map((template) => <option key={template.provider_preset_id} value={template.provider_preset_id}>{template.label}</option>)}
              <option value="custom" disabled={!customTemplate}>{copy.quickSetupCustomService}</option>
            </VNativeSelect>
          </VFieldRow>
          <VFieldRow label={copy.label} htmlFor={`${id}-label`}>
            <VInput className={styles.control} id={`${id}-label`} value={state.provider.label} onChange={(event) => onProviderChange({ ...state.provider, label: event.target.value })} />
          </VFieldRow>
        </div>
        <VFieldRow label={copy.routeFieldBaseUrl} htmlFor={`${id}-endpoint`}>
          <VInput className={styles.control} id={`${id}-endpoint`} type="url" value={state.provider.baseUrl} spellCheck={false} placeholder={copy.quickSetupBaseUrlPlaceholder}
            aria-invalid={!!endpointError} aria-describedby={endpointError ? `${id}-endpoint-error` : undefined}
            onChange={(event) => onProviderChange({ ...state.provider, baseUrl: event.target.value })} />
          {endpointError && <span id={`${id}-endpoint-error`} className={styles.error} role="alert">{endpointError}</span>}
        </VFieldRow>
        <VFieldRow label={copy.apiKeyRowLabel} htmlFor={`${id}-credential`}>
          {requiresCredential ? <VInput className={styles.control} id={`${id}-credential`} type="password" autoComplete="new-password" value={credentialValue}
            placeholder={copy.quickSetupKeyPlaceholder} aria-invalid={!!credentialError} aria-describedby={credentialError ? `${id}-credential-error` : undefined}
            onChange={(event) => onCredentialChange(event.target.value)} />
            : <span className={styles.noCredential}><CheckCircle2 size={14} aria-hidden="true" />{copy.quickSetupNoCredential}</span>}
          {credentialError && <span id={`${id}-credential-error`} className={styles.error} role="alert">{credentialError}</span>}
        </VFieldRow>
        <VFieldRow label={copy.modelId} htmlFor={`${id}-model`}>
          <div className={styles.modelInput}>
            <VInput className={styles.control} id={`${id}-model`} value={modelId} spellCheck={false} aria-describedby={`${id}-model-hint`}
              onChange={(event) => setModelDraft({ templateId: state.provider.templateId, value: event.target.value })} />
            <VButton type="button" variant="secondary" icon={<Search size={14} />} className={styles.detectAction} isDisabled={locked || !!missingConnection}
              disabledReason={locked ? copy.quickSetupBusyReason : missingConnection || undefined} onPress={() => onDetect({ provider: state.provider, credentialValue })}>
              {copy.quickSetupGetModels}
            </VButton>
          </div>
          <span id={`${id}-model-hint`} className={modelError ? styles.error : styles.hint} role={modelError ? "alert" : undefined}>
            {modelError ? `${modelError} ${copy.quickSetupModelIdHint}` : copy.quickSetupModelIdHint}
          </span>
        </VFieldRow>
        {state.discoveredModels.length > 0 && <VFieldRow label={copy.quickSetupModelListLabel} htmlFor={`${id}-catalog`}>
          <VNativeSelect className={styles.control} id={`${id}-catalog`} value={selectedCatalogModel?.modelRef || ""} onChange={(event) => {
            const model = state.discoveredModels.find((candidate) => candidate.modelRef === event.target.value);
            if (!model?.upstreamId) return;
            setModelDraft({ templateId: state.provider.templateId, value: model.upstreamId }); onModelChange(model.modelRef);
          }}>
            <option value="">{copy.quickSetupKeepManualModel}</option>
            {state.discoveredModels.filter((model) => model.upstreamId).map((model) => <option key={model.modelRef} value={model.modelRef}>{model.label || model.upstreamId} · {model.upstreamId}</option>)}
          </VNativeSelect>
        </VFieldRow>}
        <details className={styles.advanced}>
          <summary className={styles.advancedSummary}>{copy.quickSetupAdvanced}</summary>
          <div className={styles.twoFields}>
            <VFieldRow label={copy.quickSetupProtocolLabel} htmlFor={`${id}-protocol`}>
              <VNativeSelect className={styles.control} id={`${id}-protocol`} value={state.provider.defaultProtocol} onChange={(event) => {
                const protocol = event.target.value;
                onProviderChange({ ...state.provider, defaultProtocol: protocol, allowedProtocols: [protocol], driver: protocol === "anthropic_messages" ? "anthropic" : protocol === "gemini_generate_content" ? "gemini" : "openai" });
              }}>
                <option value="chat_completions">{copy.quickSetupChatCompletionsLabel}</option><option value="responses">OpenAI Responses</option>
                <option value="anthropic_messages">Anthropic Messages</option><option value="gemini_generate_content">Gemini</option>
              </VNativeSelect>
            </VFieldRow>
            <VFieldRow label={copy.quickSetupAuthMethodLabel} htmlFor={`${id}-auth`}>
              <VNativeSelect className={styles.control} id={`${id}-auth`} value={state.provider.authKind} onChange={(event) => {
                const authKind = event.target.value as ProviderAuthKind;
                const template = selectedTemplate || customTemplate;
                const credentialRef = authKind === "none" ? "none" : template ? templateToProvider(template).credentialRef
                  : state.provider.credentialRef === "none" ? "" : state.provider.credentialRef;
                onProviderChange({ ...state.provider, authKind, credentialRef });
              }}>
                <option value="api_key">API Key</option><option value="none">{copy.quickSetupNoAuthLabel}</option>
                {state.provider.authKind === "oauth" && <option value="oauth">OAuth</option>}
              </VNativeSelect>
            </VFieldRow>
          </div>
        </details>
      </fieldset>
      <div className={styles.footer}>
        <div className={styles.feedback} aria-live="polite" data-quick-setup-result={state.phase !== "input" ? "true" : undefined}>
          {saveError ? <span className={styles.error} role="alert">{saveError}</span>
            : state.phase === "success" ? <span className={styles.success}><CheckCircle2 size={15} aria-hidden="true" />{copy.quickSetupSavedBody}<span className={styles.savedModel}>{savedModelId}</span></span>
              : busy ? state.phase === "saving" ? copy.quickSetupSavingTitle : copy.quickSetupCheckingTitle : copy.quickSetupReadyHint}
        </div>
        <div className={styles.actions}>
          {state.phase === "success" && onConfigureAgent && <VButton type="button" variant="secondary" isDisabled={locked} onPress={onConfigureAgent}>{copy.quickSetupGoAgents}</VButton>}
          <VButton type="button" variant="secondary" isDisabled={locked} onPress={onCancel || onReset}>{copy.cancel}</VButton>
          <VButton type="submit" variant="primary" className={styles.primaryAction} isPending={busy} isDisabled={!!disabledReason} disabledReason={disabledReason}>{copy.quickSetupTestAndSave}</VButton>
        </div>
      </div>
    </form>
  </VSection>;
}
