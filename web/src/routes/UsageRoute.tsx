import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Database, Gauge, RefreshCw } from "lucide-react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { TokenUsageBreakdownItem, TokenUsageRollup, UsageSource, UsageSummaryResponse } from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { deriveQueryPresentation } from "../app/queryPresentation";
import { VButton, VIconButton, VLoadingValue, VMetricStrip, VRouteHeader, VStateSurface, VStatusStrip, VSurface } from "../components/vui";
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

function usageValue(state: boolean | "unavailable", value: number | undefined, loadingLabel: string) {
  if (state === "unavailable") {
    return "不可用";
  }
  return state ? <VLoadingValue label={loadingLabel} /> : numberText(value);
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
  const usagePresentation = deriveQueryPresentation({
    hasData: Boolean(summary),
    isError: usageQuery.isError,
    isFetching: usageQuery.isFetching,
    isPending: usageQuery.isPending,
  });
  const initialUsageLoading = usagePresentation === "initial-loading";
  const hasUsageData = Boolean(summary);
  const usageUnavailable = usagePresentation === "error-empty";
  const usageValueState = usageUnavailable ? "unavailable" : initialUsageLoading;
  const allTime = globalTokenUsage?.allTime;
  const today = globalTokenUsage?.today;
  const last7Days = globalTokenUsage?.last7Days;
  const sessionUsage = summary?.sessionTokenUsage;
  const agentUsage = summary?.agentTokenUsage;
  const scopeUsage = summary?.scopeTokenUsage;
  const loadedRollup = (rollup: TokenUsageRollup | undefined) => rollup ?? EMPTY_ROLLUP;
  const allTimeLoaded = loadedRollup(allTime);
  const sessionRollupLabel = summary?.rollupFilters?.sessionId || "-";
  const agentRollupLabel = summary?.rollupFilters?.agentId || "-";
  const totalTokens = allTimeLoaded.totalTokens;
  const lastSource = lastTokenUsage?.source ?? "not_called";
  const observedRatio = allTimeLoaded.callCount > 0 ? allTimeLoaded.observedCallCount / allTimeLoaded.callCount : 0;
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.usageSummary("global") });
  };
  const emptyBreakdownLabel = label(
    lang,
    "当前接口尚未提供真实细分；这里保留为后续模型/来源聚合入口。",
    "The current API does not expose real breakdown rows yet.",
  );

  return (
    <section className={styles.page} aria-busy={initialUsageLoading}>
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
              { label: label(lang, "刷新", "Refresh"), value: usagePresentation === "refreshing" ? label(lang, "同步中", "Syncing") : label(lang, "自动", "Auto"), tone: usageQuery.isError ? "danger" : "neutral" },
              { label: label(lang, "账本", "Ledger"), value: summary?.diagnostics?.source ?? "usage_ledger", tone: "info" },
            ]}
          />
        )}
      />

      <VMetricStrip
        ariaLabel={label(lang, "Token 用量概览", "Token usage overview")}
        className={styles.overviewBand}
        metrics={[
          { id: "all-time", label: label(lang, "全局累计", "All time"), value: usageValue(usageValueState, allTime?.totalTokens, label(lang, "正在加载全局累计", "Loading all-time usage")) },
          { id: "today", label: label(lang, "今日", "Today"), value: usageValue(usageValueState, today?.totalTokens, label(lang, "正在加载今日用量", "Loading today's usage")) },
          { id: "last-seven-days", label: label(lang, "最近七日", "Last 7 days"), value: usageValue(usageValueState, last7Days?.totalTokens, label(lang, "正在加载七日用量", "Loading seven-day usage")) },
          { id: "latest", label: label(lang, "最近一次", "Latest"), value: usageValue(usageValueState, lastTokenUsage?.totalTokens, label(lang, "正在加载最近用量", "Loading latest usage")), detail: formatTimestamp(lastTokenUsage?.recordedAt, lang) },
        ]}
        status={{ label: sourceLabel(lastSource, lang), tone: lastSource === "provider_usage" ? "success" : lastSource === "missing" ? "warning" : "info" }}
      />

      {usagePresentation === "error-with-data" ? (
        <VStateSurface className={styles.emptyState} title={label(lang, "用量摘要读取失败。", "Usage summary failed to load.")} tone="error">
          {usageQuery.error instanceof Error ? usageQuery.error.message : label(lang, "用量摘要读取失败。", "Usage summary failed to load.")}
        </VStateSurface>
      ) : usageUnavailable ? (
        <VStateSurface
          className={styles.emptyState}
          title={label(lang, "Token 用量暂不可用", "Token usage unavailable")}
          tone="error"
          actions={<VButton type="button" onPress={() => void usageQuery.refetch()}>{label(lang, "重试", "Retry")}</VButton>}
        >
          {usageQuery.error instanceof Error ? usageQuery.error.message : label(lang, "用量摘要读取失败。", "Usage summary failed to load.")}
        </VStateSurface>
      ) : !summary || lastSource === "not_called" ? (
        <VStateSurface
          busy={usageQuery.isFetching}
          className={styles.emptyState}
          skeletonLines={usageQuery.isFetching}
          title={label(lang, "尚未调用", "Not called yet")}
          tone={usageQuery.isFetching ? "loading" : "info"}
        >
          {label(lang, "当前没有可用的 Token 用量记录。", "No token usage record is available yet.")}
        </VStateSurface>
      ) : lastSource === "missing" ? (
        <VStateSurface
          className={styles.emptyState}
          title={label(lang, "缺少用量", "Missing usage")}
          tone="unavailable"
        >
          {label(lang, "最近一次调用未返回用量；0 不代表成功用量。", "The latest call did not return usage; zero is not successful usage.")}
        </VStateSurface>
      ) : null}

      <div className={styles.metricBand}>
        <div className={styles.primaryColumn}>
          <VSurface as="section" className={styles.compositionPanel} elevation="panel" tone="rail">
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{label(lang, "可信度", "Reliability")}</p>
                <h2>{label(lang, "Token 构成", "Token composition")}</h2>
              </div>
              <span className={styles.countPill}>{usageUnavailable ? label(lang, "不可用", "Unavailable") : initialUsageLoading ? <VLoadingValue label={label(lang, "正在加载可信度", "Loading reliability")} /> : percentText(observedRatio)}</span>
            </div>
            {!hasUsageData ? (
              <VStateSurface
                tone={usageUnavailable ? "unavailable" : "loading"}
                title={usageUnavailable ? label(lang, "Token 构成不可用", "Token composition unavailable") : label(lang, "正在加载 Token 构成", "Loading token composition")}
                skeletonLines={usageUnavailable ? undefined : 3}
              />
            ) : <><div className={styles.sourceGrid}>
              {SOURCE_KEYS.map((source) => (
                <section key={source} className={sourceClassName(source)}>
                  <span>{sourceLabel(source, lang)}</span>
                  <strong>{usageValue(usageValueState, sourceCount(allTimeLoaded, source), label(lang, "正在加载来源计数", "Loading source count"))}</strong>
                </section>
              ))}
            </div>
            <div className={styles.usageList}>
              {renderUsageRow(label(lang, "输入", "Input"), allTimeLoaded.inputTokens, totalTokens, label(lang, "prompt", "prompt"))}
              {renderUsageRow(label(lang, "缓存输入", "Cached input"), allTimeLoaded.cachedInputTokens, allTimeLoaded.inputTokens, percentText(allTimeLoaded.cacheHitRate))}
              {renderUsageRow(label(lang, "输出", "Output"), allTimeLoaded.outputTokens, totalTokens, label(lang, "answer", "answer"))}
              {renderUsageRow(label(lang, "推理输出", "Reasoning output"), allTimeLoaded.reasoningOutputTokens, totalTokens, "reasoningOutputTokens")}
            </div></>}
          </VSurface>

          <VSurface as="section" className={styles.rollupPanel} elevation="panel" tone="rail">
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
            {!hasUsageData ? (
              <VStateSurface
                tone={usageUnavailable ? "unavailable" : "loading"}
                title={usageUnavailable ? label(lang, "计数概览不可用", "Counting overview unavailable") : label(lang, "正在加载计数概览", "Loading counting overview")}
                skeletonLines={usageUnavailable ? undefined : 3}
              />
            ) : <div className={styles.rollupGrid}>
              <div className={`${styles.usageRow} ${styles.usageRowWide}`}>
                <span>{label(lang, "当前范围", "Current scope")}</span>
                <strong>{usageValue(usageValueState, scopeUsage?.totalTokens, label(lang, "正在加载范围用量", "Loading scope usage"))}</strong>
                <code>{summary?.scope ?? "global"}</code>
              </div>
              <div className={`${styles.usageRow} ${styles.usageRowWide}`}>
                <span>{label(lang, "最近会话", "Latest session")}</span>
                <strong>{usageValue(usageValueState, sessionUsage?.totalTokens, label(lang, "正在加载会话用量", "Loading session usage"))}</strong>
                <code>{sessionRollupLabel}</code>
              </div>
              <div className={`${styles.usageRow} ${styles.usageRowWide}`}>
                <span>{label(lang, "最近 Agent", "Latest agent")}</span>
                <strong>{usageValue(usageValueState, agentUsage?.totalTokens, label(lang, "正在加载 Agent 用量", "Loading agent usage"))}</strong>
                <code>{agentRollupLabel}</code>
              </div>
              <div className={`${styles.usageRow} ${styles.usageRowWide}`}>
                <span>{label(lang, "上下文窗口", "Context window")}</span>
                <strong>{usageValue(usageValueState, summary?.modelContextWindow, label(lang, "正在加载上下文窗口", "Loading context window"))}</strong>
                <code><Gauge size={13} /> window</code>
              </div>
              <div className={`${styles.usageRow} ${styles.usageRowWide}`}>
                <span>{label(lang, "延迟累计", "Latency total")}</span>
                <strong>{usageValue(usageValueState, allTime?.latencyMs, label(lang, "正在加载延迟", "Loading latency"))} ms</strong>
                <code><Activity size={13} /> api</code>
              </div>
            </div>}
          </VSurface>
        </div>

        <VSurface as="aside" className={styles.recordPanel} elevation="panel" tone="rail">
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{label(lang, "最近记录", "Latest record")}</p>
              <h2>{sourceLabel(lastSource, lang)}</h2>
            </div>
            <span className={styles.countPill}>
              <Database size={13} />
              {usageUnavailable ? label(lang, "不可用", "Unavailable") : summary?.diagnostics?.schemaVersion ?? 1}
            </span>
          </div>
          {!hasUsageData ? (
            <VStateSurface
              tone={usageUnavailable ? "unavailable" : "loading"}
              title={usageUnavailable ? label(lang, "最近记录不可用", "Latest record unavailable") : label(lang, "正在加载最近记录", "Loading latest record")}
              skeletonLines={usageUnavailable ? undefined : 3}
            />
          ) : <><div className={styles.detailGrid}>
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
          {renderBreakdownList(summary?.breakdowns?.models ?? [], emptyBreakdownLabel)}</>}
        </VSurface>
      </div>
    </section>
  );
}
