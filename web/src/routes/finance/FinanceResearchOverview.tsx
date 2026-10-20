import type { AssistantConversationTurn } from "../../api/types";
import type { StockIdentity } from "../../api/financialMarket";
import { BookOpen, ExternalLink, FileText } from "lucide-react";
import { VButton, VRouteLinkButton } from "../../components/vui";
import type { FinancialSessionView } from "./FinancialResearchBridge";
import { financeResearchProcessSummary } from "./FinanceResearchProcess";
import type { ReportCitation, StockResearchReport } from "./stockResearchModel";
import styles, { researchStatusDotClass } from "./FinanceResearchOverview.styles";

export function FinanceResearchOverview({ view, activeTurn, stock, report, topicTitle, zh, onCitation, onOpenLibrary, onOpenProcess, onOpenAttention, onNewResearch }: {
  view: FinancialSessionView | null;
  activeTurn: AssistantConversationTurn | null;
  stock: StockIdentity;
  report: StockResearchReport | null;
  topicTitle?: string;
  zh: boolean;
  onCitation: (citation: ReportCitation) => void;
  onOpenLibrary: () => void;
  onOpenProcess: () => void;
  onOpenAttention: () => void;
  onNewResearch?: () => void;
}) {
  const summary = financeResearchProcessSummary(view, activeTurn, zh);
  const attention = summary.reviewTools.length > 0 || summary.failedTools.length > 0;
  const references = report?.citations ?? [];

  return (
    <div className={styles.body} data-finance-research-overview>
      <section className={styles.identity} aria-label={topicTitle ? (zh ? "当前主题" : "Current topic") : (zh ? "当前股票" : "Current stock")}>
        <span className={styles.eyebrow}>{topicTitle ? (zh ? "当前主题" : "Current topic") : (zh ? "当前股票" : "Current stock")}</span>
        <strong className={styles.name} title={topicTitle || `${stock.name} · ${stock.ticker}`}>{topicTitle || `${stock.name} · ${stock.ticker}`}</strong>
        {!topicTitle ? <p className={styles.meta}>{stock.market}</p> : null}
      </section>

      {!view?.messages?.length && onNewResearch ? <section className={styles.start} aria-label={zh ? "开始使用" : "Get started"}><h2 className={styles.startTitle}>{zh ? "从一只股票开始" : "Start with a stock"}</h2><p className={styles.empty}>{zh ? "选择股票和研究范围，发起研究后查看真实执行过程、来源资料与研究报告。" : "Choose a stock and scope, then follow activity, sources and the report."}</p><VButton variant="primary" onPress={onNewResearch}>{zh ? "设置并开始研究" : "Set up research"}</VButton></section> : null}

      <section className={styles.section} aria-label={zh ? "研究状态" : "Research status"}>
        <h2 className={styles.sectionTitle}>{zh ? "研究状态" : "Research status"}</h2>
        <div className={styles.statusRow} role="status" title={summary.status}>
          <span className={`${styles.statusDot} ${researchStatusDotClass(summary.state, attention)}`} aria-hidden="true" />
          <strong className={styles.statusText}>{summary.status}</strong>
        </div>
        {summary.reviewTools.length || summary.failedTools.length ? <div className={styles.counts}>
          {summary.reviewTools.length ? <VButton variant="secondary" className={styles.count} onPress={onOpenAttention} aria-label={zh ? `筛选 ${summary.reviewTools.length} 项待核验工具事件` : `Filter ${summary.reviewTools.length} tool events needing review`}>
            {zh ? `待核验 ${summary.reviewTools.length}` : `Review ${summary.reviewTools.length}`}
          </VButton> : null}
          {summary.failedTools.length ? <VButton variant="secondary" className={styles.count} onPress={onOpenAttention} aria-label={zh ? `筛选 ${summary.failedTools.length} 项失败工具事件` : `Filter ${summary.failedTools.length} failed tool events`}>
            {zh ? `失败 ${summary.failedTools.length}` : `Failed ${summary.failedTools.length}`}
          </VButton> : null}
        </div> : null}
        <VButton variant="ghost" className={styles.action} onPress={onOpenProcess}>{zh ? "查看研究过程" : "View research process"}</VButton>
      </section>

      <section className={styles.section} aria-label={zh ? "当前研究引用与资料" : "Current report references and materials"}>
        <h2 className={styles.sectionTitle}>{zh ? "当前研究引用" : "Current report references"}</h2>
        {references.length ? <div className={styles.references}>
          {references.map((citation) => <VButton key={`${citation.url}#${citation.page}`} variant="ghost" className={styles.reference} icon={<FileText size={14} aria-hidden="true" />} onPress={() => onCitation(citation)} title={`${citation.label}${citation.page ? ` · ${zh ? `第${citation.page}页` : `p. ${citation.page}`}` : ""}`}>
            <span className={styles.referenceText}>{citation.page ? `${citation.label} · ${zh ? `第${citation.page}页` : `p. ${citation.page}`}` : citation.label}</span>
          </VButton>)}
        </div> : <p className={styles.empty}>{report ? (zh ? "报告未列出引用" : "No sources listed in this report") : (zh ? "当前研究暂无已完成报告引用" : "No completed report references for this research")}</p>}
        <div className={styles.actions}>
          <VButton variant="secondary" className={styles.action} icon={<BookOpen size={14} aria-hidden="true" />} onPress={onOpenLibrary}>
            {zh ? "查看财报资料" : "Browse report library"}
          </VButton>
          {references[0] ? <VRouteLinkButton to={`${references[0].url}${references[0].page ? `#page=${references[0].page}` : ""}`} target="_blank" rel="noopener noreferrer" reloadDocument className={styles.action} icon={<ExternalLink size={14} aria-hidden="true" />}>
            {zh ? "打开首条原文" : "Open first source"}
          </VRouteLinkButton> : null}
        </div>
      </section>
    </div>
  );
}
