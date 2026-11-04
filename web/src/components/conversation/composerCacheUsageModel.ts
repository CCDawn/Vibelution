import type { TokenUsageRollup, TokenUsageSample } from "../../api/types";

export type ComposerCacheUsageSnapshot = {
  sessionTokenUsage: TokenUsageRollup;
  lastTokenUsage: TokenUsageSample;
};

export type ComposerCacheUsageModel = {
  state: "ready" | "partial" | "not_called" | "missing" | "loading" | "error";
  sessionPercent: number | null;
  lastCallPercent: number | null;
  observedCalls: number;
  totalCalls: number;
  updating: boolean;
};

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function percent(cached: unknown, input: unknown): number | null {
  const numerator = count(cached);
  const denominator = count(input);
  return numerator !== null && denominator !== null && denominator > 0 && numerator <= denominator
    ? Math.round(numerator / denominator * 100) : null;
}

/** Rates use observed provider input totals; missing observations never count as zero. */
export function buildComposerCacheUsageModel({
  snapshot, loading = false, error = false, updating = false,
}: {
  snapshot?: ComposerCacheUsageSnapshot;
  loading?: boolean;
  error?: boolean;
  updating?: boolean;
}): ComposerCacheUsageModel {
  const session = snapshot?.sessionTokenUsage;
  const last = snapshot?.lastTokenUsage;
  const observedCalls = count(session?.cacheObservedCallCount) ?? 0;
  const unobservedCalls = count(session?.cacheUnobservedCallCount) ?? 0;
  // Estimated/missing calls have no provider-cache evidence either. Also accept
  // legacy rollups whose cacheUnobservedCallCount covers provider rows only.
  const totalCalls = Math.max(observedCalls + unobservedCalls,
    (count(session?.callCount) ?? 0) - (count(session?.notCalledCount) ?? 0));
  const sessionPercent = session && (session.cacheUsageObserved === true || observedCalls > 0)
    ? percent(session.cachedInputTokens, session.cacheObservedInputTokens) : null;
  const lastCallPercent = last?.source === "provider_usage" && last.cacheUsageObserved === true
    ? percent(last.cachedInputTokens ?? last.cacheReadInputTokens, last.inputTokens) : null;
  const state = error ? "error"
    : loading && !snapshot ? "loading"
      : !snapshot ? "missing"
        : sessionPercent !== null ? totalCalls > observedCalls ? "partial" : "ready"
          : totalCalls === 0 ? "not_called" : "missing";
  return { state, sessionPercent, lastCallPercent, observedCalls,
    totalCalls, updating };
}
