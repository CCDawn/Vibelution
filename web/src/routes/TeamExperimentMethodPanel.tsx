import { AlertTriangle, CheckCircle2, Save } from "lucide-react";
import { useEffect, useState } from "react";

import type {
  ExperimentContractV2,
  ExperimentMethodCatalogPayload,
  ExperimentMethodDescriptor,
  ExperimentMethodId,
  ExperimentPurposeId,
  ExperimentResearchModeId,
} from "../api/types";
import { VNativeButton, VNativeInput, VNativeSelect, VNativeTextarea } from "../components/vui";
import styles from "./TeamExperimentMethodPanel.styles";

type MethodFieldKind = "text" | "textarea" | "integer" | "number" | "list" | "integer_list" | "json" | "approval";

type MethodFieldDefinition = {
  labelZh: string;
  labelEn: string;
  kind: MethodFieldKind;
  placeholderZh?: string;
  placeholderEn?: string;
  wide?: boolean;
  allowEmpty?: boolean;
};

const METHOD_FIELD_DEFINITIONS: Record<string, MethodFieldDefinition> = {
  dataset: { labelZh: "数据集", labelEn: "Dataset", kind: "textarea", placeholderZh: "数据版本、split、checksum 与来源", placeholderEn: "Version, split, checksum, and source", wide: true },
  model: { labelZh: "模型或候选", labelEn: "Model or candidate", kind: "textarea", placeholderZh: "模型结构、候选机制和容量约束", placeholderEn: "Architecture, candidate mechanism, and capacity", wide: true },
  baseline: { labelZh: "公平基线", labelEn: "Fair baseline", kind: "textarea", wide: true },
  seeds: { labelZh: "随机种子", labelEn: "Seeds", kind: "integer_list", placeholderZh: "17, 42, 101", placeholderEn: "17, 42, 101" },
  budget: { labelZh: "实验预算", labelEn: "Budget", kind: "textarea", placeholderZh: "训练轮次、调参预算、停止条件", placeholderEn: "Epochs, tuning budget, and stop rule", wide: true },
  smokePlan: { labelZh: "Smoke 计划", labelEn: "Smoke plan", kind: "textarea", wide: true },
  sources: { labelZh: "数据来源", labelEn: "Sources", kind: "list", placeholderZh: "每行一个来源", placeholderEn: "One source per line", wide: true },
  dataSchema: { labelZh: "数据结构", labelEn: "Data schema", kind: "textarea", wide: true },
  transform: { labelZh: "清洗与转换", labelEn: "Transform", kind: "textarea", wide: true },
  split: { labelZh: "数据切分", labelEn: "Split", kind: "textarea", wide: true },
  simulator: { labelZh: "仿真器", labelEn: "Simulator", kind: "text" },
  scenario: { labelZh: "仿真场景", labelEn: "Scenario", kind: "textarea", wide: true },
  parameters: { labelZh: "参数配置", labelEn: "Parameters", kind: "json", placeholderZh: "JSON，例如 {\"temperature\":[0.1,0.5,1.0]}", placeholderEn: "JSON, e.g. {\"temperature\":[0.1,0.5,1.0]}", wide: true },
  replicates: { labelZh: "重复次数", labelEn: "Replicates", kind: "integer" },
  nullHypothesis: { labelZh: "零假设 H0", labelEn: "Null hypothesis H0", kind: "textarea", wide: true },
  alternativeHypothesis: { labelZh: "备择假设 H1", labelEn: "Alternative hypothesis H1", kind: "textarea", wide: true },
  sample: { labelZh: "样本与采样", labelEn: "Sample", kind: "textarea", wide: true },
  test: { labelZh: "统计检验", labelEn: "Statistical test", kind: "text" },
  alpha: { labelZh: "显著性水平 α", labelEn: "Alpha", kind: "number", placeholderZh: "0.05", placeholderEn: "0.05" },
  effectMeasure: { labelZh: "效应量", labelEn: "Effect measure", kind: "text" },
  confounders: { labelZh: "混杂因素", labelEn: "Confounders", kind: "list", placeholderZh: "可留空；每行一个", placeholderEn: "Optional; one per line", wide: true, allowEmpty: true },
  assumptions: { labelZh: "理论假设", labelEn: "Assumptions", kind: "list", placeholderZh: "每行一条假设", placeholderEn: "One assumption per line", wide: true },
  derivationTarget: { labelZh: "推导目标", labelEn: "Derivation target", kind: "textarea", wide: true },
  boundaryConditions: { labelZh: "适用边界", labelEn: "Boundary conditions", kind: "list", wide: true },
  counterexamplePlan: { labelZh: "反例计划", labelEn: "Counterexample plan", kind: "textarea", wide: true },
  protocol: { labelZh: "实验协议", labelEn: "Protocol", kind: "textarea", wide: true },
  instrumentOrFacility: { labelZh: "仪器或设施", labelEn: "Instrument or facility", kind: "text" },
  samplingPlan: { labelZh: "采样计划", labelEn: "Sampling plan", kind: "textarea", wide: true },
  approvalStatus: { labelZh: "审批状态", labelEn: "Approval status", kind: "approval" },
  operator: { labelZh: "执行人员", labelEn: "Operator", kind: "text" },
  resultImportContract: { labelZh: "结果导入合同", labelEn: "Result import contract", kind: "textarea", wide: true },
};

