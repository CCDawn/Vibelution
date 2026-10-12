import { useEffect, useState } from "react";
import { FilePlus2 } from "lucide-react";
import { fetchFinancialReportText, type FinancialReportExportTarget } from "../../api/financialReports";
import { LazyConversationMarkdownRenderer } from "../../components/conversation/LazyConversationMarkdownRenderer";
import { VButton, VStateSurface } from "../../components/vui";
import styles from "./FinanceGroundedReport.styles";

type ReportTarget = Omit<FinancialReportExportTarget, "format">;

/** Completed answers are immutable; keep the exact identity and reject late reads. */
export function useGroundedFinancialReport({ assistantAgentId, sessionId, turnId }: ReportTarget) {
  const key = JSON.stringify([assistantAgentId, sessionId, turnId]);
  const [result, setResult] = useState<{ key: string; text?: string; error?: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!assistantAgentId || !sessionId || !turnId) return;
    const controller = new AbortController();
    setResult({ key });
    void fetchFinancialReportText({ assistantAgentId, sessionId, turnId }, { signal: controller.signal }).then(
      (text) => { if (!controller.signal.aborted) setResult({ key, text }); },
      (error: unknown) => { if (!controller.signal.aborted) setResult({ key, error: error instanceof Error ? error.message : "Report unavailable" }); },
    );
    return () => controller.abort();
  }, [assistantAgentId, sessionId, turnId, key, attempt]);
  return {
    key,
    text: result?.key === key ? result.text : undefined,
    error: result?.key === key ? result.error : undefined,
    retry: () => setAttempt((value) => value + 1),
  };
}

export function FinanceReportReadState({ read, zh, onResumeResearch }: { read: ReturnType<typeof useGroundedFinancialReport>; zh: boolean; onResumeResearch?: () => void }) {
  const incomplete = Boolean(read.error && /研究尚未成功完成|该轮内容不是研究报告|没有已提交的最终答案|已停止的研究不能导出/.test(read.error));
  return <VStateSurface density="compact" tone={read.error ? "error" : "loading"} busy={!read.error}
    title={incomplete ? (zh ? "尚无可导出的研究报告" : "No exportable report yet") : read.error ? (zh ? "报告读取失败" : "Report unavailable") : (zh ? "读取核验正文" : "Loading grounded report")}
    actions={read.error ? <>{onResumeResearch ? <VButton variant="secondary" onPress={onResumeResearch}>{zh ? "返回研究对话" : "Return to research"}</VButton> : null}<VButton variant="secondary" onPress={read.retry}>{zh ? "重试" : "Retry"}</VButton></> : undefined}>{incomplete ? (zh ? "会话结束不代表报告已成功生成。可在原对话继续研究，明确要求生成完整研究报告。" : "A finished conversation may not contain a completed report. Continue in the original conversation and request a full research report.") : read.error}</VStateSurface>;
}

export function FinanceReportEvidenceNotice({ text, originalText, zh, onSupplementEvidence }: { text: string; originalText: string; zh: boolean; onSupplementEvidence?: () => void }) {
  const missingCount = (value: string) => value.split("没有这一项").length - 1;
  if (missingCount(text) <= missingCount(originalText)) return null;
  return <VStateSurface density="compact" tone="unavailable" title={<span className={styles.noticeTitle}>
    <span className={styles.noticeText}>{zh ? "部分数字未通过核验" : "Some figures lack verified evidence"}</span>
    {onSupplementEvidence ? <VButton density="compact" variant="ghost" className={styles.noticeAction} icon={<FilePlus2 size={14} />} title={zh ? "在原会话添加来源或附件后追问" : "Add sources or attachments and follow up in the original session"} onPress={onSupplementEvidence}>{zh ? "补充证据" : "Add evidence"}</VButton> : null}
  </span>} />;
}

export function FinanceGroundedReportBody({ target, originalText, zh, onSupplementEvidence }: { target: ReportTarget; originalText: string; zh: boolean; onSupplementEvidence?: () => void }) {
  const read = useGroundedFinancialReport(target);
  if (!read.text) return <FinanceReportReadState read={read} zh={zh} />;
  return <div data-finance-grounded-report-body>
    <FinanceReportEvidenceNotice text={read.text} originalText={originalText} zh={zh} onSupplementEvidence={onSupplementEvidence} />
    <LazyConversationMarkdownRenderer content={read.text} language={zh ? "zh" : "en"} />
  </div>;
}
