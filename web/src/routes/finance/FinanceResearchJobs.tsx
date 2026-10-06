import { useEffect, useState } from "react";
import { CalendarClock, Play, RefreshCw } from "lucide-react";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { StockIdentity } from "../../api/financialMarket";
import type { FinancialJobDepth, FinancialJobExecutionKind, FinancialJobPeriod, FinancialResearchBatch, FinancialResearchScheduleCreateRequest } from "../../api/financialJobs";
import { VButton, VChip, VInput, VSelect, VStateSurface, VSurface, VTextarea } from "../../components/vui";
import { useFinanceResearchJobs } from "./useFinanceResearchJobs";
import { ACTIVE_FINANCIAL_BATCH_STATUSES, MAX_BATCH_SYMBOLS, beijingScheduledTime, financialBatchStatusLabel, financialBatchStatusTone, financialJobTime, financialScheduleLabel, parseFinancialBatchSymbols } from "./financialJobModel";
import { isValidResearchDate, localResearchDate } from "./stockResearchModel";
import styles from "./FinanceResearchJobs.styles";
import { FinanceResearchApprovals } from "./FinanceResearchApprovals";

type Props = {
  assistant: FinancialAssistant; stock: StockIdentity; watchlist: StockIdentity[];
  mode: "batches" | "schedules"; zh: boolean; onOpenRun: (runId: string, symbol: string) => void;
};

