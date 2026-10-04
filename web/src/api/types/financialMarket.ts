export type StockIdentity = { symbol: string; ticker: string; name: string; market: string };
export type StockPeriod = "day" | "week" | "month";
export type StockQuote = StockIdentity & {
  price: number; previousClose: number; open: number; high: number; low: number;
  change: number; changePercent: number; volumeLots: number; turnoverYuan: number;
  peRatio: number | null; pbRatio: number | null; totalMarketCapYuan: number | null;
  timestamp: string;
};
export type StockCandle = { date: string; open: number; close: number; high: number; low: number; volumeLots: number };
export type StockSnapshot = {
  stock: StockQuote; candles: StockCandle[]; period: StockPeriod; adjustment: "qfq";
  source: string; sourceUrl: string; fetchedAt: string; candleError: string; notice: string;
};
