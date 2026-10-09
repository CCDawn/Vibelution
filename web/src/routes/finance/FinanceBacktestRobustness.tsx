import { useState } from "react";
import type { AIBacktestRobustness } from "../../api/types/financialBacktests";
import { VButton, VDenseTable, VStateSurface, VSurface, VTabs } from "../../components/vui";
import styles from "./FinanceAIBacktest.styles";

const pct = (value: number | null) => value === null ? "—" : `${value.toFixed(2)}%`;

export function FinanceBacktestRobustness({ result, zh }: { result: AIBacktestRobustness; zh: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const [period, setPeriod] = useState("fixed");
  const rows = period === "fixed" ? result.fixedWindows : result.annualWindows;
  return <div className={styles.comparisonShell}>
    <VButton variant="secondary" aria-expanded={expanded} onPress={() => setExpanded(value => !value)}>
      {expanded ? (zh ? "收起分段表现" : "Hide period performance") : (zh ? "查看分段表现" : "Period performance")}
    </VButton>
    {expanded ? <VSurface className={styles.panel} padding="compact">
      <div className={styles.row}>
        <strong>{zh ? "分段表现" : "Period performance"}</strong>
        <span>{result.scope === "out_of_sample" ? (zh ? "仅样本外" : "Held-out period only") : (zh ? "全区间回顾 · 未设置样本外" : "Retrospective · no held-out period")}</span>
        {result.evaluatedStartDate ? <span>{result.evaluatedStartDate} — {result.evaluatedEndDate}</span> : null}
      </div>
      {result.status === "unavailable" ? <VStateSurface tone="unavailable" density="compact" title={zh ? "分段评估不可用" : "Period evaluation unavailable"}>{result.error}</VStateSurface> : <>
        <div className={styles.row}>
          <span>{zh ? `${result.tradingDays} 个交易日 · ${result.completeWindowCount} 个完整窗口` : `${result.tradingDays} sessions · ${result.completeWindowCount} complete windows`}</span>
          {result.status === "insufficient_sample"
            ? <span>{zh ? `不足 ${result.minCompleteWindows} 个完整窗口，暂不展示超越基准占比` : `Fewer than ${result.minCompleteWindows} complete windows; outperformance rate withheld`}</span>
            : <span>{zh ? "完整窗口超越基准占比" : "Complete windows outperforming benchmark"} {pct(result.outperformingWindowRatePct)}</span>}
        </div>
        <VTabs value={period} onValueChange={setPeriod} aria-label={zh ? "分段方式" : "Period grouping"} items={[
          { id: "fixed", label: zh ? "每63个交易日" : "Every 63 sessions" },
          { id: "annual", label: zh ? "按年度" : "By year" },
        ]} />
        <VDenseTable ariaLabel={zh ? "回测分段表现" : "Backtest period performance"} resizable className={styles.comparisonTable}
          rows={rows} getRowKey={row => row.startDate} emptyText={zh ? "没有可评估区间" : "No evaluable periods"}
          columns={[
            { id: "dates", header: zh ? "区间" : "Dates", width: 205, render: row => `${row.startDate} — ${row.endDate}` },
            { id: "days", header: zh ? "交易日" : "Sessions", width: 110, render: row => `${row.tradingDays}${row.complete === false ? (zh ? " · 尾段" : " · partial") : ""}` },
            { id: "return", header: zh ? "策略收益" : "Strategy", width: 115, align: "right", render: row => pct(row.metrics.totalReturnPct) },
            { id: "benchmark", header: zh ? "基准收益" : "Benchmark", width: 115, align: "right", render: row => pct(row.metrics.benchmarkReturnPct) },
            { id: "excess", header: zh ? "超额" : "Excess", width: 100, align: "right", render: row => pct(row.metrics.excessReturnPct) },
            { id: "drawdown", header: zh ? "最大回撤" : "Drawdown", width: 115, align: "right", render: row => pct(row.metrics.maxDrawdownPct) },
            { id: "fees", header: zh ? "费用" : "Fees", width: 100, align: "right", render: row => row.metrics.fees.toFixed(2) },
            { id: "trades", header: zh ? "成交" : "Fills", width: 80, align: "right", render: row => row.metrics.tradeCount },
          ]} />
        <p className={styles.note}>{period === "fixed"
          ? (zh ? "窗口不重叠，持仓连续；不足63日的尾段不计入占比。4个窗口是展示门槛，不代表统计显著。" : "Non-overlapping windows carry positions forward. Partial windows are excluded from the rate; four windows are a display threshold, not statistical significance.")
          : (zh ? "年度首尾可能不足一年，以实际日期为准；各段费用按成交日归属。" : "First and last years may be partial. Fees belong to their execution dates.")}</p>
      </>}
      <p className={styles.note}>{result.notice}</p>
    </VSurface> : null}
  </div>;
}
