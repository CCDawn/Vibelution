import type { AssistantConversationTurn, ConversationMessage, SessionSummary } from "../../api/types";
import type { StockCandle, StockIdentity, StockSnapshot } from "../../api/financialMarket";
import { safeFinancialSourceUrl } from "./financialResearchModel";

export type ReportCitation = { url: string; page: string; label: string };
export type StockResearchReport = { turnId: string; timestamp: string; text: string; summary: string; sections: { id: string; title: string; text: string }[]; citations: ReportCitation[] };
export type ResearchScope = "financial" | "events" | "risk" | "comprehensive";
export const EMPTY_FINANCIAL_MESSAGES: ConversationMessage[] = [];

export function cleanResearchPreview(text: string, limit = 100) {
  return text.replace(/https?:\/\/\S+/g, "").replace(/[|#*_`>]/g, " ").replace(/\s+/g, " ").trim().slice(0, limit);
}
export function researchRecordStatus(row: Pick<SessionSummary, "status" | "terminalReason" | "lastTurnStatus">, zh = true) {
  if (row.status === "running") return zh ? "研究中" : "Running";
  if (row.terminalReason === "needs_continue") return zh ? "待继续" : "Needs continuation";
  if (row.status === "failed" || row.lastTurnStatus === "failed" || row.terminalReason?.startsWith("failed")) return zh ? "失败" : "Failed";
  if (row.terminalReason === "success" || row.lastTurnStatus === "completed") return zh ? "已完成" : "Completed";
  return zh ? "研究会话" : "Research session";
}
export function latestResearchTurn(messages: readonly ConversationMessage[]): AssistantConversationTurn | undefined {
  return [...messages].reverse().find((message): message is AssistantConversationTurn => message.role === "assistant");
}
export function reportMatchesStock(report: StockResearchReport | null, messages: readonly ConversationMessage[], stock: StockIdentity) {
  if (!report) return false;
  const index = messages.findIndex((message) => message.role === "assistant" && message.turnId === report.turnId);
  for (const message of messages.slice(0, index).reverse()) {
    if (message.role !== "user") continue;
    const tickers = [...message.content.matchAll(/(?:^|[^\d])([036489]\d{5})(?!\d)/g)].map((match) => match[1]);
    if (tickers.length) return tickers.length === 1 && tickers[0] === stock.ticker;
    if (message.content.includes(stock.name)) return true;
  }
  return false;
}
export function projectStockReport(messages: readonly ConversationMessage[]): StockResearchReport | null {
  // Read final-answer items from the native transcript. Never promote commentary,
  // reasoning, a tool output, or an unfinished assistant turn into a report.
  const turn = [...messages].reverse().find((message): message is AssistantConversationTurn => message.role === "assistant" && message.status === "completed" && message.turnItems.some((item) => item.type === "agent_message" && item.phase === "final_answer" && item.status === "completed"));
  if (!turn) return null;
  const text = turn.turnItems.filter((item) => item.type === "agent_message" && item.phase === "final_answer" && item.status === "completed").map((item) => item.type === "agent_message" ? item.text : "").join("\n\n");
  if (!text.trim()) return null;
  const sections: StockResearchReport["sections"] = [];
  const headings = [...text.matchAll(/^\s{0,3}#{1,3}\s+(.+)$/gm)];
  headings.forEach((heading, index) => sections.push({ id: `section-${index}`, title: cleanResearchPreview(heading[1], 25), text: text.slice(heading.index, headings[index + 1]?.index ?? text.length).trim() }));
  const intro = text.slice(0, headings[0]?.index ?? text.length).trim();
  const conclusion = sections.find((section) => /结论|摘要|简报|summary|conclusion/i.test(section.title))?.text || intro || sections[0]?.text || text;
  const conclusions = [...conclusion.matchAll(/^\s*[-*]\s+(.+)$/gm)].slice(0, 2).map((match) => match[1]).join(" ");
  const citations: ReportCitation[] = [];
  for (const match of text.matchAll(/https?:\/\/[^\s<>"\])]+/g)) {
    const safeUrl = safeFinancialSourceUrl(match[0].replace(/[。，；、.]+$/, ""));
    if (!safeUrl) continue;
    const parsed = new URL(safeUrl);
    const anchoredPage = /^#page=(\d{1,6})$/i.exec(parsed.hash)?.[1];
    if (anchoredPage) parsed.hash = "";
    const url = parsed.toString();
    const lineStart = Math.max(text.lastIndexOf("\n", match.index) + 1, match.index - 200);
    const before = text.slice(lineStart, match.index);
    const after = text.slice(match.index + match[0].length).split("\n", 1)[0].slice(0, 40);
    const pagesIn = (value: string) => [...value.matchAll(/(?:第\s*|PDF\s*)(\d{1,6})\s*页|\b(?:p\.|page\s+)(\d{1,6})\b/gi)].map((item) => item[1] || item[2]);
    const directPage = anchoredPage || pagesIn(before).at(-1) || pagesIn(after)[0];
    // A common report citation lists its pages on the title line and the PDF
    // URL on the following line. Only that same contiguous source block counts.
    const block = text.slice(Math.max(text.lastIndexOf("\n\n", match.index) + 2, match.index - 400, 0), match.index);
    const blockPages = /\.pdf$/i.test(parsed.pathname) && /财报|年报|年度报告|原文|annual report/i.test(block) ? pagesIn(block) : [];
    const pages = directPage ? [directPage] : blockPages.length ? [...new Set(blockPages)] : [""];
    for (const page of pages) {
      if (citations.some((item) => item.url === url && item.page === page)) continue;
      citations.push({ url, page, label: page ? `PDF · 第 ${page} 页` : parsed.hostname });
    }
  }
  return { turnId: turn.turnId, timestamp: turn.timestamp, text, summary: cleanResearchPreview(conclusions || conclusion.replace(/^\s{0,3}#{1,3}\s+.+\n/, ""), 240), sections, citations: citations.slice(0, 12) };
}
export function stockResearchPrompt(stock: StockIdentity, period: string, date: string, scope: ResearchScope, depth: "brief" | "detailed", snapshot?: StockSnapshot) {
  const subject = `${stock.name}（${stock.ticker}，${stock.market}）`;
  const task = { financial: "财报、盈利质量与现金流", events: "重大事件及新闻来源", risk: "财务、经营和估值风险", comprehensive: "财报、盈利质量、事件与主要风险" }[scope];
  const quote = snapshot?.stock.symbol === stock.symbol ? `\n行情快照（腾讯财经公开行情，可能延迟）：${snapshot.stock.timestamp}，价格 ${snapshot.stock.price} 元，涨跌 ${snapshot.stock.changePercent}%。这是带时点的报价，不是已审核财报证据。` : "";
  return `请研究 ${subject}，分析日期 ${date}${period.trim() ? `，报告期 ${period.trim()}` : ""}，重点检查${task}。${depth === "brief" ? "简明回答" : "详细核对"}，使用 Markdown 二级标题“结论、关键事实、风险、证据来源”组织结果。财报数值只用已审核原始 PDF 证据，注明报告期、页码和官方链接；新闻注明来源与日期。区分事实、推论和缺失数据，不编造行情、指标或买卖建议。${quote}`;
}
export function movingAverage(candles: readonly StockCandle[], length: number): (number | null)[] {
  let sum = 0;
  return candles.map((candle, index) => {
    sum += candle.close;
    if (index >= length) sum -= candles[index - length].close;
    return index + 1 < length ? null : sum / length;
  });
}
export function stockIdentityFromUnknown(value: unknown): StockIdentity | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  return typeof item.symbol === "string" && /^(sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})$/.test(item.symbol)
    && typeof item.ticker === "string" && item.ticker === item.symbol.slice(2)
    && typeof item.name === "string" && item.name.length > 0 && item.name.length <= 60 && typeof item.market === "string"
    ? { symbol: item.symbol, ticker: item.ticker, name: item.name, market: item.market.slice(0, 20) } : null;
}
export function quoteNumber(value: number | null | undefined, digits = 2) { return value == null || !Number.isFinite(value) ? "—" : value.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }); }
export function yuanAmount(value: number | null | undefined) { return value == null ? "—" : value >= 100_000_000 ? `${quoteNumber(value / 100_000_000)} 亿` : `${quoteNumber(value / 10_000)} 万`; }
