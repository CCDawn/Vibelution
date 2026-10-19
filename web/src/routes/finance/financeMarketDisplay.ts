import type { StockCandle, StockIdentity, StockQuote } from "../../api/financialMarket";
import { quoteNumber } from "./stockResearchModel";

export function stockMarketCode(stock: Pick<StockIdentity, "symbol">): "CN" | "HK" | "US" { return stock.symbol.startsWith("hk") ? "HK" : stock.symbol.startsWith("us") ? "US" : "CN"; }
export function stockCurrency(stock: Pick<StockIdentity, "symbol">): "CNY" | "HKD" | "USD" { return stockMarketCode(stock) === "HK" ? "HKD" : stockMarketCode(stock) === "US" ? "USD" : "CNY"; }
export function currencyName(currency: string | null | undefined, zh = true) { return currency === "HKD" ? zh ? "港元" : "HKD" : currency === "USD" ? zh ? "美元" : "USD" : currency === "CNY" ? zh ? "元" : "CNY" : "—"; }
export function quoteCurrency(quote: StockQuote, zh = true) { return currencyName(quote.currency ?? stockCurrency(quote), zh); }

function scaledCount(value: number, unit: string): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 100_000_000) return `${quoteNumber(value / 100_000_000)}亿${unit}`;
  if (magnitude >= 10_000) return `${quoteNumber(value / 10_000)}万${unit}`;
  return `${quoteNumber(value, 0)} ${unit}`;
}

function scaledCountEn(value: number, unit: "shares" | "lots"): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 1_000_000) return `${quoteNumber(value / 1_000_000)}M ${unit}`;
  if (magnitude >= 1_000) return `${quoteNumber(value / 1_000)}K ${unit}`;
  return `${quoteNumber(value, 0)} ${unit}`;
}

export function quoteAmount(quote: StockQuote | null | undefined, field: "turnover" | "marketCap", _zh = true) {
  if (!quote) return "—";
  const legacy = stockMarketCode(quote) === "CN" ? (field === "turnover" ? quote.turnoverYuan : quote.totalMarketCapYuan) : null;
  const value = quote[field] ?? legacy;
  if (value == null) return "—";
  const magnitude = Math.abs(value);
  if (magnitude >= 1e12) return `${quoteNumber(value / 1e12)}万亿`;
  if (magnitude >= 1e8) return `${quoteNumber(value / 1e8)}亿`;
  if (magnitude >= 1e4) return `${quoteNumber(value / 1e4)}万`;
  return Math.round(value).toLocaleString("zh-CN");
}

export function quoteVolume(quote: StockQuote | null | undefined, zh = true) {
  if (!quote) return "—";
  const lots = stockMarketCode(quote) === "CN";
  if (quote.volume != null) return zh ? scaledCount(lots ? quote.volume / 100 : quote.volume, lots ? "手" : "股") : scaledCountEn(quote.volume, "shares");
  return quote.volumeLots == null ? "—" : zh ? scaledCount(quote.volumeLots, "手") : scaledCountEn(quote.volumeLots, "lots");
}

export function candleVolume(candle: StockCandle) { return candle.volume ?? candle.volumeLots ?? 0; }

export function formatQuoteTimestamp(value: string, zh = true): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return zh ? "时间未知" : "Time unavailable";
  const time = date.toLocaleTimeString(zh ? "zh-CN" : "en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
  const now = new Date();
  const sameDay = date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
  return sameDay ? time : zh ? `${date.getMonth() + 1}月${date.getDate()}日 ${time}` : `${date.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${time}`;
}

export function quoteSnapshotDayOffset(value: string): string | null {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const now = new Date();
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
    ? null
    : `${date.getMonth() + 1}月${date.getDate()}日`;
}
