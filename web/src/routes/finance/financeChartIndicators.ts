import type { StockCandle } from "../../api/financialMarket";
import { movingAverage } from "./stockResearchModel";

/** Calculations use the complete loaded series, before viewport slicing. */
export function financeChartIndicators(candles: readonly StockCandle[]) {
  const short = movingAverage(candles, 5), long = movingAverage(candles, 20);
  const upper: (number | null)[] = [], lower: (number | null)[] = [];
  const rsi: (number | null)[] = [], dif: (number | null)[] = [], dea: (number | null)[] = [], histogram: (number | null)[] = [];
  let fast = candles[0]?.close ?? 0, slow = fast, signal = 0, gain = 0, loss = 0;
  candles.forEach((candle, index) => {
    const mean = long[index];
    // BOLL(20,2): population standard deviation around the 20-bar SMA.
    const deviation = mean === null ? null : Math.sqrt(candles.slice(index - 19, index + 1).reduce((sum, row) => sum + (row.close - mean) ** 2, 0) / 20);
    upper.push(mean === null || deviation === null ? null : mean + 2 * deviation);
    lower.push(mean === null || deviation === null ? null : mean - 2 * deviation);
    fast += 2 / 13 * (candle.close - fast); slow += 2 / 27 * (candle.close - slow);
    const difference = fast - slow;
    signal += 2 / 10 * (difference - signal);
    // MACD(12,26,9): close-seeded EMA; incomplete warm-up remains missing.
    dif.push(index >= 25 ? difference : null); dea.push(index >= 33 ? signal : null);
    histogram.push(index >= 33 ? 2 * (difference - signal) : null);
    if (index > 0) {
      const change = candle.close - candles[index - 1].close;
      if (index <= 14) { gain += Math.max(0, change) / 14; loss += Math.max(0, -change) / 14; }
      else { gain = (gain * 13 + Math.max(0, change)) / 14; loss = (loss * 13 + Math.max(0, -change)) / 14; }
    }
    // Wilder RSI(14); a flat series is neutral (50).
    rsi.push(index < 14 ? null : gain + loss === 0 ? 50 : 100 * gain / (gain + loss));
  });
  return { short, long, upper, lower, rsi, dif, dea, histogram };
}
