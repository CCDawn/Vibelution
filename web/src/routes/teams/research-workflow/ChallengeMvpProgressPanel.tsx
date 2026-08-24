/**
 * Program v2 and question-result progress inside the research workflow canvas.
 *
 * The Program v2 / question sections are read-only backend projections. The DEV
 * control section is team-scoped fixture UI shown on Launcher workbench as well
 * as Vite dev: readiness gates, dev-1/dev-5 fixture checkpoints and the legal
 * next action come from the DEV controls snapshot. Mouse actions are strictly gated by the persisted nextLegalAction
 * and mutation pending state; repair states only surface a blocking hint and
 * never advance to the next stage. No real experiment, Qwen, CUDA/GPU, DANDI,
 * network collection or formal submission is ever started.
 *
 * The question-status and experiment-planning queries are separate and share
 * the canonical keys (queryKeys.challengeQuestionRunStatus /
 * experimentPlanningStatusQueryKey) so they dedupe with the other panels and
 * degrade independently from the DEV controls: while either is pending or
 * failing the DEV snapshot section stays fully visible and operable. After a
 * mutation, actions stay pending/disabled until the snapshot refetch completes
 * so a delayed refetch cannot trigger a duplicate POST.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getChallengeQuestionRunStatus } from "../../../api/challengeQuestionRuns";
import { queryKeys } from "../../../api/queryKeys";
import {
  fetchChallengeCupDevControlSnapshot,
  fetchExperimentPlanningStatus,
  runChallengeCupDevBatch,
  runChallengeCupDevReadiness,
  fetchChallengeCupTokenUsage,
} from "../../../api/teamExperiment";
import type {
  ChallengeCupDevBatchProjection,
  ChallengeCupDevReadinessProjection,
} from "../../../api/types/challengeCup";
import {
  VButton,
  VEmptyState,
  VStateSurface,
  VStatusChip,
  VSurface,
  type VStatusTone,
} from "../../../components/vui";
import type { ExperimentPlanningStatusPayload } from "../experimentLoopModel";
import { experimentPlanningStatusQueryKey } from "../experimentLoopModel";
import { ChallengeCatalogOverview } from "../challenge-cup/ChallengeCatalogOverview";
import { ChallengeTokenUsageStrip } from "../challenge-cup/ChallengeTokenUsageStrip";
import { isTokenUsageOverview } from "../challenge-cup/challengeTokenUsageModel";
import { ChallengeSubmissionReadinessPanel } from "./ChallengeSubmissionReadinessPanel";
import { ChallengeCatalogReadinessPanel } from "./ChallengeCatalogReadinessPanel";
import { useShellI18n } from "../../../i18n/useShellI18n";
import styles from "./ChallengeMvpProgressPanel.styles";
import challengeMvpProgressPanelContract from "./ChallengeMvpProgressPanel.contract.json";

const panelContract = challengeMvpProgressPanelContract;
const devActions = panelContract.devControls.actions;
const devPlanIds = panelContract.devControls.plans;
const devMarkers = panelContract.devControls.markers;

export type ChallengeMvpProgressPanelProps = {
  teamId: string;
  lang?: "zh" | "en";
  onOpenQuestion: (questionId: string) => void;
  /** Dev-phase sessions may start expanded; product default stays collapsed. */
  defaultDevControlsOpen?: boolean;
  /** Explicit test/dev capability; production defaults to the build DEV flag. */
  devControlsEnabled?: boolean;
};

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason || "unavailable");
}

function readinessLabel(
  zh: boolean,
  report: ChallengeCupDevReadinessProjection | null,
  running: boolean,
): string {
  if (running) return zh ? "运行中" : "Running";
  if (!report) return zh ? "未运行" : "Unrun";
  if (report.status === "READY") return zh ? "就绪" : "Ready";
  return zh ? `失败 ${report.status || ""}` : `Failed ${report.status || ""}`;
}

function batchLabel(
  zh: boolean,
  batch: ChallengeCupDevBatchProjection | undefined,
  running: boolean,
): string {
  if (running) return zh ? "运行中" : "Running";
  if (!batch) return zh ? "未运行" : "Unrun";
  if (batch.failedCount > 0 || batch.blockedCount > 0) return zh ? "失败/阻塞" : "Failed/Blocked";
  if (batch.pendingCount > 0) return zh ? "暂停可恢复" : "Paused/Resumable";
  return zh ? "成功" : "Succeeded";
}

