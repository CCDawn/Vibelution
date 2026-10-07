import styles from "./FinanceResearchReport.styles";
import { useEffect, useMemo, useState } from "react";
import { FileText } from "lucide-react";
import { LazyConversationMarkdownRenderer } from "../../components/conversation/LazyConversationMarkdownRenderer";
import { VButton, VStateSurface, VSurface, VTabs } from "../../components/vui";
import { researchTablePreview, stockResearchReportFromText, type ReportCitation, type ResearchDepth, type ResearchScope, type StockResearchReport } from "./stockResearchModel";
import { FinanceReportExport } from "./FinanceReportExport";
import { fetchFinancialReportText } from "../../api/financialReports";

const researchScopeLabels: Record<ResearchScope, { zh: string; en: string }> = {
  comprehensive: { zh: "综合研究", en: "Comprehensive" },
  financial: { zh: "财报分析", en: "Financials" },
  events: { zh: "事件分析", en: "Events" },
  risk: { zh: "风险评估", en: "Risks" },
};
const researchDepthLabels: Record<ResearchDepth, { zh: string; en: string }> = {
  brief: { zh: "快速", en: "Quick" },
  basic: { zh: "基础", en: "Basic" },
  standard: { zh: "标准", en: "Standard" },
  detailed: { zh: "深入", en: "Detailed" },
  exhaustive: { zh: "全面", en: "Comprehensive" },
};

export function FinanceResearchReport({ report: projectedReport, assistantAgentId, sessionId, zh, onCitation, onResearch, busy = false, summaryOnly = false }: { report: StockResearchReport | null; assistantAgentId: string; sessionId: string; zh: boolean; onCitation: (citation: ReportCitation) => void; onResearch: () => void; busy?: boolean; summaryOnly?: boolean }) {
  const [tab, setTab] = useState("all");
  const [verified, setVerified] = useState<{ key: string; text?: string; error?: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const turnId = projectedReport?.turnId ?? "";
  const reportKey = JSON.stringify([assistantAgentId, sessionId, turnId]);
  useEffect(() => setTab("all"), [reportKey]);
  useEffect(() => {
    if (!turnId) return;
    const controller = new AbortController();
    setVerified({ key: reportKey });
    void fetchFinancialReportText({ assistantAgentId, sessionId, turnId }, { signal: controller.signal }).then(
      (text) => { if (!controller.signal.aborted) setVerified({ key: reportKey, text }); },
      (error: unknown) => { if (!controller.signal.aborted) setVerified({ key: reportKey, error: error instanceof Error ? error.message : "Report unavailable" }); },
    );
    return () => controller.abort();
  }, [assistantAgentId, sessionId, turnId, reportKey, retry]);
  const report = useMemo(() => projectedReport && verified?.key === reportKey && verified.text
    ? stockResearchReportFromText(projectedReport, verified.text) : null, [projectedReport, reportKey, verified]);
  if (!projectedReport) return <VStateSurface density="compact" tone={busy ? "loading" : "empty"} busy={busy} title={busy ? (zh ? "研究进行中" : "Research running") : (zh ? "这只股票还没有研究报告" : "No report for this stock")} actions={!busy ? <VButton variant="secondary" onPress={onResearch}>{zh ? "发起研究" : "Start research"}</VButton> : undefined}>{busy ? (zh ? "研究过程见右侧，完成后显示报告。" : "Follow progress on the right. The report appears after completion.") : undefined}</VStateSurface>;
  if (!report) {
    const error = verified?.key === reportKey ? verified.error : undefined;
    return <VStateSurface density="compact" tone={error ? "error" : "loading"} busy={!error} title={error ? (zh ? "报告读取失败" : "Report unavailable") : (zh ? "核验报告" : "Verifying report")} actions={error ? <VButton variant="secondary" onPress={() => setRetry((value) => value + 1)}>{zh ? "重试" : "Retry"}</VButton> : undefined}>{error}</VStateSurface>;
  }
  const selected = report.sections.find((section) => section.id === tab);
  const parameters = report.researchParameters;
  const parameterText = (zhLabel: string, enLabel: string, value: string) => `${zh ? zhLabel : enLabel}${zh ? "：" : ": "}${value}`;
  const parameterItems = [
    parameters?.stock ? { id: "stock", text: parameterText("标的", "Stock", `${parameters.stock.name} ${parameters.stock.ticker}`) } : null,
    parameters?.analysisDate ? { id: "date", text: parameterText("分析日期", "As of", parameters.analysisDate) } : null,
    parameters?.reportPeriod ? { id: "period", text: parameterText("报告期", "Report period", parameters.reportPeriod) } : null,
    parameters?.scope && researchScopeLabels[parameters.scope] ? { id: "scope", text: parameterText("范围", "Scope", researchScopeLabels[parameters.scope][zh ? "zh" : "en"]) } : null,
    parameters?.depth && researchDepthLabels[parameters.depth] ? { id: "depth", text: parameterText("深度", "Depth", researchDepthLabels[parameters.depth][zh ? "zh" : "en"]) } : null,
  ].filter((item): item is { id: string; text: string } => item !== null);
  return <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "研究报告" : "Research report"} data-finance-research-report>
    <div className={styles.heading}><strong className={styles.title}><FileText size={15} />{zh ? (summaryOnly ? "研究简报" : "研究报告") : (summaryOnly ? "Research brief" : "Research report")}</strong><div className={styles.actions}><span className={styles.timestamp}>{report.timestamp ? new Date(report.timestamp).toLocaleDateString("zh-CN") : ""}{busy ? (zh ? " · 上次结果" : " · Previous result") : ""}</span><FinanceReportExport assistantAgentId={assistantAgentId} sessionId={sessionId} turnId={report.turnId} zh={zh} /></div></div>
    {parameterItems.length ? <div className={styles.parameters} role="group" aria-label={zh ? "本次研究参数" : "Research parameters"} data-finance-research-metadata>{parameterItems.map((item) => <span key={item.id} className={styles.parameter}>{item.text}</span>)}</div> : null}
    {summaryOnly && report.summary ? <p className={styles.summary}>{report.summary}</p> : null}
    {summaryOnly && !report.summary && researchTablePreview(report.text) ? <div className={styles.body}><LazyConversationMarkdownRenderer content={researchTablePreview(report.text)} language={zh ? "zh" : "en"} /></div> : null}
    {!summaryOnly ? <>
      {report.sections.length ? <VTabs value={tab} onValueChange={setTab} aria-label={zh ? "报告章节" : "Report chapters"} items={[{ id: "all", label: zh ? "完整报告" : "Full report" }, ...report.sections.map((section) => ({ id: section.id, label: section.title }))]} className={styles.chapters} /> : null}
      <div className={styles.body} data-finance-report-body><LazyConversationMarkdownRenderer content={selected?.text ?? report.text} language={zh ? "zh" : "en"} /></div>
    </> : <VButton variant="secondary" onPress={onResearch}>{zh ? "查看报告与追问" : "Read and follow up"}</VButton>}
    {report.citations.length ? <div className={styles.citations}><span className={styles.timestamp}>{zh ? "引用" : "Sources"}</span>{report.citations.map((citation) => <VButton key={`${citation.url}#${citation.page}`} variant="ghost" density="compact" onPress={() => onCitation(citation)}>{citation.label}</VButton>)}</div> : null}
  </VSurface>;
}
