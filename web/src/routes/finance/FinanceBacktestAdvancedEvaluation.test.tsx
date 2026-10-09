// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { FinanceBacktestAdvancedEvaluation, type FinanceBacktestAdvancedEvaluationResult } from "./FinanceBacktestAdvancedEvaluation";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let node: HTMLDivElement;

const result: FinanceBacktestAdvancedEvaluationResult = {
  schemaVersion: 1,
  basis: "frozen_decisions",
  status: "available",
  outOfSampleStartDate: "2025-01-02",
  costStress: {
    status: "available",
    scenarios: [
      { id: "baseline", status: "available", costMultiplier: 1, commissionBps: 3, minimumCommission: 5, slippageBps: 5, metrics: { totalReturnPct: 4, benchmarkReturnPct: 3, excessReturnPct: 1, maxDrawdownPct: -2, fees: 20 }, outOfSampleMetrics: { totalReturnPct: 2, benchmarkReturnPct: 1.5, excessReturnPct: 0.5, maxDrawdownPct: -1, fees: 10 }, error: null },
      { id: "cost_1_5x", status: "available", costMultiplier: 1.5, commissionBps: 4.5, minimumCommission: 7.5, slippageBps: 7.5, metrics: { totalReturnPct: 3.8, benchmarkReturnPct: 2.9, excessReturnPct: 0.9, maxDrawdownPct: -2.1, fees: 30 }, outOfSampleMetrics: { totalReturnPct: 1.8, benchmarkReturnPct: 1.4, excessReturnPct: 0.4, maxDrawdownPct: -1.1, fees: 15 }, error: null },
      { id: "cost_2x", status: "available", costMultiplier: 2, commissionBps: 6, minimumCommission: 10, slippageBps: 10, metrics: { totalReturnPct: 3.5, benchmarkReturnPct: 2.8, excessReturnPct: 0.7, maxDrawdownPct: -2.3, fees: 40 }, outOfSampleMetrics: { totalReturnPct: 1.5, benchmarkReturnPct: 1.3, excessReturnPct: 0.2, maxDrawdownPct: -1.2, fees: 20 }, error: null },
    ],
    notice: "佣金和滑点情景。",
  },
  returnUncertainty: {
    status: "available",
    method: "newey_west_hac",
    metric: "annualized_log_excess_return_pct",
    confidenceLevel: 0.95,
    observations: 300,
    lag: 5,
    pointEstimatePct: 4,
    lowerPct: -2,
    upperPct: 10,
    error: null,
    notice: "仅描述冻结历史序列。",
  },
  notice: "冻结决策统计。",
};

beforeEach(() => {
  node = document.createElement("div");
  document.body.append(node);
  root = createRoot(node);
});
afterEach(async () => {
  await act(async () => root.unmount());
  node.remove();
});

async function render(value = result) {
  await act(async () => root.render(<FinanceBacktestAdvancedEvaluation result={value} zh />));
}
async function expand() {
  await act(async () => node.querySelector("button")!.click());
}

it("starts collapsed and shows cost stress with the frozen-decision boundary", async () => {
  await render();
  expect(node.querySelector("table")).toBeNull();
  await expand();
  expect(node.textContent).toContain("冻结决策重放");
  expect(node.textContent).toContain("不调用模型");
  expect(node.textContent).toContain("样本外起点 2025-01-02");
  expect(node.textContent).toContain("费用 1.5×");
  expect(node.textContent).toContain("策略收益");
});

it("renders HAC bounds and explains that frozen replay is not a model rerun", async () => {
  await render(); await expand();
  expect(node.textContent).toContain("300 个样本外交易日");
  expect(node.textContent).toContain("95%区间 -2.00% — 10.00%");
  expect(node.textContent).toContain("不会冒充重新训练");
});

it("withholds intervals for short samples and displays unavailable cost scenarios", async () => {
  await render({
    ...result,
    costStress: {
      ...result.costStress,
      status: "partial",
      scenarios: result.costStress.scenarios.map((scenario) => scenario.id === "cost_2x"
        ? { ...scenario, status: "unavailable", metrics: null, outOfSampleMetrics: null, error: "费用参数超出可支持范围" }
        : scenario),
    },
    returnUncertainty: { ...result.returnUncertainty, status: "insufficient_sample", observations: 120, pointEstimatePct: null, lowerPct: null, upperPct: null, error: "样本外仅有120个交易日" },
  });
  await expand();
  expect(node.textContent).toContain("部分压力情景不可用");
  expect(node.textContent).toContain("费用参数超出可支持范围");
  expect(node.textContent).toContain("样本不足，暂不显示区间");
  expect(node.textContent).not.toContain("95%区间");
});

it("shows explicit unavailability when frozen data is missing", async () => {
  await render({
    ...result,
    status: "unavailable",
    error: "没有可校验的冻结行情快照",
    costStress: { ...result.costStress, status: "unavailable", scenarios: [], error: "没有可校验的冻结行情快照" },
    returnUncertainty: { ...result.returnUncertainty, status: "unavailable", observations: 0, lag: null, pointEstimatePct: null, lowerPct: null, upperPct: null, error: "没有可校验的冻结行情快照" },
  });
  await expand();
  expect(node.textContent).toContain("费用压力测试不可用");
  expect(node.textContent).toContain("没有可校验的冻结行情快照");
  expect(node.textContent).not.toContain("Cost scenario results");
});