export function FinanceResearchJobs({ assistant, stock, watchlist, mode, zh, onOpenRun }: Props) {
  const jobs = useFinanceResearchJobs(assistant.agentId, zh);
  const [codes, setCodes] = useState(stock.symbol);
  const [periodDays, setPeriodDays] = useState<FinancialJobPeriod>(30);
  const [depth, setDepth] = useState<FinancialJobDepth>("brief");
  const [execution, setExecution] = useState<FinancialJobExecutionKind>(mode === "batches" ? "now" : "weekdays");
  const [researchDate, setResearchDate] = useState(() => localResearchDate());
  const [scheduledAt, setScheduledAt] = useState("");
  const [timeOfDay, setTimeOfDay] = useState("18:00");
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => { setCodes(stock.symbol); setSubmitted(false); }, [assistant.agentId]);
  useEffect(() => { setExecution(mode === "batches" ? "now" : "weekdays"); setSubmitted(false); jobs.clearFeedback(); }, [mode, jobs.clearFeedback]);
  const parsed = parseFinancialBatchSymbols(codes);
  const symbolError = parsed.invalid.length ? (zh ? `无法识别股票代码：${parsed.invalid.slice(0, 3).join("、")}` : `Invalid symbols: ${parsed.invalid.slice(0, 3).join(", ")}`) : parsed.symbols.length > MAX_BATCH_SYMBOLS ? (zh ? "每批最多 10 只股票" : "Up to 10 stocks per batch") : !parsed.symbols.length ? (zh ? "请输入股票代码" : "Enter stock codes") : "";
  const onceAt = beijingScheduledTime(scheduledAt);
  const timeError = execution === "once" && (!onceAt || Date.parse(onceAt) <= Date.now()) ? (zh ? "请选择未来的北京时间" : "Choose a future Beijing time") : (execution === "daily" || execution === "weekdays") && !/^([01]\d|2[0-3]):[0-5]\d$/.test(timeOfDay) ? (zh ? "请选择运行时间" : "Choose a run time") : "";
  const dateError = execution === "now" && !isValidResearchDate(researchDate) ? (zh ? "请选择有效的分析日期" : "Choose a valid research date") : "";
  const unavailable = assistant.setupStatus !== "ready" || assistant.modelStatus !== "configured_unverified";
  const formError = symbolError || timeError || dateError;
  const batchRows = jobs.batches.data?.batches ?? [];
  const scheduleRows = (jobs.schedules.data?.schedules ?? []).filter((schedule) => schedule.execution.kind !== "now");
  const query = mode === "batches" ? jobs.batches : jobs.schedules;
  const hasRows = mode === "batches" ? batchRows.length > 0 : scheduleRows.length > 0;

  function start() {
    setSubmitted(true);
    if (unavailable || formError || jobs.creating) return;
    const payload: FinancialResearchScheduleCreateRequest = {
      symbols: parsed.symbols, periodDays, depth,
      execution: { kind: execution, timezone: "Asia/Shanghai", ...(execution === "once" && onceAt ? { scheduledAt: onceAt } : execution === "daily" || execution === "weekdays" ? { timeOfDay } : {}) },
      ...(execution === "now" ? { researchDate } : {}),
    };
    void jobs.create(payload);
  }

  return <div className={styles.page} data-finance-research-jobs>
    <FinanceResearchApprovals assistantAgentId={assistant.agentId} zh={zh} turns={batchRows
      .filter((batch) => ACTIVE_FINANCIAL_BATCH_STATUSES.has(batch.status) || batch.status === "blocked")
      .flatMap((batch) => batch.items.filter((item) => item.status !== "completed")
        .flatMap((item) => item.turnRefs.map((ref) => ({ ...ref, symbol: item.symbol }))))} />
    <VSurface padding="normal" className={styles.form} ariaLabel={zh ? (mode === "batches" ? "新建批量研究" : "新建定时研究") : "New research job"}>
      <div className={styles.header}><h2 className={styles.heading}>{zh ? (mode === "batches" ? "五分析员批量研究" : "定时研究") : (mode === "batches" ? "Analyst batch research" : "Scheduled research")}</h2><VChip>{zh ? "A 股 · 港股 · 美股" : "A · HK · US"}</VChip></div>
      <label className={styles.field}>{zh ? "证券代码（最多 10 只）" : "Symbols (up to 10)"}<VTextarea className={styles.codes} aria-label={zh ? "批量证券代码" : "Batch symbols"} aria-invalid={Boolean(submitted && symbolError)} value={codes} maxLength={300} placeholder="600519, hk00700, usAAPL" onChange={(event) => setCodes(event.target.value)} /></label>
      <div className={styles.shortcuts}><VButton variant="ghost" onPress={() => setCodes(stock.symbol)}>{zh ? `当前：${stock.name || stock.ticker}` : `Current: ${stock.name || stock.ticker}`}</VButton><VButton variant="ghost" isDisabled={!watchlist.length} onPress={() => setCodes(watchlist.slice(0, MAX_BATCH_SYMBOLS).map((item) => item.symbol).join(", "))}>{zh ? (watchlist.length > MAX_BATCH_SYMBOLS ? "自选前 10 只" : "使用自选") : (watchlist.length > MAX_BATCH_SYMBOLS ? "First 10 watchlist stocks" : "Use watchlist")}</VButton><span className={styles.hint}>{zh ? `已选 ${parsed.symbols.length} 只` : `${parsed.symbols.length} selected`}</span></div>
      <div className={styles.fields}>
        {mode === "schedules" ? <label className={styles.field}>{zh ? "执行频率" : "Frequency"}<VSelect selectedKey={execution} aria-label={zh ? "执行频率" : "Frequency"} onSelectionChange={(key) => setExecution(key as FinancialJobExecutionKind)} options={[{ id: "once", label: zh ? "执行一次" : "Once" }, { id: "daily", label: zh ? "每天" : "Daily" }, { id: "weekdays", label: zh ? "周一至周五" : "Monday to Friday" }]} /></label> : <label className={styles.field}>{zh ? "分析日期" : "Analysis date"}<VInput type="date" aria-label={zh ? "批量分析日期" : "Batch analysis date"} value={researchDate} max={localResearchDate()} onChange={(event) => setResearchDate(event.target.value)} /></label>}
        {execution === "once" ? <label className={styles.field}>{zh ? "执行时间（北京时间）" : "Run at (Beijing time)"}<VInput type="datetime-local" aria-label={zh ? "执行时间（北京时间）" : "Run at (Beijing time)"} value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /></label> : execution === "daily" || execution === "weekdays" ? <label className={styles.field}>{zh ? "运行时间（北京时间）" : "Run time (Beijing time)"}<VInput type="time" aria-label={zh ? "运行时间（北京时间）" : "Run time (Beijing time)"} value={timeOfDay} onChange={(event) => setTimeOfDay(event.target.value)} /></label> : null}
        <label className={styles.field}>{zh ? "资料范围" : "Source window"}<VSelect selectedKey={String(periodDays)} aria-label={zh ? "批量资料范围" : "Batch source window"} onSelectionChange={(key) => setPeriodDays(Number(key) as FinancialJobPeriod)} options={[{ id: "7", label: zh ? "近 7 天" : "7 days" }, { id: "30", label: zh ? "近 30 天" : "30 days" }, { id: "90", label: zh ? "近 90 天" : "90 days" }]} /></label>
        <label className={styles.field}>{zh ? "研究深度" : "Depth"}<VSelect selectedKey={depth} aria-label={zh ? "批量研究深度" : "Batch depth"} onSelectionChange={(key) => setDepth(key as FinancialJobDepth)} options={[{ id: "brief", label: zh ? "1 · 快速" : "1 · Quick" }, { id: "basic", label: zh ? "2 · 基础" : "2 · Basic" }, { id: "standard", label: zh ? "3 · 标准" : "3 · Standard" }, { id: "detailed", label: zh ? "4 · 深入" : "4 · Deep" }, { id: "exhaustive", label: zh ? "5 · 全面" : "5 · Comprehensive" }]} /></label>
      </div>
      <div className={styles.footer}><span className={styles.hint}>{unavailable ? (zh ? "请先完成助手和模型配置" : "Configure the assistant and model first") : execution === "weekdays" ? (zh ? "节假日照常研究；启动后需保持应用运行" : "Includes holidays; keep the app running") : (zh ? "后台逐股执行；启动后需保持应用运行" : "Stocks run in sequence; keep the app running")}</span><VButton variant="primary" icon={mode === "batches" ? <Play size={14} /> : <CalendarClock size={14} />} isPending={jobs.creating} isDisabled={unavailable || jobs.creating} onPress={start}>{zh ? (mode === "batches" ? "开始批量研究" : "保存计划") : (mode === "batches" ? "Start batch" : "Save schedule")}</VButton></div>
      {submitted && formError ? <p className={styles.error} role="alert">{formError}</p> : null}
    </VSurface>
    {jobs.error ? <VStateSurface tone="error" title={jobs.error} /> : null}
    {jobs.notice ? <p className={styles.success} role="status">{jobs.notice}</p> : null}
    <div className={styles.header}><h2 className={styles.heading}>{zh ? (mode === "batches" ? "最近批次" : "已有计划") : (mode === "batches" ? "Recent batches" : "Schedules")}</h2><VButton variant="ghost" icon={<RefreshCw size={14} />} isPending={query.isFetching} onPress={() => void jobs.refresh()}>{zh ? "刷新" : "Refresh"}</VButton></div>
    {query.isError ? <VStateSurface tone="error" title={zh ? "任务读取失败" : "Could not load jobs"} actions={<VButton onPress={() => void jobs.refresh()}>{zh ? "重试" : "Retry"}</VButton>} /> : query.isPending && !hasRows ? <VStateSurface tone="loading" busy title={zh ? "读取研究任务" : "Loading jobs"} /> : !hasRows ? <VStateSurface tone="empty" title={zh ? (mode === "batches" ? "暂无批量研究" : "暂无定时计划") : "No jobs yet"} /> : mode === "batches" ? <div className={styles.list}>{batchRows.map((batch) => <ResearchBatchCard key={batch.batchId} batch={batch} zh={zh} pending={jobs.pendingAction} onStop={() => void jobs.stop(batch.batchId)} onRetry={() => void jobs.retry(batch.batchId)} onOpenRun={onOpenRun} />)}</div> : <div className={styles.list}>{scheduleRows.map((schedule) => {
      const firedOnce = schedule.execution.kind === "once" && Boolean(schedule.lastTriggeredAt);
      return <VSurface padding="normal" key={schedule.scheduleId} className={styles.card}><div className={styles.header}><div className={styles.identity}><strong className={styles.title}>{schedule.symbols.join(" · ")}</strong><span className={styles.hint}>{financialScheduleLabel(schedule, zh)} · {zh ? "北京时间" : "Beijing time"}</span></div><VChip tone={schedule.enabled && schedule.nextRunAt ? "success" : "neutral"}>{firedOnce ? (zh ? "已触发" : "Triggered") : schedule.enabled ? (zh ? "已启用" : "Enabled") : (zh ? "已暂停" : "Paused")}</VChip></div><div className={styles.footer}><span className={styles.hint}>{zh ? "下次执行：" : "Next: "}{financialJobTime(schedule.nextRunAt, zh)}</span>{!firedOnce ? <VButton variant="secondary" isDisabled={Boolean(jobs.pendingAction)} isPending={jobs.pendingAction === schedule.scheduleId} onPress={() => void jobs.setEnabled(schedule.scheduleId, !schedule.enabled)}>{schedule.enabled ? (zh ? "暂停计划" : "Pause") : (zh ? "恢复计划" : "Resume")}</VButton> : null}</div></VSurface>;
    })}</div>}
  </div>;
}