const DEFAULT_CONFIGS: Record<ExperimentMethodId, Record<string, string>> = {
  model_training_inference: { dataset: "", model: "", baseline: "", seeds: "17, 42, 101", budget: "", smokePlan: "" },
  dataset_analysis_benchmark: { sources: "", dataSchema: "", transform: "", split: "" },
  numerical_simulation: { simulator: "", scenario: "", parameters: "{}", replicates: "3" },
  statistical_causal_test: { nullHypothesis: "", alternativeHypothesis: "", sample: "", test: "", alpha: "0.05", effectMeasure: "", confounders: "" },
  theoretical_symbolic_validation: { assumptions: "", derivationTarget: "", boundaryConditions: "", counterexamplePlan: "" },
  external_instrument_experiment: { protocol: "", instrumentOrFacility: "", samplingPlan: "", approvalStatus: "pending", operator: "", resultImportContract: "" },
};

export type ExperimentMethodFormDraft = {
  researchMode: ExperimentResearchModeId;
  primaryPurpose: ExperimentPurposeId;
  experimentMethod: ExperimentMethodId;
  requestedAdapterId: string;
  researchQuestion: string;
  objective: string;
  primaryMetric: string;
  metricDirection: "maximize" | "minimize" | "target" | "descriptive";
  successCriteria: string;
  failureCriteria: string;
  inconclusiveCriteria: string;
  methodConfigs: Record<ExperimentMethodId, Record<string, string>>;
};

export type ExperimentPlanMethodRequest = {
  researchProfileId: string;
  researchQuestion: string;
  researchMode: ExperimentResearchModeId;
  experimentPurpose: { primaryPurpose: ExperimentPurposeId; secondaryPurposes: ExperimentPurposeId[] };
  experimentMethod: ExperimentMethodId;
  requestedAdapterId: string;
  methodConfig: Record<string, unknown>;
  metricContract: { primaryMetric: string; metrics: Array<{ name: string; direction: string }> };
  decisionContract: { successCriteria: string[]; failureCriteria: string[]; inconclusiveCriteria: string[] };
  objective: string;
  revision: number;
  supersedesPlanId: string;
};

export type TeamExperimentMethodPanelProps = {
  lang: "zh" | "en";
  catalog?: ExperimentMethodCatalogPayload;
  activeContract?: ExperimentContractV2 | null;
  activePlanStatus?: string;
  fallbackResearchQuestion?: string;
  loading: boolean;
  errorMessage?: string;
  disabled?: boolean;
  submitting: boolean;
  canCreatePlan: boolean;
  onSubmit: (payload: ExperimentPlanMethodRequest) => void;
};

function textList(value: string): string[] {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean);
}

function serializeMethodConfig(methodConfig: Record<string, unknown> | undefined): Record<string, string> {
  const result: Record<string, string> = {};
  Object.entries(methodConfig ?? {}).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      result[key] = value.join(", ");
    } else if (value && typeof value === "object") {
      result[key] = JSON.stringify(value, null, 2);
    } else {
      result[key] = value === undefined || value === null ? "" : String(value);
    }
  });
  return result;
}

