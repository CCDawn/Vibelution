import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { FinanceBacktestAdvancedEvaluation } from "./FinanceBacktestAdvancedEvaluation";
import { FinanceBacktestRobustness } from "./FinanceBacktestRobustness";
import { FinanceWalkForward } from "./FinanceWalkForward";
import { Download, GitCompareArrows, Play, RefreshCw, Square, X } from "lucide-react";
import { downloadAIBacktest, fetchAIBacktest, fetchAIBacktests, financialBacktestKeys, previewAIBacktest, resumeAIBacktest, startAIBacktest, stopAIBacktest } from "../../api/financialBacktests";
import type { AIBacktestDateCoverage, AIBacktestParams, AIBacktestPreview, AIBacktestRequest, AIBacktestRun } from "../../api/types/financialBacktests";
import type { StockIdentity } from "../../api/types/financialMarket";
import { VButton, VChip, VDenseTable, VDialog, VInput, VSelect, VStateSurface, VSurface, VTextarea } from "../../components/vui";
import { FinanceBacktestComparison } from "./FinanceBacktestComparison";
import { FinanceBacktestForkDialog } from "./FinanceBacktestForkDialog";
import { parseFinancialBatchSymbols } from "./financialJobModel";
import styles from "./FinanceAIBacktest.styles";

