import { Check, ChevronLeft, ChevronRight, KeyRound, Search, ServerCog } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { ConfigCatalogModel, ConfigProviderPresetOption } from "../api/types";
import {
  VActionGroup,
  VButton,
  VCheckbox,
  VInput,
  VPanelHeader,
  VStateSurface,
  VStatusChip,
  VStringSelect,
  VSurface,
} from "../components/vui";
import {
  buildProviderWizardDraft,
  canAdvanceProviderWizard,
  dispatchProviderWizardConnectionAction,
  isProviderWizardConnectionLocked,
  type ProviderAuthKind,
  type ProviderWizardAction,
  type ProviderWizardState,
  type ProviderWizardStep,
} from "./configProviderLogic";
import { type ConfigCopy, formatConfigCopy } from "./config/configCopy";
import styles from "./ConfigProviderWizard.styles";

export type ConfigProviderWizardProps = {
  /** Bilingual copy table (wave 4). */
  copy: ConfigCopy;
  state: ProviderWizardState;
  templates: ConfigProviderPresetOption[];
  disabled: boolean;
  busyLabel: string;
  onChange: (action: ProviderWizardAction) => void;
  onSuggestProviderId: (provider: Record<string, unknown>) => Promise<string>;
  onCreateProvider: (state: ProviderWizardState, credentialValue: string) => Promise<void>;
  onDiscover: (providerId: string, credentialValue: string) => Promise<ConfigCatalogModel[]>;
  onPin: (providerId: string, models: ConfigCatalogModel[]) => Promise<void>;
};

const STEPS: Array<{ id: ProviderWizardStep; copyKey: "wizardStepTemplate" | "wizardStepConnection" | "wizardStepDiscovery" | "wizardStepPin" }> = [
  { id: "template", copyKey: "wizardStepTemplate" },
  { id: "connection", copyKey: "wizardStepConnection" },
  { id: "discovery", copyKey: "wizardStepDiscovery" },
  { id: "pin", copyKey: "wizardStepPin" },
];

const TEMPLATE_GROUPS: Array<{ id: string; copyKey: "wizardGroupOfficial" | "wizardGroupAggregator" | "wizardGroupRelay" | "wizardGroupSelfHosted" | "wizardGroupLocalRuntime" | "wizardGroupCustom" }> = [
  { id: "official_api", copyKey: "wizardGroupOfficial" },
  { id: "aggregator", copyKey: "wizardGroupAggregator" },
  { id: "relay", copyKey: "wizardGroupRelay" },
  { id: "self_hosted", copyKey: "wizardGroupSelfHosted" },
  { id: "local_runtime", copyKey: "wizardGroupLocalRuntime" },
  { id: "custom", copyKey: "wizardGroupCustom" },
];

const PROTOCOL_OPTIONS = ["responses", "chat_completions", "anthropic_messages", "gemini_generate_content"];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function normalizeProviderAuthKind(value: unknown, credentialRef: string): ProviderAuthKind {
  if (value === "api_key" || value === "oauth" || value === "none") return value;
  return credentialRef === "none" ? "none" : "api_key";
}

function templateServiceClass(template: ConfigProviderPresetOption): string {
  const providerServiceType = asString(asRecord(template.provider).service_class);
  if (providerServiceType) return providerServiceType;
  if (template.category === "local") return "local_runtime";
  if (template.category === "official") return "official_api";
  if (template.category === "relay") return "relay";
  return "self_hosted";
}

function templateModelFamily(template: ConfigProviderPresetOption, copy: ConfigCopy): string {
  const model = asRecord(template.default_model);
  return asString(model.family) || asString(model.model) || asString(model.label) || copy.wizardModelFamilyUnlabeled;
}