export function createExperimentMethodFormDraft(
  activeContract?: ExperimentContractV2 | null,
  fallbackResearchQuestion = "",
): ExperimentMethodFormDraft {
  const method = activeContract?.experimentMethod ?? "model_training_inference";
  const methodConfigs = Object.fromEntries(
    Object.entries(DEFAULT_CONFIGS).map(([methodId, config]) => [methodId, { ...config }]),
  ) as ExperimentMethodFormDraft["methodConfigs"];
  if (activeContract) {
    methodConfigs[method] = { ...methodConfigs[method], ...serializeMethodConfig(activeContract.methodConfig) };
  }
  const metric = activeContract?.metricContract.metrics.find((item) => item.name === activeContract.metricContract.primaryMetric)
    ?? activeContract?.metricContract.metrics[0];
  return {
    researchMode: activeContract?.researchMode ?? "full_research_loop",
    primaryPurpose: activeContract?.purpose.primaryPurpose ?? "baseline_comparison",
    experimentMethod: method,
    requestedAdapterId: activeContract?.adapterSelection.requestedAdapterId ?? "",
    researchQuestion: activeContract?.researchQuestion ?? fallbackResearchQuestion,
    objective: activeContract?.objective ?? "",
    primaryMetric: activeContract?.metricContract.primaryMetric ?? "",
    metricDirection: (metric?.direction as ExperimentMethodFormDraft["metricDirection"]) ?? "maximize",
    successCriteria: activeContract?.decisionContract.successCriteria.join("\n") ?? "",
    failureCriteria: activeContract?.decisionContract.failureCriteria.join("\n") ?? "",
    inconclusiveCriteria: activeContract?.decisionContract.inconclusiveCriteria.join("\n") ?? "",
    methodConfigs,
  };
}

export function selectExperimentMethod(
  draft: ExperimentMethodFormDraft,
  experimentMethod: ExperimentMethodId,
): ExperimentMethodFormDraft {
  return {
    ...draft,
    experimentMethod,
    requestedAdapterId: experimentMethod === draft.experimentMethod ? draft.requestedAdapterId : "",
  };
}

function parseMethodConfigValue(value: string, definition: MethodFieldDefinition): unknown {
  if (definition.kind === "list") return textList(value);
  if (definition.kind === "integer_list") return textList(value).map((item) => Number.parseInt(item, 10)).filter(Number.isFinite);
  if (definition.kind === "integer") return Number.parseInt(value, 10) || 0;
  if (definition.kind === "number") return Number.parseFloat(value) || 0;
  if (definition.kind === "json") {
    try {
      return JSON.parse(value || "{}");
    } catch {
      return value;
    }
  }
  return value.trim();
}

export function buildExperimentPlanMethodRequest(
  draft: ExperimentMethodFormDraft,
  method: ExperimentMethodDescriptor,
  activeContract?: ExperimentContractV2 | null,
): ExperimentPlanMethodRequest {
  const rawConfig = draft.methodConfigs[draft.experimentMethod];
  const methodConfig = Object.fromEntries(
    method.requiredConfigFields.map((field) => {
      const definition = METHOD_FIELD_DEFINITIONS[field] ?? { labelZh: field, labelEn: field, kind: "text" as const };
      return [field, parseMethodConfigValue(rawConfig[field] ?? "", definition)];
    }),
  );
  return {
    researchProfileId: activeContract?.researchProfileId || "generic-research",
    researchQuestion: draft.researchQuestion.trim(),
    researchMode: draft.researchMode,
    experimentPurpose: { primaryPurpose: draft.primaryPurpose, secondaryPurposes: [] },
    experimentMethod: draft.experimentMethod,
    requestedAdapterId: draft.requestedAdapterId,
    methodConfig,
    metricContract: {
      primaryMetric: draft.primaryMetric.trim(),
      metrics: [{ name: draft.primaryMetric.trim(), direction: draft.metricDirection }],
    },
    decisionContract: {
      successCriteria: textList(draft.successCriteria),
      failureCriteria: textList(draft.failureCriteria),
      inconclusiveCriteria: textList(draft.inconclusiveCriteria),
    },
    objective: draft.objective.trim(),
    revision: (activeContract?.revision ?? 0) + 1,
    supersedesPlanId: activeContract?.planId ?? "",
  };
}

