import { describe, expect, it } from "vitest";
import { beijingScheduledTime, financialBatchStatusLabel, parseFinancialBatchSymbols } from "./financialJobModel";

describe("financial job input and outcomes", () => {
  it("deduplicates canonical A/HK/US symbols and infers only unambiguous A-share codes", () => {
    expect(parseFinancialBatchSymbols("600519，SH600519;000001 sz000001\n300750")).toEqual({ symbols: ["sh600519", "sz000001", "sz300750"], invalid: [] });
    expect(parseFinancialBatchSymbols("430047, hk700, HK00700, usaapl, usBRK.B, usABC-1, usAAPL.OQ")).toEqual({
      symbols: ["bj430047", "hk00700", "usAAPL", "usBRK.B", "usABC-1"],
      invalid: [],
    });
    expect(parseFinancialBatchSymbols("510300 sz600519 sh000001 830799 159915 AAPL 00700 us0ABC")).toEqual({
      symbols: ["bj830799"],
      invalid: ["510300", "sz600519", "sh000001", "159915", "AAPL", "00700", "us0ABC"],
    });
  });
  it("interprets the labelled time in Beijing regardless of the browser zone", () => {
    const time = beijingScheduledTime("2026-10-06T18:05");
    expect(time).toBe("2026-10-06T18:05:00+08:00");
    expect(new Date(time!).toISOString()).toBe("2026-10-06T10:05:00.000Z");
  });
  it("rejects rolled-over dates, invalid times and timezone-bearing local input", () => {
    for (const input of ["2026-02-29T18:00", "2026-04-31T18:00", "2026-10-06T24:00", "2026-10-06T18:60", "2026-10-06T18:00Z", "2026-00-06T18:00"]) expect(beijingScheduledTime(input)).toBeNull();
    expect(beijingScheduledTime("2028-02-29T18:00")).not.toBeNull();
  });
  it("does not label stopped, blocked or partial research as completed", () => {
    expect(financialBatchStatusLabel("stopped", true)).toBe("已停止");
    expect(financialBatchStatusLabel("blocked", true)).toBe("需处理");
    expect(financialBatchStatusLabel("partial", true)).toBe("部分完成");
  });
});
