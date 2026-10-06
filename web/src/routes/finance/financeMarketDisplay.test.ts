import { describe, expect, it } from "vitest";
import type { StockQuote } from "../../api/financialMarket";
import { quoteAmount, quoteCurrency, quoteVolume } from "./financeMarketDisplay";

const quote = { symbol: "hk00700", ticker: "00700", name: "腾讯控股", market: "港股", currency: "HKD", turnover: 3500, marketCap: null, volume: 125000, volumeLots: null, turnoverYuan: 999999, totalMarketCapYuan: 999999 } as StockQuote;
describe("market units", () => {
  it("shows HK and US amounts in their actual currency without relabeling legacy yuan values", () => {
    expect(quoteAmount(quote, "turnover")).toBe("3,500.00 港元");
    expect(quoteAmount(quote, "marketCap")).toBe("—");
    expect(quoteAmount({ ...quote, turnover: null }, "turnover")).toBe("—");
    expect(quoteCurrency({ ...quote, symbol: "usAAPL", currency: null })).toBe("美元");
  });
  it("retains legacy A-share amount/lot units and prefers explicit share counts", () => {
    expect(quoteVolume(quote)).toBe("125,000 股");
    expect(quoteVolume({ ...quote, symbol: "sh600519", volume: null, volumeLots: 100 })).toBe("100 手");
    expect(quoteAmount({ ...quote, symbol: "sh600519", currency: "CNY", turnover: null, turnoverYuan: 5000 }, "turnover")).toBe("5,000.00 元");
  });
});
