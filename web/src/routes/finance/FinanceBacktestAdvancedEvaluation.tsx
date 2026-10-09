import { useState } from "react";
import { VButton, VDenseTable, VStateSurface, VSurface } from "../../components/vui";
import type { AIBacktestAdvancedEvaluation } from "../../api/types/financialBacktests";
import styles from "./FinanceAIBacktest.styles";

export type FinanceBacktestAdvancedEvaluationResult = AIBacktestAdvancedEvaluation;

const pct = (value: number | null | undefined) =>
  typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}%` : "—";

const amount = (value: number | null | undefined) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";

const scenarioLabel = (id: string, zh: boolean) => {
  if (id === "baseline") return zh ? "原费用" : "Baseline";
  if (id === "cost_1_5x") return zh ? "费用 1.5×" : "Costs 1.5×";
  if (id === "cost_2x") return zh ? "费用 2×" : "Costs 2×";
  return id;
};

export function FinanceBacktestAdvancedEvaluation({
  result,
  zh,
}: {
  result: FinanceBacktestAdvancedEvaluationResult;
  zh: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const fields = result.costStress.scenarios.map((scenario) => {
    const metrics = scenario.outOfSampleMetrics ?? scenario.metrics;
    return {
      ...scenario,
      evaluatedMetrics: metrics,
    };
  });

  return (
    <div className={styles.comparisonShell}>
      <VButton variant="secondary" aria-expanded={expanded} onPress={() => setExpanded((value) => !value)}>
        {expanded
          ? (zh ? "收起成本与统计评估" : "Hide cost and statistical evaluation")
          : (zh ? "查看成本与统计评估" : "Cost and statistical evaluation")}
      </VButton>
      {expanded ? (
        <VSurface className={styles.panel} padding="compact">
          <div className={styles.row}>
            <strong>{zh ? "冻结决策重放" : "Frozen decision replay"}</strong>
            <span>{zh ? "不调用模型" : "No model calls"}</span>
            <span>
              {result.outOfSampleStartDate
                ? `${zh ? "样本外起点" : "Holdout start"} ${result.outOfSampleStartDate}`
                : (zh ? "未设置样本外区间" : "No held-out period")}
            </span>
          </div>

          <section className={styles.panel} aria-label={zh ? "费用压力测试" : "Cost stress test"}>
            <strong>{zh ? "费用压力测试" : "Cost stress test"}</strong>
            {result.costStress.status === "unavailable" ? (
              <VStateSurface tone="unavailable" density="compact" title={zh ? "费用压力测试不可用" : "Cost stress test unavailable"}>
                {result.costStress.error || result.costStress.notice}
              </VStateSurface>
            ) : null}
            {result.costStress.status !== "unavailable" ? <div className={styles.table}>
              <VDenseTable
                ariaLabel={zh ? "费用情景结果" : "Cost scenario results"}
                resizable
                className={styles.comparisonTable}
                rows={fields}
                getRowKey={(row) => row.id}
                emptyText={zh ? "没有费用情景" : "No cost scenarios"}
                columns={[
                  { id: "scenario", header: zh ? "情景" : "Scenario", width: 120, render: (row) => scenarioLabel(row.id, zh) },
                  { id: "commission", header: zh ? "佣金" : "Commission", width: 105, align: "right", render: (row) => `${row.commissionBps} bp` },
                  { id: "minimum", header: zh ? "最低佣金" : "Minimum fee", width: 105, align: "right", render: (row) => amount(row.minimumCommission) },
                  { id: "slippage", header: zh ? "滑点" : "Slippage", width: 100, align: "right", render: (row) => `${row.slippageBps} bp` },
                  { id: "return", header: zh ? "策略收益" : "Strategy", width: 110, align: "right", render: (row) => pct(row.evaluatedMetrics?.totalReturnPct) },
                  { id: "benchmark", header: zh ? "基准收益" : "Benchmark", width: 110, align: "right", render: (row) => pct(row.evaluatedMetrics?.benchmarkReturnPct) },
                  { id: "excess", header: zh ? "超额" : "Excess", width: 100, align: "right", render: (row) => pct(row.evaluatedMetrics?.excessReturnPct) },
                  { id: "drawdown", header: zh ? "最大回撤" : "Drawdown", width: 110, align: "right", render: (row) => pct(row.evaluatedMetrics?.maxDrawdownPct) },
                  { id: "fees", header: zh ? "费用" : "Fees", width: 95, align: "right", render: (row) => amount(row.evaluatedMetrics?.fees) },
                ]}
              />
            </div> : null}
            {fields.some((row) => row.status === "unavailable") ? (
              <VStateSurface tone="unavailable" density="compact" title={zh ? "部分压力情景不可用" : "Some cost scenarios unavailable"}>
                {fields.filter((row) => row.status === "unavailable").map((row) => `${scenarioLabel(row.id, zh)}：${row.error}`).join("；")}
              </VStateSurface>
            ) : null}
            <p className={styles.note}>{result.costStress.notice}</p>
          </section>

          <section className={styles.panel} aria-label={zh ? "统计区间" : "Statistical interval"}>
            <strong>{zh ? "样本外超额收益区间" : "Out-of-sample excess-return interval"}</strong>
            {result.returnUncertainty.status === "available" ? (
              <div className={styles.row}>
                <span>{zh ? `${result.returnUncertainty.observations} 个样本外交易日` : `${result.returnUncertainty.observations} held-out sessions`}</span>
                <span>{zh ? "估算年化超额" : "Estimated annualized excess"} {pct(result.returnUncertainty.pointEstimatePct)}</span>
                <span>{zh ? "95%区间" : "95% interval"} {pct(result.returnUncertainty.lowerPct)} — {pct(result.returnUncertainty.upperPct)}</span>
                <span>{zh ? "HAC滞后阶数" : "HAC lag"} {result.returnUncertainty.lag ?? "—"}</span>
              </div>
            ) : (
              <VStateSurface
                tone={result.returnUncertainty.status === "insufficient_sample" ? "info" : "unavailable"}
                density="compact"
                title={result.returnUncertainty.status === "insufficient_sample"
                  ? (zh ? "样本不足，暂不显示区间" : "Insufficient sample for an interval")
                  : (zh ? "统计区间不可用" : "Statistical interval unavailable")}
              >
                {result.returnUncertainty.error}
              </VStateSurface>
            )}
            <p className={styles.note}>{result.returnUncertainty.notice}</p>
          </section>

          <VStateSurface tone="info" density="compact" title={zh ? "模型参数与滚动样本外" : "Model parameters and walk-forward evaluation"}>
            {zh
              ? "策略、模型、提示或决策频率变化必须创建独立完整回测，并受原有模型调用和 Token 预算控制；冻结信号重放不会冒充重新训练、LLM 重跑或滚动样本外验证。"
              : "Changes to strategy, model, prompt or decision frequency require separate complete runs under the existing model-call and token budgets. Replaying frozen signals is not retraining, an LLM rerun or walk-forward validation."}
          </VStateSurface>
          <p className={styles.note}>{result.notice}</p>
        </VSurface>
      ) : null}
    </div>
  );
}
