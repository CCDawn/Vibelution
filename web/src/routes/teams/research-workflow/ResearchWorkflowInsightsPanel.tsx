import { VEmptyState, VPanelHeader, VSurface } from "../../../components/vui";
import type { ResearchWorkflowInsights } from "./useResearchWorkflowInsights";
import styles from "./ResearchWorkflowInsightsPanel.styles";

function total(values: Record<string, number> | undefined): number {
  return Object.values(values ?? {}).reduce((sum, value) => sum + value, 0);
}

export function ResearchWorkflowInsightsPanel({
  insights,
  lang = "zh",
}: {
  insights: ResearchWorkflowInsights;
  lang?: "zh" | "en";
}) {
  const isZh = lang === "zh";
  const latestBudget = insights.budget?.budgetLedgers.at(-1);
  const latestPortfolio = insights.hypotheses?.hypothesisPortfolios.at(-1);
  const latestCampaign = insights.campaigns?.experimentCampaigns.at(-1);
  const latestEvaluation = insights.evaluation?.competitionEvaluations.at(-1);
  const summary = insights.ledger?.summary;

  if (insights.loading) {
    return (
      <VSurface
        tone="panel"
        className={styles.loading}
        ariaLabel={isZh ? "加载科研效能" : "Loading research insights"}
      >
        <span />
      </VSurface>
    );
  }
  if (insights.error) {
    return (
      <VSurface tone="panel" className={styles.error} role="alert">
        {insights.error}
      </VSurface>
    );
  }
  if (!summary && !latestBudget && !latestPortfolio && !latestCampaign && !latestEvaluation) {
    return (
      <VEmptyState
        title={isZh ? "暂无科研效能记录" : "No research insights yet"}
        className={styles.empty}
      />
    );
  }

  return (
    <VSurface tone="panel" className={styles.root} data-vui="research-workflow-insights">
      <VPanelHeader title={isZh ? "科研效能" : "Research insights"} headingLevel={3} />
      <dl className={styles.metrics}>
        <div className={styles.metric} title={isZh ? "Claim 与证据链覆盖" : "Claims with evidence coverage"}>
          <dt className={styles.label}>{isZh ? "证据" : "Evidence"}</dt>
          <dd className={styles.value}>{summary?.claimEvidenceCount ?? 0}</dd>
        </div>
        <div className={styles.metric} title={isZh ? "已验证 Artifact 数量" : "Verified artifacts"}>
          <dt className={styles.label}>{isZh ? "产物" : "Artifacts"}</dt>
          <dd className={styles.value}>{summary?.artifactCount ?? 0}</dd>
        </div>
        <div className={styles.metric} title={latestBudget?.stopReason || (isZh ? "预算正常" : "Budget healthy")}>
          <dt className={styles.label}>{isZh ? "剩余预算" : "Budget left"}</dt>
          <dd className={styles.value}>{total(latestBudget?.remaining)}</dd>
        </div>
        <div className={styles.metric} title={isZh ? "当前有界候选组合" : "Current bounded candidate set"}>
          <dt className={styles.label}>{isZh ? "假设" : "Hypotheses"}</dt>
          <dd className={styles.value}>{latestPortfolio?.candidates.length ?? 0}</dd>
        </div>
      </dl>
      <dl className={styles.detail}>
        <dt className={styles.label}>{isZh ? "实验阶段" : "Experiment stage"}</dt>
        <dd className={styles.detailValue}>{latestCampaign?.stage || "—"}</dd>
        <dt className={styles.label}>{isZh ? "复现" : "Replication"}</dt>
        <dd className={styles.detailValue}>{latestCampaign ? `${latestCampaign.replicationCount}/${latestCampaign.seedSet.length}` : "—"}</dd>
        <dt className={styles.label}>{isZh ? "竞赛评价" : "Competition evaluation"}</dt>
        <dd className={styles.detailValue}>{latestEvaluation?.rubricVersion || "—"}</dd>
        <dt className={styles.label}>{isZh ? "阻塞警告" : "Blocking warnings"}</dt>
        <dd className={latestEvaluation?.blockingWarnings.length ? styles.blocking : styles.detailValue}>
          {latestEvaluation?.blockingWarnings.length ?? 0}
        </dd>
      </dl>
    </VSurface>
  );
}