const ago = (days: number) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(Date.now() - days * 86400000));
const active = new Set(["queued", "running", "stop_requested"]);
const labels: Record<AIBacktestRun["status"], string> = { queued: "排队中", running: "运行中", stop_requested: "正在停止", stopped: "已停止", blocked: "条件不满足", paused_unknown: "调用结果待确认", failed: "失败", completed: "已完成" };
const pct = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}%` : "—";
const orderLabels: Record<string, string> = { below_board_minimum_buy: "不足板块最低买入量", volume_participation_below_minimum_order: "成交量额度不足最低申报量", order_quantity_below_minimum: "申报额度不足最低数量", insufficient_cash_for_minimum_order: "资金不足最低申报量", volume_participation_below_sell_increment: "成交量额度不足卖出单位", order_quantity_below_sell_increment: "申报额度不足卖出单位", below_minimum_sell_order: "不足最低卖出量", no_sellable_quantity: "没有可卖数量", order_and_volume_quantity_limit: "申报与成交量上限", order_quantity_limit: "单笔申报数量上限", board_sell_increment_limit: "卖出数量单位限制", filled: "已成交", partial_fill: "部分成交", daily_volume_participation_limit: "日成交量上限", volume_participation_below_one_lot: "日成交量额度不足一手", rejected: "未成交", no_action: "无需调仓", next_session_open: "下日开盘成交", zero_volume_or_suspended: "零成交量或停牌", one_price_at_candidate_limit_up: "疑似一字涨停", one_price_at_candidate_limit_down: "疑似一字跌停", one_price_bar_unverified: "一字行情，无法核验成交", insufficient_cash_for_one_lot: "资金不足一手", no_sellable_board_lot: "没有可卖整手", target_shares_unchanged: "目标仓位未变", cash_limited_board_lots: "可用资金限制成交股数", same_cost_buy_and_hold_benchmark: "同成本买入持有" };
const message = (cause: unknown) => cause instanceof Error ? cause.message : "操作失败，请重试";
const isAShare = (symbol: string) => /^(?:sh|sz|bj)\d{6}$/i.test(symbol);
const statusLabel = (status: AIBacktestRun["status"], zh: boolean) => zh ? labels[status] : ({ queued: "Queued", running: "Running", stop_requested: "Stopping", stopped: "Stopped", blocked: "Blocked", paused_unknown: "Uncertain call", failed: "Failed", completed: "Completed" } satisfies Record<AIBacktestRun["status"], string>)[status];
const symbolsForRun = (run: Pick<AIBacktestRun, "symbol" | "symbols">) => run.symbols?.length ? run.symbols : run.symbol ? [run.symbol] : [];
const assetLabel = (symbols: string[], zh: boolean) => symbols.length > 1 ? `${zh ? "组合" : "Basket"} · ${symbols.length} ${zh ? "只" : "stocks"} · ${symbols.slice(0, 3).join(" / ")}${symbols.length > 3 ? " …" : ""}` : symbols[0] || (zh ? "未知标的" : "Unknown asset");
const quantityLabel = (params: AIBacktestParams | undefined, zh: boolean) => !params ? (zh ? "撮合规则未提供" : "Execution rules unavailable") : params.quantityRuleVersion === "ashare_quantity_v2" ? (zh ? "按板块股数规则" : "Board-specific quantities") : (zh ? "旧版100股规则" : "Legacy 100-share rules");

type BacktestForm = AIBacktestParams & { startDate: string; endDate: string; dataSource?: "tencent" | "eastmoney" | "sina" | "auto"; researchInput?: "price_only" | "announcements" | "financial_reports" };

export function FinanceAIBacktest({ agentId, stock, zh, disabled }: { agentId: string; stock: StockIdentity; zh: boolean; disabled: boolean }) {
  const client = useQueryClient();
  const [form, setForm] = useState<BacktestForm>({ startDate: ago(90), endDate: ago(1), strategy: "只根据已完成的历史日线分析趋势和风险，控制回撤，选择下一交易日的目标仓位；证据不足时保持现金。", initialCash: 100000, maxPositionPct: 80, maxParticipationPct: 1, researchInput: "price_only", decisionInterval: 5, commissionBps: 3, minimumCommission: 5, slippageBps: 5, maxDecisions: 30, maxTokens: 500000 });
  const [scope, setScope] = useState<"single" | "portfolio">("single");
  const [symbolsText, setSymbolsText] = useState(stock.symbol);
  const [preview, setPreview] = useState<AIBacktestPreview | null>(null), [selected, setSelected] = useState(""), [pending, setPending] = useState(""), [error, setError] = useState(""), [confirmRetry, setConfirmRetry] = useState(false), [forkOpen, setForkOpen] = useState(false);
  const gate = useRef(false), generation = useRef(0), mounted = useRef(true), startRequest = useRef({ previewId: "", id: "" }), portfolioEdited = useRef(false), previousStock = useRef(stock.symbol);
  const parsed = parseFinancialBatchSymbols(symbolsText);
  const inputTokens = symbolsText.trim().split(/[\s,，;；]+/).filter(Boolean);
  const normalizedTokens = inputTokens.map(token => parseFinancialBatchSymbols(token).symbols[0]).filter((symbol): symbol is string => Boolean(symbol));
  const hasDuplicateSymbols = new Set(normalizedTokens).size !== normalizedTokens.length;
  const invalidMarketSymbols = parsed.symbols.filter(symbol => !isAShare(symbol));
  const portfolioError = parsed.invalid.length ? `${zh ? "无法识别代码" : "Invalid codes"}: ${parsed.invalid.slice(0, 3).join("、")}` : invalidMarketSymbols.length ? (zh ? "AI组合回测仅支持沪、深、北交所 A 股" : "AI basket backtests support Shanghai, Shenzhen and Beijing A-shares only") : hasDuplicateSymbols ? (zh ? "组合内不能重复选择同一股票" : "A basket cannot contain a symbol twice") : parsed.symbols.length < 2 ? (zh ? "组合回测至少选择 2 只 A 股" : "Choose at least 2 A-shares") : parsed.symbols.length > 10 ? (zh ? "组合回测最多选择 10 只 A 股" : "Choose no more than 10 A-shares") : "";
  const busy = Boolean(pending);
  const numericValid = (form.maxParticipationPct ?? 1) >= 0.1 && (form.maxParticipationPct ?? 1) <= 100 && form.initialCash >= 1000 && form.initialCash <= 100_000_000 && form.maxPositionPct >= 0 && form.maxPositionPct <= 100 && [1, 5, 20].includes(form.decisionInterval) && form.commissionBps >= 0 && form.commissionBps <= 100 && form.minimumCommission >= 0 && form.minimumCommission <= 100 && form.slippageBps >= 0 && form.slippageBps <= 100 && Number.isInteger(form.maxDecisions) && form.maxDecisions >= 1 && form.maxDecisions <= 500 && Number.isInteger(form.maxTokens) && form.maxTokens >= 1000 && form.maxTokens <= 2_000_000;
  const valid = Boolean(form.startDate && form.endDate && form.startDate < form.endDate && form.endDate < ago(0)) && (!form.outOfSampleStartDate || (form.outOfSampleStartDate > form.startDate && form.outOfSampleStartDate <= form.endDate)) && form.strategy.trim().length > 0 && form.strategy.length <= 2000 && numericValid && (scope === "single" ? isAShare(stock.symbol) : !portfolioError);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current += 1; }; }, []);
  useEffect(() => {
    if (previousStock.current === stock.symbol) return;
    previousStock.current = stock.symbol;
    generation.current += 1; setPreview(null); setError("");
    if (!portfolioEdited.current) setSymbolsText(stock.symbol);
  }, [stock.symbol]);

  const list = useInfiniteQuery({ queryKey: financialBacktestKeys.list(agentId), initialPageParam: undefined as string | undefined, queryFn: ({ pageParam, signal }) => fetchAIBacktests(agentId, pageParam, signal), getNextPageParam: page => page.nextCursor ?? undefined, retry: false, refetchInterval: query => query.state.data?.pages.some(page => page.items.some(run => active.has(run.status))) ? 3000 : false });
  const listed = list.data?.pages.flatMap(page => page.items) ?? [];
  const detail = useQuery({ queryKey: financialBacktestKeys.run(agentId, selected), queryFn: ({ signal }) => fetchAIBacktest(agentId, selected, signal), enabled: Boolean(selected), retry: false, refetchInterval: query => query.state.data && active.has(query.state.data.status) ? 2000 : false });
  const shown = detail.data?.agentId === agentId && detail.data.runId === selected ? detail.data : null;

  function edit<K extends keyof BacktestForm>(key: K, value: BacktestForm[K]) {
    generation.current += 1; setForm(current => ({ ...current, [key]: value })); setPreview(null); setError("");
  }
  function changeScope(value: "single" | "portfolio") {
    if (value === scope) return;
    generation.current += 1; setScope(value); setPreview(null); setError("");
  }
  function editSymbols(value: string) {
    portfolioEdited.current = true; generation.current += 1; setSymbolsText(value); setPreview(null); setError("");
  }
  function buildRequest(): AIBacktestRequest {
    const { startDate, endDate, outOfSampleStartDate, ...params } = form;
    const request = { ...params, startDate, endDate, ...(outOfSampleStartDate ? { outOfSampleStartDate } : {}) };
    return scope === "single" ? { ...request, symbol: stock.symbol } : { ...request, symbols: parsed.symbols };
  }
  function requestSymbols(request: AIBacktestRequest): string[] {
    return "symbols" in request && Array.isArray(request.symbols) ? [...request.symbols].sort() : [request.symbol as string];
  }
  function resultMatchesSymbols(value: Pick<AIBacktestPreview | AIBacktestRun, "symbol" | "symbols">, expected: string[]) {
    const actual = symbolsForRun(value).map(symbol => symbol.toLowerCase()).sort();
    return actual.length === expected.length && actual.every((symbol, index) => symbol === expected[index].toLowerCase());
  }
  async function perform(kind: string, work: () => Promise<void>) {
    if (gate.current) return;
    gate.current = true; setPending(kind); setError("");
    try { await work(); } catch (cause) { if (mounted.current) setError(message(cause)); }
    finally { gate.current = false; if (mounted.current) setPending(""); }
  }
  async function reconcile(run: AIBacktestRun) {
    if (run.agentId !== agentId) throw new Error("回测智能体身份不匹配");
    if (!mounted.current) return;
    client.setQueryData(financialBacktestKeys.run(agentId, run.runId), run); setSelected(run.runId);
    await client.invalidateQueries({ queryKey: financialBacktestKeys.list(agentId) });
  }
  function number(key: keyof BacktestForm, title: string, min: number, max: number, step = 1) {
    return <label className={styles.field}>{title}<VInput aria-label={title} type="number" min={min} max={max} step={step} value={String(form[key])} disabled={busy} onChange={event => edit(key, Number(event.target.value))} /></label>;
  }
  function removeSymbol(symbol: string) {
    const tokens = symbolsText.trim().split(/[\s,，;；]+/).filter(Boolean);
    editSymbols(tokens.filter(token => parseFinancialBatchSymbols(token).symbols[0] !== symbol).join(", "));
  }
  function addCurrentStock() {
    if (!isAShare(stock.symbol) || parsed.symbols.includes(stock.symbol)) return;
    editSymbols([...parsed.symbols, stock.symbol].join(", "));
  }
  return <div className={styles.page}>
    <p className={styles.note}>{zh ? "历史日线 → AI目标仓位 → 下日开盘撮合。独立模拟账户，不连接券商；支持单股或组合、停止续跑和结果导出。" : "Historical bars → AI target weights → next-open execution. Independent simulation, no broker connection; single-stock or basket runs can be stopped, resumed and exported."}</p>
    <div className={styles.row}>
      <label className={styles.field}>{zh ? "历史行情源" : "Historical source"}<VSelect aria-label="AI回测历史行情源" selectedKey={form.dataSource ?? "tencent"} isDisabled={busy} className={styles.scopeSelect} options={[{ id: "tencent", label: "腾讯财经" }, { id: "eastmoney", label: "东方财富" }, { id: "sina", label: "新浪财经" }, { id: "auto", label: zh ? "自动备用（整段切换）" : "Whole-snapshot fallback" }]} onSelectionChange={key => edit("dataSource", String(key) as "tencent" | "eastmoney" | "sina" | "auto")} /></label>
      <label className={styles.field}>{zh ? "回测范围" : "Scope"}<VSelect aria-label={zh ? "AI回测范围" : "AI backtest scope"} selectedKey={scope} isDisabled={busy} className={styles.scopeSelect} options={[{ id: "single", label: zh ? "单股" : "Single stock" }, { id: "portfolio", label: zh ? "组合" : "Portfolio" }]} onSelectionChange={key => changeScope(String(key ?? "single") as "single" | "portfolio")} /></label>
      {scope === "single" ? <span className={styles.note}>{stock.name} · {stock.symbol}</span> : <span className={styles.note}>{zh ? "按同一交易日历并行组合；每次决策需给全部股票分配目标仓位。" : "Assets share a trading calendar; each decision allocates a target weight to every stock."}</span>}
    </div>
    {scope === "portfolio" ? <div className={styles.panel}>
      <label className={styles.field}>{zh ? "组合股票代码" : "Portfolio symbols"}<VInput aria-label={zh ? "组合股票代码" : "Portfolio symbols"} value={symbolsText} disabled={busy} placeholder="sh600519, sz000001" onChange={event => editSymbols(event.target.value)} /></label>
      <div className={styles.row}>
        <span className={styles.note}>{zh ? `已选 ${parsed.symbols.length}/10 只` : `${parsed.symbols.length}/10 selected`}</span>
        <VButton variant="ghost" isDisabled={busy || !isAShare(stock.symbol) || parsed.symbols.includes(stock.symbol)} onPress={addCurrentStock}>{zh ? `加入当前股票 ${stock.ticker}` : `Add current stock ${stock.ticker}`}</VButton>
      </div>
      {parsed.symbols.length ? <div className={styles.assetList}>{parsed.symbols.map(symbol => <span key={symbol} className={styles.assetChip}><VChip>{symbol}</VChip><VButton type="button" variant="ghost" isIconOnly aria-label={zh ? `移除 ${symbol}` : `Remove ${symbol}`} isDisabled={busy} onPress={() => removeSymbol(symbol)} icon={<X size={13} aria-hidden="true" />} /></span>)}</div> : null}
      {portfolioError ? <VStateSurface tone="error" density="compact" title={portfolioError} /> : null}
    </div> : null}
    <div className={styles.row}>
      <label className={styles.field}>{zh ? "开始" : "From"}<VInput aria-label="AI回测开始日期" type="date" max={ago(1)} value={form.startDate} disabled={busy} onChange={event => edit("startDate", event.target.value)} /></label>
      <label className={styles.field}>{zh ? "结束" : "To"}<VInput aria-label="AI回测结束日期" type="date" max={ago(1)} value={form.endDate} disabled={busy} onChange={event => edit("endDate", event.target.value)} /></label>
      <label className={styles.field}>{zh ? "样本外起点（可选）" : "Holdout start (optional)"}<VInput aria-label="AI回测样本外起点" type="date" min={form.startDate} max={form.endDate} value={form.outOfSampleStartDate ?? ""} disabled={busy} onChange={event => edit("outOfSampleStartDate", event.target.value || undefined)} /></label>
      {number("initialCash", zh ? "初始资金" : "Initial cash", 1000, 100000000)}
      {number("maxPositionPct", scope === "portfolio" ? (zh ? "单股上限 %" : "Per-stock cap %") : (zh ? "仓位上限 %" : "Max position %"), 0, 100)}
      <label className={styles.field}>{zh ? "决策频率" : "Frequency"}<VSelect aria-label="AI回测决策频率" selectedKey={String(form.decisionInterval)} isDisabled={busy} className={styles.frequency} options={[{ id: "1", label: zh ? "每个交易日" : "Daily" }, { id: "5", label: zh ? "每5个交易日" : "Every 5 bars" }, { id: "20", label: zh ? "每20个交易日" : "Every 20 bars" }]} onSelectionChange={key => edit("decisionInterval", Number(key))} /></label>
      {number("commissionBps", zh ? "佣金 bps" : "Commission bps", 0, 100, 0.1)}
      {number("minimumCommission", zh ? "最低佣金" : "Minimum fee", 0, 100)}
      {number("slippageBps", zh ? "滑点 bps" : "Slippage bps", 0, 100, 0.1)}
      {number("maxParticipationPct", zh ? "日成交量上限 %" : "Daily volume cap %", 0.1, 100, 0.1)}
      <label className={styles.field}>{zh ? "研究输入" : "Research input"}<VSelect aria-label="AI回测研究输入" selectedKey={form.researchInput ?? "price_only"} isDisabled={busy} options={[{ id: "price_only", label: zh ? "仅行情" : "Prices only" }, { id: "announcements", label: zh ? "行情 + 历史公告" : "Prices + historical announcements" }, { id: "financial_reports", label: zh ? "行情 + 历史财报原文" : "Prices + historical filings" }]} onSelectionChange={key => edit("researchInput", String(key) as "price_only" | "announcements" | "financial_reports")} /></label>
      {number("maxDecisions", zh ? "最多决策" : "Decision limit", 1, 500)}
      {number("maxTokens", zh ? "Token预算" : "Token budget", 1000, 2000000, 1000)}
    </div>
    <p className={styles.note}>{zh ? "样本外日期留空时按 80/20 切分；预检会冻结实际交易日边界。" : "Leave the holdout date empty for an 80/20 split; preview freezes the actual trading-day boundary."}</p>
    <label className={styles.panel}><span className={styles.status}>{zh ? "策略指令" : "Strategy instruction"}</span><VTextarea aria-label="AI回测策略指令" value={form.strategy} maxLength={2000} disabled={busy} onChange={event => edit("strategy", event.target.value)} /></label>
    <div className={styles.row}><VButton variant="secondary" isPending={pending === "preview"} isDisabled={busy || disabled || !valid} onPress={() => void perform("preview", async () => {
      const expectedGeneration = generation.current, request = buildRequest(), expectedSymbols = requestSymbols(request);
      const data = await previewAIBacktest(agentId, request);
      if (!mounted.current || generation.current !== expectedGeneration) return;
      if (data.agentId !== agentId || !resultMatchesSymbols(data, expectedSymbols)) throw new Error(zh ? "回测预检标的或归属不匹配，请刷新后重试" : "Preview asset or owner mismatch; refresh and retry");
      setPreview(data);
    })}>{zh ? "检查数据与预算" : "Check data and budget"}</VButton><span className={styles.note}>{zh ? "预检不调用模型。印花税按成交日期计算；1 bps = 0.01%。" : "Preview makes no model calls. Stamp duty follows execution dates; 1 bps = 0.01%."}</span></div>
    {preview ? <VSurface tone="panel" padding="normal" className={styles.panel}>
      <div className={styles.row}><strong>{assetLabel(symbolsForRun(preview), zh)}</strong><span>{zh ? "共同区间" : "Common period"} {preview.dateCoverage.actualStartDate} — {preview.dateCoverage.actualEndDate}</span><span>{zh ? `${preview.dateCoverage.tradingDays} 个交易日 · ${preview.decisionCount} 次决策` : `${preview.dateCoverage.tradingDays} sessions · ${preview.decisionCount} decisions`}</span></div>
      <div className={styles.row}><span>{zh ? "样本外起点" : "Holdout starts"} {preview.outOfSampleStartDate || "—"}</span><span>{zh ? "模型" : "Model"} {preview.modelId}</span><span>{zh ? "预计 Token" : "Estimated tokens"} {typeof preview.estimatedTokens === "number" ? preview.estimatedTokens.toLocaleString() : "—"} / {preview.maxTokens.toLocaleString()}</span><span>{zh ? "数据哈希" : "Data hash"} {preview.dataHash.slice(0, 12)}</span></div>
      <AssetCoverageTable coverage={preview.assetCoverage} fallback={preview.dateCoverage} sources={preview.assetSources} symbols={symbolsForRun(preview)} zh={zh} />
      {preview.researchCoverage ? <p className={styles.note}>{zh ? `${preview.researchInput === "financial_reports" ? "财报原文" : "历史公告"} · ${preview.researchCoverage.itemCount} 条 · ${preview.researchCoverage.groupCount} 组 · ${preview.researchCoverage.status === "partial" ? "覆盖不完整" : "已冻结"}` : `Historical evidence · ${preview.researchCoverage.itemCount} items · ${preview.researchCoverage.status}`}</p> : null}
      {preview.warnings.map((warning, index) => <p key={index} className={styles.note}>{warning}</p>)}
      <span className={styles.note}>{quantityLabel(preview.params, zh)}</span>
      {!preview.canStart ? <VStateSurface tone="error" density="compact" title={preview.blockReason || (zh ? "当前数据不满足回测条件" : "Data requirements not met")} /> : null}
      <VButton variant="primary" icon={<Play size={14} />} isPending={pending === "start"} isDisabled={busy || disabled || !preview.canStart || Date.parse(preview.expiresAt) <= Date.now()} onPress={() => void perform("start", async () => {
        if (startRequest.current.previewId !== preview.previewId) startRequest.current = { previewId: preview.previewId, id: crypto.randomUUID() };
        const run = await startAIBacktest(agentId, preview.previewId, startRequest.current.id);
        if (run.agentId !== agentId || !resultMatchesSymbols(run, symbolsForRun(preview))) throw new Error(zh ? "回测启动结果标的或归属不匹配" : "Started run asset or owner mismatch");
        await reconcile(run); setPreview(null);
      })}>{zh ? "开始AI回测" : "Start AI backtest"}</VButton>
      <p className={styles.note}>{zh ? "启动会使用当前模型额度。模型使用冻结行情、账户及所选历史证据；训练知识的历史回溯偏差无法消除。" : "Starting consumes model quota. The model receives frozen bars, portfolio and selected historical evidence; training-data hindsight cannot be removed."}</p>
    </VSurface> : null}
    {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
    <div className={styles.row}><h3 className={styles.title}>{zh ? "回测记录 · 当前智能体" : "Backtest history · this agent"}</h3><VButton variant="ghost" icon={<RefreshCw size={14} />} isDisabled={list.isFetching} onPress={() => void list.refetch()}>{zh ? "刷新" : "Refresh"}</VButton></div>
    {list.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取回测记录" : "Loading backtests"} /> : list.isError ? <VStateSurface tone="error" title={list.error.message} /> : !listed.length ? <VStateSurface tone="empty" density="compact" title={zh ? "当前智能体还没有AI回测" : "No AI backtests for this agent"} /> : <div className={styles.history}>{listed.map(run => <VButton key={run.runId} variant={selected === run.runId ? "secondary" : "ghost"} onPress={() => { setSelected(run.runId); setError(""); }}>{statusLabel(run.status, zh)} · {assetLabel(symbolsForRun(run), zh)} · {new Date(run.startedAt || run.updatedAt).toLocaleString(zh ? "zh-CN" : "en-US")} · {run.completedDecisionCount}/{run.decisionCount}</VButton>)}</div>}
    {listed.length > 1 ? <FinanceBacktestComparison agentId={agentId} runs={listed} zh={zh} /> : null}
    <FinanceWalkForward key={agentId} agentId={agentId} sourceRunId={shown?.runId} zh={zh} onSelectRun={id => setSelected(id)} />
    {list.hasNextPage ? <VButton isPending={list.isFetchingNextPage} onPress={() => void list.fetchNextPage()}>{zh ? "更早的记录" : "Earlier runs"}</VButton> : null}
    {selected && detail.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取回测详情" : "Loading run"} /> : detail.isError ? <VStateSurface tone="error" title={detail.error.message} actions={<VButton onPress={() => void detail.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : null}
    {shown ? <VSurface tone="panel" padding="normal" className={styles.panel}>
      <div className={styles.row}><strong>{statusLabel(shown.status, zh)} · {assetLabel(symbolsForRun(shown), zh)}</strong><span>{shown.completedDecisionCount}/{shown.decisionCount} · {shown.currentDecisionDate || "—"}</span><span className={styles.note}>{zh ? "调用" : "Calls"} {shown.callsUsed} · {shown.tokenAccounting === "estimated" ? (zh ? "Token估算" : "Estimated tokens") : shown.tokenAccounting === "reserved" ? (zh ? "Token预留" : "Reserved tokens") : "Token"} {shown.tokensUsed.toLocaleString()}/{shown.maxTokens.toLocaleString()}</span>
        {active.has(shown.status) ? <VButton icon={<Square size={14} />} isDisabled={busy || shown.status === "stop_requested"} isPending={pending === "stop"} onPress={() => void perform("stop", async () => reconcile(await stopAIBacktest(agentId, shown.runId)))}>{zh ? "停止" : "Stop"}</VButton> : ["stopped", "paused_unknown"].includes(shown.status) ? <VButton icon={<Play size={14} />} isDisabled={busy} onPress={() => { if (shown.status === "paused_unknown") setConfirmRetry(true); else void perform("resume", async () => reconcile(await resumeAIBacktest(agentId, shown.runId))); }}>{zh ? "继续未完成部分" : "Resume unfinished"}</VButton> : null}
        <VButton variant="ghost" icon={<GitCompareArrows size={14} />} isDisabled={busy || !shown.dataHash} onPress={() => setForkOpen(true)}>{zh ? "创建同数据副本" : "Fork same data"}</VButton>
        <VButton variant="ghost" icon={<Download size={14} />} isDisabled={busy} onPress={() => void perform("export", () => downloadAIBacktest(agentId, shown.runId, "json"))}>JSON</VButton><VButton variant="ghost" icon={<Download size={14} />} isDisabled={busy} onPress={() => void perform("export", () => downloadAIBacktest(agentId, shown.runId, "csv"))}>CSV</VButton>
      </div>
      {active.has(shown.status) ? <progress className={styles.progress} aria-label="AI回测进度" value={shown.completedDecisionCount} max={Math.max(1, shown.decisionCount)} /> : null}
      {shown.terminalReason ? <VStateSurface tone={shown.status === "completed" ? "empty" : "error"} density="compact" title={shown.terminalReason} /> : null}
      {shown.metrics ? <BacktestResult run={shown} zh={zh} /> : null}
      {shown.advancedEvaluation ? <FinanceBacktestAdvancedEvaluation key={`${shown.runId}:advanced`} result={shown.advancedEvaluation} zh={zh} /> : null}
      <AssetCoverageTable coverage={shown.assetCoverage} fallback={shown.dateCoverage} sources={shown.assetSources} symbols={symbolsForRun(shown)} zh={zh} />
      <div className={styles.table}><VDenseTable ariaLabel="AI回测历史决策" rows={shown.decisions} getRowKey={row => row.date} emptyText={zh ? "还没有成功的模型决策" : "No accepted decisions yet"} columns={[{ id: "date", header: zh ? "决策日" : "Decision date", render: row => row.date }, { id: "weight", header: zh ? "目标仓位" : "Target weights", render: row => row.targetWeights ? Object.entries(row.targetWeights).map(([symbol, weight]) => `${symbol} ${pct(weight)}`).join(" · ") : `${shown.symbol || symbolsForRun(shown)[0] || ""} ${pct(row.targetWeight)}` }, { id: "reason", header: zh ? "依据" : "Reason", render: row => <span className={styles.reason}>{row.reason}</span> }]} /></div>
      <div className={styles.table}><VDenseTable ariaLabel="AI回测订单审计" rows={[...shown.orders.map((row, index) => ({ ...row, account: "strategy", rowKey: `strategy:${row.date}:${row.symbol || ""}:${row.side || ""}:${index}` })), ...(shown.benchmarkOrders ?? []).map((row, index) => ({ ...row, account: "benchmark", rowKey: `benchmark:${row.date}:${row.symbol || ""}:${row.side || ""}:${index}` }))]} getRowKey={row => row.rowKey} emptyText={zh ? "没有订单" : "No orders"} columns={[{ id: "date", header: zh ? "执行日" : "Execution", render: row => row.date }, { id: "symbol", header: zh ? "股票" : "Symbol", render: row => row.symbol || (shown.symbol ?? "—") }, { id: "account", header: zh ? "账户" : "Account", render: row => row.account === "benchmark" ? (zh ? "持有基准" : "Benchmark") : (zh ? "AI策略" : "Strategy") }, { id: "side", header: zh ? "方向" : "Side", render: row => row.side === "buy" ? (zh ? "买入" : "Buy") : row.side === "sell" ? (zh ? "卖出" : "Sell") : "—" }, { id: "status", header: zh ? "状态" : "Status", render: row => zh ? (orderLabels[row.status] || row.status) : row.status }, { id: "reason", header: zh ? "执行说明" : "Reason", render: row => row.reason ? (zh ? (orderLabels[row.reason] || row.reason) : row.reason) : "—" }]} /></div>
      <p className={styles.note}>{shown.modelId} · {zh ? "参数" : "Params"} {shown.paramsHash.slice(0, 12)} · {zh ? "数据" : "Data"} {shown.dataHash.slice(0, 12)}</p>
      {shown.notice ? <p className={styles.note}>{shown.notice}</p> : null}{shown.warnings?.map((warning, index) => <p key={index} className={styles.note}>{warning}</p>)}
      <span className={styles.note}>{quantityLabel(shown.params, zh)}</span>
    </VSurface> : null}
    {shown ? <FinanceBacktestForkDialog agentId={agentId} source={shown} open={forkOpen} disabled={disabled} zh={zh} onOpenChange={setForkOpen} onStarted={reconcile} /> : null}
    <VDialog open={confirmRetry} onOpenChange={setConfirmRetry} title={zh ? "确认重试未落盘的模型调用" : "Retry an uncertain model call"} footer={<VButton variant="primary" isPending={pending === "resume"} isDisabled={busy || !shown?.currentDecisionDate} onPress={() => { if (!shown?.currentDecisionDate) return; void perform("resume", async () => { await reconcile(await resumeAIBacktest(agentId, shown.runId, { retryUnknownDecisionDate: shown.currentDecisionDate!, confirmPossibleDuplicateCharge: true })); setConfirmRetry(false); }); }}>{zh ? "确认可能重复计费并重试" : "Accept possible duplicate charge and retry"}</VButton>}><p className={styles.note}>{zh ? `${shown?.currentDecisionDate || ""} 的模型调用没有可靠结果，可能已经计费。继续将只重试这一时点，保留已成功决策。` : "This invocation has no reliable result and may already have been billed. Retry only this date; accepted decisions stay unchanged."}</p></VDialog>
  </div>;
}

function AssetCoverageTable({ coverage, fallback, sources, symbols, zh }: {
  coverage?: Record<string, AIBacktestDateCoverage>;
  fallback?: AIBacktestDateCoverage;
  sources?: Record<string, { source?: string; sourceUrl?: string; fetchedAt?: string }>;
  symbols: string[];
  zh: boolean;
}) {
  const rows = symbols.map((symbol, index) => ({ symbol, coverage: coverage?.[symbol] ?? (index === 0 ? fallback : undefined), source: sources?.[symbol] }));
  if (!rows.length) return null;
  return <div className={styles.table}><VDenseTable ariaLabel={zh ? "逐股行情覆盖" : "Per-asset market data coverage"} rows={rows} getRowKey={row => row.symbol} emptyText={zh ? "没有行情覆盖信息" : "No coverage data"} columns={[{ id: "symbol", header: zh ? "股票" : "Symbol", render: row => row.symbol }, { id: "dates", header: zh ? "实际行情区间" : "Actual bars", render: row => row.coverage ? `${row.coverage.actualStartDate || "—"} — ${row.coverage.actualEndDate || "—"}` : "—" }, { id: "days", header: zh ? "交易日" : "Sessions", render: row => row.coverage?.tradingDays ?? "—" }, { id: "complete", header: zh ? "覆盖" : "Coverage", render: row => row.coverage ? (row.coverage.complete ? (zh ? "完整" : "Complete") : (zh ? "不完整" : "Incomplete")) : "—" }, { id: "source", header: zh ? "来源 / 抓取时间" : "Source / fetched", render: row => row.source ? `${row.source.source || "—"} · ${row.source.fetchedAt || "—"}` : "—" }]} /></div>;
}

function BacktestResult({ run, zh }: { run: AIBacktestRun; zh: boolean }) {
  const metrics = run.metrics!;
  const values = run.equity.flatMap(point => [point.equity, point.benchmarkEquity]), min = Math.min(...values), max = Math.max(...values);
  const points = (key: "equity" | "benchmarkEquity") => run.equity.map((point, index) => `${10 + index * 580 / Math.max(1, run.equity.length - 1)},${150 - (point[key] - min) * 130 / Math.max(1, max - min)}`).join(" ");
  const last = run.equity.at(-1);
  const holdings = Object.entries(last?.positions ?? {}).filter(([, units]) => units > 0).map(([symbol, units]) => ({ symbol, units }));
  const unfilledBenchmarkSymbols = run.unfilledBenchmarkSymbols ?? [];
  const evaluationRows = run.evaluation ? ([
    { key: "inSample", name: zh ? "样本内" : "In sample", ...run.evaluation.inSample },
    { key: "outOfSample", name: zh ? "样本外" : "Out of sample", ...run.evaluation.outOfSample },
  ]) : [];
  return <>
    {run.robustness ? <FinanceBacktestRobustness key={run.runId} result={run.robustness} zh={zh} /> : null}
    <div className={styles.row}><strong>{zh ? "策略收益" : "Return"} {pct(metrics.totalReturnPct)}</strong><span>{zh ? "持有基准" : "Benchmark"} {pct(metrics.benchmarkReturnPct)}</span><span>{zh ? "超额" : "Excess"} {pct(metrics.excessReturnPct)}</span><span>{zh ? "最大回撤" : "Drawdown"} {pct(metrics.maxDrawdownPct)}</span><span>{zh ? "年化" : "Annualized"} {pct(metrics.annualizedReturnPct)}</span><span>Sharpe {metrics.sharpeRatio?.toFixed(2) ?? "—"}</span><span>{zh ? "成交" : "Fills"} {metrics.tradeCount}</span><span>{zh ? "费用" : "Fees"} {metrics.fees.toFixed(2)}</span></div>
    {run.benchmarkStatus && run.benchmarkStatus !== "invested" ? <p className={styles.note}>{zh ? `基准有 ${unfilledBenchmarkSymbols.length} 只未成交，保留现金：${unfilledBenchmarkSymbols.join("、") || "代码未提供"}` : `${unfilledBenchmarkSymbols.length} benchmark assets were not filled; their sleeves remain cash: ${unfilledBenchmarkSymbols.join(", ") || "symbols unavailable"}`}</p> : null}
    {run.evaluation ? <><div className={styles.row}><strong>{zh ? "样本内外评估" : "In-sample / out-of-sample evaluation"}</strong><span>{zh ? "冻结边界" : "Frozen boundary"} {run.evaluation.outOfSampleStartDate}</span></div><div className={styles.table}><VDenseTable ariaLabel={zh ? "样本内外评估" : "In-sample and out-of-sample evaluation"} rows={evaluationRows} getRowKey={row => row.key} emptyText={zh ? "暂无分段评估" : "No split evaluation"} columns={[{ id: "window", header: zh ? "窗口" : "Window", render: row => row.name }, { id: "dates", header: zh ? "区间" : "Dates", render: row => `${row.startDate} — ${row.endDate}` }, { id: "days", header: zh ? "交易日" : "Sessions", render: row => row.tradingDays }, { id: "return", header: zh ? "策略收益" : "Strategy", render: row => pct(row.metrics.totalReturnPct) }, { id: "benchmark", header: zh ? "基准收益" : "Benchmark", render: row => pct(row.metrics.benchmarkReturnPct) }, { id: "excess", header: zh ? "超额" : "Excess", render: row => pct(row.metrics.excessReturnPct) }, { id: "drawdown", header: zh ? "最大回撤" : "Drawdown", render: row => pct(row.metrics.maxDrawdownPct) }, { id: "fees", header: zh ? "费用" : "Fees", render: row => row.metrics.fees.toFixed(2) }]} /></div><p className={styles.note}>{run.evaluation.notice}</p></> : null}
    {run.equity.length ? <svg viewBox="0 0 600 170" className={styles.chart} role="img" aria-label={zh ? "AI回测净值与持有基准" : "AI backtest equity and buy-and-hold benchmark"}><polyline points={points("benchmarkEquity")} fill="none" stroke="currentColor" strokeDasharray="4 3" opacity="0.4" strokeWidth="2" /><polyline points={points("equity")} fill="none" stroke="currentColor" strokeWidth="2" /></svg> : null}
    <p className={styles.note}>{zh ? "实线：策略净值；虚线：相同撮合成本下的买入持有。期末持仓按收盘估值。" : "Solid: strategy; dashed: buy-and-hold with the same execution costs. Final holdings are marked to close."}{last ? ` ${zh ? "期末现金" : "Ending cash"} ${last.cash?.toFixed(2) ?? "—"}.` : ""}</p>
    {holdings.length ? <div className={styles.table}><VDenseTable ariaLabel={zh ? "回测期末持仓" : "Ending backtest holdings"} rows={holdings} getRowKey={row => row.symbol} emptyText={zh ? "期末没有持仓" : "No ending holdings"} columns={[{ id: "symbol", header: zh ? "股票" : "Symbol", render: row => row.symbol }, { id: "units", header: zh ? "期末股数" : "Ending shares", render: row => row.units.toLocaleString() }]} /></div> : null}
    <div className={styles.table}><VDenseTable ariaLabel="AI回测成交" rows={run.trades} getRowKey={row => `${row.date}:${row.signalDate}:${row.symbol || run.symbol || ""}:${row.side}`} emptyText={zh ? "没有成交" : "No fills"} columns={[{ id: "signal", header: zh ? "信号日" : "Signal", render: row => row.signalDate }, { id: "date", header: zh ? "成交日" : "Fill", render: row => row.date }, { id: "symbol", header: zh ? "股票" : "Symbol", render: row => row.symbol || run.symbol || "—" }, { id: "side", header: zh ? "方向" : "Side", render: row => row.side === "buy" ? (zh ? "买入" : "Buy") : (zh ? "卖出" : "Sell") }, { id: "price", header: zh ? "成交价" : "Price", render: row => row.price.toFixed(3) }, { id: "units", header: zh ? "股数" : "Shares", render: row => row.units.toLocaleString() }, { id: "fee", header: zh ? "费用" : "Fees", render: row => row.fee.toFixed(2) }]} /></div>
  </>;
}
