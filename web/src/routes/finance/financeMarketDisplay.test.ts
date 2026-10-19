import { describe, expect, it } from "vitest";
import type { StockQuote } from "../../api/financialMarket";
import { formatQuoteTimestamp, quoteAmount, quoteCurrency, quoteSnapshotDayOffset, quoteVolume } from "./financeMarketDisplay";

const quote = { symbol: "hk00700", ticker: "00700", name: "腾讯控股", market: "港股", currency: "HKD", turnover: 3500, marketCap: null, volume: 125000, volumeLots: null, turnoverYuan: 999999, totalMarketCapYuan: 999999 } as StockQuote;
describe("market units", () => {
  it("shows amounts as scaled numbers without a trailing currency suffix", () => {
    expect(quoteAmount(quote, "turnover")).toBe("3,500");
    expect(quoteAmount(quote, "marketCap")).toBe("—");
    expect(quoteAmount({ ...quote, turnover: null }, "turnover")).toBe("—");
    expect(quoteAmount({ ...quote, turnover: 3_360_000_000 }, "turnover")).toBe("33.60亿");
    expect(quoteCurrency({ ...quote, symbol: "usAAPL", currency: null })).toBe("美元");
  });
  it("scales amounts up to the trillion band and keeps legacy yuan values", () => {
    expect(quoteAmount({ ...quote, symbol: "sh600519", currency: "CNY", turnover: null, turnoverYuan: 1_671_800_000_000 }, "turnover")).toBe("1.67万亿");
    expect(quoteAmount({ ...quote, symbol: "sh600519", currency: "CNY", turnover: null, turnoverYuan: 5000 }, "turnover")).toBe("5,000");
    expect(quoteAmount({ ...quote, symbol: "sh600519", currency: "CNY", turnover: null, turnoverYuan: 480_000 }, "turnover")).toBe("48.00万");
  });
  it("renders A-share volume in lots and HK/US volume in shares", () => {
    expect(quoteVolume(quote)).toBe("12.50万股");
    expect(quoteVolume({ ...quote, symbol: "sh600519", volume: 2_507_900 })).toBe("2.51万手");
    expect(quoteVolume({ ...quote, symbol: "sh600519", volume: 900 })).toBe("9 手");
    expect(quoteVolume({ ...quote, symbol: "sh600519", volume: null, volumeLots: 100 })).toBe("100 手");
    expect(quoteVolume({ ...quote, symbol: "sh600519", volume: null, volumeLots: 150_000_000 })).toBe("1.50亿手");
    expect(quoteVolume(null)).toBe("—");
  });
  it("keeps K/M share scaling for English volume labels", () => {
    expect(quoteVolume({ ...quote, volume: 2_507_900 }, false)).toBe("2.51M shares");
    expect(quoteVolume({ ...quote, volume: 9_500 }, false)).toBe("9.50K shares");
    expect(quoteVolume({ ...quote, volume: null, volumeLots: 100 }, false)).toBe("100 lots");
  });
});

describe("quote timestamps", () => {
  it("formats today's snapshots as a bare time and older ones with the day", () => {
    const today = new Date();
    today.setHours(9, 30, 0, 0);
    expect(formatQuoteTimestamp(today.toISOString())).toMatch(/^\d{2}:\d{2}$/);
    const earlier = new Date(2026, 0, 5, 9, 30);
    expect(formatQuoteTimestamp(earlier.toISOString())).toBe("1月5日 09:30");
    expect(formatQuoteTimestamp(earlier.toISOString(), false)).toBe("Jan 5 09:30");
    expect(formatQuoteTimestamp("not-a-time")).toBe("时间未知");
    expect(formatQuoteTimestamp("not-a-time", false)).toBe("Time unavailable");
  });
  it("flags stale snapshot days for inline badges", () => {
    expect(quoteSnapshotDayOffset(new Date().toISOString())).toBeNull();
    expect(quoteSnapshotDayOffset(new Date(2026, 0, 5, 9, 30).toISOString())).toBe("1月5日");
    expect(quoteSnapshotDayOffset("not-a-time")).toBeNull();
  });
});
