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

  it("replaces the truncated-tool projection with the server-grounded preview", async () => {
    const canonical = "## 结论\nsz000001 最新报价11.57元/股，行情日期2026-09-30，<https://gu.qq.com/sz000001/gp>。";
    vi.mocked(fetchFinancialReportText).mockResolvedValue(canonical);
    const container = await render({ report: { ...report, text: "没有这一项/股" } });
    expect(container.querySelector("[data-finance-report-body]")?.textContent).toBe(canonical);
    expect(container.textContent).not.toContain("没有这一项/股");
    expect(fetchFinancialReportText).toHaveBeenCalledWith({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "research-turn" }, { signal: expect.any(AbortSignal) });
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