export function isExperimentMethodDraftComplete(
  draft: ExperimentMethodFormDraft,
  method?: ExperimentMethodDescriptor,
): boolean {
  if (!method || !draft.researchQuestion.trim() || !draft.primaryMetric.trim()) return false;
  if (!textList(draft.successCriteria).length || !textList(draft.failureCriteria).length || !textList(draft.inconclusiveCriteria).length) return false;
  const config = draft.methodConfigs[draft.experimentMethod];
  return method.requiredConfigFields.every((field) => {
    const definition = METHOD_FIELD_DEFINITIONS[field];
    return definition?.allowEmpty || Boolean(config[field]?.trim());
  });
}

function MethodField({
  field,
  value,
  lang,
  disabled,
  onChange,
}: {
  field: string;
  value: string;
  lang: "zh" | "en";
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const definition = METHOD_FIELD_DEFINITIONS[field] ?? { labelZh: field, labelEn: field, kind: "text" as const };
  const label = lang === "zh" ? definition.labelZh : definition.labelEn;
  const placeholder = lang === "zh" ? definition.placeholderZh : definition.placeholderEn;
  const className = definition.wide ? styles.fieldWide : styles.field;
  if (definition.kind === "textarea" || definition.kind === "list" || definition.kind === "json") {
    return (
      <label className={className}>
        <span>{label}</span>
        <VNativeTextarea value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} placeholder={placeholder} rows={definition.kind === "json" ? 4 : 2} />
      </label>
    );
  }
  if (definition.kind === "approval") {
    return (
      <label className={className}>
        <span>{label}</span>
        <VNativeSelect value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
          <option value="not_required">{lang === "zh" ? "无需审批" : "Not required"}</option>
          <option value="pending">{lang === "zh" ? "审批中" : "Pending"}</option>
          <option value="approved">{lang === "zh" ? "已批准" : "Approved"}</option>
          <option value="rejected">{lang === "zh" ? "已拒绝" : "Rejected"}</option>
        </VNativeSelect>
      </label>
    );
  }
  return (
    <label className={className}>
      <span>{label}</span>
      <VNativeInput
        type={definition.kind === "integer" || definition.kind === "number" ? "number" : "text"}
        step={definition.kind === "number" ? "any" : undefined}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        placeholder={placeholder}
      />
    </label>
  );
}

