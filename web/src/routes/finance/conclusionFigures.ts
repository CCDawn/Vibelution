import type { SessionTurnItem } from "../../api/types";

export const MISSING_FIGURE = "没有这一项";
const MAX_DIGITS = 40;
const FAILED = new Set(["failed", "error", "timeout", "timed_out", "blocked", "cancelled", "canceled", "interrupted"]);
const HEADING = /^[ \t]{0,3}(?:#{1,3}[ \t]+(.+?)[ \t]*$|\*\*([^*\r\n]{1,60})\*\*[ \t]*[：:]?[ \t]*)/gm;
const CONCLUSION = /结论|摘要|简报|summary|conclusion/i;
const BOLD_SECTION = /结论|摘要|简报|关键事实|核心事实|风险|建议|summary|conclusions?|key facts|facts|risks?|recommendations?/i;
const PAGE = /第\s*(\d{1,6})\s*页|PDF\s*(\d{1,6})\s*页|\b(?:p\.|page\s+)(\d{1,6})\b/gi;
const FENCE = /```[\s\S]*?```/g;
const AMOUNT = /(?<![\d.])([+-])?((?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?)(?![\d.])(\s*(?:%|％|万亿|亿元|万元|港元|美元|元|股))?/g;
const SCIENCE = /(?<![\d.])[+-]?\d+(?:\.\d+)?[eE][+-]?\d+(?![\d])/g;
const OPERATOR = /^\s*([+＋×*/／÷]|[-－−])\s*$/;
const EQUALS = /^\s*(?:=|＝|≈|约等于|约为)\s*$/;

export type FilingExcerpt = { page: number; text: string };
type Amount = { start: number; end: number; sign: string; number: string; unit: string };
type Dec = { neg: boolean; int: bigint; scale: number };

export function groundResearchConclusion(reportText: string, excerpts: readonly FilingExcerpt[], marketItems: readonly SessionTurnItem[] = []): string {
  const original = reportText || "";
  const text = asciiDigits(original);
  if (!text) return original;
  const pages = citedPages(text);
  const allowed = new Set<string>();
  for (const excerpt of excerpts) {
    if (pages.has(excerpt.page) && excerpt.text) {
      for (const value of numbersInText(excerpt.text)) allowed.add(value);
    }
  }
  const spans = conclusionSpans(text);
  if (!spans.length) return original;
  const fences = fenceSpans(text);
  const pageNumbers = new Set(allowed);
  let computed = new Set(pageNumbers);
  // These exact positions never enter the filing-number or calculation pool.
  const kept = marketPriceSpans(text, spans, marketItems);
  for (const [start, end] of spans) {
    const known = new Set(computed);
    for (let pass = 0; pass < 4; pass += 1) {
      const added = confirmedResults(text.slice(start, end), known, start, fences, text);
      const before = known.size;
      for (const value of added.values) known.add(value);
      if (known.size === before) break;
      for (const [left, right] of added.positions) kept.push([start + left, start + right]);
    }
    computed = known;
  }
  return replaceAmounts(original, text, spans, pageNumbers, kept, fences);
}

/** A quoted price is a market fact, not evidence for a financial statement. */
function marketPriceSpans(text: string, spans: Array<[number, number]>, items: readonly SessionTurnItem[]): Array<[number, number]> {
  const kept: Array<[number, number]> = [];
  const pattern = /(?:最新公开报价|最新报价|股价|价格|收盘价|latest quote|stock price|share price)[ \t*]*(?:为|是|[:：])?[ \t*]*([+-]?\d+(?:\.\d+)?)([ \t]*(?:港元|美元|元|CNY|RMB|HKD|USD))/gi;
  for (const item of items) {
    if (item.type !== "tool_call" || item.toolName !== "financial_market_snapshot_tool" || !item.output || item.output.length > 8000 || !["completed", "success", "partial", "degraded"].includes(item.status.toLowerCase())) continue;
    let payload: Record<string, unknown>;
    try { payload = JSON.parse(item.output) as Record<string, unknown>; } catch { continue; }
    if (!payload || payload.ok !== true || !["ok", "partial"].includes(String(payload.status))) continue;
    const quote = payload.quote as Record<string, unknown> | null;
    if (!quote || typeof quote !== "object" || typeof quote.price !== "number" || !Number.isFinite(quote.price) || quote.price <= 0) continue;
    const symbol = typeof payload.ticker === "string" ? payload.ticker : "";
    const quoteTicker = typeof quote.ticker === "string" ? quote.ticker : "";
    const baseTicker = symbol.startsWith("us") ? quoteTicker.replace(/\.(?:OQ|N|AM|PK|PNK|NYSE|NASDAQ)$/i, "") : quoteTicker;
    if (!/^(?:sh|sz|bj)\d{6}$|^hk\d{5}$|^us[A-Za-z][A-Za-z0-9.]{0,15}$/.test(symbol) || quote.symbol !== symbol || baseTicker !== symbol.slice(2)) continue;
    const currency = ({ sh: "CNY", sz: "CNY", bj: "CNY", hk: "HKD", us: "USD" } as Record<string, string>)[symbol.slice(0, 2)];
    if (payload.currency !== currency || quote.currency !== currency || typeof quote.timestamp !== "string" || !/^\d{4}-\d{2}-\d{2}T/.test(quote.timestamp) || !Number.isFinite(Date.parse(quote.timestamp))) continue;
    if (payload.priceUnit !== undefined && payload.priceUnit !== (currency === "CNY" ? "元" : `${currency}/share`)) continue;
    if (quote.priceUnit !== undefined && quote.priceUnit !== `${currency}/share`) continue;
    if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(quote.timestamp)) continue;
    const quoteDate = quote.timestamp.slice(0, 10);
    const url = typeof payload.sourceUrl === "string" ? payload.sourceUrl : "";
    // The adapter's canonical quote identity is also encoded in this URL.
    if (url !== `https://gu.qq.com/${symbol}/gp`) continue;
    for (const [start, end] of spans) {
      const chunk = text.slice(start, end);
      for (const match of chunk.matchAll(pattern)) {
        const at = match.index ?? 0;
        const previousBreak = chunk.lastIndexOf("\n\n", at);
        const paragraph = chunk.slice(previousBreak < 0 ? 0 : previousBreak + 2, chunk.indexOf("\n\n", at) < 0 ? chunk.length : chunk.indexOf("\n\n", at));
        const visibleIdentity = paragraph.replace(/https?:\/\/\S+/g, "");
        const explicitSymbols = [...visibleIdentity.matchAll(/\b(?:(?:sh|sz|bj)\d{6}|hk\d{5}|us[A-Za-z][A-Za-z0-9.]{0,15})\b/g)].map((entry) => entry[0]);
        const escapedTicker = symbol.slice(2).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const hasTicker = new RegExp(`(?<![A-Za-z0-9])(?:${symbol.slice(0, 2)})?${escapedTicker}(?![A-Za-z0-9])`, "i").test(visibleIdentity);
        const quotedDate = [...paragraph.matchAll(/(?:行情(?:日期|时点|时间)|报价(?:日期|时点|时间)|quote (?:date|time|timestamp))[ \t*]*(?:为|是|[:：])?[ \t*]*(\d{4}-\d{2}-\d{2})/gi)];
        if (!paragraph.includes(url) || !quotedDate.some((date) => date[1] === quoteDate) || !hasTicker || explicitSymbols.some((identity) => identity !== symbol)) continue;
        const number = match[1];
        const unit = match[2].trim();
        const sentenceStart = Math.max(...["。", "；", ";", "\n"].map((separator) => chunk.lastIndexOf(separator, at))) + 1;
        const prefix = chunk.slice(sentenceStart, at);
        const suffix = chunk.slice(at + match[0].length).replace(/^(?:\/(?:股|share))?[ \t*]*/i, "");
        if (/营收|收入|利润|现金流|负债|分红|目标|预测|预计|profit|revenue|target|forecast/i.test(prefix) || /^[+×*/÷=＝-]/.test(suffix)) continue;
        const units = currency === "CNY" ? ["元", "CNY", "RMB"] : currency === "HKD" ? ["港元", "HKD"] : ["美元", "USD"];
        const stated = decimalOf({ start: 0, end: 0, sign: number.startsWith("-") ? "-" : "", number: number.replace(/^[+-]/, ""), unit: "" });
        const quoted = decimalOf({ start: 0, end: 0, sign: "", number: String(quote.price), unit: "" });
        if (!units.includes(unit.toUpperCase()) || !stated || !quoted || canonicalDecimal(stated) !== canonicalDecimal(quoted)) continue;
        const offset = match[0].lastIndexOf(number + match[2]);
        const amountStart = start + (match.index ?? 0) + offset;
        const amountEnd = amountStart + number.length + (/[元]$/.test(unit) ? match[2].length : 0);
        kept.push([amountStart, amountEnd]);
      }
    }
  }
  return kept;
}

/** Bound bare source URLs before Chinese punctuation for GFM autolinking. */
export function normalizeFinancialReportLinks(text: string): string {
  const fences = [...fenceSpans(text), ...[...text.matchAll(/`[^`\n]*`/g)].map((match): [number, number] => [match.index ?? 0, (match.index ?? 0) + match[0].length])];
  return text.replace(/https?:\/\/[^\s<>"\])。，；、）]+(?=[。，；、）])/g, (url: string, offset: number) => {
    if (inside(fences, offset) || ["<", "(", "\""].includes(text[offset - 1] ?? "")) return url;
    return `<${url}>`;
  });
}

export function filingExcerptsFromTurnItems(items: readonly SessionTurnItem[]): FilingExcerpt[] {
  const excerpts: FilingExcerpt[] = [];
  for (const item of items) {
    if (item.type !== "tool_call" || !item.output || FAILED.has(item.status.toLowerCase())) continue;
    excerpts.push(...filingExcerptsFromToolOutput(item.toolName, item.output));
  }
  return excerpts;
}

export function filingExcerptsFromToolOutput(toolName: string, output: string): FilingExcerpt[] {
  if (String(toolName || "").trim() !== "financial_evidence_search_tool") return [];
  let payload: unknown;
  try {
    payload = JSON.parse(output);
  } catch {
    return [];
  }
  if (!payload || typeof payload !== "object") return [];
  const record = payload as { citations?: unknown; results?: unknown };
  const pagesByItem = new Map<string, number[]>();
  for (const citation of Array.isArray(record.citations) ? record.citations : []) {
    if (!citation || typeof citation !== "object") continue;
    const row = citation as { knowledgeItemId?: unknown; financialEvidence?: unknown };
    const itemId = typeof row.knowledgeItemId === "string" ? row.knowledgeItemId : "";
    const pages = (Array.isArray(row.financialEvidence) ? row.financialEvidence : [])
      .map((meta) => pageOf(meta && typeof meta === "object" ? (meta as { page?: unknown }).page : undefined))
      .filter((page): page is number => page !== null);
    if (itemId && pages.length) pagesByItem.set(itemId, pages);
  }
  const found: FilingExcerpt[] = [];
  for (const result of Array.isArray(record.results) ? record.results : []) {
    if (!result || typeof result !== "object") continue;
    const row = result as { knowledgeItemId?: unknown; excerpt?: unknown };
    const excerpt = typeof row.excerpt === "string" ? row.excerpt : "";
    const itemId = typeof row.knowledgeItemId === "string" ? row.knowledgeItemId : "";
    if (!excerpt.trim()) continue;
    for (const page of pagesByItem.get(itemId) ?? []) found.push({ page, text: excerpt });
  }
  return found;
}

function pageOf(value: unknown): number | null {
  const page = typeof value === "number" ? value : typeof value === "string" && /^\d+$/.test(value) ? Number(value) : NaN;
  return Number.isInteger(page) && page >= 1 && page <= 100_000 ? page : null;
}

function asciiDigits(text: string): string {
  return text.replace(/[０-９]/g, (char) => String.fromCharCode(char.charCodeAt(0) - 0xfee0));
}

function citedPages(text: string): Set<number> {
  const pages = new Set<number>();
  for (const match of text.matchAll(PAGE)) {
    const raw = match[1] || match[2] || match[3];
    const page = Number(raw);
    if (page >= 1 && page <= 100_000) pages.add(page);
  }
  return pages;
}

function conclusionSpans(text: string): Array<[number, number]> {
  const headings = [...text.matchAll(HEADING)].filter((heading) => heading[1] || BOLD_SECTION.test(heading[2] || "") || /^[ \t]*$/.test(text.slice((heading.index ?? 0) + heading[0].length).split("\n")[0]));
  const spans: Array<[number, number]> = [];
  headings.forEach((heading, index) => {
    if (!CONCLUSION.test(heading[1] || heading[2] || "")) return;
    const start = (heading.index ?? 0) + heading[0].length;
    const end = headings[index + 1]?.index ?? text.length;
    spans.push([start, end]);
  });
  if (spans.length) return spans;
  return headings.length ? [] : [[0, text.length]];
}

function fenceSpans(text: string): Array<[number, number]> {
  return [...text.matchAll(FENCE)].map((match) => [(match.index ?? 0), (match.index ?? 0) + match[0].length]);
}

function numbersInText(text: string): Set<string> {
  const found = new Set<string>();
  for (const amount of amountsIn(asciiDigits(text))) {
    const canonical = canonicalAmount(amount);
    if (canonical) found.add(canonical);
  }
  return found;
}

function amountsIn(text: string): Amount[] {
  const found: Amount[] = [];
  for (const match of text.matchAll(AMOUNT)) {
    const number = match[2] ?? "";
    const digits = number.replace(/\D/g, "");
    const unit = match[3] ?? "";
    if (!digits || digits.length > MAX_DIGITS) continue;
    if (!unit && !/[.，,]/.test(number)) continue;
    found.push({ start: match.index ?? 0, end: (match.index ?? 0) + match[0].length, sign: match[1] ?? "", number, unit });
  }
  return found;
}

function canonicalAmount(amount: Amount): string | null {
  const parsed = decimalOf(amount);
  return parsed ? canonicalDecimal(parsed) : null;
}

function absoluteKey(amount: Amount): string | null {
  const parsed = decimalOf(amount);
  return parsed ? canonicalDecimal({ ...parsed, neg: false }) : null;
}

function decimalOf(amount: Amount): Dec | null {
  const cleaned = amount.number.replace(/[,，]/g, "");
  if (!/^\d+(?:\.\d+)?$/.test(cleaned)) return null;
  const [whole, fraction = ""] = cleaned.split(".");
  if (whole.length + fraction.length > MAX_DIGITS) return null;
  return { neg: amount.sign === "-", int: BigInt((whole + fraction).replace(/^0+/, "") || "0"), scale: fraction.length };
}

function canonicalDecimal(value: Dec): string {
  let int = value.int;
  let scale = value.scale;
  while (scale > 0 && int % 10n === 0n) {
    int /= 10n;
    scale -= 1;
  }
  const digits = int.toString();
  let body = digits;
  if (scale > 0) {
    body = digits.length > scale
      ? `${digits.slice(0, digits.length - scale)}.${digits.slice(digits.length - scale)}`
      : `0.${"0".repeat(scale - digits.length)}${digits}`;
  }
  if (body === "0") return "0";
  return value.neg ? `-${body}` : body;
}

function writtenPlaces(amount: Amount): number {
  const cleaned = amount.number.replace(/[,，]/g, "");
  return cleaned.includes(".") ? cleaned.split(".")[1].length : 0;
}

function isPercent(amount: Amount): boolean {
  return amount.unit.includes("%") || amount.unit.includes("％");
}

function roundTo(value: Dec, places: number): Dec {
  if (places >= value.scale) {
    return { neg: value.neg, int: value.int * 10n ** BigInt(places - value.scale), scale: places };
  }
  const factor = 10n ** BigInt(value.scale - places);
  let kept = value.int / factor;
  if (value.int % factor * 2n >= factor) kept += 1n;
  return { neg: value.neg, int: kept, scale: places };
}

function divideRounded(left: Dec, right: Dec, places: number): Dec | null {
  if (right.int === 0n) return null;
  const scaled = left.int * 10n ** BigInt(right.scale + places + 1) / (right.int * 10n ** BigInt(left.scale));
  let kept = scaled / 10n;
  if (scaled % 10n >= 5n) kept += 1n;
  return { neg: left.neg !== right.neg, int: kept, scale: places };
}

function apply(operator: string, left: Dec, right: Dec, places: number, percent: boolean): Dec | null {
  if (operator === "+") return roundTo(add(left, right, false), places);
  if (operator === "-") return roundTo(add(left, right, true), places);
  if (operator === "*") {
    const product = { neg: left.neg !== right.neg, int: left.int * right.int, scale: left.scale + right.scale };
    return roundTo(percent ? { ...product, int: product.int * 100n } : product, places);
  }
  return divideRounded(percent ? { ...left, int: left.int * 100n } : left, right, places);
}

function add(left: Dec, right: Dec, subtract: boolean): Dec {
  const scale = Math.max(left.scale, right.scale);
  const leftInt = (left.neg ? -left.int : left.int) * 10n ** BigInt(scale - left.scale);
  const rightInt = (right.neg ? -right.int : right.int) * 10n ** BigInt(scale - right.scale);
  const signed = subtract ? leftInt - rightInt : leftInt + rightInt;
  return { neg: signed < 0n, int: signed < 0n ? -signed : signed, scale };
}

function operatorOf(text: string): string | null {
  const match = OPERATOR.exec(text);
  if (!match) return null;
  const symbol = match[1];
  if (symbol === "+" || symbol === "＋") return "+";
  if (symbol === "-" || symbol === "－" || symbol === "−") return "-";
  if (symbol === "*" || symbol === "×") return "*";
  return "/";
}

function rightOperand(chunk: string, left: Amount, right: Amount): { operator: string; value: Dec } | null {
  const direct = operatorOf(chunk.slice(left.end, right.start));
  const value = decimalOf(right);
  if (!value) return null;
  if (direct) return { operator: direct, value };
  if (right.sign === "-" && chunk.slice(left.end, right.start).trim() === "") return { operator: "-", value: { ...value, neg: false } };
  return null;
}

function confirmedResults(chunk: string, known: Set<string>, base: number, fences: Array<[number, number]>, full: string): { values: Set<string>; positions: Array<[number, number]> } {
  const amounts = amountsIn(chunk).filter((amount) => !insideUrl(full, base + amount.start) && !inside(fences, base + amount.start));
  const values = new Set<string>();
  const positions: Array<[number, number]> = [];
  for (let index = 0; index < amounts.length - 2; index += 1) {
    const [left, right, result] = [amounts[index], amounts[index + 1], amounts[index + 2]];
    const parsed = rightOperand(chunk, left, right);
    if (!parsed || !EQUALS.test(chunk.slice(right.end, result.start))) continue;
    const leftKey = canonicalAmount(left);
    const subtracted = parsed.operator === "-" && right.sign === "-" && chunk.slice(left.end, right.start).trim() === "";
    const rightKey = subtracted ? absoluteKey(right) : canonicalAmount(right);
    const leftValue = decimalOf(left);
    const resultValue = decimalOf(result);
    if (!leftKey || !rightKey || !leftValue || !resultValue || !known.has(leftKey) || !known.has(rightKey)) continue;
    const computed = apply(parsed.operator, leftValue, parsed.value, writtenPlaces(result), isPercent(result));
    if (computed && canonicalDecimal(computed) === canonicalDecimal(resultValue)) {
      values.add(canonicalDecimal(resultValue));
      for (const amount of [left, right, result]) positions.push([amount.start, amount.end]);
    }
  }
  return { values, positions };
}

function keepsAmount(amount: Amount, known: Set<string>, chunk: string): boolean {
  const canonical = canonicalAmount(amount);
  if (!canonical || known.has(canonical)) return true;
  if (amount.sign !== "-" || !known.has(absoluteKey(amount) ?? "")) return false;
  const previous = amount.start ? chunk[amount.start - 1] : "";
  return previous === "" || /\s/.test(previous);
}

function insideUrl(text: string, index: number): boolean {
  const window = text.slice(Math.max(0, index - 300), index);
  const start = Math.max(window.lastIndexOf("http://"), window.lastIndexOf("https://"));
  return start >= 0 && !/\s/.test(window.slice(start));
}

function inside(spans: Array<[number, number]>, index: number): boolean {
  return spans.some(([start, end]) => index >= start && index < end);
}

function replaceAmounts(original: string, normalized: string, spans: Array<[number, number]>, known: Set<string>, kept: Array<[number, number]>, fences: Array<[number, number]>): string {
  let cursor = 0;
  let next = "";
  for (const [start, end] of spans) {
    const local = kept.filter(([left, right]) => left >= start && right <= end).map(([left, right]): [number, number] => [left - start, right - start]);
    next += original.slice(cursor, start) + replaceSpan(original.slice(start, end), normalized.slice(start, end), start, known, local, fences, normalized);
    cursor = end;
  }
  return next + original.slice(cursor);
}

function replaceSpan(originalChunk: string, chunk: string, base: number, known: Set<string>, kept: Array<[number, number]>, fences: Array<[number, number]>, full: string): string {
  const spans: Array<[number, number]> = [];
  for (const amount of amountsIn(chunk)) {
    if (keepsAmount(amount, known, chunk) || kept.some(([start, end]) => start === amount.start && end === amount.end)) continue;
    const absolute = base + amount.start;
    if (insideUrl(full, absolute) || inside(fences, absolute)) continue;
    spans.push([amount.start, amount.end]);
  }
  for (const match of chunk.matchAll(SCIENCE)) {
    const start = match.index ?? 0;
    const absolute = base + start;
    if (insideUrl(full, absolute) || inside(fences, absolute)) continue;
    spans.push([start, start + match[0].length]);
  }
  spans.sort((left, right) => left[0] - right[0] || right[1] - right[0] - (left[1] - left[0]));
  const chosen: Array<[number, number]> = [];
  let occupied = -1;
  for (const [start, end] of spans) {
    if (start < occupied) continue;
    chosen.push([start, end]);
    occupied = end;
  }
  let cursor = 0;
  let next = "";
  for (const [start, end] of chosen) {
    next += originalChunk.slice(cursor, start) + MISSING_FIGURE;
    cursor = end;
  }
  return next + originalChunk.slice(cursor);
}
