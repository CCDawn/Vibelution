import { describe, expect, it } from "vitest";
import type { AssistantConversationTurn, ConversationMessage, SessionSummary, SessionTurnItem } from "../../api/types";
import { cleanResearchPreview, isResearchSearchResult, isValidResearchDate, localResearchDate, movingAverage, projectStockReport, reportMatchesStock, researchRecordStatus, researchTablePreview, stockFromResearchRequest, stockIdentityFromUnknown, stockResearchPrompt } from "./stockResearchModel";

const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
function turn(status = "completed", items: unknown[] = []): AssistantConversationTurn { return { role: "assistant", id: "a", turnId: "t", status: status as AssistantConversationTurn["status"], timestamp: "2026-10-04T12:00:00Z", turnItems: items as SessionTurnItem[] }; }
const final = { type: "agent_message", phase: "final_answer", status: "completed", text: "## 结论\n需继续核对现金流。\n## 关键事实\n来自原始PDF第5页：https://example.com/report.pdf\n## 风险\n资料不足。" };
describe("stock research projections", () => {
  it("excludes an unmatched Agent directory stub even when it inherits an old terminal outcome", () => {
    const stub: SessionSummary = { id: "direct", title: "炒股智能体", status: "ready", currentPhase: "ready", taskSummary: "", lastActive: "", updatedAt: "", conversationIndexKind: "personal_agent", terminalReason: "success", lastTurnStatus: "ready", lastTurnTerminalTurnId: "old-direct-turn" };
    expect(isResearchSearchResult(stub, "Markowitz")).toBe(false);
    expect(isResearchSearchResult(stub, "炒股")).toBe(true);
    expect(isResearchSearchResult({ ...stub, conversationIndexKind: "user_chat", updatedAt: "2026-10-05", searchSnippets: ["Markowitz"] }, "Markowitz")).toBe(true);
  });
  it("keeps financial tables intact rather than manufacturing prose from columns", () => {
    const table = "| 指标 | 2024FY（元） | 同比 |\n| --- | ---: | ---: |\n| 净利润 | 86228146421.62 | +15.38% |\n| 经营现金流 | 92463692168.43 | +38.85% |";
    const text = `${table}\n来源：原 PDF 第 5 页，https://example.com/report.pdf`;
    const evidence = JSON.stringify({
      results: [{ knowledgeItemId: "k1", excerpt: "净利润 86228146421.62 同比 15.38 经营现金流 92463692168.43 同比 38.85" }],
      citations: [{ knowledgeItemId: "k1", financialEvidence: [{ page: 5 }] }],
    });
    const report = projectStockReport([turn("completed", [
      { type: "tool_call", toolName: "financial_evidence_search_tool", output: evidence, status: "completed" },
      { ...final, text },
    ])])!;
    expect(report.summary).toBe("");
    expect(researchTablePreview(report.text)).toBe(table);
    expect(report.text).toBe(text);
    expect(cleanResearchPreview(`## 结论\n现金流覆盖利润。\n${table}\nPDF：https://example.com/report.pdf`)).toBe("现金流覆盖利润。");
  });
  it("hides an uncited conclusion ratio while keeping a cited amount and a risk amount", () => {
    const text = "## 结论\n营业收入 200.00 元，见第5页。毛利率约为 91.93%。\n## 风险\n跌幅 9.99%。";
    const evidence = JSON.stringify({
      results: [{ knowledgeItemId: "k1", excerpt: "营业收入 200.00 元" }],
      citations: [{ knowledgeItemId: "k1", financialEvidence: [{ page: 5 }] }],
    });
    const report = projectStockReport([turn("completed", [
      { type: "tool_call", toolName: "financial_evidence_search_tool", output: evidence, status: "completed" },
      { ...final, text },
    ])])!;
    expect(report.text).toContain("200.00 元");
    expect(report.text).toContain("9.99%");
    expect(report.text).not.toContain("91.93");
    expect(report.text).toContain("没有这一项");
    const uncited = projectStockReport([turn("completed", [{ ...final, text: "| 指标 | 数值 |\n| --- | --- |\n| 营收 | 12 亿元 |" }])])!;
    expect(uncited.text).toContain("| 营收 | 没有这一项 |");
    expect(uncited.text).not.toContain("亿元");
  });
  it("never promotes reasoning, tools, commentary or unfinished turns into reports", () => {
    for (const message of [turn("running", [final]), turn("failed", [final]), turn("completed", [{ ...final, phase: "commentary" }]), turn("completed", [{ type: "tool_call", output: "买入", status: "completed" }])]) expect(projectStockReport([message])).toBeNull();
    const report = projectStockReport([turn("completed", [final])])!;
    expect(report.sections.map((section) => section.title)).toEqual(["结论", "关键事实", "风险"]);
    expect(report.citations).toEqual([{ url: "https://example.com/report.pdf", page: "5", label: "PDF · 第 5 页" }]);
  });
  it("keeps report stock identity after a short follow-up and rejects other stock contexts", () => {
    const messages: ConversationMessage[] = [{ role: "user", id: "u", content: "核对贵州茅台（600519）", timestamp: "" }, { role: "user", id: "followup", content: "现金流如何？", timestamp: "" }, turn("completed", [final])];
    const report = projectStockReport(messages);
    expect(reportMatchesStock(report, messages, stock)).toBe(true);
    expect(reportMatchesStock(report, messages, { ...stock, ticker: "000858", symbol: "sz000858", name: "五粮液" })).toBe(false);
  });
  it("recognizes a stock repeated in source URLs while rejecting mixed stock reports", () => {
    const request: ConversationMessage = { role: "user", id: "u", timestamp: "", content: "研究贵州茅台（600519），来源 https://qt.gtimg.cn/q=sh600519" };
    const messages = [request, turn("completed", [final])];
    expect(reportMatchesStock(projectStockReport(messages), messages, stock)).toBe(true);
    const mixed = [{ ...request, content: `${request.content}，并比较五粮液（000858）` }, messages[1]];
    expect(reportMatchesStock(projectStockReport(mixed), mixed, stock)).toBe(false);
  });

  it("keeps the complete native research report after ordinary follow-ups", () => {
    const request: ConversationMessage = { role: "user", id: "research", timestamp: "", content: stockResearchPrompt(stock, "2024FY", "2026-10-04", "financial", "brief") };
    const original = { ...turn("completed", [final]), turnId: "research-turn" };
    const messages: ConversationMessage[] = [request, original, { role: "user", id: "follow", timestamp: "", content: "用三句话总结现金流风险" }, { ...turn("completed", [{ ...final, text: "这是三句话的追问答复。" }]), turnId: "follow-turn" }];
    expect(projectStockReport(messages)?.turnId).toBe("research-turn");
    expect(projectStockReport(messages)?.text).toBe(final.text);
    expect(projectStockReport(messages)?.sections).toHaveLength(3);
    // An explicit new full report may replace the older report.
    messages.push({ ...request, id: "new-research" }, { ...original, turnId: "new-report" });
    expect(projectStockReport(messages)?.turnId).toBe("new-report");
  });

  it("does not promote stopped or incomplete final answers and retains older reports", () => {
    const original = { ...turn("completed", [final]), turnId: "original" };
    const stopped = { ...turn("completed", [{ ...final, text: "本轮已按请求停止。" }]), turnId: "stopped" };
    expect(projectStockReport([stopped], { terminalReason: "stopped_by_user", lastTurnTerminalTurnId: "stopped" })).toBeNull();
    expect(projectStockReport([original, stopped], { terminalReason: "stopped_by_user", lastTurnTerminalTurnId: "stopped" })?.turnId).toBe("original");
    const resumed = { ...original, turnId: "resumed" };
    expect(projectStockReport([stopped, resumed], { terminalReason: "success" })?.turnId).toBe("resumed");
    expect(projectStockReport([original], { terminalReason: "needs_continue", lastTurnTerminalTurnId: "original" })).toBeNull();
  });

  it("distinguishes native terminal outcomes from the ready phase", () => {
    expect(researchRecordStatus({ status: "ready", terminalReason: "success", lastTurnStatus: "completed" })).toBe("已完成");
    expect(researchRecordStatus({ status: "ready", terminalReason: "stopped_by_user", lastTurnStatus: "completed" })).toBe("已停止");
    expect(researchRecordStatus({ status: "needs_continue" })).toBe("待继续");
    expect(researchRecordStatus({ status: "ready", terminalReason: "paused_limit" })).toBe("待继续");
    expect(researchRecordStatus({ status: "ready", terminalReason: "failed_provider" })).toBe("失败");
    expect(researchRecordStatus({ status: "running", terminalReason: "success" })).toBe("研究中");
    expect(researchRecordStatus({ status: "ready" })).toBe("研究会话");
  });

  it("rejects future, empty and invalid calendar dates using the local day", () => {
    const now = new Date(2026, 9, 5, 0, 15);
    expect(localResearchDate(now)).toBe("2026-10-05");
    expect(isValidResearchDate("2026-10-05", now)).toBe(true);
    expect(isValidResearchDate("2024-02-29", now)).toBe(true);
    for (const value of ["", "0000-01-01", "2099-01-01", "2026-10-06", "2025-02-29", "2026-04-31", "2026-1-01"]) expect(isValidResearchDate(value, now)).toBe(false);
  });

  it("keeps separate cited pages from the same PDF and does not borrow another line's page", () => {
    const text = "第5页：https://example.com/report.pdf\n第63页：[现金流](https://example.com/report.pdf)\n[同一页](https://example.com/report.pdf#page=63)\n新闻：https://example.com/news";
    expect(projectStockReport([turn("completed", [{ ...final, text }])])?.citations).toEqual([
      { url: "https://example.com/report.pdf", page: "5", label: "PDF · 第 5 页" },
      { url: "https://example.com/report.pdf", page: "63", label: "PDF · 第 63 页" },
      { url: "https://example.com/news", page: "", label: "example.com" },
    ]);
  });

  it("links pages on a PDF source title line without repeating metadata in the summary", () => {
    const text = "## 结论\n**数据时点**：2024FY年报。\n- **现金流覆盖利润**：真实结论。\n## 证据来源\n- 贵州茅台《2024年度报告》，p.5（数据）、p.63（利润表）\n- PDF：https://example.com/report.pdf\n\n新闻：https://example.com/news";
    const report = projectStockReport([turn("completed", [{ ...final, text }])])!;
    expect(report.summary).toBe("现金流覆盖利润 ：真实结论。");
    expect(report.citations.map((item) => item.page)).toEqual(["5", "63", ""]);
  });
  it("keeps all PDF pages listed on the same source line and honors explicit page anchors", () => {
    const text = "原 PDF 第 5 页（主要会计数据）、第 63 页（合并利润表）：https://example.com/report.pdf\n原 PDF 第 5 页、第 63 页：https://example.com/anchored.pdf#page=63\n第5页、第63页：新闻 https://example.com/news";
    expect(projectStockReport([turn("completed", [{ ...final, text }])])?.citations.map(({ url, page }) => [url, page])).toEqual([
      ["https://example.com/report.pdf", "5"], ["https://example.com/report.pdf", "63"],
      ["https://example.com/anchored.pdf", "63"], ["https://example.com/news", ""],
    ]);
  });
  it("does not assign one PDF's cited page to a second PDF on the same line", () => {
    const text = "第5页：https://example.com/a.pdf；第63页：https://example.com/b.pdf";
    expect(projectStockReport([turn("completed", [{ ...final, text }])])?.citations.map(({ url, page }) => [url, page])).toEqual([
      ["https://example.com/a.pdf", "5"], ["https://example.com/b.pdf", "63"],
    ]);
  });
  it("computes averages from actual closes and has no fabricated warm-up values", () => {
    const candles = Array.from({ length: 25 }, (_, index) => ({ date: "", open: index + 1, close: index + 1, high: index + 1, low: index + 1, volumeLots: 1 }));
    expect(movingAverage(candles, 5).slice(0, 5)).toEqual([null, null, null, null, 3]);
    expect(movingAverage(candles, 20)[19]).toBe(10.5);
  });
  it("validates stored identities and binds the prompt to stock/date/scope", () => {
    expect(stockIdentityFromUnknown({ ...stock, symbol: "https://example.com" })).toBeNull();
    expect(stockResearchPrompt(stock, "2024FY", "2026-10-04", "financial", "brief")).toContain("贵州茅台（600519，上交所）");
    expect(stockResearchPrompt(stock, "2024FY", "2026-10-04", "financial", "brief")).toContain("分析日期 2026-10-04，报告期 2024FY");
  });
  it("canonicalizes known US exchange suffixes from search and quotes without stripping share classes", () => {
    const searchResult = { symbol: "usNVDA", ticker: "NVDA.OQ", name: "英伟达", market: "NASDAQ", marketCode: "US", currency: "USD" };
    const quote = { symbol: "usAAPL", ticker: "AAPL.OQ", name: "苹果", market: "NASDAQ", marketCode: "US", currency: "USD", price: 200 };
    expect(stockIdentityFromUnknown(searchResult)).toEqual({ symbol: "usNVDA", ticker: "NVDA", name: "英伟达", market: "NASDAQ" });
    expect(stockIdentityFromUnknown(quote)).toEqual({ symbol: "usAAPL", ticker: "AAPL", name: "苹果", market: "NASDAQ" });
    expect(stockIdentityFromUnknown({ symbol: "usBRK.B", ticker: "BRK.B", name: "伯克希尔", market: "NYSE" }))
      .toMatchObject({ symbol: "usBRK.B", ticker: "BRK.B" });
    expect(stockIdentityFromUnknown({ symbol: "usAAPL", ticker: "MSFT.OQ", name: "微软", market: "NASDAQ" })).toBeNull();
    expect(stockIdentityFromUnknown({ symbol: "usAAPL", ticker: "AAPL.X", name: "苹果", market: "NASDAQ" })).toBeNull();
    expect(stockIdentityFromUnknown({ ...stock, ticker: "600519.OQ" })).toBeNull();
    expect(stockIdentityFromUnknown({ symbol: "hk00700", ticker: "00700.OQ", name: "腾讯控股", market: "港交所" })).toBeNull();
    expect(stockFromResearchRequest("请研究 英伟达（NVDA.OQ，NASDAQ）")?.ticker).toBe("NVDA");
  });
  it("restores canonical CN, HK and US stock identities from research headers rather than follow-up numbers", () => {
    for (const identity of [stock, { symbol: "hk00700", ticker: "00700", name: "腾讯控股", market: "港股" }, { symbol: "usBRK.B", ticker: "BRK.B", name: "Berkshire", market: "NYSE" }]) {
      expect(stockFromResearchRequest(stockResearchPrompt(identity, "2024FY", "2026-10-06", "comprehensive", "standard"))).toEqual(identity);
    }
    expect(stockFromResearchRequest("请研究2024年现金流，利润600519元")).toBeNull();
    expect(stockFromResearchRequest("用五句话讲讲00700")).toBeNull();
  });
  it("retains international research identity through ordinary follow-ups and rejects another ticker", () => {
    for (const identity of [{ symbol: "hk00700", ticker: "00700", name: "腾讯控股", market: "港股" }, { symbol: "usAAPL", ticker: "AAPL", name: "Apple", market: "NASDAQ" }]) {
      const messages: ConversationMessage[] = [{ role: "user", id: "request", timestamp: "", content: stockResearchPrompt(identity, "2024FY", "2026-10-06", "comprehensive", "standard") }, turn("completed", [final]), { role: "user", id: "follow", timestamp: "", content: "现金流如何？" }];
      const report = projectStockReport(messages)!;
      expect(reportMatchesStock(report, messages, identity)).toBe(true);
      expect(reportMatchesStock(report, messages, stock)).toBe(false);
      expect(reportMatchesStock(report, messages, { symbol: "usMSFT", ticker: "MSFT", name: "Microsoft", market: "NASDAQ" })).toBe(false);
    }
  });
  it("shows each screened stock with a filing page from the same turn or 没有这一项", () => {
    const request = "请研究以下股票筛选条件，生成筛选报告。分析截至 2026-10-06。按条件筛选股票，列出候选、筛选依据和数据限制。\n\n用户选股条件：PE低于20";
    const screen = JSON.stringify({
      ok: true, status: "partial", source: "新浪财经", fetchedAt: "2026-10-06T10:00:00+08:00",
      coverage: { providerTotal: 5000, loaded: 120, complete: false, totalFiltered: 2 }, returnedCount: 2,
      items: [
        { symbol: "sh600519", ticker: "600519", name: "贵州茅台", price: 1258.62, peRatio: 20.1 },
        { symbol: "sz000001", ticker: "000001", name: "平安银行", price: 10 },
      ],
      notice: "来源只提供行情时分，未提供交易日期；抓取时间不代表行情日期。市值单位未核实，未用于筛选。",
    });
    const evidence = JSON.stringify({
      results: [{ knowledgeItemId: "k1", excerpt: "营业收入 200.00 元" }],
      citations: [{ knowledgeItemId: "k1", financialEvidence: [{ page: "42" }] }],
    });
    const report = projectStockReport([
      { role: "user", id: "u", timestamp: "", content: request },
      turn("completed", [
        { type: "tool_call", toolName: "financial_market_screen_tool", status: "completed", output: screen },
        { type: "tool_call", toolName: "financial_evidence_search_tool", status: "completed", input: JSON.stringify({ ticker: "sh600519", query: "营收", report_period: "2024FY" }), output: evidence },
        { type: "tool_call", toolName: "financial_report_query_tool", status: "completed", output: "{\"page\":7}" },
        { ...final, text: "模型说明工具不支持市值。毛利率 91.93%。" },
      ]),
    ])!;
    expect(report.text).toContain("| 贵州茅台 | 600519 | 第 42 页 |");
    expect(report.text).toContain("| 平安银行 | 000001 | 没有这一项 |");
    expect(report.text).toContain("覆盖不完整，结果仅基于已加载范围。");
    expect(report.text).toContain("候选和财报页码以上表为准");
    expect(report.text).toContain("工具不支持市值");
    expect(report.text).not.toContain("1258.62");
    expect(report.text).not.toContain("91.93");
    expect(report.text).not.toContain("第 7 页");
    expect(researchTablePreview(report.text)).toContain("600519");
    const cleared = JSON.stringify({
      ok: true, status: "partial", source: "新浪财经", fetchedAt: "2026-10-06T10:00:00+08:00",
      coverage: { providerTotal: 5000, loaded: 120, complete: false, totalFiltered: 0 }, returnedCount: 0, items: [],
      message: "筛选快照没有不晚于分析日期 2024-12-31 的交易日期，未作为本次研究依据。",
      notice: "筛选快照没有不晚于分析日期 2024-12-31 的交易日期，未作为本次研究依据。",
    });
    const empty = projectStockReport([
      { role: "user", id: "u2", timestamp: "", content: request },
      turn("completed", [
        { type: "tool_call", toolName: "financial_market_screen_tool", status: "completed", output: cleared },
        { ...final, text: "虚构股份 999999 见第1页" },
      ]),
    ])!;
    expect(empty.text).toContain("未作为本次研究依据");
    expect(empty.text).toContain("没有符合条件的候选");
    expect(empty.text).not.toContain("虚构股份");
    const unchanged = projectStockReport([
      { role: "user", id: "u3", timestamp: "", content: request },
      turn("completed", [{ ...final, text: "目标Turn筛选结论" }]),
    ])!;
    expect(unchanged.text).toBe("目标Turn筛选结论");
    const laterScreen = projectStockReport([
      { role: "user", id: "stock", timestamp: "", content: stockResearchPrompt(stock, "2024FY", "2026-10-04", "financial", "brief") },
      { ...turn("completed", [final]), turnId: "stock-turn" },
      { role: "user", id: "screen", timestamp: "", content: request },
      { ...turn("completed", [{ ...final, text: "目标Turn筛选结论" }]), turnId: "screen-turn" },
    ]);
    expect(laterScreen?.turnId).toBe("screen-turn");
  });
});
