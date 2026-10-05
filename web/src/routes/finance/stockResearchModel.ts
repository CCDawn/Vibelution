import type { AssistantConversationTurn, ConversationMessage, SessionSummary } from "../../api/types";
import type { StockCandle, StockIdentity, StockSnapshot } from "../../api/financialMarket";
import { safeFinancialSourceUrl } from "./financialResearchModel";

export type ReportCitation = { url: string; page: string; label: string };
export type StockResearchReport = { turnId: string; timestamp: string; text: string; summary: string; sections: { id: string; title: string; text: string }[]; citations: ReportCitation[] };
export type ResearchScope = "financial" | "events" | "risk" | "comprehensive";
export type ResearchTerminalState = Pick<SessionSummary, "terminalReason" | "lastTurnStatus" | "lastTurnTerminalTurnId">;
export const EMPTY_FINANCIAL_MESSAGES: ConversationMessage[] = [];

export function isBlankResearchPlaceholder(row: SessionSummary) {
  // The native Agent query also appends an unpersisted direct-session stub.
  // Such a blank stub has no searchable body; indexed body-only hits must stay.
  // Native lists populate ready/idle even when the stub has never had a turn.
  return !row.updatedAt && !row.lastActive && !row.taskSummary
    && !row.lastTurnTerminalTurnId
    && ["", "ready", "idle"].includes(row.lastTurnStatus ?? "")
    && ["", "ready", "idle"].includes(row.terminalReason ?? "");
}

export function isResearchSearchResult(row: SessionSummary, query: string) {
  const needle = query.trim().toLocaleLowerCase();
  return !needle || !isBlankResearchPlaceholder(row) || row.title.toLocaleLowerCase().includes(needle);
}

