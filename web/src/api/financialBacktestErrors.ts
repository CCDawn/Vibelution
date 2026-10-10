import { isFetchJsonHttpError } from "./client";

export function financialBacktestErrorMessage(cause: unknown, zh: boolean) {
  if (isFetchJsonHttpError(cause) && cause.status === 422 && cause.details && typeof cause.details === "object") {
    const detail = (cause.details as { detail?: unknown }).detail;
    if (Array.isArray(detail)) {
      const names: Record<string, string> = zh
        ? { dailyPriceLimits: "逐日限价文件", source: "来源", url: "网址", sha256: "摘要", fetchedAt: "采集时间", records: "每日记录", date: "日期", upper: "涨停价", lower: "跌停价", symbol: "股票代码", schemaVersion: "文件版本" }
        : { dailyPriceLimits: "Daily limit file", source: "source", url: "URL", sha256: "hash", fetchedAt: "fetch time", records: "daily records", date: "date", upper: "upper limit", lower: "lower limit", symbol: "stock code", schemaVersion: "file version" };
      const first = detail.find(item => item && typeof item === "object" && Array.isArray(item.loc));
      const field = first?.loc.filter((part: unknown) => typeof part === "string" && part !== "body").map((part: string) => names[part] ?? (zh ? "参数" : "field")).join(" · ");
      return zh ? `${field || "回测参数"}缺失或格式不正确，请修改后重试。` : `${field || "Backtest input"} is missing or invalid. Correct it and retry.`;
    }
  }
  return cause instanceof Error ? cause.message : (zh ? "操作失败，请重试" : "Operation failed. Please retry.");
}
