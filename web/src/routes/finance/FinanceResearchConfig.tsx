import styles from "./FinanceResearchConfig.styles";
import { Play, SlidersHorizontal } from "lucide-react";
import { VButton, VInput, VRouteLinkButton, VSelect, VStateSurface, VSurface } from "../../components/vui";
import type { SessionLlmModelOption, SessionLlmOptions, SessionModelSelection } from "../../api/types";
import { financialResearchModelSelection, financialResearchModelUnavailableReason, type FinancialResearchModelUnavailableReason } from "./FinancialResearchBridge";
import { isValidResearchDate, localResearchDate, type ResearchDepth, type ResearchScope } from "./stockResearchModel";

export type FinanceResearchConfigValue = { period: string; date: string; scope: ResearchScope; depth: ResearchDepth; instructions?: string };
const FOLLOW_SESSION_MODEL = "__finance_follow_session_model__";

type NativeModelChoice = SessionLlmModelOption & { contextWindow?: number };
type FinanceResearchModelGateIssue =
  | "session_missing"
  | "options_loading"
  | "options_unavailable"
  | "default_missing"
  | FinancialResearchModelUnavailableReason
  | "turn_model_unavailable";

function isModelUnavailableReason(value: FinanceResearchModelGateIssue | null): value is FinancialResearchModelUnavailableReason {
  return value === "missing_context_window" || value === "not_runtime_selectable"
    || value === "provider_unavailable" || value === "missing_credentials";
}

function modelId(model: SessionLlmModelOption | null | undefined) {
  return String(model?.modelRef || model?.modelId || "").trim();
}

