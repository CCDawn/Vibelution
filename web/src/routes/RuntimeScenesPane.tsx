import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Check, CheckSquare, Copy, ListFilter, Square, Trash2, TriangleAlert, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
} from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  LogDiagnostics,
  LogFileContent,
  LogRoot,
  RuntimeSceneIssueCluster,
  RuntimeSceneDeleteResponse,
  RuntimeSceneDetail,
  RuntimeSceneListItem,
  RuntimeSceneWorkRunItem,
} from "../api/types";
import { LazyFilePreview } from "../components/preview/LazyFilePreview";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { TranslationKey } from "../i18n/dictionary";
import { classifyRuntimeSceneEvent, type LogSeverityFilter, matchesSeverityFilter } from "../logs/logSeverity";
import styles from "./LogsRoute.module.css";
import { runtimeScenePackageFiles, runtimeScenePackageSections } from "./runtimeScenePackageSections";

type ActionNotice = {
  tone: "success" | "error";
  message: string;
};

const RESIZE_HANDLE_WIDTH = 16;
const RUNTIME_SCENES_SIDEBAR_STORAGE_KEY = "vibelution.logs.runtime-scenes-sidebar-width";
const DEFAULT_RUNTIME_SCENES_SIDEBAR_WIDTH = 320;
const MIN_RUNTIME_SCENES_SIDEBAR_WIDTH = 280;
const MAX_RUNTIME_SCENES_SIDEBAR_WIDTH = 560;
const MIN_RUNTIME_SCENES_PREVIEW_WIDTH = 520;
const KEYBOARD_RESIZE_STEP = 24;

type DragState = {
  startX: number;
  startWidth: number;
};

type RuntimeScenesPaneProps = {
  activeRoot: LogRoot;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  statusLabel: (status: string) => string;
  initialSceneId?: string;
  initialPath?: string;
};

function filterRuntimeScenes(items: RuntimeSceneListItem[], query: string): RuntimeSceneListItem[] {
  const term = query.trim().toLowerCase();
  if (!term) {
    return items;
  }
  return items.filter((item) =>
    [
      item.runtimeSceneId,
      item.directoryName,
      item.title,
      item.displayName,
      item.packageIndex?.displayName,
      item.packageIndex?.indexKey,
      item.packageIndex?.startedDate,
      item.packageIndex?.startedTime,
      item.packageIndex?.startedAtLocal,
      item.packageIndex?.searchText,
      ...(item.packageIndex?.tags ?? []),
      item.status,
      item.result,
      item.stopReason,
      item.trigger,
      item.backendStatus,
      item.frontendStatus,
      item.browserStatus,
    ]
      .join(" ")
      .toLowerCase()
      .includes(term),
  );
}

function uniqueIds(items: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of items) {
    const value = String(item || "").trim();
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    result.push(value);
  }
  return result;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getMaxSidebarWidth(layoutWidth: number) {
  const maxWidth = layoutWidth - RESIZE_HANDLE_WIDTH - MIN_RUNTIME_SCENES_PREVIEW_WIDTH;
  return Math.max(MIN_RUNTIME_SCENES_SIDEBAR_WIDTH, Math.min(MAX_RUNTIME_SCENES_SIDEBAR_WIDTH, maxWidth));
}

function normalizeSidebarWidth(layoutWidth: number, sidebarWidth: number) {
  return Math.round(clamp(sidebarWidth, MIN_RUNTIME_SCENES_SIDEBAR_WIDTH, getMaxSidebarWidth(layoutWidth)));
}

function describeError(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return `${fallback}: ${error.message}`;
  }
  return fallback;
}

function severityLabel(severity: string, lang: "zh" | "en") {
  if (severity === "error") {
    return lang === "zh" ? "有错误" : "Errors";
  }
  if (severity === "warning") {
    return lang === "zh" ? "有警告" : "Warnings";
  }
  return lang === "zh" ? "未见明显异常" : "No obvious issues";
}

function severityClassName(severity: string) {
  if (severity === "error") {
    return `${styles.diagnosticPill} ${styles.diagnosticPillError}`;
  }
  if (severity === "warning") {
    return `${styles.diagnosticPill} ${styles.diagnosticPillWarning}`;
  }
  return `${styles.diagnosticPill} ${styles.diagnosticPillInfo}`;
}

function renderDiagnosticsPanel(diagnostics: LogDiagnostics, lang: "zh" | "en") {
  const firstSignalLabel =
    diagnostics.firstSignalLine === null || diagnostics.firstSignalLine === undefined
      ? lang === "zh"
        ? "无"
        : "None"
      : `${lang === "zh" ? "第" : "Line "}${diagnostics.firstSignalLine}${lang === "zh" ? " 行" : ""}`;
  return (
    <section className={styles.diagnosticsPanel}>
      <div className={styles.diagnosticsHeader}>
        <div>
          <p className={styles.sidebarEyebrow}>{lang === "zh" ? "原始日志摘要" : "Raw Log Summary"}</p>
          <h2 className={styles.sidebarTitle}>
            {lang === "zh" ? "先看信号，再对照时间线" : "Inspect signals, then compare timeline"}
          </h2>
        </div>
        <span className={severityClassName(diagnostics.severity)}>
          {severityLabel(diagnostics.severity, lang)}
        </span>
      </div>
      <p className={styles.diagnosticsSummary}>{diagnostics.userSummary}</p>
      <div className={styles.diagnosticMetricGrid}>
        <span>
          <strong>{diagnostics.errorCount}</strong>
          {lang === "zh" ? " 错误" : " errors"}
        </span>
        <span>
          <strong>{diagnostics.warningCount}</strong>
          {lang === "zh" ? " 警告" : " warnings"}
        </span>
        <span>
          <strong>{diagnostics.lineCount}</strong>
          {lang === "zh" ? " 行" : " lines"}
        </span>
        <span>
          <strong>{diagnostics.structuredEventCount}</strong>
          {lang === "zh" ? " 结构事件" : " structured"}
        </span>
      </div>
      <div className={styles.diagnosticHintGrid}>
        <article>
          <span>{lang === "zh" ? "首个信号" : "First signal"}</span>
          <strong>{firstSignalLabel}</strong>
          {diagnostics.firstSignalPreview ? <p>{diagnostics.firstSignalPreview}</p> : null}
        </article>
        <article>
          <span>{lang === "zh" ? "建议动作" : "Suggested next step"}</span>
          <p>{diagnostics.suggestedNextStep}</p>
        </article>
        <article>
          <span>{lang === "zh" ? "Agent 排查锚点" : "Agent investigation anchor"}</span>
          <code>{diagnostics.agentHint}</code>
        </article>
      </div>
    </section>
  );
}

