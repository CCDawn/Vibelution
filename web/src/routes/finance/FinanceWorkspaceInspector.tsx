import type { StockIdentity, StockSnapshot } from "../../api/financialMarket";
import type { FinancialReportSummary } from "../../api/types/financialReports";
import { VSurface, VStateSurface } from "../../components/vui";
import styles from "./FinanceWorkspaceInspector.styles";

export function FinanceWorkspaceInspector({ area, title, stock, snapshot, report, selection, preparing, date, zh }: {
  area: string; title: string; stock: StockIdentity; snapshot?: StockSnapshot;
  report: FinancialReportSummary | null; selection: { sessionId: string; turnId: string } | null; preparing: boolean; date: string; zh: boolean;
}) {
  if (area === "reports" || area === "review") return report ? <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "当前报告" : "Selected report"}>
    <strong className={styles.title} title={report.title}>{report.title}</strong>
    <p className={styles.line} title={report.sessionTitle}>{report.sessionTitle}</p>
    <p className={styles.line}>{[report.ticker, report.marketCode, report.completedAt ? new Date(report.completedAt).toLocaleString(zh ? "zh-CN" : "en-US") : ""].filter(Boolean).join(" · ")}</p>
    <p className={styles.line}>{zh ? `${report.chars.toLocaleString()} 字` : `${report.chars.toLocaleString()} characters`}</p>
  </VSurface> : selection ? <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "当前报告" : "Selected report"}><strong className={styles.title}>{zh ? "历史报告" : "Historical report"}</strong><p className={styles.line} title={selection.turnId}>{zh ? "轮次" : "Turn"} · {selection.turnId}</p></VSurface> : <VStateSurface density="compact" tone="info" title={zh ? "选择报告" : "Select a report"} />;
  if (["workspace", "watchlist", "screen"].includes(area)) return <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "当前股票" : "Selected stock"}>
    <strong className={styles.title} title={`${stock.name} · ${stock.ticker}`}>{stock.name} · {stock.ticker}</strong>
    <p className={styles.line}>{stock.market}</p>
    {preparing ? <p className={styles.line}>{zh ? `分析日期 ${date}` : `As of ${date}`}</p> : null}
    {snapshot?.stock.symbol === stock.symbol ? <p className={styles.line}>{snapshot.source} · {snapshot.stock.timestamp}</p> : null}
  </VSurface>;
  return <VStateSurface density="compact" tone="info" title={title} />;
}
