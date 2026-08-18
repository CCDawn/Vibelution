/**
 * Program v2 and question-result progress inside the research workflow canvas.
 *
 * The Program v2 / question sections are read-only backend projections. The DEV
 * control section is team-scoped and DEV-only: readiness gates, dev-1/dev-5
 * fixture checkpoints and the legal next action come from the DEV controls
 * snapshot. Mouse actions are strictly gated by the persisted nextLegalAction
 * and mutation pending state; repair states only surface a blocking hint and
 * never advance to the next stage. No real experiment, Qwen, CUDA/GPU, DANDI,
 * network collection or formal submission is ever started.
 *
 * The program/question combined query degrades independently from the DEV
 * controls: while it is pending or failing the DEV snapshot section stays
 * fully visible and operable. After a mutation, actions stay pending/disabled
 * until the snapshot refetch completes so a delayed refetch cannot trigger a
 * duplicate POST.
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
import styles from "./ChallengeMvpProgressPanel.styles";

export type ChallengeMvpProgressPanelProps = {
  teamId: string;
  lang?: "zh" | "en";
  onOpenQuestion: (questionId: string) => void;
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
    run_dev_readiness: zh ? "运行 DEV readiness" : "Run DEV readiness",
    run_dev_1_fixture_batch: zh ? "运行 dev-1 fixture" : "Run dev-1 fixture",
    run_dev_5_fixture_batch: zh ? "运行 dev-5（首次 maxItems=2）" : "Run dev-5 (first maxItems=2)",
    resume_dev_5_fixture_batch: zh ? "恢复 dev-5" : "Resume dev-5",
    repair_failed_platform_gates: zh ? "修复失败的平台门禁" : "Repair failed platform gates",
    repair_dev_1_fixture_batch: zh ? "修复 dev-1 fixture" : "Repair dev-1 fixture",
    repair_dev_5_fixture_batch: zh ? "修复 dev-5 fixture" : "Repair dev-5 fixture",
    RESEARCH_AUTHORIZATION_REQUIRED: "RESEARCH_AUTHORIZATION_REQUIRED",
  };
  return labels[action] ?? action;
}

export function ChallengeMvpProgressPanel({
  teamId,
  lang = "zh",
  onOpenQuestion,
}: ChallengeMvpProgressPanelProps) {
  const zh = lang === "zh";
  const statusQuery = useQuery({
    queryKey: [...queryKeys.challengeQuestionRunStatus(teamId), "program-v2"],
    queryFn: async () => {
      const [questionResult, experimentResult] = await Promise.allSettled([
        getChallengeQuestionRunStatus(teamId),
        fetchExperimentPlanningStatus<ExperimentPlanningStatusPayload>(teamId),
      ]);
      if (questionResult.status === "rejected" && experimentResult.status === "rejected") {
        throw new Error(`${errorMessage(questionResult.reason)}; ${errorMessage(experimentResult.reason)}`);
      }
      return {
        questionStatus: questionResult.status === "fulfilled" ? questionResult.value : null,
        experimentStatus: experimentResult.status === "fulfilled" ? experimentResult.value : null,
        questionError: questionResult.status === "rejected" ? errorMessage(questionResult.reason) : "",
        programError: experimentResult.status === "rejected" ? errorMessage(experimentResult.reason) : "",
      };
    },
    enabled: Boolean(teamId.trim()),
    staleTime: 30_000,
  });

  const devControlsKey = queryKeys.challengeCupDevControlsSnapshot(teamId);
  const devControlsQuery = useQuery({
    queryKey: devControlsKey,
    queryFn: () => fetchChallengeCupDevControlSnapshot(teamId),
    enabled: Boolean(teamId.trim()),
    staleTime: 15_000,
  });

  const queryClient = useQueryClient();
  const [snapshotRefreshing, setSnapshotRefreshing] = useState(false);
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
    return runChallengeCupDevBatch(vars.teamId, "dev-1", { maxItems: null, retryFailed: false });
  }

  async function runDev5(vars: { teamId: string; maxItems: number | null }) {
    return runChallengeCupDevBatch(vars.teamId, "dev-5", { maxItems: vars.maxItems, retryFailed: false });
  }

  async function repairDev1(vars: { teamId: string }) {
    return runChallengeCupDevBatch(vars.teamId, "dev-1", { maxItems: null, retryFailed: true });
  }

  async function repairDev5(vars: { teamId: string }) {
    return runChallengeCupDevBatch(vars.teamId, "dev-5", { maxItems: null, retryFailed: true });
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

  const program = statusQuery.data?.experimentStatus?.competitionProgramProjection;
  const summary = statusQuery.data?.questionStatus?.summary;
  const results = summary?.validatedQuestionResults ?? [];
  const approvedDeepExperimentCount = program?.requiredDeepExperiments.filter((item) => item.approved).length ?? 0;

  const snapshot = devControlsQuery.data ?? null;
  const nextLegalAction = snapshot?.nextLegalAction ?? "";
  const report = snapshot?.report ?? null;
  const dev1 = snapshot?.batches?.["dev-1"];
  const dev5 = snapshot?.batches?.["dev-5"];
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

  const programRetry = (
    <VButton type="button" variant="secondary" onClick={() => void statusQuery.refetch()}>
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
        <VButton type="button" variant="ghost" onClick={() => void statusQuery.refetch()}>
          {zh ? "刷新" : "Refresh"}
        </VButton>
      </div>

      {statusQuery.isPending ? (
        <VStateSurface tone="loading" title={zh ? "读取比赛与题目进度" : "Loading program and question progress"} className={styles.fill} />
      ) : statusQuery.isError ? (
        <VStateSurface tone="error" title={zh ? "比赛与题目状态加载失败" : "Program and question status failed"} className={styles.fill} actions={programRetry}>
          {statusQuery.error instanceof Error ? statusQuery.error.message : String(statusQuery.error)}
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
              <div className={styles.metricValue}>{approvedDeepExperimentCount}/{program.requiredDeepExperiments.length}</div>
            </div>
          </div>
          <div className={styles.catalog} title={program.questionCatalog.catalogSha256}>
            {program.questionCatalog.catalogId} · {program.questionCatalog.questionCount} · SHA-256 {program.questionCatalog.catalogSha256.slice(0, 12)}…
          </div>
          <div className={styles.experimentGrid}>
            {program.requiredDeepExperiments.map((experiment) => (
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
          {statusQuery.data?.programError || (zh ? "后端尚未提供 competitionProgramProjection。" : "competitionProgramProjection is not available.")}
        </VEmptyState>
      )}

      <section className={styles.devControls} aria-label={zh ? "开发态就绪与批次控制" : "DEV readiness and batch control"}>
        <div className={styles.sectionHeader}>
          <strong>{zh ? "开发态就绪 / 批次 / 证据 locator" : "DEV readiness / batches / locators"}</strong>
          <VStatusChip tone={report?.status === "READY" ? "success" : report ? "danger" : "neutral"}>
            {zh ? "DEV-only" : "DEV-only"}
          </VStatusChip>
        </div>

        {devControlsQuery.isPending ? (
          <VStateSurface tone="loading" title={zh ? "读取 DEV 控制快照" : "Loading DEV control snapshot"} fill className={styles.fill} />
        ) : devControlsQuery.isError || !snapshot ? (
          <div className={styles.error} role="alert" data-dev-controls="snapshot-error">
            <div className={styles.devMeta}>
              {devControlsQuery.error instanceof Error ? devControlsQuery.error.message : String(devControlsQuery.error ?? (zh ? "DEV 控制快照不可用" : "DEV control snapshot unavailable"))}
            </div>
            <VButton type="button" variant="secondary" data-dev-controls="snapshot-retry" onClick={() => void devControlsQuery.refetch()}>
              {zh ? "重试" : "Retry"}
            </VButton>
            <VButton
              type="button"
              variant="danger"
              data-dev-controls="snapshot-readiness-repair"
              isDisabled={readinessMutation.isPending}
              isPending={readinessMutation.isPending}
              onClick={() => readinessMutation.mutate({ teamId })}
            >
              {zh ? "重新运行 DEV readiness" : "Re-run DEV readiness"}
            </VButton>
          </div>
        ) : (
          <>
            <div className={styles.devRow} data-dev-controls="readiness">
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

            {(["dev-1", "dev-5"] as const).map((planId) => {
              const batch = planId === "dev-1" ? dev1 : dev5;
              const running = planId === "dev-1" ? dev1Mutation.isPending : dev5Mutation.isPending;
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
                        attempts={batch.totalAttempts} · canResume={String(batch.canResume)} · updated={batch.lastUpdatedAt || "—"}
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
                      {planId === "dev-1"
                        ? (zh ? "readiness 通过后运行。" : "Run after readiness passes.")
                        : (zh ? "dev-1 通过后首次以 maxItems=2 运行，随后恢复。" : "Run first with maxItems=2 after dev-1, then resume.")}
                    </VEmptyState>
                  )}
                </div>
              );
            })}

            <div className={styles.actions} data-dev-controls="actions" aria-live="polite">
              {nextLegalAction === "run_dev_readiness" ? (
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
              {nextLegalAction === "run_dev_1_fixture_batch" ? (
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
              {nextLegalAction === "run_dev_5_fixture_batch" ? (
                <VButton
                  type="button"
                  variant="primary"
                  isDisabled={anyActionPending}
                  isPending={dev5Mutation.isPending}
                  onClick={() => dev5Mutation.mutate({ teamId, maxItems: 2 })}
                >
                  {zh ? "首次运行 dev-5（maxItems=2）" : "Run dev-5 first (maxItems=2)"}
                </VButton>
              ) : null}
              {nextLegalAction === "resume_dev_5_fixture_batch" ? (
                <VButton
                  type="button"
                  variant="primary"
                  isDisabled={anyActionPending}
                  isPending={dev5Mutation.isPending}
                  onClick={() => dev5Mutation.mutate({ teamId, maxItems: null })}
                >
                  {zh ? "恢复 dev-5（maxItems=null）" : "Resume dev-5 (maxItems=null)"}
                </VButton>
              ) : null}
              {nextLegalAction === "repair_failed_platform_gates" ? (
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
              {nextLegalAction === "repair_dev_1_fixture_batch" ? (
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
              {nextLegalAction === "repair_dev_5_fixture_batch" ? (
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
              {nextLegalAction === "RESEARCH_AUTHORIZATION_REQUIRED" ? (
                <div className={styles.notice} role="status">
                  {zh
                    ? "DEV fixture 已全部通过，停在 RESEARCH_AUTHORIZATION_REQUIRED；真实 Qwen / CUDA / DANDI / 125 题 / 提交需单独科研授权。"
                    : "DEV fixtures all passed; stopped at RESEARCH_AUTHORIZATION_REQUIRED. Real Qwen/CUDA/DANDI/125-question/submission needs separate research authorization."}
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
                <div className={styles.devMeta}>
                  forbiddenFeatures: {boundary.forbiddenFeatures.join(" / ") || "—"}
                </div>
              </div>
            ) : null}

            <div className={styles.locator} data-dev-controls="cli-locator">
              {zh
                ? "CLI 诊断（非授权入口）：python scripts/challenge_cup/platform_flow_ready.py · PlatformFlowReady"
                : "CLI diagnostic (not an authorization entry): python scripts/challenge_cup/platform_flow_ready.py · PlatformFlowReady"}
            </div>
          </>
        )}

        {activeMutationError ? (
          <div className={styles.error} role="alert" data-dev-controls="mutation-error">
            {zh
              ? `DEV 操作失败：${errorMessage(activeMutationError)}（可安全重试）`
              : `DEV action failed: ${errorMessage(activeMutationError)} (retry is safe)`}
          </div>
        ) : null}
      </section>

      <section className={styles.questionSection} aria-label={zh ? "单题结果" : "Question results"}>
        <div className={styles.sectionHeader}>
          <strong>{zh ? "单题结果与审核" : "Question results"}</strong>
          {summary ? <span>{zh ? `已验证 ${summary.validatedQuestionCount}` : `${summary.validatedQuestionCount} validated`}</span> : null}
        </div>
        {statusQuery.isPending ? (
          <VStateSurface tone="loading" title={zh ? "读取题目结果" : "Loading question results"} className={styles.fill} />
        ) : statusQuery.isError ? (
          <VStateSurface tone="error" title={zh ? "题目结果加载失败" : "Question results failed"} className={styles.fill} actions={programRetry}>
            {statusQuery.error instanceof Error ? statusQuery.error.message : String(statusQuery.error)}
          </VStateSurface>
        ) : (
          <>
            {statusQuery.data?.questionError ? <div className={styles.error} role="alert">{statusQuery.data.questionError}</div> : null}
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
