import type { SessionTurnUsageStats } from "../../api/types/chat";

/**
 * Codex parity: settled turns carry a quiet token-usage label near the turn
 * meta. Only measured wire facts render — no invented numbers, no label while
 * the turn is still streaming.
 */

export type ConversationTurnUsageLabel = {
  /** Quiet inline text, e.g. `1.2k tokens`. */
  label: string;
  /** Hover breakdown lines (max 4), localized. */
  titleLines: string[];
};

const compactZh = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 });
const compactEn = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

function positiveFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

export function formatTurnTokenCount(value: number, lang: "zh" | "en"): string {
  return (lang === "zh" ? compactZh : compactEn).format(value);
}

export function resolveConversationTurnUsageLabel(
  usageStats: SessionTurnUsageStats | null | undefined,
  lang: "zh" | "en",
): ConversationTurnUsageLabel | null {
  if (!usageStats || !positiveFinite(usageStats.totalTokens)) {
    return null;
  }
  const total = formatTurnTokenCount(usageStats.totalTokens, lang);
  const zh = lang === "zh";
  const titleLines = [
    positiveFinite(usageStats.inputTokens)
      ? (zh ? `输入 ${formatTurnTokenCount(usageStats.inputTokens, lang)}` : `Input ${formatTurnTokenCount(usageStats.inputTokens, lang)}`)
      : "",
    positiveFinite(usageStats.completionTokens)
      ? (zh ? `输出 ${formatTurnTokenCount(usageStats.completionTokens, lang)}` : `Output ${formatTurnTokenCount(usageStats.completionTokens, lang)}`)
      : "",
    positiveFinite(usageStats.cachedInputTokens)
      ? (zh ? `缓存 ${formatTurnTokenCount(usageStats.cachedInputTokens, lang)}` : `Cached ${formatTurnTokenCount(usageStats.cachedInputTokens, lang)}`)
      : "",
    positiveFinite(usageStats.tokensPerSecond)
      ? (zh
        ? `速度 ${Math.round(usageStats.tokensPerSecond)} tok/s`
        : `Speed ${Math.round(usageStats.tokensPerSecond)} tok/s`)
      : "",
  ].filter(Boolean);
  return {
    label: zh ? `${total} tokens` : `${total} tokens`,
    titleLines,
  };
}
