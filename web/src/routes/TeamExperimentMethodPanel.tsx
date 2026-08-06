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
import { VNativeButton, VNativeInput, VNativeTextarea, VStringSelect, VTabs } from "../components/vui";
import type { ExperimentHypothesisCandidateSummary } from "./teams/experimentLoopModel";
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

/** Productize raw adapter resolver errors into actionable Chinese/English copy. */
export function productizeAdapterUnavailableReason(
  reason: string | undefined,
  lang: "zh" | "en",
): { title: string; body: string; capabilities: string[] } {
  const raw = String(reason || "").trim();
  const capsMatch = raw.match(/capabilities?:\s*([^.]+)/i);
  const capabilities = capsMatch
    ? capsMatch[1].split(/[,\s]+/).map((item) => item.trim()).filter(Boolean)
    : [];
  if (/not required/i.test(raw)) {
    return {
      title: lang === "zh" ? "当前模式不需要执行器" : "No adapter required for this mode",
      body: lang === "zh"
        ? "可以只做规划与假设；切换到需要执行的闭环模式后再绑定执行器。"
        : "Planning-only mode. Switch to an execution research mode before binding an adapter.",
      capabilities,
    };
  }
  if (capabilities.length) {
    return {
      title: lang === "zh" ? "执行器尚未就绪" : "Execution adapter not ready",
      body: lang === "zh"
        ? `当前没有满足能力 ${capabilities.join("、")} 的执行器。可先保存计划，或在上方选择/配置可用执行器后再跑真实验。`
        : `No adapter provides ${capabilities.join(", ")}. Save the plan first, or pick a capable adapter above before a real run.`,
      capabilities,
    };
  }
  if (/no available adapter|not registered|unresolved/i.test(raw) || !raw) {
    return {
      title: lang === "zh" ? "执行器尚未就绪" : "Execution adapter not ready",
      body: lang === "zh"
        ? "尚未登记可用执行器。可以先完善并保存实验计划；需要真跑时再配置满足 full_run / prepare 的执行器。"
        : "No available adapter is registered. You can still save the plan; configure an adapter before a real run.",
      capabilities,
    };
  }
  return {
    title: lang === "zh" ? "执行器尚未就绪" : "Execution adapter not ready",
    body: lang === "zh"
      ? `${raw}。可以先保存计划，暂不开始真实执行。`
      : `${raw}. You can save the plan without starting a real run.`,
    capabilities,
  };
}

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
  preferredExperimentMethod?: ExperimentMethodId;
  activePlanStatus?: string;
  fallbackResearchQuestion?: string;
  loading: boolean;
  errorMessage?: string;
  disabled?: boolean;
  submitting: boolean;
  canCreatePlan: boolean;
  onSubmit: (payload: ExperimentPlanMethodRequest) => void;
  hypotheses?: ExperimentHypothesisCandidateSummary[];
  completingCandidateId?: string;
  onCompleteHypothesis?: (
    candidateId: string,
    payload: ExperimentPlanMethodRequest,
  ) => void;
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
  preferredExperimentMethod?: ExperimentMethodId,
): ExperimentMethodFormDraft {
  const method = preferredExperimentMethod ?? activeContract?.experimentMethod ?? "model_training_inference";
  const methodConfigs = Object.fromEntries(
    Object.entries(DEFAULT_CONFIGS).map(([methodId, config]) => [methodId, { ...config }]),
  ) as ExperimentMethodFormDraft["methodConfigs"];
  if (activeContract) {
    methodConfigs[method] = { ...methodConfigs[method], ...serializeMethodConfig(activeContract.methodConfig) };
  }
  const metrics = activeContract?.metricContract?.metrics ?? [];
  const primaryMetric = activeContract?.metricContract?.primaryMetric ?? "";
  const metric = metrics.find((item) => item.name === primaryMetric) ?? metrics[0];
  const decisionContract = activeContract?.decisionContract;
  return {
    researchMode: activeContract?.researchMode ?? "full_research_loop",
    primaryPurpose: activeContract?.purpose?.primaryPurpose ?? "baseline_comparison",
    experimentMethod: method,
    requestedAdapterId: activeContract?.adapterSelection?.requestedAdapterId ?? "",
    researchQuestion: activeContract?.researchQuestion ?? fallbackResearchQuestion,
    objective: activeContract?.objective ?? "",
    primaryMetric,
    metricDirection: (metric?.direction as ExperimentMethodFormDraft["metricDirection"]) ?? "maximize",
    successCriteria: (decisionContract?.successCriteria ?? []).join("\n"),
    failureCriteria: (decisionContract?.failureCriteria ?? []).join("\n"),
    inconclusiveCriteria: (decisionContract?.inconclusiveCriteria ?? []).join("\n"),
    methodConfigs,
  };
}

