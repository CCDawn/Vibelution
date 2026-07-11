import { Check, ChevronLeft, ChevronRight, KeyRound, Search, ServerCog } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { ConfigCatalogModel, ConfigProviderPresetOption } from "../api/types";
import {
  VActionGroup,
  VButton,
  VCheckbox,
  VChip,
  VInput,
  VPanelHeader,
  VStateSurface,
  VStatusChip,
  VStringSelect,
  VSurface,
} from "../components/vui";
import {
  canAdvanceProviderWizard,
  dispatchProviderWizardConnectionAction,
  isProviderWizardConnectionLocked,
  type ProviderWizardAction,
  type ProviderWizardState,
  type ProviderWizardStep,
} from "./configProviderLogic";
import styles from "./ConfigProviderRegistryPanel.styles";

export type ConfigProviderWizardProps = {
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

const STEPS: Array<{ id: ProviderWizardStep; label: string }> = [
  { id: "template", label: "1 模板" },
  { id: "connection", label: "2 连接" },
  { id: "discovery", label: "3 发现" },
  { id: "pin", label: "4 固定" },
];

const TEMPLATE_GROUPS = [
  { id: "official_api", label: "官方 API" },
  { id: "aggregator", label: "聚合平台" },
  { id: "relay", label: "中继" },
  { id: "self_hosted", label: "远程自托管" },
  { id: "local_runtime", label: "本地框架" },
  { id: "custom", label: "自定义" },
] as const;

const PROTOCOL_OPTIONS = ["responses", "chat_completions", "anthropic_messages", "gemini_generate_content"];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function templateServiceClass(template: ConfigProviderPresetOption): string {
  const serviceClass = asString(asRecord(template.provider).service_class);
  if (serviceClass) return serviceClass;
  if (template.category === "local") return "local_runtime";
  if (template.category === "official") return "official_api";
  if (template.category === "relay") return "relay";
  return "self_hosted";
}

function providerDraft(state: ProviderWizardState, template?: ConfigProviderPresetOption): Record<string, unknown> {
  const source = asRecord(template?.provider);
  return {
    ...source,
    label: state.label,
    service_class: state.serviceClass,
    driver: state.driver,
    base_url: state.baseUrl,
    auth_kind: asString(source.auth_kind) || (state.credentialRef === "none" ? "none" : "api_key"),
    credential_ref: state.credentialRef,
    requires_credential: state.credentialRef !== "none",
    protocols: { default: state.defaultProtocol, allowed: state.allowedProtocols },
    discovery: {
      ...asRecord(source.discovery),
      mode: asString(asRecord(source.discovery).mode) || "auto",
    },
    ...(state.serviceClass === "local_runtime"
      ? { runtime_framework: state.runtimeFramework, artifact_path: state.artifactPath }
      : {}),
    models: {},
  };
}

function templateModelFamily(template: ConfigProviderPresetOption): string {
  const model = asRecord(template.default_model);
  return asString(model.family) || asString(model.model) || asString(model.label) || "模型族未标注";
}

export function ConfigProviderWizard({
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
    () => providerDraft(state, selectedTemplate),
    [selectedTemplate, state],
  );

  useEffect(() => {
    if (state.step !== "connection" || !selectedTemplate || appliedTemplateRef.current === selectedTemplate.provider_preset_id) {
      return;
    }
    appliedTemplateRef.current = selectedTemplate.provider_preset_id;
    const templateProvider = asRecord(selectedTemplate.provider);
    const protocols = asRecord(templateProvider.protocols);
    const allowed = Array.isArray(protocols.allowed)
      ? protocols.allowed.filter((value): value is string => typeof value === "string")
      : [];
    onChange({
      type: "set_connection",
      providerId: state.providerId,
      label: state.label || selectedTemplate.label,
      baseUrl: state.baseUrl || asString(templateProvider.base_url),
      credentialRef: state.credentialRef || asString(templateProvider.credential_ref) || "none",
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
        runtimeFramework: state.runtimeFramework || asString(templateProvider.runtime_framework),
        artifactPath: state.artifactPath || asString(templateProvider.artifact_path),
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
              credentialRef: state.credentialRef,
            });
          }
        })
        .catch((error: unknown) => {
          if (!cancelled) setLocalError(error instanceof Error ? error.message : "Provider ID 建议失败");
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [onChange, onSuggestProviderId, providerCreated, selectedProviderDraft, state.baseUrl, state.credentialRef, state.label, state.providerId, state.step, state.templateId]);

  function updateConnection(patch: Partial<Pick<ProviderWizardState, "providerId" | "label" | "baseUrl" | "credentialRef">>) {
    const changed = dispatchProviderWizardConnectionAction(connectionLocked, {
      type: "set_connection",
      providerId: patch.providerId ?? state.providerId,
      label: patch.label ?? state.label,
      baseUrl: patch.baseUrl ?? state.baseUrl,
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
      setLocalError(error instanceof Error ? error.message : "发现失败；已保留上一次目录。 ");
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
      setLocalError(error instanceof Error ? error.message : "固定模型失败");
    }
  }

  const selectedStepIndex = STEPS.findIndex((step) => step.id === state.step);

  return (
    <VSurface as="section" className={styles.wizard} padding="none" data-wizard-step={state.step}>
      <VPanelHeader
        eyebrow="Provider setup"
        title="四步 Provider 向导"
        actions={<VStatusChip tone={busyLabel ? "warning" : "accent"}>{busyLabel || `步骤 ${selectedStepIndex + 1}/4`}</VStatusChip>}
      />
      <div className={styles.wizardSteps} aria-label="Provider 向导进度">
        {STEPS.map((step, index) => (
          <VButton key={step.id} variant={step.id === state.step ? "primary" : "ghost"} isDisabled>
            {index < selectedStepIndex ? <Check size={13} /> : null}{step.label}
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
              return (
                <section key={group.id} className={styles.templateGroup}>
                  <strong>{group.label}</strong>
                  <div className={styles.templateGrid}>
                    {groupTemplates.map((template) => (
                      <VButton
                        key={template.provider_preset_id}
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
                          <VChip tone="neutral">{templateModelFamily(template)}</VChip>
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
                        自定义 Provider
                      </VButton>
                    ) : null}
                    {!groupTemplates.length && group.id !== "custom" ? <small className={styles.muted}>当前无可用模板</small> : null}
                  </div>
                </section>
              );
            })}
          </div>
        ) : null}

        {state.step === "connection" ? (
          <div className={styles.fieldGrid}>
            {providerCreated ? (
              <VStateSurface className={styles.fieldWide} tone="unavailable" title="Provider 已创建，连接字段已锁定">
                返回 Provider 详情使用“修改路由”并完成 backend preview token 确认；向导不会静默忽略字段修改。
              </VStateSurface>
            ) : null}
            <label className={styles.field}>
              <span>Provider ID</span>
              <VInput value={state.providerId} disabled={connectionLocked} onChange={(event) => updateConnection({ providerId: event.target.value })} />
            </label>
            <label className={styles.field}>
              <span>显示名称</span>
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
              <span>Secret（仅本次请求）</span>
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
              <VStringSelect ariaLabel="Auth kind" value={asString(selectedProviderDraft.auth_kind)} isDisabled options={[{ value: "none", label: "none" }, { value: "api_key", label: "API key" }, { value: "bearer", label: "Bearer" }]} onValueChange={() => undefined} />
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
              <span>默认 wire protocol</span>
              <VStringSelect
                ariaLabel="默认 wire protocol"
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
              title={localError ? "发现失败，已保留上次目录" : state.discoveredModels.length ? `发现 ${state.discoveredModels.length} 个模型` : "创建草稿并测试发现"}
              facts={state.discoveredModels.slice(0, 4).map((model) => ({ key: model.modelRef, label: model.modelRef, value: model.availability }))}
              actions={<VButton variant="primary" icon={<ServerCog size={14} />} isDisabled={disabled || Boolean(busyLabel)} onPress={() => void createAndDiscover()}>创建 / 测试 / 发现</VButton>}
            >
              仅展示归一化目录与有界错误，不展示原始 Provider 响应。Secret 完成请求后立即清空。
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
        <VButton icon={<ChevronLeft size={14} />} isDisabled={disabled || state.step === "template"} onPress={() => onChange({ type: "back" })}>上一步</VButton>
        <VActionGroup ariaLabel="向导下一步">
          {state.step === "pin" ? (
            <VButton variant="primary" icon={<KeyRound size={14} />} isDisabled={disabled || Boolean(busyLabel) || !canAdvanceProviderWizard(state)} onPress={() => void pinSelectedModels()}>固定所选模型</VButton>
          ) : (
            <VButton variant="primary" trailingIcon={<ChevronRight size={14} />} isDisabled={disabled || !canAdvanceProviderWizard(state)} onPress={() => onChange({ type: "next" })}>下一步</VButton>
          )}
        </VActionGroup>
      </div>
    </VSurface>
  );
}