export function ConfigProviderWizard({
  copy,
  state,
  templates,
  disabled,
  busyLabel,
  onChange,
  onSuggestProviderId,
  onCreateProvider,
  onDiscover,
  onPin,
}: ConfigProviderWizardProps) {
  const [credentialValue, setCredentialValue] = useState("");
  const [providerCreated, setProviderCreated] = useState(false);
  const [localError, setLocalError] = useState("");
  const [discoveryAttempted, setDiscoveryAttempted] = useState(false);
  const appliedTemplateRef = useRef("");
  const selectedTemplate = templates.find((item) => item.provider_preset_id === state.templateId);
  const connectionLocked = isProviderWizardConnectionLocked(disabled, providerCreated);
  const selectedProviderDraft = useMemo(
    () => buildProviderWizardDraft(state, selectedTemplate?.provider),
    [selectedTemplate, state],
  );

  useEffect(() => {
    if (state.step !== "connection" || !selectedTemplate || appliedTemplateRef.current === selectedTemplate.provider_preset_id) {
      return;
    }
    appliedTemplateRef.current = selectedTemplate.provider_preset_id;
    const templateProvider = asRecord(selectedTemplate.provider);
    const templateDeployment = asRecord(templateProvider.deployment);
    const protocols = asRecord(templateProvider.protocols);
    const allowed = Array.isArray(protocols.allowed)
      ? protocols.allowed.filter((value): value is string => typeof value === "string")
      : [];
    const credentialRef = state.credentialRef || asString(templateProvider.credential_ref) || "none";
    onChange({
      type: "set_connection",
      providerId: state.providerId,
      label: state.label || selectedTemplate.label,
      baseUrl: state.baseUrl || asString(templateProvider.base_url),
      authKind: normalizeProviderAuthKind(templateProvider.auth_kind, credentialRef),
      credentialRef,
    });
    onChange({
      type: "set_protocol",
      driver: state.driver || asString(templateProvider.driver),
      defaultProtocol: state.defaultProtocol || asString(protocols.default) || allowed[0] || "responses",
      allowedProtocols: allowed.length ? allowed : ["responses"],
    });
    if (state.serviceClass === "local_runtime") {
      onChange({
        type: "set_deployment",
        runtimeFramework: state.runtimeFramework || asString(templateDeployment.runtime_framework),
        artifactPath: state.artifactPath || asString(templateDeployment.artifact_path),
      });
    }
  }, [onChange, selectedTemplate, state]);

  useEffect(() => {
    if (state.step !== "connection" || providerCreated || !state.label.trim()) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void onSuggestProviderId(selectedProviderDraft)
        .then((suggestedProviderId) => {
          if (!cancelled && suggestedProviderId && !state.providerId) {
            onChange({
              type: "set_connection",
              providerId: suggestedProviderId,
              label: state.label,
              baseUrl: state.baseUrl,
              authKind: state.authKind,
              credentialRef: state.credentialRef,
            });
          }
        })
        .catch((error: unknown) => {
          if (!cancelled) setLocalError(error instanceof Error ? error.message : copy.wizardSuggestFailed);
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [onChange, onSuggestProviderId, providerCreated, selectedProviderDraft, state.baseUrl, state.credentialRef, state.label, state.providerId, state.step, state.templateId]);

  function updateConnection(patch: Partial<Pick<ProviderWizardState, "providerId" | "label" | "baseUrl" | "authKind" | "credentialRef">>) {
    const changed = dispatchProviderWizardConnectionAction(connectionLocked, {
      type: "set_connection",
      providerId: patch.providerId ?? state.providerId,
      label: patch.label ?? state.label,
      baseUrl: patch.baseUrl ?? state.baseUrl,
      authKind: patch.authKind ?? state.authKind,
      credentialRef: patch.credentialRef ?? state.credentialRef,
    }, onChange);
    if (changed) setLocalError("");
  }

  function updateSavedConnection(
    action: Extract<ProviderWizardAction, { type: "set_protocol" | "set_deployment" }>,
  ) {
    const changed = dispatchProviderWizardConnectionAction(connectionLocked, action, onChange);
    if (changed) setLocalError("");
  }

  async function createAndDiscover() {
    if (disabled || busyLabel) return;
    setLocalError("");
    setDiscoveryAttempted(true);
    try {
      if (!providerCreated) {
        await onCreateProvider(state, credentialValue);
        setProviderCreated(true);
      }
      const models = await onDiscover(state.providerId, credentialValue);
      onChange({ type: "set_discovery", models });
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : copy.wizardDiscoverPreserved);
    } finally {
      setCredentialValue("");
    }
  }

  async function pinSelectedModels() {
    const selected = state.discoveredModels.filter((model) => state.pinnedModelRefs.includes(model.modelRef));
    if (!selected.length) return;
    setLocalError("");
    try {
      await onPin(state.providerId, selected);
      onChange({ type: "reset" });
      setProviderCreated(false);
      setDiscoveryAttempted(false);
      appliedTemplateRef.current = "";
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : copy.wizardPinFailed);
    }
  }

  const selectedStepIndex = STEPS.findIndex((step) => step.id === state.step);

  return (
    <VSurface as="section" className={styles.wizard} padding="none" data-wizard-step={state.step}>
      <VPanelHeader
        eyebrow="Provider setup"
        title={copy.wizardTitle}
        actions={<VStatusChip tone={busyLabel ? "warning" : "accent"}>{busyLabel || formatConfigCopy(copy.wizardStepProgressTemplate, { current: selectedStepIndex + 1, total: STEPS.length })}</VStatusChip>}
      />
      <div className={styles.wizardSteps} aria-label={copy.wizardStepsAria}>
        {STEPS.map((step, index) => (
          <VButton key={step.id} variant={step.id === state.step ? "primary" : "ghost"} isDisabled
            icon={index < selectedStepIndex ? <Check size={13} /> : null}
          >
            {copy[step.copyKey]}
          </VButton>
        ))}
      </div>

      <div className={styles.wizardBody}>
        {state.step === "template" ? (
          <div className={styles.templateGroups}>
            {TEMPLATE_GROUPS.map((group) => {
              const groupTemplates = group.id === "custom"
                ? []
                : templates.filter((template) => templateServiceClass(template) === group.id);
              if (group.id !== "custom" && !groupTemplates.length) return null;
              return (
                <section key={group.id} className={styles.templateGroup}>
                  <strong>{copy[group.copyKey]}</strong>
                  <div className={styles.templateGrid}>
                    {groupTemplates.map((template) => (
                      <VButton
                        key={template.provider_preset_id}
                        className={styles.templateButton}
                        contentLayout="plain"
                        variant={state.templateId === template.provider_preset_id ? "primary" : "secondary"}
                        onPress={() => {
                          appliedTemplateRef.current = "";
                          setProviderCreated(false);
                          onChange({ type: "choose_template", templateId: template.provider_preset_id, serviceClass: group.id });
                        }}
                      >
                        <span className={styles.providerIdentity}>
                          <strong className={styles.ellipsis}>{template.label}</strong>
                          <small className={styles.muted}>{templateModelFamily(template, copy)}</small>
                        </span>
                      </VButton>
                    ))}
                    {group.id === "custom" ? (
                      <VButton
                        variant={state.templateId === "custom" ? "primary" : "secondary"}
                        onPress={() => {
                          appliedTemplateRef.current = "custom";
                          setProviderCreated(false);
                          onChange({ type: "choose_template", templateId: "custom", serviceClass: "self_hosted" });
                        }}
                      >
                        {copy.wizardCustomService}
                      </VButton>
                    ) : null}
                  </div>
                </section>
              );
            })}
          </div>
        ) : null}

        {state.step === "connection" ? (
          <div className={styles.fieldGrid}>
            {providerCreated ? (
              <VStateSurface className={styles.fieldWide} tone="unavailable" title={copy.wizardLockedTitle}>
                {copy.wizardLockedBody}
              </VStateSurface>
            ) : null}
            <label className={styles.field}>
              <span>Provider ID</span>
              <VInput value={state.providerId} disabled={connectionLocked} onChange={(event) => updateConnection({ providerId: event.target.value })} />
            </label>
            <label className={styles.field}>
              <span>{copy.wizardDisplayName}</span>
              <VInput value={state.label} disabled={connectionLocked} onChange={(event) => updateConnection({ label: event.target.value })} />
            </label>
            <label className={styles.fieldWide}>
              <span>Service root</span>
              <VInput value={state.baseUrl} disabled={connectionLocked} onChange={(event) => updateConnection({ baseUrl: event.target.value })} />
            </label>
            <label className={styles.field}>
              <span>Credential reference</span>
              <VInput value={state.credentialRef} disabled={connectionLocked} onChange={(event) => updateConnection({ credentialRef: event.target.value })} />
            </label>
            <label className={styles.field}>
              <span>{copy.wizardSecretOnce}</span>
              <VInput
                type="password"
                autoComplete="new-password"
                value={credentialValue}
                disabled={connectionLocked}
                onChange={(event) => setCredentialValue(event.target.value)}
              />
            </label>
            <label className={styles.field}>
              <span>Auth kind</span>
              <VStringSelect
                ariaLabel="Auth kind"
                value={state.authKind}
                isDisabled={connectionLocked}
                options={[
                  { value: "api_key", label: "API key" },
                  { value: "oauth", label: "OAuth" },
                  { value: "none", label: "None" },
                ]}
                onValueChange={(value) => {
                  const authKind = value as ProviderAuthKind;
                  updateConnection({
                    authKind,
                    credentialRef: authKind === "none" ? "none" : state.credentialRef === "none" ? "" : state.credentialRef,
                  });
                }}
              />
            </label>
            <label className={styles.field}>
              <span>Driver</span>
              <VStringSelect
                ariaLabel="Driver"
                value={state.driver}
                isDisabled={connectionLocked}
                options={["openai", "anthropic", "gemini"].map((value) => ({ value, label: value }))}
                onValueChange={(driver) => updateSavedConnection({ type: "set_protocol", driver, defaultProtocol: state.defaultProtocol, allowedProtocols: state.allowedProtocols })}
              />
            </label>
            <label className={styles.field}>
              <span>{copy.wizardDefaultWireProtocol}</span>
              <VStringSelect
                ariaLabel={copy.wizardDefaultWireProtocol}
                value={state.defaultProtocol}
                isDisabled={connectionLocked}
                options={PROTOCOL_OPTIONS.map((value) => ({ value, label: value }))}
                onValueChange={(defaultProtocol) => updateSavedConnection({ type: "set_protocol", driver: state.driver, defaultProtocol, allowedProtocols: Array.from(new Set([...state.allowedProtocols, defaultProtocol])) })}
              />
            </label>
            <div className={styles.fieldWide}>
              <span>Allowed wire protocols</span>
              <div className={styles.protocolGrid}>
                {PROTOCOL_OPTIONS.map((protocol) => (
                  <VCheckbox
                    key={protocol}
                    isSelected={state.allowedProtocols.includes(protocol)}
                    isDisabled={connectionLocked || state.defaultProtocol === protocol}
                    onChange={(selected) => updateSavedConnection({
                      type: "set_protocol",
                      driver: state.driver,
                      defaultProtocol: state.defaultProtocol,
                      allowedProtocols: selected ? [...state.allowedProtocols, protocol] : state.allowedProtocols.filter((item) => item !== protocol),
                    })}
                  >
                    {protocol}
                  </VCheckbox>
                ))}
              </div>
            </div>
            {state.serviceClass === "local_runtime" ? (
              <>
                <label className={styles.field}>
                  <span>Runtime framework</span>
                  <VInput value={state.runtimeFramework} disabled={connectionLocked} onChange={(event) => updateSavedConnection({ type: "set_deployment", runtimeFramework: event.target.value, artifactPath: state.artifactPath })} />
                </label>
                <label className={styles.field}>
                  <span>Artifact path</span>
                  <VInput value={state.artifactPath} disabled={connectionLocked} onChange={(event) => updateSavedConnection({ type: "set_deployment", runtimeFramework: state.runtimeFramework, artifactPath: event.target.value })} />
                </label>
              </>
            ) : null}
          </div>
        ) : null}

        {state.step === "discovery" ? (
          <div className={styles.discoveryGrid}>
            <VStateSurface
              tone={localError ? "error" : discoveryAttempted && state.discoveredModels.length ? "info" : "empty"}
              icon={<Search size={15} />}
              title={localError
                ? copy.wizardDiscoverFailedTitle
                : state.discoveredModels.length
                  ? formatConfigCopy(copy.wizardDiscoveredTemplate, { count: state.discoveredModels.length })
                  : copy.wizardDiscoverIdleTitle}
              facts={state.discoveredModels.slice(0, 4).map((model) => ({ key: model.modelRef, label: model.modelRef, value: model.availability }))}
              actions={<VButton variant="primary" icon={<ServerCog size={14} />} isDisabled={disabled || Boolean(busyLabel)} onPress={() => void createAndDiscover()}>{copy.wizardCreateTestDiscover}</VButton>}
            >
              {copy.wizardDiscoveryBody}
            </VStateSurface>
          </div>
        ) : null}

        {state.step === "pin" ? (
          <div className={styles.discoveryGrid}>
            {state.discoveredModels.map((model) => (
              <VCheckbox
                key={model.modelRef}
                data-model-availability={model.availability}
                isSelected={state.pinnedModelRefs.includes(model.modelRef)}
                isDisabled={disabled}
                onChange={() => onChange({ type: "toggle_pin", modelRef: model.modelRef })}
              >
                <span className={styles.modelIdentity}>
                  <strong title={model.modelRef}>{model.modelRef}</strong>
                  <small className={styles.muted}>upstream: {model.upstreamId}</small>
                </span>
              </VCheckbox>
            ))}
          </div>
        ) : null}
      </div>

      {localError ? <p className={styles.critical} role="alert">{localError}</p> : null}
      <div className={styles.wizardFooter}>
        <VButton icon={<ChevronLeft size={14} />} isDisabled={disabled || state.step === "template"} onPress={() => onChange({ type: "back" })}>{copy.wizardPrevious}</VButton>
        <VActionGroup ariaLabel={copy.wizardNextActionsAria}>
          {state.step === "pin" ? (
            <VButton variant="primary" icon={<KeyRound size={14} />} isDisabled={disabled || Boolean(busyLabel) || !canAdvanceProviderWizard(state)} onPress={() => void pinSelectedModels()}>{copy.wizardPinSelected}</VButton>
          ) : (
            <VButton variant="primary" trailingIcon={<ChevronRight size={14} />} isDisabled={disabled || !canAdvanceProviderWizard(state)} onPress={() => onChange({ type: "next" })}>{copy.wizardNext}</VButton>
          )}
        </VActionGroup>
      </div>
    </VSurface>
  );
}
