import { describe, expect, it } from "vitest";
import type { AssistantConversationTurn, ConversationMessage, SessionTurnItem } from "../../api/types";
import { movingAverage, projectStockReport, reportMatchesStock, stockIdentityFromUnknown, stockResearchPrompt } from "./stockResearchModel";

const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
function turn(status = "completed", items: unknown[] = []): AssistantConversationTurn { return { role: "assistant", id: "a", turnId: "t", status: status as AssistantConversationTurn["status"], timestamp: "2026-10-04T12:00:00Z", turnItems: items as SessionTurnItem[] }; }
const final = { type: "agent_message", phase: "final_answer", status: "completed", text: "## 结论\n需继续核对现金流。\n## 关键事实\n来自原始PDF第5页：https://example.com/report.pdf\n## 风险\n资料不足。" };
describe("stock research projections", () => {
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
});
