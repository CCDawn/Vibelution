/**
 * Experiment planning ledger (method panel, baseline/smoke/full-run, knowledge ingestion).
 * Wave 8J: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Play, Save, Send } from "lucide-react";

import type { ExperimentMethodId, Team } from "../api/types";
import { VNativeButton, VNativeInput, VNativeSelect, VNativeTextarea } from "../components/vui";
import {
  EXPERIMENT_FULL_RUN_RESULT_STATUSES,
  EXPERIMENT_SMOKE_RESULT_STATUSES,
  type ExperimentBaselineArtifactDraft,
  type ExperimentFullRunResultDraft,
  type ExperimentFullRunResultStatus,
  type ExperimentKnowledgeIngestionDraft,
  type ExperimentPlanRecord,
  type ExperimentPlanningStatusPayload,
  type ExperimentSmokeResultDraft,
  type ExperimentSmokeResultStatus,
} from "./teams/experimentLoopModel";
import { TeamExperimentMethodPanel, type ExperimentPlanMethodRequest } from "./TeamExperimentMethodPanel";
import experimentStyles from "./TeamsRoute.experiment.styles";
import researchStyles from "./TeamsRoute.research.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...experimentStyles, ...researchStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

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
  freezeExperimentDesignFromWorkspace: (plan: ExperimentPlanRecord) => void;
  registerExperimentBaselineArtifactFromWorkspace: (plan: ExperimentPlanRecord) => void;
  runExperimentSmokeFromWorkspace: (plan: ExperimentPlanRecord, adapter: string, seed: number) => void;
  registerExperimentSmokeResultFromWorkspace: (plan: ExperimentPlanRecord) => void;
  registerExperimentFullRunResultFromWorkspace: (plan: ExperimentPlanRecord) => void;
  requestExperimentKnowledgeIngestionFromWorkspace: (plan: ExperimentPlanRecord) => void;
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
    freezeExperimentDesignFromWorkspace,
    registerExperimentBaselineArtifactFromWorkspace,
    runExperimentSmokeFromWorkspace,
    registerExperimentSmokeResultFromWorkspace,
    registerExperimentFullRunResultFromWorkspace,
    requestExperimentKnowledgeIngestionFromWorkspace,
    renderResearchLoopPanel,
  } = props;


    const latestKnowledgeIngestionMutationPayload = selectedTeamRequestExperimentKnowledgeIngestionResult;
    const latestFullRunMutationPayload = selectedTeamRegisterExperimentFullRunResultResult;
    const latestSmokeMutationPayload = selectedTeamRegisterExperimentSmokeResultResult;
    const latestBaselineMutationPayload = selectedTeamRegisterExperimentBaselineArtifactResult;
    const latestMutationPayload = selectedTeamCreateExperimentPlanResult;
    const latestFreezePayload = selectedTeamFreezeExperimentDesignResult;
    const statusPayload =
      latestFreezePayload?.experimentStatus
      ?? latestKnowledgeIngestionMutationPayload?.status
      ?? latestFullRunMutationPayload?.status
      ?? latestSmokeMutationPayload?.status
      ?? latestBaselineMutationPayload?.status
      ?? latestMutationPayload?.status
      ?? experimentPlanningStatus;
    const activePlan =
      latestFreezePayload?.plan
      ?? latestKnowledgeIngestionMutationPayload?.plan
      ?? latestFullRunMutationPayload?.plan
      ?? latestSmokeMutationPayload?.plan
      ?? latestBaselineMutationPayload?.plan
      ?? latestMutationPayload?.plan
      ?? statusPayload?.activePlan
      ?? null;
    const activeBaselineArtifact = activePlan?.baselineSelection.activeBaselineArtifact ?? null;
    const activeSmokeRun = selectedTeamRunExperimentSmokeResult?.smokeRun ?? activePlan?.activeSmokeRun ?? null;
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
    const requestedSmokeAdapterId = activeExperimentContract?.adapterSelection?.requestedAdapterId ?? "";
    const activeSmokeAdapter =
      boundedSmokeAdapters.find((adapter: any) => adapter.adapterId === requestedSmokeAdapterId)
      ?? boundedSmokeAdapters[0]
      ?? null;
    const hypotheses = statusPayload?.readyHypothesisCandidates?.length
      ? statusPayload.readyHypothesisCandidates
      : statusPayload?.hypothesisCandidates ?? [];
    const canDraftPlan = Boolean(selectedTeam?.teamId && statusPayload?.latestExperimentRound && !selectedTeamCreateExperimentPlanPending);
    const explicitDesignGate = activePlan?.designGate;
    const designExecutionAllowed = !explicitDesignGate || explicitDesignGate.status === "frozen";
    const canFreezeDesign = Boolean(
      selectedTeam?.teamId
      && activePlan
      && explicitDesignGate?.status === "draft"
      && activePlan.contractValidation?.valid
      && activePlan.readiness.readyForPlanReview
      && !selectedTeamFreezeExperimentDesignPending,
    );
    const canRegisterBaselineArtifact = Boolean(
      selectedTeam?.teamId
      && activePlan
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
      && activePlan.readiness.readyForSmoke
      && activeSmokeAdapter?.adapterId
      && !selectedTeamRunExperimentSmokePending,
    );
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
    const summary = statusPayload?.summary;
    return (
      <section className={styles.experimentLedgerPanel} aria-label={lang === "zh" ? "实验计划账本" : "Experiment planning ledger"}>
        <div className={styles.experimentLedgerHeader}>
          <div>
            <strong>{lang === "zh" ? "实验计划账本" : "Experiment ledger"}</strong>
            <span>
              {statusPayload?.readiness.reason
                || (experimentPlanningStatusQuery.isFetching
                  ? (lang === "zh" ? "读取实验账本中" : "Loading experiment ledger")
                  : (lang === "zh" ? "等待实验阶段状态" : "Waiting for experiment status"))}
            </span>
          </div>
          <span>{activePlan ? `${lang === "zh" ? "当前计划" : "Active plan"} · ${activePlan.planId}` : (lang === "zh" ? "尚未保存实验配置" : "Experiment setup not saved")}</span>
        </div>
        <div className={styles.experimentLedgerStats}>
          <span>
            {lang === "zh" ? "计划" : "Plans"}
            <strong>{summary?.planCount ?? 0}</strong>
          </span>
          <span>
            {lang === "zh" ? "候选假设" : "Hypotheses"}
            <strong>{summary?.hypothesisCandidateCount ?? 0}</strong>
          </span>
          <span>
            {lang === "zh" ? "可规划" : "Ready"}
            <strong>{summary?.readyHypothesisCandidateCount ?? 0}</strong>
          </span>
          <span>
            {lang === "zh" ? "缺口" : "Gaps"}
            <strong>{summary?.gapCount ?? 0}</strong>
          </span>
        </div>
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
          errorMessage={
            experimentMethodCatalogQuery.error instanceof Error
              ? experimentMethodCatalogQuery.error.message
              : selectedTeamCreateExperimentPlanError?.message
          }
          submitting={selectedTeamCreateExperimentPlanPending}
          canCreatePlan={canDraftPlan}
          onSubmit={createExperimentPlanFromWorkspace}
        />
        {activePlan ? (
          <>
            <div className={styles.experimentPlanGrid}>
              <article className={styles.experimentPlanSummary}>
                <div>
                  <span>{lang === "zh" ? "当前草稿" : "Active draft"}</span>
                  <strong>{activePlan.title}</strong>
                </div>
                <p>{activePlan.goal || activePlan.topic || (lang === "zh" ? "实验目标待补齐" : "Experiment goal pending")}</p>
                <div className={styles.experimentPlanFields}>
                  {activeExperimentContract ? <span>{lang === "zh" ? "科研闭环" : "Research loop"} · {(lang === "zh" ? activeResearchModeDescriptor?.labelZh : activeResearchModeDescriptor?.labelEn) || activeExperimentContract.researchMode}</span> : null}
                  {activeExperimentContract ? <span>{lang === "zh" ? "实验目的" : "Purpose"} · {(lang === "zh" ? activePurposeDescriptor?.labelZh : activePurposeDescriptor?.labelEn) || activeExperimentContract.purpose.primaryPurpose}</span> : null}
                  {activeExperimentContract ? <span>{lang === "zh" ? "实验方法" : "Method"} · {(lang === "zh" ? activeMethodDescriptor?.labelZh : activeMethodDescriptor?.labelEn) || activeExperimentContract.experimentMethod}</span> : null}
                  {activePlan.experimentPlan.dataset ? <span title={activePlan.experimentPlan.dataset}>{lang === "zh" ? "数据" : "Data"} · {activePlan.experimentPlan.dataset}</span> : null}
                  {activePlan.experimentPlan.metric ? <span title={activePlan.experimentPlan.metric}>{lang === "zh" ? "指标" : "Metric"} · {activePlan.experimentPlan.metric}</span> : null}
                  {activePlan.experimentPlan.baseline ? <span title={activePlan.experimentPlan.baseline}>Baseline · {activePlan.experimentPlan.baseline}</span> : null}
                  {activePlan.experimentPlan.smokePlan ? <span title={activePlan.experimentPlan.smokePlan}>Smoke · {activePlan.experimentPlan.smokePlan}</span> : null}
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
                  <VNativeButton type="button" onClick={() => freezeExperimentDesignFromWorkspace(activePlan)} disabled={!canFreezeDesign}>
                    <CheckCircle2 size={13} />
                    {selectedTeamFreezeExperimentDesignPending
                      ? (lang === "zh" ? "冻结中" : "Freezing")
                      : (lang === "zh" ? "冻结设计" : "Freeze design")}
                  </VNativeButton>
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
            {activeBaselineArtifact ? (
              <>
                <div className={styles.experimentBaselineArtifact}>
                  <span>{lang === "zh" ? "受控 Smoke" : "Bounded smoke"}</span>
                  <strong title={activeSmokeRun?.artifactHash || activeSmokeAdapter?.adapterId || ""}>
                    {activeSmokeRun
                      ? `${activeSmokeRun.adapter} · ${activeSmokeRun.status}`
                      : activeSmokeAdapter?.adapterId || (lang === "zh" ? "没有可用的离线执行器" : "No offline Adapter available")}
                  </strong>
                  <small>
                    {activeSmokeRun
                      ? `${activeSmokeRun.decisionHint} · seed ${activeSmokeRun.seed}`
                      : (lang === "zh"
                        ? "仅运行后端白名单离线 Smoke；不会启动 full run，也不会生成正式科学结论。"
                        : "Runs only the backend allowlisted offline smoke; no full run or formal scientific claim.")}
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
                    <VNativeSelect
                      value={experimentSmokeResultDraft.status}
                      onChange={(event) =>
                        setExperimentSmokeResultDraft((draft) => ({
                          ...draft,
                          status: event.target.value as ExperimentSmokeResultStatus,
                        }))}
                    >
                      {EXPERIMENT_SMOKE_RESULT_STATUSES.map((status: any) => (
                        <option key={status} value={status}>
                          {status === "needs_review"
                            ? (lang === "zh" ? "需复核" : "needs review")
                            : status === "passed"
                              ? (lang === "zh" ? "通过" : "passed")
                              : (lang === "zh" ? "失败" : "failed")}
                        </option>
                      ))}
                    </VNativeSelect>
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
                        <VNativeSelect
                          value={experimentFullRunResultDraft.status}
                          onChange={(event) =>
                            setExperimentFullRunResultDraft((draft) => ({
                              ...draft,
                              status: event.target.value as ExperimentFullRunResultStatus,
                            }))}
                        >
                          {EXPERIMENT_FULL_RUN_RESULT_STATUSES.map((status: any) => (
                            <option key={status} value={status}>
                              {status === "needs_review"
                                ? (lang === "zh" ? "需复核" : "needs review")
                                : status === "passed"
                                  ? (lang === "zh" ? "通过" : "passed")
                                  : (lang === "zh" ? "失败" : "failed")}
                            </option>
                          ))}
                        </VNativeSelect>
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
          </>
        ) : (
          <div className={styles.experimentLedgerEmpty}>
            <AlertTriangle size={14} />
            <span>{lang === "zh" ? "还没有实验计划草稿，先启动实验阶段并生成计划。" : "No experiment plan draft yet. Start the stage and draft a plan."}</span>
          </div>
        )}
        {renderResearchLoopPanel(activePlan, "experiment")}
        <div className={styles.experimentEvidenceGrid}>
          <section>
            <strong>{lang === "zh" ? "候选算法假设" : "Algorithm hypotheses"}</strong>
            <div className={styles.experimentHypothesisList}>
              {hypotheses.slice(0, 4).map((candidate: any) => (
                <article key={candidate.candidateId}>
                  <div>
                    <span>{candidate.valid ? (lang === "zh" ? "可用" : "ready") : (lang === "zh" ? "需修订" : "rework")}</span>
                    <strong>{candidate.title || candidate.candidateId}</strong>
                  </div>
                  <p>{candidate.hypothesis || candidate.summary || "-"}</p>
                  <small>
                    {candidate.missingExperimentPlanFields.length
                      ? `${lang === "zh" ? "缺" : "missing"} ${candidate.missingExperimentPlanFields.join(", ")}`
                      : `${candidate.experimentPlan.dataset || "-"} / ${candidate.experimentPlan.metric || "-"}`}
                  </small>
                </article>
              ))}
              {hypotheses.length === 0 ? <span>{lang === "zh" ? "暂无可用假设候选" : "No hypothesis candidates yet"}</span> : null}
            </div>
          </section>
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
                  {lang === "zh" ? "计划审查入口已就绪" : "Plan review is ready"}
                </span>
              ) : null}
            </div>
          </section>
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
