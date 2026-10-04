// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinanceStockChart } from "./FinanceStockChart";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let cleanup = async () => {};
afterEach(async () => cleanup());
const candles = Array.from({ length: 120 }, (_, index) => ({ date: `2026-bar-${index + 1}`, open: 100 + index, high: 102 + index, low: 99 + index, close: 101 + index, volumeLots: 100 }));
async function render(data = candles) {
  const node = document.createElement("div"); document.body.appendChild(node); const root = createRoot(node);
  cleanup = async () => { await act(async () => root.unmount()); node.remove(); };
  await act(async () => root.render(<FinanceStockChart candles={data} period="day" onPeriodChange={vi.fn()} zh />));
  return node;
}
async function tab(node: HTMLElement, text: string) {
  const target = [...node.querySelectorAll('[role="tab"]')].find((item) => item.textContent === text)!;
  await act(async () => target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
}
describe("stock chart viewport", () => {
  it("changes the visible window while preserving full-series averages and supports panning", async () => {
    const node = await render();
    await tab(node, "30 根");
    expect(node.querySelector('svg[role="img"]')?.textContent).toContain("2026-bar-91");
    expect(node.textContent).toContain("MA20 210.50");
    const earlier = node.querySelector('button[aria-label="查看更早 K 线"]') as HTMLButtonElement;
    await act(async () => earlier.click());
    expect(node.querySelector('svg[role="img"]')?.textContent).toContain("2026-bar-81");
    expect(node.querySelector('svg[role="img"]')?.textContent).toContain("2026-bar-110");
    expect(node.textContent).toContain("MA20 200.50");
  });
  it("switches technical panels and announces the candle selected by keyboard", async () => {
    const node = await render();
    await tab(node, "RSI");
    expect(node.textContent).toContain("RSI14 100.00");
    expect(node.querySelector('svg[role="img"]')?.textContent).toContain("RSI(14)");
    await act(async () => node.querySelector('svg[role="img"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true })));
    expect(node.querySelector('[role="status"]')?.textContent).toContain("2026-bar-119");
    await tab(node, "MACD");
    expect(node.querySelector('svg[role="img"]')?.textContent).toContain("MACD(12,26,9)");
    expect(node.querySelector('svg[role="img"]')?.innerHTML).not.toMatch(/NaN|Infinity/);
  });
  it("shows an empty state instead of invalid chart geometry", async () => {
    const node = await render([]);
    expect(node.textContent).toContain("暂无 K 线数据");
    expect(node.querySelector("svg[role=img]")).toBeNull();
  });
});