function batchTone(
  batch: ChallengeCupDevBatchProjection | undefined,
  running: boolean,
): VStatusTone {
  if (running) return "accent";
  if (!batch) return "neutral";
  if (batch.failedCount > 0 || batch.blockedCount > 0) return "danger";
  if (batch.pendingCount > 0) return "warning";
  return "success";
}

function actionLabel(zh: boolean, action: string): string {
  const labels: Record<string, string> = {
    [devActions.runReadiness]: zh ? "运行 DEV readiness" : "Run DEV readiness",
    [devActions.runDev1]: zh ? "运行 dev-1 fixture" : "Run dev-1 fixture",
    [devActions.runDev5]: zh ? "开始处理首批题目" : "Process the first question batch",
    [devActions.resumeDev5]: zh ? "继续处理剩余题目" : "Continue with remaining questions",
    [devActions.repairReadiness]: zh ? "修复失败的平台门禁" : "Repair failed platform gates",
    [devActions.repairDev1]: zh ? "修复 dev-1 fixture" : "Repair dev-1 fixture",
    [devActions.repairDev5]: zh ? "修复 dev-5 fixture" : "Repair dev-5 fixture",
    [devActions.researchAuthorizationRequired]: zh
      ? "需要科研负责人授权"
      : "Research-owner authorization required",
  };
  return labels[action] ?? action;
}

