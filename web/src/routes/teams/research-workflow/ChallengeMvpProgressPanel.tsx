/**
 * Program v2 and question-result progress inside the research workflow canvas.
 *
 * Every section is a read-only backend projection: the program contract, the
 * submission/catalog readiness gates, the real batches, token usage and the
 * 125-question catalog come from the live challenge-program endpoints. The
 * question-status and experiment-planning queries are separate and share the
 * canonical keys (queryKeys.challengeQuestionRunStatus /
 * experimentPlanningStatusQueryKey) so they dedupe with the other panels and
 * degrade independently.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getChallengeQuestionRunStatus } from "../../../api/challengeQuestionRuns";
import { queryKeys } from "../../../api/queryKeys";
import {
  fetchChallengeCupTokenUsage,
  fetchExperimentPlanningStatus,
} from "../../../api/teamExperiment";
import {
  VButton,
  VEmptyState,
  VStateSurface,
  VStatusChip,
  VSurface,
} from "../../../components/vui";
import type { ExperimentPlanningStatusPayload } from "../experimentLoopModel";
import { experimentPlanningStatusQueryKey } from "../experimentLoopModel";
import { ChallengeCatalogOverview } from "../challenge-cup/ChallengeCatalogOverview";
import { ChallengeQuestionRegisterDialog } from "../challenge-cup/ChallengeQuestionRegisterDialog";
import { ChallengeTokenUsageStrip } from "../challenge-cup/ChallengeTokenUsageStrip";
import { isTokenUsageOverview } from "../challenge-cup/challengeTokenUsageModel";
import { ChallengeSubmissionReadinessPanel } from "./ChallengeSubmissionReadinessPanel";
import { ChallengeCatalogReadinessPanel } from "./ChallengeCatalogReadinessPanel";
import { ChallengeRealBatchControlPanel } from "./ChallengeRealBatchControlPanel";
import { useShellI18n } from "../../../i18n/useShellI18n";
import styles from "./ChallengeMvpProgressPanel.styles";
import challengeMvpProgressPanelContract from "./ChallengeMvpProgressPanel.contract.json";

const panelContract = challengeMvpProgressPanelContract;

export type ChallengeMvpProgressPanelProps = {
  teamId: string;
  lang?: "zh" | "en";
  onOpenQuestion: (questionId: string) => void;
};

export function ChallengeMvpProgressPanel({
  teamId,
  lang: langProp,
  onOpenQuestion,
}: ChallengeMvpProgressPanelProps) {
  // The inspector mount point cannot thread lang yet (claimed by another task);
  // self-serve the shell language and let an explicit prop win.
  const { lang: shellLang } = useShellI18n();
  const lang = langProp ?? shellLang;
  const zh = lang === "zh";
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
  const tokenUsageQuery = useQuery({
    queryKey: queryKeys.challengeCupTokenUsage(teamId),
    queryFn: () => fetchChallengeCupTokenUsage(teamId),
    enabled: Boolean(teamId.trim()),
    staleTime: 15_000,
    retry: false,
  });

  const [registerDialogOpen, setRegisterDialogOpen] = useState(false);

  const program = experimentStatusQuery.data?.[
    panelContract.programProjection.property as "competitionProgramProjection"
  ];
  const requiredDeepExperiments = program?.[
    panelContract.programProjection.requiredDeepExperimentsProperty as "requiredDeepExperiments"
  ] ?? [];
  const summary = questionStatusQuery.data?.summary;
  const results = summary?.validatedQuestionResults ?? [];
  const approvedDeepExperimentCount = requiredDeepExperiments.filter((item) => item.approved).length;

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
  const tokenRetry = (
    <VButton type="button" variant="secondary" onClick={() => void tokenUsageQuery.refetch()}>
      {zh ? "重试" : "Retry"}
    </VButton>
  );
  const jumpTargets: Array<{ id: string; label: string }> = [
    { id: "ch-cup-program", label: zh ? "比赛状态" : "Program" },
    { id: "ch-cup-submission", label: zh ? "提交就绪" : "Submission" },
    { id: "ch-cup-readiness", label: zh ? "目录就绪" : "Catalog gates" },
    { id: "ch-cup-batches", label: zh ? "真实批次" : "Real batches" },
    { id: "ch-cup-token", label: "Token" },
    { id: "ch-cup-catalog", label: zh ? "题目目录" : "Question catalog" },
    { id: "ch-cup-results", label: zh ? "单题结果" : "Question results" },
  ];

  return (
    <VSurface tone="panel" className={styles.root} data-vui="competition-program-progress-panel">
      <div className={styles.header}>
        <div>
          <div className={styles.eyebrow}>AI Research Program v2</div>
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

      <nav className={styles.jumpNav} aria-label={zh ? "进度分区跳转" : "Progress section jump"}>
        {jumpTargets.map((target) => (
          <a
            key={target.id}
            className={styles.jumpLink}
            href={`#${target.id}`}
            data-testid={`ch-cup-jump-${target.id}`}
          >
            {target.label}
          </a>
        ))}
      </nav>

      {experimentStatusQuery.isPending ? (
        <VStateSurface tone="loading" title={zh ? "读取比赛进度" : "Loading program progress"} className={styles.fill} />
      ) : experimentStatusQuery.isError ? (
        <VStateSurface tone="error" title={zh ? "比赛状态加载失败" : "Program status failed"} className={styles.fill} actions={programRetry}>
          {experimentStatusQuery.error instanceof Error ? experimentStatusQuery.error.message : String(experimentStatusQuery.error)}
        </VStateSurface>
      ) : program ? (
        <section id="ch-cup-program" className={`${styles.program} ${styles.anchor}`} aria-label={zh ? "比赛总合同" : "Program contract"}>
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

      <div id="ch-cup-submission" className={styles.anchor}>
        <ChallengeSubmissionReadinessPanel teamId={teamId} lang={lang} onOpenQuestion={onOpenQuestion} />
      </div>
      <div id="ch-cup-readiness" className={styles.anchor}>
        <ChallengeCatalogReadinessPanel teamId={teamId} lang={lang} />
      </div>
      <div id="ch-cup-batches" className={styles.anchor}>
        <ChallengeRealBatchControlPanel teamId={teamId} lang={lang} />
      </div>
      <div id="ch-cup-token" className={styles.anchor}>
        {tokenUsageQuery.isPending ? (
          <VStateSurface tone="loading" title={zh ? "读取 token 消耗" : "Loading token usage"} className={styles.fill} />
        ) : tokenUsageQuery.isError ? (
          <VStateSurface tone="error" title={zh ? "token 消耗加载失败" : "Token usage failed"} className={styles.fill} actions={tokenRetry}>
            {tokenUsageQuery.error instanceof Error ? tokenUsageQuery.error.message : String(tokenUsageQuery.error)}
          </VStateSurface>
        ) : isTokenUsageOverview(tokenUsageQuery.data) ? (
          <ChallengeTokenUsageStrip
            lang={lang}
            title={zh ? "Program token 消耗" : "Program token usage"}
            totalTokens={tokenUsageQuery.data.program.totalTokens}
            callCount={tokenUsageQuery.data.program.callCount}
            inputTokens={tokenUsageQuery.data.program.inputTokens}
            outputTokens={tokenUsageQuery.data.program.outputTokens}
          />
        ) : null}
      </div>
      <div id="ch-cup-catalog" className={styles.anchor}>
        <ChallengeCatalogOverview
          teamId={teamId}
          lang={lang}
          onOpenQuestion={onOpenQuestion}
        />
      </div>

      <section id="ch-cup-results" className={`${styles.questionSection} ${styles.anchor}`} aria-label={zh ? "单题结果" : "Question results"}>
        <div className={styles.sectionHeader}>
          <strong>{zh ? "单题结果与审核" : "Question results"}</strong>
          <div className={styles.actions}>
            {summary ? <span>{zh ? `已验证 ${summary.validatedQuestionCount}` : `${summary.validatedQuestionCount} validated`}</span> : null}
            {questionStatusQuery.isSuccess ? (
              <VButton
                type="button"
                variant="secondary"
                density="compact"
                data-testid="challenge-question-register-entry"
                onPress={() => setRegisterDialogOpen(true)}
              >
                {zh ? "登记题目 / 发布产出" : "Register question / publish"}
              </VButton>
            ) : null}
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

      {questionStatusQuery.isSuccess && registerDialogOpen ? (
        <ChallengeQuestionRegisterDialog
          teamId={teamId}
          initialMode="register"
          onClose={() => setRegisterDialogOpen(false)}
          onOpenQuestion={(questionId) => {
            setRegisterDialogOpen(false);
            onOpenQuestion(questionId);
          }}
          lang={lang}
        />
      ) : null}

    </VSurface>
  );
}