export function cleanResearchPreview(text: string, limit = 100) {
  // Tables and source metadata are not prose. Keep them in the canonical report
  // instead of flattening financial columns into an unreadable summary.
  return text.replace(/```[\s\S]*?```/g, "").split("\n")
    .filter((line) => !line.includes("|") && !/^\s*[-: ]{3,}\s*$/.test(line)
      && !/^\s*(?:[-*]\s*)?(?:来源|证据来源|PDF|source)\s*[：:]/i.test(line)
      && !/^\s{0,3}#{1,3}\s/.test(line))
    .join(" ").replace(/\[([^\]]+)\]\(https?:\/\/[^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "").replace(/[#*_`>]/g, " ")
    .replace(/\s+/g, " ").trim().slice(0, limit);
}

/** An exact, bounded table excerpt for reports that have no prose conclusion. */
export function researchTablePreview(text: string) {
  const lines = text.split("\n");
  const start = lines.findIndex((line, index) => line.includes("|")
    && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1] ?? ""));
  if (start < 0) return "";
  const rows: string[] = [];
  for (const line of lines.slice(start, start + 7)) {
    if (!line.includes("|")) break;
    rows.push(line);
  }
  return rows.join("\n");
}
export function researchRecordStatus(row: Pick<SessionSummary, "status" | "terminalReason" | "lastTurnStatus">, zh = true) {
  if (["running", "queued"].includes(row.status)) return zh ? "研究中" : "Running";
  if (row.status === "stopping") return zh ? "正在停止" : "Stopping";
  const outcome = row.terminalReason || row.lastTurnStatus || row.status;
  if (["needs_continue", "paused_limit", "paused"].includes(outcome) || ["needs_continue", "paused_limit"].includes(row.status)) return zh ? "待继续" : "Needs continuation";
  if (["stopped_by_user", "stopped", "aborted", "cancelled", "superseded"].includes(outcome)) return zh ? "已停止" : "Stopped";
  if (row.status === "failed" || row.lastTurnStatus === "failed" || row.terminalReason?.startsWith("failed")) return zh ? "失败" : "Failed";
  if (row.terminalReason === "success" || row.lastTurnStatus === "completed" || row.status === "completed") return zh ? "已完成" : "Completed";
  return zh ? "研究会话" : "Research session";
}
export function localResearchDate(now = new Date()) {
  return `${String(now.getFullYear()).padStart(4, "0")}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
export function isValidResearchDate(value: string, now = new Date()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00`);
  return Number.isFinite(date.getTime()) && date.getFullYear() > 0 && localResearchDate(date) === value && value <= localResearchDate(now);
}
export function latestResearchTurn(messages: readonly ConversationMessage[]): AssistantConversationTurn | undefined {
  return [...messages].reverse().find((message): message is AssistantConversationTurn => message.role === "assistant");
}
export function reportMatchesStock(report: StockResearchReport | null, messages: readonly ConversationMessage[], stock: StockIdentity) {
  if (!report) return false;
  const index = messages.findIndex((message) => message.role === "assistant" && message.turnId === report.turnId);
  for (const message of messages.slice(0, index).reverse()) {
    if (message.role !== "user") continue;
    const tickers = [...new Set([...message.content.matchAll(/(?:^|[^\d])([036489]\d{5})(?!\d)/g)].map((match) => match[1]))];
    if (tickers.length) return tickers.length === 1 && tickers[0] === stock.ticker;
    if (message.content.includes(stock.name)) return true;
  }
  return false;
}
export function projectStockReport(messages: readonly ConversationMessage[], terminal?: ResearchTerminalState | null): StockResearchReport | null {
  // Read final-answer items from the native transcript. Never promote commentary,
  // reasoning, a tool output, or an unfinished assistant turn into a report.
  const candidates: { turn: AssistantConversationTurn; text: string; request: string }[] = [];
  const latest = latestResearchTurn(messages);
  let request = "";
  for (const message of messages) {
    if (message.role === "user") { request = message.content; continue; }
    if (message.status !== "completed") continue;
    const terminalTurn = terminal?.lastTurnTerminalTurnId || latest?.turnId;
    const outcome = terminal?.terminalReason || terminal?.lastTurnStatus || "";
    if (message.turnId === terminalTurn && /^(?:stopped|aborted|cancelled|superseded|failed|needs_continue|paused)/.test(outcome)) continue;
    const text = message.turnItems.filter((item) => item.type === "agent_message" && item.phase === "final_answer" && item.status === "completed").map((item) => item.type === "agent_message" ? item.text : "").join("\n\n");
    // Older native interrupted turns may be represented as completed messages.
    // Their native stop notice remains a notice even after a successful resume.
    if (!text.trim() || /(?:^|\n\n)(?:本轮已按请求停止[。，]|This turn was stopped (?:as requested|before it started)\.)/i.test(text)) continue;
    candidates.push({ turn: message, text, request });
  }
  // Native finance starts carry this request contract. Ordinary follow-ups stay
  // in the conversation, leaving the full report and its export stable.
  const isResearchRequest = (text: string) => /分析日期 \d{4}-\d{2}-\d{2}[\s\S]*使用 Markdown 二级标题/.test(text)
    || /(?:重新生成|更新|重写)(?:完整)?(?:研究报告|研报)|(?:regenerate|update|rewrite) (?:the )?(?:full )?(?:research )?report/i.test(text);
  const selected = candidates.filter((candidate) => isResearchRequest(candidate.request)).at(-1) ?? candidates[0];
  if (!selected) return null;
  const { turn, text } = selected;
  const sections: StockResearchReport["sections"] = [];
  const headings = [...text.matchAll(/^\s{0,3}#{1,3}\s+(.+)$/gm)];
  headings.forEach((heading, index) => sections.push({ id: `section-${index}`, title: cleanResearchPreview(heading[1], 25), text: text.slice(heading.index, headings[index + 1]?.index ?? text.length).trim() }));
  const intro = text.slice(0, headings[0]?.index ?? text.length).trim();
  const conclusion = sections.find((section) => /结论|摘要|简报|summary|conclusion/i.test(section.title))?.text || intro || sections[0]?.text || text;
  const conclusions = [...conclusion.matchAll(/^\s*[-*]\s+(.+)$/gm)].slice(0, 2).map((match) => match[1]).join(" ");
  const citations: ReportCitation[] = [];
  for (const match of text.matchAll(/https?:\/\/[^\s<>"\])。，；、）]+/g)) {
    const safeUrl = safeFinancialSourceUrl(match[0].replace(/[。，；、.]+$/, ""));
    if (!safeUrl) continue;
    const parsed = new URL(safeUrl);
    const anchoredPage = /^#page=(\d{1,6})$/i.exec(parsed.hash)?.[1];
    if (anchoredPage) parsed.hash = "";
    const url = parsed.toString();
    const lineStart = Math.max(text.lastIndexOf("\n", match.index) + 1, match.index - 200);
    const before = text.slice(lineStart, match.index).split(/https?:\/\/[^\s<>"\])。，；、）]+/).at(-1) || "";
    const after = text.slice(match.index + match[0].length).split("\n", 1)[0].slice(0, 40);
    const pagesIn = (value: string) => [...value.matchAll(/(?:第\s*|PDF\s*)(\d{1,6})\s*页|\b(?:p\.|page\s+)(\d{1,6})\b/gi)].map((item) => item[1] || item[2]);
    const precedingPages = pagesIn(before);
    const directPages = /\.pdf$/i.test(parsed.pathname) ? (precedingPages.length ? precedingPages : pagesIn(after)) : [];
    // A common report citation lists its pages on the title line and the PDF
    // URL on the following line. Only that same contiguous source block counts.
    const block = text.slice(Math.max(text.lastIndexOf("\n\n", match.index) + 2, match.index - 400, 0), match.index);
    const blockPages = /\.pdf$/i.test(parsed.pathname) && !/https?:\/\//.test(block) && /财报|年报|年度报告|原文|annual report/i.test(block) ? pagesIn(block) : [];
    const pages = anchoredPage ? [anchoredPage] : directPages.length ? [...new Set(directPages)] : blockPages.length ? [...new Set(blockPages)] : [""];
    for (const page of pages) {
      if (citations.some((item) => item.url === url && item.page === page)) continue;
      citations.push({ url, page, label: page ? `PDF · 第 ${page} 页` : parsed.hostname });
    }
  }
  return { turnId: turn.turnId, timestamp: turn.timestamp, text, summary: cleanResearchPreview(conclusions || conclusion.replace(/^\s{0,3}#{1,3}\s+.+\n/, ""), 240), sections, citations: citations.slice(0, 12) };
}
export type ResearchDepth = "brief" | "basic" | "standard" | "detailed" | "exhaustive";
export const RESEARCH_DEPTH_INSTRUCTIONS: Record<ResearchDepth, string> = {
  brief: "简明回答，优先核实最重要的事实",
  basic: "基础研究，交叉核对关键行情、财务与事件",
  standard: "标准研究，覆盖市场、基本面、新闻、行业和主要风险，列出多空依据",
  detailed: "详细核对，比较多个来源，讨论估值、催化剂、反例与多种情景",
  exhaustive: "全面研究，逐项核对原始证据、行业对照、多空论点、情景与风险，明确证据不足之处",
};

export function stockResearchPrompt(stock: StockIdentity, period: string, date: string, scope: ResearchScope, depth: ResearchDepth, snapshot?: StockSnapshot) {
  const subject = `${stock.name}（${stock.ticker}，${stock.market}）`;
  const task = { financial: "财报、盈利质量与现金流", events: "重大事件及新闻来源", risk: "财务、经营和估值风险", comprehensive: "财报、盈利质量、事件与主要风险" }[scope];
  const quote = snapshot?.stock.symbol === stock.symbol ? `\n行情快照（腾讯财经公开行情，可能延迟）：${snapshot.stock.timestamp}，价格 ${snapshot.stock.price} 元，涨跌 ${snapshot.stock.changePercent}%。这是带时点的报价，不是已审核财报证据。` : "";
  return `请研究 ${subject}，分析日期 ${date}${period.trim() ? `，报告期 ${period.trim()}` : ""}，重点检查${task}。${RESEARCH_DEPTH_INSTRUCTIONS[depth]}，使用 Markdown 二级标题“结论、市场与技术、基本面、新闻与催化剂、行业与大盘、多空论证、情景分析、风险、证据来源”组织结果；不适用的章节简要说明缺失证据。财报数值只用已审核原始 PDF 证据，注明报告期、页码和官方链接；新闻注明来源与日期。区分事实、推论和缺失数据，不编造行情、指标或买卖建议。${quote}`;
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
