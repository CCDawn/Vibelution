import type { AiSearchRun, AiSearchRunSummary } from "../../api/types";

export const AI_SEARCH_RUN_PREVIEW_LIMIT = 6;

export type AiSearchRunDisplay = AiSearchRun | AiSearchRunSummary;
export type AiSearchRunCardDisplay = AiSearchRun["cards"][number];

export function aiSearchSourceRoleLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    primary: "一手证据",
    secondary: "二手索引",
    signal: "线索信号",
  };
  const en: Record<string, string> = {
    primary: "Primary evidence",
    secondary: "Secondary index",
    signal: "Signal only",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? normalized;
}

export function aiSearchSourceTierLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    tier1: "Tier 1 官方",
    tier2: "Tier 2 可信索引",
    tier3: "Tier 3 信号",
  };
  const en: Record<string, string> = {
    tier1: "Tier 1 official",
    tier2: "Tier 2 trusted",
    tier3: "Tier 3 signal",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? normalized;
}

export function aiSearchRunCounts(run: AiSearchRunDisplay) {
  if ("summary" in run) {
    return run.summary;
  }
  return {
    cardCount: run.cardCount,
    succeededCount: run.succeededCount,
    failedCount: run.failedCount,
    degradedCount: run.degradedCount ?? 0,
    referenceCount: run.referenceCount,
  };
}

export function aiSearchRunQueryCount(run: AiSearchRunDisplay) {
  return "queryPlan" in run ? run.queryPlan.queryCount : run.queryCount;
}

export function aiSearchRunPath(run: AiSearchRunDisplay) {
  return "storage" in run ? run.storage.runPath : run.runPath;
}

export function aiSearchRunStatusLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim().toLowerCase();
  const zh: Record<string, string> = {
    completed: "已完成",
    partial: "部分完成",
    failed: "失败",
    running: "运行中",
  };
  const en: Record<string, string> = {
    completed: "Completed",
    partial: "Partial",
    failed: "Failed",
    running: "Running",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? normalized;
}

export function aiSearchRunCardExtra(card: AiSearchRunCardDisplay, key: string) {
  return (card as unknown as Record<string, unknown>)[key];
}

export function aiSearchRunCardExtraString(card: AiSearchRunCardDisplay, key: string) {
  const value = aiSearchRunCardExtra(card, key);
  return typeof value === "string" ? value.trim() : "";
}

export function aiSearchRunCardSearchMode(card: AiSearchRunCardDisplay) {
  return aiSearchRunCardExtraString(card, "searchMode").toLowerCase();
}

export function aiSearchRunCardFallbackReason(card: AiSearchRunCardDisplay) {
  return aiSearchRunCardExtraString(card, "fallbackReason");
}

export function aiSearchRunCardUsesFallback(card: AiSearchRunCardDisplay) {
  const degraded = aiSearchRunCardExtra(card, "degraded") === true;
  const searchMode = aiSearchRunCardSearchMode(card);
  return (
    degraded
    || Boolean(aiSearchRunCardFallbackReason(card))
    || searchMode.includes("fallback")
    || searchMode.includes("source_page")
  );
}

export function aiSearchRunCardModeLabel(card: AiSearchRunCardDisplay, lang: "zh" | "en") {
  if (aiSearchRunCardUsesFallback(card)) {
    return lang === "zh" ? "源页扫描" : "Source page scan";
  }
  const searchMode = aiSearchRunCardSearchMode(card);
  if (searchMode.includes("web") || searchMode.includes("search")) {
    return lang === "zh" ? "搜索 API" : "Search API";
  }
  return searchMode || (lang === "zh" ? "搜索" : "Search");
}

export function aiSearchRunNeedsReviewCount(run: AiSearchRunDisplay) {
  return run.cards.filter((card) => card.status === "failed" || aiSearchRunCardUsesFallback(card)).length;
}

export function aiSearchRunPrimaryResultText(
  run: AiSearchRunDisplay,
  counts: ReturnType<typeof aiSearchRunCounts>,
  lang: "zh" | "en",
) {
  const needsReview = aiSearchRunNeedsReviewCount(run);
  if (counts.succeededCount > 0) {
    return lang === "zh"
      ? `本轮已产出 ${counts.succeededCount} 条可用结果，覆盖 ${counts.referenceCount} 条引用；${needsReview ? `${needsReview} 条需要人工复核。` : "暂无明显失败项。"}`
      : `This run produced ${counts.succeededCount} usable results with ${counts.referenceCount} references; ${needsReview ? `${needsReview} need review.` : "no obvious failed items."}`;
  }
  if (counts.failedCount > 0) {
    return lang === "zh"
      ? `本轮没有形成可用结果，${counts.failedCount} 个来源失败，需要调整主题、来源或网络。`
      : `No usable results were produced; ${counts.failedCount} sources failed and need topic, source, or network review.`;
  }
  return lang === "zh"
    ? "本轮尚未生成结果，先启动搜索或等待执行回写。"
    : "No results have been generated yet; start a search or wait for writeback.";
}

export function aiSearchRunNextActionText(
  run: AiSearchRunDisplay,
  counts: ReturnType<typeof aiSearchRunCounts>,
  lang: "zh" | "en",
) {
  const needsReview = aiSearchRunNeedsReviewCount(run);
  if (run.status === "failed" || counts.succeededCount === 0) {
    return lang === "zh"
      ? "先检查失败来源，再缩小主题或换一组可信来源重搜。"
      : "Review failed sources first, then narrow the topic or retry with trusted sources.";
  }
  if (needsReview > 0) {
    return lang === "zh"
      ? "先复核备用扫描和失败项，通过后再进入资料提炼复核。"
      : "Review fallback and failed items before moving to source review.";
  }
  return lang === "zh"
    ? "可进入资料提炼复核，也可以继续扩大主题做下一轮搜索。"
    : "Ready for extraction review, or expand the topic for another search round.";
}