function nativeContextWindow(model: SessionLlmModelOption | null | undefined) {
  const value = (model as NativeModelChoice | null | undefined)?.contextWindow;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

export function financialResearchModelGateIssue({ sessionId, options, loading, error, selection }: {
  sessionId?: string;
  options?: SessionLlmOptions;
  loading?: boolean;
  error?: boolean;
  selection?: SessionModelSelection | null;
}): FinanceResearchModelGateIssue | null {
  if (!sessionId) return "session_missing";
  if (loading || (options && options.sessionId !== sessionId && !error)) return "options_loading";
  if (error || !options || options.sessionId !== sessionId) return "options_unavailable";
  if (!options.model) return "default_missing";
  const defaultIssue = financialResearchModelUnavailableReason(options.model);
  if (defaultIssue) return defaultIssue;
  if (selection) {
    const selected = (options.choices ?? []).find((choice) => modelId(choice) === selection.modelId);
    if (!selected || financialResearchModelUnavailableReason(selected)) return "turn_model_unavailable";
  }
  return null;
}

function modelUnavailableText(reason: FinancialResearchModelUnavailableReason, zh: boolean) {
  if (reason === "missing_context_window") return zh ? "缺少有效的 context_window" : "No valid context_window";
  if (reason === "missing_credentials") return zh ? "供应商凭证未配置" : "Provider credentials are missing";
  if (reason === "provider_unavailable") return zh ? "供应商当前不可用" : "Provider is unavailable";
  return zh ? "当前模型未启用或不可执行" : "Model is not enabled for execution";
}

function modelChoiceLabel(model: SessionLlmModelOption, zh: boolean) {
  const name = model.label || model.model || model.modelRef || model.modelId;
  const context = nativeContextWindow(model);
  return `${name} · ${new Intl.NumberFormat(zh ? "zh-CN" : "en-US").format(context)} ${zh ? "tokens" : "tokens"}`;
}

export function FinanceResearchConfig({ value, onChange, onStart, disabled, pending, zh, sessionId, sessionLlmOptions, sessionLlmOptionsLoading = false, sessionLlmOptionsError = false, turnModelSelection, onTurnModelSelectionChange, agentConfigHref }: {
  value: FinanceResearchConfigValue;
  onChange: (value: FinanceResearchConfigValue) => void;
  onStart: () => void;
  disabled: boolean;
  pending: boolean;
  zh: boolean;
  sessionId?: string;
  sessionLlmOptions?: SessionLlmOptions;
  sessionLlmOptionsLoading?: boolean;
  sessionLlmOptionsError?: boolean;
  turnModelSelection?: SessionModelSelection | null;
  onTurnModelSelectionChange?: (selection: SessionModelSelection | null) => void;
  agentConfigHref?: string;
}) {
  const modelGateIssue = financialResearchModelGateIssue({
    sessionId,
    options: sessionLlmOptions,
    loading: sessionLlmOptionsLoading,
    error: sessionLlmOptionsError,
    selection: turnModelSelection,
  });
  const optionsMatchSession = Boolean(sessionId && sessionLlmOptions?.sessionId === sessionId);
  const choices = optionsMatchSession
    ? (sessionLlmOptions?.choices ?? []).filter((choice) => financialResearchModelUnavailableReason(choice) === null)
    : [];
  const currentModel = optionsMatchSession ? sessionLlmOptions?.model : null;
  const currentModelId = modelId(currentModel);
  const currentDefaultReady = Boolean(currentModel && financialResearchModelUnavailableReason(currentModel) === null);
  const selectedKey = turnModelSelection?.modelId || (currentDefaultReady ? FOLLOW_SESSION_MODEL : null);
  const modelOptions = [
    {
      id: FOLLOW_SESSION_MODEL,
      label: currentModel
        ? `${zh ? "跟随助手默认" : "Follow assistant default"} · ${currentModel.label || currentModel.model || currentModel.modelId}`
        : (zh ? "跟随助手默认" : "Follow assistant default"),
      description: currentModel && !currentDefaultReady
        ? modelUnavailableText(financialResearchModelUnavailableReason(currentModel) ?? "not_runtime_selectable", zh)
        : undefined,
      disabled: !currentDefaultReady,
    },
    ...choices.map((choice) => ({
      id: modelId(choice),
      label: modelChoiceLabel(choice, zh),
      description: [choice.providerLabel, choice.supportsReasoningEffort && choice.reasoningEffortOptions.length
        ? choice.reasoningEffortOptions.map((effort) => effort.label || effort.value).join(" / ")
        : null].filter(Boolean).join(" · "),
    })),
  ];
  const selectableTurnModel = turnModelSelection
    ? choices.find((choice) => modelId(choice) === turnModelSelection.modelId)
    : null;
  const modelSelectorDisabled = !sessionId || sessionLlmOptionsLoading || sessionLlmOptionsError
    || !optionsMatchSession || !onTurnModelSelectionChange || choices.length === 0;
  const canStartResearch = !disabled && !modelGateIssue && isValidResearchDate(value.date);
  const effectiveEffort = !modelGateIssue && sessionLlmOptions
    ? financialResearchModelSelection(value.depth, sessionLlmOptions, turnModelSelection)?.reasoningEffort
    : undefined;
  const effortModel = selectableTurnModel ?? currentModel;
  const effortLabel = effortModel?.reasoningEffortOptions.find((option) => option.value === effectiveEffort)?.label
    || ({ minimal: "极低", low: "低", medium: "中", high: "高", xhigh: "超高" } as Record<string, string>)[effectiveEffort || ""]
    || effectiveEffort;
  const hasDefaultProblem = modelGateIssue === "default_missing" || isModelUnavailableReason(modelGateIssue);
  const modelGateMessage = modelGateIssue === "session_missing"
    ? (zh ? "正在等待当前助手的研究会话。" : "Waiting for this assistant's research session.")
    : modelGateIssue === "options_loading"
      ? (zh ? "正在读取本研究会话的模型能力。" : "Loading model capabilities for this research session.")
      : modelGateIssue === "options_unavailable"
        ? (zh ? "无法读取当前研究会话的模型能力；为避免误用，不会自动切换模型。" : "Model capabilities could not be loaded for this research session; no model will be selected automatically.")
        : modelGateIssue === "default_missing"
          ? (zh ? "当前助手没有可确认的默认对话模型，暂不能开始研究。请先检查助手配置。" : "The assistant has no confirmed default dialogue model, so research cannot start. Check assistant settings.")
        : isModelUnavailableReason(modelGateIssue)
            ? (zh
              ? `当前助手默认对话模型「${currentModel?.label || currentModel?.model || currentModelId}」${modelUnavailableText(modelGateIssue, true)}。研究会话会先检查此默认模型，本轮模型选择不能绕过该检查。`
              : `The assistant default model “${currentModel?.label || currentModel?.model || currentModelId}” is not ready: ${modelUnavailableText(modelGateIssue, false)}. The research session checks this default first; a per-turn choice cannot bypass it.`)
            : modelGateIssue === "turn_model_unavailable"
              ? (zh ? "已选的本轮模型不在当前研究会话的可执行选项中，请重新选择或恢复助手默认。" : "The selected turn model is not in this research session's executable choices. Select another model or follow the assistant default.")
              : null;
  const modelGateTone = sessionLlmOptionsError ? "error" : hasDefaultProblem || modelGateIssue === "turn_model_unavailable" ? "unavailable" : "info";
  const keepReasoningEffort = (choice: SessionLlmModelOption) => {
    const effort = turnModelSelection?.reasoningEffort;
    const supported = new Set([
      ...(choice.reasoningEffortValues ?? []),
      ...(choice.reasoningEffortOptions ?? []).map((option) => option.value),
    ]);
    return effort && supported.has(effort) ? effort : undefined;
  };
  return <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "研究设置" : "Research settings"}>
    <div className={styles.heading}><strong className={styles.title}><SlidersHorizontal size={15} />{zh ? "发起研究" : "Start research"}</strong><span className={styles.caption}>{zh ? "财报 · 事件 · 风险" : "Financials · Events · Risks"}</span></div>
    <div className={styles.fields}>
      <label className={styles.field}>{zh ? "分析日期" : "As of"}<VInput type="date" value={value.date} max={localResearchDate()} aria-invalid={!isValidResearchDate(value.date)} aria-label={zh ? "分析日期" : "Analysis date"} onChange={(event) => onChange({ ...value, date: event.target.value })} /></label>
      <label className={styles.field}>{zh ? "报告期" : "Report period"}<VInput value={value.period} maxLength={40} placeholder="2024FY" aria-label={zh ? "报告期" : "Report period"} onChange={(event) => onChange({ ...value, period: event.target.value })} /></label>
      <label className={styles.field}>{zh ? "研究范围" : "Scope"}<VSelect selectedKey={value.scope} aria-label={zh ? "研究范围" : "Research scope"} onSelectionChange={(key) => onChange({ ...value, scope: key as ResearchScope })} options={[{ id: "comprehensive", label: zh ? "综合研究" : "Comprehensive" }, { id: "financial", label: zh ? "财报分析" : "Financials" }, { id: "events", label: zh ? "事件分析" : "Events" }, { id: "risk", label: zh ? "风险评估" : "Risks" }]} /></label>
      <label className={styles.field}>{zh ? "研究深度" : "Depth"}<VSelect selectedKey={value.depth} aria-label={zh ? "研究深度" : "Research depth"} onSelectionChange={(key) => onChange({ ...value, depth: key as ResearchDepth })} options={[{ id: "brief", label: zh ? "1 · 快速" : "1 · Quick" }, { id: "basic", label: zh ? "2 · 基础" : "2 · Basic" }, { id: "standard", label: zh ? "3 · 标准" : "3 · Standard" }, { id: "detailed", label: zh ? "4 · 深入" : "4 · Deep" }, { id: "exhaustive", label: zh ? "5 · 全面" : "5 · Comprehensive" }]} /></label>
      <label className={styles.field}>{zh ? "本轮研究模型" : "Model for this research"}<VSelect selectedKey={selectedKey} isDisabled={modelSelectorDisabled} aria-label={zh ? "本轮研究模型" : "Model for this research"} placeholder={zh ? "选择可执行模型" : "Select an executable model"} options={modelOptions} onSelectionChange={(key) => {
        if (!onTurnModelSelectionChange || key === null) return;
        if (key === FOLLOW_SESSION_MODEL) { onTurnModelSelectionChange(null); return; }
        const choice = choices.find((candidate) => modelId(candidate) === String(key));
        if (choice) onTurnModelSelectionChange({ modelId: modelId(choice), ...(keepReasoningEffort(choice) ? { reasoningEffort: keepReasoningEffort(choice) } : {}) });
      }} /></label>
      <VButton variant="primary" isDisabled={!canStartResearch} onPress={onStart} icon={<Play size={14} />}>{pending ? (zh ? "正在启动" : "Starting") : (zh ? "开始研究" : "Start research")}</VButton>
    </div>
    {effectiveEffort ? <p className={styles.caption} aria-live="polite">{zh ? `本轮推理：${effortLabel}` : `Reasoning: ${effectiveEffort}`}</p> : null}
    {modelGateMessage ? <VStateSurface tone={modelGateTone} density="compact" title={zh ? "模型状态" : "Model status"} className={styles.modelStatus} data-testid="finance-research-model-status" aria-live="polite" actions={hasDefaultProblem && agentConfigHref ? <VRouteLinkButton to={agentConfigHref}>{zh ? "打开助手配置" : "Open assistant settings"}</VRouteLinkButton> : undefined}>{modelGateMessage}{selectableTurnModel ? <span className={styles.modelStatusDetail}>{zh ? ` 本轮已选：${selectableTurnModel.label || selectableTurnModel.model || selectableTurnModel.modelId}。` : ` Selected for this turn: ${selectableTurnModel.label || selectableTurnModel.model || selectableTurnModel.modelId}.`}</span> : null}</VStateSurface> : null}
  </VSurface>;
}
