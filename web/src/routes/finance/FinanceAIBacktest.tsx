import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Play, Square, Download, RefreshCw } from "lucide-react";
import { downloadAIBacktest, fetchAIBacktest, fetchAIBacktests, financialBacktestKeys, previewAIBacktest, resumeAIBacktest, startAIBacktest, stopAIBacktest } from "../../api/financialBacktests";
import type { AIBacktestPreview, AIBacktestRequest, AIBacktestRun } from "../../api/types/financialBacktests";
import type { StockIdentity } from "../../api/types/financialMarket";
import { VButton, VDenseTable, VDialog, VInput, VSelect, VStateSurface, VSurface, VTextarea } from "../../components/vui";
import styles from "./FinanceAIBacktest.styles";

const ago = (days: number) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(Date.now() - days * 86400000));
const active = new Set(["queued", "running", "stop_requested"]);
const labels: Record<AIBacktestRun["status"], string> = { queued: "排队中", running: "运行中", stop_requested: "正在停止", stopped: "已停止", blocked: "条件不满足", paused_unknown: "调用结果待确认", failed: "失败", completed: "已完成" };
const pct = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}%` : "—";
const orderLabels: Record<string, string> = { filled: "已成交", rejected: "未成交", no_action: "无需调仓", next_session_open: "下日开盘成交", zero_volume_or_suspended: "零成交量或停牌", one_price_at_candidate_limit_up: "疑似一字涨停", one_price_at_candidate_limit_down: "疑似一字跌停", one_price_bar_unverified: "一字行情，无法核验成交", insufficient_cash_for_one_lot: "资金不足一手", no_sellable_board_lot: "没有可卖整手", same_cost_buy_and_hold_benchmark: "同成本买入持有" };
const message = (cause: unknown) => cause instanceof Error ? cause.message : "操作失败，请重试";

export function FinanceAIBacktest({ agentId, stock, zh, disabled }: { agentId: string; stock: StockIdentity; zh: boolean; disabled: boolean }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<AIBacktestRequest>({ symbol: stock.symbol, startDate: ago(90), endDate: ago(1), strategy: "只根据已完成的历史日线分析趋势和风险，控制回撤，选择下一交易日的目标仓位；证据不足时保持现金。", initialCash: 100000, maxPositionPct: 80, decisionInterval: 5, commissionBps: 3, minimumCommission: 5, slippageBps: 5, maxDecisions: 30, maxTokens: 500000 });
  const [preview, setPreview] = useState<AIBacktestPreview | null>(null), [selected, setSelected] = useState(""), [pending, setPending] = useState(""), [error, setError] = useState(""), [confirmRetry, setConfirmRetry] = useState(false);
  const gate = useRef(false), generation = useRef(0), mounted = useRef(true), startRequest = useRef({ previewId: "", id: "" });
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current += 1; }; }, []);
  const list = useInfiniteQuery({ queryKey: financialBacktestKeys.list(agentId), initialPageParam: undefined as string | undefined, queryFn: ({ pageParam, signal }) => fetchAIBacktests(agentId, pageParam, signal), getNextPageParam: page => page.nextCursor ?? undefined, retry: false, refetchInterval: query => query.state.data?.pages.some(page => page.items.some(run => active.has(run.status))) ? 3000 : false });
  const listed = list.data?.pages.flatMap(page => page.items).filter(run => run.symbol === stock.symbol) ?? [];
  const detail = useQuery({ queryKey: financialBacktestKeys.run(agentId, selected), queryFn: ({ signal }) => fetchAIBacktest(agentId, selected, signal), enabled: Boolean(selected), retry: false, refetchInterval: query => query.state.data && active.has(query.state.data.status) ? 2000 : false });
  const shown = detail.data?.agentId === agentId && detail.data.symbol === stock.symbol ? detail.data : null;
  const busy = Boolean(pending);
  const valid = draft.startDate < draft.endDate && draft.endDate < ago(0) && draft.strategy.trim().length > 0 && Object.values(draft).every(value => typeof value !== "number" || Number.isFinite(value));
  function edit<K extends keyof AIBacktestRequest>(key: K, value: AIBacktestRequest[K]) { generation.current += 1; setDraft(current => ({ ...current, [key]: value })); setPreview(null); setError(""); }
  async function perform(kind: string, work: () => Promise<void>) {
    if (gate.current) return;
    gate.current = true; setPending(kind); setError("");
    try { await work(); } catch (cause) { if (mounted.current) setError(message(cause)); }
    finally { gate.current = false; if (mounted.current) setPending(""); }
  }
  async function reconcile(run: AIBacktestRun) {
    if (run.agentId !== agentId || run.symbol !== stock.symbol) throw new Error("回测身份不匹配");
    if (!mounted.current) return;
    client.setQueryData(financialBacktestKeys.run(agentId, run.runId), run); setSelected(run.runId);
    await client.invalidateQueries({ queryKey: financialBacktestKeys.list(agentId) });
  }
  function number(key: keyof AIBacktestRequest, title: string, min: number, max: number, step = 1) { return <label className={styles.field}>{title}<VInput aria-label={title} type="number" min={min} max={max} step={step} value={String(draft[key])} disabled={busy} onChange={event => edit(key, Number(event.target.value))} /></label>; }
  return <div className={styles.page}>
    <p className={styles.note}>{zh ? "历史日线 → AI目标仓位 → 下日开盘撮合。独立模拟账户，支持停止、恢复和导出。" : "Historical bars → AI target weights → next-open execution. An independent simulation with stop, resume and export."}</p>
    <div className={styles.row}>
      <label className={styles.field}>{zh ? "开始" : "From"}<VInput aria-label="AI回测开始日期" type="date" max={ago(1)} value={draft.startDate} disabled={busy} onChange={event => edit("startDate", event.target.value)} /></label>
      <label className={styles.field}>{zh ? "结束" : "To"}<VInput aria-label="AI回测结束日期" type="date" max={ago(1)} value={draft.endDate} disabled={busy} onChange={event => edit("endDate", event.target.value)} /></label>
      {number("initialCash", zh ? "初始资金" : "Initial cash", 1000, 100000000)}
      {number("maxPositionPct", zh ? "仓位上限 %" : "Max position %", 0, 100)}
      <label className={styles.field}>{zh ? "决策频率" : "Frequency"}<VSelect aria-label="AI回测决策频率" selectedKey={String(draft.decisionInterval)} isDisabled={busy} className={styles.frequency} options={[{ id: "1", label: zh ? "每个交易日" : "Daily" }, { id: "5", label: zh ? "每5个交易日" : "Every 5 bars" }, { id: "20", label: zh ? "每20个交易日" : "Every 20 bars" }]} onSelectionChange={key => edit("decisionInterval", Number(key))} /></label>
      {number("commissionBps", zh ? "佣金 bps" : "Commission bps", 0, 100, 0.1)}
      {number("minimumCommission", zh ? "最低佣金" : "Minimum fee", 0, 100)}
      {number("slippageBps", zh ? "滑点 bps" : "Slippage bps", 0, 100, 0.1)}
      {number("maxDecisions", zh ? "最多决策" : "Decision limit", 1, 500)}
      {number("maxTokens", zh ? "Token预算" : "Token budget", 1000, 2000000, 1000)}
    </div>
    <label className={styles.panel}><span className={styles.status}>{zh ? "策略指令" : "Strategy instruction"}</span><VTextarea aria-label="AI回测策略指令" value={draft.strategy} maxLength={2000} disabled={busy} onChange={event => edit("strategy", event.target.value)} /></label>
    <div className={styles.row}><VButton variant="secondary" isPending={pending === "preview"} isDisabled={busy || disabled || !valid || /^(hk|us)/.test(stock.symbol)} onPress={() => void perform("preview", async () => { const expected = generation.current; const data = await previewAIBacktest(agentId, draft); if (mounted.current && generation.current === expected) { if (data.agentId !== agentId || data.symbol !== stock.symbol) throw new Error(zh ? "回测预检归属不匹配，请刷新后重试" : "Preview identity mismatch; refresh and retry"); setPreview(data); } })}>{zh ? "检查数据与预算" : "Check data and budget"}</VButton><span className={styles.note}>{zh ? "预检不调用模型。印花税按成交日期计算；1 bps = 0.01%。" : "Preview makes no model calls. Stamp duty follows execution dates; 1 bps = 0.01%."}</span></div>
    {preview ? <VSurface tone="panel" padding="normal" className={styles.panel}>
      <div className={styles.row}><strong>{preview.dateCoverage.actualStartDate} — {preview.dateCoverage.actualEndDate}</strong><span>{zh ? `${preview.dateCoverage.tradingDays}根日线 · ${preview.decisionCount}次决策` : `${preview.dateCoverage.tradingDays} bars · ${preview.decisionCount} decisions`}</span></div>
      <p className={styles.note}>{preview.modelId} · {zh ? "Token上限" : "Token limit"} {preview.maxTokens.toLocaleString()} · {zh ? "数据" : "Data"} {preview.dataHash.slice(0, 12)}</p>
      {preview.warnings.map((warning, index) => <p key={index} className={styles.note}>{warning}</p>)}
      {!preview.canStart ? <VStateSurface tone="error" density="compact" title={preview.blockReason || (zh ? "当前数据不满足回测条件" : "Data requirements not met")} /> : null}
      <VButton variant="primary" icon={<Play size={14} />} isPending={pending === "start"} isDisabled={busy || disabled || !preview.canStart || Date.parse(preview.expiresAt) <= Date.now()} onPress={() => void perform("start", async () => { if (startRequest.current.previewId !== preview.previewId) startRequest.current = { previewId: preview.previewId, id: crypto.randomUUID() }; await reconcile(await startAIBacktest(agentId, preview.previewId, startRequest.current.id)); setPreview(null); })}>{zh ? "开始AI回测" : "Start AI backtest"}</VButton>
      <p className={styles.note}>{zh ? "启动会使用当前模型额度。模型仅接收当时的行情与账户；训练知识的历史回溯偏差无法消除。" : "Starting consumes model quota. Inputs contain only contemporaneous bars and portfolio; training hindsight cannot be removed."}</p>
    </VSurface> : null}
    {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
    <div className={styles.row}><h3 className={styles.title}>{zh ? "回测记录" : "Backtest runs"}</h3><VButton variant="ghost" icon={<RefreshCw size={14} />} isDisabled={list.isFetching} onPress={() => void list.refetch()}>{zh ? "刷新" : "Refresh"}</VButton></div>
    {list.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取回测记录" : "Loading backtests"} /> : list.isError ? <VStateSurface tone="error" title={list.error.message} /> : !listed.length ? <VStateSurface tone="empty" density="compact" title={zh ? "这只股票还没有AI回测" : "No AI backtests for this stock"} /> : <div className={styles.row}>{listed.map(run => <VButton key={run.runId} variant={selected === run.runId ? "secondary" : "ghost"} onPress={() => { setSelected(run.runId); setError(""); }}>{labels[run.status]} · {new Date(run.startedAt || run.updatedAt).toLocaleString(zh ? "zh-CN" : "en-US")} · {run.completedDecisionCount}/{run.decisionCount}</VButton>)}</div>}
    {list.hasNextPage ? <VButton isPending={list.isFetchingNextPage} onPress={() => void list.fetchNextPage()}>{zh ? "更早的记录" : "Earlier runs"}</VButton> : null}
    {selected && detail.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取回测详情" : "Loading run"} /> : detail.isError ? <VStateSurface tone="error" title={detail.error.message} actions={<VButton onPress={() => void detail.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : null}
    {shown ? <VSurface tone="panel" padding="normal" className={styles.panel}>
      <div className={styles.row}><strong>{labels[shown.status]}</strong><span>{shown.completedDecisionCount}/{shown.decisionCount} · {shown.currentDecisionDate || "—"}</span><span className={styles.note}>{zh ? "调用" : "Calls"} {shown.callsUsed} · {shown.tokenAccounting === "estimated" ? (zh ? "Token估算" : "Estimated tokens") : shown.tokenAccounting === "reserved" ? (zh ? "Token预留" : "Reserved tokens") : "Token"} {shown.tokensUsed.toLocaleString()}/{shown.maxTokens.toLocaleString()}</span>
        {active.has(shown.status) ? <VButton icon={<Square size={14} />} isDisabled={busy || shown.status === "stop_requested"} isPending={pending === "stop"} onPress={() => void perform("stop", async () => reconcile(await stopAIBacktest(agentId, shown.runId)))}>{zh ? "停止" : "Stop"}</VButton> : ["stopped", "paused_unknown"].includes(shown.status) ? <VButton icon={<Play size={14} />} isDisabled={busy} onPress={() => { if (shown.status === "paused_unknown") setConfirmRetry(true); else void perform("resume", async () => reconcile(await resumeAIBacktest(agentId, shown.runId))); }}>{zh ? "继续未完成部分" : "Resume unfinished"}</VButton> : null}
        <VButton variant="ghost" icon={<Download size={14} />} isDisabled={busy} onPress={() => void perform("export", () => downloadAIBacktest(agentId, shown.runId, "json"))}>JSON</VButton><VButton variant="ghost" icon={<Download size={14} />} isDisabled={busy} onPress={() => void perform("export", () => downloadAIBacktest(agentId, shown.runId, "csv"))}>CSV</VButton>
      </div>
      {active.has(shown.status) ? <progress className={styles.progress} aria-label="AI回测进度" value={shown.completedDecisionCount} max={Math.max(1, shown.decisionCount)} /> : null}
      {shown.terminalReason ? <VStateSurface tone={shown.status === "completed" ? "empty" : "error"} density="compact" title={shown.terminalReason} /> : null}
      {shown.metrics ? <BacktestResult run={shown} zh={zh} /> : null}
      <div className={styles.table}><VDenseTable ariaLabel="AI回测历史决策" rows={shown.decisions} getRowKey={row => row.date} emptyText={zh ? "还没有成功的模型决策" : "No accepted decisions yet"} columns={[{ id: "date", header: zh ? "决策日" : "Decision date", render: row => row.date }, { id: "weight", header: zh ? "目标仓位" : "Target weight", render: row => pct(row.targetWeight) }, { id: "reason", header: zh ? "依据" : "Reason", render: row => <span className={styles.reason}>{row.reason}</span> }]} /></div>
      <div className={styles.table}><VDenseTable ariaLabel="AI回测订单审计" rows={[...shown.orders.map(row => ({ ...row, account: "strategy" })), ...(shown.benchmarkOrders ?? []).map(row => ({ ...row, account: "benchmark" }))]} getRowKey={row => `${row.account}:${row.date}:${row.side}`} emptyText={zh ? "没有订单" : "No orders"} columns={[{ id: "date", header: zh ? "执行日" : "Execution", render: row => row.date }, { id: "account", header: zh ? "账户" : "Account", render: row => row.account === "benchmark" ? (zh ? "持有基准" : "Benchmark") : (zh ? "AI策略" : "Strategy") }, { id: "side", header: zh ? "方向" : "Side", render: row => row.side === "buy" ? (zh ? "买入" : "Buy") : row.side === "sell" ? (zh ? "卖出" : "Sell") : "—" }, { id: "status", header: zh ? "状态" : "Status", render: row => zh ? (orderLabels[row.status] || row.status) : row.status }, { id: "reason", header: zh ? "执行说明" : "Reason", render: row => row.reason ? (zh ? (orderLabels[row.reason] || row.reason) : row.reason) : "—" }]} /></div>
      <p className={styles.note}>{shown.modelId} · {zh ? "参数" : "Params"} {shown.paramsHash.slice(0, 12)} · {zh ? "数据" : "Data"} {shown.dataHash.slice(0, 12)}</p>
      {shown.notice ? <p className={styles.note}>{shown.notice}</p> : null}{shown.warnings?.map((warning, index) => <p key={index} className={styles.note}>{warning}</p>)}
    </VSurface> : null}
    <VDialog open={confirmRetry} onOpenChange={setConfirmRetry} title={zh ? "确认重试未落盘的模型调用" : "Retry an uncertain model call"} footer={<VButton variant="primary" isPending={pending === "resume"} isDisabled={busy || !shown?.currentDecisionDate} onPress={() => { if (!shown?.currentDecisionDate) return; void perform("resume", async () => { await reconcile(await resumeAIBacktest(agentId, shown.runId, { retryUnknownDecisionDate: shown.currentDecisionDate!, confirmPossibleDuplicateCharge: true })); setConfirmRetry(false); }); }}>{zh ? "确认可能重复计费并重试" : "Accept possible duplicate charge and retry"}</VButton>}><p className={styles.note}>{zh ? `${shown?.currentDecisionDate || ""} 的模型调用没有可靠结果，可能已经计费。继续将只重试这一时点，保留已成功决策。` : "This invocation has no reliable result and may already have been billed. Retry only this date; accepted decisions stay unchanged."}</p></VDialog>
  </div>;
}

function BacktestResult({ run, zh }: { run: AIBacktestRun; zh: boolean }) {
  const metrics = run.metrics!;
  const values = run.equity.flatMap(point => [point.equity, point.benchmarkEquity]), min = Math.min(...values), max = Math.max(...values);
  const points = (key: "equity" | "benchmarkEquity") => run.equity.map((point, index) => `${10 + index * 580 / Math.max(1, run.equity.length - 1)},${150 - (point[key] - min) * 130 / Math.max(1, max - min)}`).join(" ");
  return <>
    <div className={styles.row}><strong>{zh ? "策略收益" : "Return"} {pct(metrics.totalReturnPct)}</strong><span>{zh ? "持有基准" : "Benchmark"} {pct(metrics.benchmarkReturnPct)}</span><span>{zh ? "超额" : "Excess"} {pct(metrics.excessReturnPct)}</span><span>{zh ? "最大回撤" : "Drawdown"} {pct(metrics.maxDrawdownPct)}</span><span>{zh ? "年化" : "Annualized"} {pct(metrics.annualizedReturnPct)}</span><span>Sharpe {metrics.sharpeRatio?.toFixed(2) ?? "—"}</span><span>{zh ? "费用" : "Fees"} {metrics.fees.toFixed(2)}</span></div>
    {run.equity.length ? <svg viewBox="0 0 600 170" className={styles.chart} role="img" aria-label="AI回测净值与持有基准"><polyline points={points("benchmarkEquity")} fill="none" stroke="currentColor" strokeDasharray="4 3" opacity="0.4" strokeWidth="2" /><polyline points={points("equity")} fill="none" stroke="currentColor" strokeWidth="2" /></svg> : null}
    <p className={styles.note}>{zh ? "实线：策略净值；虚线：相同撮合成本下的买入持有。期末持仓按收盘估值。" : "Solid: strategy; dashed: buy-and-hold with the same execution costs. Final holdings marked to close."}</p>
    <div className={styles.table}><VDenseTable ariaLabel="AI回测成交" rows={run.trades} getRowKey={row => `${row.date}:${row.side}`} emptyText={zh ? "没有成交" : "No fills"} columns={[{ id: "signal", header: zh ? "信号日" : "Signal", render: row => row.signalDate }, { id: "date", header: zh ? "成交日" : "Fill", render: row => row.date }, { id: "side", header: zh ? "方向" : "Side", render: row => row.side === "buy" ? (zh ? "买入" : "Buy") : (zh ? "卖出" : "Sell") }, { id: "price", header: zh ? "成交价" : "Price", render: row => row.price.toFixed(3) }, { id: "units", header: zh ? "股数" : "Shares", render: row => row.units.toLocaleString() }, { id: "fee", header: zh ? "费用" : "Fees", render: row => row.fee.toFixed(2) }]} /></div>
  </>;
}
