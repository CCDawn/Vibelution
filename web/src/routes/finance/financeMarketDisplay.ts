import type { StockCandle, StockIdentity, StockQuote } from "../../api/financialMarket";
import { quoteNumber, yuanAmount } from "./stockResearchModel";

export function stockMarketCode(stock: Pick<StockIdentity, "symbol">): "CN" | "HK" | "US" { return stock.symbol.startsWith("hk") ? "HK" : stock.symbol.startsWith("us") ? "US" : "CN"; }
export function stockCurrency(stock: Pick<StockIdentity, "symbol">): "CNY" | "HKD" | "USD" { return stockMarketCode(stock) === "HK" ? "HKD" : stockMarketCode(stock) === "US" ? "USD" : "CNY"; }
export function currencyName(currency: string | null | undefined, zh = true) { return currency === "HKD" ? zh ? "港元" : "HKD" : currency === "USD" ? zh ? "美元" : "USD" : currency === "CNY" ? zh ? "元" : "CNY" : "—"; }
export function quoteCurrency(quote: StockQuote, zh = true) { return currencyName(quote.currency ?? stockCurrency(quote), zh); }
export function quoteAmount(quote: StockQuote | null | undefined, field: "turnover" | "marketCap", zh = true) {
  if (!quote) return "—";
  const legacy = stockMarketCode(quote) === "CN" ? (field === "turnover" ? quote.turnoverYuan : quote.totalMarketCapYuan) : null;
  const value = quote[field] ?? legacy;
  return value == null ? "—" : `${Math.abs(value) < 10_000 ? quoteNumber(value) : yuanAmount(value)} ${quoteCurrency(quote, zh)}`;
}
export function quoteVolume(quote: StockQuote | null | undefined, zh = true) {
  if (!quote) return "—";
  if (quote.volume != null) return `${quoteNumber(quote.volume, 0)} ${zh ? "股" : "shares"}`;
  return quote.volumeLots == null ? "—" : `${quoteNumber(quote.volumeLots, 0)} ${zh ? "手" : "lots"}`;
}
export function candleVolume(candle: StockCandle) { return candle.volume ?? candle.volumeLots ?? 0; }
