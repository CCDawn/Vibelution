/**
 * Source-collection action chrome: i18n loading copy + readiness helpers.
 * Pure; free of React. Used by TeamsRoute presentation (Phase 4+ presentation extract).
 */
import type { SourceCollectionActionReadiness } from "./stageProjection";

export const SOURCE_COLLECTION_ACTION_READY: SourceCollectionActionReadiness = {
  disabled: false,
  loading: false,
  reason: "",
};

export function sourceCollectionLoadingChrome(lang: "zh" | "en") {
  return {
    loadingText: lang === "zh" ? "加载中" : "loading",
    dataSyncText: lang === "zh" ? "同步中" : "syncing",
    loadingSummary: lang === "zh" ? "正在读取资料提炼结果" : "Loading extraction results",
    actionLoadingReason: lang === "zh" ? "正在读取当前批次数据" : "Loading current batch data",
    actionErrorReason:
      lang === "zh"
        ? "当前批次数据读取失败，请刷新后重试"
        : "Current batch data failed to load. Refresh and retry.",
    actionNoRunReason: lang === "zh" ? "还没有可执行的搜集批次" : "No collection run is available yet.",
    actionNoInputReason: lang === "zh" ? "当前阶段还没有可执行输入" : "This stage has no runnable input yet.",
    actionBusyReason: lang === "zh" ? "已有任务正在执行" : "A task is already running.",
  };
}

export function sourceCollectionActionReadinessOf(
  disabled: boolean,
  reason: string,
  loading = false,
): SourceCollectionActionReadiness {
  return disabled
    ? { disabled: true, loading, reason }
    : SOURCE_COLLECTION_ACTION_READY;
}

export function sourceCollectionActionDisabledTitle(
  readiness: SourceCollectionActionReadiness,
  fallback: string,
): string {
  return readiness.disabled && readiness.reason ? readiness.reason : fallback;
}
