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
import styles from "./ConfigQuickSetupPanel.styles";

export type ConfigQuickSetupPanelProps = {
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

function templateToProvider(template: ConfigProviderPresetOption): ProviderWizardState {
  const provider = asRecord(template.provider);
  const protocols = asRecord(provider.protocols);
  const deployment = asRecord(provider.deployment);
  const credentialRef = asString(provider.credential_ref) || "none";
  const rawAuthKind = asString(provider.auth_kind);
  const authKind: ProviderAuthKind = rawAuthKind === "none" || rawAuthKind === "oauth" || rawAuthKind === "api_key"
    ? rawAuthKind
    : credentialRef === "none" ? "none" : "api_key";
  const allowedProtocols = asStringArray(protocols.allowed);
  const defaultProtocol = asString(protocols.default) || allowedProtocols[0] || "responses";
  return {
    ...initialProviderWizardState(),
    templateId: template.provider_preset_id,
    serviceClass: templateServiceClass(template),
    providerId: template.provider_id,
    label: template.label,
    baseUrl: asString(provider.base_url),
    authKind,
    credentialRef: authKind === "none" ? "none" : credentialRef,
    driver: asString(provider.driver),
    defaultProtocol,
    allowedProtocols: allowedProtocols.length ? allowedProtocols : [defaultProtocol],
    runtimeFramework: asString(deployment.runtime_framework),
    artifactPath: asString(deployment.artifact_path),
  };
}

function resultCopy(state: ProviderQuickSetupState) {
  if (state.phase === "checking") return { title: "正在检测连接", tone: "loading" as const };
  if (state.phase === "review") return { title: "确认生成的配置", tone: "info" as const };
  if (state.phase === "saving") return { title: "正在保存配置", tone: "loading" as const };
  if (state.phase === "success") return { title: "配置已保存", tone: "info" as const };
  if (state.phase === "error") return { title: "需要处理后重试", tone: "error" as const };
  return { title: "等待检测", tone: "empty" as const };
}

function phaseLabel(state: ProviderQuickSetupState): string {
  if (state.phase === "checking") return "检测中";
  if (state.phase === "review") return "待确认";
  if (state.phase === "saving") return "保存中";
  if (state.phase === "success") return "已完成";
  if (state.phase === "error") return "需处理";
  return "待输入";
}

export function ConfigQuickSetupPanel({
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
}: ConfigQuickSetupPanelProps) {
  const result = resultCopy(state);
  const selectedTemplate = templates.find((template) => template.provider_preset_id === state.provider.templateId);
  const canDetect = Boolean(
    state.provider.templateId
    && (state.provider.authKind === "none" || credentialValue.trim())
    && !disabled
    && state.phase !== "checking"
    && state.phase !== "saving",
  );
  const canConfirm = state.phase === "review" && Boolean(state.selectedModelRef) && !disabled;
  const showResult = state.phase !== "input";
  const showDetectAction = state.phase === "input" || state.phase === "checking" || state.phase === "error";
  const showReviewActions = state.phase === "review" || state.phase === "saving";
  const detectLabel = state.phase === "checking"
    ? "检测中…"
    : state.phase === "error"
      ? "重新检测"
      : "检测连接";
  const resultFacts = [
    { key: "provider", label: "Provider", value: state.provider.label || selectedTemplate?.label || "-" },
    { key: "endpoint", label: "端点", value: state.provider.baseUrl || "-" },
    { key: "protocol", label: "协议", value: state.provider.defaultProtocol || "-" },
    { key: "models", label: "发现模型", value: state.discoveredModels.length },
  ];
  const resultMessage = state.phase === "error"
    ? state.errorMessage || "检测或保存未完成，请检查输入后重试。"
    : state.phase === "review"
      ? `推荐理由：${state.recommendationReason || "等待选择"}`
      : state.phase === "success"
        ? "当前模型连接已经保存并同步。"
        : "保持当前页面，完成后会在这里显示结果。";

  return (
    <VSection
      className={styles.root}
      aria-labelledby="provider-quick-setup-title"
      eyebrow="Model connection"
      title="连接一个模型服务"
      meta="约 1 分钟"
    >
      <div className={styles.workspace}>
        <div className={styles.inputPanel}>
          <div className={styles.inputGrid}>
            <label className={styles.field}>
              <span>选择服务商</span>
              <VStringSelect
                ariaLabel="选择服务商"
                value={state.provider.templateId}
                placeholder="选择 Provider 模板"
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

            {state.provider.authKind === "none" ? (
              <div className={styles.field}>
                <span>凭据</span>
                <div className={styles.noCredential}>
                  <CheckCircle2 size={14} />
                  无需凭据
                </div>
              </div>
            ) : (
              <label className={styles.field}>
                <span>API Key</span>
                <VInput
                  type="password"
                  autoComplete="new-password"
                  value={credentialValue}
                  disabled={disabled || state.phase === "checking" || state.phase === "saving"}
                  placeholder="仅用于本次本地配置请求"
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
                onPress={() => onDetect({ provider: state.provider, credentialValue })}
              >
                {detectLabel}
              </VButton>
            ) : null}
          </div>

          <small className={styles.hint}>凭据只用于本次本地检测；确认前不会写入正式配置。</small>

          <details className={styles.advanced}>
            <summary className={styles.advancedSummary}>高级参数</summary>
            <div className={styles.advancedGrid}>
              <label className={styles.field}>
                <span>服务端点</span>
                <VInput value={state.provider.baseUrl} readOnly />
              </label>
              <label className={styles.field}>
                <span>协议</span>
                <VInput value={state.provider.defaultProtocol} readOnly />
              </label>
            </div>
          </details>
        </div>

        {showResult ? (
          <section className={styles.resultRegion} data-quick-setup-result="true" aria-live="polite">
            <div className={styles.resultHeader}>
              <h3 className={styles.resultTitle}>{result.title}</h3>
              <VStatusChip tone={state.phase === "error" ? "danger" : state.phase === "success" ? "success" : "accent"}>
                {phaseLabel(state)}
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

            {showReviewActions ? (
              <div className={styles.reviewActions}>
                <label className={styles.field}>
                  <span>默认模型</span>
                  <VStringSelect
                    ariaLabel="默认模型"
                    value={state.selectedModelRef}
                    isDisabled={state.phase === "saving"}
                    options={state.discoveredModels.map((model) => ({
                      value: model.modelRef,
                      label: model.label || model.modelRef,
                      description: model.modelRef,
                    }))}
                    onValueChange={onModelChange}
                  />
                </label>
                <VButton variant="ghost" isDisabled={state.phase === "saving"} onPress={onReset}>
                  重新检测
                </VButton>
                <VButton
                  variant="primary"
                  icon={<CheckCircle2 size={14} />}
                  isDisabled={!canConfirm}
                  onPress={onConfirm}
                >
                  {state.phase === "saving" ? "保存中…" : "保存并完成"}
                </VButton>
              </div>
            ) : null}
          </section>
        ) : null}
      </div>
    </VSection>
  );
}
