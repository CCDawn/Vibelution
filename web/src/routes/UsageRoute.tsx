import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Database, Gauge, RefreshCw } from "lucide-react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { TokenUsageBreakdownItem, TokenUsageRollup, UsageSource, UsageSummaryResponse } from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { VIconButton, VRouteHeader, VStatusStrip } from "../components/vui";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./UsageRoute.styles";

const SOURCE_KEYS: UsageSource[] = ["provider_usage", "estimated", "missing", "not_called"];

const EMPTY_ROLLUP: TokenUsageRollup = {
  inputTokens: 0,
  cachedInputTokens: 0,
  cacheReadInputTokens: 0,
  cacheCreationInputTokens: 0,
  uncachedInputTokens: 0,
  outputTokens: 0,
  reasoningOutputTokens: 0,
  totalTokens: 0,
  callCount: 0,
  observedCallCount: 0,
  estimatedCallCount: 0,
  missingCallCount: 0,
  notCalledCount: 0,
  latencyMs: 0,
  cacheHitRate: 0,
};

function label(lang: "zh" | "en", zh: string, en: string) {
  return lang === "zh" ? zh : en;
}

function numberText(value: number | undefined) {
  return new Intl.NumberFormat().format(Math.max(0, Math.round(Number(value ?? 0))));
}

function percentText(value: number | undefined) {
  return `${Math.round(Math.max(0, Math.min(1, Number(value ?? 0))) * 100)}%`;
}

