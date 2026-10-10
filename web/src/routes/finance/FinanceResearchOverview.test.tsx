// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinanceResearchOverview } from "./FinanceResearchOverview";
import type { FinancialSessionView } from "./FinancialResearchBridge";
import type { StockResearchReport } from "./stockResearchModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
afterEach(() => { act(() => root?.unmount()); root = undefined; document.body.replaceChildren(); });

const stock = { symbol: "sz000001", ticker: "000001", name: "平安银行", market: "深交所" };
const report: StockResearchReport = {
  turnId: "turn-1", timestamp: "2026-10-10", text: "结论", summary: "结论",
  sections: [], citations: [{ label: "2025 年报", page: "12", url: "https://example.com/report.pdf" }],
};
const view: FinancialSessionView = {
  sessionId: "session", title: "平安银行研究", status: "ready", busy: false, stopping: false,
  terminalReason: "failed_provider", lastTurnStatus: "failed", messages: [{
    role: "assistant", id: "answer", turnId: "turn-1", timestamp: "", status: "failed", turnItems: [
      { type: "tool_call", id: "failed", itemId: "failed", version: 3, sessionId: "session", turnId: "turn-1", revision: 1, sequence: 1, toolName: "news_search_tool", status: "failed" },
      { type: "tool_call", id: "review", itemId: "review", version: 3, sessionId: "session", turnId: "turn-1", revision: 1, sequence: 2, toolName: "financial_report_query_tool", status: "completed", semanticStatus: "partial" },
      { type: "tool_call", id: "done", itemId: "done", version: 3, sessionId: "session", turnId: "turn-1", revision: 1, sequence: 3, toolName: "financial_market_snapshot_tool", status: "completed" },
    ],
  }],
};

async function render(props: Partial<React.ComponentProps<typeof FinanceResearchOverview>> = {}) {
  const node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node);
  await act(async () => root?.render(<MemoryRouter><FinanceResearchOverview
    view={view} activeTurn={null} stock={stock} report={report} zh
    onCitation={() => {}} onOpenLibrary={() => {}} onOpenProcess={() => {}} onOpenAttention={() => {}}
    {...props}
  /></MemoryRouter>));
  return node;
}

describe("FinanceResearchOverview", () => {
  it("shows the native status and counts only real review and failed tool events", async () => {
    const onOpenAttention = vi.fn();
    const node = await render({ onOpenAttention });
    expect(node.querySelector('[role="status"]')?.textContent).toBe("研究未完成");
    expect(node.textContent).toContain("待核验 1");
    expect(node.textContent).toContain("失败 1");
    expect(node.textContent).not.toContain("失败 2");
    const review = [...node.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes("待核验 1"));
    await act(async () => review?.click());
    expect(onOpenAttention).toHaveBeenCalledTimes(1);
  });

  it("opens a citation through its callback and exposes the library entry", async () => {
    const onCitation = vi.fn(); const onOpenLibrary = vi.fn();
    const node = await render({ onCitation, onOpenLibrary });
    const reference = [...node.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes("2025 年报"));
    await act(async () => reference?.click());
    await act(async () => [...node.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes("查看财报资料"))?.click());
    expect(onCitation).toHaveBeenCalledWith(report.citations[0]);
    expect(onOpenLibrary).toHaveBeenCalledTimes(1);
    expect(node.querySelector('a[target="_blank"]')?.href).toBe("https://example.com/report.pdf#page=12");
  });

  it("uses the topic title and omits an unrelated selected stock", async () => {
    const node = await render({ topicTitle: "主题 · 现金流趋势", report: null });
    expect(node.textContent).toContain("主题 · 现金流趋势");
    expect(node.textContent).not.toContain("平安银行");
    expect(node.textContent).not.toContain("000001");
  });
});
