import { describe, expect, it } from "vitest";
import { financeChartIndicators } from "./financeChartIndicators";

const candles = (closes: number[]) => closes.map((close, index) => ({ date: `bar-${index}`, close, open: close, high: close, low: close, volumeLots: 1 }));
describe("financial chart calculations", () => {
  it("uses a 20-bar population deviation for BOLL and omits warm-up", () => {
    const result = financeChartIndicators(candles(Array.from({ length: 20 }, (_, i) => i + 1)));
    expect(result.upper.slice(0, 19)).toEqual(Array(19).fill(null));
    expect(result.long[19]).toBe(10.5);
    expect(result.upper[19]).toBeCloseTo(22.0325625947, 8);
    expect(result.lower[19]).toBeCloseTo(-1.0325625947, 8);
  });
  it("matches the standard Wilder RSI example and handles flat/up/down series", () => {
    const example = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28];
    expect(financeChartIndicators(candles(example)).rsi[14]).toBeCloseTo(70.464135, 5);
    expect(financeChartIndicators(candles(Array(30).fill(100))).rsi[29]).toBe(50);
    expect(financeChartIndicators(candles(Array.from({ length: 30 }, (_, i) => 100 + i))).rsi[29]).toBe(100);
    expect(financeChartIndicators(candles(Array.from({ length: 30 }, (_, i) => 100 - i))).rsi[29]).toBe(0);
  });
  it("keeps MACD warm-up missing and never changes an earlier bar using later prices", () => {
    const prefix = candles(Array.from({ length: 40 }, (_, i) => 20 + i));
    const result = financeChartIndicators(prefix);
    expect(result.dif.slice(0, 25)).toEqual(Array(25).fill(null));
    expect(result.histogram.slice(0, 33)).toEqual(Array(33).fill(null));
    expect(result.dif[39]).toBeGreaterThan(0);
    const extended = financeChartIndicators([...prefix, ...candles([500, 3, 900])]);
    for (const key of ["short", "long", "upper", "lower", "rsi", "dif", "dea", "histogram"] as const) expect(extended[key].slice(0, 40)).toEqual(result[key]);
    expect(financeChartIndicators(candles(Array(40).fill(10))).histogram[39]).toBe(0);
  });
});