export function TeamExperimentMethodPanel({
  lang,
  catalog,
  activeContract,
  activePlanStatus = "",
  fallbackResearchQuestion = "",
  loading,
  errorMessage,
  disabled = false,
  submitting,
  canCreatePlan,
  onSubmit,
}: TeamExperimentMethodPanelProps) {
  const [draft, setDraft] = useState(() => createExperimentMethodFormDraft(activeContract, fallbackResearchQuestion));
  useEffect(() => {
    setDraft(createExperimentMethodFormDraft(activeContract, fallbackResearchQuestion));
  }, [activeContract?.planId, activeContract?.revision, fallbackResearchQuestion]);

  const selectedMethod = catalog?.methods.find((item) => item.methodId === draft.experimentMethod);
  const adapterSelection = selectedMethod?.adapterAvailability[draft.researchMode];
  const adaptersForMethod = catalog?.adapters.filter((adapter) => adapter.method === draft.experimentMethod) ?? [];
  const selectedAdapter = adaptersForMethod.find((adapter) => adapter.adapterId === draft.requestedAdapterId);
  const locked = disabled || submitting || /running/i.test(activePlanStatus);
  const complete = isExperimentMethodDraftComplete(draft, selectedMethod);
  const isZh = lang === "zh";
  const selectionSource = activeContract?.experimentMethod === draft.experimentMethod ? (isZh ? "当前计划" : "Active plan") : (isZh ? "用户选择" : "User selection");
  const submitLabel = activeContract
    ? (isZh ? "保存为新版本" : "Save new revision")
    : (isZh ? "保存实验配置" : "Save experiment setup");

  const updateConfig = (field: string, value: string) => {
    setDraft((current) => ({
      ...current,
      methodConfigs: {
        ...current.methodConfigs,
        [current.experimentMethod]: { ...current.methodConfigs[current.experimentMethod], [field]: value },
      },
    }));
  };

  if (loading && !catalog) return <div className={styles.loading} aria-label={isZh ? "读取实验方式" : "Loading experiment methods"} />;
  if (!catalog) return <div className={styles.error}>{errorMessage || (isZh ? "实验方式目录暂不可用。" : "Experiment method catalog is unavailable.")}</div>;

  return (
    <section className={styles.panel} data-experiment-method-panel="true" data-selected-method={draft.experimentMethod} aria-label={isZh ? "实验方式配置" : "Experiment method setup"}>
      <div className={styles.header}>
        <div>
          <strong>{isZh ? "实验方式" : "Experiment method"}</strong>
          <span>{isZh ? "团队保持不变；切换方法只替换计划字段和执行能力。" : "The team stays fixed; switching methods only changes plan fields and execution capability."}</span>
        </div>
        <span className={styles.sourceBadge}>{selectionSource}</span>
      </div>

      <div className={styles.section}>
        <span>{isZh ? "科研闭环" : "Research loop"}</span>
        <div className={styles.segmented} role="group" aria-label={isZh ? "科研闭环模式" : "Research loop mode"}>
          {catalog.researchModes.map((mode) => (
            <VNativeButton
              key={mode.modeId}
              className={[styles.segment, draft.researchMode === mode.modeId ? styles.segmentActive : ""].join(" ")}
              aria-pressed={draft.researchMode === mode.modeId}
              disabled={locked}
              onClick={() => setDraft((current) => ({ ...current, researchMode: mode.modeId }))}
            >
              {isZh ? mode.labelZh : mode.labelEn}
            </VNativeButton>
          ))}
        </div>
      </div>

      <div className={styles.selectionRow}>
        <label className={styles.field}>
          <span>{isZh ? "实验目的" : "Experiment purpose"}</span>
          <VNativeSelect value={draft.primaryPurpose} onChange={(event) => setDraft((current) => ({ ...current, primaryPurpose: event.target.value as ExperimentPurposeId }))} disabled={locked}>
            {catalog.experimentPurposes.map((purpose) => <option key={purpose.purposeId} value={purpose.purposeId}>{isZh ? purpose.labelZh : purpose.labelEn}</option>)}
          </VNativeSelect>
        </label>
        <div className={styles.section}>
          <span>{isZh ? "验证方法" : "Validation method"}</span>
          <div className={styles.methodGrid} role="group" aria-label={isZh ? "实验方法" : "Experiment methods"}>
            {catalog.methods.map((method) => (
              <VNativeButton
                key={method.methodId}
                className={[styles.methodButton, draft.experimentMethod === method.methodId ? styles.methodButtonActive : ""].join(" ")}
                aria-pressed={draft.experimentMethod === method.methodId}
                disabled={locked}
                onClick={() => setDraft((current) => selectExperimentMethod(current, method.methodId))}
              >
                {isZh ? method.labelZh : method.labelEn}
              </VNativeButton>
            ))}
          </div>
        </div>
      </div>

      {activeContract?.recommendation ? (
        <div className={styles.recommendation}>
          <strong>{isZh ? "Agent 推荐" : "Agent recommendation"} · {Math.round(activeContract.recommendation.confidence * 100)}%</strong>
          <span>{activeContract.recommendation.reason}</span>
        </div>
      ) : null}

      <label className={styles.fieldWide}>
        <span>{isZh ? "执行器" : "Execution adapter"}</span>
        <VNativeSelect
          value={draft.requestedAdapterId}
          onChange={(event) => setDraft((current) => ({ ...current, requestedAdapterId: event.target.value }))}
          disabled={locked}
          aria-label={isZh ? "执行器选择" : "Execution adapter selection"}
        >
          <option value="">{isZh ? "自动选择（仅使用默认可用执行器）" : "Automatic selection (default available adapters only)"}</option>
          {adaptersForMethod.map((adapter) => (
            <option key={adapter.adapterId} value={adapter.adapterId}>
              {adapter.adapterId}{adapter.requiresExplicitSelection ? (isZh ? "（需显式选择）" : " (explicit selection required)") : ""}
            </option>
          ))}
        </VNativeSelect>
      </label>

      <div className={[styles.adapterStatus, (selectedAdapter || adapterSelection?.resolvedAdapterId) ? styles.adapterStatusReady : styles.adapterStatusBlocked].join(" ")} aria-live="polite">
        {(selectedAdapter || adapterSelection?.resolvedAdapterId) ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
        <div>
          <strong>{selectedAdapter?.adapterId || adapterSelection?.resolvedAdapterId || (isZh ? "执行器尚未就绪" : "Execution Adapter unavailable")}</strong>
          <span>{selectedAdapter ? `${selectedAdapter.adapterVersion} · ${selectedAdapter.requiresExplicitSelection ? (isZh ? "用户显式选择；仍需通过环境预检" : "user-selected; environment preflight still required") : (isZh ? "用户选择" : "user-selected")}` : adapterSelection?.resolvedAdapterId ? `${adapterSelection.resolvedAdapterVersion} · ${adapterSelection.selectionSource}` : adapterSelection?.unavailableReason || (isZh ? "可以保存计划，但不能开始真实执行。" : "The plan can be saved, but a real run cannot start.")}</span>
        </div>
      </div>

      <div className={styles.form}>
        <label className={styles.fieldWide}>
          <span>{isZh ? "待研究问题" : "Research question"}</span>
          <VNativeTextarea value={draft.researchQuestion} onChange={(event) => setDraft((current) => ({ ...current, researchQuestion: event.target.value }))} disabled={locked} rows={2} />
        </label>
        <label className={styles.fieldWide}>
          <span>{isZh ? "本轮目标" : "Objective"}</span>
          <VNativeTextarea value={draft.objective} onChange={(event) => setDraft((current) => ({ ...current, objective: event.target.value }))} disabled={locked} rows={2} />
        </label>
        <label className={styles.field}>
          <span>{isZh ? "主指标" : "Primary metric"}</span>
          <VNativeInput value={draft.primaryMetric} onChange={(event) => setDraft((current) => ({ ...current, primaryMetric: event.target.value }))} disabled={locked} />
        </label>
        <label className={styles.field}>
          <span>{isZh ? "指标方向" : "Metric direction"}</span>
          <VNativeSelect value={draft.metricDirection} onChange={(event) => setDraft((current) => ({ ...current, metricDirection: event.target.value as ExperimentMethodFormDraft["metricDirection"] }))} disabled={locked}>
            <option value="maximize">{isZh ? "越高越好" : "Maximize"}</option>
            <option value="minimize">{isZh ? "越低越好" : "Minimize"}</option>
            <option value="target">{isZh ? "接近目标" : "Target"}</option>
            <option value="descriptive">{isZh ? "描述性指标" : "Descriptive"}</option>
          </VNativeSelect>
        </label>
        {selectedMethod?.requiredConfigFields.map((field) => (
          <MethodField key={field} field={field} value={draft.methodConfigs[draft.experimentMethod][field] ?? ""} lang={lang} disabled={locked} onChange={(value) => updateConfig(field, value)} />
        ))}
      </div>

      <div className={styles.criteria}>
        <label className={styles.field}>
          <span>{isZh ? "支持条件" : "Support criteria"}</span>
          <VNativeTextarea value={draft.successCriteria} onChange={(event) => setDraft((current) => ({ ...current, successCriteria: event.target.value }))} disabled={locked} rows={3} />
        </label>
        <label className={styles.field}>
          <span>{isZh ? "反驳条件" : "Refute criteria"}</span>
          <VNativeTextarea value={draft.failureCriteria} onChange={(event) => setDraft((current) => ({ ...current, failureCriteria: event.target.value }))} disabled={locked} rows={3} />
        </label>
        <label className={styles.field}>
          <span>{isZh ? "不确定条件" : "Inconclusive criteria"}</span>
          <VNativeTextarea value={draft.inconclusiveCriteria} onChange={(event) => setDraft((current) => ({ ...current, inconclusiveCriteria: event.target.value }))} disabled={locked} rows={3} />
        </label>
      </div>

      {errorMessage ? <div className={styles.error}>{errorMessage}</div> : null}
      <div className={styles.actions}>
        <span>{locked && /running/i.test(activePlanStatus) ? (isZh ? "实验运行中，方法切换已锁定。" : "Method switching is locked while a run is active.") : complete ? (isZh ? "配置字段已齐，可以保存计划。" : "The setup is complete and can be saved.") : (isZh ? "补齐方法字段、判断标准和主指标后保存。" : "Complete the method fields, decision criteria, and primary metric.")}</span>
        <VNativeButton
          className={styles.primaryAction}
          disabled={locked || !canCreatePlan || !complete}
          onClick={() => selectedMethod && onSubmit(buildExperimentPlanMethodRequest(draft, selectedMethod, activeContract))}
        >
          <Save size={14} />
          {submitting ? (isZh ? "保存中" : "Saving") : submitLabel}
        </VNativeButton>
      </div>
    </section>
  );
}
