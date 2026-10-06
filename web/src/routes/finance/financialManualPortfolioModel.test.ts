import { expect, it } from "vitest";
import type { StockQuote } from "../../api/financialMarket";
import type { FinancialManualPosition } from "../../api/financialPreferences";
import { ManualPositionConflictError, manualPositionQuote, manualPortfolioPrompt, manualPortfolioTotals, saveManualPositionChange } from "./financialManualPortfolioModel";

const positions: FinancialManualPosition[] = [
  { id: "cn", stock: { symbol: "sh600519", ticker: "600519", name: "茅台", market: "上交所" }, quantity: 10, costPrice: 1000, currency: "CNY", note: "长期" },
  { id: "us", stock: { symbol: "usAAPL", ticker: "AAPL", name: "Apple", market: "NASDAQ" }, quantity: 5, costPrice: 180, currency: "USD", note: "" },
  { id: "us-missing", stock: { symbol: "usMSFT", ticker: "MSFT", name: "Microsoft", market: "NASDAQ" }, quantity: 2, costPrice: 400, currency: "USD", note: "" },
];

it("keeps currency totals separate and excludes missing quotes from marked P/L", () => {
  const quotes = new Map<string, StockQuote>([["sh600519", { symbol: "sh600519", price: 1200, currency: "CNY" } as StockQuote], ["usAAPL", { symbol: "usAAPL", price: 200, currency: "USD" } as StockQuote]]);
  expect(manualPortfolioTotals(positions, quotes)).toEqual([
    { currency: "CNY", count: 1, marked: 1, cost: 10000, markedCost: 10000, marketValue: 12000 },
    { currency: "USD", count: 2, marked: 1, cost: 1700, markedCost: 900, marketValue: 1000 },
  ]);
  const prompt = manualPortfolioPrompt(positions, quotes, "2026-10-06T12:00:00+08:00");
  expect(prompt).toContain("请对以下主题开展投资研究");
  expect(prompt).toContain("报价不可用");
  expect(prompt).toContain("不合并不同币种金额");
});

it("uses no mismatched-currency or mismatched-identity quote in either valuation or research prompt", () => {
  const wrongCurrency = { symbol: "usAAPL", ticker: "AAPL", name: "Apple", market: "NASDAQ", price: 240, currency: "HKD", timestamp: "2026-10-06T12:00:00Z" } as StockQuote;
  const wrongIdentity = { symbol: "usGOOG", ticker: "GOOG", name: "Alphabet", market: "NASDAQ", price: 500, currency: "USD", timestamp: "2026-10-06T12:00:00Z" } as StockQuote;
  const quotes = new Map<string, StockQuote>([["usAAPL", wrongCurrency], ["usMSFT", wrongIdentity]]);
  const rows = [positions[1], positions[2]];

  expect(manualPositionQuote(rows[0], quotes)).toBeUndefined();
  expect(manualPositionQuote(rows[1], quotes)).toBeUndefined();
  expect(manualPortfolioTotals(rows, quotes)).toEqual([
    { currency: "USD", count: 2, marked: 0, cost: 1700, markedCost: 0, marketValue: 0 },
  ]);
  const prompt = manualPortfolioPrompt(rows, quotes, "");
  expect(prompt).toContain("Apple（AAPL，NASDAQ，usAAPL）：5股，成本180 USD；报价不可用");
  expect(prompt).toContain("Microsoft（MSFT，NASDAQ，usMSFT）：2股，成本400 USD；报价不可用");
  expect(prompt).not.toContain("240 HKD");
  expect(prompt).not.toContain("500 USD");
});

it("rebases an edit over unrelated row changes and refuses overwrite or resurrection of the edited row", () => {
  const baseline = positions[1];
  const submitted = { ...baseline, quantity: 8, costPrice: 190 };
  const latest = [positions[0], { ...baseline, note: "updated in another window" }, positions[2]];
  const unrelatedLatest = [positions[0], baseline, { ...positions[2], note: "also updated" }];

  expect(saveManualPositionChange(unrelatedLatest, submitted, baseline)).toEqual([
    positions[0], submitted, { ...positions[2], note: "also updated" },
  ]);
  expect(() => saveManualPositionChange(latest, submitted, baseline)).toThrowError(ManualPositionConflictError);
  expect(() => saveManualPositionChange(latest, submitted, baseline)).toThrowError(expect.objectContaining({ reason: "changed" }));
  expect(() => saveManualPositionChange(latest.filter((row) => row.id !== baseline.id), submitted, baseline)).toThrowError(expect.objectContaining({ reason: "deleted" }));
});

it("does not let a new holding with a colliding ID replace an existing position", () => {
  const existing = positions[1];
  expect(() => saveManualPositionChange(positions, { ...existing, quantity: 99 }, null))
    .toThrowError(expect.objectContaining({ reason: "id_collision" }));
});