function ResearchBatchCard({ batch, zh, pending, onStop, onRetry, onOpenRun }: {
  batch: FinancialResearchBatch; zh: boolean; pending: string; onStop: () => void; onRetry: () => void; onOpenRun: Props["onOpenRun"];
}) {
  const completed = batch.items.filter((item) => item.status === "completed").length;
  const retryable = ["partial", "failed", "stopped"].includes(batch.status) && batch.items.some((item) => ["failed", "cancelled", "skipped"].includes(item.status));
  return <VSurface padding="normal" className={styles.card} data-finance-batch-id={batch.batchId}>
    <div className={styles.header}><div className={styles.identity}><strong className={styles.title}>{batch.researchDate} · {zh ? `${batch.symbols.length} 只股票` : `${batch.symbols.length} stocks`}</strong><span className={styles.hint}>{financialJobTime(batch.triggeredAt, zh)} · {zh ? `已完成 ${completed}/${batch.items.length}` : `${completed}/${batch.items.length} completed`}</span></div><VChip tone={financialBatchStatusTone(batch.status)}>{financialBatchStatusLabel(batch.status, zh)}</VChip><div className={styles.actions}>{ACTIVE_FINANCIAL_BATCH_STATUSES.has(batch.status) && batch.status !== "stop_requested" ? <VButton variant="secondary" isDisabled={Boolean(pending)} isPending={pending === batch.batchId} onPress={onStop}>{zh ? "停止批次" : "Stop batch"}</VButton> : retryable ? <VButton variant="secondary" isDisabled={Boolean(pending)} isPending={pending === batch.batchId} onPress={onRetry}>{zh ? "重试未完成" : "Retry unfinished"}</VButton> : null}</div></div>
    {batch.terminalReason ? <p className={styles.errorBox}>{batch.terminalReason}</p> : null}
    <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>{zh ? "股票" : "Stock"}</th><th>{zh ? "状态" : "Status"}</th><th>{zh ? "详情" : "Details"}</th></tr></thead><tbody>{batch.items.map((item) => <tr key={item.symbol}><td className={styles.stockCell}>{item.symbol}</td><td><VChip tone={financialBatchStatusTone(item.status)}>{financialBatchStatusLabel(item.status, zh)}</VChip>{item.terminalReason ? <p className={styles.reason}>{item.terminalReason}</p> : null}</td><td>{item.runId ? <VButton variant="ghost" onPress={() => onOpenRun(item.runId!, item.symbol)}>{item.status === "completed" ? (zh ? "查看结果" : "View result") : (zh ? "查看过程" : "View activity")}</VButton> : "—"}</td></tr>)}</tbody></table></div>
  </VSurface>;
}
