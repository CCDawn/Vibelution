import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { downloadFinancialReportsExport, exportFinancialReport, fetchFinancialReports, financialReportKeys, isFinancialReportNotFoundError, type FinancialReportSummary } from "../../api/financialReports";
import type { FinancialReportFilters } from "../../api/types/financialReports";
import type { FinancialReviewCase } from "../../api/financialPreferences";
import { LazyConversationMarkdownRenderer } from "../../components/conversation/LazyConversationMarkdownRenderer";
import { VButton, VCheckbox, VDenseTable, VDialog, VInput, VSelect, VStateSurface, VSurface, VTextarea, type VDenseTableColumn } from "../../components/vui";
import { isSessionDeleteTombstoned } from "../sessionDeleteTombstone";
import { FinanceReportExport } from "./FinanceReportExport";
import styles from "./FinanceReportsCenter.styles";

type ReportTarget = Pick<FinancialReportSummary, "sessionId" | "turnId" | "title">;
const keyOf = (item: ReportTarget) => JSON.stringify([item.sessionId, item.turnId]);

export function FinanceReportsCenter({ agentId, cases, onSaveCases, onOpenSession, pending, zh, casesOnly = false, initialKind = "" }: {
  agentId: string; cases: FinancialReviewCase[];
  onSaveCases: (change: (current: FinancialReviewCase[]) => FinancialReviewCase[]) => Promise<unknown>;
  onOpenSession: (id: string) => void; pending: boolean; zh: boolean; casesOnly?: boolean; initialKind?: "" | "research" | "review";
}) {
  const [q, setQ] = useState(""), [query, setQuery] = useState("");
  const [marketCode, setMarketCode] = useState<FinancialReportFilters["marketCode"]>("");
  const [dateFrom, setDateFrom] = useState(""), [dateTo, setDateTo] = useState(""), [kind, setKind] = useState<FinancialReportFilters["kind"]>(initialKind);
  const [selected, setSelected] = useState<Map<string, ReportTarget>>(new Map());
  const [missingReportKeys, setMissingReportKeys] = useState<Set<string>>(() => new Set());
  const [viewing, setViewing] = useState<ReportTarget | null>(null);
  const [batchFormat, setBatchFormat] = useState<"markdown" | "json" | "docx">("markdown"), [exporting, setExporting] = useState(false);
  const [error, setError] = useState(""), [bookmark, setBookmark] = useState<(ReportTarget & { id?: string }) | null>(null);
  const [title, setTitle] = useState(""), [tags, setTags] = useState(""), [note, setNote] = useState("");
  const exportGate = useRef(false);
  const bookmarkSaveGate = useRef(false);
  useEffect(() => { const timer = setTimeout(() => setQuery(q.trim()), 250); return () => clearTimeout(timer); }, [q]);
  useEffect(() => setSelected(new Map()), [query, marketCode, dateFrom, dateTo, kind, casesOnly]);
  const filters = useMemo(() => ({ q: query, marketCode, dateFrom, dateTo, kind, limit: 30 }), [query, marketCode, dateFrom, dateTo, kind]);
  const catalog = useInfiniteQuery({ queryKey: financialReportKeys.catalog(agentId, filters), queryFn: ({ signal, pageParam }) => fetchFinancialReports(agentId, { ...filters, cursor: pageParam }, { signal }), initialPageParam: "", getNextPageParam: (page) => page.nextCursor || undefined, enabled: !casesOnly, staleTime: 15_000, retry: false });
  const rows = catalog.data?.pages.flatMap((page) => page.items) ?? [];
  const report = useQuery({ queryKey: ["finance", "exact-report", agentId, viewing?.sessionId, viewing?.turnId], queryFn: async ({ signal }) => {
    if (!viewing) throw new Error("未选择报告");
    const response = await exportFinancialReport({ assistantAgentId: agentId, sessionId: viewing.sessionId, turnId: viewing.turnId, format: "markdown" }, { signal });
    if (response.sessionId !== viewing.sessionId || response.turnId !== viewing.turnId || response.format !== "markdown" || response.encoding !== "utf8" || typeof response.content !== "string" || response.content.length > 250_000) throw new Error("报告身份或内容无效");
    return response.content;
  }, enabled: viewing !== null && !isSessionDeleteTombstoned(viewing.sessionId), staleTime: 60_000, retry: false });
  const viewingKey = viewing ? keyOf(viewing) : "";
  const report404 = report.isError && isFinancialReportNotFoundError(report.error);
  const viewingReportMissing = Boolean(viewing && (isSessionDeleteTombstoned(viewing.sessionId) || missingReportKeys.has(viewingKey) || report404));
  function isReportMissing(target: ReportTarget) {
    return missingReportKeys.has(keyOf(target))
      || isSessionDeleteTombstoned(target.sessionId)
      || Boolean(viewing && keyOf(target) === viewingKey && report404);
  }
  const exportableSelection = [...selected.values()].filter((target) => !isReportMissing(target));
  const matchingCases = cases.filter((item) => `${item.title} ${item.tags.join(" ")} ${item.note}`.toLocaleLowerCase().includes(q.trim().toLocaleLowerCase()));
  useEffect(() => {
    if (!viewing || (!isSessionDeleteTombstoned(viewing.sessionId) && !report404)) return;
    const missingKey = keyOf(viewing);
    setMissingReportKeys((current) => current.has(missingKey) ? current : new Set(current).add(missingKey));
    setSelected((current) => {
      if (!current.has(missingKey)) return current;
      const next = new Map(current);
      next.delete(missingKey);
      return next;
    });
  }, [report404, viewing]);
  function editBookmark(target: ReportTarget & { id?: string }) {
    const existing = cases.find((row) => row.sessionId === target.sessionId && row.turnId === target.turnId);
    setBookmark({ ...target, id: existing?.id ?? target.id }); setTitle(existing?.title ?? target.title); setTags(existing?.tags.join(", ") ?? ""); setNote(existing?.note ?? ""); setError("");
  }
  async function saveBookmark() {
    if (!bookmark || !title.trim() || pending || bookmarkSaveGate.current) return;
    const parsedTags = [...new Set(tags.split(/[,，]/).map((value) => value.trim()).filter(Boolean))];
    if (parsedTags.length > 10 || parsedTags.some((value) => value.length > 30)) { setError(zh ? "最多10个标签，每个30字" : "At most 10 tags, 30 characters each"); return; }
    const row: FinancialReviewCase = { id: bookmark.id ?? crypto.randomUUID(), sessionId: bookmark.sessionId, turnId: bookmark.turnId, title: title.trim(), tags: parsedTags, note };
    bookmarkSaveGate.current = true;
    try { await onSaveCases((current) => current.some((item) => item.sessionId === row.sessionId && item.turnId === row.turnId) ? current.map((item) => item.sessionId === row.sessionId && item.turnId === row.turnId ? { ...row, id: item.id } : item) : [...current, row]); setBookmark(null); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "保存失败"); }
    finally { bookmarkSaveGate.current = false; }
  }
  async function batchExport() {
    if (exportGate.current || !exportableSelection.length) return;
    exportGate.current = true; setExporting(true); setError("");
    try { await downloadFinancialReportsExport(agentId, exportableSelection.map(({ sessionId, turnId }) => ({ sessionId, turnId })), batchFormat); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "导出失败"); }
    finally { exportGate.current = false; setExporting(false); }
  }
  const columns: VDenseTableColumn<FinancialReportSummary>[] = [
    { id: "select", header: zh ? "选择" : "Select", width: 50, render: (row) => <VCheckbox aria-label={`${zh ? "选择" : "Select"} ${row.title} ${row.turnId}`} isSelected={!isReportMissing(row) && selected.has(keyOf(row))} isDisabled={exporting || isReportMissing(row) || (!selected.has(keyOf(row)) && exportableSelection.length >= 20)} onChange={(checked) => setSelected((current) => { if (isReportMissing(row)) return current; const next = new Map(current); if (checked) next.set(keyOf(row), row); else next.delete(keyOf(row)); return next; })} /> },
    { id: "title", header: zh ? "报告" : "Report", fill: true, minWidth: 190, render: (row) => {
      const missing = isReportMissing(row);
      return <VButton variant="ghost" className={styles.titleButton} isDisabled={missing} onPress={() => setViewing(row)}><span className={styles.identity}><strong>{row.title}</strong><small>{row.ticker || (row.kind === "review" ? zh ? "复盘" : "Review" : zh ? "主题研究" : "Topic")} · {row.marketCode || "—"}{missing ? ` · ${zh ? "原报告已删除" : "Original report deleted"}` : ""}</small></span></VButton>;
    } },
    { id: "date", header: zh ? "完成时间" : "Completed", width: 142, render: (row) => <span className={styles.muted}>{row.completedAt ? new Date(row.completedAt).toLocaleString(zh ? "zh-CN" : "en-US", { dateStyle: "short", timeStyle: "short" }) : "—"}</span> },
    { id: "actions", header: zh ? "操作" : "Actions", width: 126, truncate: false, className: styles.actionCell, render: (row) => <span className={styles.actions}>{!isReportMissing(row) ? <FinanceReportExport assistantAgentId={agentId} sessionId={row.sessionId} turnId={row.turnId} zh={zh} /> : null}<VButton density="compact" variant="ghost" isDisabled={pending || isReportMissing(row) || (cases.length >= 100 && !cases.some((item) => keyOf(item) === keyOf(row)))} onPress={() => editBookmark(row)}>{zh ? "收藏" : "Save case"}</VButton></span> },
  ];
  return <div className={styles.root}>
    {casesOnly ? <><label className={styles.field}>{zh ? "查找案例" : "Find a case"}<VInput aria-label={zh ? "案例搜索" : "Case search"} value={q} maxLength={120} onChange={(event) => setQ(event.target.value)} placeholder={zh ? "标题 / 标签 / 备注" : "Title / tags / note"} /></label>{cases.length
  ? matchingCases.length
    ? matchingCases.map((item) => {
        const missing = isReportMissing(item);
        return (
          <VSurface key={item.id} tone="panel" padding="normal" className={styles.case}>
            <div className={styles.reportHeader}>
              <VButton variant="ghost" isDisabled={missing} onPress={() => setViewing(item)}>{item.title}</VButton>
              <span className={styles.actions}>
                <VButton variant="ghost" isDisabled={pending} onPress={() => editBookmark(item)}>{zh ? "编辑书签" : "Edit case"}</VButton>
                <VButton variant="ghost" isDisabled={pending} onPress={() => void onSaveCases((current) => current.filter((row) => row.id !== item.id)).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "删除失败"))}>{zh ? "删除书签" : "Remove case"}</VButton>
              </span>
            </div>
            {missing ? <span className={styles.muted} role="status">{zh ? "原报告已删除，仍可编辑备注或删除此案例。" : "Original report deleted. You can still edit notes or remove this case."}</span> : null}
            <span className={styles.muted}>{item.tags.join(" · ")}</span>
            {item.note ? <p className={styles.note}>{item.note}</p> : null}
          </VSurface>
        );
      })
    : <VStateSurface tone="empty" title={zh ? "没有匹配的复盘案例" : "No matching cases"} actions={<VButton variant="secondary" onPress={() => setQ("")}>{zh ? "清除搜索" : "Clear search"}</VButton>}>{zh ? "试试其他标题、标签或备注关键词。" : "Try another title, tag, or note keyword."}</VStateSurface>
  : <VStateSurface tone="empty" title={zh ? "还没有复盘案例" : "No saved cases"}>{zh ? "在报告中心收藏已完成的研究，添加标签和复盘备注。" : "Save a completed report and add review tags and notes."}</VStateSurface>}</> : <>
      <div className={styles.toolbar}><label className={styles.field}>{zh ? "查找报告" : "Find reports"}<VInput aria-label={zh ? "报告搜索" : "Report search"} value={q} maxLength={120} onChange={(event) => setQ(event.target.value)} placeholder={zh ? "代码 / 标题 / 摘要" : "Ticker / title / summary"} /></label><label className={styles.field}>{zh ? "市场" : "Market"}<VSelect aria-label={zh ? "报告市场" : "Report market"} selectedKey={marketCode} onSelectionChange={(key) => setMarketCode(String(key) as FinancialReportFilters["marketCode"])} options={[{ id: "", label: zh ? "全部" : "All" }, { id: "CN", label: "A股" }, { id: "HK", label: "港股" }, { id: "US", label: "美股" }]} /></label><label className={styles.field}>{zh ? "类型" : "Kind"}<VSelect aria-label={zh ? "报告类型" : "Report kind"} selectedKey={kind} onSelectionChange={(key) => setKind(String(key) as FinancialReportFilters["kind"])} options={[{ id: "", label: zh ? "全部报告" : "All reports" }, { id: "research", label: zh ? "研究" : "Research" }, { id: "review", label: zh ? "复盘" : "Review" }]} /></label><label className={styles.date}>{zh ? "从" : "From"}<VInput type="date" aria-label={zh ? "报告开始日期" : "Report date from"} value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label><label className={styles.date}>{zh ? "至" : "To"}<VInput type="date" aria-label={zh ? "报告结束日期" : "Report date to"} value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label></div>
      <div className={styles.actions}><VSelect aria-label={zh ? "批量导出格式" : "Batch export format"} selectedKey={batchFormat} options={[{ id: "markdown", label: "Markdown" }, { id: "json", label: "JSON" }, { id: "docx", label: "Word" }]} onSelectionChange={(key) => setBatchFormat(String(key) as typeof batchFormat)} /><VButton isDisabled={!exportableSelection.length || exporting} isPending={exporting} onPress={() => void batchExport()}>{zh ? `导出选中 ${exportableSelection.length}/20` : `Export selected ${exportableSelection.length}/20`}</VButton><VButton variant="ghost" isDisabled={!selected.size || exporting} onPress={() => setSelected(new Map())}>{zh ? "清空选择" : "Clear selection"}</VButton><VButton variant="secondary" isPending={catalog.isFetching && !catalog.isFetchingNextPage} onPress={() => void catalog.refetch()}>{zh ? "刷新" : "Refresh"}</VButton></div>
      {catalog.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取已完成报告" : "Loading completed reports"} /> : catalog.isError ? <VStateSurface tone="error" title={zh ? "报告目录读取失败" : "Reports unavailable"} actions={<VButton onPress={() => void catalog.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{catalog.error.message}</VStateSurface> : <div className={styles.table}><VDenseTable ariaLabel={zh ? "逐份研究报告" : "Completed research reports"} rows={rows} columns={columns} getRowKey={keyOf} resizable emptyText={zh ? "已扫描范围内没有匹配报告" : "No matching reports in scanned sessions"} /></div>}
      <div className={styles.actions}><span className={styles.muted}>{zh ? "按会话最近活动排列，只展示成功完成的报告。" : "Ordered by session activity; completed reports only."}</span>{catalog.hasNextPage ? <VButton isPending={catalog.isFetchingNextPage} onPress={() => void catalog.fetchNextPage()}>{zh ? "继续读取历史" : "Load older reports"}</VButton> : null}</div>
    </>}
    {error && !bookmark ? <VStateSurface density="compact" tone="error" title={error} /> : null}
    {viewing ? <section className={styles.report} aria-label={zh ? "历史报告正文" : "Historical report"}><div className={styles.reportHeader}><h2>{viewing.title}</h2><span className={styles.actions}>{!viewingReportMissing ? <><FinanceReportExport assistantAgentId={agentId} sessionId={viewing.sessionId} turnId={viewing.turnId} zh={zh} /><VButton onPress={() => onOpenSession(viewing.sessionId)}>{zh ? "打开原会话 / 追问" : "Open session / follow up"}</VButton></> : null}<VButton variant="ghost" onPress={() => setViewing(null)}>{zh ? "关闭" : "Close"}</VButton></span></div>{viewingReportMissing ? <VStateSurface tone="error" title={zh ? "原报告已删除" : "Original report deleted"}>{zh ? "无法查看或导出报告，也无法从已删除的会话继续追问。你仍可保留或移除此复盘案例。" : "The report cannot be viewed or exported, and its deleted session cannot be reopened. You can keep or remove this review case."}</VStateSurface> : report.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取报告" : "Loading report"} /> : report.isError ? <VStateSurface tone="error" title={zh ? "报告不可用" : "Report unavailable"} actions={<VButton onPress={() => void report.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{report.error.message}</VStateSurface> : <LazyConversationMarkdownRenderer content={report.data ?? ""} language={zh ? "zh" : "en"} />}</section> : null}
    <VDialog open={Boolean(bookmark)} onOpenChange={(open) => { if (!open) setBookmark(null); }} title={zh ? "复盘案例书签" : "Review case"} footer={<VButton variant="primary" isDisabled={pending || !title.trim()} onPress={() => void saveBookmark()}>{zh ? "保存案例" : "Save case"}</VButton>}><div className={styles.form}><label className={styles.field}>{zh ? "标题" : "Title"}<VInput aria-label={zh ? "案例标题" : "Case title"} value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} /></label><label className={styles.field}>{zh ? "标签（逗号分隔）" : "Tags (comma separated)"}<VInput aria-label={zh ? "案例标签" : "Case tags"} value={tags} maxLength={309} onChange={(event) => setTags(event.target.value)} /></label><label className={styles.field}>{zh ? "复盘备注" : "Review note"}<VTextarea aria-label={zh ? "复盘备注" : "Review note"} value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} /></label>{error ? <VStateSurface density="compact" tone="error" title={error} /> : null}</div></VDialog>
  </div>;
}
