import { CheckCircle2, KeyRound, Search, Sparkles } from "lucide-react";

import type { ConfigProviderPresetOption } from "../api/types";
import {
  VButton,
  VInput,
  VSection,
  VStateSurface,
  VStatusChip,
  VStringSelect,
} from "../components/vui";
import {
  initialProviderWizardState,
  type ProviderAuthKind,
  type ProviderQuickSetupState,
  type ProviderWizardState,
} from "./configProviderLogic";
import type { ConfigCopy } from "./config/configCopy";
import styles from "./ConfigQuickSetupPanel.styles";

export type ConfigQuickSetupPanelProps = {
  /** Bilingual copy table (wave 4). */
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
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function templateServiceClass(template: ConfigProviderPresetOption): string {
  const provider = asRecord(template.provider);
  const declared = asString(provider.service_class);
  if (declared) return declared;
  if (template.category === "local") return "local_runtime";
  if (template.category === "official") return "official_api";
  if (template.category === "relay") return "relay";
  return "self_hosted";
}

export function templateToProvider(template: ConfigProviderPresetOption): ProviderWizardState {
  const provider = asRecord(template.provider);
  const model = asRecord(template.default_model);
  const protocols = asRecord(provider.protocols);
  const deployment = asRecord(provider.deployment);
  const credentialRef = asString(provider.credential_ref);
  const rawAuthKind = asString(provider.auth_kind);
  const authKind: ProviderAuthKind = rawAuthKind === "none" || rawAuthKind === "oauth" || rawAuthKind === "api_key"
    ? rawAuthKind
    : provider.requires_api_key === false || provider.requires_credential === false || credentialRef === "none"
      ? "none" : "api_key";
  const allowedProtocols = asStringArray(protocols.allowed);
  const defaultProtocol = asString(protocols.default) || allowedProtocols[0] || asString(model.transport) || "chat_completions";
  return {
    ...initialProviderWizardState(),
    templateId: template.provider_preset_id,
    serviceClass: templateServiceClass(template),
    providerId: template.provider_id,
    label: template.label,
    baseUrl: asString(provider.base_url).includes(".example.com") ? "" : asString(provider.base_url),
    authKind,
    credentialRef: authKind === "none" ? "none" : credentialRef,
    driver: asString(provider.driver) || (defaultProtocol === "anthropic_messages" ? "anthropic" : defaultProtocol === "gemini_generate_content" ? "gemini" : "openai"),
    defaultProtocol,
    allowedProtocols: allowedProtocols.length ? allowedProtocols : [defaultProtocol],
    runtimeFramework: asString(deployment.runtime_framework),
    artifactPath: asString(deployment.artifact_path),
  };
}

function resultCopy(state: ProviderQuickSetupState, copy: ConfigCopy) {
  if (state.phase === "checking") return { title: copy.quickSetupCheckingTitle, tone: "loading" as const };
  if (state.phase === "review") return { title: copy.quickSetupReviewTitle, tone: "info" as const };
  if (state.phase === "saving") return { title: copy.quickSetupSavingTitle, tone: "loading" as const };
  if (state.phase === "success") return { title: copy.quickSetupSuccessTitle, tone: "info" as const };
  if (state.phase === "error") return { title: copy.quickSetupErrorTitle, tone: "error" as const };
  return { title: copy.quickSetupIdleTitle, tone: "empty" as const };
}

function phaseLabel(state: ProviderQuickSetupState, copy: ConfigCopy): string {
  if (state.phase === "checking") return copy.quickSetupPhaseChecking;
  if (state.phase === "review") return copy.quickSetupPhaseReview;
  if (state.phase === "saving") return copy.quickSetupPhaseSaving;
  if (state.phase === "success") return copy.quickSetupPhaseSuccess;
  if (state.phase === "error") return copy.quickSetupPhaseError;
  return copy.quickSetupPhaseIdle;
}

export function ConfigQuickSetupPanel({
  copy,
  state,
  templates,
  credentialValue,
  disabled,
  onCredentialChange,
  onProviderChange,
  onDetect,
  onModelChange,
  onConfirm,
  onReset,
  onConfigureAgent,
}: ConfigQuickSetupPanelProps) {
  const result = resultCopy(state, copy);
  const selectedTemplate = templates.find((template) => template.provider_preset_id === state.provider.templateId);
  const canDetect = Boolean(
    state.provider.templateId
    && state.provider.baseUrl.trim()
    && (state.provider.authKind === "none" || credentialValue.trim())
    && !disabled
    && state.phase !== "checking"
    && state.phase !== "saving",
  );
  const retrySave = state.phase === "error" && ["partial_save", "save"].includes(state.errorKind);
  const canConfirm = (state.phase === "review" || retrySave) && Boolean(state.selectedModelRef) && !disabled;
  const showResult = state.phase !== "input";
  const showDetectAction = state.phase === "input" || state.phase === "checking" || (state.phase === "error" && !retrySave);
  const showReviewActions = state.phase === "review" || state.phase === "saving" || retrySave;
  const detectLabel = state.phase === "checking"
    ? copy.quickSetupDetecting
    : state.phase === "error"
      ? copy.quickSetupRedetect
      : copy.quickSetupDetect;
  const resultFacts = [
    { key: "provider", label: "Provider", value: state.provider.label || selectedTemplate?.label || "-" },
    { key: "endpoint", label: copy.quickSetupFactEndpoint, value: state.provider.baseUrl || "-" },
    { key: "protocol", label: copy.quickSetupFactProtocol, value: state.provider.defaultProtocol || "-" },
    { key: "models", label: copy.quickSetupFactModels, value: state.discoveredModels.length },
  ];
  const resultMessage = state.phase === "error"
    ? state.errorMessage || copy.quickSetupErrorFallback
    : state.phase === "review"
      ? `${copy.quickSetupRecommendationPrefix}${state.recommendationReason || copy.quickSetupWaitingChoice}`
      : state.phase === "success"
        ? copy.quickSetupSavedBody
        : copy.quickSetupIdleBody;
  const credentialHint = copy.quickSetupCredentialHint;
  const detectDisabledReason = disabled
    ? copy.quickSetupDisabledReason
    : !state.provider.templateId
      ? copy.quickSetupPickProviderFirst
      : !state.provider.baseUrl.trim()
        ? copy.quickSetupFillBaseUrlFirst
      : state.provider.authKind !== "none" && !credentialValue.trim()
        ? copy.quickSetupFillKeyFirst
        : state.phase === "checking" || state.phase === "saving"
          ? copy.quickSetupBusyReason
          : undefined;

  return (
    <VSection
      className={styles.root}
      aria-labelledby="provider-quick-setup-title"
      eyebrow="Model connection"
      title={copy.quickSetupTitle}
      tooltip={copy.quickSetupTooltip}
      tooltipLabel={copy.quickSetupTooltipLabel}
    >
      <div className={styles.workspace}>
        {state.phase !== "success" ? <div className={styles.inputPanel}>
          <div className={styles.inputGrid}>
            <label className={styles.field}>
              <span>{copy.quickSetupProviderLabel}</span>
              <VStringSelect
                ariaLabel={copy.quickSetupProviderLabel}
                value={state.provider.templateId}
                placeholder={copy.quickSetupProviderPlaceholder}
                isDisabled={disabled || state.phase === "checking" || state.phase === "saving"}
                options={templates.map((template) => ({
                  value: template.provider_preset_id,
                  label: template.label,
                  description: asString(asRecord(template.default_model).label) || asString(asRecord(template.default_model).model_ref),
                }))}
                onValueChange={(templateId) => {
                  const template = templates.find((candidate) => candidate.provider_preset_id === templateId);
                  if (template) onProviderChange(templateToProvider(template));
                }}
              />
            </label>

            {selectedTemplate ? (
              <label className={styles.field}>
                <span>{copy.routeFieldBaseUrl}</span>
                <VInput type="url" value={state.provider.baseUrl} disabled={disabled || state.phase === "checking" || state.phase === "saving"}
                  placeholder={copy.quickSetupBaseUrlPlaceholder}
                  onChange={(event) => onProviderChange({ ...state.provider, baseUrl: event.target.value })} />
              </label>
            ) : null}

            {state.provider.authKind === "none" ? (
              <div className={styles.field}>
                <span>{copy.quickSetupCredentialLabel}</span>
                <div className={styles.noCredential}>
                  <CheckCircle2 size={14} />
                  {copy.quickSetupNoCredential}
                </div>
              </div>
            ) : (
              <label className={styles.field}>
                <span>API Key</span>
                  <VInput
                    type="password"
                    title={credentialHint}
                    autoComplete="new-password"
                    value={credentialValue}
                    disabled={disabled || state.phase === "checking" || state.phase === "saving"}
                    placeholder={copy.quickSetupKeyPlaceholder}
                    onChange={(event) => onCredentialChange(event.target.value)}
                  />
              </label>
            )}

            {showDetectAction ? (
              <VButton
                className={styles.primaryAction}
                variant="primary"
                icon={<Search size={14} />}
                isDisabled={!canDetect}
                title={copy.quickSetupDetectHint}
                disabledReason={detectDisabledReason}
                onPress={() => onDetect({ provider: state.provider, credentialValue })}
              >
                {detectLabel}
              </VButton>
            ) : null}
          </div>

          <details className={styles.advanced}>
            <summary className={styles.advancedSummary}>{copy.quickSetupAdvanced}</summary>
            <div className={styles.advancedGrid}>
              <label className={styles.field}>
                <span>{copy.quickSetupProtocolLabel}</span>
                <VStringSelect ariaLabel={copy.routeFieldProtocol} value={state.provider.defaultProtocol}
                  isDisabled={disabled || state.phase === "checking" || state.phase === "saving"}
                  options={[
                    { value: "chat_completions", label: copy.quickSetupChatCompletionsLabel },
                    { value: "responses", label: "OpenAI Responses" },
                    { value: "anthropic_messages", label: "Anthropic Messages" },
                    { value: "gemini_generate_content", label: "Gemini" },
                  ]}
                  onValueChange={(protocol) => onProviderChange({ ...state.provider, defaultProtocol: protocol, allowedProtocols: [protocol],
                    driver: protocol === "anthropic_messages" ? "anthropic" : protocol === "gemini_generate_content" ? "gemini" : "openai" })} />
              </label>
              <label className={styles.field}>
                <span>{copy.quickSetupAuthMethodLabel}</span>
                <VStringSelect ariaLabel={copy.quickSetupAuthMethodLabel} value={state.provider.authKind}
                  isDisabled={disabled || state.phase === "checking" || state.phase === "saving"}
                  options={[{ value: "api_key", label: "API Key" }, { value: "none", label: copy.quickSetupNoAuthLabel }]}
                  onValueChange={(authKind) => onProviderChange({ ...state.provider, authKind: authKind as ProviderAuthKind, credentialRef: authKind === "none" ? "none" : "" })} />
              </label>
            </div>
          </details>
        </div> : null}

        {showResult ? (
          <section className={styles.resultRegion} data-quick-setup-result="true" aria-live="polite">
            <div className={styles.resultHeader}>
              <h3 className={styles.resultTitle}>{result.title}</h3>
              <VStatusChip tone={state.phase === "error" ? "danger" : state.phase === "success" ? "success" : "accent"}>
                {phaseLabel(state, copy)}
              </VStatusChip>
            </div>
            <VStateSurface
              tone={result.tone}
              busy={state.phase === "checking" || state.phase === "saving"}
              skeletonLines={state.phase === "checking" ? 3 : false}
              icon={state.phase === "review" || state.phase === "success" ? <Sparkles size={15} /> : <KeyRound size={15} />}
              title={result.title}
              facts={state.phase === "review" || state.phase === "saving" || state.phase === "success" ? resultFacts : []}
            >
              {resultMessage}
            </VStateSurface>

            {state.phase === "success" && onConfigureAgent ? (
              <VButton variant="primary" onPress={onConfigureAgent}>{copy.quickSetupGoAgents}</VButton>
            ) : null}
            {showReviewActions ? (
              <div className={styles.reviewActions}>
                <label className={styles.field}>
                  <span>{copy.quickSetupModelToAdd}</span>
                  <VStringSelect
                    ariaLabel={copy.quickSetupModelToAdd}
                    value={state.selectedModelRef}
                    isDisabled={state.phase === "saving" || retrySave}
                    options={state.discoveredModels.map((model) => ({
                      value: model.modelRef,
                      label: model.label || model.modelRef,
                      description: model.modelRef,
                    }))}
                    onValueChange={onModelChange}
                  />
                </label>
                <VButton variant="ghost" isDisabled={state.phase === "saving"} onPress={onReset}>
                  {copy.quickSetupRedetect}
                </VButton>
                <VButton
                  variant="primary"
                  icon={<CheckCircle2 size={14} />}
                  isDisabled={!canConfirm}
                  onPress={onConfirm}
                >
                  {state.phase === "saving" ? copy.quickSetupSaving : retrySave ? copy.quickSetupRetrySave : copy.quickSetupSaveFinish}
                </VButton>
              </div>
            ) : null}
          </section>
        ) : null}
      </div>
    </VSection>
  );
}
