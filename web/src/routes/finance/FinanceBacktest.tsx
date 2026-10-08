import { useEffect, useRef, useState } from "react";
import { runFinancialBacktest } from "../../api/financialEvaluation";
import type { FinancialBacktestResult } from "../../api/types/financialEvaluation";
import type { StockIdentity } from "../../api/types/financialMarket";
import { VButton, VDenseTable, VInput, VStateSurface, VSurface } from "../../components/vui";
import { evaluationReferenceBlock } from "./financialEvaluationModel";
import styles from "./FinanceEvaluation.styles";

const dateAgo = (days: number) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(Date.now() - days * 86400000));
const pct = (v: number) => `${v.toFixed(2)}%`;

export function FinanceBacktest({ agentId, stock, zh, onResearchPrompt, disabled, availableDates }: { agentId: string; stock: StockIdentity; zh: boolean; onResearchPrompt: (text: string) => void; disabled: boolean; availableDates?: string[] }) {
  const [startDate, setStartDate] = useState(() => dateAgo(90)), [endDate, setEndDate] = useState(() => dateAgo(1));
  const [window, setWindow] = useState("20"), [commission, setCommission] = useState("3"), [slippage, setSlippage] = useState("5");
  const [result, setResult] = useState<FinancialBacktestResult | null>(null), [pending, setPending] = useState(false), [error, setError] = useState("");
  const gate = useRef(false), identity = `${agentId}:${stock.symbol}`;
  const datesInitialized = useRef(false), datesEdited = useRef(false);
  useEffect(() => {
    if (datesInitialized.current || datesEdited.current) return;
    const dates = availableDates?.filter(date => date < dateAgo(0)) ?? [];
    if (dates.length <= 20) return;
    datesInitialized.current = true;
    setStartDate(dates[Math.max(20, dates.length - 60)]); setEndDate(dates[dates.length - 1]);
  }, [availableDates]);
  const latestIdentity = useRef(identity); latestIdentity.current = identity;
  const shown = result?.symbol === stock.symbol ? result : null;
  async function run() {
    if (gate.current) return;
    gate.current = true; setPending(true); setError(""); setResult(null);
    const expected = identity;
    try {
      const data = await runFinancialBacktest(agentId, { symbol: stock.symbol, startDate, endDate, window: Number(window), commissionBps: Number(commission), slippageBps: Number(slippage) });
      if (latestIdentity.current === expected) {
        if (data.symbol !== stock.symbol) throw new Error("回测股票身份不匹配");
        setResult(data);
      }
    } catch (cause) { if (latestIdentity.current === expected) setError(cause instanceof Error ? cause.message : "回测失败"); }
    finally { gate.current = false; setPending(false); }
  }
  const metrics = shown?.metrics;
  const equity = shown?.equity ?? [];
  const minimum = Math.min(...equity.flatMap(point => [point.equity, point.benchmarkEquity]));
  const maximum = Math.max(...equity.flatMap(point => [point.equity, point.benchmarkEquity]));
  function points(key: "equity" | "benchmarkEquity") { return equity.map((point, index) => `${10 + index * 580 / Math.max(1, equity.length - 1)},${150 - (point[key] - minimum) * 130 / Math.max(1, maximum - minimum)}`).join(" "); }
  return <div className={styles.page}>
    <h3 className={styles.title}>{zh ? `历史策略回测 · ${stock.name} ${stock.ticker}` : `Historical strategy · ${stock.ticker}`}</h3>
    <p className={styles.note}>{zh ? "均线策略：收盘高于均线持有，否则持现金；下一交易日开盘成交。仅A股最近120根日线，前复权单位模拟，起点需足够预热。" : "MA strategy: hold above the moving average, otherwise cash; execute at the next open. CN only, latest 120 forward-adjusted daily bars with warm-up."}</p>
    <div className={styles.row}>
      <label className={styles.field}>{zh ? "开始" : "From"}<VInput type="date" aria-label="回测开始日期" value={startDate} onChange={event => { datesEdited.current = true; setStartDate(event.target.value); }} /></label>
      <label className={styles.field}>{zh ? "结束" : "To"}<VInput type="date" aria-label="回测结束日期" value={endDate} onChange={event => { datesEdited.current = true; setEndDate(event.target.value); }} /></label>
      <label className={styles.field}>MA<VInput type="number" aria-label="均线窗口" min={5} max={60} value={window} onChange={event => setWindow(event.target.value)} /></label>
      <label className={styles.field}>{zh ? "佣金 bps" : "Fee bps"}<VInput type="number" aria-label="回测佣金" min={0} max={100} value={commission} onChange={event => setCommission(event.target.value)} /></label>
      <label className={styles.field}>{zh ? "滑点 bps" : "Slippage bps"}<VInput type="number" aria-label="回测滑点" min={0} max={100} value={slippage} onChange={event => setSlippage(event.target.value)} /></label>
      <VButton variant="primary" isPending={pending} isDisabled={pending || !startDate || !endDate || stock.symbol.startsWith("hk") || stock.symbol.startsWith("us")} onPress={() => void run()}>{zh ? "运行回测" : "Run backtest"}</VButton>
    </div>
    {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
    {pending ? <VStateSurface tone="loading" busy title={zh ? "读取历史日线并执行策略" : "Loading bars and running strategy"} /> : null}
    {shown && metrics ? <VSurface tone="panel" padding="normal" className={styles.panel}>
      <div className={styles.row}><strong>{zh ? "策略" : "Strategy"} {pct(metrics.totalReturnPct)}</strong><span>{zh ? "持有基准" : "Buy and hold"} {pct(metrics.benchmarkReturnPct)}</span><span>{zh ? "超额" : "Excess"} {pct(metrics.excessReturnPct)}</span><span>{zh ? "最大回撤" : "Max drawdown"} {pct(metrics.maxDrawdownPct)}</span><span>{zh ? "成交" : "Trades"} {metrics.tradeCount}</span></div>
      <svg viewBox="0 0 600 170" className={styles.chart} role="img" aria-label={zh ? "策略净值与买入持有基准" : "Strategy equity and benchmark"}><polyline points={points("benchmarkEquity")} fill="none" stroke="currentColor" strokeDasharray="4 3" opacity="0.4" strokeWidth="2" /><polyline points={points("equity")} fill="none" stroke="currentColor" strokeWidth="2" /></svg>
      <p className={styles.note}>{shown.startDate} — {shown.endDate} · {zh ? "实线策略 / 虚线持有基准；初始100000，期末按收盘估值；费用" : "Solid strategy / dashed benchmark; initial 100000, marked to final close; fees"} {metrics.fees.toFixed(2)}</p>
      <div className={styles.table}><VDenseTable ariaLabel="历史策略成交" rows={shown.trades} getRowKey={row => `${row.date}:${row.side}`} emptyText={zh ? "区间内没有成交" : "No trades"} columns={[
        { id: "signal", header: zh ? "信号日" : "Signal", render: row => row.signalDate }, { id: "date", header: zh ? "成交日" : "Execution", render: row => row.date },
        { id: "side", header: zh ? "方向" : "Side", render: row => row.side === "buy" ? (zh ? "买入" : "Buy") : (zh ? "卖出" : "Sell") },
        { id: "price", header: zh ? "成交价" : "Price", render: row => row.price.toFixed(3) }, { id: "fee", header: zh ? "费用" : "Fee", render: row => row.fee.toFixed(2) },
      ]} /></div>
      <p className={styles.note}>{shown.notice}</p>
      <div className={styles.row}><a href={shown.sourceUrl} target="_blank" rel="noreferrer">{shown.source}</a><span className={styles.note}>{shown.fetchedAt} · {shown.dataHash.slice(0, 12)}</span><VButton isDisabled={disabled} onPress={() => onResearchPrompt(`请复盘以下历史均线策略回测，区分事实、假设、过拟合和数据边界；这不是AI策略准确率。不要改变原研究报告。\n${evaluationReferenceBlock(shown)}`)}>{zh ? "开始AI复盘" : "Start AI review"}</VButton></div>
    </VSurface> : !pending ? <VStateSurface tone="empty" title={zh ? "设置区间后运行" : "Choose dates and run"}>{zh ? "1 bps = 0.01%；策略和基准采用相同费用假设。" : "1 bps = 0.01%; strategy and benchmark use the same costs."}</VStateSurface> : null}
  </div>;
}
