export type StockMarketCode = "CN" | "HK" | "US";
export type StockCurrency = "CNY" | "HKD" | "USD";
export type StockPriceUnit = "CNY/share" | "HKD/share" | "USD/share";
export type StockIdentity = {
  symbol: string; ticker: string; name: string; market: string;
  marketCode?: StockMarketCode | null; currency?: StockCurrency | null;
  marketTimeZone?: "Asia/Shanghai" | "Asia/Hong_Kong" | "America/New_York" | null;
};
export type StockPeriod = "day" | "week" | "month";
export type StockQuote = StockIdentity & {
  price: number; previousClose: number; open: number; high: number; low: number;
  change: number; changePercent: number; volumeLots: number | null; turnoverYuan: number | null;
  priceUnit?: StockPriceUnit | null; volume?: number | null; volumeUnit?: "shares" | null;
  turnover?: number | null; marketCap?: number | null;
  peRatio: number | null; pbRatio: number | null; totalMarketCapYuan: number | null;
  timestamp: string;
};
export type StockCandle = {
  date: string; open: number; close: number; high: number; low: number;
  volumeLots: number | null; volume?: number | null; volumeUnit?: "shares" | null;
};
export type StockSnapshot = {
  stock: StockQuote; candles: StockCandle[]; period: StockPeriod; adjustment: "qfq" | "raw";
  source: string; sourceUrl: string; fetchedAt: string; candleError: string; notice: string;
};
