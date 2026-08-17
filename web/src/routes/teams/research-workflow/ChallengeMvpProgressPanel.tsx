/**
 * Program v2 and question-result progress inside the research workflow canvas.
 *
 * Both sections are read-only backend projections. This component never derives
 * completion from legacy MVP counts and never starts a question or experiment.
 */
import { useQuery } from "@tanstack/react-query";

import { getChallengeQuestionRunStatus } from "../../../api/challengeQuestionRuns";
import { queryKeys } from "../../../api/queryKeys";
import { fetchExperimentPlanningStatus } from "../../../api/teamExperiment";
import {
  VButton,
  VEmptyState,
  VStateSurface,
  VStatusChip,
  VSurface,
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

  if (statusQuery.isPending) {
    return (
      <VSurface tone="panel" className={styles.root}>
        <VStateSurface tone="loading" title={zh ? "读取比赛与题目进度" : "Loading program and question progress"} fill className={styles.fill} />
      </VSurface>
    );
  }

  if (statusQuery.isError || !statusQuery.data) {
    return (
      <VSurface tone="panel" className={styles.root}>
        <div className={styles.error} role="alert">
          {statusQuery.error instanceof Error ? statusQuery.error.message : String(statusQuery.error)}
        </div>
        <VButton type="button" variant="secondary" onClick={() => void statusQuery.refetch()}>
          {zh ? "重试" : "Retry"}
        </VButton>
      </VSurface>
    );
  }

  const program = statusQuery.data.experimentStatus?.competitionProgramProjection;
  const summary = statusQuery.data.questionStatus?.summary;
  const results = summary?.validatedQuestionResults ?? [];
  const approvedDeepExperimentCount = program?.requiredDeepExperiments.filter((item) => item.approved).length ?? 0;

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

      {program ? (
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
          <section className={styles.readiness} aria-label={zh ? "开发态就绪与批次控制" : "DEV readiness and batch control"}>
            <div className={styles.sectionHeader}>
              <strong>{zh ? "开发态就绪 / 批次 / 证据 locator" : "DEV readiness / batches / locators"}</strong>
            </div>
            <div className={styles.gateRow}>
              <VStatusChip tone="warning">R0 source_integrity=CLI</VStatusChip>
              <VStatusChip tone="warning">R1 clean_clone=CLI</VStatusChip>
              <VStatusChip tone="warning">PlatformFlowReady CLI</VStatusChip>
              <VStatusChip tone={program.directionSubmissionRequirement.blocksSubmissionReady ? "warning" : "accent"}>
                {program.directionSubmissionRequirement.blocksSubmissionReady
                  ? (zh ? "提交投影未冻结" : "Submission projection unfrozen")
                  : (zh ? "提交投影已捕获" : "Submission projection captured")}
              </VStatusChip>
            </div>
            <div className={styles.locator}>
              python scripts/challenge_cup/platform_flow_ready.py
            </div>
            <div className={styles.boundary} role="note">
              <strong>{zh ? "DEV 批次" : "DEV batches"}</strong>
              <span>
                {zh
                  ? "允许 fixture 计划 dev-1 / dev-5；真实 G1/G5/G12/G125、Qwen 与联网搜集未授权。"
                  : "Fixture plans dev-1 / dev-5 are allowed; real G1/G5/G12/G125, Qwen and live collection are unauthorized."}
              </span>
            </div>
            <div className={styles.locator}>
              {zh ? "下一合法动作：运行 DEV fixture 与 PlatformFlowReady CLI，然后停止于 RESEARCH_AUTHORIZATION_REQUIRED。" : "Next legal action: run DEV fixtures and the PlatformFlowReady CLI, then stop at RESEARCH_AUTHORIZATION_REQUIRED."}
            </div>
          </section>
        </section>
      ) : (
        <VEmptyState title={zh ? "Program v2 状态不可用" : "Program v2 unavailable"} className={styles.empty}>
          {statusQuery.data.programError || (zh ? "后端尚未提供 competitionProgramProjection。" : "competitionProgramProjection is not available.")}
        </VEmptyState>
      )}

      <section className={styles.questionSection} aria-label={zh ? "单题结果" : "Question results"}>
        <div className={styles.sectionHeader}>
          <strong>{zh ? "单题结果与审核" : "Question results"}</strong>
          {summary ? <span>{zh ? `已验证 ${summary.validatedQuestionCount}` : `${summary.validatedQuestionCount} validated`}</span> : null}
        </div>
        {statusQuery.data.questionError ? <div className={styles.error} role="alert">{statusQuery.data.questionError}</div> : null}
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
      </section>
    </VSurface>
  );
}