function renderPackageDiagnosisPanel(
  scene: RuntimeSceneDetail,
  lang: "zh" | "en",
  handleOpenRawLog: (sceneId: string, path: string) => void,
) {
  const diagnosis = scene.packageDiagnosis;
  if (!diagnosis) {
    return null;
  }
  const firstSignal = diagnosis.firstSignal;
  const firstSignalLabel = firstSignal?.eventCode
    ? `${formatTimestamp(firstSignal.timestamp, lang)} · ${localizeRuntimeSceneText(firstSignal.component, lang)} · ${
        firstSignal.eventCode
      }`
    : lang === "zh"
      ? "未发现错误或警告信号"
      : "No error or warning signal";
  const keyEntries = diagnosis.keyEntries ?? [];
  const recommendedOrder = diagnosis.recommendedOrder ?? [];
  const startupSteps = diagnosis.startupTrace?.steps ?? [];
  const issueState = diagnosis.issueState;
  const workRunSummary = diagnosis.workRunSummary;
  const activeRuns = workRunSummary?.activeRuns ?? [];
  const highFrequencyRuns = workRunSummary?.highFrequencyRuns ?? [];
  const latestRuns = workRunSummary?.latestRuns ?? [];
  const visibleWorkRuns = [...activeRuns, ...highFrequencyRuns, ...latestRuns].filter(
    (run, index, runs) =>
      index === runs.findIndex((item) => `${item.runKind}:${item.runId}` === `${run.runKind}:${run.runId}`),
  );
  const showWorkRunSummary = Boolean(
    workRunSummary &&
      (workRunSummary.snapshotEventCount > 0 ||
        workRunSummary.runCount > 0 ||
        workRunSummary.activeRunCount > 0 ||
        workRunSummary.highFrequencyRunCount > 0),
  );
  const activeSignalCount = issueState ? issueState.activeErrorCount + issueState.activeWarningCount : 0;
  const historicalSignalCount = issueState ? issueState.historicalErrorCount + issueState.historicalWarningCount : 0;
  const activeIssueCount = issueState ? issueState.activeClusterCount ?? activeSignalCount : 0;
  const policyIssueCount = issueState ? issueState.policyClusterCount ?? issueState.policySignalCount ?? 0 : 0;
  const historicalIssueCount = issueState ? issueState.historicalClusterCount ?? historicalSignalCount : 0;
  const primaryCluster =
    issueState?.firstActiveCluster ??
    issueState?.firstPolicyCluster ??
    issueState?.firstHistoricalCluster ??
    issueState?.activeClusters?.[0] ??
    issueState?.policyClusters?.[0] ??
    issueState?.historicalClusters?.[0];
  const evidencePaths = diagnosis.evidencePaths?.length
    ? diagnosis.evidencePaths
    : [
        ...(primaryCluster?.rawRefs ?? []).map((ref) => ref.path),
        ...(firstSignal?.rawRefs ?? []).map((ref) => ref.path),
        ...recommendedOrder,
      ].filter((path, index, paths) => path && paths.indexOf(path) === index);
  const visibleClusters = [
    ...(issueState?.activeClusters ?? []).slice(0, 3),
    ...(issueState?.policyClusters ?? []).slice(0, 2),
    ...(issueState?.historicalClusters ?? []).slice(0, 2),
  ].slice(0, 4);
  const primaryClusterLabel =
    activeIssueCount > 0
      ? lang === "zh"
        ? "主活跃问题簇"
        : "Primary active cluster"
      : policyIssueCount > 0
        ? lang === "zh"
          ? "主控制/策略簇"
          : "Primary policy cluster"
        : lang === "zh"
          ? "主历史问题簇"
          : "Primary historical cluster";
  const signalHeading = firstSignal?.eventCode
    ? activeIssueCount > 0
      ? lang === "zh"
        ? "优先信号"
        : "Priority signal"
      : policyIssueCount > 0
        ? lang === "zh"
          ? "策略信号"
          : "Policy signal"
        : historicalIssueCount > 0
        ? lang === "zh"
          ? "历史信号"
          : "Historical signal"
        : lang === "zh"
          ? "控制信号"
          : "Control signal"
    : lang === "zh"
      ? "信号"
      : "Signal";
  return (
    <section className={styles.packageDiagnosisPanel}>
      <div className={styles.packageDiagnosisHeader}>
        <div>
          <p className={styles.sidebarEyebrow}>{lang === "zh" ? "日志包诊断" : "Package Diagnosis"}</p>
          <h3>{lang === "zh" ? "先判断周期，再打开证据" : "Assess cycle, then open evidence"}</h3>
        </div>
        <span className={severityClassName(diagnosis.severity)}>{severityLabel(diagnosis.severity, lang)}</span>
      </div>
      <p className={styles.packageDiagnosisSummary}>{diagnosis.userSummary}</p>
      {issueState ? (
        <div className={styles.packageIssueStateStrip}>
          <span>
            <strong>{activeIssueCount}</strong>
            {lang === "zh" ? " 活跃问题簇" : " active clusters"}
          </span>
          <span>
            <strong>{policyIssueCount}</strong>
            {lang === "zh" ? " 策略簇" : " policy clusters"}
          </span>
          <span>
            <strong>{historicalIssueCount}</strong>
            {lang === "zh" ? " 历史/已恢复簇" : " historical clusters"}
          </span>
          <span>
            <strong>{issueState.controlSignalCount}</strong>
            {lang === "zh" ? " 控制信号" : " control"}
          </span>
        </div>
      ) : null}
      {showWorkRunSummary && workRunSummary ? (
        <div className={styles.packageWorkRunPanel}>
          <div className={styles.packageWorkRunHeader}>
            <span>{lang === "zh" ? "运行任务摘要" : "Work Run Summary"}</span>
            {workRunSummary.eventsPath ? (
              <button
                type="button"
                className={styles.packageWorkRunPathButton}
                onClick={() => handleOpenRawLog(scene.runtimeSceneId, workRunSummary.eventsPath)}
                title={
                  lang === "zh"
                    ? `打开 Work Run 事件源：${workRunSummary.eventsPath}`
                    : `Open work run event source: ${workRunSummary.eventsPath}`
                }
              >
                {workRunSummary.eventsPath}
              </button>
            ) : null}
          </div>
          <div className={styles.packageWorkRunMetricStrip}>
            <span>
              <strong>{workRunSummary.activeRunCount}</strong>
              {lang === "zh" ? " 活跃" : " active"}
            </span>
            <span>
              <strong>{workRunSummary.highFrequencyRunCount}</strong>
              {lang === "zh" ? " 高频" : " high-frequency"}
            </span>
            <span>
              <strong>{workRunSummary.snapshotEventCount}</strong>
              {lang === "zh" ? " 快照" : " snapshots"}
            </span>
            <span>
              <strong>{workRunSummary.runCount}</strong>
              {lang === "zh" ? " 运行项" : " runs"}
            </span>
          </div>
          {visibleWorkRuns.length > 0 ? (
            <div className={styles.packageWorkRunList}>
              {visibleWorkRuns.slice(0, 4).map((run) => (
                <div key={`${run.runKind}-${run.runId}`} className={styles.packageWorkRunItem}>
                  <strong>{runtimeSceneWorkRunLabel(run, lang)}</strong>
                  <span>{runtimeSceneWorkRunMeta(run, lang)}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {evidencePaths.length > 0 ? (
        <div className={styles.packageEvidencePaths}>
          <span>{lang === "zh" ? "优先排查路径" : "Priority evidence paths"}</span>
          <div>
            {evidencePaths.slice(0, 6).map((path, index) => (
              <button
                key={`${path}-${index}`}
                type="button"
                onClick={() => handleOpenRawLog(scene.runtimeSceneId, path)}
                title={
                  lang === "zh"
                    ? `包内相对路径：${path}`
                    : `Package-relative path: ${path}`
                }
              >
                <strong>{index + 1}</strong>
                <code>{path}</code>
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {primaryCluster ? (
        <div className={styles.packagePrimaryCluster}>
          <span>{primaryClusterLabel}</span>
          <strong>{runtimeSceneIssueClusterLabel(primaryCluster, lang)}</strong>
          <p>{runtimeSceneIssueClusterMeta(primaryCluster, lang)}</p>
          {primaryCluster.rawRefs?.length ? (
            <div className={styles.packageClusterRefs}>
              {primaryCluster.rawRefs.slice(0, 2).map((ref, index) => (
                <button
                  key={`${primaryCluster.eventCode}-${ref.path}-${index}`}
                  type="button"
                  onClick={() => handleOpenRawLog(scene.runtimeSceneId, ref.path)}
                >
                  {ref.path}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {diagnosis.startupTrace ? (
        <div className={styles.startupTracePanel}>
          <div className={styles.startupTraceHeader}>
            <span>{lang === "zh" ? "启动流程" : "Startup flow"}</span>
            <strong>{diagnosis.startupTrace.summary}</strong>
          </div>
          <div className={styles.startupTraceSteps}>
            {startupSteps.map((step) => (
              <button
                key={step.id}
                type="button"
                className={
                  step.status === "recorded"
                    ? styles.startupTraceStep
                    : `${styles.startupTraceStep} ${styles.startupTraceStepMissing}`
                }
                onClick={() => step.evidencePath && handleOpenRawLog(scene.runtimeSceneId, step.evidencePath)}
                disabled={!step.evidencePath}
                title={step.message || step.eventCode || step.evidencePath}
              >
                <span>{localizeRuntimeSceneText(step.label, lang)}</span>
                <strong>
                  {step.status === "recorded"
                    ? lang === "zh"
                      ? "已记录"
                      : "Recorded"
                    : lang === "zh"
                      ? "缺失"
                      : "Missing"}
                </strong>
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <div className={styles.packageDiagnosisGrid}>
        <article>
          <span>{signalHeading}</span>
          <strong>{firstSignalLabel}</strong>
          {firstSignal?.message ? <p>{localizeRuntimeSceneText(firstSignal.message, lang)}</p> : null}
        </article>
        <article>
          <span>{lang === "zh" ? "Agent 下一步" : "Agent next step"}</span>
          <p>{diagnosis.agentNextStep}</p>
        </article>
      </div>
      <details className={styles.packageDiagnosisDetails}>
        <summary className={styles.packageDiagnosisSummaryRow}>
          <span className={styles.packageDiagnosisSummaryText}>
            {lang === "zh" ? "阅读顺序与关键入口" : "Reading order and key entries"}
          </span>
          <span className={styles.packageDiagnosisInlineMetrics}>
            <strong>{Math.min(recommendedOrder.length, 8)}</strong>
            {lang === "zh" ? " 项阅读" : " items"}
            <strong>{keyEntries.length}</strong>
            {lang === "zh" ? " 个入口" : " entries"}
          </span>
          <span className={styles.packageDiagnosisExpandLabel}>{lang === "zh" ? "展开" : "Open"}</span>
        </summary>
        <div className={styles.packageDiagnosisFoldout}>
          <div className={styles.packageDiagnosisFoldoutSection}>
            <span>{lang === "zh" ? "推荐阅读顺序" : "Reading order"}</span>
            <div className={styles.packageReadingOrder}>
              {recommendedOrder.slice(0, 8).map((path, index) => (
                <code key={`${path}-${index}`}>{path}</code>
              ))}
            </div>
          </div>
          {keyEntries.length > 0 ? (
            <div className={styles.packageDiagnosisFoldoutSection}>
              <span>{lang === "zh" ? "关键入口" : "Key entries"}</span>
              <div className={styles.packageKeyEntries}>
                {keyEntries.slice(0, 6).map((entry) => (
                  <button
                    key={entry.path}
                    type="button"
                    className={styles.packageKeyEntryButton}
                    onClick={() => handleOpenRawLog(scene.runtimeSceneId, entry.path)}
                  >
                    <strong>{localizeRuntimeSceneText(entry.label, lang)}</strong>
                    <span>{entry.path}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {visibleClusters.length > 0 ? (
            <div className={styles.packageDiagnosisFoldoutSection}>
              <span>{lang === "zh" ? "问题簇索引" : "Issue cluster index"}</span>
              <div className={styles.packageClusterList}>
                {visibleClusters.map((cluster, index) => (
                  <div key={`${cluster.eventCode}-${cluster.firstTimestamp}-${index}`} className={styles.packageClusterItem}>
                    <strong>{runtimeSceneIssueClusterLabel(cluster, lang)}</strong>
                    <span>{runtimeSceneIssueClusterMeta(cluster, lang)}</span>
                    {cluster.rawRefs?.[0]?.path ? (
                      <button type="button" onClick={() => handleOpenRawLog(scene.runtimeSceneId, cluster.rawRefs[0].path)}>
                        {cluster.rawRefs[0].path}
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </details>
    </section>
  );
}

function runtimeSceneIssueClusterLabel(cluster: RuntimeSceneIssueCluster, lang: "zh" | "en") {
  const label = cluster.label || [cluster.component, cluster.eventCode].filter(Boolean).join(" / ");
  const localized = localizeRuntimeSceneText(label || (lang === "zh" ? "未命名问题簇" : "Unnamed issue cluster"), lang);
  return cluster.repeatCount > 1 ? `${localized} x${cluster.repeatCount}` : localized;
}

function runtimeSceneIssueClusterMeta(cluster: RuntimeSceneIssueCluster, lang: "zh" | "en") {
  const parts = [
    severityLabel(cluster.severity, lang),
    cluster.phase ? localizeRuntimeSceneText(cluster.phase, lang) : "",
    cluster.firstTimestamp ? formatTimestamp(cluster.firstTimestamp, lang) : "",
  ].filter(Boolean);
  if (cluster.lastTimestamp && cluster.lastTimestamp !== cluster.firstTimestamp) {
    parts.push(lang === "zh" ? `最后 ${formatTimestamp(cluster.lastTimestamp, lang)}` : `Last ${formatTimestamp(cluster.lastTimestamp, lang)}`);
  }
  return parts.join(lang === "zh" ? " · " : " · ");
}

function runtimeSceneWorkRunLabel(run: RuntimeSceneWorkRunItem, lang: "zh" | "en") {
  const kind = localizeRuntimeSceneText(run.runKind || "work_run", lang) || (lang === "zh" ? "运行任务" : "Work run");
  const runId = run.runId || (lang === "zh" ? "未知 ID" : "unknown id");
  return `${kind} · ${runId}`;
}

function runtimeSceneWorkRunMeta(run: RuntimeSceneWorkRunItem, lang: "zh" | "en") {
  const status = localizeRuntimeSceneText(run.latestStatus || "unknown", lang);
  const phase = run.latestPhase ? localizeRuntimeSceneText(run.latestPhase, lang) : "";
  const parts = [
    lang === "zh" ? `${run.snapshotCount} 次快照` : `${run.snapshotCount} snapshots`,
    status ? (lang === "zh" ? `状态 ${status}` : `status ${status}`) : "",
    phase ? (lang === "zh" ? `阶段 ${phase}` : `phase ${phase}`) : "",
    run.latestAt ? formatTimestamp(run.latestAt, lang) : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

function formatTimestamp(value: string, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text) {
    return lang === "zh" ? "未记录" : "Not recorded";
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return parsed.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function runtimeSceneDisplayName(scene: RuntimeSceneListItem | RuntimeSceneDetail) {
  const title = "title" in scene ? scene.title : "";
  return scene.packageIndex?.displayName || scene.displayName || title || scene.directoryName || scene.runtimeSceneId;
}

function runtimeSceneIndexLabel(scene: RuntimeSceneListItem | RuntimeSceneDetail) {
  return scene.packageIndex?.indexKey || scene.directoryName || scene.runtimeSceneId;
}

function runtimeSceneStartedLabel(scene: RuntimeSceneListItem | RuntimeSceneDetail, lang: "zh" | "en") {
  const date = scene.packageIndex?.startedDate || "";
  const time = scene.packageIndex?.startedTime || "";
  if (date && time) {
    return `${date} ${time}`;
  }
  return formatTimestamp(scene.startedAt, lang);
}

function formatDuration(seconds: number | null | undefined, lang: "zh" | "en") {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) {
    return lang === "zh" ? "未结束" : "Open";
  }
  if (seconds < 60) {
    return lang === "zh" ? `${Math.round(seconds)} 秒` : `${Math.round(seconds)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return lang === "zh" ? `${minutes} 分 ${rest} 秒` : `${minutes}m ${rest}s`;
}

function formatBytes(size: number) {
  const value = Number(size || 0);
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function issueCount(value: unknown) {
  const count = Number(value || 0);
  return Number.isFinite(count) && count > 0 ? count : 0;
}

function runtimeSceneSignal(scene: RuntimeSceneDetail, lang: "zh" | "en") {
  const issueState = scene.packageDiagnosis?.issueState;
  if (issueState) {
    const activeErrors = issueCount(issueState.activeErrorCount);
    const activeWarnings = issueCount(issueState.activeWarningCount);
    const activeClusters = Math.max(
      issueCount(issueState.activeClusterCount),
      activeErrors + activeWarnings,
    );
    if (activeClusters > 0) {
      return {
        severity: activeErrors > 0 || scene.packageDiagnosis?.severity === "error" ? "error" : "warning",
        label: lang === "zh" ? `${activeClusters} 个活跃问题` : `${activeClusters} active issues`,
      };
    }
    const policyClusters = Math.max(
      issueCount(issueState.policyClusterCount),
      issueCount(issueState.policySignalCount),
    );
    if (policyClusters > 0) {
      return {
        severity: "warning",
        label: lang === "zh" ? `${policyClusters} 个策略信号` : `${policyClusters} policy signals`,
      };
    }
    const historicalClusters = issueCount(issueState.historicalClusterCount);
    if (historicalClusters > 0) {
      return {
        severity: "info",
        label: lang === "zh" ? "历史已恢复" : "Recovered history",
      };
    }
  }
  const errors = scene.packageSummary?.errorCount ?? 0;
  const warnings = scene.packageSummary?.warningCount ?? 0;
  if (errors > 0) {
    return {
      severity: "error",
      label: lang === "zh" ? `${errors} 个错误` : `${errors} errors`,
    };
  }
  if (warnings > 0) {
    return {
      severity: "warning",
      label: lang === "zh" ? `${warnings} 个警告` : `${warnings} warnings`,
    };
  }
  return {
    severity: "info",
    label: lang === "zh" ? "未见明显异常" : "No obvious issues",
  };
}

function runtimeSceneListSignal(scene: RuntimeSceneListItem, lang: "zh" | "en") {
  if (scene.diagnosisSummary) {
    const activeErrors = issueCount(scene.diagnosisSummary.activeErrorCount);
    const activeWarnings = issueCount(scene.diagnosisSummary.activeWarningCount);
    const activeClusters = Math.max(
      issueCount(scene.diagnosisSummary.activeClusterCount),
      activeErrors + activeWarnings,
      scene.diagnosisSummary.needsAction ? 1 : 0,
    );
    if (activeClusters > 0) {
      return {
        severity: activeErrors > 0 || scene.diagnosisSummary.severity === "error" ? "error" : "warning",
        label: lang === "zh" ? `${activeClusters} 个活跃问题` : `${activeClusters} active issues`,
      };
    }
    const policyClusters = Math.max(
      issueCount(scene.diagnosisSummary.policyClusterCount),
      issueCount(scene.diagnosisSummary.policySignalCount),
    );
    if (policyClusters > 0) {
      return {
        severity: "warning",
        label: lang === "zh" ? `${policyClusters} 个策略信号` : `${policyClusters} policy signals`,
      };
    }
    return null;
  }
  const errors = Number(scene.errorCount || 0);
  const warnings = Number(scene.warningCount || 0);
  if (errors <= 0 && warnings <= 0) {
    return null;
  }
  const parts: string[] = [];
  if (errors > 0) {
    parts.push(lang === "zh" ? `${errors} 个错误` : `${errors} errors`);
  }
  if (warnings > 0) {
    parts.push(lang === "zh" ? `${warnings} 个警告` : `${warnings} warnings`);
  }
  return {
    severity: errors > 0 ? "error" : "warning",
    label: parts.join(lang === "zh" ? "，" : ", "),
  };
}

function runtimeSceneListSummary(scene: RuntimeSceneListItem, lang: "zh" | "en") {
  return localizeRuntimeSceneText(
    scene.stopReason || scene.result || scene.displayName || scene.title || scene.directoryName,
    lang,
  );
}

function runtimeSceneChildLogCount(scene: RuntimeSceneDetail) {
  return (
    (scene.packageSummary?.rawLogCount ?? scene.rawFiles.length) +
    (scene.packageSummary?.conversationLogCount ?? scene.conversationLogs.length) +
    (scene.packageSummary?.agentLogCount ?? scene.agentLogs.length) +
    (scene.packageSummary?.artifactCount ?? scene.artifacts.length) +
    (scene.packageSummary?.eventLogCount ?? scene.eventLogs?.length ?? 0) +
    (scene.packageSummary?.researchLogCount ?? scene.researchLogs?.length ?? 0)
  );
}

const runtimeSceneTokenZhMap: Record<string, string> = {
  start: "启动",
  "internal-start": "内部启动",
  "internal-restart": "内部重启",
  managed: "托管",
  current: "当前",
  pending: "待处理",
  healthy: "正常",
  stopped: "已停止",
  running: "运行中",
  success: "成功",
  explicit_stop: "手动停止",
  "explicit stop": "手动停止",
  failed: "失败",
  info: "信息",
  error: "错误",
  launcher: "启动器",
  frontend: "前端",
  backend: "后端",
  browser: "浏览器",
  research: "科研",
  supervisor: "监督器",
  work_run: "运行任务",
  chat_turn: "对话轮次",
  chat_room_round: "群聊轮次",
  self: "自进化",
  self_evolution_run: "自进化运行",
  supervised_evolution_run: "监督进化运行",
  supervised_worktree_evolution_run: "监督工作树运行",
  completed: "已完成",
  queued: "排队中",
  stopping: "停止中",
  session: "会话",
  startup: "启动",
  shutdown: "关闭",
  build: "构建",
  dependencies: "依赖",
  health: "健康检查",
  window: "窗口",
  browser_window_closed: "应用窗口已关闭",
  "app window closed": "应用窗口已关闭",
  "Lifecycle package summary": "日志包摘要",
  "Package index": "包索引",
  "Unified timeline": "统一时间线",
  "Lifecycle events": "生命周期事件",
  "First signal evidence": "首个信号证据",
  "Frontend build log": "前端构建日志",
  "Backend stdout": "后端标准输出",
  "Backend stderr": "后端错误输出",
  "Browser log": "浏览器日志",
  "Supervisor log": "监督器日志",
  "Supervisor stderr": "监督器错误输出",
  "Conversation child log": "对话子日志",
  "Agent child log": "Agent 子日志",
  "Component event stream": "组件事件流",
  "Raw log": "原始日志",
  Artifact: "产物",
};

const runtimeSceneFieldZhMap: Record<string, string> = {
  directory_name: "目录名",
  browser_managed: "浏览器托管",
  trigger: "触发方式",
  port: "端口",
  host: "主机",
  python_label: "Python 环境",
  pid: "进程号",
  url: "地址",
  executable: "可执行文件",
  managed_session_id: "托管会话 ID",
  browser_window_pid: "浏览器窗口进程",
  backend_pid: "后端进程",
  supervisor_pid: "监督器进程",
  browser_stopped: "浏览器已停止",
  backend_stopped: "后端已停止",
  reason: "原因",
  window_pid: "窗口进程",
  launch_pid: "启动进程",
};

function localizeRuntimeSceneText(text: string, lang: "zh" | "en") {
  const normalized = String(text || "").trim();
  if (!normalized || lang !== "zh") {
    return normalized;
  }
  return runtimeSceneTokenZhMap[normalized] ?? normalized;
}

function summarizeFields(fields: Record<string, unknown>) {
  return Object.entries(fields)
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`);
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "absolute";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) {
    throw new Error("copy failed");
  }
}

export function RuntimeScenesPane({ activeRoot, lang, t, statusLabel, initialSceneId = "", initialPath = "" }: RuntimeScenesPaneProps) {
  const queryClient = useQueryClient();
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const [sceneSearch, setSceneSearch] = useState("");
  const [selectedSceneIds, setSelectedSceneIds] = useState<string[]>([]);
  const [activeSceneId, setActiveSceneId] = useState(initialSceneId);
  const [severityFilter, setSeverityFilter] = useState<LogSeverityFilter>("all");
  const [openRawLogByScene, setOpenRawLogByScene] = useState<Record<string, string>>(() =>
    initialSceneId && initialPath ? { [initialSceneId]: initialPath } : {},
  );
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    if (typeof window === "undefined") {
      return DEFAULT_RUNTIME_SCENES_SIDEBAR_WIDTH;
    }
    const saved = Number(window.localStorage.getItem(RUNTIME_SCENES_SIDEBAR_STORAGE_KEY) || "");
    return Number.isFinite(saved)
      ? clamp(saved, MIN_RUNTIME_SCENES_SIDEBAR_WIDTH, MAX_RUNTIME_SCENES_SIDEBAR_WIDTH)
      : DEFAULT_RUNTIME_SCENES_SIDEBAR_WIDTH;
  });
  const pageVisible = usePageVisibility();

  const runtimeScenesQuery = useQuery({
    queryKey: queryKeys.runtimeScenes(),
    queryFn: () => fetchJson<RuntimeSceneListItem[]>("/api/logs/runtime-scenes"),
    refetchInterval: resolvePollingInterval(pageVisible, 10_000),
    refetchIntervalInBackground: false,
  });

  const filteredScenes = useMemo(
    () => filterRuntimeScenes(runtimeScenesQuery.data ?? [], sceneSearch),
    [runtimeScenesQuery.data, sceneSearch],
  );
  const visibleSceneIds = useMemo(() => filteredScenes.map((item) => item.runtimeSceneId), [filteredScenes]);
  const selectedSceneIdSet = useMemo(() => new Set(selectedSceneIds), [selectedSceneIds]);

  useEffect(() => {
    if (!initialSceneId) {
      return;
    }
    setActiveSceneId(initialSceneId);
    if (initialPath) {
      setOpenRawLogByScene((current) => ({ ...current, [initialSceneId]: initialPath }));
    }
  }, [initialPath, initialSceneId]);

  useEffect(() => {
    const availableIds = new Set((runtimeScenesQuery.data ?? []).map((item) => item.runtimeSceneId));
    setSelectedSceneIds((current) => current.filter((id) => availableIds.has(id)));
    if (activeSceneId && availableIds.has(activeSceneId)) {
      return;
    }
    setActiveSceneId((runtimeScenesQuery.data ?? [])[0]?.runtimeSceneId ?? "");
  }, [activeSceneId, runtimeScenesQuery.data]);

  const sceneDetailQuery = useQuery({
    queryKey: queryKeys.runtimeScene(activeSceneId),
    enabled: Boolean(activeSceneId),
    queryFn: () => fetchJson<RuntimeSceneDetail>(`/api/logs/runtime-scenes/${encodeURIComponent(activeSceneId)}`),
    refetchInterval: resolvePollingInterval(pageVisible, 5_000),
    refetchIntervalInBackground: false,
  });

  const activeRawLogPath =
    (activeSceneId ? openRawLogByScene[activeSceneId] : "") ||
    (sceneDetailQuery.data ? runtimeScenePackageFiles(sceneDetailQuery.data)[0]?.path : "") ||
    "";

  useEffect(() => {
    if (!activeSceneId || !sceneDetailQuery.data) {
      return;
    }
    const packageFiles = runtimeScenePackageFiles(sceneDetailQuery.data);
    const availablePaths = new Set(packageFiles.map((item) => item.path));
    const current = openRawLogByScene[activeSceneId] ?? "";
    if (current && availablePaths.has(current)) {
      return;
    }
    setOpenRawLogByScene((state) => ({
      ...state,
      [activeSceneId]: packageFiles[0]?.path ?? "",
    }));
  }, [activeSceneId, openRawLogByScene, sceneDetailQuery.data]);

  const sceneContentQuery = useQuery({
    queryKey: queryKeys.runtimeSceneContent(activeSceneId, activeRawLogPath),
    enabled: Boolean(activeSceneId && activeRawLogPath),
    queryFn: () =>
      fetchJson<LogFileContent>(
        `/api/logs/runtime-scenes/${encodeURIComponent(activeSceneId)}/content?path=${encodeURIComponent(activeRawLogPath)}`,
      ),
    refetchInterval: resolvePollingInterval(pageVisible, 5_000),
    refetchIntervalInBackground: false,
  });

  const deleteRuntimeScenesMutation = useMutation({
    mutationFn: async (sceneIds: string[]) =>
      fetchJson<RuntimeSceneDeleteResponse>("/api/logs/runtime-scenes/delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ sceneIds }),
      }),
    onSuccess: (payload, sceneIds) => {
      const deletedIdSet = new Set(payload.deletedSceneIds);
      setSelectedSceneIds((current) => current.filter((id) => !deletedIdSet.has(id)));
      setOpenRawLogByScene((current) => {
        const next: Record<string, string> = {};
        for (const [key, value] of Object.entries(current)) {
          if (!deletedIdSet.has(key)) {
            next[key] = value;
          }
        }
        return next;
      });
      if (deletedIdSet.has(activeSceneId)) {
        setActiveSceneId("");
      }
      queryClient.setQueryData<RuntimeSceneListItem[] | undefined>(queryKeys.runtimeScenes(), (current) =>
        (current ?? []).filter((item) => !deletedIdSet.has(item.runtimeSceneId)),
      );
      for (const sceneId of payload.deletedSceneIds) {
        queryClient.removeQueries({ queryKey: queryKeys.runtimeScene(sceneId) });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeScenes() });
      setActionNotice({
        tone: "success",
        message: `已删除 ${payload.deletedCount} 组运行现场日志`,
      });
    },
    onError: (error) => {
      setActionNotice({
        tone: "error",
        message: describeError(error, t("logActionFailed")),
      });
    },
  });

  useEffect(() => {
    setCopyState("idle");
  }, [activeSceneId, activeRawLogPath, sceneContentQuery.data?.content]);

  useEffect(() => {
    if (copyState === "idle") {
      return;
    }
    const timeout = window.setTimeout(() => setCopyState("idle"), 1800);
    return () => window.clearTimeout(timeout);
  }, [copyState]);

  useEffect(() => {
    if (!actionNotice) {
      return;
    }
    const timeout = window.setTimeout(() => setActionNotice(null), 2400);
    return () => window.clearTimeout(timeout);
  }, [actionNotice]);

  const syncSidebarWidthToLayout = useCallback(() => {
    const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
    if (!layoutWidth) {
      return;
    }
    const normalized = normalizeSidebarWidth(layoutWidth, sidebarWidth);
    if (normalized !== sidebarWidth) {
      setSidebarWidth(normalized);
    }
  }, [sidebarWidth]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(RUNTIME_SCENES_SIDEBAR_STORAGE_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    syncSidebarWidthToLayout();
    const layoutElement = layoutRef.current;
    if (!layoutElement) {
      return;
    }

    const observer = new ResizeObserver(() => {
      syncSidebarWidthToLayout();
    });
    observer.observe(layoutElement);
    return () => observer.disconnect();
  }, [syncSidebarWidthToLayout]);

  useEffect(() => {
    if (!dragState) {
      return;
    }

    const activeDrag = dragState;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function stopDragging() {
      setDragState(null);
    }

    function handlePointerMove(event: globalThis.PointerEvent) {
      const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
      if (!layoutWidth) {
        return;
      }
      const delta = event.clientX - activeDrag.startX;
      setSidebarWidth(normalizeSidebarWidth(layoutWidth, activeDrag.startWidth + delta));
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);
    window.addEventListener("mousemove", handlePointerMove as EventListener);
    window.addEventListener("mouseup", stopDragging);

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
      window.removeEventListener("mousemove", handlePointerMove as EventListener);
      window.removeEventListener("mouseup", stopDragging);
    };
  }, [dragState]);

  const copyLabel =
    copyState === "copied" ? t("copied") : copyState === "error" ? t("copyFailed") : t("copyContent");
  const severityFilterOptions: Array<{
    value: LogSeverityFilter;
    label: string;
    icon: typeof ListFilter;
  }> = [
    { value: "all", label: t("logSeverityAll"), icon: ListFilter },
    { value: "error", label: t("logSeverityError"), icon: CircleAlert },
    { value: "warning", label: t("logSeverityWarning"), icon: TriangleAlert },
  ];
  const selectedCountLabel =
    lang === "zh" ? `${t("selectedScenes")} ${selectedSceneIds.length} 组` : `${selectedSceneIds.length} ${t("selectedScenes")}`;
  const severityFilterControl = (
    <div className={styles.filterGroup} role="group" aria-label={t("logSeverityFilter")}>
      {severityFilterOptions.map((option) => {
        const Icon = option.icon;
        const active = severityFilter === option.value;
        return (
          <button
            key={option.value}
            type="button"
            className={active ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
            onClick={() => setSeverityFilter(option.value)}
          >
            <Icon size={14} />
            <span>{option.label}</span>
          </button>
        );
      })}
    </div>
  );

  function handleToggleSelection(sceneId: string) {
    setSelectedSceneIds((current) => {
      const next = current.includes(sceneId) ? current.filter((item) => item !== sceneId) : [...current, sceneId];
      return uniqueIds(next);
    });
  }

  function handleSelectVisible() {
    setSelectedSceneIds(uniqueIds(visibleSceneIds));
  }

  function handleClearSelection() {
    setSelectedSceneIds([]);
  }

  function handleOpenRawLog(sceneId: string, path: string) {
    setOpenRawLogByScene((current) => ({
      ...current,
      [sceneId]: path,
    }));
  }

  async function handleCopy() {
    if (!sceneContentQuery.data?.content) {
      return;
    }
    try {
      await copyText(sceneContentQuery.data.content);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  }

  function buildDeleteConfirmationLabel(sceneIds: string[]) {
    const sceneById = new Map((runtimeScenesQuery.data ?? []).map((scene) => [scene.runtimeSceneId, scene]));
    const names = sceneIds.slice(0, 4).map((sceneId) => {
      const scene = sceneById.get(sceneId);
      return scene ? `${runtimeSceneDisplayName(scene)} (${sceneId})` : sceneId;
    });
    const tail = sceneIds.length > names.length ? `\n等 ${sceneIds.length} 组运行。` : "";
    return `确认删除这 ${sceneIds.length} 组运行现场日志吗？\n${names.map((name) => `- ${name}`).join("\n")}${tail}`;
  }

  function handleDeleteSelected() {
    if (selectedSceneIds.length === 0 || deleteRuntimeScenesMutation.isPending) {
      return;
    }
    if (!window.confirm(buildDeleteConfirmationLabel(selectedSceneIds))) {
      return;
    }
    deleteRuntimeScenesMutation.mutate(selectedSceneIds);
  }

  const previewActions = (
    <div className={styles.previewActions}>
      <button type="button" className={styles.copyButton} onClick={handleCopy} disabled={!sceneContentQuery.data?.content}>
        {copyState === "copied" ? <Check size={15} /> : <Copy size={15} />}
        <span>{copyLabel}</span>
      </button>
    </div>
  );

  const layoutStyle = useMemo(
    () =>
      ({
        "--logs-sidebar-width": sidebarCollapsed ? "0px" : `${sidebarWidth}px`,
      }) as CSSProperties,
    [sidebarCollapsed, sidebarWidth],
  );

  function beginResize(clientX: number) {
    setDragState({
      startX: clientX,
      startWidth: sidebarWidth,
    });
  }

  function handleResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    if (sidebarCollapsed) {
      return;
    }
    event.preventDefault();
    beginResize(event.clientX);
  }

  function handleResizeMouseDown(event: MouseEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    if (sidebarCollapsed) {
      return;
    }
    event.preventDefault();
    beginResize(event.clientX);
  }

  function handleResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!layoutRef.current) {
      return;
    }
    if (sidebarCollapsed) {
      return;
    }

    const { key } = event;
    const direction =
      key === "ArrowLeft" ? -1 : key === "ArrowRight" ? 1 : key === "Home" ? "min" : key === "End" ? "max" : null;
    if (direction === null) {
      return;
    }

    event.preventDefault();
    const layoutWidth = layoutRef.current.getBoundingClientRect().width;
    const maxWidth = getMaxSidebarWidth(layoutWidth);
    const nextWidth =
      direction === "min"
        ? MIN_RUNTIME_SCENES_SIDEBAR_WIDTH
        : direction === "max"
          ? maxWidth
          : clamp(
              sidebarWidth + Number(direction) * KEYBOARD_RESIZE_STEP,
              MIN_RUNTIME_SCENES_SIDEBAR_WIDTH,
              maxWidth,
            );
    setSidebarWidth(Math.round(nextWidth));
  }

  function renderSceneDetail(scene: RuntimeSceneDetail) {
    const signal = runtimeSceneSignal(scene, lang);
    const filteredTimeline = scene.timeline.filter((event) =>
      matchesSeverityFilter(classifyRuntimeSceneEvent(event), severityFilter),
    );
    const packageSections = runtimeScenePackageSections(scene);
    return (
      <div className={styles.sceneDetailSurface}>
        <div className={styles.sceneDetailHeaderCompact}>
          <div className={styles.sceneIdentityBlock}>
            <p className={styles.eyebrow}>{t("logsRootRuntimeScenes")}</p>
            <h2 className={styles.sceneDetailTitle}>{runtimeSceneDisplayName(scene)}</h2>
            <div className={styles.sceneQuickFacts}>
              <span className={severityClassName(signal.severity)}>{signal.label}</span>
              <span>{runtimeSceneStartedLabel(scene, lang)}</span>
              <span>{formatDuration(scene.packageIndex?.durationSeconds, lang)}</span>
              <code>{runtimeSceneIndexLabel(scene)}</code>
            </div>
          </div>
          <div className={styles.sceneHeaderControls}>
            <span className={styles.metaPill}>{statusLabel(scene.status)}</span>
            {previewActions}
          </div>
        </div>

        {renderPackageDiagnosisPanel(scene, lang, handleOpenRawLog)}

        <div className={styles.sceneEvidenceStrip}>
          <span>
            <strong>{scene.timeline.length}</strong>
            {lang === "zh" ? " 时间线事件" : " timeline events"}
          </span>
          <span>
            <strong>{runtimeSceneChildLogCount(scene)}</strong>
            {lang === "zh" ? " 子日志" : " child logs"}
          </span>
          <span>
            <strong>{scene.lifecycle.length}</strong>
            {lang === "zh" ? " 生命周期事件" : " lifecycle events"}
          </span>
          <span>
            <strong>{localizeRuntimeSceneText(scene.trigger || "start", lang)}</strong>
            {lang === "zh" ? " 触发" : " trigger"}
          </span>
        </div>

        <details className={styles.sceneTechnicalDetails}>
          <summary>{lang === "zh" ? "技术索引与低频信息" : "Technical index and metadata"}</summary>
          <div className={styles.sceneTechnicalGrid}>
            <span>
              <strong>ID</strong>
              <code>{scene.runtimeSceneId}</code>
            </span>
            <span>
              <strong>{lang === "zh" ? "索引 key" : "Index key"}</strong>
              <code>{runtimeSceneIndexLabel(scene)}</code>
            </span>
            <span>
              <strong>Manifest</strong>
              <code>{scene.manifestPath}</code>
            </span>
            <span>
              <strong>{lang === "zh" ? "模式" : "Mode"}</strong>
              {localizeRuntimeSceneText(scene.sessionMode || "managed", lang)}
            </span>
          </div>
        </details>

        <div className={styles.sceneInfoGrid}>
          <article className={styles.sceneInfoCard}>
            <div className={styles.sceneCardHeaderRow}>
              <h3>{t("runtimeSceneTimeline")}</h3>
              {severityFilterControl}
            </div>
            <div className={styles.timelineList}>
              {scene.timeline.length === 0 ? (
                <div className={styles.panelState}>{t("runtimeSceneNoTimeline")}</div>
              ) : filteredTimeline.length === 0 ? (
                <div className={styles.panelState}>{t("logSeverityEmpty")}</div>
              ) : (
                filteredTimeline.map((event) => {
                  const severity = classifyRuntimeSceneEvent(event);
                  const timelineItemClassName =
                    severity === "error"
                      ? `${styles.timelineItem} ${styles.timelineItemError}`
                      : severity === "warning"
                        ? `${styles.timelineItem} ${styles.timelineItemWarning}`
                        : styles.timelineItem;
                  return (
                    <div key={`${event.component}-${event.seq}-${event.timestamp}`} className={timelineItemClassName}>
                      <div className={styles.timelineHeader}>
                        <span>{formatTimestamp(event.timestamp, lang)}</span>
                        <span>{localizeRuntimeSceneText(event.component, lang)}</span>
                        <span>{localizeRuntimeSceneText(event.phase, lang)}</span>
                        <span>{localizeRuntimeSceneText(event.level, lang)}</span>
                      </div>
                      <strong className={styles.timelineCode}>{event.eventCode}</strong>
                      <p className={styles.timelineMessage}>{localizeRuntimeSceneText(event.message, lang)}</p>
                      {summarizeFields(event.fields).length > 0 ? (
                        <div className={styles.timelineFields}>
                          {Object.entries(event.fields)
                            .slice(0, 4)
                            .map(([key, value]) => {
                              const label = runtimeSceneFieldZhMap[key] ?? key;
                              const rendered = Array.isArray(value) ? value.join(", ") : String(value);
                              return (
                                <span key={`${key}:${rendered}`} className={styles.timelineField}>
                                  {`${label}: ${localizeRuntimeSceneText(rendered, lang)}`}
                                </span>
                              );
                            })}
                        </div>
                      ) : null}
                      {event.rawRefs.length > 0 ? (
                        <div className={styles.timelineRawRefs}>
                          {event.rawRefs.map((ref) => (
                            <button
                              key={`${event.eventCode}-${ref.path}`}
                              type="button"
                              className={styles.toolbarButton}
                              onClick={() => handleOpenRawLog(scene.runtimeSceneId, ref.path)}
                            >
                              <span>{t("runtimeSceneOpenRaw")}</span>
                              <span>{ref.path}</span>
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  );
                })
              )}
            </div>
          </article>

          <article className={styles.sceneInfoCard}>
            <div className={styles.sceneRawHeader}>
              <div>
                <h3>{t("runtimeSceneRawLogs")}</h3>
                <p className={styles.sceneDetailSummary}>
                  {lang === "zh"
                    ? "按用途选择日志；空分区表示本周期没有发生对应流程"
                    : "Choose logs by purpose; empty sections mean that flow did not run in this cycle"}
                </p>
              </div>
              <div className={styles.sceneHeaderControls}>{severityFilterControl}</div>
            </div>

            <div className={styles.packageSectionList}>
              {packageSections.map((section) => (
                <section key={section.id} className={styles.packageSection}>
                  <div className={styles.packageSectionHeader}>
                    <h4>{lang === "zh" ? section.titleZh : section.titleEn}</h4>
                    <span>{section.files.length}</span>
                  </div>
                  {section.files.length === 0 ? (
                    <div className={styles.packageSectionEmpty}>
                      {lang === "zh" ? section.emptyZh : section.emptyEn}
                    </div>
                  ) : (
                    <div className={styles.rawFileTabs}>
                      {section.files.map((item) => (
                        <button
                          key={item.path}
                          type="button"
                          className={
                            activeRawLogPath === item.path
                              ? `${styles.rawFileButton} ${styles.rawFileButtonActive}`
                              : styles.rawFileButton
                          }
                          onClick={() => handleOpenRawLog(scene.runtimeSceneId, item.path)}
                        >
                          <span>{item.label}</span>
                          <span>{formatBytes(item.size)}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </section>
              ))}
            </div>

            <div className={styles.sceneRawPreview}>
              {sceneContentQuery.isError ? (
                <div className={styles.panelState}>{describeError(sceneContentQuery.error, t("loadFailed"))}</div>
              ) : sceneContentQuery.isPending && !sceneContentQuery.data ? (
                <div className={styles.panelState}>{t("loadingFilePreview")}</div>
              ) : sceneContentQuery.data ? (
                <div className={styles.logPreviewStack}>
                  {renderDiagnosticsPanel(sceneContentQuery.data.diagnostics, lang)}
                  <LazyFilePreview
                    file={sceneContentQuery.data}
                    changed={false}
                    sourceLabel={activeRoot.path}
                    headerActions={null}
                    highlightAsLog
                    severityFilter={severityFilter}
                    fallback={<div className={styles.panelState}>{t("loadingFilePreview")}</div>}
                  />
                </div>
              ) : (
                <div className={styles.panelState}>{t("runtimeSceneNoRawLogs")}</div>
              )}
            </div>
          </article>
        </div>
      </div>
    );
  }

  return (
    <div ref={layoutRef} className={styles.resizableLayout} style={layoutStyle}>
      <aside className={sidebarCollapsed ? `${styles.sidebar} ${styles.paneCollapsed}` : styles.sidebar} aria-hidden={sidebarCollapsed}>
        <div className={styles.sidebarHeader}>
          <div>
            <p className={styles.sidebarEyebrow}>{t("logsRootRuntimeScenes")}</p>
            <h2 className={styles.sidebarTitle}>{activeRoot.path}</h2>
            <p className={styles.railText}>{t("runtimeScenesSubtitle")}</p>
          </div>
          <div className={styles.selectionToolbar}>
            <span className={styles.selectionPill}>{selectedCountLabel}</span>
            <div className={styles.selectionActions}>
              <button
                type="button"
                className={styles.toolbarButton}
                onClick={handleSelectVisible}
                disabled={visibleSceneIds.length === 0}
              >
                <CheckSquare size={15} />
                <span>{t("selectVisibleRuntimeScenes")}</span>
              </button>
              <button
                type="button"
                className={styles.toolbarButton}
                onClick={handleClearSelection}
                disabled={selectedSceneIds.length === 0}
              >
                <X size={15} />
                <span>{t("clearSelection")}</span>
              </button>
              <button
                type="button"
                className={styles.deleteButton}
                onClick={handleDeleteSelected}
                disabled={selectedSceneIds.length === 0 || deleteRuntimeScenesMutation.isPending}
                title={selectedSceneIds.length === 0 ? t("deleteSelectedRuntimeScenesDisabled") : undefined}
              >
                <Trash2 size={15} />
                <span>
                  {deleteRuntimeScenesMutation.isPending
                    ? t("deletingSelectedRuntimeScenes")
                    : t("deleteSelectedRuntimeScenes")}
                </span>
              </button>
            </div>
          </div>
          {actionNotice ? (
            <p
              className={
                actionNotice.tone === "success"
                  ? `${styles.notice} ${styles.noticeSuccess}`
                  : `${styles.notice} ${styles.noticeError}`
              }
            >
              {actionNotice.message}
            </p>
          ) : null}
        </div>

        <div className={styles.panelSearch}>
          <input
            className={styles.panelSearchInput}
            type="text"
            value={sceneSearch}
            onChange={(event) => setSceneSearch(event.target.value)}
            placeholder={t("searchRuntimeScenesPlaceholder")}
          />
        </div>

        <div className={styles.packageList}>
          {runtimeScenesQuery.isError ? (
            <div className={styles.panelState}>{describeError(runtimeScenesQuery.error, t("loadFailed"))}</div>
          ) : runtimeScenesQuery.isPending && !runtimeScenesQuery.data ? (
            <div className={styles.panelState}>{t("loadingLogs")}</div>
          ) : filteredScenes.length === 0 ? (
            <div className={styles.panelState}>
              {sceneSearch.trim() ? t("noRuntimeSceneMatches") : t("noRuntimeScenesYet")}
            </div>
          ) : (
            filteredScenes.map((scene) => {
              const isActive = activeSceneId === scene.runtimeSceneId;
              const isSelected = selectedSceneIdSet.has(scene.runtimeSceneId);
              const displayName = runtimeSceneDisplayName(scene);
              const signal = runtimeSceneListSignal(scene, lang);
              return (
                <div
                  key={scene.runtimeSceneId}
                  className={isActive ? `${styles.sceneCard} ${styles.sceneCardActive}` : styles.sceneCard}
                >
                  <div className={styles.sceneCardTop}>
                    <button
                      type="button"
                      className={
                        isSelected
                          ? `${styles.packageSelectButton} ${styles.packageSelectButtonActive}`
                          : styles.packageSelectButton
                      }
                      onClick={() => handleToggleSelection(scene.runtimeSceneId)}
                      title={isSelected ? t("clearSelection") : t("selectVisibleRuntimeScenes")}
                    >
                      {isSelected ? <CheckSquare size={16} /> : <Square size={16} />}
                    </button>
                    <button
                      type="button"
                      className={styles.sceneCardButton}
                      onClick={() => setActiveSceneId(scene.runtimeSceneId)}
                    >
                      <div className={styles.sceneCardHeader}>
                        <strong title={scene.runtimeSceneId}>{displayName}</strong>
                        <span className={styles.sceneCardStatusGroup}>
                          {signal ? (
                            <span
                              className={
                                signal.severity === "error"
                                  ? `${styles.sceneIssueBadge} ${styles.sceneIssueBadgeError}`
                                  : `${styles.sceneIssueBadge} ${styles.sceneIssueBadgeWarning}`
                              }
                            >
                              {signal.label}
                            </span>
                          ) : null}
                          <span className={styles.sceneCardStatus}>{statusLabel(scene.status)}</span>
                        </span>
                      </div>
                      <code className={styles.sceneIndexKey} title={runtimeSceneIndexLabel(scene)}>
                        {runtimeSceneIndexLabel(scene)}
                      </code>
                      <div className={styles.sceneCardMeta}>
                        <span>{lang === "zh" ? "日期" : "Date"} {scene.packageIndex?.startedDate || "-"}</span>
                        <span>{lang === "zh" ? "时间" : "Time"} {scene.packageIndex?.startedTime || "-"}</span>
                        <span>{scene.eventCount} 条事件</span>
                        <span>
                          {scene.rawLogCount +
                            scene.conversationCount +
                            scene.agentLogCount +
                            scene.artifactCount +
                            scene.eventLogCount}{" "}
                          个子日志
                        </span>
                      </div>
                      <p className={styles.sceneCardSummary}>
                        {runtimeSceneListSummary(scene, lang)}
                      </p>
                    </button>
                  </div>
                  <div className={styles.scenePillRow}>
                    <span className={styles.metaPill}>{localizeRuntimeSceneText(scene.trigger || "start", lang)}</span>
                    <span className={styles.metaPill}>{localizeRuntimeSceneText(scene.frontendStatus || "pending", lang)}</span>
                    <span className={styles.metaPill}>{localizeRuntimeSceneText(scene.backendStatus || "pending", lang)}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </aside>

      <PaneCollapseHandle
        side="left"
        collapsed={sidebarCollapsed}
        separatorLabel={t("resizeLeftPanel")}
        collapseLabel={lang === "zh" ? "收起左栏" : "Collapse left pane"}
        expandLabel={lang === "zh" ? "展开左栏" : "Expand left pane"}
        className={styles.resizeHandle}
        active={Boolean(dragState)}
        activeClassName={styles.resizeHandleActive}
        onToggle={() => setSidebarCollapsed((current) => !current)}
        onPointerDown={handleResizeStart}
        onMouseDown={handleResizeMouseDown}
        onKeyDown={handleResizeKeyDown}
      />

      <section className={styles.previewPane}>
        {!activeSceneId ? (
          <div className={styles.emptySurface}>{t("selectRuntimeScene")}</div>
        ) : sceneDetailQuery.isError ? (
          <div className={styles.emptySurface}>{describeError(sceneDetailQuery.error, t("loadFailed"))}</div>
        ) : sceneDetailQuery.isPending && !sceneDetailQuery.data ? (
          <div className={styles.emptySurface}>{t("loadingFilePreview")}</div>
        ) : sceneDetailQuery.data ? (
          renderSceneDetail(sceneDetailQuery.data)
        ) : (
          <div className={styles.emptySurface}>{t("loadingFilePreview")}</div>
        )}
      </section>
    </div>
  );
}
