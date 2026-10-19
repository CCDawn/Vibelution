// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { FinancialAssistant } from "../../api/financialAssistant";
import { FinanceTaskCenter } from "./FinanceTaskCenter";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let cleanup = async () => {};
afterEach(async () => { await cleanup(); });

it("starts research from empty records without creating a job or opening a record", async () => {
  const node = document.createElement("div"), root = createRoot(node);
  document.body.append(node);
  cleanup = async () => { await act(async () => root.unmount()); node.remove(); };
  const onNewResearch = vi.fn(), onOpen = vi.fn(), onOpenRun = vi.fn();
  await act(async () => root.render(<FinanceTaskCenter
    assistant={{ agentId: "agent-1" } as FinancialAssistant}
    stock={{ symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" }}
    watchlist={[]} tab="records" onTabChange={vi.fn()} records={[]} selectedId=""
    onOpen={onOpen} onOpenRun={onOpenRun} onRefresh={vi.fn()} loading={false} error={false} zh
    onNewResearch={onNewResearch}
  />));
  expect(node.textContent).toContain("从一次研究开始");
  expect(node.textContent).not.toContain("已加载记录");
  const start = [...node.querySelectorAll("button")].find(item => item.textContent === "新建研究");
  expect(start).toBeDefined();
  await act(async () => start!.click());
  expect(onNewResearch).toHaveBeenCalledOnce();
  expect(onOpen).not.toHaveBeenCalled();
  expect(onOpenRun).not.toHaveBeenCalled();
});
