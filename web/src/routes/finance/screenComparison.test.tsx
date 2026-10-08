// @vitest-environment happy-dom

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinanceResearchReport } from "./FinanceResearchReport";
import { projectStockReport } from "./stockResearchModel";
import { fetchFinancialReportText } from "../../api/financialReports";

vi.mock("../../api/financialReports", async (original) => ({ ...await original<typeof import("../../api/financialReports")>(), fetchFinancialReportText: vi.fn() }));

const request = "请研究以下股票筛选条件，生成筛选报告。分析截至 2026-10-06。按条件筛选股票，列出候选、筛选依据和数据限制。\n\n用户选股条件：PE低于20";
const screen = JSON.stringify({
  ok: true, status: "complete", source: "新浪财经", fetchedAt: "2026-10-06T10:00:00+08:00",
  coverage: { providerTotal: 10, loaded: 10, complete: true, totalFiltered: 1 }, returnedCount: 1,
  items: [{
    symbol: "sh600519", ticker: "600519", name: "贵州茅台", price: 1258.62,
    officialFiling: {
      title: "贵州茅台2025年年度报告",
      url: "https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
      announcedOn: "2026-04-17",
      source: "巨潮资讯",
    },
    periodicFilings: [{
      kind: "semiannual",
      title: "贵州茅台2026年半年度报告",
      url: "https://static.cninfo.com.cn/finalpage/2026-08-15/1225475868.PDF",
      announcedOn: "2026-08-15",
      source: "巨潮资讯",
    }],
  }],
  notice: "来源只提供行情时分，未提供交易日期。",
});
const evidence = JSON.stringify({
  results: [{ knowledgeItemId: "k1", excerpt: "营业收入 200.00 元" }],
  citations: [{ knowledgeItemId: "k1", financialEvidence: [{ page: 42 }] }],
});

describe("screening comparison report", () => {
  let root: Root | undefined;
  afterEach(() => { act(() => root?.unmount()); root = undefined; document.body.replaceChildren(); });

  it("renders the filing page in the research report and omits the quote", async () => {
    const report = projectStockReport([
      { role: "user", id: "u", timestamp: "", content: request },
      {
        role: "assistant", id: "a", turnId: "screen-turn", status: "completed", timestamp: "2026-10-06T12:00:00Z",
        turnItems: [
          { type: "tool_call", toolName: "financial_market_screen_tool", status: "completed", output: screen },
          { type: "tool_call", toolName: "financial_evidence_search_tool", status: "completed", input: JSON.stringify({ ticker: "600519" }), output: evidence },
          { type: "agent_message", phase: "final_answer", status: "completed", text: "模型原文保留限制说明。" },
        ],
      },
    ] as never)!;
    vi.mocked(fetchFinancialReportText).mockResolvedValue(report.text);
    const container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<QueryClientProvider client={new QueryClient()}><FinanceResearchReport report={report} assistantAgentId="agent-1" sessionId="session-1" zh onCitation={() => {}} onResearch={() => {}} /></QueryClientProvider>);
    });
    expect(container.textContent).toContain("贵州茅台");
    expect(container.textContent).toContain("600519");
    expect(container.textContent).toContain("贵州茅台2025年年度报告");
    expect(container.textContent).toContain("2026-04-17");
    expect(container.textContent).toContain("半年报");
    expect(container.textContent).toContain("贵州茅台2026年半年度报告");
    expect(container.textContent).toContain("三季报：没有这一项");
    expect(container.textContent).toContain("第 42 页");
    expect(container.innerHTML).toContain("https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF");
    expect(container.textContent).not.toContain("1258.62");
    expect(container.querySelector("[data-finance-report-body]")?.textContent).toContain("筛选对照");
  });
});