export function createExperimentMethodDraftSyncKey(
  activeContract?: ExperimentContractV2 | null,
  fallbackResearchQuestion = "",
  preferredExperimentMethod?: ExperimentMethodId,
): string {
  return JSON.stringify({
    activeContract: activeContract ?? null,
    fallbackResearchQuestion,
    preferredExperimentMethod: preferredExperimentMethod ?? "",
  });
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
        <VStringSelect
          ariaLabel={lang === "zh" ? "审批状态" : "Approval status"}
          value={value}
          isDisabled={disabled}
          onValueChange={onChange}
          options={[
            { value: "not_required", label: lang === "zh" ? "无需审批" : "Not required" },
            { value: "pending", label: lang === "zh" ? "审批中" : "Pending" },
            { value: "approved", label: lang === "zh" ? "已批准" : "Approved" },
            { value: "rejected", label: lang === "zh" ? "已拒绝" : "Rejected" },
          ]}
        />
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
  preferredExperimentMethod,
  activePlanStatus = "",
  fallbackResearchQuestion = "",
  loading,
  errorMessage,
  disabled = false,
  submitting,
  canCreatePlan,
  onSubmit,
  hypotheses = [],
  completingCandidateId = "",
  onCompleteHypothesis,
}: TeamExperimentMethodPanelProps) {
  const [draft, setDraft] = useState(() => createExperimentMethodFormDraft(
    activeContract,
    fallbackResearchQuestion,
    preferredExperimentMethod,
  ));
  const scientificCandidatesNeedingDesign = hypotheses.filter(
    (candidate) => (
      candidate.hypothesisKind !== "engineering_proxy"
      && (
        !candidate.valid
        || candidate.missingExperimentPlanFields.length > 0
      )
    ),
  );
  const [selectedScientificCandidateId, setSelectedScientificCandidateId] = useState(
    () => scientificCandidatesNeedingDesign[0]?.candidateId ?? "",
  );
  const draftSyncKey = createExperimentMethodDraftSyncKey(
    activeContract,
    fallbackResearchQuestion,
    preferredExperimentMethod,
  );
  useEffect(() => {
    setDraft(createExperimentMethodFormDraft(activeContract, fallbackResearchQuestion, preferredExperimentMethod));
  }, [draftSyncKey]);
  useEffect(() => {
    if (
      scientificCandidatesNeedingDesign.length > 0
      && !scientificCandidatesNeedingDesign.some(
        (candidate) => candidate.candidateId === selectedScientificCandidateId,
      )
    ) {
      setSelectedScientificCandidateId(
        scientificCandidatesNeedingDesign[0].candidateId,
      );
    }
  }, [hypotheses, selectedScientificCandidateId]);

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
          <strong>{isZh ? "实验配置" : "Experiment setup"}</strong>
        </div>
        <span className={styles.sourceBadge}>{selectionSource}</span>
      </div>

      <div className={styles.section}>
        <span>{isZh ? "科研闭环" : "Research loop"}</span>
        <VTabs
          density="compact"
          className={styles.researchModeTabs}
          listClassName={styles.researchModeTabsList}
          triggerClassName={styles.researchModeTabsTrigger}
          aria-label={isZh ? "科研闭环模式" : "Research loop mode"}
          value={draft.researchMode}
          onValueChange={(value) => {
            if (locked) {
              return;
            }
            setDraft((current) => ({
              ...current,
              researchMode: value as ExperimentResearchModeId,
            }));
          }}
          items={catalog.researchModes.map((mode) => ({
            id: mode.modeId,
            label: isZh ? mode.labelZh : mode.labelEn,
            disabled: locked,
          }))}
        />
      </div>

      <div className={styles.selectionRow}>
        <label className={styles.field}>
          <span>{isZh ? "实验目的" : "Experiment purpose"}</span>
          <VStringSelect
            ariaLabel={isZh ? "主实验目的" : "Primary purpose"}
            value={draft.primaryPurpose}
            isDisabled={locked}
            onValueChange={(primaryPurpose) => setDraft((current) => ({ ...current, primaryPurpose: primaryPurpose as ExperimentPurposeId }))}
            options={catalog.experimentPurposes.map((purpose) => ({
              value: purpose.purposeId,
              label: isZh ? purpose.labelZh : purpose.labelEn,
            }))}
          />
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

      <div className={styles.fieldWide}>
        <span>{isZh ? "执行器" : "Execution adapter"}</span>
        <div className={styles.adapterChoices} role="group" aria-label={isZh ? "执行器选择" : "Execution adapter selection"}>
          <VNativeButton
            className={[styles.adapterChoice, draft.requestedAdapterId === "" ? styles.adapterChoiceActive : ""].join(" ")}
            aria-pressed={draft.requestedAdapterId === ""}
            disabled={locked}
            onClick={() => setDraft((current) => ({ ...current, requestedAdapterId: "" }))}
          >
            {isZh ? "自动选择（仅使用默认可用执行器）" : "Automatic selection (default available adapters only)"}
          </VNativeButton>
          {adaptersForMethod.map((adapter) => (
            <VNativeButton
              key={adapter.adapterId}
              className={[styles.adapterChoice, draft.requestedAdapterId === adapter.adapterId ? styles.adapterChoiceActive : ""].join(" ")}
              aria-pressed={draft.requestedAdapterId === adapter.adapterId}
              disabled={locked}
              title={adapter.adapterId}
              onClick={() => setDraft((current) => ({ ...current, requestedAdapterId: adapter.adapterId }))}
            >
              {adapter.adapterId}{adapter.requiresExplicitSelection ? (isZh ? "（需显式选择）" : " (explicit selection required)") : ""}
            </VNativeButton>
          ))}
        </div>
      </div>

      {(() => {
        const adapterReady = Boolean(selectedAdapter || adapterSelection?.resolvedAdapterId);
        const blockedCopy = adapterReady
          ? null
          : productizeAdapterUnavailableReason(adapterSelection?.unavailableReason, lang);
        return (
          <div
            className={[styles.adapterStatus, adapterReady ? styles.adapterStatusReady : styles.adapterStatusBlocked].join(" ")}
            aria-live="polite"
            data-testid="experiment-adapter-status"
            data-adapter-ready={adapterReady ? "true" : "false"}
          >
            {adapterReady ? <CheckCircle2 size={14} aria-hidden /> : <AlertTriangle size={14} aria-hidden />}
            <div>
              <strong>
                {selectedAdapter?.adapterId
                  || adapterSelection?.resolvedAdapterId
                  || blockedCopy?.title
                  || (isZh ? "执行器尚未就绪" : "Execution adapter not ready")}
              </strong>
              <span title={blockedCopy?.body || undefined}>
                {selectedAdapter
                  ? selectedAdapter.adapterVersion
                  : adapterSelection?.resolvedAdapterId
                    ? adapterSelection.resolvedAdapterVersion
                    : (isZh ? "可先保存计划" : "Save plan first")}
              </span>
              {!adapterReady && blockedCopy?.capabilities.length ? (
                <span className={styles.adapterCapabilityChips} data-testid="experiment-adapter-missing-caps">
                  {blockedCopy.capabilities.map((cap) => (
                    <em key={cap}>{cap}</em>
                  ))}
                </span>
              ) : null}
            </div>
          </div>
        );
      })()}

      <div className={styles.form}>
        <label className={styles.field}>
          <span>{isZh ? "待研究问题" : "Research question"}</span>
          <VNativeTextarea value={draft.researchQuestion} onChange={(event) => setDraft((current) => ({ ...current, researchQuestion: event.target.value }))} disabled={locked} rows={2} />
        </label>
        <label className={styles.field}>
          <span>{isZh ? "本轮目标" : "Objective"}</span>
          <VNativeTextarea value={draft.objective} onChange={(event) => setDraft((current) => ({ ...current, objective: event.target.value }))} disabled={locked} rows={2} />
        </label>
        <div className={styles.formPair}>
          <label className={styles.field}>
            <span>{isZh ? "主指标" : "Primary metric"}</span>
            <VNativeInput value={draft.primaryMetric} onChange={(event) => setDraft((current) => ({ ...current, primaryMetric: event.target.value }))} disabled={locked} />
          </label>
          <label className={styles.field}>
            <span>{isZh ? "指标方向" : "Metric direction"}</span>
            <VStringSelect
              ariaLabel={isZh ? "指标方向" : "Metric direction"}
              value={draft.metricDirection}
              isDisabled={locked}
              onValueChange={(metricDirection) => setDraft((current) => ({
                ...current,
                metricDirection: metricDirection as ExperimentMethodFormDraft["metricDirection"],
              }))}
              options={[
                { value: "maximize", label: isZh ? "越高越好" : "Maximize" },
                { value: "minimize", label: isZh ? "越低越好" : "Minimize" },
                { value: "target", label: isZh ? "接近目标" : "Target" },
                { value: "descriptive", label: isZh ? "描述性指标" : "Descriptive" },
              ]}
            />
          </label>
        </div>
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

      {activeContract && scientificCandidatesNeedingDesign.length > 0 && onCompleteHypothesis ? (
        <div className={styles.selectionRow} data-scientific-hypothesis-completion="true">
          <label className={styles.field}>
            <span>{isZh ? "待补全的科学假设" : "Scientific hypothesis to complete"}</span>
            <VStringSelect
              ariaLabel={isZh ? "科学候选" : "Scientific candidate"}
              value={selectedScientificCandidateId}
              isDisabled={locked || Boolean(completingCandidateId)}
              onValueChange={setSelectedScientificCandidateId}
              options={scientificCandidatesNeedingDesign.map((candidate) => ({
                value: candidate.candidateId,
                label: candidate.title || candidate.hypothesis || candidate.candidateId,
              }))}
            />
          </label>
          <div className={styles.section}>
            <span>
              {isZh
                ? "生成新的、可审核的修订候选；保留原候选，不创建实验、不自动批准。"
                : "Creates a new reviewable revision; preserves the source and runs nothing."}
            </span>
            <VNativeButton
              type="button"
              disabled={
                locked
                || !complete
                || !selectedScientificCandidateId
                || Boolean(completingCandidateId)
              }
              onClick={() => {
                if (selectedMethod && selectedScientificCandidateId) {
                  onCompleteHypothesis(
                    selectedScientificCandidateId,
                    buildExperimentPlanMethodRequest(
                      draft,
                      selectedMethod,
                      activeContract,
                    ),
                  );
                }
              }}
            >
              <CheckCircle2 size={14} />
              {completingCandidateId
                ? (isZh ? "生成修订中" : "Creating revision")
                : (isZh ? "用当前配置补全假设" : "Complete with current setup")}
            </VNativeButton>
          </div>
        </div>
      ) : null}

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
