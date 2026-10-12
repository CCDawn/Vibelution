import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { previewFinancialPdf, stageFinancialPdf } from "../../api/financialEvidence";
import { reviewKnowledgeSourceInbox } from "../../api/knowledge";
import type { FinancialPdfInput, FinancialPdfPreview, FinancialPdfStaged } from "../../api/types/financialEvidence";
import type { StockIdentity } from "../../api/financialMarket";
import { VButton, VCheckbox, VDialog, VInput, VRouteLinkButton, VStateSurface } from "../../components/vui";

import styles from "./FinanceEvidenceImport.styles";

export function FinanceEvidenceImport({ agentId, knowledgeBaseId, stock, sourceUrl = "", zh }: { agentId: string; knowledgeBaseId: string; stock?: StockIdentity; sourceUrl?: string; zh: boolean }) {
  const client = useQueryClient(), gate = useRef(false);
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [url, setUrl] = useState(sourceUrl), [pdfBase64, setPdfBase64] = useState("");
  const [company, setCompany] = useState(stock?.name ?? ""), [ticker, setTicker] = useState(stock?.ticker ?? "");
  const [period, setPeriod] = useState(""), [published, setPublished] = useState("");
  const [preview, setPreview] = useState<FinancialPdfPreview | null>(null), [original, setOriginal] = useState<FinancialPdfInput | null>(null);
  const [page, setPage] = useState(""), [staged, setStaged] = useState<FinancialPdfStaged | null>(null);
  const [checked, setChecked] = useState(false), [approved, setApproved] = useState(false);
  const selected = preview?.pages.find(p => String(p.page) === page);
  const pageValid = Boolean(preview && /^\d+$/.test(page) && Number(page) >= 1 && Number(page) <= preview.pageCount);
  const metadataValid = Boolean(company.trim() && /^[036489]\d{5}$/.test(ticker) && /^20\d{2}(FY|Q[1-4]|H[12])$/.test(period) && /^\d{4}-\d{2}-\d{2}$/.test(published));
  function resetPreview() { setPreview(null); setOriginal(null); setStaged(null); setChecked(false); setApproved(false); setError(""); }
  async function operation(action: () => Promise<void>) {
    if (gate.current) return;
    gate.current = true; setBusy(true); setError("");
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : "财报导入失败"); }
    finally { gate.current = false; setBusy(false); }
  }
  async function readFile(file: File | undefined) {
    resetPreview(); setPdfBase64("");
    if (!file) return;
    if (file.size > 20_000_000 || !file.name.toLowerCase().endsWith(".pdf")) { setError(zh ? "请选择20MB以内的PDF文件" : "Choose a PDF up to 20 MB"); return; }
    await operation(async () => {
      const encoded = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
        reader.onerror = () => reject(new Error(zh ? "PDF文件读取失败" : "Could not read PDF"));
        reader.readAsDataURL(file);
      });
      setPdfBase64(encoded);
    });
  }
  async function loadPreview() {
    resetPreview();
    await operation(async () => {
      const input = { sourceUrl: url.trim(), pdfBase64 };
      const result = await previewFinancialPdf(agentId, input);
      setPreview(result); setOriginal(input); setPage(String(result.pages[0]?.page ?? ""));
    });
  }
  async function stage() {
    if (!preview || !original || !selected || !metadataValid) return;
    await operation(async () => {
      const result = await stageFinancialPdf(agentId, { ...original, company: company.trim(), ticker, reportPeriod: period, publishedDate: published, reportVersion: "original", page: selected.page, expectedDocumentSha256: preview.documentSha256 });
      setStaged(result); setApproved(Boolean(result.source.knowledgeItemId));
    });
  }
  async function loadPage() {
    if (!preview || !original || !pageValid) return;
    const expectedHash = preview.documentSha256;
    await operation(async () => {
      const result = await previewFinancialPdf(agentId, { ...original, page: Number(page) });
      if (result.documentSha256 !== expectedHash) { resetPreview(); throw new Error(zh ? "PDF原件已变化，请重新预览" : "Original PDF changed; preview again"); }
      setPreview(result); setChecked(false);
    });
  }
  async function approve() {
    if (!staged || !selected || !checked || approved) return;
    await operation(async () => {
      await reviewKnowledgeSourceInbox("agent", agentId, staged.source.inboxSourceId, {
        decision: "accepted", reviewedByAgentId: agentId, resolutionNote: "用户已核对公司、报告期、披露日期及原始PDF页文本。",
        ingestOnAccept: true, knowledgeBaseId, knowledgeTitle: staged.source.title,
        knowledgeContent: selected.excerpt, knowledgeSummary: zh ? `已审核原始页摘录 · 第${selected.page}页` : `Reviewed original excerpt · page ${selected.page}`, tags: ["financial-report", ticker, period],
      });
      setApproved(true);
      await client.invalidateQueries({ queryKey: ["finance", "library", agentId, knowledgeBaseId] });
    });
  }
  const locked = busy || Boolean(staged);
  return <>
    <VButton density="compact" variant="secondary" icon={<Upload size={14} />} onPress={() => setOpen(true)}>{zh ? "导入财报" : "Import PDF"}</VButton>
    <VDialog open={open} onOpenChange={value => { if (!busy) setOpen(value); }} title={zh ? "导入原始财报" : "Import original filing"} size="lg"
      footer={<><VButton variant="secondary" isDisabled={busy} onPress={() => setOpen(false)}>{zh ? "关闭" : "Close"}</VButton>{approved ? <VButton variant="secondary" onPress={resetPreview}>{zh ? "导入另一页" : "Import another page"}</VButton> : staged ? <VButton isPending={busy} isDisabled={!checked || busy} onPress={() => void approve()}>{zh ? "确认原文并入库" : "Approve original and file"}</VButton> : <VButton isPending={busy} isDisabled={busy || !selected || !metadataValid} onPress={() => void stage()}>{zh ? "提交本页审核" : "Stage this page"}</VButton>}</>}>
      <div className={styles.form}>
        <label className={styles.field}>{zh ? "官方PDF链接" : "Official PDF URL"}<VInput aria-label="财报官方PDF链接" value={url} disabled={locked} placeholder="https://static.cninfo.com.cn/...PDF" onChange={event => { setUrl(event.target.value); resetPreview(); }} /></label>
        <label className={styles.field}>{zh ? "本地PDF（可选）" : "Local PDF (optional)"}<VInput aria-label="财报PDF文件" type="file" accept=".pdf,application/pdf" disabled={locked} onChange={event => void readFile(event.target.files?.[0])} /></label>
        <div className={styles.metadata}>
          <label className={styles.field}>{zh ? "公司" : "Company"}<VInput aria-label="财报公司" value={company} disabled={locked} maxLength={120} onChange={event => setCompany(event.target.value)} /></label>
          <label className={styles.field}>{zh ? "A股代码" : "CN ticker"}<VInput aria-label="财报股票代码" value={ticker} disabled={locked} maxLength={6} onChange={event => setTicker(event.target.value.trim())} /></label>
          <label className={styles.field}>{zh ? "报告期" : "Period"}<VInput aria-label="财报报告期" value={period} disabled={locked} placeholder="2026H1 / 2025FY" maxLength={8} onChange={event => setPeriod(event.target.value.toUpperCase())} /></label>
          <label className={styles.field}>{zh ? "披露日期" : "Published"}<VInput aria-label="财报披露日期" type="date" value={published} disabled={locked} onChange={event => setPublished(event.target.value)} /></label>
        </div>
        {!staged ? <VButton variant="secondary" isPending={busy} isDisabled={!url.trim() || busy} onPress={() => void loadPreview()}>{zh ? "读取原文预览" : "Preview original"}</VButton> : null}
        {preview ? <>
          <div className={styles.pageActions}><span className={styles.pageCount}>{zh ? `原件${preview.pageCount}页` : `${preview.pageCount} original pages`}</span><label className={styles.field}>{zh ? "原始页码" : "Page"}<VInput aria-label="财报原文页码" type="number" min={1} max={preview.pageCount} value={page} disabled={locked} onChange={event => { setPage(event.target.value); setChecked(false); }} /></label><VButton variant="secondary" density="compact" isDisabled={locked || !pageValid} onPress={() => void loadPage()}>{zh ? "读取该页" : "Read page"}</VButton><VRouteLinkButton to={`${preview.sourceUrl}#page=${pageValid ? page : 1}`} target="_blank" rel="noopener noreferrer" reloadDocument>{zh ? "打开PDF原件" : "Original PDF"}</VRouteLinkButton></div>
          {!selected ? <VStateSurface tone="info" density="compact" title={zh ? "输入原始页码并读取该页后才能送审" : "Read the original page before staging"} /> : null}
          <pre aria-label="财报原文页文本" className={styles.excerpt}>{selected?.excerpt}</pre>
          <p className={styles.notice}>{zh ? "仅提交当前原始页摘录，审核后才可检索；未自动核验数字、公司归属或披露日期。" : "Only this original page excerpt is submitted. Search requires approval; figures, issuer and date are not automatically verified."}</p>
          {preview.warnings.map(warning => <VStateSurface key={warning} tone="unavailable" density="compact" title={warning} />)}
        </> : null}
        {staged && !approved ? <><VStateSurface tone="info" density="compact" title={zh ? "本页待审核，尚不可检索" : "Pending review; not searchable"} /><VCheckbox isSelected={checked} onChange={setChecked} isDisabled={busy}>{zh ? "我已核对公司、报告期、披露日期及本页原文" : "I checked the issuer, period, publication date and original page"}</VCheckbox></> : null}
        {approved ? <VStateSurface tone="info" density="compact" title={zh ? "本页原文已审核入库" : "Original page approved and filed"} /> : null}
        {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
      </div>
    </VDialog>
  </>;
}
