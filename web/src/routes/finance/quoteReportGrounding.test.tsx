// @vitest-environment happy-dom
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { SessionTurnItem } from "../../api/types";
import { ConversationMarkdownRenderer } from "../../components/conversation/ConversationMarkdownRenderer";
import { groundResearchConclusion, normalizeFinancialReportLinks } from "./conclusionFigures";
import { projectStockReport } from "./stockResearchModel";

const source = "https://gu.qq.com/sz000001/gp";
const text = `**结论**：平安银行（sz000001）最新公开报价为 **11.57 元/股（人民币 CNY）**，行情日期 **2026-09-30**，来源腾讯财经（${source}），本次抓取时间2026-10-07。\n\n**关键事实**\n- 前收11.35，最高11.65。\n\n**风险**\n- 报价可能延迟。`;
const payload = { ok: true, status: "partial", ticker: "sz000001", currency: "CNY", priceUnit: "元", sourceUrl: source, fetchedAt: "2026-10-07T05:57:00Z", quote: { symbol: "sz000001", ticker: "000001", currency: "CNY", price: 11.57, timestamp: "2026-09-30T16:15:00+08:00" } };
function tool(value: unknown = payload, status = "completed"): SessionTurnItem {
  return { type: "tool_call", toolName: "financial_market_snapshot_tool", output: JSON.stringify(value), status } as SessionTurnItem;
}

describe("same-turn market report grounding", () => {
  it("keeps a sourced quote while limiting bold conclusion grounding to its section", () => {
    const result = groundResearchConclusion(text, [], [tool()]);
    expect(result).toContain("**11.57 元/股");
    expect(result).toContain("前收11.35，最高11.65");
    expect(groundResearchConclusion(text, [])).toContain("没有这一项/股");
    expect(groundResearchConclusion("**利润**：11.57 元", [])).toContain("没有这一项");
    expect(groundResearchConclusion(text.replace("**结论**", "**结论（先说）**"), [], [tool()])).toContain("**11.57 元/股");
  });

  it.each([
    ["failed", payload, "failed"],
    ["unavailable", { ...payload, ok: false }, "completed"],
    ["null quote", { ...payload, quote: null }, "completed"],
    ["other stock", { ...payload, quote: { ...payload.quote, symbol: "sh600519" } }, "completed"],
    ["other currency", { ...payload, quote: { ...payload.quote, currency: "USD" } }, "completed"],
    ["no source", { ...payload, sourceUrl: "" }, "completed"],
    ["no date", { ...payload, quote: { ...payload.quote, timestamp: "" } }, "completed"],
    ["wrong date", { ...payload, quote: { ...payload.quote, timestamp: "2026-10-07T05:57:00Z" } }, "completed"],
  ])("does not accept %s market evidence", (_name, evidence, status) => {
    expect(groundResearchConclusion(text, [], [tool(evidence, status)])).not.toContain("**11.57 元/股");
  });

  it("never lets quote prices validate filing amounts, arithmetic or forecasts", () => {
    const extra = text.replace("，行情日期", "，利润11.57元，毛利率11.57%，11.57元 + 1.00元 = 12.57元，行情日期");
    const result = groundResearchConclusion(extra, [], [tool()]);
    expect(result).toContain("**11.57 元/股");
    expect(result).not.toContain("利润11.57元");
    expect(result).not.toContain("11.57%");
    expect(result).not.toContain("12.57元");
    for (const value of [text.replace("11.57 元", "11.58 元"), text.replace("最新公开报价", "目标价格"), text.replace("11.57 元", "11.57 美元"), text.replace("11.57 元", "11.5700000000000001 元")]) {
      expect(groundResearchConclusion(value, [], [tool()])).not.toContain(value.match(/\*\*([\d.]+ (?:元|美元))/)?.[1] ?? "11.57 元");
    }
    const separateSource = text.replace(`，来源腾讯财经（${source}）`, `。\n\n来源腾讯财经（${source}）`);
    expect(groundResearchConclusion(separateSource, [], [tool()])).not.toContain("**11.57 元/股");
    for (const identity of ["（sh000001）", "（sh600519）", ""] ) {
      expect(groundResearchConclusion(text.replace("（sz000001）", identity), [], [tool()])).not.toContain("**11.57 元/股");
    }
  });

  it.each([["hk00700", "HKD", "港元"], ["usAAPL", "USD", "美元"]])("preserves %s prices only in the market currency", (symbol, currency, unit) => {
    const url = `https://gu.qq.com/${symbol}/gp`;
    const evidence = { ...payload, ticker: symbol, currency, priceUnit: `${currency}/share`, sourceUrl: url, quote: { ...payload.quote, symbol, ticker: symbol.slice(2), currency } };
    const claim = `## 结论\n${symbol} 最新报价11.57 ${unit}/股，行情日期2026-09-30，${url}。`;
    expect(groundResearchConclusion(claim, [], [tool(evidence)])).toContain(`11.57 ${unit}`);
    expect(groundResearchConclusion(claim.replace(unit, "元"), [], [tool(evidence)])).toContain("没有这一项");
  });

  it("projects the exact final answer without changing its native stored text", () => {
    const answer = { type: "agent_message", status: "completed", phase: "final_answer", text } as SessionTurnItem;
    const report = projectStockReport([{ role: "user", id: "u", timestamp: "", content: "请对以下主题开展投资研究：核对平安银行公开行情。" }, { role: "assistant", id: "a", timestamp: "", status: "completed", turnId: "quote-turn", turnItems: [tool(), answer] }]);
    expect(report?.turnId).toBe("quote-turn");
    expect(report?.text).toContain("**11.57 元/股");
    expect(report?.citations[0].url).toBe(source);
    expect(answer.text).toBe(text);
  });

  it("renders Chinese punctuation outside the source href without changing Markdown links or code", () => {
    const projected = normalizeFinancialReportLinks(text);
    const html = renderToStaticMarkup(createElement(ConversationMarkdownRenderer, { content: projected }));
    const host = document.createElement("div"); host.innerHTML = html;
    expect(host.querySelector("a")?.getAttribute("href")).toBe(source);
    expect(normalizeFinancialReportLinks(projected)).toBe(projected);
    const protectedText = `[来源](${source})，\n\`${source}），示例\`\n\n\`\`\`\n${source}），示例\n\`\`\``;
    expect(normalizeFinancialReportLinks(protectedText)).toBe(protectedText);
  });
});