export function ChallengeMvpProgressPanel({
  teamId,
  lang: langProp,
  onOpenQuestion,
  defaultDevControlsOpen = false,
  devControlsEnabled: devControlsEnabledProp,
}: ChallengeMvpProgressPanelProps) {
  // The inspector mount point cannot thread lang yet (claimed by another task);
  // self-serve the shell language and let an explicit prop win.
  const { lang: shellLang } = useShellI18n();
  const lang = langProp ?? shellLang;
  const zh = lang === "zh";
  const devControlsEnabled = devControlsEnabledProp ?? import.meta.env.DEV;
  // Canonical keys: the question run status and the experiment planning status
  // are shared with the other team panels, so React Query dedupes the requests
  // and mutation invalidations reach this panel.
  const questionStatusQuery = useQuery({
    queryKey: queryKeys.challengeQuestionRunStatus(teamId),
    queryFn: () => getChallengeQuestionRunStatus(teamId),
    enabled: Boolean(teamId.trim()),
    staleTime: 30_000,
  });
  const experimentStatusQuery = useQuery({
    queryKey: experimentPlanningStatusQueryKey(teamId),
    queryFn: () => fetchExperimentPlanningStatus<ExperimentPlanningStatusPayload>(teamId),
    enabled: Boolean(teamId.trim()),
    staleTime: 30_000,
  });
  const devControlsKey = queryKeys[
    panelContract.devControls.snapshotQueryKey as "challengeCupDevControlsSnapshot"
  ](teamId);
  const devControlsQuery = useQuery({
    queryKey: devControlsKey,
    queryFn: () => fetchChallengeCupDevControlSnapshot(teamId),
    enabled: devControlsEnabled && Boolean(teamId.trim()),
    staleTime: 15_000,
  });
  const tokenUsageQuery = useQuery({
    queryKey: queryKeys.challengeCupTokenUsage(teamId),
    queryFn: () => fetchChallengeCupTokenUsage(teamId),
    enabled: Boolean(teamId.trim()),
    staleTime: 15_000,
    retry: false,
  });

  const queryClient = useQueryClient();
  const [snapshotRefreshing, setSnapshotRefreshing] = useState(false);
  const [devControlsOpen, setDevControlsOpen] = useState(defaultDevControlsOpen);
  const refreshDevControls = async () => {
    setSnapshotRefreshing(true);
    try {
      await queryClient.invalidateQueries({ queryKey: devControlsKey });
    } finally {
      setSnapshotRefreshing(false);
    }
  };

  async function runDevReadiness(vars: { teamId: string }) {
    return runChallengeCupDevReadiness(vars.teamId, { mode: "dev" });
  }

  async function runDev1(vars: { teamId: string }) {
    return runChallengeCupDevBatch(vars.teamId, devPlanIds.dev1, { maxItems: null, retryFailed: false });
  }

  async function runDev5(vars: { teamId: string; maxItems: number | null }) {
    return runChallengeCupDevBatch(vars.teamId, devPlanIds.dev5, { maxItems: vars.maxItems, retryFailed: false });
  }

  async function repairDev1(vars: { teamId: string }) {
    return runChallengeCupDevBatch(vars.teamId, devPlanIds.dev1, { maxItems: null, retryFailed: true });
  }

  async function repairDev5(vars: { teamId: string }) {
    return runChallengeCupDevBatch(vars.teamId, devPlanIds.dev5, { maxItems: null, retryFailed: true });
  }

  const readinessMutation = useMutation({
    mutationFn: runDevReadiness,
    onSuccess: () => refreshDevControls(),
  });
  const dev1Mutation = useMutation({
    mutationFn: runDev1,
    onSuccess: () => refreshDevControls(),
  });
  const dev5Mutation = useMutation({
    mutationFn: runDev5,
    onSuccess: () => refreshDevControls(),
  });
  const repairDev1Mutation = useMutation({
    mutationFn: repairDev1,
    onSuccess: () => refreshDevControls(),
  });
  const repairDev5Mutation = useMutation({
    mutationFn: repairDev5,
    onSuccess: () => refreshDevControls(),
  });
  const program = experimentStatusQuery.data?.[
    panelContract.programProjection.property as "competitionProgramProjection"
  ];
  const requiredDeepExperiments = program?.[
    panelContract.programProjection.requiredDeepExperimentsProperty as "requiredDeepExperiments"
  ] ?? [];
  const summary = questionStatusQuery.data?.summary;
  const results = summary?.validatedQuestionResults ?? [];
  const approvedDeepExperimentCount = requiredDeepExperiments.filter((item) => item.approved).length;

  const snapshot = devControlsQuery.data ?? null;
  const nextLegalAction = snapshot?.nextLegalAction ?? "";
  const report = snapshot?.report ?? null;
  const dev1 = snapshot?.batches?.[devPlanIds.dev1];
  const dev5 = snapshot?.batches?.[devPlanIds.dev5];
  const boundary = snapshot?.boundary ?? null;
  const anyMutationPending =
    readinessMutation.isPending
    || dev1Mutation.isPending
    || dev5Mutation.isPending
    || repairDev1Mutation.isPending
    || repairDev5Mutation.isPending;
  const anyActionPending = anyMutationPending || snapshotRefreshing;
  const activeMutationError =
    readinessMutation.error
    ?? dev1Mutation.error
    ?? dev5Mutation.error
    ?? repairDev1Mutation.error
    ?? repairDev5Mutation.error;
  const devNeedsAttention = Boolean(
    nextLegalAction.startsWith(panelContract.devControls.repairActionPrefix)
    || nextLegalAction === devActions.researchAuthorizationRequired
    || (report && report.status !== "READY"),
  );

  const programRetry = (
    <VButton type="button" variant="secondary" onClick={() => void experimentStatusQuery.refetch()}>
      {zh ? "重试" : "Retry"}
    </VButton>
  );
  const questionRetry = (
    <VButton type="button" variant="secondary" onClick={() => void questionStatusQuery.refetch()}>
      {zh ? "重试" : "Retry"}
    </VButton>
  );

  return (
    <VSurface tone="panel" className={styles.root} data-vui="competition-program-progress-panel">
      <div className={styles.header}>
        <div>
          <div className={styles.eyebrow}>Challenge Cup Program v2</div>
          <strong className={styles.title}>{program?.program.title || (zh ? "比赛状态尚未投影" : "Program projection unavailable")}</strong>
        </div>
        <VButton
          type="button"
          variant="ghost"
          onClick={() => {
            void questionStatusQuery.refetch();
            void experimentStatusQuery.refetch();
          }}
        >
          {zh ? "刷新" : "Refresh"}
        </VButton>
      </div>

      {experimentStatusQuery.isPending ? (
        <VStateSurface tone="loading" title={zh ? "读取比赛进度" : "Loading program progress"} className={styles.fill} />
      ) : experimentStatusQuery.isError ? (
        <VStateSurface tone="error" title={zh ? "比赛状态加载失败" : "Program status failed"} className={styles.fill} actions={programRetry}>
          {experimentStatusQuery.error instanceof Error ? experimentStatusQuery.error.message : String(experimentStatusQuery.error)}
        </VStateSurface>
      ) : program ? (
        <section className={styles.program} aria-label={zh ? "比赛总合同" : "Program contract"}>
          <div className={styles.programHeader}>
            <span>{program.program.problemId} · {program.program.track}</span>
            <VStatusChip tone={program.completion.completed ? "accent" : "warning"}>
              {program.completion.completed ? (zh ? "项目完成" : "Complete") : (zh ? "开发/任务未完成" : "Incomplete")}
            </VStatusChip>
          </div>
          <div className={styles.contractMeta}>
            <span>{zh ? "合同" : "Contract"} {program.contractVersion}</span>
            <span>A+B · {program.program.direction}</span>
            <span>{zh ? "题目 Schema" : "Question schema"} v{program.questionSchema.activeVersion}</span>
          </div>
          <div className={styles.metrics}>
            <div className={styles.metric}>
              <div className={styles.metricLabel}>{zh ? "125 题批准" : "Approved"}</div>
              <div className={styles.metricValue}>{program.fullCatalogResultSet.approvedQuestionCount}/{program.fullCatalogResultSet.requiredApprovedQuestionCount}</div>
            </div>
            <div className={styles.metric}>
              <div className={styles.metricLabel}>{zh ? "尚缺题目" : "Missing"}</div>
              <div className={styles.metricValue}>{program.fullCatalogResultSet.missingQuestionCount}</div>
            </div>
            <div className={styles.metric}>
              <div className={styles.metricLabel}>{zh ? "独立实验" : "Deep experiments"}</div>
              <div className={styles.metricValue}>{approvedDeepExperimentCount}/{requiredDeepExperiments.length}</div>
            </div>
          </div>
          <div className={styles.catalog} title={program.questionCatalog.catalogSha256}>
            {program.questionCatalog.catalogId} · {program.questionCatalog.questionCount} · SHA-256 {program.questionCatalog.catalogSha256.slice(0, 12)}…
          </div>
          <div className={styles.experimentGrid}>
            {requiredDeepExperiments.map((experiment) => (
              <article className={styles.experimentCard} key={experiment.experimentId}>
                <div className={styles.experimentHeader}>
                  <strong>{experiment.questionId} · {experiment.name}</strong>
                  <VStatusChip tone={experiment.approved ? "accent" : "warning"}>
                    {experiment.approved ? (zh ? "已批准" : "Approved") : (zh ? "未启动/未批准" : "Not approved")}
                  </VStatusChip>
                </div>
                <div className={styles.experimentIds}>{experiment.themeId}</div>
                <div className={styles.experimentIds}>{experiment.campaignId}</div>
                <div className={styles.locator}>
                  {zh
                    ? "下一合法动作：DEV fixture；真实 CUDA / DANDI 需单独科研授权。"
                    : "Next legal action: DEV fixture; real CUDA/DANDI needs research authorization."}
                </div>
              </article>
            ))}
          </div>
          <div className={styles.boundary} role="note">
            <strong>{zh ? "隔离边界" : "Isolation"}</strong>
            <span>
              {program.independentThemeBoundaries.separateThemes && program.independentThemeBoundaries.separateCampaigns
                ? (zh ? "独立 Theme + 独立 Campaign；跨实验科研证据禁止复用。" : "Separate themes and campaigns; cross-experiment scientific evidence reuse is forbidden.")
                : (zh ? "隔离合同未满足。" : "Isolation contract is not satisfied.")}
            </span>
          </div>
          {program.directionSubmissionRequirement.blocksSubmissionReady ? (
            <div className={styles.notice} role="status">
              {zh ? "提交方向要求尚未捕获，当前不能标记 submission ready。" : "Submission direction is not captured; submission ready remains blocked."}
            </div>
          ) : null}
        </section>
      ) : (
        <VEmptyState title={zh ? "Program v2 状态不可用" : "Program v2 unavailable"} className={styles.empty} actions={programRetry}>
          {zh ? "后端尚未提供 competitionProgramProjection。" : "competitionProgramProjection is not available."}
        </VEmptyState>
      )}

      <ChallengeSubmissionReadinessPanel teamId={teamId} lang={lang} onOpenQuestion={onOpenQuestion} />
      <ChallengeCatalogReadinessPanel teamId={teamId} lang={lang} />
      {isTokenUsageOverview(tokenUsageQuery.data) ? (
        <ChallengeTokenUsageStrip
          lang={lang}
          title={zh ? "Program token 消耗" : "Program token usage"}
          totalTokens={tokenUsageQuery.data.program.totalTokens}
          callCount={tokenUsageQuery.data.program.callCount}
          inputTokens={tokenUsageQuery.data.program.inputTokens}
          outputTokens={tokenUsageQuery.data.program.outputTokens}
        />
      ) : null}
      <ChallengeCatalogOverview
        teamId={teamId}
        lang={lang}
        onOpenQuestion={onOpenQuestion}
        devBatchControlsEnabled={devControlsEnabled}
      />

      {devControlsEnabled ? <section className={styles.devControls} aria-label={zh ? "开发态就绪与批次控制" : "DEV readiness and batch control"}>
        <div className={styles.sectionHeader}>
          <strong>{zh ? "开发态就绪 / 批次 / 证据 locator" : "DEV readiness / batches / locators"}</strong>
          <div className={styles.sectionHeaderActions}>
            <VStatusChip tone={report?.status === "READY" ? "success" : report ? "danger" : "neutral"}>
              {zh ? "DEV-only" : "DEV-only"}
            </VStatusChip>
            <VButton
              type="button"
              variant="ghost"
              density="compact"
              aria-expanded={devControlsOpen}
              onPress={() => setDevControlsOpen((open) => !open)}
            >
              {devControlsOpen ? (zh ? "收起" : "Collapse") : (zh ? "展开" : "Expand")}
            </VButton>
          </div>
        </div>
        {devControlsOpen ? (
          <>
        {devControlsQuery.isPending ? (
          <VStateSurface tone="loading" title={zh ? "读取 DEV 控制快照" : "Loading DEV control snapshot"} fill className={styles.fill} />
        ) : devControlsQuery.isError || !snapshot ? (
          <div className={styles.error} role="alert" data-dev-controls={devMarkers.snapshotError}>
            <div className={styles.devMeta}>
              {devControlsQuery.error instanceof Error ? devControlsQuery.error.message : String(devControlsQuery.error ?? (zh ? "DEV 控制快照不可用" : "DEV control snapshot unavailable"))}
            </div>
            <VButton type="button" variant="secondary" data-dev-controls={devMarkers.snapshotRetry} onClick={() => void devControlsQuery.refetch()}>
              {zh ? "重试" : "Retry"}
            </VButton>
            <VButton
              type="button"
              variant="danger"
              data-dev-controls={devMarkers.snapshotReadinessRepair}
              isDisabled={readinessMutation.isPending}
              isPending={readinessMutation.isPending}
              onClick={() => readinessMutation.mutate({ teamId })}
            >
              {zh ? "重新运行 DEV readiness" : "Re-run DEV readiness"}
            </VButton>
          </div>
        ) : (
          <>
            <div className={styles.devRow} data-dev-controls={devMarkers.readiness}>
              <div className={styles.devRowHeader}>
                <strong>Readiness</strong>
                <VStatusChip tone={readinessMutation.isPending ? "accent" : report?.status === "READY" ? "success" : report ? "danger" : "neutral"}>
                  {readinessLabel(zh, report, readinessMutation.isPending)}
                </VStatusChip>
              </div>
              {report ? (
                <>
                  <div className={styles.devMeta}>
                    {zh ? `报告状态 ${report.status} · 生成 ${report.generatedAt || "—"}` : `Status ${report.status} · generated ${report.generatedAt || "—"}`}
                  </div>
                  {report.gates.length > 0 ? (
                    <ul className={styles.gateList}>
                      {report.gates.map((gate) => (
                        <li key={gate.gateId} className={styles.gateItem}>
                          <span className={styles.gateId}>{gate.gateId}</span>
                          <VStatusChip tone={gate.status === "PASS" ? "success" : gate.status === "FAIL" ? "danger" : "warning"}>
                            {gate.status || "—"}
                          </VStatusChip>
                          <span className={styles.gateDetail}>{gate.detail}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : (
                <VEmptyState title={zh ? "readiness 未运行" : "Readiness not run"} className={styles.empty}>
                  {zh ? "先运行 DEV readiness 生成门禁报告。" : "Run DEV readiness to generate the gate report."}
                </VEmptyState>
              )}
            </div>

            {([devPlanIds.dev1, devPlanIds.dev5] as const).map((planId) => {
              const batch = planId === devPlanIds.dev1 ? dev1 : dev5;
              const running = planId === devPlanIds.dev1 ? dev1Mutation.isPending : dev5Mutation.isPending;
              return (
                <div className={styles.devRow} key={planId} data-dev-controls={planId}>
                  <div className={styles.devRowHeader}>
                    <strong>{planId}{batch ? <span className={styles.devMeta}> · {batch.gateId}</span> : null}</strong>
                    <VStatusChip tone={batchTone(batch, running)}>{batchLabel(zh, batch, running)}</VStatusChip>
                  </div>
                  {batch ? (
                    <>
                      <div className={styles.devMeta}>
                        {zh
                          ? `成功 ${batch.succeededCount}/${batch.questionCount} · 待处理 ${batch.pendingCount} · 失败 ${batch.failedCount} · 阻塞 ${batch.blockedCount}`
                          : `succeeded ${batch.succeededCount}/${batch.questionCount} · pending ${batch.pendingCount} · failed ${batch.failedCount} · blocked ${batch.blockedCount}`}
                      </div>
                      <div className={styles.devMeta}>
                        {zh
                          ? `已尝试 ${batch.totalAttempts} 次 · ${batch.canResume ? "可继续" : "无需继续"} · 更新 ${batch.lastUpdatedAt || "—"}`
                          : `${batch.totalAttempts} attempts · ${batch.canResume ? "can continue" : "no continuation needed"} · updated ${batch.lastUpdatedAt || "—"}`}
                      </div>
                      {batch.completedQuestionIds.length > 0 ? (
                        <div className={styles.devMeta}>
                          {zh ? "完成：" : "done: "}{batch.completedQuestionIds.join(", ")}
                        </div>
                      ) : null}
                      {batch.pendingQuestionIds.length > 0 ? (
                        <div className={styles.devMeta}>
                          {zh ? "待处理：" : "pending: "}{batch.pendingQuestionIds.join(", ")}
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <VEmptyState title={`${planId} ${zh ? "未运行" : "unrun"}`} className={styles.empty}>
                      {planId === devPlanIds.dev1
                        ? (zh ? "readiness 通过后运行。" : "Run after readiness passes.")
                        : (zh ? "dev-1 通过后先处理首批题目，完成后可继续剩余题目。" : "After dev-1 passes, process the first batch and continue with the remaining questions.")}
                    </VEmptyState>
                  )}
                </div>
              );
            })}

            <div className={styles.actions} data-dev-controls={devMarkers.actions} aria-live="polite">
              {nextLegalAction === devActions.runReadiness ? (
                <VButton
                  type="button"
                  variant="primary"
                  isDisabled={anyActionPending}
                  isPending={readinessMutation.isPending}
                  onClick={() => readinessMutation.mutate({ teamId })}
                >
                  {zh ? "运行 DEV readiness" : "Run DEV readiness"}
                </VButton>
              ) : null}
              {nextLegalAction === devActions.runDev1 ? (
                <VButton
                  type="button"
                  variant="primary"
                  isDisabled={anyActionPending}
                  isPending={dev1Mutation.isPending}
                  onClick={() => dev1Mutation.mutate({ teamId })}
                >
                  {zh ? "运行 dev-1 fixture" : "Run dev-1 fixture"}
                </VButton>
              ) : null}
              {nextLegalAction === devActions.runDev5 ? (
                <VButton
                  type="button"
                  variant="primary"
                  isDisabled={anyActionPending}
                  isPending={dev5Mutation.isPending}
                  onClick={() => dev5Mutation.mutate({ teamId, maxItems: 2 })}
                >
                  {zh ? "开始处理首批题目" : "Process the first question batch"}
                </VButton>
              ) : null}
              {nextLegalAction === devActions.resumeDev5 ? (
                <VButton
                  type="button"
                  variant="primary"
                  isDisabled={anyActionPending}
                  isPending={dev5Mutation.isPending}
                  onClick={() => dev5Mutation.mutate({ teamId, maxItems: null })}
                >
                  {zh ? "继续处理剩余题目" : "Continue with remaining questions"}
                </VButton>
              ) : null}
              {nextLegalAction === devActions.repairReadiness ? (
                <>
                  <VButton
                    type="button"
                    variant="danger"
                    isDisabled={anyActionPending}
                    isPending={readinessMutation.isPending}
                    onClick={() => readinessMutation.mutate({ teamId })}
                  >
                    {zh ? "重新运行 readiness" : "Re-run readiness"}
                  </VButton>
                  <div className={styles.notice} role="note">
                    {zh
                      ? "平台门禁存在失败，必须修复后才能继续；下一阶段保持阻塞，禁止放行。"
                      : "Platform gates failed; repair required before continuing; the next stage stays blocked and cannot advance."}
                  </div>
                </>
              ) : null}
              {nextLegalAction === devActions.repairDev1 ? (
                <>
                  <VButton
                    type="button"
                    variant="danger"
                    isDisabled={anyActionPending}
                    isPending={repairDev1Mutation.isPending}
                    onClick={() => repairDev1Mutation.mutate({ teamId })}
                  >
                    {zh ? "修复 dev-1 fixture" : "Repair dev-1 fixture"}
                  </VButton>
                  <div className={styles.notice} role="note">
                    {zh
                      ? "dev-1 fixture 存在失败/阻塞，必须修复后才能继续；下一阶段保持阻塞，禁止放行。"
                      : "dev-1 fixture has failed/blocked items; repair required before continuing; the next stage stays blocked and cannot advance."}
                  </div>
                </>
              ) : null}
              {nextLegalAction === devActions.repairDev5 ? (
                <>
                  <VButton
                    type="button"
                    variant="danger"
                    isDisabled={anyActionPending}
                    isPending={repairDev5Mutation.isPending}
                    onClick={() => repairDev5Mutation.mutate({ teamId })}
                  >
                    {zh ? "修复 dev-5 fixture" : "Repair dev-5 fixture"}
                  </VButton>
                  <div className={styles.notice} role="note">
                    {zh
                      ? "dev-5 fixture 存在失败/阻塞，必须修复后才能继续；下一阶段保持阻塞，禁止放行。"
                      : "dev-5 fixture has failed/blocked items; repair required before continuing; the next stage stays blocked and cannot advance."}
                  </div>
                </>
              ) : null}
              {nextLegalAction === devActions.researchAuthorizationRequired ? (
                <div className={styles.notice} role="status">
                  {zh
                    ? "DEV fixture 已全部通过，当前没有可自动执行的下一步（系统状态 RESEARCH_AUTHORIZATION_REQUIRED）。请科研负责人单独授权后，真实 Qwen / CUDA / DANDI / 125 题运行与正式提交才会解锁。"
                    : "DEV fixtures all passed; there is no automatic next step (system state RESEARCH_AUTHORIZATION_REQUIRED). Real Qwen/CUDA/DANDI/125-question runs and formal submission unlock only after separate research-owner authorization."}
                </div>
              ) : null}
              <div className={styles.locator}>
                {zh ? "下一合法动作：" : "Next legal action: "}{actionLabel(zh, nextLegalAction)}
              </div>
            </div>

            {boundary ? (
              <div className={styles.boundary} role="note">
                <strong>{zh ? "DEV 隔离边界" : "DEV-only boundary"}</strong>
                <span>
                  {zh
                    ? `DEV fixture 只允许计划 ${boundary.authorizedPlans.join(" / ")}；${boundary.forbiddenPlans.join(" / ")} 与真实 G1/G5/G12/G125、Qwen、CUDA/GPU、DANDI 下载、联网搜集、正式提交均未授权（fixtureOnly=${String(boundary.fixtureOnly)}）。`
                    : `DEV fixture plans ${boundary.authorizedPlans.join(" / ")} only; ${boundary.forbiddenPlans.join(" / ")} and real G1/G5/G12/G125, Qwen, CUDA/GPU, DANDI download, live collection and formal submission are unauthorized (fixtureOnly=${String(boundary.fixtureOnly)}).`}
                </span>
                <span>
                  {zh
                    ? "G1/G5/G12/G125 指分层试点批次：1 题 → 5 题 → 12 题领域分层 → 125 题全量；任一前置批次失败都不会放行下一层。"
                    : "G1/G5/G12/G125 are staged pilot batches: 1 → 5 → 12-domain → all 125 questions; a failed stage never unlocks the next."}
                </span>
                <div className={styles.devMeta}>
                  forbiddenFeatures: {boundary.forbiddenFeatures.join(" / ") || "—"}
                </div>
              </div>
            ) : null}

            <div className={styles.locator} data-dev-controls={devMarkers.cliLocator}>
              {zh
                ? "开发者诊断（非授权入口，普通使用者可忽略）：python scripts/challenge_cup/platform_flow_ready.py · PlatformFlowReady"
                : "Developer diagnostic (not an authorization entry; safe to ignore): python scripts/challenge_cup/platform_flow_ready.py · PlatformFlowReady"}
            </div>
          </>
        )}

        {activeMutationError ? (
          <div className={styles.error} role="alert" data-dev-controls={devMarkers.mutationError}>
            {zh
              ? `DEV 操作失败：${errorMessage(activeMutationError)}（可安全重试）`
              : `DEV action failed: ${errorMessage(activeMutationError)} (retry is safe)`}
          </div>
        ) : null}
          </>
        ) : (
          <p className={styles.devCollapsedHint} data-dev-controls={devMarkers.collapsedSummary} role={devNeedsAttention ? "status" : undefined}>
            {devNeedsAttention ? (
              <>
                <strong>{zh ? "开发态需要处理" : "DEV action needs attention"}</strong>
                <span>
                  {zh
                    ? `：${actionLabel(zh, nextLegalAction)}。展开控制区查看修复操作。`
                    : `: ${actionLabel(zh, nextLegalAction)}. Expand the controls to repair or continue.`}
                </span>
              </>
            ) : (
              zh
                ? "开发态控制已折叠；批量运行的日常操作在上方题目总览，fixture 控制展开后可见。"
                : "DEV controls collapsed; daily batch operations live in the catalog overview above."
            )}
          </p>
        )}
      </section> : null}

      <section className={styles.questionSection} aria-label={zh ? "单题结果" : "Question results"}>
        <div className={styles.sectionHeader}>
          <strong>{zh ? "单题结果与审核" : "Question results"}</strong>
          <div className={styles.actions}>
            {summary ? <span>{zh ? `已验证 ${summary.validatedQuestionCount}` : `${summary.validatedQuestionCount} validated`}</span> : null}
          </div>
        </div>
        {questionStatusQuery.isPending ? (
          <VStateSurface tone="loading" title={zh ? "读取题目结果" : "Loading question results"} className={styles.fill} />
        ) : questionStatusQuery.isError ? (
          <VStateSurface tone="error" title={zh ? "题目结果加载失败" : "Question results failed"} className={styles.fill} actions={questionRetry}>
            {questionStatusQuery.error instanceof Error ? questionStatusQuery.error.message : String(questionStatusQuery.error)}
          </VStateSurface>
        ) : (
          <>
            {!summary || results.length === 0 ? (
              <VEmptyState title={zh ? "暂无已验证题目" : "No validated questions"} className={styles.empty}>
                {zh ? "完成受控运行与候选晋升后，题目结果会出现在这里。" : "Question results appear here after controlled runs and candidate promotion."}
              </VEmptyState>
            ) : (
              <ul className={styles.list}>
                {results.map((item) => (
                  <li key={item.questionId} className={styles.item}>
                    <div className={styles.itemText}>
                      <div className={styles.itemTitle}>{item.questionId}</div>
                      <div className={styles.itemMeta}>{item.runId} · {item.status}</div>
                    </div>
                    <VButton type="button" variant="ghost" onClick={() => onOpenQuestion(item.questionId)}>
                      {zh ? "详情" : "Detail"}
                    </VButton>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

    </VSurface>
  );
}
