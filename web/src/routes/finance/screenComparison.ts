import type { SessionTurnItem } from "../../api/types";
import { MISSING_FIGURE, filingExcerptsFromToolOutput } from "./conclusionFigures";

export const SCREEN_COMPARISON_HEADING = "## 筛选对照（本轮工具结果）";
const FAILED = new Set(["failed", "error", "timeout", "timed_out", "blocked", "cancelled", "canceled", "interrupted"]);
const SCREENING_REPORT_PROMPT = /^请研究以下股票筛选条件，生成筛选报告。分析截至 (\d{4}-\d{2}-\d{2})。按条件筛选股票，列出候选、筛选依据和数据限制。(?:\r?\n|$)/;
const A_SHARE = /(?<!\d)([036489]\d{5})(?!\d)/;
const TICKER_FIELD = /"(?:ticker|symbol)"\s*:\s*"([^"\\]{1,40})"/;
const MAX_ROWS = 20;
const MAX_PAGES = 12;
const FILING_HOSTS = new Set([
  "static.cninfo.com.cn",
  "www.cninfo.com.cn",
  "www.sse.com.cn",
  "static.sse.com.cn",
  "query.sse.com.cn",
  "www.szse.cn",
  "disc.static.szse.cn",
  "www.bse.cn",
]);
const BLOCKED_FILING_TITLE = ["摘要", "英文", "取消", "更正", "补充"];

type ToolRecord = { name: string; input: string; output: string; status: string };
type ScreenPayload = {
  source?: unknown;
  fetchedAt?: unknown;
  coverage?: unknown;
  returnedCount?: unknown;
  outputTruncated?: unknown;
  message?: unknown;
  notice?: unknown;
  items?: unknown;
};

export function isScreeningReportPrompt(text: string): boolean {
  const match = SCREENING_REPORT_PROMPT.exec((text || "").trim());
  return Boolean(match && isCalendarDate(match[1] ?? ""));
}

export function projectScreeningComparison(reportText: string, requestText: string, items: readonly SessionTurnItem[]): string {
  const original = reportText || "";
  if (!isScreeningReportPrompt(requestText) || original.startsWith(`${SCREEN_COMPARISON_HEADING}\n`)) return original;
  const records = toolRecords(items);
  const payload = lastScreenPayload(records);
  if (!payload) return original;
  const cutoff = analysisDate(requestText);
  const rows = screenRows(payload, cutoff);
  const block = renderComparison(payload, rows, pagesByCode(records, new Set(rows.map((row) => row.code))));
  if (!rows.length) return block;
  const body = original.trim();
  if (!body) return block;
  return `${block}\n## 模型原文\n\n候选、公告原文和财报页码以上表为准。\n\n${body}\n`;
}

function analysisDate(requestText: string): string {
  return SCREENING_REPORT_PROMPT.exec((requestText || "").trim())?.[1] ?? "";
}

function isCalendarDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  if (!year || month < 1 || month > 12 || day < 1 || day > 31) return false;
  const date = new Date(year, month - 1, day);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
}

function toolRecords(items: readonly SessionTurnItem[]): ToolRecord[] {
  const records: ToolRecord[] = [];
  for (const item of items) {
    if (item.type !== "tool_call" || !item.toolName || !item.output) continue;
    records.push({ name: item.toolName, input: item.input ?? "", output: item.output, status: item.status });
  }
  return records;
}

function lastScreenPayload(records: readonly ToolRecord[]): ScreenPayload | null {
  let found: ScreenPayload | null = null;
  for (const record of records) {
    if (record.name !== "financial_market_screen_tool" || FAILED.has(record.status.toLowerCase())) continue;
    const payload = screenPayload(record.output);
    if (payload) found = payload;
  }
  return found;
}

function screenPayload(output: string): ScreenPayload | null {
  let payload: unknown;
  try {
    payload = JSON.parse(output);
  } catch {
    return null;
  }
  if (!payload || typeof payload !== "object" || (payload as { ok?: unknown }).ok !== true) return null;
  const record = payload as ScreenPayload & { ok?: unknown; status?: unknown };
  if (record.status !== "complete" && record.status !== "partial") return null;
  if (!Array.isArray(record.items)) return null;
  return record;
}

function pagesByCode(records: readonly ToolRecord[], codes: ReadonlySet<string>): Map<string, string> {
  const found = new Map<string, Set<number>>();
  for (const record of records) {
    if (record.name !== "financial_evidence_search_tool" || FAILED.has(record.status.toLowerCase())) continue;
    const code = tickerFromInput(record.input);
    if (!codes.has(code)) continue;
    const pages = new Set(filingExcerptsFromToolOutput(record.name, record.output).map((excerpt) => excerpt.page));
    if (!pages.size) continue;
    const prior = found.get(code) ?? new Set<number>();
    for (const page of pages) prior.add(page);
    found.set(code, prior);
  }
  return new Map([...found].map(([code, pages]) => [code, formatPages(pages)]));
}

function screenRows(payload: ScreenPayload, cutoff: string): Array<{ name: string; code: string; filing: string }> {
  const items = Array.isArray(payload.items) ? payload.items : [];
  const rows: Array<{ name: string; code: string; filing: string }> = [];
  for (const raw of items.slice(0, MAX_ROWS)) {
    if (!raw || typeof raw !== "object") continue;
    const record = raw as Record<string, unknown>;
    const row = identity(record);
    if (row) rows.push({ ...row, filing: filingCell(record, cutoff) });
  }
  return rows;
}

