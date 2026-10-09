// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import type { AIBacktestRobustness } from "../../api/types/financialBacktests";
import { FinanceBacktestRobustness } from "./FinanceBacktestRobustness";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, node: HTMLDivElement;
const window = { label: "1", startDate: "2025-01-02", endDate: "2025-01-03", baselineDate: null, tradingDays: 2, complete: false, metrics: { totalReturnPct: 1, benchmarkReturnPct: 0.5, excessReturnPct: 0.5, maxDrawdownPct: 0, fees: 5, tradeCount: 1 } };
const result: AIBacktestRobustness = { schemaVersion: 1, status: "insufficient_sample", scope: "out_of_sample", windowSize: 63, minCompleteWindows: 4, completeWindowCount: 0, partialWindowCount: 1, outperformingWindowRatePct: null, evaluatedStartDate: window.startDate, evaluatedEndDate: window.endDate, tradingDays: 2, error: null, annualWindows: [{ ...window, complete: null }], fixedWindows: [window], notice: "切片不是独立实验。" };
beforeEach(() => { node = document.createElement("div"); document.body.append(node); root = createRoot(node); });
afterEach(async () => { await act(async () => root.unmount()); node.remove(); });
async function render(value = result) { await act(async () => root.render(<FinanceBacktestRobustness result={value} zh />)); }
async function expand() { await act(async () => node.querySelector("button")!.click()); }

it("starts collapsed and hides the rate for short held-out samples", async () => {
  await render();
  expect(node.querySelector("table")).toBeNull();
  await expand();
  expect(node.textContent).toContain("仅样本外");
  expect(node.textContent).toContain("不足 4 个完整窗口");
  expect(node.textContent).not.toContain("完整窗口超越基准占比");
  expect(node.textContent).toContain("2 · 尾段");
  expect(node.querySelector("button")!.getAttribute("aria-expanded")).toBe("true");
});

it("shows annual actual dates without asserting full-year coverage", async () => {
  await render(); await expand();
  const tab = [...node.querySelectorAll<HTMLElement>('[role="tab"]')].find(item => item.textContent === "按年度")!;
  await act(async () => { tab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })); tab.click(); });
  expect(node.textContent).toContain("年度首尾可能不足一年");
  expect(node.textContent).not.toContain("2 · 尾段");
  expect(node.textContent).toContain("2025-01-02 — 2025-01-03");
});

it("labels full-period retrospective results and explains the display threshold", async () => {
  await render({ ...result, scope: "full_period", status: "available", completeWindowCount: 4, outperformingWindowRatePct: 75 });
  await expand();
  expect(node.textContent).toContain("全区间回顾 · 未设置样本外");
  expect(node.textContent).toContain("完整窗口超越基准占比 75.00%");
  expect(node.textContent).toContain("不代表统计显著");
});

it("keeps unavailable evidence explicit without displaying metrics", async () => {
  await render({ ...result, status: "unavailable", error: "行情覆盖未确认" }); await expand();
  expect(node.textContent).toContain("行情覆盖未确认");
  expect(node.querySelector("table")).toBeNull();
  expect(node.querySelector('[role="tab"]')).toBeNull();
});
