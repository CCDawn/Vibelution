import { useEffect, useRef, useState } from "react";
import { Download, FileJson, FileText, Printer } from "lucide-react";
import { downloadFinancialReportExport, downloadFinancialReportPrintHtml, printFinancialReportExport, type FinancialReportFormat } from "../../api/financialReports";
import { VButton, VDropdownMenu } from "../../components/vui";
import styles from "./FinanceReportExport.styles";

type FinanceReportExportProps = {
  assistantAgentId: string;
  sessionId: string;
  turnId: string;
  zh: boolean;
};

type ReportExportAction = FinancialReportFormat | "print-html";

export function FinanceReportExport(props: FinanceReportExportProps) {
  const identityKey = JSON.stringify([props.assistantAgentId, props.sessionId, props.turnId]);
  return <FinanceReportExportAction key={identityKey} {...props} />;
}

function FinanceReportExportAction({ assistantAgentId, sessionId, turnId, zh }: FinanceReportExportProps) {
  const [exporting, setExporting] = useState<ReportExportAction | null>(null);
  const [exportError, setExportError] = useState("");
  const [pdfFallbackAvailable, setPdfFallbackAvailable] = useState(false);
  const activeAttempt = useRef<symbol | null>(null);
  const activeController = useRef<AbortController | null>(null);

  useEffect(() => () => activeController.current?.abort(), []);

  async function exportReport(action: ReportExportAction) {
    if (activeAttempt.current) return;
    const attempt = Symbol("financial-report-export");
    const controller = new AbortController();
    activeAttempt.current = attempt;
    activeController.current = controller;
    setExportError("");
    setPdfFallbackAvailable(false);
    setExporting(action);
    try {
      const format: FinancialReportFormat = action === "print-html" ? "pdf" : action;
      const target = { assistantAgentId, sessionId, turnId, format };
      const options = { signal: controller.signal };
      if (action === "print-html") await downloadFinancialReportPrintHtml(target, options);
      else if (format === "pdf") await printFinancialReportExport(target, options);
      else await downloadFinancialReportExport(target, options);
    } catch (error) {
      if (activeAttempt.current === attempt && !controller.signal.aborted) {
        setPdfFallbackAvailable(action === "pdf-file");
        setExportError(error instanceof Error && error.message
          ? error.message
          : (zh ? "导出失败，请稍后重试" : "Export failed. Try again."));
      }
    } finally {
      if (activeAttempt.current === attempt && !controller.signal.aborted) {
        activeAttempt.current = null;
        activeController.current = null;
        setExporting(null);
      }
    }
  }

  return <div className={styles.action} data-finance-report-export>
    <VDropdownMenu
      align="end"
      aria-label={zh ? "导出研究报告" : "Export research report"}
      trigger={<VButton variant="ghost" isPending={exporting !== null} isDisabled={exporting !== null || !assistantAgentId || !sessionId || !turnId} icon={<Download size={14} />}>{zh ? "导出" : "Export"}</VButton>}
      items={[
        { id: "pdf-file", icon: <FileText size={14} />, label: "PDF (.pdf)", disabled: exporting !== null, onSelect: () => void exportReport("pdf-file") },
        { id: "markdown", icon: <FileText size={14} />, label: "Markdown (.md)", disabled: exporting !== null, onSelect: () => void exportReport("markdown") },
        { id: "json", icon: <FileJson size={14} />, label: "JSON (.json)", disabled: exporting !== null, onSelect: () => void exportReport("json") },
        { id: "docx", icon: <FileText size={14} />, label: "Word (.docx)", disabled: exporting !== null, onSelect: () => void exportReport("docx") },
        { id: "pdf", icon: <Printer size={14} />, label: zh ? "打印" : "Print", disabled: exporting !== null, onSelect: () => void exportReport("pdf") },
      ]}
    />
    {exportError ? <p className={styles.error} role="alert">{exportError}</p> : null}
    {pdfFallbackAvailable ? <VButton variant="ghost" isDisabled={exporting !== null} onPress={() => void exportReport("print-html")}>{zh ? "下载打印版" : "Download printable version"}</VButton> : null}
  </div>;
}
