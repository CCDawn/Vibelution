import styles from "./FinanceResearchReport.styles";
import { useEffect, useState } from "react";
import { Download, FileText } from "lucide-react";
import { LazyConversationMarkdownRenderer } from "../../components/conversation/LazyConversationMarkdownRenderer";
import { VButton, VStateSurface, VSurface, VTabs } from "../../components/vui";
import { researchTablePreview, type ReportCitation, type StockResearchReport } from "./stockResearchModel";

export function FinanceResearchReport({ report, zh, onCitation, onResearch, busy = false, summaryOnly = false }: { report: StockResearchReport | null; zh: boolean; onCitation: (citation: ReportCitation) => void; onResearch: () => void; busy?: boolean; summaryOnly?: boolean }) {
  const [tab, setTab] = useState("all");
  useEffect(() => setTab("all"), [report?.turnId]);
  if (!report) return <VStateSurface density="compact" tone={busy ? "loading" : "empty"} busy={busy} title={busy ? (zh ? "研究进行中" : "Research running") : (zh ? "这只股票还没有研究报告" : "No report for this stock")} actions={!busy ? <VButton variant="secondary" onPress={onResearch}>{zh ? "发起研究" : "Start research"}</VButton> : undefined}>{busy ? (zh ? "研究过程见右侧，完成后显示报告。" : "Follow progress on the right. The report appears after completion.") : undefined}</VStateSurface>;
  function download() {
    if (!report) return;
    const blob = new Blob([report.text], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url; link.download = `stock-research-${report.timestamp.slice(0, 10) || "report"}.md`;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const selected = report.sections.find((section) => section.id === tab);
  return <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "研究报告" : "Research report"} data-finance-research-report>
    <div className={styles.heading}><strong className={styles.title}><FileText size={15} />{zh ? (summaryOnly ? "研究简报" : "研究报告") : (summaryOnly ? "Research brief" : "Research report")}</strong><div className={styles.actions}><span className={styles.timestamp}>{report.timestamp ? new Date(report.timestamp).toLocaleDateString("zh-CN") : ""}{busy ? (zh ? " · 上次结果" : " · Previous result") : ""}</span><VButton variant="ghost" onPress={download} icon={<Download size={14} />}>{zh ? "导出" : "Export"}</VButton></div></div>
    {summaryOnly && report.summary ? <p className={styles.summary}>{report.summary}</p> : null}
    {summaryOnly && !report.summary && researchTablePreview(report.text) ? <div className={styles.body}><LazyConversationMarkdownRenderer content={researchTablePreview(report.text)} language={zh ? "zh" : "en"} /></div> : null}
    {!summaryOnly ? <>
      {report.sections.length ? <VTabs value={tab} onValueChange={setTab} aria-label={zh ? "报告章节" : "Report chapters"} items={[{ id: "all", label: zh ? "完整报告" : "Full report" }, ...report.sections.map((section) => ({ id: section.id, label: section.title }))]} className={styles.chapters} /> : null}
      <div className={styles.body} data-finance-report-body><LazyConversationMarkdownRenderer content={selected?.text ?? report.text} language={zh ? "zh" : "en"} /></div>
    </> : <VButton variant="secondary" onPress={onResearch}>{zh ? "查看报告与追问" : "Read and follow up"}</VButton>}
    {report.citations.length ? <div className={styles.citations}><span className={styles.timestamp}>{zh ? "引用" : "Sources"}</span>{report.citations.map((citation) => <VButton key={`${citation.url}#${citation.page}`} variant="ghost" density="compact" onPress={() => onCitation(citation)}>{citation.label}</VButton>)}</div> : null}
  </VSurface>;
}
