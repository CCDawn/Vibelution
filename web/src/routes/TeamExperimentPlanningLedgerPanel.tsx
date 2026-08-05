/**
 * Experiment planning workbench (stepped product surface).
 * Wave 8J base + product IA: setup → review → freeze → run (one step at a time).
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Play, Save, Send } from "lucide-react";

import type { ExperimentMethodId, Team } from "../api/types";
import {
  VButton,
  VMetricChip,
  VNativeButton,
  VNativeInput,
  VStatusChip,
  VStringSelect,
  type VStatusTone,
} from "../components/vui";
import {
  EXPERIMENT_FULL_RUN_RESULT_STATUSES,
  EXPERIMENT_SMOKE_RESULT_STATUSES,
  type EngineeringProxyHypothesisDraft,
  type ExperimentBaselineArtifactDraft,
  type ExperimentFullRunResultDraft,
  type ExperimentFullRunResultStatus,
  type ExperimentKnowledgeIngestionDraft,
  type ExperimentPlanRecord,
  type ExperimentPlanningStatusPayload,
  type ExperimentSmokeResultDraft,
  type ExperimentSmokeResultStatus,
  experimentDeclaredSmokeAdapterId,
  selectBoundedSmokeAdapter,
} from "./teams/experimentLoopModel";
import {
  EXPERIMENT_WORKBENCH_STEPS,
  isExperimentWorkbenchStepUnlocked,
  resolveExperimentWorkbenchStep,
  shortProtocolLabel,
  type ExperimentWorkbenchStepId,
} from "./teams/experimentWorkbenchStepModel";
import { TeamExperimentHypothesisGovernancePanel } from "./TeamExperimentHypothesisGovernancePanel";
import { TeamExperimentMethodPanel, type ExperimentPlanMethodRequest } from "./TeamExperimentMethodPanel";
import experimentStyles from "./TeamsRoute.experiment.styles";
import researchStyles from "./TeamsRoute.research.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...experimentStyles, ...researchStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

type SmokeMetricValue = string | number | boolean;

type SmokeMetricEntry = {
  label: string;
  value: SmokeMetricValue;
};

const smokeBoundaryCopy: Record<string, Record<Lang, string>> = {
  offline_numpy_only: {
    zh: "仅离线 NumPy 代理",
    en: "Offline NumPy proxy only",
  },
  does_not_replace_target_dataset_evaluation: {
    zh: "不替代目标数据集评估",
    en: "Does not replace target-dataset evaluation",
  },
  does_not_validate_neural_realism: {
    zh: "不验证神经真实性",
    en: "Does not validate neural realism",
  },
  no_full_run_promotion_from_proxy_only: {
    zh: "代理结果不可晋升 Full run",
    en: "Proxy result cannot promote a full run",
  },
};

function isSmokeMetricValue(value: unknown): value is SmokeMetricValue {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function readSmokeMetric(
  metrics: Record<string, unknown>,
  group: string,
  key: string,
): SmokeMetricValue | null {
  const metricGroup = metrics[group];
  if (!metricGroup || typeof metricGroup !== "object" || Array.isArray(metricGroup)) {
    return null;
  }
  const value = (metricGroup as Record<string, unknown>)[key];
  return isSmokeMetricValue(value) ? value : null;
}

function buildSmokeMetricEntries(metrics: Record<string, unknown>): SmokeMetricEntry[] {
  const preferredMetrics = [
    { group: "baseline", key: "reconstruction_mse", label: "Baseline MSE" },
    { group: "variant", key: "reconstruction_mse", label: "Variant MSE" },
    { group: "delta", key: "mse_improvement", label: "Improvement" },
    { group: "threshold", key: "mse_improvement", label: "Threshold" },
  ];
  const preferredEntries = preferredMetrics.flatMap(({ group, key, label }) => {
    const value = readSmokeMetric(metrics, group, key);
    return value === null ? [] : [{ label, value }];
  });
  if (preferredEntries.length > 0) {
    return preferredEntries;
  }

  return Object.entries(metrics)
    .flatMap(([group, value]) => {
      if (isSmokeMetricValue(value)) {
        return [{ label: group, value }];
      }
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        return [];
      }
      return Object.entries(value as Record<string, unknown>).flatMap(([key, nestedValue]) =>
        isSmokeMetricValue(nestedValue)
          ? [{ label: `${group}.${key}`, value: nestedValue }]
          : [],
      );
    })
    .slice(0, 6);
}

function smokeStatusTone(status: string): VStatusTone {
  if (status === "passed") {
    return "success";
  }
  if (status === "failed") {
    return "danger";
  }
  return "warning";
}

export function boundedSmokeReviewCopy(
  status: string,
  proxyOnly: boolean,
  lang: Lang,
): { statusLabel: string; actionLabel: string } {
  if (proxyOnly && status === "needs_review") {
    return lang === "zh"
      ? {
          statusLabel: "代理结果 · 需正式证据",
          actionLabel: "查看评审与补证据",
        }
      : {
          statusLabel: "Proxy result · formal evidence required",
          actionLabel: "Review and add evidence",
        };
  }
  return {
    statusLabel:
      status === "needs_review"
        ? (lang === "zh" ? "待人工复核" : "Needs review")
        : status,
    actionLabel: lang === "zh" ? "进入执行与迭代" : "Open execution and iteration",
  };
}

export type TeamExperimentPlanningLedgerPanelProps = {
  lang: Lang;
  selectedTeam: Team | null | undefined;
  experimentPlanningStatus: ExperimentPlanningStatusPayload | null | undefined;
  experimentPlanningStatusQuery: { isFetching: boolean; refetch: () => unknown };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  experimentMethodCatalogQuery: { data?: any; isFetching: boolean; error?: unknown };
  preferredExperimentMethod: string;
  searchParams: URLSearchParams;
  experimentBaselineArtifactDraft: ExperimentBaselineArtifactDraft;
  setExperimentBaselineArtifactDraft: (updater: (draft: ExperimentBaselineArtifactDraft) => ExperimentBaselineArtifactDraft) => void;
  experimentSmokeResultDraft: ExperimentSmokeResultDraft;
  setExperimentSmokeResultDraft: (updater: (draft: ExperimentSmokeResultDraft) => ExperimentSmokeResultDraft) => void;
  experimentFullRunResultDraft: ExperimentFullRunResultDraft;
  setExperimentFullRunResultDraft: (updater: (draft: ExperimentFullRunResultDraft) => ExperimentFullRunResultDraft) => void;
  experimentKnowledgeIngestionDraft: ExperimentKnowledgeIngestionDraft;
  setExperimentKnowledgeIngestionDraft: (updater: (draft: ExperimentKnowledgeIngestionDraft) => ExperimentKnowledgeIngestionDraft) => void;
  selectedTeamCreateExperimentPlanPending: boolean;
  selectedTeamCreateExperimentPlanError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamCreateExperimentPlanResult: any;
  selectedTeamMaterializeEngineeringProxyPending: boolean;
  selectedTeamMaterializeEngineeringProxyError: Error | null;
  selectedTeamCompleteScientificHypothesisCandidateId: string;
  selectedTeamCompleteScientificHypothesisError: Error | null;
  selectedTeamReviewExperimentHypothesisCandidateId: string;
  selectedTeamReviewExperimentHypothesisError: Error | null;
  selectedTeamCreateExperimentHypothesisRevisionCandidateId: string;
  selectedTeamCreateExperimentHypothesisRevisionError: Error | null;
  selectedTeamFreezeExperimentDesignPending: boolean;
  selectedTeamFreezeExperimentDesignError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamFreezeExperimentDesignResult: any;
  selectedTeamRegisterExperimentBaselineArtifactPending: boolean;
  selectedTeamRegisterExperimentBaselineArtifactError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRegisterExperimentBaselineArtifactResult: any;
  selectedTeamRunExperimentSmokePending: boolean;
  selectedTeamRunExperimentSmokeError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRunExperimentSmokeResult: any;
  selectedTeamRegisterExperimentSmokeResultPending: boolean;
  selectedTeamRegisterExperimentSmokeResultError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRegisterExperimentSmokeResultResult: any;
  selectedTeamRegisterExperimentFullRunResultPending: boolean;
  selectedTeamRegisterExperimentFullRunResultError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRegisterExperimentFullRunResultResult: any;
  selectedTeamRequestExperimentKnowledgeIngestionPending: boolean;
  selectedTeamRequestExperimentKnowledgeIngestionError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRequestExperimentKnowledgeIngestionResult: any;
  createExperimentPlanFromWorkspace: (methodRequest?: ExperimentPlanMethodRequest) => void;
  materializeEngineeringProxyHypothesisFromWorkspace: (
    plan: ExperimentPlanRecord,
    draft: EngineeringProxyHypothesisDraft,
  ) => void;
  completeScientificHypothesisFromWorkspace: (
    plan: ExperimentPlanRecord,
    candidateId: string,
    methodRequest: ExperimentPlanMethodRequest,
  ) => void;
  reviewExperimentHypothesisFromWorkspace: (candidateId: string) => void;
  createExperimentHypothesisRevisionFromWorkspace: (
    plan: ExperimentPlanRecord,
    candidateId: string,
  ) => void;
  freezeExperimentDesignFromWorkspace: (plan: ExperimentPlanRecord) => void;
  registerExperimentBaselineArtifactFromWorkspace: (plan: ExperimentPlanRecord) => void;
  runExperimentSmokeFromWorkspace: (plan: ExperimentPlanRecord, adapter: string, seed: number) => void;
  registerExperimentSmokeResultFromWorkspace: (plan: ExperimentPlanRecord) => void;
  registerExperimentFullRunResultFromWorkspace: (plan: ExperimentPlanRecord) => void;
  requestExperimentKnowledgeIngestionFromWorkspace: (plan: ExperimentPlanRecord) => void;
  openIterationWorkspace: () => void;
  renderResearchLoopPanel: (activePlan: ExperimentPlanRecord | null, variant?: "experiment" | "iteration") => ReactNode;
};

export function TeamExperimentPlanningLedgerPanel(props: TeamExperimentPlanningLedgerPanelProps) {
  const {
    lang,
    selectedTeam,
    experimentPlanningStatus,
    experimentPlanningStatusQuery,
    experimentMethodCatalogQuery,
    preferredExperimentMethod,
    searchParams,
    experimentBaselineArtifactDraft,
    setExperimentBaselineArtifactDraft,
    experimentSmokeResultDraft,
    setExperimentSmokeResultDraft,
    experimentFullRunResultDraft,
    setExperimentFullRunResultDraft,
    experimentKnowledgeIngestionDraft,
    setExperimentKnowledgeIngestionDraft,
    selectedTeamCreateExperimentPlanPending,
    selectedTeamCreateExperimentPlanError,
    selectedTeamCreateExperimentPlanResult,
    selectedTeamMaterializeEngineeringProxyPending,
    selectedTeamMaterializeEngineeringProxyError,
    selectedTeamCompleteScientificHypothesisCandidateId,
    selectedTeamCompleteScientificHypothesisError,
    selectedTeamReviewExperimentHypothesisCandidateId,
    selectedTeamReviewExperimentHypothesisError,
    selectedTeamCreateExperimentHypothesisRevisionCandidateId,
    selectedTeamCreateExperimentHypothesisRevisionError,
    selectedTeamFreezeExperimentDesignPending,
    selectedTeamFreezeExperimentDesignError,
    selectedTeamFreezeExperimentDesignResult,
    selectedTeamRegisterExperimentBaselineArtifactPending,
    selectedTeamRegisterExperimentBaselineArtifactError,
    selectedTeamRegisterExperimentBaselineArtifactResult,
    selectedTeamRunExperimentSmokePending,
    selectedTeamRunExperimentSmokeError,
    selectedTeamRunExperimentSmokeResult,
    selectedTeamRegisterExperimentSmokeResultPending,
    selectedTeamRegisterExperimentSmokeResultError,
    selectedTeamRegisterExperimentSmokeResultResult,
    selectedTeamRegisterExperimentFullRunResultPending,
    selectedTeamRegisterExperimentFullRunResultError,
    selectedTeamRegisterExperimentFullRunResultResult,
    selectedTeamRequestExperimentKnowledgeIngestionPending,
    selectedTeamRequestExperimentKnowledgeIngestionError,
    selectedTeamRequestExperimentKnowledgeIngestionResult,
    createExperimentPlanFromWorkspace,
    materializeEngineeringProxyHypothesisFromWorkspace,
    completeScientificHypothesisFromWorkspace,
    reviewExperimentHypothesisFromWorkspace,
    createExperimentHypothesisRevisionFromWorkspace,
    freezeExperimentDesignFromWorkspace,
    registerExperimentBaselineArtifactFromWorkspace,
    runExperimentSmokeFromWorkspace,
    registerExperimentSmokeResultFromWorkspace,
    registerExperimentFullRunResultFromWorkspace,
    requestExperimentKnowledgeIngestionFromWorkspace,
    openIterationWorkspace,
    renderResearchLoopPanel,
  } = props;


    const latestKnowledgeIngestionMutationPayload = selectedTeamRequestExperimentKnowledgeIngestionResult;
    const latestFullRunMutationPayload = selectedTeamRegisterExperimentFullRunResultResult;
    const latestSmokeMutationPayload = selectedTeamRegisterExperimentSmokeResultResult;
    const latestBaselineMutationPayload = selectedTeamRegisterExperimentBaselineArtifactResult;
    const latestMutationPayload = selectedTeamCreateExperimentPlanResult;
    const latestFreezePayload = selectedTeamFreezeExperimentDesignResult;
    const statusPayload =
      experimentPlanningStatus
      ?? latestFreezePayload?.experimentStatus
      ?? latestKnowledgeIngestionMutationPayload?.status
      ?? latestFullRunMutationPayload?.status
      ?? latestSmokeMutationPayload?.status
      ?? latestBaselineMutationPayload?.status
      ?? latestMutationPayload?.status;
    const activePlan =
      statusPayload?.activePlan
      ?? latestFreezePayload?.plan
      ?? latestKnowledgeIngestionMutationPayload?.plan
      ?? latestFullRunMutationPayload?.plan
      ?? latestSmokeMutationPayload?.plan
      ?? latestBaselineMutationPayload?.plan
      ?? latestMutationPayload?.plan
      ?? null;
    const activeBaselineArtifact = activePlan?.baselineSelection.activeBaselineArtifact ?? null;
    const activeSmokeRun = selectedTeamRunExperimentSmokeResult?.smokeRun ?? activePlan?.activeSmokeRun ?? null;
    const activeSmokeReviewCopy = activeSmokeRun
      ? boundedSmokeReviewCopy(activeSmokeRun.status, Boolean(activeSmokeRun.proxyOnly), lang)
      : null;
    const activeSmokeMetricEntries = activeSmokeRun
      ? buildSmokeMetricEntries(activeSmokeRun.metrics ?? {})
      : [];
    const activeSmokeResult = activePlan?.activeSmokeResult ?? null;
    const activeFullRunResult = activePlan?.activeFullRunResult ?? null;
    const knowledgeIngestion = activePlan?.knowledgeIngestion ?? null;
    const activeExperimentContract = activePlan?.experimentContract ?? null;
    const activeMethodDescriptor = experimentMethodCatalogQuery.data?.methods.find(
      (method: any) => method.methodId === activeExperimentContract?.experimentMethod,
    );
    const activeResearchModeDescriptor = experimentMethodCatalogQuery.data?.researchModes.find(
      (mode: any) => mode.modeId === activeExperimentContract?.researchMode,
    );
    const activePurposeDescriptor = experimentMethodCatalogQuery.data?.experimentPurposes.find(
      (purpose: any) => purpose.purposeId === activeExperimentContract?.purpose.primaryPurpose,
    );
    const boundedSmokeAdapters = (experimentMethodCatalogQuery.data?.adapters ?? []).filter(
      (adapter: any) =>
        adapter.method === activeExperimentContract?.experimentMethod
        && adapter.availability === "available"
        && adapter.formalResult !== true
        && Array.isArray(adapter.capabilities)
        && adapter.capabilities.includes("smoke"),
    );
    const declaredSmokeAdapterId = experimentDeclaredSmokeAdapterId(activePlan);
    const activeSmokeAdapter = selectBoundedSmokeAdapter(boundedSmokeAdapters, activePlan);
    const hypotheses = statusPayload?.hypothesisCandidates ?? [];
    const canDraftPlan = Boolean(selectedTeam?.teamId && statusPayload?.latestExperimentRound && !selectedTeamCreateExperimentPlanPending);
    const explicitDesignGate = activePlan?.designGate;
    const designExecutionAllowed = !explicitDesignGate || explicitDesignGate.status === "frozen";
    const activeMemoryVariableContract =
      statusPayload?.lifecycleProjection?.stage2.memoryContextSummary?.allowedVariableContract;
    const iterationDesignRequiresGovernance = Boolean(explicitDesignGate?.sourceProposalId);
    const iterationVariableGovernanceReady = Boolean(
      !iterationDesignRequiresGovernance
      || (
        activeMemoryVariableContract?.status !== "missing"
        && activeMemoryVariableContract?.variables.length
        && activeMemoryVariableContract?.frozenControls.length
      ),
    );
    const canFreezeDesign = Boolean(
      selectedTeam?.teamId
      && activePlan
      && explicitDesignGate?.status === "draft"
      && activePlan.contractValidation?.valid
      && activePlan.readiness.readyForPlanReview
      && iterationVariableGovernanceReady
      && !selectedTeamFreezeExperimentDesignPending,
    );
    const canRegisterBaselineArtifact = Boolean(
      selectedTeam?.teamId
      && activePlan
      && designExecutionAllowed
      && !activePlan.baselineSelection.activeBaselineReady
      && experimentBaselineArtifactDraft.artifactPath.trim()
      && experimentBaselineArtifactDraft.reproductionCommand.trim()
      && !selectedTeamRegisterExperimentBaselineArtifactPending,
    );
    const canRegisterSmokeResult = Boolean(
      selectedTeam?.teamId
      && activePlan
      && designExecutionAllowed
      && activePlan.baselineSelection.activeBaselineReady
      && experimentSmokeResultDraft.metricValue.trim()
      && (experimentSmokeResultDraft.resultPath.trim() || experimentSmokeResultDraft.logRef.trim())
      && !selectedTeamRegisterExperimentSmokeResultPending,
    );
    const canRunBoundedSmoke = Boolean(
      selectedTeam?.teamId
      && activePlan
      && designExecutionAllowed
      && activePlan.readiness.readyForBoundedSmokeRun
      && activeSmokeAdapter?.adapterId
      && !selectedTeamRunExperimentSmokePending,
    );
    const smokeGateDetail = !designExecutionAllowed
      ? (lang === "zh"
        ? "先完成假设审查并冻结设计；之后可运行自包含受控 Smoke。"
        : "Review the hypothesis and freeze the design first; then the bounded self-contained Smoke becomes available.")
      : !activeSmokeAdapter
        ? declaredSmokeAdapterId
          ? (lang === "zh"
            ? `计划声明的离线 Smoke 执行器不可用：${declaredSmokeAdapterId}。`
            : `The offline smoke adapter declared by the plan is unavailable: ${declaredSmokeAdapterId}.`)
          : (lang === "zh"
            ? "当前实验方式没有可用的白名单离线 Smoke 执行器。"
            : "No allowlisted offline smoke adapter is available for this method.")
        : !activeBaselineArtifact
        ? activePlan?.readiness.readyForBoundedSmokeRun
          ? (lang === "zh"
            ? "自包含执行器会在 Smoke 中同时计算 baseline 与 variant；无需手工登记 baseline artifact。"
            : "The self-contained runner computes baseline and variant in the Smoke; no manual baseline artifact is required.")
          : (lang === "zh"
            ? "冻结设计尚未满足自包含 Smoke 合同。"
            : "The frozen design is not ready for the self-contained Smoke contract.")
        : (lang === "zh"
            ? "仅运行后端白名单离线 Smoke；不会启动 full run，也不会生成正式科学结论。"
            : "Runs only the backend allowlisted offline smoke; no full run or formal scientific claim.");
    const canRegisterFullRunResult = Boolean(
      selectedTeam?.teamId
      && activePlan
      && designExecutionAllowed
      && activePlan.readiness.readyForFullRun
      && experimentFullRunResultDraft.metricValue.trim()
      && (experimentFullRunResultDraft.resultPath.trim() || experimentFullRunResultDraft.logRef.trim())
      && !selectedTeamRegisterExperimentFullRunResultPending,
    );
    const canRequestKnowledgeIngestion = Boolean(
      selectedTeam?.teamId
      && activePlan
      && activeFullRunResult
      && String(activeFullRunResult.status || "").toLowerCase() === "passed"
      && activePlan.readiness.readyForKnowledgeIngestion
      && !knowledgeIngestion
      && !selectedTeamRequestExperimentKnowledgeIngestionPending,
    );
    const hasApprovedHypothesis = hypotheses.some((candidate: any) => candidate.approvedForExperiment);
    const designFrozen = explicitDesignGate
      ? explicitDesignGate.status === "frozen"
      : designExecutionAllowed && Boolean(activePlan);
    const stepInput = useMemo(() => ({
      hasActivePlan: Boolean(activePlan),
      hasApprovedHypothesis,
      designFrozen: Boolean(designFrozen),
      readyForBoundedSmoke: Boolean(activePlan?.readiness.readyForBoundedSmokeRun),
    }), [activePlan, hasApprovedHypothesis, designFrozen]);
    const autoStep = resolveExperimentWorkbenchStep(stepInput);
    const [stepOverride, setStepOverride] = useState<ExperimentWorkbenchStepId | null>(null);
    useEffect(() => {
      setStepOverride(null);
    }, [autoStep]);
    const currentStep = stepOverride && isExperimentWorkbenchStepUnlocked(stepOverride, stepInput)
      ? stepOverride
      : autoStep;

    const methodPanel = (
      <TeamExperimentMethodPanel
        lang={lang}
        catalog={experimentMethodCatalogQuery.data}
        activeContract={activeExperimentContract}
        preferredExperimentMethod={
          experimentMethodCatalogQuery.data?.methods.some(
            (method: any) => method.methodId === searchParams.get("experimentMethod"),
          )
            ? searchParams.get("experimentMethod") as ExperimentMethodId
            : ((preferredExperimentMethod as ExperimentMethodId | "") || undefined)
        }
        activePlanStatus={activePlan?.status ?? ""}
        fallbackResearchQuestion={
          activePlan?.goal
          || activePlan?.topic
          || statusPayload?.latestExperimentRound?.goal
          || statusPayload?.latestExperimentRound?.topic
          || ""
        }
        loading={experimentMethodCatalogQuery.isFetching}
        submitting={selectedTeamCreateExperimentPlanPending}
        canCreatePlan={canDraftPlan}
        onSubmit={createExperimentPlanFromWorkspace}
        hypotheses={hypotheses}
        completingCandidateId={selectedTeamCompleteScientificHypothesisCandidateId}
        onCompleteHypothesis={(candidateId, methodRequest) => {
          if (activePlan) {
            completeScientificHypothesisFromWorkspace(
              activePlan,
              candidateId,
              methodRequest,
            );
          }
        }}
        errorMessage={
          selectedTeamCompleteScientificHypothesisError?.message
          || (
            experimentMethodCatalogQuery.error instanceof Error
              ? experimentMethodCatalogQuery.error.message
              : selectedTeamCreateExperimentPlanError?.message
          )
        }
      />
    );

    const reviewPanel = (
      <TeamExperimentHypothesisGovernancePanel
        lang={lang}
        activePlan={activePlan}
        hypotheses={hypotheses}
        materializing={selectedTeamMaterializeEngineeringProxyPending}
        reviewingCandidateId={selectedTeamReviewExperimentHypothesisCandidateId}
        revisingCandidateId={selectedTeamCreateExperimentHypothesisRevisionCandidateId}
        materializeError={selectedTeamMaterializeEngineeringProxyError}
        reviewError={selectedTeamReviewExperimentHypothesisError}
        revisionError={selectedTeamCreateExperimentHypothesisRevisionError}
        onMaterialize={materializeEngineeringProxyHypothesisFromWorkspace}
        onReview={reviewExperimentHypothesisFromWorkspace}
        onCreateRevision={createExperimentHypothesisRevisionFromWorkspace}
      />
    );

    return (
      <section
        className={styles.experimentLedgerPanel}
        aria-label={lang === "zh" ? "实验规划工作台" : "Experiment planning workbench"}
        data-testid="experiment-planning-workbench"
        data-workbench-step={currentStep}
      >
        <nav className={styles.experimentWorkbenchSteps} aria-label={lang === "zh" ? "实验规划步骤" : "Planning steps"}>
          {EXPERIMENT_WORKBENCH_STEPS.map((step, index) => {
            const unlocked = isExperimentWorkbenchStepUnlocked(step.id, stepInput);
            const active = currentStep === step.id;
            return (
              <VButton
                key={step.id}
                type="button"
                density="compact"
                variant={active ? "primary" : "secondary"}
                className={styles.experimentWorkbenchStep}
                isDisabled={!unlocked}
                data-testid={`experiment-workbench-step-${step.id}`}
                data-active={active ? "true" : "false"}
                data-unlocked={unlocked ? "true" : "false"}
                onPress={() => {
                  if (!unlocked) return;
                  setStepOverride(step.id);
                }}
              >
                {`${index + 1}. ${lang === "zh" ? step.zh : step.en}`}
              </VButton>
            );
          })}
        </nav>

        <div className={styles.experimentWorkbenchStepBody}>
          {currentStep === "setup" ? methodPanel : null}
          {currentStep === "review" ? (
            activePlan ? reviewPanel : (
              <div className={styles.experimentLedgerEmpty}>
                <AlertTriangle size={14} />
                <span>{lang === "zh" ? "请先在「配置实验」保存计划。" : "Save a plan in Setup first."}</span>
              </div>
            )
          ) : null}
          {currentStep === "protocol" && activePlan ? (
            <>
            <div className={styles.experimentPlanGrid}>
              <article className={styles.experimentPlanSummary}>
                <div>
                  <span>{lang === "zh" ? "当前计划" : "Active plan"}</span>
                  <strong>{activePlan.title}</strong>
                </div>
                <p className="line-clamp-2" title={activePlan.goal || activePlan.topic || undefined}>
                  {activePlan.goal || activePlan.topic || (lang === "zh" ? "实验目标待补齐" : "Experiment goal pending")}
                </p>
                <div className={styles.experimentPlanFields}>
                  {activeExperimentContract ? (
                    <span className={styles.experimentProtocolChip}>
                      {(lang === "zh" ? activePurposeDescriptor?.labelZh : activePurposeDescriptor?.labelEn)
                        || activeExperimentContract.purpose.primaryPurpose}
                    </span>
                  ) : null}
                  {activeExperimentContract ? (
                    <span className={styles.experimentProtocolChip}>
                      {(lang === "zh" ? activeMethodDescriptor?.labelZh : activeMethodDescriptor?.labelEn)
                        || activeExperimentContract.experimentMethod}
                    </span>
                  ) : null}
                  {activePlan.experimentPlan.dataset ? (
                    <span className={styles.experimentProtocolChip} title={activePlan.experimentPlan.dataset}>
                      {lang === "zh" ? "数据" : "Data"} · {shortProtocolLabel(activePlan.experimentPlan.dataset)}
                    </span>
                  ) : null}
                  {activePlan.experimentPlan.metric ? (
                    <span className={styles.experimentProtocolChip} title={activePlan.experimentPlan.metric}>
                      {lang === "zh" ? "指标" : "Metric"} · {shortProtocolLabel(activePlan.experimentPlan.metric, 28)}
                    </span>
                  ) : null}
                  {activePlan.experimentPlan.baseline ? (
                    <span className={styles.experimentProtocolChip} title={activePlan.experimentPlan.baseline}>
                      Baseline · {shortProtocolLabel(activePlan.experimentPlan.baseline)}
                    </span>
                  ) : null}
                </div>
              </article>
              <div className={styles.experimentChecklist}>
                {activePlan.readinessChecklist.map((item: any) => (
                  <span key={item.item} className={item.status === "pass" ? styles.experimentChecklistPass : styles.experimentChecklistWarn} title={item.note}>
                    {item.status === "pass" ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
                    {item.label}
                  </span>
                ))}
              </div>
            </div>
            {explicitDesignGate ? (
              <div className={styles.experimentBaselineArtifact}>
                <span>{lang === "zh" ? "设计门禁" : "Design gate"}</span>
                <strong>
                  {explicitDesignGate.status === "frozen"
                    ? (lang === "zh" ? `已冻结 v${activeExperimentContract?.revision ?? "-"}` : `Frozen v${activeExperimentContract?.revision ?? "-"}`)
                    : (lang === "zh" ? `迭代草稿 v${activeExperimentContract?.revision ?? "-"} · 待冻结` : `Iteration draft v${activeExperimentContract?.revision ?? "-"} · freeze required`)}
                </strong>
                <small title={explicitDesignGate.sourceProposalId}>
                  {lang === "zh" ? "来源" : "Source"} · {explicitDesignGate.sourceLoopId || explicitDesignGate.sourceProposalId}
                </small>
                {explicitDesignGate.status === "draft" ? (
                  <>
                    {!iterationVariableGovernanceReady ? (
                      <small>
                        {lang === "zh"
                          ? "缺少允许变化路径或固定控制项，需从最新提案重新生成受治理草稿。"
                          : "Allowed change paths or frozen controls are missing. Regenerate from the latest proposal."}
                      </small>
                    ) : null}
                    <VNativeButton type="button" onClick={() => freezeExperimentDesignFromWorkspace(activePlan)} disabled={!canFreezeDesign}>
                      <CheckCircle2 size={13} />
                      {selectedTeamFreezeExperimentDesignPending
                        ? (lang === "zh" ? "冻结中" : "Freezing")
                        : (lang === "zh" ? "冻结设计" : "Freeze design")}
                    </VNativeButton>
                  </>
                ) : null}
              </div>
            ) : null}
            {activeBaselineArtifact ? (
              <div className={styles.experimentBaselineArtifact}>
                <span>{lang === "zh" ? "Active baseline" : "Active baseline"}</span>
                <strong title={activeBaselineArtifact.artifactPath}>{activeBaselineArtifact.artifactPath}</strong>
                <small title={activeBaselineArtifact.reproductionCommand}>{activeBaselineArtifact.reproductionCommand}</small>
              </div>
            ) : (
              <div className={styles.experimentBaselineForm}>
                <label>
                  <span>{lang === "zh" ? "工件路径" : "Artifact path"}</span>
                  <VNativeInput
                    value={experimentBaselineArtifactDraft.artifactPath}
                    onChange={(event) => setExperimentBaselineArtifactDraft((draft) => ({ ...draft, artifactPath: event.target.value }))}
                    placeholder="workspace/experiments/baselines/baseline.json"
                  />
                </label>
                <label>
                  <span>{lang === "zh" ? "复现命令" : "Reproduce"}</span>
                  <VNativeInput
                    value={experimentBaselineArtifactDraft.reproductionCommand}
                    onChange={(event) => setExperimentBaselineArtifactDraft((draft) => ({ ...draft, reproductionCommand: event.target.value }))}
                    placeholder="python experiments/run_baseline.py"
                  />
                </label>
                <label>
                  <span>{lang === "zh" ? "评估命令" : "Evaluate"}</span>
                  <VNativeInput
                    value={experimentBaselineArtifactDraft.evaluationCommand}
                    onChange={(event) => setExperimentBaselineArtifactDraft((draft) => ({ ...draft, evaluationCommand: event.target.value }))}
                    placeholder="python experiments/evaluate.py"
                  />
                </label>
                <label>
                  <span>{lang === "zh" ? "指标快照" : "Metric"}</span>
                  <VNativeInput
                    value={experimentBaselineArtifactDraft.metricValue}
                    onChange={(event) => setExperimentBaselineArtifactDraft((draft) => ({ ...draft, metricValue: event.target.value }))}
                    placeholder={activePlan.experimentPlan.metric || "validation accuracy"}
                  />
                </label>
                <VNativeButton type="button" onClick={() => registerExperimentBaselineArtifactFromWorkspace(activePlan)} disabled={!canRegisterBaselineArtifact}>
                  <Save size={13} />
                  {selectedTeamRegisterExperimentBaselineArtifactPending
                    ? (lang === "zh" ? "登记中" : "Registering")
                    : (lang === "zh" ? "登记基线工件" : "Register baseline")}
                </VNativeButton>
              </div>
            )}
            </>
          ) : null}
          {currentStep === "protocol" && !activePlan ? (
            <div className={styles.experimentLedgerEmpty}>
              <AlertTriangle size={14} />
              <span>{lang === "zh" ? "请先保存并批准假设。" : "Save a plan and approve a hypothesis first."}</span>
            </div>
          ) : null}

          {currentStep === "execute" && activePlan ? (
            <>
            <div className={styles.experimentBaselineArtifact}>
              <span>{lang === "zh" ? "受控试跑" : "Bounded smoke"}</span>
              <strong title={activeSmokeRun?.artifactHash || activeSmokeAdapter?.adapterId || ""}>
                {activeSmokeRun
                  ? `${shortProtocolLabel(String(activeSmokeRun.adapter || ""), 28)} · ${activeSmokeRun.status}`
                  : !designExecutionAllowed
                    ? (lang === "zh" ? "设计尚未冻结" : "Design is not frozen")
                    : shortProtocolLabel(activeSmokeAdapter?.adapterId || "", 36)
                      || (lang === "zh" ? "没有可用的离线执行器" : "No offline Adapter available")}
              </strong>
              <small title={activeSmokeRun ? `${activeSmokeRun.decisionHint} · seed ${activeSmokeRun.seed}` : smokeGateDetail}>
                {activeSmokeRun
                  ? `seed ${activeSmokeRun.seed}`
                  : (lang === "zh" ? "冻结后可试跑" : "Available after freeze")}
              </small>
              <VNativeButton
                type="button"
                onClick={() => runExperimentSmokeFromWorkspace(activePlan, activeSmokeAdapter?.adapterId || "", 42)}
                disabled={!canRunBoundedSmoke}
              >
                <Play size={13} />
                {selectedTeamRunExperimentSmokePending
                  ? (lang === "zh" ? "Smoke 运行中" : "Running smoke")
                  : (lang === "zh" ? "运行受控 Smoke" : "Run bounded smoke")}
              </VNativeButton>
            </div>
            {activeSmokeRun ? (
              <section
                className={styles.experimentSmokeRunEvidence}
                aria-label={lang === "zh" ? "本次受控 Smoke 证据" : "Bounded smoke evidence"}
              >
                <header className={styles.experimentSmokeRunHeader}>
                  <div>
                    <span>{lang === "zh" ? "本次 Smoke 证据" : "Smoke evidence"}</span>
                    <strong>{activeSmokeRun.adapter}</strong>
                  </div>
                  <div className={styles.experimentSmokeMeta}>
                    <VStatusChip tone={smokeStatusTone(activeSmokeRun.status)}>
                      {activeSmokeReviewCopy?.statusLabel ?? activeSmokeRun.status}
                    </VStatusChip>
                    {activeSmokeRun.proxyOnly ? (
                      <VStatusChip tone="warning">
                        {lang === "zh" ? "仅代理验证" : "Proxy only"}
                      </VStatusChip>
                    ) : null}
                  </div>
                </header>
                {activeSmokeMetricEntries.length > 0 ? (
                  <div className={styles.experimentSmokeMetricList}>
                    {activeSmokeMetricEntries.map((entry) => (
                      <VMetricChip key={entry.label} label={entry.label} value={String(entry.value)} />
                    ))}
                  </div>
                ) : null}
                <dl className={styles.experimentSmokeEvidenceGrid}>
                  <div>
                    <dt>Run ID</dt>
                    <dd>{activeSmokeRun.smokeRunId}</dd>
                  </div>
                  <div>
                    <dt>Artifact hash</dt>
                    <dd>{activeSmokeRun.artifactHash}</dd>
                  </div>
                </dl>
                {(activeSmokeRun.boundaries ?? []).length > 0 ? (
                  <div className={styles.experimentSmokeBoundaryList}>
                    {(activeSmokeRun.boundaries ?? []).map((boundary: string) => (
                      <VStatusChip key={boundary} tone="neutral">
                        {smokeBoundaryCopy[boundary]?.[lang] ?? boundary}
                      </VStatusChip>
                    ))}
                  </div>
                ) : null}
                <VNativeButton type="button" onClick={openIterationWorkspace}>
                  <ArrowRight size={13} />
                  {activeSmokeReviewCopy?.actionLabel
                    ?? (lang === "zh" ? "进入执行与迭代" : "Open execution and iteration")}
                </VNativeButton>
              </section>
            ) : null}
            {activeBaselineArtifact ? (
              <>
                {activeSmokeResult ? (
                  <div
                    className={[
                      styles.experimentSmokeResult,
                      activeSmokeResult.status === "passed" ? styles.experimentSmokeResultPass : styles.experimentSmokeResultWarn,
                    ].join(" ")}
                  >
                    <div>
                      <span>{lang === "zh" ? "Active smoke" : "Active smoke"}</span>
                      <strong title={activeSmokeResult.resultPath || activeSmokeResult.logRef || activeSmokeResult.smokeResultId}>
                        {activeSmokeResult.resultPath || activeSmokeResult.logRef || activeSmokeResult.smokeResultId}
                      </strong>
                      <small title={activeSmokeResult.evaluationCommand || activeSmokeResult.recordedAt}>
                        {activeSmokeResult.evaluationCommand || activeSmokeResult.recordedAt || "-"}
                      </small>
                    </div>
                    <div className={styles.experimentSmokeMeta}>
                      <span>{activeSmokeResult.status}</span>
                      <span>{activeSmokeResult.gateDecision}</span>
                      <span>{activeSmokeResult.metricName || activePlan.experimentPlan.metric || "metric"} · {activeSmokeResult.metricValue || "-"}</span>
                      <span>
                        {activePlan.readiness.readyForFullRun
                          ? (lang === "zh" ? "full-run 已解锁" : "full-run ready")
                          : (lang === "zh" ? "full-run 阻塞" : "full-run blocked")}
                      </span>
                    </div>
                  </div>
                ) : null}
                <div className={styles.experimentSmokeForm}>
                  <label>
                    <span>{lang === "zh" ? "Smoke 状态" : "Smoke status"}</span>
                    <VStringSelect
                      ariaLabel={lang === "zh" ? "Smoke 状态" : "Smoke status"}
                      value={experimentSmokeResultDraft.status}
                      onValueChange={(status) =>
                        setExperimentSmokeResultDraft((draft) => ({
                          ...draft,
                          status: status as ExperimentSmokeResultStatus,
                        }))}
                      options={EXPERIMENT_SMOKE_RESULT_STATUSES.map((status: any) => ({
                        value: status,
                        label:
                          status === "needs_review"
                            ? (lang === "zh" ? "需复核" : "needs review")
                            : status === "passed"
                              ? (lang === "zh" ? "通过" : "passed")
                              : (lang === "zh" ? "失败" : "failed"),
                      }))}
                    />
                  </label>
                  <label>
                    <span>{lang === "zh" ? "Smoke 指标" : "Smoke metric"}</span>
                    <VNativeInput
                      value={experimentSmokeResultDraft.metricValue}
                      onChange={(event) => setExperimentSmokeResultDraft((draft) => ({ ...draft, metricValue: event.target.value }))}
                      placeholder={activePlan.experimentPlan.metric || "0.00"}
                    />
                  </label>
                  <label>
                    <span>{lang === "zh" ? "Baseline 指标" : "Baseline metric"}</span>
                    <VNativeInput
                      value={experimentSmokeResultDraft.baselineMetricValue}
                      onChange={(event) => setExperimentSmokeResultDraft((draft) => ({ ...draft, baselineMetricValue: event.target.value }))}
                      placeholder={activeBaselineArtifact.metricValue || "-"}
                    />
                  </label>
                  <label>
                    <span>Delta</span>
                    <VNativeInput
                      value={experimentSmokeResultDraft.delta}
                      onChange={(event) => setExperimentSmokeResultDraft((draft) => ({ ...draft, delta: event.target.value }))}
                      placeholder="+0.00"
                    />
                  </label>
                  <label>
                    <span>{lang === "zh" ? "结果路径" : "Result path"}</span>
                    <VNativeInput
                      value={experimentSmokeResultDraft.resultPath}
                      onChange={(event) => setExperimentSmokeResultDraft((draft) => ({ ...draft, resultPath: event.target.value }))}
                      placeholder="workspace/experiments/smoke/result.json"
                    />
                  </label>
                  <label>
                    <span>{lang === "zh" ? "日志引用" : "Log ref"}</span>
                    <VNativeInput
                      value={experimentSmokeResultDraft.logRef}
                      onChange={(event) => setExperimentSmokeResultDraft((draft) => ({ ...draft, logRef: event.target.value }))}
                      placeholder="logs/experiments/smoke.log"
                    />
                  </label>
                  <VNativeButton type="button" onClick={() => registerExperimentSmokeResultFromWorkspace(activePlan)} disabled={!canRegisterSmokeResult}>
                    <Save size={13} />
                    {selectedTeamRegisterExperimentSmokeResultPending
                      ? (lang === "zh" ? "登记中" : "Registering")
                      : activeSmokeResult
                        ? (lang === "zh" ? "更新 smoke 结果" : "Update smoke result")
                        : (lang === "zh" ? "登记 smoke 结果" : "Register smoke")}
                  </VNativeButton>
                  <label className={styles.experimentSmokeWide}>
                    <span>{lang === "zh" ? "评估命令" : "Evaluate"}</span>
                    <VNativeInput
                      value={experimentSmokeResultDraft.evaluationCommand}
                      onChange={(event) => setExperimentSmokeResultDraft((draft) => ({ ...draft, evaluationCommand: event.target.value }))}
                      placeholder={activeBaselineArtifact.evaluationCommand || "python experiments/evaluate_smoke.py"}
                    />
                  </label>
                  <label className={styles.experimentSmokeWide}>
                    <span>{lang === "zh" ? "备注" : "Notes"}</span>
                    <VNativeInput
                      value={experimentSmokeResultDraft.notes}
                      onChange={(event) => setExperimentSmokeResultDraft((draft) => ({ ...draft, notes: event.target.value }))}
                      placeholder={lang === "zh" ? "只登记证据，不触发训练" : "Evidence only; no training execution"}
                    />
                  </label>
                </div>
                {activePlan.readiness.readyForFullRun ? (
                  <>
                    {activeFullRunResult ? (
                      <div
                        className={[
                          styles.experimentSmokeResult,
                          String(activeFullRunResult.status || "").toLowerCase() === "passed"
                            ? styles.experimentSmokeResultPass
                            : styles.experimentSmokeResultWarn,
                        ].join(" ")}
                      >
                        <div>
                          <span>{lang === "zh" ? "Active full-run" : "Active full-run"}</span>
                          <strong title={activeFullRunResult.resultPath || activeFullRunResult.logRef || activeFullRunResult.fullRunResultId}>
                            {activeFullRunResult.resultPath || activeFullRunResult.logRef || activeFullRunResult.fullRunResultId}
                          </strong>
                          <small title={activeFullRunResult.configPath || activeFullRunResult.recordedAt}>
                            {activeFullRunResult.configPath || activeFullRunResult.recordedAt || "-"}
                          </small>
                        </div>
                        <div className={styles.experimentSmokeMeta}>
                          <span>{activeFullRunResult.status}</span>
                          <span>{activeFullRunResult.gateDecision}</span>
                          <span>{activeFullRunResult.metricName || activePlan.experimentPlan.metric || "metric"} · {activeFullRunResult.metricValue || "-"}</span>
                          <span>
                            {activePlan.readiness.readyForKnowledgeIngestion
                              ? (lang === "zh" ? "可通知知识库管理员" : "knowledge review ready")
                              : (lang === "zh" ? "知识入库阻塞" : "knowledge blocked")}
                          </span>
                        </div>
                      </div>
                    ) : null}
                    <div className={styles.experimentSmokeForm}>
                      <label>
                        <span>{lang === "zh" ? "Full-run 状态" : "Full-run status"}</span>
                        <VStringSelect
                          ariaLabel={lang === "zh" ? "Full-run 状态" : "Full-run status"}
                          value={experimentFullRunResultDraft.status}
                          onValueChange={(status) =>
                            setExperimentFullRunResultDraft((draft) => ({
                              ...draft,
                              status: status as ExperimentFullRunResultStatus,
                            }))}
                          options={EXPERIMENT_FULL_RUN_RESULT_STATUSES.map((status: any) => ({
                            value: status,
                            label:
                              status === "needs_review"
                                ? (lang === "zh" ? "需复核" : "needs review")
                                : status === "passed"
                                  ? (lang === "zh" ? "通过" : "passed")
                                  : (lang === "zh" ? "失败" : "failed"),
                          }))}
                        />
                      </label>
                      <label>
                        <span>{lang === "zh" ? "Full-run 指标" : "Full-run metric"}</span>
                        <VNativeInput
                          value={experimentFullRunResultDraft.metricValue}
                          onChange={(event) => setExperimentFullRunResultDraft((draft) => ({ ...draft, metricValue: event.target.value }))}
                          placeholder={activePlan.experimentPlan.metric || "0.00"}
                        />
                      </label>
                      <label>
                        <span>{lang === "zh" ? "Baseline 指标" : "Baseline metric"}</span>
                        <VNativeInput
                          value={experimentFullRunResultDraft.baselineMetricValue}
                          onChange={(event) => setExperimentFullRunResultDraft((draft) => ({ ...draft, baselineMetricValue: event.target.value }))}
                          placeholder={activeBaselineArtifact.metricValue || activeSmokeResult?.baselineMetricValue || "-"}
                        />
                      </label>
                      <label>
                        <span>{lang === "zh" ? "Smoke 指标" : "Smoke metric"}</span>
                        <VNativeInput
                          value={experimentFullRunResultDraft.smokeMetricValue}
                          onChange={(event) => setExperimentFullRunResultDraft((draft) => ({ ...draft, smokeMetricValue: event.target.value }))}
                          placeholder={activeSmokeResult?.metricValue || "-"}
                        />
                      </label>
                      <label>
                        <span>Delta</span>
                        <VNativeInput
                          value={experimentFullRunResultDraft.delta}
                          onChange={(event) => setExperimentFullRunResultDraft((draft) => ({ ...draft, delta: event.target.value }))}
                          placeholder="+0.00"
                        />
                      </label>
                      <label>
                        <span>{lang === "zh" ? "结果路径" : "Result path"}</span>
                        <VNativeInput
                          value={experimentFullRunResultDraft.resultPath}
                          onChange={(event) => setExperimentFullRunResultDraft((draft) => ({ ...draft, resultPath: event.target.value }))}
                          placeholder="workspace/experiments/full_run/result.json"
                        />
                      </label>
                      <label>
                        <span>{lang === "zh" ? "日志引用" : "Log ref"}</span>
                        <VNativeInput
                          value={experimentFullRunResultDraft.logRef}
                          onChange={(event) => setExperimentFullRunResultDraft((draft) => ({ ...draft, logRef: event.target.value }))}
                          placeholder="logs/experiments/full_run.log"
                        />
                      </label>
                      <VNativeButton type="button" onClick={() => registerExperimentFullRunResultFromWorkspace(activePlan)} disabled={!canRegisterFullRunResult}>
                        <Save size={13} />
                        {selectedTeamRegisterExperimentFullRunResultPending
                          ? (lang === "zh" ? "登记中" : "Registering")
                          : activeFullRunResult
                            ? (lang === "zh" ? "更新 full-run" : "Update full-run")
                            : (lang === "zh" ? "登记 full-run" : "Register full-run")}
                      </VNativeButton>
                      <label className={styles.experimentSmokeWide}>
                        <span>{lang === "zh" ? "配置路径" : "Config path"}</span>
                        <VNativeInput
                          value={experimentFullRunResultDraft.configPath}
                          onChange={(event) => setExperimentFullRunResultDraft((draft) => ({ ...draft, configPath: event.target.value }))}
                          placeholder="workspace/experiments/full_run/config.json"
                        />
                      </label>
                      <label className={styles.experimentSmokeWide}>
                        <span>{lang === "zh" ? "复现命令" : "Reproduce"}</span>
                        <VNativeInput
                          value={experimentFullRunResultDraft.reproductionCommand}
                          onChange={(event) => setExperimentFullRunResultDraft((draft) => ({ ...draft, reproductionCommand: event.target.value }))}
                          placeholder={activeBaselineArtifact.reproductionCommand || "python experiments/run_full.py"}
                        />
                      </label>
                      <label className={styles.experimentSmokeWide}>
                        <span>{lang === "zh" ? "评估命令" : "Evaluate"}</span>
                        <VNativeInput
                          value={experimentFullRunResultDraft.evaluationCommand}
                          onChange={(event) => setExperimentFullRunResultDraft((draft) => ({ ...draft, evaluationCommand: event.target.value }))}
                          placeholder={activeSmokeResult?.evaluationCommand || activeBaselineArtifact.evaluationCommand || "python experiments/evaluate_full.py"}
                        />
                      </label>
                      <label className={styles.experimentSmokeWide}>
                        <span>{lang === "zh" ? "备注" : "Notes"}</span>
                        <VNativeInput
                          value={experimentFullRunResultDraft.notes}
                          onChange={(event) => setExperimentFullRunResultDraft((draft) => ({ ...draft, notes: event.target.value }))}
                          placeholder={lang === "zh" ? "只登记外部 full-run 证据" : "External full-run evidence only"}
                        />
                      </label>
                    </div>
                  </>
                ) : null}
                {activeFullRunResult && String(activeFullRunResult.status || "").toLowerCase() === "passed" ? (
                  <div className={styles.experimentKnowledgePanel}>
                    <div>
                      <strong>{lang === "zh" ? "实验结果入库请求" : "Experiment result ingestion"}</strong>
                      <span>
                        {knowledgeIngestion
                          ? `${knowledgeIngestion.status} · ${knowledgeIngestion.experimentResultPack?.packId || knowledgeIngestion.knowledgeBaseId}`
                          : (lang === "zh" ? "生成结果包并通知知识库管理员；正式知识仍需复核。" : "Create a result pack and notify the knowledge base admin.")}
                      </span>
                    </div>
                    {!knowledgeIngestion ? (
                      <div className={styles.experimentKnowledgeForm}>
                        <label>
                          <span>{lang === "zh" ? "知识库" : "Knowledge base"}</span>
                          <VNativeInput
                            value={experimentKnowledgeIngestionDraft.knowledgeBaseId}
                            onChange={(event) => setExperimentKnowledgeIngestionDraft((draft) => ({ ...draft, knowledgeBaseId: event.target.value }))}
                            placeholder={`${selectedTeam?.teamId || "research-team"}-challenge-cup-experiments`}
                          />
                        </label>
                        <label>
                          <span>{lang === "zh" ? "知识域" : "Domain"}</span>
                          <VNativeInput
                            value={experimentKnowledgeIngestionDraft.targetDomain}
                            onChange={(event) => setExperimentKnowledgeIngestionDraft((draft) => ({ ...draft, targetDomain: event.target.value }))}
                            placeholder={lang === "zh" ? "挑战杯实验结果" : "Challenge Cup experiment results"}
                          />
                        </label>
                        <label>
                          <span>{lang === "zh" ? "结果标题" : "Title"}</span>
                          <VNativeInput
                            value={experimentKnowledgeIngestionDraft.title}
                            onChange={(event) => setExperimentKnowledgeIngestionDraft((draft) => ({ ...draft, title: event.target.value }))}
                            placeholder={activePlan.title}
                          />
                        </label>
                        <label>
                          <span>{lang === "zh" ? "摘要" : "Summary"}</span>
                          <VNativeInput
                            value={experimentKnowledgeIngestionDraft.summary}
                            onChange={(event) => setExperimentKnowledgeIngestionDraft((draft) => ({ ...draft, summary: event.target.value }))}
                            placeholder={`${activeFullRunResult.metricName || activePlan.experimentPlan.metric || "metric"} = ${activeFullRunResult.metricValue || "-"}`}
                          />
                        </label>
                        <label className={styles.experimentKnowledgeWide}>
                          <span>{lang === "zh" ? "备注" : "Notes"}</span>
                          <VNativeInput
                            value={experimentKnowledgeIngestionDraft.notes}
                            onChange={(event) => setExperimentKnowledgeIngestionDraft((draft) => ({ ...draft, notes: event.target.value }))}
                            placeholder={lang === "zh" ? "原始日志只保留引用，正式知识由 Steward 复核" : "Raw logs stay referenced; Steward reviews curated knowledge"}
                          />
                        </label>
                        <label className={styles.experimentKnowledgeToggle}>
                          <VNativeInput
                            type="checkbox"
                            checked={experimentKnowledgeIngestionDraft.wakeStewardAgent}
                            onChange={(event) => setExperimentKnowledgeIngestionDraft((draft) => ({ ...draft, wakeStewardAgent: event.target.checked }))}
                          />
                          <span>{lang === "zh" ? "立即唤醒知识库管理员" : "Wake knowledge base admin"}</span>
                        </label>
                        <VNativeButton type="button" onClick={() => requestExperimentKnowledgeIngestionFromWorkspace(activePlan)} disabled={!canRequestKnowledgeIngestion}>
                          <Send size={13} />
                          {selectedTeamRequestExperimentKnowledgeIngestionPending
                            ? (lang === "zh" ? "通知中" : "Notifying")
                            : (lang === "zh" ? "通知知识库管理员" : "Notify admin")}
                        </VNativeButton>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : null}
            <details className="min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] p-2">
              <summary className="cursor-pointer [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)]">
                {lang === "zh" ? "更多（循环与阻塞）" : "More (loop & blockers)"}
              </summary>
              <div className="mt-2 grid gap-2">
                {renderResearchLoopPanel(activePlan, "experiment")}
                <div className={styles.experimentEvidenceGrid}>
                  <section>
                    <strong>{lang === "zh" ? "阻塞项" : "Blockers"}</strong>
                    <div className={styles.experimentGapList}>
                      {(statusPayload?.gaps ?? []).map((gap: any) => (
                        <span key={gap.code} title={gap.message}>
                          <AlertTriangle size={12} />
                          {gap.message}
                        </span>
                      ))}
                      {statusPayload && statusPayload.gaps.length === 0 ? (
                        <span>
                          <CheckCircle2 size={12} />
                          {lang === "zh" ? "无阻塞" : "No blockers"}
                        </span>
                      ) : null}
                    </div>
                  </section>
                </div>
              </div>
            </details>
            </>
          ) : null}
          {currentStep === "execute" && !activePlan ? (
            <div className={styles.experimentLedgerEmpty}>
              <AlertTriangle size={14} />
              <span>{lang === "zh" ? "完成前三步后再试跑。" : "Finish the earlier steps first."}</span>
            </div>
          ) : null}
        </div>

        {selectedTeamCreateExperimentPlanError ? <div className={styles.workflowError}>{selectedTeamCreateExperimentPlanError.message}</div> : null}
        {selectedTeamFreezeExperimentDesignError ? <div className={styles.workflowError}>{selectedTeamFreezeExperimentDesignError.message}</div> : null}
        {selectedTeamRegisterExperimentBaselineArtifactError ? <div className={styles.workflowError}>{selectedTeamRegisterExperimentBaselineArtifactError.message}</div> : null}
        {selectedTeamRunExperimentSmokeError ? <div className={styles.workflowError}>{selectedTeamRunExperimentSmokeError.message}</div> : null}
        {selectedTeamRegisterExperimentSmokeResultError ? <div className={styles.workflowError}>{selectedTeamRegisterExperimentSmokeResultError.message}</div> : null}
        {selectedTeamRegisterExperimentFullRunResultError ? <div className={styles.workflowError}>{selectedTeamRegisterExperimentFullRunResultError.message}</div> : null}
        {selectedTeamRequestExperimentKnowledgeIngestionError ? <div className={styles.workflowError}>{selectedTeamRequestExperimentKnowledgeIngestionError.message}</div> : null}
      </section>
    );

}
