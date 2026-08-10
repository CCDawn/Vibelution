import { VEmptyState, VPanelHeader, VSurface } from "../../../components/vui";
import type { ResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import styles from "./ResearchWorkflowInsightsPanel.styles";

function total(values: Record<string, number> | undefined): number {
  return Object.values(values ?? {}).reduce((sum, value) => sum + value, 0);
}

export function ResearchWorkflowInsightsPanel({
  insights,
}: {
  insights: ResearchWorkflowInsights;
}) {
  const latestBudget = insights.budget?.budgetLedgers.at(-1);
  const latestPortfolio = insights.hypotheses?.hypothesisPortfolios.at(-1);
  const latestCampaign = insights.campaigns?.experimentCampaigns.at(-1);
  const latestEvaluation = insights.evaluation?.competitionEvaluations.at(-1);
  const summary = insights.ledger?.summary;

  if (insights.loading) {
    return <VSurface tone="panel" className={styles.loading} ariaLabel="加载科研效能"><span /></VSurface>;
  }
  if (insights.error) {
    return (
      <VSurface tone="panel" className={styles.error} role="alert">
        {insights.error}
      </VSurface>
    );
  }
  if (!summary && !latestBudget && !latestPortfolio && !latestCampaign && !latestEvaluation) {
    return <VEmptyState title="暂无科研效能记录" className={styles.empty} />;
  }

  return (
    <VSurface tone="panel" className={styles.root} data-vui="research-workflow-insights">
      <VPanelHeader title="科研效能" headingLevel={3} />
      <dl className={styles.metrics}>
        <div className={styles.metric} title="Claim 与证据链覆盖">
          <dt className={styles.label}>证据</dt>
          <dd className={styles.value}>{summary?.claimEvidenceCount ?? 0}</dd>
        </div>
        <div className={styles.metric} title="已验证 Artifact 数量">
          <dt className={styles.label}>产物</dt>
          <dd className={styles.value}>{summary?.artifactCount ?? 0}</dd>
        </div>
        <div className={styles.metric} title={latestBudget?.stopReason || "预算正常"}>
          <dt className={styles.label}>剩余预算</dt>
          <dd className={styles.value}>{total(latestBudget?.remaining)}</dd>
        </div>
        <div className={styles.metric} title="当前有界候选组合">
          <dt className={styles.label}>假设</dt>
          <dd className={styles.value}>{latestPortfolio?.candidates.length ?? 0}</dd>
        </div>
      </dl>
      <dl className={styles.detail}>
        <dt className={styles.label}>实验阶段</dt>
        <dd className={styles.detailValue}>{latestCampaign?.stage || "—"}</dd>
        <dt className={styles.label}>复现</dt>
        <dd className={styles.detailValue}>{latestCampaign ? `${latestCampaign.replicationCount}/${latestCampaign.seedSet.length}` : "—"}</dd>
        <dt className={styles.label}>竞赛评价</dt>
        <dd className={styles.detailValue}>{latestEvaluation?.rubricVersion || "—"}</dd>
        <dt className={styles.label}>阻塞警告</dt>
        <dd className={latestEvaluation?.blockingWarnings.length ? styles.blocking : styles.detailValue}>
          {latestEvaluation?.blockingWarnings.length ?? 0}
        </dd>
      </dl>
    </VSurface>
  );
}
