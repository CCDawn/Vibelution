import type { StockIdentity, StockSnapshot } from "../../api/financialMarket";
import type { FinancialReportSummary } from "../../api/types/financialReports";
import { FileText } from "lucide-react";
import { VButton, VSurface, VStateSurface } from "../../components/vui";
import type { ReportCitation } from "./stockResearchModel";
import styles from "./FinanceWorkspaceInspector.styles";

export function FinanceWorkspaceInspector({ area, title, topicTitle, stock, snapshot, report, selection, preparing, date, zh, reportCitations, onCitation }: {
  area: string; title: string; topicTitle?: string; stock: StockIdentity; snapshot?: StockSnapshot;
  report: FinancialReportSummary | null; selection: { sessionId: string; turnId: string } | null; preparing: boolean; date: string; zh: boolean;
  reportCitations?: ReportCitation[]; onCitation?: (citation: ReportCitation) => void;
}) {
  const sources = reportCitations && onCitation ? <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "报告引用" : "Report sources"}>
    <strong className={styles.title}>{zh ? "报告引用" : "Report sources"}</strong>
    {reportCitations.length ? <div className={styles.sources}>{reportCitations.map(citation => <VButton key={`${citation.url}#${citation.page}`} variant="ghost" density="compact" className={styles.sourceButton} title={`${citation.label} ${citation.page} · ${citation.url}`} icon={<FileText size={14} aria-hidden="true" />} onPress={() => onCitation(citation)}>{citation.page ? `${citation.label} · ${zh ? "第" : "p. "}${citation.page}${zh ? "页" : ""}` : citation.label}</VButton>)}</div> : <p className={styles.line}>{zh ? "报告未列出引用" : "No sources listed in this report"}</p>}
  </VSurface> : null;
  if (area === "workspace" && topicTitle) return <><VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "当前研究主题" : "Research topic"}><strong className={styles.title} title={topicTitle}>{topicTitle}</strong></VSurface>{sources}</>;
  if (area === "reports" || area === "review") return report ? <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "当前报告" : "Selected report"}>
    <strong className={styles.title} title={report.title}>{report.title}</strong>
    <p className={styles.line} title={report.sessionTitle}>{report.sessionTitle}</p>
    <p className={styles.line}>{[report.ticker, report.marketCode, report.completedAt ? new Date(report.completedAt).toLocaleString(zh ? "zh-CN" : "en-US") : ""].filter(Boolean).join(" · ")}</p>
    <p className={styles.line}>{zh ? `${report.chars.toLocaleString()} 字` : `${report.chars.toLocaleString()} characters`}</p>
  </VSurface> : selection ? <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "当前报告" : "Selected report"}><strong className={styles.title}>{zh ? "历史报告" : "Historical report"}</strong><p className={styles.line} title={selection.turnId}>{zh ? "轮次" : "Turn"} · {selection.turnId}</p></VSurface> : <VStateSurface density="compact" tone="info" title={zh ? "选择报告" : "Select a report"} />;
  if (["workspace", "watchlist", "screen"].includes(area)) return <><VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "当前股票" : "Selected stock"}>
    <strong className={styles.title} title={`${stock.name} · ${stock.ticker}`}>{stock.name} · {stock.ticker}</strong>
    <p className={styles.line}>{stock.market}</p>
    {preparing ? <p className={styles.line}>{zh ? `分析日期 ${date}` : `As of ${date}`}</p> : null}
    {snapshot?.stock.symbol === stock.symbol ? <p className={styles.line}>{snapshot.source} · {snapshot.stock.timestamp}</p> : null}
  </VSurface>{sources}</>;
  return <VStateSurface density="compact" tone="info" title={title} />;
}
