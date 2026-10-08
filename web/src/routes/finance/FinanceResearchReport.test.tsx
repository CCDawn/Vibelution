// @vitest-environment happy-dom

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FinanceResearchReport } from "./FinanceResearchReport";
import { projectStockReport, stockResearchPrompt } from "./stockResearchModel";
import { fetchFinancialReportText } from "../../api/financialReports";

vi.mock("../../api/financialReports", async (original) => ({ ...await original<typeof import("../../api/financialReports")>(), fetchFinancialReportText: vi.fn() }));
vi.mock("../../components/conversation/LazyConversationMarkdownRenderer", () => ({ LazyConversationMarkdownRenderer: ({ content }: { content: string }) => <div data-markdown>{content}</div> }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
const request = stockResearchPrompt(stock, "2024FY", "2026-10-04", "financial", "brief");
const report = projectStockReport([
  { role: "user", id: "request", timestamp: "", content: request },
  {
    role: "assistant", id: "assistant", turnId: "research-turn", status: "completed", timestamp: "2026-10-04T12:00:00Z",
    turnItems: [{ type: "agent_message", phase: "final_answer", status: "completed", text: "## 结论\n经营质量仍需核实。" }],
  },
] as never)!;

describe("FinanceResearchReport research metadata", () => {
  let root: Root | undefined;
  beforeEach(() => { vi.mocked(fetchFinancialReportText).mockReset().mockResolvedValue(report.text); });
  afterEach(() => { act(() => root?.unmount()); root = undefined; document.body.replaceChildren(); });

  async function render(props: Partial<React.ComponentProps<typeof FinanceResearchReport>> = {}) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root?.render(<FinanceResearchReport report={report} assistantAgentId="agent-1" sessionId="session-1" zh onCitation={() => {}} onResearch={() => {}} {...props} />));
    return container;
  }

  it("shows the original report's known stock and research settings in one metadata row", async () => {
    const container = await render();
    const metadata = container.querySelector<HTMLElement>("[data-finance-research-metadata]");
    expect(metadata?.textContent).toContain("标的：贵州茅台 600519");
    expect(metadata?.textContent).toContain("分析日期：2026-10-04");
    expect(metadata?.textContent).toContain("报告期：2024FY");
    expect(metadata?.textContent).toContain("范围：财报分析");
    expect(metadata?.textContent).toContain("深度：快速");
    expect(metadata?.textContent).not.toContain("模型");
    expect(metadata?.querySelectorAll("span")).toHaveLength(5);
  });

  it("keeps the metadata visible in the compact brief and hides the row for legacy reports", async () => {
    const brief = await render({ summaryOnly: true });
    expect(brief.querySelector("[data-finance-research-metadata]")?.textContent).toContain("报告期：2024FY");
    act(() => root?.unmount());
    root = undefined;
    document.body.replaceChildren();

    const legacy = await render({ report: { ...report, researchParameters: undefined } });
    expect(legacy.querySelector("[data-finance-research-metadata]")).toBeNull();
  });

  it("does not repeat a ticker used as the unresolved company name", async () => {
    const container = await render({ report: { ...report, researchParameters: { stock: { ...stock, ticker: "000001", name: "000001" } } } });
    expect(container.querySelector("[data-finance-research-metadata]")?.textContent).toBe("标的：000001");
  });

  it("keeps full chapter titles and switches between exact grounded sections", async () => {
    const title = "二、本轮我已直接核验的部分（行情，可回链）";
    const text = `## 一、结论（先给判断）\n结论原文。\n\n## ${title}\n行情来源原文。`;
    vi.mocked(fetchFinancialReportText).mockResolvedValue(text);
    const container = await render();
    const section = container.querySelector<HTMLElement>(`[role="tab"][title="${title}"]`)!;
    expect(section).toBeTruthy();
    await act(async () => section.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    expect(container.querySelector("[data-finance-report-body]")?.textContent).toContain("行情来源原文。");
    expect(container.querySelector("[data-finance-report-body]")?.textContent).not.toContain("结论原文。");
    await act(async () => [...container.querySelectorAll<HTMLElement>('[role="tab"]')].find(tab => tab.textContent === "完整报告")!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
    expect(container.querySelector("[data-finance-report-body]")?.textContent).toBe(text);
  });

  it("replaces the truncated-tool projection with the server-grounded preview", async () => {
    const canonical = "## 结论\nsz000001 最新报价11.57元/股，行情日期2026-09-30，<https://gu.qq.com/sz000001/gp>。";
    vi.mocked(fetchFinancialReportText).mockResolvedValue(canonical);
    const container = await render({ report: { ...report, text: "没有这一项/股" } });
    expect(container.querySelector("[data-finance-report-body]")?.textContent).toBe(canonical);
    expect(container.textContent).not.toContain("没有这一项/股");
    expect(fetchFinancialReportText).toHaveBeenCalledWith({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "research-turn" }, { signal: expect.any(AbortSignal) });
  });

  it("compares the evidence notice to the raw final answer after local grounding", async () => {
    const originalText = [
      "## 结论",
      "营业收入 1 亿元，净利润 2 亿元，经营现金流 3 亿元，毛利率 4%，净利率 5%，资产总额 6 亿元，负债 7 亿元，ROE 8%。",
    ].join("\n");
    const projected = projectStockReport([
      { role: "assistant", id: "assistant", turnId: "grounding-turn", status: "completed", timestamp: "2026-10-04T12:00:00Z", turnItems: [{ type: "agent_message", phase: "final_answer", status: "completed", text: originalText }] },
    ] as never)!;
    const supplement = vi.fn();
    vi.mocked(fetchFinancialReportText).mockResolvedValue(projected.text);

    const container = await render({ report: projected, onSupplementEvidence: supplement });

    expect(projected.text.match(/没有这一项/g)).toHaveLength(8);
    expect(container.querySelector("[data-finance-report-body]")?.textContent).toBe(projected.text);
    expect(container.textContent).toContain("部分数字未通过核验");
    expect(container.textContent).toContain("补充证据");
    expect(container.textContent).not.toContain("营业收入 1 亿元");
    await act(async () => Array.from(container.querySelectorAll("button")).find((button) => button.textContent === "补充证据")?.click());
    expect(supplement).toHaveBeenCalledTimes(1);
  });

  it("uses the projected body as the evidence baseline for a legacy report without originalText", async () => {
    const legacy = { ...report, text: "## 结论\n利润没有这一项。", originalText: undefined };
    vi.mocked(fetchFinancialReportText).mockResolvedValue(legacy.text);

    const container = await render({ report: legacy });

    expect(container.querySelector("[data-finance-report-body]")?.textContent).toBe(legacy.text);
    expect(container.textContent).not.toContain("部分数字未通过核验");
  });

  it("never displays a late preview from another session and exposes a retry on failure", async () => {
    let resolveOld!: (text: string) => void;
    vi.mocked(fetchFinancialReportText).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    const container = await render();
    expect(container.textContent).toContain("读取核验正文");
    vi.mocked(fetchFinancialReportText).mockRejectedValueOnce(new Error("Unavailable"));
    await act(async () => root?.render(<FinanceResearchReport report={report} assistantAgentId="agent-1" sessionId="session-2" zh onCitation={() => {}} onResearch={() => {}} />));
    await act(async () => resolveOld("Other session private result"));
    expect(container.textContent).toContain("报告读取失败");
    expect(container.textContent).not.toContain("Other session");
    vi.mocked(fetchFinancialReportText).mockResolvedValue("## 结论\nRecovered exact report");
    await act(async () => Array.from(container.querySelectorAll("button")).find((button) => button.textContent === "重试")?.click());
    expect(container.textContent).toContain("Recovered exact report");
  });

  it("offers native follow-up for missing evidence without starting another research", async () => {
    const supplement = vi.fn(), startResearch = vi.fn();
    vi.mocked(fetchFinancialReportText).mockResolvedValue("## 结论\n利润没有这一项。");
    const container = await render({ onSupplementEvidence: supplement, onResearch: startResearch });
    await act(async () => Array.from(container.querySelectorAll("button")).find((button) => button.textContent === "补充证据")!.click());
    expect(supplement).toHaveBeenCalledTimes(1);
    expect(startResearch).not.toHaveBeenCalled();
  });
});