function formatTimestamp(value: string | undefined, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text) {
    return label(lang, "未记录", "Not recorded");
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

function sourceLabel(source: UsageSource, lang: "zh" | "en") {
  if (source === "provider_usage") {
    return label(lang, "供应商返回", "Provider usage");
  }
  if (source === "estimated") {
    return label(lang, "本地估算", "Estimated");
  }
  if (source === "missing") {
    return label(lang, "缺少用量", "Missing usage");
  }
  if (source === "not_called") {
    return label(lang, "尚未调用", "Not called");
  }
  return String(source || "-").replaceAll("_", " ");
}

function rollupOrEmpty(rollup: TokenUsageRollup | undefined): TokenUsageRollup {
  return rollup ?? EMPTY_ROLLUP;
}

function sourceCount(rollup: TokenUsageRollup, source: UsageSource) {
  if (source === "provider_usage") {
    return rollup.observedCallCount;
  }
  if (source === "estimated") {
    return rollup.estimatedCallCount;
  }
  if (source === "missing") {
    return rollup.missingCallCount;
  }
  if (source === "not_called") {
    return rollup.notCalledCount;
  }
  return 0;
}

function sourceClassName(source: UsageSource) {
  if (source === "provider_usage") {
    return `${styles.sourceTile} ${styles.sourceTileObserved}`;
  }
  if (source === "estimated") {
    return `${styles.sourceTile} ${styles.sourceTileEstimated}`;
  }
  if (source === "missing") {
    return `${styles.sourceTile} ${styles.sourceTileMissing}`;
  }
  return `${styles.sourceTile} ${styles.sourceTileEmpty}`;
}

function renderUsageRow(labelText: string, value: number, total: number, detail: string) {
  const ratio = total > 0 ? value / total : 0;
  return (
    <div className={styles.usageRow}>
      <span>{labelText}</span>
      <div className={styles.progressTrack} aria-hidden="true">
        <span className={styles.progressFill} style={{ width: percentText(ratio) }} />
      </div>
      <strong>{numberText(value)}</strong>
      <code>{detail}</code>
    </div>
  );
}

function renderBreakdownList(items: TokenUsageBreakdownItem[], emptyLabel: string) {
  if (!items.length) {
    return <p className={styles.quietState}>{emptyLabel}</p>;
  }
  return (
    <div className={styles.breakdownList}>
      {items.map((item) => (
        <div key={`${item.key}:${item.label}`} className={styles.breakdownRow}>
          <strong>{item.label || item.key}</strong>
          <span>{numberText(item.totalTokens)}</span>
        </div>
      ))}
    </div>
  );
}

export function UsageRoute() {
  const { lang } = useAppI18n();
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const usageQuery = useQuery({
    queryKey: queryKeys.usageSummary("global"),
    queryFn: () => fetchJson<UsageSummaryResponse>("/api/usage/summary"),
    refetchInterval: resolvePollingInterval(pageVisible, 10_000, { backgroundMs: 60_000 }),
    refetchIntervalInBackground: false,
  });

  const summary = usageQuery.data;
  const globalTokenUsage = summary?.globalTokenUsage;
  const lastTokenUsage = summary?.lastTokenUsage;
  const allTime = rollupOrEmpty(globalTokenUsage?.allTime);
  const today = rollupOrEmpty(globalTokenUsage?.today);
  const last7Days = rollupOrEmpty(globalTokenUsage?.last7Days);
  const sessionUsage = rollupOrEmpty(summary?.sessionTokenUsage);
  const agentUsage = rollupOrEmpty(summary?.agentTokenUsage);
  const scopeUsage = rollupOrEmpty(summary?.scopeTokenUsage);
  const sessionRollupLabel = summary?.rollupFilters?.sessionId || "-";
  const agentRollupLabel = summary?.rollupFilters?.agentId || "-";
  const totalTokens = allTime.totalTokens;
  const lastSource = lastTokenUsage?.source ?? "not_called";
  const observedRatio = allTime.callCount > 0 ? allTime.observedCallCount / allTime.callCount : 0;
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.usageSummary("global") });
  };
  const emptyBreakdownLabel = label(
    lang,
    "当前接口尚未提供真实细分；这里保留为后续模型/来源聚合入口。",
    "The current API does not expose real breakdown rows yet.",
  );

  return (
    <section className={styles.page} aria-busy={usageQuery.isPending && !summary}>
      <VRouteHeader
        className={styles.header}
        eyebrow="Token"
        title={label(lang, "全局 Token 用量", "Global token usage")}
        meta={label(lang, "按 Codex 风格展示最近一次、最近会话、最近 Agent、今日、七日和全局累计。", "Codex-style latest, latest session, latest agent, today, seven-day, and all-time usage.")}
        actions={(
          <VStatusStrip
            className={styles.headerMeta}
            items={[
              { label: label(lang, "来源", "Source"), value: sourceLabel(lastSource, lang), tone: lastSource === "provider_usage" ? "success" : lastSource === "missing" ? "warning" : "info" },
              { label: label(lang, "刷新", "Refresh"), value: usageQuery.isFetching ? label(lang, "同步中", "Syncing") : label(lang, "自动", "Auto"), tone: usageQuery.isError ? "danger" : "neutral" },
              { label: label(lang, "账本", "Ledger"), value: summary?.diagnostics?.source ?? "usage_ledger", tone: "info" },
            ]}
          />
        )}
      />

      <div className={styles.overviewBand}>
        <section className={styles.heroMetric}>
          <span>{label(lang, "全局累计", "All time")}</span>
          <strong>{numberText(allTime.totalTokens)}</strong>
          <small>{allTime.callCount} {label(lang, "次调用", "calls")}</small>
        </section>
        <div className={styles.overviewStats}>
          <section className={styles.overviewStat}>
            <span>{label(lang, "今日", "Today")}</span>
            <strong>{numberText(today.totalTokens)}</strong>
            <small>{numberText(today.inputTokens)} / {numberText(today.outputTokens)}</small>
          </section>
          <section className={styles.overviewStat}>
            <span>{label(lang, "最近七日", "Last 7 days")}</span>
            <strong>{numberText(last7Days.totalTokens)}</strong>
            <small>{numberText(last7Days.reasoningOutputTokens)} {label(lang, "推理输出", "reasoning")}</small>
          </section>
          <section className={styles.overviewStat}>
            <span>{label(lang, "最近一次", "Latest")}</span>
            <strong>{numberText(lastTokenUsage?.totalTokens)}</strong>
            <small>{formatTimestamp(lastTokenUsage?.recordedAt, lang)}</small>
          </section>
        </div>
      </div>

      {usageQuery.isError ? (
        <p className={styles.errorState}>
          {usageQuery.error instanceof Error ? usageQuery.error.message : label(lang, "用量摘要读取失败。", "Usage summary failed to load.")}
        </p>
      ) : null}

      <div className={styles.metricBand}>
        <div className={styles.primaryColumn}>
          <section className={styles.compositionPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{label(lang, "可信度", "Reliability")}</p>
                <h2>{label(lang, "Token 构成", "Token composition")}</h2>
              </div>
              <span className={styles.countPill}>{percentText(observedRatio)}</span>
            </div>
            <div className={styles.sourceGrid}>
              {SOURCE_KEYS.map((source) => (
                <section key={source} className={sourceClassName(source)}>
                  <span>{sourceLabel(source, lang)}</span>
                  <strong>{numberText(sourceCount(allTime, source))}</strong>
                </section>
              ))}
            </div>
            <div className={styles.usageList}>
              {renderUsageRow(label(lang, "输入", "Input"), allTime.inputTokens, totalTokens, label(lang, "prompt", "prompt"))}
              {renderUsageRow(label(lang, "缓存输入", "Cached input"), allTime.cachedInputTokens, allTime.inputTokens, percentText(allTime.cacheHitRate))}
              {renderUsageRow(label(lang, "输出", "Output"), allTime.outputTokens, totalTokens, label(lang, "answer", "answer"))}
              {renderUsageRow(label(lang, "推理输出", "Reasoning output"), allTime.reasoningOutputTokens, totalTokens, "reasoningOutputTokens")}
            </div>
          </section>

          <section className={styles.rollupPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{label(lang, "汇总", "Rollups")}</p>
                <h2>{label(lang, "计数概览", "Counting overview")}</h2>
              </div>
              <VIconButton
                type="button"
                className={styles.refreshButton}
                label={label(lang, "刷新 Token 用量", "Refresh token usage")}
                icon={<RefreshCw size={16} />}
                onPress={refresh}
              />
            </div>
            <div className={styles.rollupGrid}>
              <div className={`${styles.usageRow} ${styles.usageRowWide}`}>
                <span>{label(lang, "当前范围", "Current scope")}</span>
                <strong>{numberText(scopeUsage.totalTokens)}</strong>
                <code>{summary?.scope ?? "global"}</code>
              </div>
              <div className={`${styles.usageRow} ${styles.usageRowWide}`}>
                <span>{label(lang, "最近会话", "Latest session")}</span>
                <strong>{numberText(sessionUsage.totalTokens)}</strong>
                <code>{sessionRollupLabel}</code>
              </div>
              <div className={`${styles.usageRow} ${styles.usageRowWide}`}>
                <span>{label(lang, "最近 Agent", "Latest agent")}</span>
                <strong>{numberText(agentUsage.totalTokens)}</strong>
                <code>{agentRollupLabel}</code>
              </div>
              <div className={`${styles.usageRow} ${styles.usageRowWide}`}>
                <span>{label(lang, "上下文窗口", "Context window")}</span>
                <strong>{numberText(summary?.modelContextWindow)}</strong>
                <code><Gauge size={13} /> window</code>
              </div>
              <div className={`${styles.usageRow} ${styles.usageRowWide}`}>
                <span>{label(lang, "延迟累计", "Latency total")}</span>
                <strong>{numberText(allTime.latencyMs)} ms</strong>
                <code><Activity size={13} /> api</code>
              </div>
            </div>
          </section>
        </div>

        <aside className={styles.recordPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{label(lang, "最近记录", "Latest record")}</p>
              <h2>{sourceLabel(lastSource, lang)}</h2>
            </div>
            <span className={styles.countPill}>
              <Database size={13} />
              {summary?.diagnostics?.schemaVersion ?? 1}
            </span>
          </div>
          <div className={styles.detailGrid}>
            <div className={styles.detailRow}>
              <span>provider / model</span>
              <strong>{[lastTokenUsage?.provider, lastTokenUsage?.model].filter(Boolean).join(" / ") || "-"}</strong>
            </div>
            <div className={styles.detailRow}>
              <span>event</span>
              <strong>{lastTokenUsage?.eventId || "-"}</strong>
            </div>
            <div className={styles.detailRow}>
              <span>{label(lang, "缓存读取", "Cache read")}</span>
              <strong>{numberText(lastTokenUsage?.cacheReadInputTokens)}</strong>
            </div>
            <div className={styles.detailRow}>
              <span>{label(lang, "未缓存输入", "Uncached input")}</span>
              <strong>{numberText(lastTokenUsage?.uncachedInputTokens)}</strong>
            </div>
            <div className={styles.detailRow}>
              <span>{label(lang, "跳过记录", "Skipped rows")}</span>
              <strong>{numberText(summary?.diagnostics?.skippedRecordCount)}</strong>
            </div>
          </div>
          {renderBreakdownList(summary?.breakdowns?.models ?? [], emptyBreakdownLabel)}
        </aside>
      </div>
    </section>
  );
}