function filingCell(row: Record<string, unknown>, cutoff: string): string {
  const filing = row.officialFiling;
  if (!filing || typeof filing !== "object") return MISSING_FIGURE;
  const record = filing as Record<string, unknown>;
  const title = filingTitle(record.title);
  if (!title) return MISSING_FIGURE;
  const url = typeof record.url === "string" ? record.url : "";
  const announced = typeof record.announcedOn === "string" ? record.announcedOn : "";
  if (!allowedFilingUrl(url) || !isCalendarDate(announced) || !isCalendarDate(cutoff) || announced > cutoff) return MISSING_FIGURE;
  return `[${title}（${announced}）](${url})`;
}

function filingTitle(value: unknown): string {
  if (typeof value !== "string") return "";
  const text = value
    .replace(/<[^>]{0,80}>/g, "")
    .replace(/[|\r\n[\]]/g, " ")
    .replace(/[()]/g, (char) => (char === "(" ? "（" : "）"))
    .replace(/\s+/g, " ")
    .trim();
  if (!text || text.length > 80 || !text.includes("年度报告") || BLOCKED_FILING_TITLE.some((word) => text.includes(word))) return "";
  return text;
}

function allowedFilingUrl(value: string): boolean {
  if (!value || value.length > 240 || /\s/.test(value) || value.includes("..") || value.includes("\\")) return false;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  const host = url.hostname.toLowerCase();
  return url.protocol === "https:"
    && !url.username
    && !url.password
    && (!url.port || url.port === "443")
    && !url.search
    && !url.hash
    && FILING_HOSTS.has(host)
    && url.pathname.toLowerCase().endsWith(".pdf");
}

function renderComparison(payload: ScreenPayload, rows: readonly { name: string; code: string; filing: string }[], pages: ReadonlyMap<string, string>): string {
  const lines = [SCREEN_COMPARISON_HEADING, ""];
  const source = plain(payload.source, 100);
  const fetched = plain(payload.fetchedAt, 64);
  if (source) lines.push(`来源：${source}`);
  if (fetched) lines.push(`抓取时间：${fetched}`);
  lines.push(coverageLine(payload));
  const count = countLine(payload);
  if (count) lines.push(count);
  if (payload.outputTruncated === true) lines.push("工具输出已截断，未列入被省略的候选。");
  const message = plain(payload.message, 240);
  const notice = plain(payload.notice, 240);
  if (message) lines.push(message);
  if (notice && notice !== message) lines.push(notice);
  lines.push("");
  if (!rows.length) {
    lines.push("没有符合条件的候选。");
    return `${lines.join("\n").trimEnd()}\n`;
  }
  lines.push("| 股票 | 代码 | 公告原文 | 财报页码 |", "| --- | --- | --- | --- |");
  for (const row of rows) lines.push(`| ${row.name} | ${row.code} | ${row.filing} | ${pages.get(row.code) || MISSING_FIGURE} |`);
  lines.push("", "行情价格、市盈率和市净率不是财报，不列入本表。", "公告原文只列巨潮资讯或交易所年报链接。");
  return `${lines.join("\n").trimEnd()}\n`;
}

function coverageLine(payload: ScreenPayload): string {
  const coverage = payload.coverage && typeof payload.coverage === "object" ? payload.coverage as { complete?: unknown; loaded?: unknown; providerTotal?: unknown } : {};
  const scope = coverage.complete === true ? "覆盖完整。" : "覆盖不完整，结果仅基于已加载范围。";
  if (nonnegativeInt(coverage.loaded) && nonnegativeInt(coverage.providerTotal)) return `已加载 ${coverage.loaded} / 行情池 ${coverage.providerTotal}。${scope}`;
  return scope;
}

function countLine(payload: ScreenPayload): string {
  if (!nonnegativeInt(payload.returnedCount)) return "";
  const coverage = payload.coverage && typeof payload.coverage === "object" ? payload.coverage as { totalFiltered?: unknown } : {};
  if (nonnegativeInt(coverage.totalFiltered) && coverage.totalFiltered !== payload.returnedCount) return `符合条件 ${coverage.totalFiltered}，本次返回 ${payload.returnedCount}。`;
  return `符合条件 ${payload.returnedCount}。`;
}

function identity(row: Record<string, unknown>): { name: string; code: string } | null {
  const ticker = typeof row.ticker === "string" ? row.ticker : "";
  const symbol = typeof row.symbol === "string" ? row.symbol : "";
  const code = tickerKey(ticker) || tickerKey(symbol);
  if (!code) return null;
  return { name: plain(row.name, 60) || code, code };
}

function tickerFromInput(raw: string): string {
  const text = (raw || "").trim();
  if (!text) return "";
  try {
    const payload = JSON.parse(text) as { ticker?: unknown; symbol?: unknown };
    if (payload && typeof payload === "object") {
      for (const value of [payload.ticker, payload.symbol]) {
        if (typeof value === "string" && value.trim()) return tickerKey(value);
      }
    }
  } catch {
    // A truncated argument string can still carry the ticker field.
  }
  const match = TICKER_FIELD.exec(text);
  return match ? tickerKey(match[1] ?? "") : "";
}

function tickerKey(value: string): string {
  const text = (value || "").trim();
  if (!text) return "";
  const match = A_SHARE.exec(text);
  if (match) return match[1] ?? "";
  return text.replace(/\s+/g, "").toUpperCase().slice(0, 20);
}

function formatPages(pages: ReadonlySet<number>): string {
  const ordered = [...pages].sort((left, right) => left - right);
  const shown = ordered.slice(0, MAX_PAGES).map((page) => `第 ${page} 页`).join("、");
  return ordered.length > MAX_PAGES ? `${shown}等` : shown;
}

function plain(value: unknown, limit: number): string {
  if (typeof value !== "string") return "";
  const text = value.replace(/[\r\n|]+/g, " ").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, limit).trimEnd()}…`;
}

function nonnegativeInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}
