import "../design/route-css/workbench-secondary.tailwind.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";

import {
  getLauncherBranchInstances,
  requestBranchInstanceLifecycle,
  getLauncherStatus,
  getLauncherDeveloperNoiseOverview,
  getLauncherMaintenanceSummary,
  applyLauncherDeveloperCleanup,
  applyLauncherMaintenancePlan,
  isLauncherControlPlaneNotReady,
  previewLauncherDeveloperCleanup,
  previewLauncherMaintenancePlan,
  reattachLauncherSupervisor,
  resetLauncherDeveloperSandbox,
  saveLauncherWorkbenchWindowMode,
  updateLauncherDeveloperMode,
  updateLauncherStartupSettings,
} from "../api/launcher";
import { useWorkbenchLifecycleActions } from "../app/useWorkbenchLifecycleActions";
import { queryKeys } from "../api/queryKeys";
import type {
  LauncherDeveloperCleanupAction,
  LauncherDeveloperCleanupPlan,
  LauncherMaintenancePlan,
  LauncherMaintenanceProfileId,
  LauncherComponentState,
  LauncherControlResponse,
  LauncherOperation,
  WorkbenchWindowMode,
} from "../api/types";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "../app/browserTelemetry";
import { resolveLauncherStatusPollingInterval, usePageVisibility } from "../app/pollingPolicy";
import {
  applyBeforeUnloadProjectCloseGuard,
  buildProjectWindowCloseBlockedTelemetry,
  clearControlledProjectLifecycleOperation,
  isElectronDesktopShell,
  markControlledProjectLifecycleOperation,
  projectWindowCloseGuardMessage,
  shouldArmBrowserProjectCloseGuard,
  shouldBlockProjectWindowClose,
} from "../app/projectCloseGuard";
import { useStableBeforeUnload } from "../app/useStableBeforeUnload";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VDenseOpsPage, VStateSurface, VTooltip } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import { launcherRouteStyles as styles } from "./LauncherRoute.styles";

/** T4: secondary launcher panels load as route packs — keep lifecycle shell first. */
import { LauncherBranchInstancesPanel } from "./LauncherBranchInstancesPanel";
import { buildAllInstanceMonitorRows } from "./LauncherProcessMonitor.binding";
import { LauncherProcessMonitorPanel, type LauncherProcessRow } from "./LauncherProcessMonitorPanel";

const LauncherStartupSettingsPanel = lazy(() =>
  import("./LauncherStartupSettingsPanel").then((module) => ({ default: module.LauncherStartupSettingsPanel })),
);
const LauncherProjectMaintenancePanel = lazy(() =>
  import("./LauncherProjectMaintenancePanel").then((module) => ({ default: module.LauncherProjectMaintenancePanel })),
);
const LauncherDeveloperModePanel = lazy(() =>
  import("./LauncherDeveloperModePanel").then((module) => ({ default: module.LauncherDeveloperModePanel })),
);
const LauncherDiagnosticsPanel = lazy(() =>
  import("./LauncherDiagnosticsPanel").then((module) => ({ default: module.LauncherDiagnosticsPanel })),
);

const LAUNCHER_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.launcher;

type LauncherNotice = {
  tone: "neutral" | "success" | "warning" | "error";
  text: string;
  source?: "lifecycle-control" | "supervisor" | "startup-settings" | "window-mode";
};

type LauncherTrackedCommand = {
  commandId: string;
  operation: LauncherOperation;
};

type LauncherGuardianResponsibility = {
  id: string;
  owner: string;
  adapter: string;
  status: string;
  detail: string;
  blocking?: boolean;
  impact?: string;
  userMessage?: string;
};

type LauncherControlPlaneCommand = {
  commandId: string;
  type: string;
  requestedBy: string;
  requestedAt: string;
  reason: string;
  source: string;
  noBrowser: boolean;
  stopManager: boolean;
  deferredUntilActiveWorkClear?: boolean;
  queuedBecauseActiveWork?: boolean;
  deferUntil?: string;
  activeWorkDeferCount?: number;
  lastActiveWorkCount?: number;
};

type LauncherControlPlaneResult = {
  commandId: string;
  ok: boolean;
  completed: boolean;
  message: string;
  errorType: string;
  stateVersion: number;
};

type LauncherControlPlaneEvent = {
  type: string;
  at: string;
  commandId: string;
  commandType: string;
  ok: boolean | null;
  message: string;
};

type LauncherStatusWithGuardian = Awaited<ReturnType<typeof getLauncherStatus>> & {
  controlPlaneEvidence?: {
    schemaVersion: number;
    state: {
      stateVersion: number;
      runtimeState: string;
      managerPid: number;
      updatedAt: string;
      activeCommand: LauncherControlPlaneCommand;
    };
    queue: {
      pendingCount: number;
      processingCount: number;
      pending: LauncherControlPlaneCommand[];
      processing: LauncherControlPlaneCommand[];
    };
    results: {
      recent: LauncherControlPlaneResult[];
    };
    events: {
      recent: LauncherControlPlaneEvent[];
    };
    recovery: {
      active: boolean;
      commandId: string;
      commandType: string;
      recoveredAt: string;
      resultMessage: string;
      resultOk: boolean | null;
      statusLine: string;
    };
    restartQueue?: {
      pending: boolean;
      pendingCount: number;
      active: boolean;
      commandId: string;
      deferUntil: string;
      activeWorkDeferCount: number;
      lastActiveWorkCount: number;
      statusLine: string;
    };
  };
  guardianAdapter?: {
    schemaVersion: number;
    mode: string;
    targetMode: string;
    statusLine: string;
    ownedCount: number;
    adapterCount: number;
    supervisor?: {
      pid: number;
      alive: boolean;
      status: string;
      blocking?: boolean;
      impact?: string;
      userMessage?: string;
      stdoutPath: string;
      stderrPath: string;
      runtimeSceneId: string;
      runtimeSceneDir: string;
      detail: string;
    };
    responsibilities: LauncherGuardianResponsibility[];
  };
};

type StatusRow = LauncherProcessRow;

type LauncherCopy = {
  controlLimited: string;
  controlLimitedDetail: string;
  controlReady: string;
  controlReadyDetail: string;
  lifecycleClosed: string;
  lifecycleClosedDetail: string;
  lifecycleFailed: string;
  lifecycleFailedDetail: string;
  lifecycleReadingLimited: string;
  lifecycleReadingLimitedDetail: string;
  lifecycleRestarting: string;
  lifecycleRestartingDetail: string;
  lifecyclePartial: string;
  lifecyclePartialDetail: string;
  lifecycleRunning: string;
  lifecycleRunningDetail: string;
  lifecycleStarting: string;
  lifecycleStartingDetail: string;
  lifecycleStatus: string;
  lifecycleStopping: string;
  lifecycleStoppingDetail: string;
  lifecycleUnknown: string;
  lifecycleUnknownDetail: string;
  lifecycleControls: string;
  openWorkbenchSummary: string;
  safeToUse: string;
  startProjectSummary: string;
  stopDisabledClosed: string;
  stopDisabledInFlight: string;
  restartDisabledClosed: string;
  forceStop: string;
  forceStopHint: string;
  forceStopDisabledClosed: string;
  forceStopDisabledInFlight: string;
  powerMenu: string;
  stopWorkbench: string;
  restart: string;
  useCheckAction: string;
  useStartAction: string;
  useWaitAction: string;
  windowMode: string;
  windowModeFullscreen: string;
  windowModeWindowed: string;
  windowModeSaved: string;
  windowModeRestartRequired: string;
  windowModeEnvOverride: string;
  startupSettings: string;
  expandSettings: string;
  collapseSettings: string;
  startupSettingsSaved: string;
  runtimeProfile: string;
  preflightDoctor: string;
  requireVenv: string;
  launcherControlPort: string;
  launcherControlPortHint: string;
  backendPort: string;
  backendPortHint: string;
  frontendPort: string;
  frontendPortHint: string;
  windowSize: string;
  windowSizeAuto: string;
  windowSizeEnvOverride: string;
  interfaceLanguage: string;
  languageZh: string;
  languageEn: string;
  saveStartupSettings: string;
  portOverride: string;
  invalidPort: string;
  userGuide: string;
  userGuideReady: string;
  userGuideReadyDetail: string;
  userGuideBlocked: string;
  userGuideBlockedDetail: string;
  userGuideClosed: string;
  userGuideClosedDetail: string;
  userGuidePartial: string;
  userGuidePartialDetail: string;
  userGuideChanging: string;
  userGuideChangingDetail: string;
  userGuideProblem: string;
  userGuideProblemDetail: string;
  actionsLocked: string;
  actionsAvailable: string;
  actionsStartOnly: string;
  diagnosticsCollapsedHint: string;
  developerModeTitle: string;
  developerModeHint: string;
  developerModeCurrentState: string;
  developerModeLastUpdated: string;
  developerModeOn: string;
  developerModeOff: string;
  developerModeEnable: string;
  developerModeDisable: string;
  developerModeResetSandbox: string;
  developerModeSandbox: string;
  developerModeControlled: string;
  developerModeSettingsReadonly: string;
  developerModeUpdated: string;
  maintenanceTitle: string;
  maintenanceHint: string;
  maintenanceProfile: string;
  maintenanceCleanStart: string;
  maintenanceFactoryRuntime: string;
  maintenanceCustom: string;
  maintenancePreview: string;
  maintenanceApply: string;
  maintenancePlanReady: string;
  maintenancePlanEmpty: string;
  maintenancePlanMissingForProfile: string;
  maintenancePlanProfileMismatch: string;
  maintenanceTargets: string;
  maintenanceEstimated: string;
  maintenanceActiveWorkPolicy: string;
  maintenanceRequiresConfirm: string;
  maintenanceApplied: string;
  maintenanceLoading: string;
  developerModeNoiseOverview: string;
  developerModeNoiseLoading: string;
  developerModeRefreshNoise: string;
  developerModeAction: string;
  cleanupQuickClean: string;
  cleanupQuickCleanDetail: string;
  cleanupDbCompact: string;
  cleanupDbCompactDetail: string;
  cleanupWorktreeCleanup: string;
  cleanupWorktreeCleanupDetail: string;
  cleanupPreview: string;
  cleanupApply: string;
  cleanupPlanReady: string;
  cleanupPlanEmpty: string;
  cleanupTargets: string;
  cleanupEstimated: string;
  cleanupSkipped: string;
  cleanupRequiresConfirm: string;
  cleanupDisabledOff: string;
  cleanupApplied: string;
  technicalDetailAvailable: string;
  workbenchNotReadySummary: string;
  workbenchWindowClosedSummary: string;
  backendUnavailableSummary: string;
  backendPortUnavailableSummary: string;
  lifecycleEvidenceIncomplete: string;
  processMonitor: string;
  processMonitorHint: string;
  branchInstances: string;
  branchInstancesHint: string;
  branchColumn: string;
  instanceState: string;
  instanceKind: string;
  instancePath: string;
  currentInstance: string;
  legacyCheckout: string;
  retiredCheckout: string;
  notCheckedOut: string;
  selectedInstance: string;
  instanceNoObservation: string;
  ownership: string;
  residualCount: string;
  residualProcess: string;
  ownedProcess: string;
  leftoverProcess: string;
  controlSurface: string;
  advancedFold: string;
  advancedFoldHint: string;
  effectiveValue: string;
};

type LifecycleDisplay = {
  state: "running" | "partial" | "closed" | "starting" | "stopping" | "restarting" | "failed" | "limited" | "unknown";
  label: string;
  detail: string;
  tone: "neutral" | "success" | "warning" | "error";
};

const COMPONENT_ORDER = new Map([
  ["backend", 0],
  ["frontend", 1],
  ["browser", 2],
]);

function sortComponents(components: LauncherComponentState[]) {
  return [...components].sort((left, right) => {
    const leftOrder = COMPONENT_ORDER.get(left.id) ?? 99;
    const rightOrder = COMPONENT_ORDER.get(right.id) ?? 99;
    if (leftOrder !== rightOrder) {
      return leftOrder - rightOrder;
    }
    return left.id.localeCompare(right.id);
  });
}

function compactDate(value: string, locale: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function stateTone(state: string, ok = true) {
  const normalized = state.trim().toLowerCase();
  if (!ok || normalized.includes("fail") || normalized.includes("error") || normalized.includes("conflict")) {
    return "error";
  }
  if (normalized.includes("run") || normalized.includes("ready") || normalized.includes("ok") || normalized.includes("healthy")) {
    return "success";
  }
  if (normalized.includes("non_blocking")) {
    return "neutral";
  }
  if (normalized.includes("start") || normalized.includes("stop") || normalized.includes("queue") || normalized.includes("restart") || normalized.includes("partial")) {
    return "warning";
  }
  return "neutral";
}

function boolText(value: boolean | undefined, yes: string, no: string) {
  return value ? yes : no;
}

function displayPid(value: unknown) {
  const pid = Number(value || 0);
  return Number.isFinite(pid) && pid > 0 ? String(pid) : "-";
}

function displayPort(value: unknown) {
  const port = Number(value || 0);
  return Number.isFinite(port) && port > 0 ? String(port) : "-";
}

function residualKindLabel(kind: string, lang: "zh" | "en") {
  const labels: Record<string, { zh: string; en: string }> = {
    unmanaged_workbench: { zh: "未托管工作台", en: "Unmanaged workbench" },
    unmanaged_frontend_dev_server: { zh: "未托管前端开发服务", en: "Unmanaged frontend dev server" },
  };
  return labels[kind]?.[lang] ?? kind;
}

function normalizeMaintenanceProfileId(value: unknown): LauncherMaintenanceProfileId | null {
  const profileId = String(value || "").trim();
  if (profileId === "custom" || profileId === "clean_start" || profileId === "factory_runtime") {
    return profileId;
  }
  return null;
}

function humanState(value: string | undefined, lang: "zh" | "en") {
  const raw = String(value || "").trim();
  const normalized = raw.toLowerCase();
  const zh: Record<string, string> = {
    alive: "运行中",
    active: "已接管",
    closed: "已关闭",
    failed: "异常",
    healthy: "健康",
    idle: "空闲",
    managed: "已托管",
    open: "已打开",
    processing: "执行中",
    partial: "部分运行",
    queued: "排队中",
    ready: "就绪",
    running: "运行中",
    steady: "稳定",
    stopped: "已停止",
    non_blocking: "非阻塞",
  };
  const en: Record<string, string> = {
    alive: "Running",
    active: "Owned",
    closed: "Closed",
    failed: "Failed",
    healthy: "Healthy",
    idle: "Idle",
    managed: "Managed",
    open: "Open",
    processing: "Processing",
    partial: "Partial",
    queued: "Queued",
    ready: "Ready",
    running: "Running",
    steady: "Stable",
    stopped: "Stopped",
    non_blocking: "Non-blocking",
  };
  return (lang === "zh" ? zh : en)[normalized] || raw || "-";
}

function humanCommandType(value: string | undefined, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    close_workbench: "关闭项目",
    force_close_workbench: "强制关闭项目",
    open_workbench: "打开项目",
    restart_workbench: "重启项目",
    start_supervised_run: "启动监督运行",
  };
  const en: Record<string, string> = {
    close_workbench: "Close project",
    force_close_workbench: "Force close project",
    open_workbench: "Open project",
    restart_workbench: "Restart project",
    start_supervised_run: "Start supervised run",
  };
  return (lang === "zh" ? zh : en)[normalized] || normalized || "-";
}

function isLauncherStatusNetworkDisconnect(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /failed to fetch|network request failed|networkerror|load failed/i.test(message);
}

function isControlTokenError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /missing or invalid web control token|control token request failed|control token response was empty/i.test(message);
}

function resultMessage(result: LauncherControlPlaneResult, operation: LauncherOperation, lang: "zh" | "en") {
  const commandType = operation === "force-stop"
    ? "force_close_workbench"
    : operation === "restart"
      ? "restart_workbench"
      : operation === "start"
        ? "open_workbench"
        : "close_workbench";
  const fallback = lang === "zh"
    ? `${humanCommandType(commandType, lang)}${result.ok ? "已完成" : "失败"}`
    : `${humanCommandType(commandType, lang)} ${result.ok ? "completed" : "failed"}`;
  const raw = String(result.message || result.errorType || fallback).trim();
  if (result.ok) {
    return raw || fallback;
  }
  const lower = raw.toLowerCase();
  if (lower.includes("restart preflight failed before closing the workbench")) {
    return lang === "zh"
      ? "重启前检查失败，工作台未被关闭。请展开高级诊断查看依赖或构建错误。"
      : "Restart preflight failed before closing the workbench. Expand diagnostics for dependency or build errors.";
  }
  if (lower.includes("typescript") && lower.includes("tsc")) {
    return lang === "zh"
      ? "前端 TypeScript 工具链不完整，Launcher 会尝试重新安装依赖。"
      : "The frontend TypeScript toolchain is incomplete; Launcher will try to reinstall dependencies.";
  }
  return raw.length > 180 ? `${raw.slice(0, 177)}...` : raw;
}

function launcherControlNoticeMessage(
  response: LauncherControlResponse,
  operation: LauncherOperation,
  lang: "zh" | "en",
  fallback: string,
) {
  const base = String(response.message || fallback || "").trim() || fallback;
  if (operation !== "force-stop") {
    return base;
  }
  const activeWorkRuns = response.activeWorkRuns ?? [];
  const activeWorkCount = typeof response.activeWorkCount === "number"
    ? response.activeWorkCount
    : activeWorkRuns.length;
  if (activeWorkCount <= 0) {
    return base;
  }
  const kinds = Array.from(new Set(activeWorkRuns.map((item) => String(item.kind || "").trim()).filter(Boolean)));
  if (lang === "en") {
    const suffix = kinds.length ? ` (${kinds.join(", ")})` : "";
    return `${base} Requested interruption for ${activeWorkCount} active task${activeWorkCount === 1 ? "" : "s"}${suffix}.`;
  }
  const suffix = kinds.length ? `（${kinds.join("、")}）` : "";
  return `${base} 已请求中断 ${activeWorkCount} 个活动任务${suffix}。`;
}

function launcherOperationSettledByStatus(
  operation: LauncherOperation,
  state: { projectIsOpen: boolean; projectIsPartial: boolean; projectIsClosed: boolean },
) {
  if (operation === "stop" || operation === "force-stop") {
    return state.projectIsClosed;
  }
  if (operation === "start" || operation === "restart") {
    return state.projectIsOpen || state.projectIsPartial;
  }
  return false;
}

function postLauncherLifecycleControlTelemetry(
  operation: LauncherOperation,
  status: "requested" | "accepted" | "rejected" | "request_failed",
  fields: Record<string, unknown> = {},
) {
  const failed = status === "request_failed";
  const rejected = status === "rejected";
  postBrowserTelemetry(
    {
      phase: "launcher_lifecycle_control",
      eventCode: `launcher.lifecycle_control.${status}`,
      message: `Launcher lifecycle control ${status}.`,
      level: failed ? "error" : rejected ? "warning" : "info",
      fields: {
        ...collectBrowserPageSnapshot(),
        source: "launcher_route",
        operation,
        status,
        ...fields,
      },
    },
    { preferBeacon: true },
  );
}

function launcherLifecycleResponseTelemetryFields(response: LauncherControlResponse): Record<string, unknown> {
  const responseWithCompletion = response as LauncherControlResponse & { completed?: boolean };
  return {
    accepted: Boolean(response.accepted),
    completed: Boolean(responseWithCompletion.completed),
    commandId: String(response.commandId || ""),
    launcherMode: String(response.launcherMode || ""),
    responseOperation: String(response.operation || ""),
    responseMessage: String(response.message || ""),
  };
}

function workbenchWindowModeLabel(mode: string | undefined, copy: LauncherCopy) {
  return String(mode || "").toLowerCase() === "windowed" ? copy.windowModeWindowed : copy.windowModeFullscreen;
}

function includesAny(value: string, needles: string[]) {
  return needles.some((needle) => value.includes(needle));
}

function summarizeLauncherMessage(value: string | undefined, copy: LauncherCopy, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const lower = text.toLowerCase();
  const hasWorkbenchNotReady = lower.includes("workbench is not ready");
  const observedClosed = /observedstate=closed/i.test(text);
  const backendUnhealthy = /backendhealthy=false/i.test(text) || /backendobserved=false/i.test(text);
  const backendPortClosed = /backendportlistening=false/i.test(text);
  if (hasWorkbenchNotReady && backendUnhealthy) {
    return backendPortClosed ? copy.backendPortUnavailableSummary : copy.backendUnavailableSummary;
  }
  if (hasWorkbenchNotReady && observedClosed) {
    return copy.workbenchWindowClosedSummary;
  }
  if (hasWorkbenchNotReady) {
    return copy.workbenchNotReadySummary;
  }
  if (/observedstate=|backendhealthy=|backendobserved=|backendportlistening=/i.test(text)) {
    return copy.lifecycleEvidenceIncomplete;
  }
  const firstSentence = text.match(/^[^.!?。！？]+[.!?。！？]?/)?.[0]?.trim() || text;
  const limit = lang === "zh" ? 56 : 88;
  return firstSentence.length > limit ? `${firstSentence.slice(0, limit - 1)}...` : firstSentence;
}

function resolveLifecycleDisplay(
  status: LauncherStatusWithGuardian | undefined,
  copy: LauncherCopy,
  options: { disconnected: boolean; controlLimited: boolean; starting: boolean },
): LifecycleDisplay {
  if (options.starting) {
    return {
      state: "starting",
      label: copy.lifecycleStarting,
      detail: copy.lifecycleStartingDetail,
      tone: "warning",
    };
  }
  if (options.disconnected) {
    return {
      state: "closed",
      label: copy.lifecycleClosed,
      detail: copy.lifecycleClosedDetail,
      tone: "neutral",
    };
  }
  if (!status) {
    return {
      state: options.controlLimited ? "limited" : "unknown",
      label: options.controlLimited ? copy.lifecycleReadingLimited : copy.lifecycleUnknown,
      detail: options.controlLimited ? copy.lifecycleReadingLimitedDetail : copy.lifecycleUnknownDetail,
      tone: options.controlLimited ? "warning" : "neutral",
    };
  }

  const bundle = status.projectBundle;
  const evidence = status.controlPlaneEvidence;
  const restartQueue = evidence?.restartQueue;
  const desired = String(bundle?.desiredState || "").toLowerCase();
  const observed = String(bundle?.observedState || "").toLowerCase();
  const phase = String(bundle?.phase || status.launcher.phase || "").toLowerCase();
  const overall = String(status.lifecycleProof?.overallState || bundle?.overallState || "").toLowerCase();
  const lifecycleConsistency = String(bundle?.lifecycleConsistency || "").toLowerCase();
  const browserMissing = observed === "partial" || lifecycleConsistency === "browser_missing";
  const commandType = String(evidence?.state.activeCommand?.type || "").toLowerCase();
  const recoveryType = String(evidence?.recovery?.commandType || "").toLowerCase();
  const activeLifecycleCommand = commandType || (evidence?.recovery?.active ? recoveryType : "");

  if (restartQueue?.active) {
    return {
      state: "restarting",
      label: copy.lifecycleRestarting,
      detail: restartQueue.statusLine || copy.lifecycleRestartingDetail,
      tone: "warning",
    };
  }
  if (includesAny(overall, ["fail", "error", "conflict"]) || includesAny(phase, ["fail", "error", "conflict"])) {
    return {
      state: "failed",
      label: copy.lifecycleFailed,
      detail: bundle?.failureMessage || bundle?.statusLine || status.lifecycleProof?.summary || copy.lifecycleFailedDetail,
      tone: "error",
    };
  }
  if (activeLifecycleCommand.includes("restart") || includesAny(phase, ["restart"])) {
    return {
      state: "restarting",
      label: copy.lifecycleRestarting,
      detail: evidence?.recovery?.statusLine || bundle?.statusLine || copy.lifecycleRestartingDetail,
      tone: "warning",
    };
  }
  if (activeLifecycleCommand.includes("open") || includesAny(phase, ["start", "open", "queue", "processing"])) {
    return {
      state: "starting",
      label: copy.lifecycleStarting,
      detail: bundle?.statusLine || status.lifecycleProof?.summary || copy.lifecycleStartingDetail,
      tone: "warning",
    };
  }
  if (activeLifecycleCommand.includes("close") || includesAny(phase, ["stop", "close", "shutdown"])) {
    return {
      state: "stopping",
      label: copy.lifecycleStopping,
      detail: bundle?.statusLine || status.lifecycleProof?.summary || copy.lifecycleStoppingDetail,
      tone: "warning",
    };
  }
  if (browserMissing) {
    return {
      state: "partial",
      label: copy.lifecyclePartial,
      detail: bundle?.statusLine || status.lifecycleProof?.summary || copy.lifecyclePartialDetail,
      tone: "warning",
    };
  }
  if (desired === "open" && observed === "open") {
    return {
      state: "running",
      label: copy.lifecycleRunning,
      detail: status.lifecycleProof?.summary || bundle?.statusLine || copy.lifecycleRunningDetail,
      tone: "success",
    };
  }
  if (desired === "closed" && observed === "closed") {
    return {
      state: "closed",
      label: copy.lifecycleClosed,
      detail: bundle?.statusLine || copy.lifecycleClosedDetail,
      tone: "neutral",
    };
  }

  return {
    state: "unknown",
    label: copy.lifecycleUnknown,
    detail: bundle?.statusLine || status.lifecycleProof?.summary || copy.lifecycleUnknownDetail,
    tone: "warning",
  };
}

function componentLabel(id: string, lang: "zh" | "en") {
  const zh: Record<string, string> = {
    backend: "后端服务",
    browser: "工作台窗口",
    frontend: "前端资源",
    project: "项目整体",
    runtime_manager: "生命周期管理",
    supervisor: "后台守护检查",
  };
  const en: Record<string, string> = {
    backend: "Backend service",
    browser: "Workbench window",
    frontend: "Frontend assets",
    project: "Project bundle",
    runtime_manager: "Lifecycle manager",
    supervisor: "Background monitor",
  };
  return (lang === "zh" ? zh : en)[id] || id;
}

function responsibilityLabel(id: string, lang: "zh" | "en") {
  const zh: Record<string, string> = {
    backend_process: "后端服务",
    browser_window: "工作台窗口",
    desktop_supervisor: "后台守护检查",
    project_bundle_lifecycle: "项目生命周期",
    runtime_manager_daemon: "生命周期管理器",
    runtime_scene_logging: "运行证据",
  };
  const en: Record<string, string> = {
    backend_process: "Backend service",
    browser_window: "Workbench window",
    desktop_supervisor: "Background monitor",
    project_bundle_lifecycle: "Project lifecycle",
    runtime_manager_daemon: "Lifecycle manager",
    runtime_scene_logging: "Runtime evidence",
  };
  return (lang === "zh" ? zh : en)[id] || id;
}

function responsibilityOwner(owner: string, lang: "zh" | "en") {
  const zh: Record<string, string> = {
    launcher_api: "Launcher",
    powershell_launcher: "启动脚本",
    runtime_manager: "生命周期管理器",
    runtime_scene_service: "日志系统",
  };
  const en: Record<string, string> = {
    launcher_api: "Launcher",
    powershell_launcher: "Launch script",
    runtime_manager: "Lifecycle manager",
    runtime_scene_service: "Log system",
  };
  return (lang === "zh" ? zh : en)[owner] || owner || "-";
}

function responsibilityDetail(item: LauncherGuardianResponsibility, lang: "zh" | "en") {
  if (item.userMessage) {
    return item.userMessage;
  }
  const zh: Record<string, string> = {
    backend_process: "后端进程纳入项目生命周期维护。",
    browser_window: "工作台窗口纳入项目生命周期维护。",
    desktop_supervisor: "后台守护检查未运行时，不影响当前项目使用。",
    project_bundle_lifecycle: "启动、停止、重启统一通过 Launcher 入口处理。",
    runtime_manager_daemon: "负责排队并执行生命周期命令。",
    runtime_scene_logging: "运行过程持续写入 runtime scene 证据。",
  };
  const en: Record<string, string> = {
    backend_process: "Backend process is maintained as part of the project lifecycle.",
    browser_window: "Workbench window is maintained as part of the project lifecycle.",
    desktop_supervisor: "When stopped, the background monitor does not block current project use.",
    project_bundle_lifecycle: "Start, stop, and restart are handled through Launcher.",
    runtime_manager_daemon: "Queues and executes lifecycle commands.",
    runtime_scene_logging: "Runtime scene evidence is written continuously.",
  };
  return (lang === "zh" ? zh : en)[item.id] || item.detail || "-";
}

function responsibilityDisplayState(item: LauncherGuardianResponsibility, lang: "zh" | "en") {
  if (item.blocking === false && item.impact) {
    return humanState(item.impact, lang);
  }
  return humanState(item.status, lang);
}

function responsibilityToneState(item: LauncherGuardianResponsibility) {
  if (item.blocking === false && item.impact) {
    return item.impact;
  }
  return item.status;
}

function isControlPlaneIdle(evidence: LauncherStatusWithGuardian["controlPlaneEvidence"] | undefined): boolean {
  if (!evidence) {
    return true;
  }
  return (
    !evidence.state.activeCommand?.commandId &&
    evidence.queue.pendingCount === 0 &&
    evidence.queue.processingCount === 0 &&
    !evidence.restartQueue?.active &&
    !evidence.restartQueue?.pending
  );
}

function controlPlaneHasCommandType(
  evidence: LauncherStatusWithGuardian["controlPlaneEvidence"] | undefined,
  commandTypes: readonly string[],
): boolean {
  if (!evidence) {
    return false;
  }
  const wanted = new Set(commandTypes.map((item) => item.trim()).filter(Boolean));
  if (!wanted.size) {
    return false;
  }
  const activeType = String(evidence.state.activeCommand?.type || "").trim();
  if (activeType && wanted.has(activeType)) {
    return true;
  }
  return [...(evidence.queue.pending ?? []), ...(evidence.queue.processing ?? [])].some((command) => {
    const commandType = String(command.type || "").trim();
    return commandType !== "" && wanted.has(commandType);
  });
}

function launcherStatusCommandActive(status: LauncherStatusWithGuardian | undefined): boolean {
  const evidence = status?.controlPlaneEvidence;
  if (!evidence) {
    return false;
  }
  return Boolean(
    evidence.state.activeCommand?.commandId
    || evidence.queue.pendingCount > 0
    || evidence.queue.processingCount > 0
    || evidence.restartQueue?.active
    || evidence.restartQueue?.pending
    || evidence.recovery?.active,
  );
}

function launcherStatusLifecycleChanging(status: LauncherStatusWithGuardian | undefined): boolean {
  const bundle = status?.projectBundle;
  const phase = String(bundle?.phase || status?.launcher.phase || "").toLowerCase();
  const overall = String(status?.lifecycleProof?.overallState || bundle?.overallState || "").toLowerCase();
  const desired = String(bundle?.desiredState || "").toLowerCase();
  const observed = String(bundle?.observedState || "").toLowerCase();
  return (
    includesAny(phase, ["start", "open", "queue", "processing", "stop", "close", "restart"])
    || includesAny(overall, ["starting", "closing", "stopping", "restarting"])
    || (desired !== "" && observed !== "" && desired !== observed)
  );
}

export function LauncherRoute() {
  const { lang } = useShellI18n({ configEnabled: false });
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const { request: requestLifecycle } = useWorkbenchLifecycleActions("launcher_route");
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const copy = lang === "zh"
    ? {
        eyebrow: "Launcher",
        title: "项目启动器",
        subtitle: "分支实例是本页主内容；启动、停止和电源由 Electron 托盘管理",
        refresh: "刷新",
        start: "启动",
        stop: "停止",
        forceStop: "强制停止",
        powerMenu: "工作台电源操作",
        restart: "重启工作台",
        stopWorkbench: "停止工作台",
        open: "打开",
        lifecycleControls: "生命周期控制",
        startDisabled: "启动暂不可用",
        startDisabledBusy: "正在处理上一个生命周期操作",
        startDisabledRunning: "项目已在运行",
        startDisabledChanging: "项目正在切换",
        lifecycleActionDisabledActiveWork: "有进行中的任务，无法停止或重启 Vibelution",
        stopDisabledClosed: "项目已经关闭",
        stopDisabledInFlight: "关闭命令已经在处理中",
        restartDisabledClosed: "项目已经关闭；请使用启动",
        forceStopDisabledClosed: "工作台已经关闭",
        forceStopDisabledInFlight: "关闭命令已经在处理中",
        forceStopHint: "仅在普通停止无法收口时使用，会请求中断活动任务。",
        projectStatus: "项目状态",
        launcherStatus: "Launcher 维护",
        lifecycleStatus: "生命周期",
        activeWork: "任务保护",
        activeTasks: "进行中任务",
        noActiveWork: "无进行中任务",
        restartProtected: "有任务，禁止重启",
        restartClear: "可安全重启",
        userAction: "下一步",
        projectRunning: "项目正在运行",
        projectClosed: "项目已关闭",
        projectChanging: "项目正在切换",
        projectProblem: "项目需要处理",
        launcherMaintaining: "正在维护",
        launcherOffline: "未连接",
        lifecycleRunning: "运行中",
        lifecycleRunningDetail: "后端、前端和工作台窗口已对齐，项目可以继续使用。",
        lifecyclePartial: "部分运行",
        lifecyclePartialDetail: "后端仍在运行，但工作台窗口未打开；可以重新打开或停止项目。",
        lifecycleClosed: "已关闭",
        lifecycleClosedDetail: "项目生命周期已停止；需要时从这里重新启动。",
        lifecycleStarting: "启动中",
        lifecycleStartingDetail: "Launcher 正在启动后端、前端资源和工作台窗口。",
        lifecycleStopping: "停止中",
        lifecycleStoppingDetail: "Launcher 正在关闭项目生命周期，请等待收口完成。",
        lifecycleRestarting: "重启中",
        lifecycleRestartingDetail: "Launcher 正在执行重启，完成后会回到运行中。",
        lifecycleFailed: "异常",
        lifecycleFailedDetail: "生命周期证据显示项目需要处理，请查看诊断。",
        lifecycleUnknown: "状态待确认",
        lifecycleUnknownDetail: "还没有拿到足够证据判断项目生命周期。",
        lifecycleReadingLimited: "状态读取受限",
        lifecycleReadingLimitedDetail: "项目可能仍在运行，但 Launcher 状态接口需要重新取得控制权限。",
        controlReady: "控制可用",
        controlReadyDetail: "控制 token 正常，启动、停止和重启按钮可按权限提交。",
        controlLimited: "控制受限",
        controlLimitedDetail: "当前缺少有效控制 token；请刷新后再执行启动、停止或重启。",
        safeToUse: "可以打开工作台继续使用",
        useOpenAction: "打开工作台",
        useStartAction: "启动项目",
        useWaitAction: "等待当前操作完成",
        useCheckAction: "查看诊断",
        lifecycle: "生命周期",
        keyStatus: "托管进程",
        matrix: "进程监控",
        processMonitor: "进程监控",
        processMonitorHint: "托管进程与残留子进程",
        branchInstances: "分支实例",
        branchInstancesHint: "一行一个分支：状态、后端、窗口和操作",
        branchColumn: "分支",
        instanceState: "状态",
        instanceKind: "类型",
        instancePath: "路径",
        currentInstance: "当前 main",
        legacyCheckout: "旧目录",
        retiredCheckout: "退役",
        notCheckedOut: "未打开",
        selectedInstance: "选中实例",
        instanceNoObservation: "该实例没有运行时观察，进程表只描述当前 Launcher 项目。",
        ownership: "归属",
        residualCount: "残留进程",
        residualProcess: "残留",
        ownedProcess: "托管",
        leftoverProcess: "残留子进程",
        controlSurface: "Launcher 控制面",
        advancedFold: "高级",
        advancedFoldHint: "维护恢复、开发沙盒和诊断",
        effectiveValue: "生效",
        controlPlane: "维护范围",
        controlEvidence: "证据",
        guardian: "托管明细",
        advancedDiagnostics: "高级诊断",
        queueAndEvents: "命令与事件",
        recovery: "恢复记录",
        recoveryIdle: "无恢复动作",
        maintenanceDetails: "维护细节",
        diagnostics: "诊断详情",
        activeCommand: "当前命令",
        recentResults: "最近结果",
        recentEvents: "最近事件",
        desired: "目标",
        observed: "实际",
        phase: "稳定性",
        overall: "可用性",
        adapter: "适配器",
        independent: "独立",
        nextPhase: "下一阶段",
        stable: "稳定控制面",
        pid: "PID",
        state: "状态",
        detail: "说明",
        unit: "单元",
        mode: "职责",
        port: "端口",
        listening: "监听",
        owner: "占用 PID",
        alive: "存活",
        healthy: "健康",
        yes: "是",
        no: "否",
        unavailable: "不可用",
        loadFailed: "Launcher 状态读取失败",
        stoppedStatusUnavailable: "工作台已关闭，Launcher 后端连接已断开。重新启动后会恢复状态。",
        stoppedProjectDetail: "后端不可达，当前页面只保留旧前端壳；请从 Launcher 重新启动项目。",
        stoppedBackendDetail: "后端连接已断开，接口和状态刷新不可用。",
        stoppedFrontendDetail: "当前看到的是旧前端页面，不代表项目仍在运行。",
        stoppedBrowserDetail: "工作台窗口或后端已停止，旧窗口可关闭。",
        loading: "正在读取 Launcher 状态",
        commandDone: "命令已提交",
        reattachSupervisor: "检查维护",
        targetMode: "内部目标",
        owned: "维护项",
        legacyAdapter: "记录项",
        supervisor: "守护检查",
        stdout: "stdout",
        stderr: "stderr",
        scene: "现场",
        pending: "待执行",
        processing: "执行中",
        queue: "队列",
        reason: "原因",
        source: "来源",
        requestTrigger: "触发入口",
        requestEndpoint: "请求路径",
        transition: "转换",
        proof: "证明",
        schema: "schema",
        advancedDetails: "技术细节",
        notBlocking: "不影响项目使用",
        maintenanceScopeSummary: "Launcher 正在维护项目启动、停止、重启、后端、窗口和日志证据。",
        activeWorkSummary: "有任务运行时，Launcher 会拒绝停止或重启，避免打断会话或进化任务。",
        noActiveWorkSummary: "当前没有进行中的项目任务，生命周期操作不会打断运行任务。",
        openWorkbenchSummary: "工作台已就绪，可继续开发或查看页面。",
        startProjectSummary: "项目未运行时，从这里统一启动前后端和窗口。",
        waitOperationSummary: "Launcher 正在处理生命周期命令，请等待状态稳定。",
        checkDiagnosticsSummary: "关键状态无法确认时，展开高级诊断查看原因。",
        internalMigrationDetails: "内部迁移细节",
        windowMode: "启动窗口",
        windowModeFullscreen: "全屏",
        windowModeWindowed: "窗口化",
        windowModeSaved: "启动窗口模式已保存",
        windowModeRestartRequired: "下次启动或重启工作台生效",
        windowModeEnvOverride: "环境变量正在覆盖配置",
        startupSettings: "启动设置",
        expandSettings: "展开编辑",
        collapseSettings: "收起设置",
        startupSettingsSaved: "启动设置已保存",
        runtimeProfile: "运行档位",
        preflightDoctor: "启动前自检",
        requireVenv: "要求 .venv",
        launcherControlPort: "Launcher 端口",
        launcherControlPortHint: "本页控制面端口，不是某个分支实例的端口。",
        backendPort: "默认后端",
        backendPortHint: "启动主项目时的工作台后端默认值；分支区只在后端实际运行时显示监听端口。",
        frontendPort: "开发前端",
        frontendPortHint: "Vite 开发热更新端口。打包工作台走实例后端，不走这里。",
        windowSize: "窗口尺寸",
        windowSizeAuto: "自动",
        windowSizeEnvOverride: "窗口尺寸被环境变量覆盖",
        interfaceLanguage: "界面语言",
        languageZh: "中文",
        languageEn: "英文",
        saveStartupSettings: "保存启动设置",
        portOverride: "端口被环境变量覆盖",
        invalidPort: "端口必须是 1-65535 的整数",
        userGuide: "当前建议",
        userGuideReady: "可以继续使用",
        userGuideReadyDetail: "项目已就绪；打开工作台继续使用。需要重启前，先确认没有进行中的任务。",
        userGuideBlocked: "先等任务完成",
        userGuideBlockedDetail: "有任务正在运行，停止和重启已自动锁定，避免打断当前会话或进化任务。",
        userGuideClosed: "可以启动项目",
        userGuideClosedDetail: "项目当前关闭；点击启动会统一拉起后端、前端资源和工作台窗口。",
        userGuidePartial: "重新打开工作台",
        userGuidePartialDetail: "后端仍在运行，但工作台窗口已关闭；点击启动或打开重新拉起窗口。",
        userGuideChanging: "等待操作完成",
        userGuideChangingDetail: "Launcher 正在处理生命周期操作；完成后状态会自动刷新。",
        userGuideProblem: "需要查看诊断",
        userGuideProblemDetail: "当前状态证据不完整或异常；展开高级诊断查看最近命令和现场日志。",
        actionsLocked: "停止/重启已保护",
        actionsAvailable: "停止/重启可用",
        actionsStartOnly: "项目已关闭，仅启动可用",
        diagnosticsCollapsedHint: "排查时展开",
        developerModeTitle: "无痕开发沙盒",
        developerModeHint: "开启后 Chat/Coding、Team 和监督进化写入开发者沙盒；正式链路只读，日志会标记为调试记录。",
        developerModeCurrentState: "当前状态",
        developerModeLastUpdated: "最近保存",
        developerModeOn: "沙盒开启",
        developerModeOff: "正式模式",
        developerModeEnable: "开启沙盒",
        developerModeDisable: "关闭并清理沙盒",
        developerModeResetSandbox: "重置沙盒",
        developerModeSandbox: "当前沙盒",
        developerModeControlled: "Launcher 控制",
        developerModeSettingsReadonly: "设置页只读展示，不能在工作台设置里改动",
        developerModeUpdated: "开发者沙盒已更新",
        maintenanceTitle: "恢复初始化",
        maintenanceHint: "清理与恢复初始化由 Launcher 生成计划、校验档位和 planHash，并在执行前阻止 active work；默认保留用户会话和 Agent/Team 结构。",
        maintenanceProfile: "维护档位",
        maintenanceCleanStart: "干净启动",
        maintenanceFactoryRuntime: "恢复初始化",
        maintenanceCustom: "自选",
        maintenancePreview: "生成预览",
        maintenanceApply: "确认执行",
        maintenancePlanReady: "维护计划已就绪",
        maintenancePlanEmpty: "当前计划没有可执行目标。",
        maintenancePlanMissingForProfile: "当前档位尚未生成预览，请先生成预览。",
        maintenancePlanProfileMismatch: "当前档位与预览计划不一致，请重新生成预览。",
        maintenanceTargets: "目标",
        maintenanceEstimated: "预计释放",
        maintenanceActiveWorkPolicy: "active work 存在时阻止执行",
        maintenanceRequiresConfirm: "确认执行当前 Launcher 维护计划？执行前会再次校验档位、planId、planHash 和 active work。",
        maintenanceApplied: "Launcher 维护计划已执行",
        maintenanceLoading: "正在读取维护盘点",
        developerModeNoiseOverview: "噪声概览",
        developerModeNoiseLoading: "正在扫描噪声来源",
        developerModeRefreshNoise: "刷新概览",
        developerModeAction: "清理动作",
        cleanupQuickClean: "快速白名单清理",
        cleanupQuickCleanDetail: "仅删除缓存、构建产物和 __pycache__。",
        cleanupDbCompact: "压缩 Git 记忆 DB",
        cleanupDbCompactDetail: "只清理旧 wt-* 快照并 VACUUM，不删除提交历史。",
        cleanupWorktreeCleanup: "清理已合并 worktree",
        cleanupWorktreeCleanupDetail: "只处理干净且已并入 main 的外部 worktree。",
        cleanupPreview: "生成预览",
        cleanupApply: "确认执行",
        cleanupPlanReady: "预览计划已就绪",
        cleanupPlanEmpty: "当前计划没有可执行目标。",
        cleanupTargets: "目标",
        cleanupEstimated: "预计释放",
        cleanupSkipped: "跳过",
        cleanupRequiresConfirm: "确认执行当前开发者清理计划？执行前会再次校验 planId、planHash、目标白名单和开发者模式状态。",
        cleanupDisabledOff: "沙盒关闭时不能生成或执行开发期清理计划",
        cleanupApplied: "清理计划已执行",
        technicalDetailAvailable: "技术详情已保留在悬停提示和高级诊断里。",
        workbenchNotReadySummary: "工作台尚未就绪，建议查看关键状态。",
        workbenchWindowClosedSummary: "工作台窗口未打开，后端状态需复查。",
        backendUnavailableSummary: "后端未确认可用，先查看诊断或重新启动。",
        backendPortUnavailableSummary: "后端端口未监听，启动流程未完成。",
        lifecycleEvidenceIncomplete: "生命周期证据不完整，展开诊断查看原始状态。",
      }
    : {
        eyebrow: "Launcher",
        title: "Project Launcher",
        subtitle: "Branch instances are the main content; Electron tray owns start, stop, and power",
        refresh: "Refresh",
        start: "Start",
        stop: "Stop",
        forceStop: "Force stop",
        powerMenu: "Workbench power actions",
        restart: "Restart workbench",
        stopWorkbench: "Stop workbench",
        open: "Open",
        lifecycleControls: "Lifecycle controls",
        startDisabled: "Start is temporarily unavailable",
        startDisabledBusy: "A lifecycle command is still settling",
        startDisabledRunning: "Project is already running",
        startDisabledChanging: "Project lifecycle is changing",
        lifecycleActionDisabledActiveWork: "Active work is running; Vibelution cannot stop or restart",
        stopDisabledClosed: "Project is already closed",
        stopDisabledInFlight: "A close command is already running",
        restartDisabledClosed: "Project is already closed; use Start",
        forceStopDisabledClosed: "Workbench is already closed",
        forceStopDisabledInFlight: "A close command is already running",
        forceStopHint: "Use only when normal Stop cannot settle; active work may be interrupted.",
        projectStatus: "Project Status",
        launcherStatus: "Launcher Care",
        lifecycleStatus: "Lifecycle",
        activeWork: "Work Guard",
        activeTasks: "Active Tasks",
        noActiveWork: "No active tasks",
        restartProtected: "Blocked by work",
        restartClear: "Safe to restart",
        userAction: "Next Step",
        projectRunning: "Project is running",
        projectClosed: "Project is closed",
        projectChanging: "Project is changing",
        projectProblem: "Project needs attention",
        launcherMaintaining: "Maintaining",
        launcherOffline: "Disconnected",
        lifecycleRunning: "Running",
        lifecycleRunningDetail: "Backend, frontend, and workbench window line up; the project is usable.",
        lifecyclePartial: "Partial",
        lifecyclePartialDetail: "The backend is still running, but the workbench window is not open; reopen or stop the project.",
        lifecycleClosed: "Closed",
        lifecycleClosedDetail: "The project lifecycle is stopped; start it here when needed.",
        lifecycleStarting: "Starting",
        lifecycleStartingDetail: "Launcher is starting backend, frontend assets, and workbench window.",
        lifecycleStopping: "Stopping",
        lifecycleStoppingDetail: "Launcher is closing the project lifecycle; wait for cleanup.",
        lifecycleRestarting: "Restarting",
        lifecycleRestartingDetail: "Launcher is restarting the project and will return to running.",
        lifecycleFailed: "Problem",
        lifecycleFailedDetail: "Lifecycle evidence says the project needs attention; check diagnostics.",
        lifecycleUnknown: "Checking",
        lifecycleUnknownDetail: "There is not enough evidence yet to prove the lifecycle state.",
        lifecycleReadingLimited: "Status limited",
        lifecycleReadingLimitedDetail: "The project may still be running, but Launcher needs fresh control permission.",
        controlReady: "Control ready",
        controlReadyDetail: "Control token is available, so lifecycle buttons can submit commands.",
        controlLimited: "Control limited",
        controlLimitedDetail: "A valid control token is missing; refresh before start, stop, or restart.",
        safeToUse: "Open the workbench and keep working",
        useOpenAction: "Open workbench",
        useStartAction: "Start project",
        useWaitAction: "Wait for the current operation",
        useCheckAction: "Check diagnostics",
        lifecycle: "Lifecycle",
        keyStatus: "Managed processes",
        matrix: "Process monitor",
        processMonitor: "Process monitor",
        processMonitorHint: "Owned and leftover child processes",
        branchInstances: "Branch instances",
        branchInstancesHint: "One row per branch: status, backend, window, and actions",
        branchColumn: "Branch",
        instanceState: "State",
        instanceKind: "Kind",
        instancePath: "Path",
        currentInstance: "Current main",
        legacyCheckout: "Legacy path",
        retiredCheckout: "Retired",
        notCheckedOut: "Not checked out",
        selectedInstance: "Selected instance",
        instanceNoObservation: "This instance has no runtime observation. The process table still describes the current Launcher project.",
        ownership: "Owner",
        residualCount: "Leftover processes",
        residualProcess: "Leftover",
        ownedProcess: "Owned",
        leftoverProcess: "Leftover child process",
        controlSurface: "Launcher control plane",
        advancedFold: "Advanced",
        advancedFoldHint: "Recovery, developer sandbox, and diagnostics",
        effectiveValue: "Effective",
        controlPlane: "Maintenance Scope",
        controlEvidence: "Evidence",
        guardian: "Managed Details",
        advancedDiagnostics: "Advanced Diagnostics",
        queueAndEvents: "Commands and Events",
        recovery: "Recovery",
        recoveryIdle: "No recovery action",
        maintenanceDetails: "Maintenance Details",
        diagnostics: "Diagnostics",
        activeCommand: "Active Command",
        recentResults: "Recent Results",
        recentEvents: "Recent Events",
        desired: "Target",
        observed: "Actual",
        phase: "Stability",
        overall: "Availability",
        adapter: "Adapter",
        independent: "Independent",
        nextPhase: "Next Phase",
        stable: "Stable Control Plane",
        pid: "PID",
        state: "State",
        detail: "Notes",
        unit: "Unit",
        mode: "Role",
        port: "Port",
        listening: "Listening",
        owner: "Owner PID",
        alive: "Alive",
        healthy: "Healthy",
        yes: "Yes",
        no: "No",
        unavailable: "Unavailable",
        loadFailed: "Launcher status failed",
        stoppedStatusUnavailable: "Workbench is closed; the Launcher backend connection is no longer available. Start again to restore status.",
        stoppedProjectDetail: "The backend is unreachable; this page is only a stale frontend shell. Start the project again from Launcher.",
        stoppedBackendDetail: "The backend connection is gone, so APIs and status refresh are unavailable.",
        stoppedFrontendDetail: "This is a stale frontend page and does not mean the project is still running.",
        stoppedBrowserDetail: "The workbench window or backend has stopped; this stale window can be closed.",
        loading: "Loading Launcher status",
        commandDone: "Command submitted",
        reattachSupervisor: "Check care",
        targetMode: "Internal Target",
        owned: "Managed",
        legacyAdapter: "Recorded",
        supervisor: "Monitor",
        stdout: "stdout",
        stderr: "stderr",
        scene: "Scene",
        pending: "Pending",
        processing: "Processing",
        queue: "Queue",
        reason: "Reason",
        source: "Source",
        requestTrigger: "Trigger",
        requestEndpoint: "Request",
        transition: "Transition",
        proof: "Proof",
        schema: "schema",
        advancedDetails: "Technical details",
        notBlocking: "Not blocking project use",
        maintenanceScopeSummary: "Launcher maintains project start, stop, restart, backend, window, and runtime evidence.",
        activeWorkSummary: "When tasks are running, Launcher rejects stop and restart requests so chat or evolution work is not interrupted.",
        noActiveWorkSummary: "There are no active project tasks, so lifecycle actions will not interrupt running work.",
        openWorkbenchSummary: "Workbench is ready for development or inspection.",
        startProjectSummary: "When closed, start frontend, backend, and window from here.",
        waitOperationSummary: "Launcher is processing a lifecycle command; wait for the state to settle.",
        checkDiagnosticsSummary: "If key status is unclear, expand diagnostics for the reason.",
        internalMigrationDetails: "Internal migration details",
        windowMode: "Launch Window",
        windowModeFullscreen: "Fullscreen",
        windowModeWindowed: "Windowed",
        windowModeSaved: "Launch window mode saved",
        windowModeRestartRequired: "Takes effect on next workbench start or restart",
        windowModeEnvOverride: "Environment override is active",
        startupSettings: "Startup Settings",
        expandSettings: "Expand to edit",
        collapseSettings: "Collapse",
        startupSettingsSaved: "Startup settings saved",
        runtimeProfile: "Runtime mode",
        preflightDoctor: "Preflight doctor",
        requireVenv: "Require .venv",
        launcherControlPort: "Launcher port",
        launcherControlPortHint: "Control-plane port for this Launcher page, not a branch instance port.",
        backendPort: "Default backend",
        backendPortHint: "Default workbench backend when starting the main project. Branch rows show a port only when the backend is actually running.",
        frontendPort: "Dev frontend",
        frontendPortHint: "Vite dev-server port. Packaged workbench uses the instance backend, not this port.",
        windowSize: "Window size",
        windowSizeAuto: "Auto",
        windowSizeEnvOverride: "Window size is overridden by environment",
        interfaceLanguage: "Interface language",
        languageZh: "Chinese",
        languageEn: "English",
        saveStartupSettings: "Save startup settings",
        portOverride: "Port is overridden by environment",
        invalidPort: "Ports must be integers from 1 to 65535",
        userGuide: "Current guidance",
        userGuideReady: "Keep working",
        userGuideReadyDetail: "The project is ready. Open the workbench and continue. Before restarting, make sure no task is running.",
        userGuideBlocked: "Wait for work to finish",
        userGuideBlockedDetail: "A task is running, so stop and restart are locked to avoid interrupting chat or evolution work.",
        userGuideClosed: "Start the project",
        userGuideClosedDetail: "The project is closed. Start will bring up backend, frontend assets, and the workbench window together.",
        userGuidePartial: "Reopen the workbench",
        userGuidePartialDetail: "The backend is still running, but the workbench window is closed. Start or open will bring the window back.",
        userGuideChanging: "Wait for completion",
        userGuideChangingDetail: "Launcher is processing a lifecycle operation. The state will refresh when it settles.",
        userGuideProblem: "Check diagnostics",
        userGuideProblemDetail: "The current evidence is incomplete or abnormal. Expand diagnostics for recent commands and scene logs.",
        actionsLocked: "Stop/restart protected",
        actionsAvailable: "Stop/restart available",
        actionsStartOnly: "Project is closed; Start is the only lifecycle action",
        diagnosticsCollapsedHint: "Open when troubleshooting",
        developerModeTitle: "No-trace Dev Sandbox",
        developerModeHint: "When enabled, Chat/Coding, Team, and supervised evolution write into the developer sandbox; formal state is read-only and logs are marked debug.",
        developerModeCurrentState: "Current state",
        developerModeLastUpdated: "Last saved",
        developerModeOn: "Sandbox enabled",
        developerModeOff: "Formal mode",
        developerModeEnable: "Enable sandbox",
        developerModeDisable: "Disable and clear sandbox",
        developerModeResetSandbox: "Reset sandbox",
        developerModeSandbox: "Current sandbox",
        developerModeControlled: "Launcher controlled",
        developerModeSettingsReadonly: "Settings shows this read-only and cannot change it",
        developerModeUpdated: "Developer sandbox updated",
        maintenanceTitle: "Restore initialization",
        maintenanceHint: "Cleanup and restore initialization are planned by Launcher, validated with profile and planHash, and blocked when active work exists. The default keeps user sessions and Agent/Team structure.",
        maintenanceProfile: "Maintenance profile",
        maintenanceCleanStart: "Clean start",
        maintenanceFactoryRuntime: "Restore initialization",
        maintenanceCustom: "Custom",
        maintenancePreview: "Preview",
        maintenanceApply: "Apply",
        maintenancePlanReady: "Maintenance plan ready",
        maintenancePlanEmpty: "This profile has no executable targets.",
        maintenancePlanMissingForProfile: "Generate a preview for the selected profile first.",
        maintenancePlanProfileMismatch: "The selected profile does not match this preview plan. Generate a new preview.",
        maintenanceTargets: "targets",
        maintenanceEstimated: "Estimated",
        maintenanceActiveWorkPolicy: "Blocks execution when active work exists",
        maintenanceRequiresConfirm: "Apply this Launcher maintenance plan? Vibelution will re-check profile, planId, planHash, and active work before executing.",
        maintenanceApplied: "Launcher maintenance plan applied",
        maintenanceLoading: "Reading maintenance inventory",
        developerModeNoiseOverview: "Noise overview",
        developerModeNoiseLoading: "Scanning noise sources",
        developerModeRefreshNoise: "Refresh overview",
        developerModeAction: "Cleanup action",
        cleanupQuickClean: "Quick whitelist clean",
        cleanupQuickCleanDetail: "Deletes only caches, build artifacts, and __pycache__.",
        cleanupDbCompact: "Compact Git memory DB",
        cleanupDbCompactDetail: "Prunes old wt-* snapshots and VACUUMs without deleting commit history.",
        cleanupWorktreeCleanup: "Clean merged worktrees",
        cleanupWorktreeCleanupDetail: "Only clean external worktrees already merged into main.",
        cleanupPreview: "Preview",
        cleanupApply: "Apply",
        cleanupPlanReady: "Preview plan ready",
        cleanupPlanEmpty: "This plan has no executable targets.",
        cleanupTargets: "targets",
        cleanupEstimated: "Estimated",
        cleanupSkipped: "skipped",
        cleanupRequiresConfirm: "Apply this developer cleanup plan? Vibelution will re-check planId, planHash, whitelist targets, and developer mode before executing.",
        cleanupDisabledOff: "Sandbox must be enabled before preview or apply",
        cleanupApplied: "Cleanup plan applied",
        technicalDetailAvailable: "Technical detail is kept in hover titles and advanced diagnostics.",
        workbenchNotReadySummary: "Workbench is not ready; check key status.",
        workbenchWindowClosedSummary: "Workbench window is closed; backend status needs review.",
        backendUnavailableSummary: "Backend is not confirmed ready; check diagnostics or start again.",
        backendPortUnavailableSummary: "Backend port is not listening; startup has not completed.",
        lifecycleEvidenceIncomplete: "Lifecycle evidence is incomplete; expand diagnostics for raw state.",
      };

  const [notice, setNotice] = useState<LauncherNotice>({ tone: "neutral", text: "" });
  const [lastControlOperation, setLastControlOperation] = useState<LauncherOperation | null>(null);
  const [trackedCommand, setTrackedCommand] = useState<LauncherTrackedCommand | null>(null);
  const [selectedCleanupAction, setSelectedCleanupAction] = useState<LauncherDeveloperCleanupAction>("quick_clean");
  const [cleanupPlan, setCleanupPlan] = useState<LauncherDeveloperCleanupPlan | null>(null);
  const [maintenanceProfile, setMaintenanceProfile] = useState<LauncherMaintenanceProfileId>("clean_start");
  const [maintenancePlansByProfile, setMaintenancePlansByProfile] = useState<Partial<Record<LauncherMaintenanceProfileId, LauncherMaintenancePlan>>>({});
  const maintenancePlan = maintenancePlansByProfile[maintenanceProfile] ?? null;
  const statusQuery = useQuery({
    queryKey: queryKeys.launcherStatus(),
    queryFn: getLauncherStatus,
    refetchInterval: (query) => {
      const status = query.state.data as LauncherStatusWithGuardian | undefined;
      return resolveLauncherStatusPollingInterval(pageVisible, {
        commandActive: launcherStatusCommandActive(status),
        lifecycleChanging: launcherStatusLifecycleChanging(status),
      });
    },
    refetchIntervalInBackground: true,
  });
  const branchInstancesQuery = useQuery({
    queryKey: queryKeys.launcherBranchInstances(),
    queryFn: getLauncherBranchInstances,
    refetchInterval: pageVisible ? 20_000 : false,
  });
  const [selectedInstanceId, setSelectedInstanceId] = useState("");
  const branchItems = branchInstancesQuery.data?.items ?? [];
  const currentInstanceId = branchInstancesQuery.data?.currentId || "main";
  const selectedBranchId = branchItems.some((item) => item.id === selectedInstanceId)
    ? selectedInstanceId
    : currentInstanceId;
  const selectedBranch = branchItems.find((item) => item.id === selectedBranchId);
  const selectedIsCurrent = !selectedBranch || selectedBranch.current;
  const selectedStartable = Boolean(
    selectedBranch
    && selectedBranch.checkedOut
    && selectedBranch.kind !== "retired"
    && selectedBranch.kind !== "local_branch",
  );
  const selectedAlive = Boolean(selectedBranch?.alive);
  const developerNoiseQuery = useQuery({
    queryKey: queryKeys.launcherDeveloperNoiseOverview(),
    queryFn: getLauncherDeveloperNoiseOverview,
    enabled: Boolean(statusQuery.data && !statusQuery.isError),
    refetchInterval: false,
  });
  const maintenanceSummaryQuery = useQuery({
    queryKey: queryKeys.launcherMaintenanceSummary(),
    queryFn: getLauncherMaintenanceSummary,
    enabled: Boolean(statusQuery.data && !statusQuery.isError),
    refetchInterval: false,
  });
  const runInstanceLifecycle = (instanceId: string, operation: LauncherOperation) => {
    const item = branchItems.find((candidate) => candidate.id === instanceId);
    if (item && !item.current) {
      return requestBranchInstanceLifecycle(item.id, operation);
    }
    return requestLifecycle(operation);
  };
  type LauncherControlRequest = LauncherOperation | {
    operation: LauncherOperation;
    instanceId?: string;
    instanceIds?: string[];
  };
  const resolveControlRequest = (input: LauncherControlRequest) => {
    if (typeof input === "string") {
      return { operation: input, instanceId: selectedBranchId, instanceIds: undefined as string[] | undefined };
    }
    const instanceIds = (input.instanceIds || []).map((id) => String(id || "").trim()).filter(Boolean);
    return {
      operation: input.operation,
      instanceId: input.instanceId || instanceIds[0] || selectedBranchId,
      instanceIds: instanceIds.length > 0 ? instanceIds : undefined,
    };
  };
  const controlMutation = useMutation({
    mutationFn: async (input: LauncherControlRequest) => {
      const request = resolveControlRequest(input);
      const ids = request.instanceIds && request.instanceIds.length > 0
        ? request.instanceIds
        : [request.instanceId];
      const firstId = ids[0];
      if (!firstId) {
        throw new Error("missing instance id");
      }
      let last = await runInstanceLifecycle(firstId, request.operation);
      for (const instanceId of ids.slice(1)) {
        last = await runInstanceLifecycle(instanceId, request.operation);
      }
      return last;
    },
    onMutate: (input) => {
      const operation = resolveControlRequest(input).operation;
      setLastControlOperation(operation);
      markControlledProjectLifecycleOperation(operation);
      postLauncherLifecycleControlTelemetry(operation, "requested");
      // Immediate feedback — restart/stop used to look like a no-op until status poll returned.
      if (operation === "restart") {
        setNotice({
          tone: "neutral",
          text: copy.lifecycleRestartingDetail,
          source: "lifecycle-control",
        });
      } else if (operation === "stop" || operation === "force-stop") {
        setNotice({
          tone: "neutral",
          text: copy.lifecycleStoppingDetail || copy.commandDone,
          source: "lifecycle-control",
        });
      }
    },
    onSuccess: (response, input) => {
      const operation = resolveControlRequest(input).operation;
      postLauncherLifecycleControlTelemetry(
        operation,
        response.accepted ? "accepted" : "rejected",
        launcherLifecycleResponseTelemetryFields(response),
      );
      if (!response.accepted) {
        clearControlledProjectLifecycleOperation();
      }
      setLastControlOperation((operation === "stop" || operation === "force-stop") && response.accepted ? operation : null);
      setTrackedCommand(response.accepted && response.commandId ? { commandId: response.commandId, operation } : null);
      setNotice({
        tone: response.accepted ? "neutral" : "warning",
        text: launcherControlNoticeMessage(response, operation, uiLang, copy.commandDone),
        source: "lifecycle-control",
      });
      const startedId = String(response.instanceId || resolveControlRequest(input).instanceId || currentInstanceId || "").trim();
      if (response.accepted && (operation === "start" || operation === "restart") && startedId) {
        setSelectedInstanceId(startedId);
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherBranchInstances() });
    },
    onError: (error, input) => {
      postLauncherLifecycleControlTelemetry(resolveControlRequest(input).operation, "request_failed", {
        errorMessage: error instanceof Error ? error.message : String(error),
      });
      clearControlledProjectLifecycleOperation();
      setLastControlOperation(null);
      setTrackedCommand(null);
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error), source: "lifecycle-control" });
    },
  });
  const supervisorMutation = useMutation({
    mutationFn: reattachLauncherSupervisor,
    onSuccess: (response) => {
      setNotice({
        tone: response.accepted ? "success" : "warning",
        text: response.message || copy.commandDone,
        source: "supervisor",
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error), source: "supervisor" });
    },
  });
  const startupSettingsMutation = useMutation({
    mutationFn: updateLauncherStartupSettings,
    onSuccess: (response) => {
      const workbench = response.setting.workbench;
      setNotice({
        tone:
          response.setting.launcher.controlPortEnvOverride
          || workbench.windowModeEnvOverride
          || workbench.windowSizeEnvOverride
          || workbench.backendPortEnvOverride
          || workbench.frontendPortEnvOverride
            ? "warning"
            : "success",
        text: response.message || copy.startupSettingsSaved,
        source: "startup-settings",
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error), source: "startup-settings" });
    },
  });
  const [pendingWindowMode, setPendingWindowMode] = useState<WorkbenchWindowMode | "">("");
  const workbenchWindowSaveMutation = useMutation({
    mutationFn: saveLauncherWorkbenchWindowMode,
    onMutate: (request) => {
      setPendingWindowMode(request.mode);
    },
    onSuccess: (response) => {
      setNotice({
        tone: response.setting.envOverride ? "warning" : "success",
        text: response.message || copy.windowModeSaved,
        source: "window-mode",
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error), source: "window-mode" });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
    },
    onSettled: () => {
      setPendingWindowMode("");
    },
  });
  const developerModeMutation = useMutation({
    mutationFn: updateLauncherDeveloperMode,
    onSuccess: (response) => {
      setCleanupPlan(null);
      setNotice({ tone: response.setting.enabled ? "warning" : "success", text: response.message || copy.developerModeUpdated });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherDeveloperNoiseOverview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });
  const resetDeveloperSandboxMutation = useMutation({
    mutationFn: resetLauncherDeveloperSandbox,
    onSuccess: (response) => {
      setCleanupPlan(null);
      setNotice({ tone: "success", text: response.message || copy.developerModeUpdated });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherDeveloperNoiseOverview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });
  const cleanupPreviewMutation = useMutation({
    mutationFn: previewLauncherDeveloperCleanup,
    onSuccess: (response) => {
      setCleanupPlan(response.plan);
      setNotice({ tone: response.plan.targetCount > 0 ? "warning" : "neutral", text: response.message || copy.cleanupPlanReady });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherDeveloperNoiseOverview() });
    },
    onError: (error) => {
      setCleanupPlan(null);
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });
  const cleanupApplyMutation = useMutation({
    mutationFn: applyLauncherDeveloperCleanup,
    onSuccess: (response) => {
      setCleanupPlan(null);
      setNotice({ tone: "success", text: response.message || copy.cleanupApplied });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherDeveloperNoiseOverview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherDeveloperNoiseOverview() });
    },
  });
  const maintenancePreviewMutation = useMutation({
    mutationFn: previewLauncherMaintenancePlan,
    onSuccess: (response, variables) => {
      const planProfile = normalizeMaintenanceProfileId(response.plan.profileId)
        ?? normalizeMaintenanceProfileId(variables.profileId)
        ?? maintenanceProfile;
      setMaintenancePlansByProfile((plans) => ({ ...plans, [planProfile]: response.plan }));
      setNotice({ tone: response.plan.targetCount > 0 ? "warning" : "neutral", text: response.message || copy.maintenancePlanReady });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherMaintenanceSummary() });
    },
    onError: (error, variables) => {
      const failedProfile = normalizeMaintenanceProfileId(variables.profileId) ?? maintenanceProfile;
      setMaintenancePlansByProfile((plans) => {
        const nextPlans = { ...plans };
        delete nextPlans[failedProfile];
        return nextPlans;
      });
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });
  const maintenanceApplyMutation = useMutation({
    mutationFn: applyLauncherMaintenancePlan,
    onSuccess: (response) => {
      const appliedProfile = normalizeMaintenanceProfileId(response.profileId) ?? maintenanceProfile;
      setMaintenancePlansByProfile((plans) => {
        const nextPlans = { ...plans };
        delete nextPlans[appliedProfile];
        return nextPlans;
      });
      setNotice({ tone: response.ok ? "success" : "warning", text: response.message || copy.maintenanceApplied });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherMaintenanceSummary() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teams() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeScenes() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.logRoots() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherMaintenanceSummary() });
    },
  });

  const status = statusQuery.data as LauncherStatusWithGuardian | undefined;
  const bundle = status?.projectBundle;
  const guardian = status?.guardianAdapter;
  const evidence = status?.controlPlaneEvidence;
  const componentRows = useMemo(() => sortComponents(bundle?.components ?? []), [bundle?.components]);
  const headerTone = stateTone(bundle?.overallState ?? status?.launcher.phase ?? "", Boolean(bundle));
  const transitionAt = compactDate(bundle?.lastOperation.transitionAt ?? "", locale);
  const lastRequestAudit = bundle?.lastOperation.requestAudit ?? {};
  const lastRequestTrigger = lastRequestAudit.trigger || "-";
  const lastRequestEndpoint = [lastRequestAudit.method, lastRequestAudit.endpoint].filter(Boolean).join(" ") || "-";
  const canRequestSupervisorReattach = Boolean(status && guardian?.supervisor && !guardian.supervisor.alive);
  const uiLang = lang === "zh" ? "zh" : "en";
  const bundleDesired = String(bundle?.desiredState || "").toLowerCase();
  const bundleObserved = String(bundle?.observedState || "").toLowerCase();
  const launcherControlPlaneStarting = statusQuery.isError && isLauncherControlPlaneNotReady(statusQuery.error);
  const launcherStatusDisconnected = statusQuery.isError
    && !launcherControlPlaneStarting
    && isLauncherStatusNetworkDisconnect(statusQuery.error);
  const launcherControlLimited = statusQuery.isError
    && !launcherControlPlaneStarting
    && isControlTokenError(statusQuery.error);
  const pendingBranchOperation = controlMutation.isPending && controlMutation.variables
    ? (() => {
        const request = resolveControlRequest(controlMutation.variables);
        return {
          instanceId: request.instanceId,
          instanceIds: request.instanceIds,
          operation: request.operation === "force-stop" ? "stop" : request.operation,
        } as const;
      })()
    : undefined;
  const lifecycleDisplay = resolveLifecycleDisplay(status, copy, { disconnected: launcherStatusDisconnected, controlLimited: launcherControlLimited, starting: launcherControlPlaneStarting });
  const projectIsOpen = lifecycleDisplay.state === "running";
  const projectIsPartial = lifecycleDisplay.state === "partial";
  const projectIsClosed = lifecycleDisplay.state === "closed";
  const projectIsChanging = ["starting", "stopping", "restarting"].includes(lifecycleDisplay.state);
  const lifecycleSettled = projectIsOpen || projectIsPartial || projectIsClosed;
  const controlPlaneIdle = isControlPlaneIdle(evidence);
  const controlBusy = controlMutation.isPending && !(controlPlaneIdle && lifecycleSettled);
  const busy = controlBusy || supervisorMutation.isPending;
  const startDisabled = selectedIsCurrent
    ? launcherControlPlaneStarting || launcherStatusDisconnected || busy || !controlPlaneIdle || projectIsOpen || projectIsChanging
    : launcherControlPlaneStarting || launcherStatusDisconnected || controlMutation.isPending || !selectedStartable || selectedAlive;
  const startDisabledReason = launcherControlPlaneStarting
    ? copy.lifecycleStartingDetail
    : launcherStatusDisconnected
      ? copy.loadFailed
      : selectedIsCurrent
      ? busy || !controlPlaneIdle
        ? copy.startDisabledBusy
        : projectIsOpen
        ? copy.startDisabledRunning
        : projectIsChanging
          ? copy.startDisabledChanging
          : copy.startDisabled
      : !selectedStartable
        ? (selectedBranch?.kind === "retired" ? copy.retiredCheckout : copy.notCheckedOut)
        : selectedAlive
          ? copy.startDisabledRunning
          : copy.startDisabled;
  const projectSummary = selectedIsCurrent
    ? lifecycleDisplay.label
    : selectedAlive
      ? copy.lifecycleRunning
      : copy.lifecycleClosed;
  const launcherSummary = !status
    ? launcherControlPlaneStarting || statusQuery.isPending ? copy.launcherMaintaining : copy.launcherOffline
    : copy.launcherMaintaining;
  const controlSummary = launcherControlLimited ? copy.controlLimited : copy.controlReady;
  const controlDetail = launcherControlLimited ? copy.controlLimitedDetail : copy.controlReadyDetail;
  const activeWorkCount = status?.lifecycleProof.activeWorkRuns.count ?? 0;
  const activeWorkKinds = status?.lifecycleProof.activeWorkRuns.kinds ?? [];
  const startupSettings = status?.settings?.startup;
  const developerModeSetting = status?.settings?.developerMode;
  const fallbackWindowSetting = status?.settings?.workbenchWindow;
  const configuredWindowMode = startupSettings?.workbench.windowMode ?? fallbackWindowSetting?.mode ?? "fullscreen";
  const effectiveWindowMode = startupSettings?.workbench.effectiveWindowMode ?? fallbackWindowSetting?.effectiveMode ?? configuredWindowMode;
  const envOverrideMode = startupSettings?.workbench.windowModeEnvOverride ?? fallbackWindowSetting?.envOverride ?? "";
  const controlPortOverride = startupSettings?.launcher.controlPortEnvOverride || 0;
  const backendPortOverride = startupSettings?.workbench.backendPortEnvOverride || 0;
  const frontendPortOverride = startupSettings?.workbench.frontendPortEnvOverride || 0;
  const windowModeDetail = envOverrideMode
    ? `${copy.windowModeEnvOverride}: ${workbenchWindowModeLabel(envOverrideMode, copy)} · ${copy.windowModeRestartRequired}`
    : copy.windowModeRestartRequired;
  const restartQueue = evidence?.restartQueue;
  const restartQueueActive = Boolean(restartQueue?.active);
  const restartQueuePending = Boolean(restartQueue?.pending);
  const activeWorkSummary = restartQueueActive
    ? copy.lifecycleRestarting
    : activeWorkCount > 0
      ? copy.restartProtected
      : projectIsClosed
        ? copy.noActiveWork
      : copy.restartClear;
  const closeCommandInFlight =
    trackedCommand?.operation === "stop"
    || trackedCommand?.operation === "force-stop"
    || controlPlaneHasCommandType(evidence, ["close_workbench", "force_close_workbench"]);
  const destructiveActionDisabled = selectedIsCurrent
    ? busy || !controlPlaneIdle || activeWorkCount > 0 || projectIsChanging || projectIsClosed
    : controlMutation.isPending || !selectedAlive;
  const destructiveActionDisabledReason = selectedIsCurrent
    ? activeWorkCount > 0
      ? copy.lifecycleActionDisabledActiveWork
      : projectIsClosed
        ? copy.restartDisabledClosed
        : projectIsChanging
          ? copy.startDisabledChanging
          : copy.startDisabledBusy
    : selectedAlive
      ? copy.startDisabledBusy
      : copy.stopDisabledClosed;
  const stopDisabled = selectedIsCurrent
    ? destructiveActionDisabled || closeCommandInFlight
    : controlMutation.isPending || !selectedAlive;
  const stopDisabledReason = selectedIsCurrent
    ? projectIsClosed
      ? copy.stopDisabledClosed
      : closeCommandInFlight
        ? copy.stopDisabledInFlight
        : destructiveActionDisabledReason
    : selectedAlive
      ? copy.startDisabledBusy
      : copy.stopDisabledClosed;
  const forceStopDisabled = selectedIsCurrent
    ? busy || projectIsClosed || closeCommandInFlight
    : controlMutation.isPending || !selectedAlive;
  const forceStopDisabledReason = selectedIsCurrent
    ? projectIsClosed
      ? copy.forceStopDisabledClosed
      : closeCommandInFlight
        ? copy.forceStopDisabledInFlight
        : copy.startDisabledBusy
    : selectedAlive
      ? copy.startDisabledBusy
      : copy.forceStopDisabledClosed;
  const activeWorkDetail = activeWorkCount > 0
    ? `${copy.activeTasks}: ${activeWorkCount}${activeWorkKinds.length ? ` · ${activeWorkKinds.join(", ")}` : ""}${restartQueue?.statusLine ? ` · ${restartQueue.statusLine}` : ""}`
    : restartQueue?.statusLine
      ? restartQueue.statusLine
    : copy.noActiveWorkSummary;
  const nextAction = restartQueueActive
    ? copy.useWaitAction
    : projectIsPartial
      ? copy.useOpenAction
    : projectIsOpen
    ? copy.safeToUse
    : projectIsChanging
      ? copy.useWaitAction
      : projectIsClosed
        ? copy.useStartAction
        : copy.useCheckAction;
  const nextActionDetail = restartQueueActive
    ? restartQueue?.statusLine || lifecycleDisplay.detail
    : projectIsPartial
      ? lifecycleDisplay.detail || copy.openWorkbenchSummary
    : projectIsOpen
    ? copy.openWorkbenchSummary
    : projectIsChanging
      ? lifecycleDisplay.detail
      : projectIsClosed
        ? copy.startProjectSummary
        : lifecycleDisplay.detail || copy.checkDiagnosticsSummary;
  const activeWorkDetailShort = summarizeLauncherMessage(activeWorkDetail, copy, uiLang) || activeWorkDetail;
  const nextActionDetailShort = summarizeLauncherMessage(nextActionDetail, copy, uiLang) || nextActionDetail;
  const userGuideTone = activeWorkCount > 0 || restartQueuePending
    ? "warning"
    : lifecycleDisplay.tone;
  const userGuideTitle = activeWorkCount > 0
    ? copy.userGuideBlocked
    : restartQueueActive || projectIsChanging
      ? copy.userGuideChanging
      : projectIsPartial
        ? copy.userGuidePartial
      : projectIsOpen
        ? copy.userGuideReady
        : projectIsClosed
          ? copy.userGuideClosed
          : copy.userGuideProblem;
  const userGuideDetail = activeWorkCount > 0
    ? copy.userGuideBlockedDetail
    : restartQueueActive || projectIsChanging
      ? restartQueue?.statusLine || copy.userGuideChangingDetail
      : projectIsPartial
        ? lifecycleDisplay.detail || copy.userGuidePartialDetail
      : projectIsOpen
        ? copy.userGuideReadyDetail
        : projectIsClosed
          ? copy.userGuideClosedDetail
          : lifecycleDisplay.detail || copy.userGuideProblemDetail;
  const statusBarBlockerReason = activeWorkCount > 0
    ? activeWorkDetail
    : restartQueuePending || restartQueueActive
      ? restartQueue?.statusLine || copy.userGuideChangingDetail
      : launcherControlLimited
        ? copy.controlLimitedDetail
        : launcherStatusDisconnected
          ? copy.loadFailed
          : closeCommandInFlight
            ? stopDisabledReason
            : controlBusy || !controlPlaneIdle
              ? copy.startDisabledBusy
              : projectIsChanging
                ? lifecycleDisplay.detail || copy.userGuideChangingDetail
                : projectIsClosed
                  ? copy.lifecycleClosedDetail
                  : lifecycleDisplay.detail || copy.noActiveWorkSummary;
  const statusBarReasonText = summarizeLauncherMessage(statusBarBlockerReason, copy, uiLang) || statusBarBlockerReason;
  const noticeTextShort = summarizeLauncherMessage(notice.text, copy, uiLang) || notice.text;
  const actionLockLabel = projectIsClosed ? copy.actionsStartOnly : destructiveActionDisabled ? copy.actionsLocked : copy.actionsAvailable;
  const guardianProgress = `${guardian?.ownedCount ?? 0}/${guardian?.adapterCount ?? 0}`;
  const toggleDeveloperMode = (enabled: boolean, baseHash: string) => {
    developerModeMutation.mutate({ enabled, baseHash });
  };
  const resetDeveloperSandbox = () => {
    resetDeveloperSandboxMutation.mutate();
  };
  const previewDeveloperCleanup = () => {
    setCleanupPlan(null);
    cleanupPreviewMutation.mutate(selectedCleanupAction);
  };
  const applyDeveloperCleanup = () => {
    if (!cleanupPlan) {
      return;
    }
    const confirmed = window.confirm(copy.cleanupRequiresConfirm);
    if (!confirmed) {
      return;
    }
    cleanupApplyMutation.mutate({
      action: cleanupPlan.action,
      planId: cleanupPlan.planId,
      planHash: cleanupPlan.planHash,
      confirm: true,
    });
  };
  const previewMaintenancePlan = () => {
    setMaintenancePlansByProfile((plans) => {
      const nextPlans = { ...plans };
      delete nextPlans[maintenanceProfile];
      return nextPlans;
    });
    maintenancePreviewMutation.mutate({ profileId: maintenanceProfile });
  };
  const applyMaintenancePlan = () => {
    if (!maintenancePlan) {
      return;
    }
    const confirmed = window.confirm(copy.maintenanceRequiresConfirm);
    if (!confirmed) {
      return;
    }
    maintenanceApplyMutation.mutate({
      planId: maintenancePlan.planId,
      planHash: maintenancePlan.planHash,
      profileId: maintenanceProfile,
      confirm: true,
    });
  };
  const residualItems = status?.lifecycleProof.residualProcesses?.items ?? [];
  const residualCount = Math.max(status?.lifecycleProof.residualProcesses?.count ?? 0, residualItems.length);
  const statusRows = useMemo<StatusRow[]>(() => {
    const componentById = new Map(componentRows.map((component) => [component.id, component]));
    const backend = componentById.get("backend");
    const frontend = componentById.get("frontend");
    const browser = componentById.get("browser");
    const controlPort = startupSettings?.launcher.effectiveControlPort || status?.launcher.controlPlane.port || 0;
    const controlPid = status?.launcher.controlPlane.pid;
    const backendPid = bundle?.backend.pid || backend?.pid || 0;
    const windowPid = bundle?.browser.windowPid || browser?.pid || 0;
    const managerPid = status?.runtimeManager.managerPid || 0;
    const ownedRows: StatusRow[] = [
      {
        id: "launcher_control",
        label: copy.controlSurface,
        status: launcherStatusDisconnected ? humanState("stopped", uiLang) : humanState("running", uiLang),
        pid: displayPid(controlPid),
        port: displayPort(controlPort),
        ownership: copy.ownedProcess,
        detail: launcherStatusDisconnected
          ? copy.launcherOffline
          : (lang === "zh" ? "当前 Launcher 控制面。" : "Current Launcher control plane."),
        technical: `${copy.pid} ${displayPid(controlPid)} · ${copy.port} ${displayPort(controlPort)}`,
        ok: !launcherStatusDisconnected,
        tone: launcherStatusDisconnected ? "warning" : "success",
      },
      {
        id: "backend",
        label: componentLabel("backend", uiLang),
        status: launcherStatusDisconnected ? humanState("stopped", uiLang) : humanState(backend?.state || (bundle?.backend.healthy ? "healthy" : "-"), uiLang),
        pid: displayPid(backendPid),
        port: displayPort(bundle?.backend.port),
        ownership: copy.ownedProcess,
        detail: launcherStatusDisconnected
          ? copy.stoppedBackendDetail
          : bundle?.backend.healthy
          ? (lang === "zh" ? "后端已监听，工作台可以访问。" : "Backend is listening and reachable.")
          : (lang === "zh" ? "后端未确认可用。" : "Backend is not confirmed ready."),
        technical: `${copy.pid} ${displayPid(backendPid)} · ${copy.port} ${displayPort(bundle?.backend.port)} · ${copy.owner} ${displayPid(bundle?.backend.portOwnerPid)} · ${copy.listening}: ${boolText(bundle?.backend.portListening, copy.yes, copy.no)}`,
        ok: Boolean(!launcherStatusDisconnected && (backend?.ok ?? bundle?.backend.healthy)),
        tone: stateTone(backend?.state || (bundle?.backend.healthy ? "healthy" : "stopped"), Boolean(!launcherStatusDisconnected && (backend?.ok ?? bundle?.backend.healthy))),
      },
      {
        id: "browser",
        label: componentLabel("browser", uiLang),
        status: humanState(launcherStatusDisconnected ? "stopped" : browser?.state || (bundle?.browser.alive ? "alive" : "stopped"), uiLang),
        pid: displayPid(windowPid),
        port: "-",
        ownership: copy.ownedProcess,
        detail: launcherStatusDisconnected
          ? copy.stoppedBrowserDetail
          : bundle?.browser.alive
          ? (lang === "zh" ? "工作台窗口由 Launcher 管理。" : "Workbench window is managed by Launcher.")
          : (lang === "zh" ? "工作台窗口未打开。" : "Workbench window is not open."),
        technical: `${copy.pid} ${displayPid(windowPid)} · managed ${boolText(bundle?.browser.managed, copy.yes, copy.no)} · ${browser?.detail || "-"}`,
        ok: Boolean(launcherStatusDisconnected || (browser?.ok ?? !bundle?.browser.alive)),
        tone: stateTone(bundle?.browser.alive ? "running" : "stopped", Boolean(bundle?.browser.alive || launcherStatusDisconnected)),
      },
      {
        id: "runtime_manager",
        label: componentLabel("runtime_manager", uiLang),
        status: humanState(status?.runtimeManager.runtimeState || "-", uiLang),
        pid: displayPid(managerPid),
        port: "-",
        ownership: copy.ownedProcess,
        detail: status?.runtimeManager.running
          ? (lang === "zh" ? "生命周期管理器正在维护项目。" : "Lifecycle manager is maintaining the project.")
          : (lang === "zh" ? "生命周期管理器未运行。" : "Lifecycle manager is not running."),
        technical: `${copy.pid} ${displayPid(managerPid)} · state ${status?.runtimeManager.stateVersion ?? "-"} · ${evidence?.state.updatedAt ? compactDate(evidence.state.updatedAt, locale) : "-"}`,
        ok: Boolean(status?.runtimeManager.running),
        tone: stateTone(status?.runtimeManager.runtimeState || "idle", Boolean(status?.runtimeManager.running)),
      },
      {
        id: "frontend",
        label: componentLabel("frontend", uiLang),
        status: humanState(frontend?.state || (bundle?.frontend.distReady ? "ready" : "-"), uiLang),
        pid: displayPid(frontend?.pid),
        port: displayPort(startupSettings?.workbench.effectiveFrontendPort),
        ownership: copy.ownedProcess,
        detail: launcherStatusDisconnected
          ? copy.stoppedFrontendDetail
          : bundle?.frontend.distReady
          ? (lang === "zh" ? "前端资源已就绪。" : "Frontend assets are ready.")
          : (lang === "zh" ? "前端资源还未构建。" : "Frontend assets are not built yet."),
        technical: `dist ${boolText(bundle?.frontend.distReady, copy.yes, copy.no)} · orphaned ${boolText(bundle?.frontend.orphaned, copy.yes, copy.no)} · mode ${bundle?.frontend.mode || "-"}`,
        ok: Boolean(frontend?.ok ?? bundle?.frontend.distReady),
        tone: stateTone(frontend?.state || (bundle?.frontend.distReady ? "ready" : "missing"), Boolean(frontend?.ok ?? bundle?.frontend.distReady)),
      },
    ];
    const leftoverRows = residualItems.map((item, index) => {
      const kind = String(item.kind || "residual");
      return {
        id: `residual-${item.pid || index}-${kind}`,
        label: residualKindLabel(kind, uiLang),
        status: humanState("running", uiLang),
        pid: displayPid(item.pid),
        port: displayPort(item.port),
        ownership: copy.residualProcess,
        detail: copy.leftoverProcess,
        technical: `${kind} · ${copy.pid} ${displayPid(item.pid)} · parent ${displayPid(item.parentPid)} · ${item.commandLine || item.name || "-"}`,
        ok: false,
        tone: "warning" as const,
      };
    });
    return [...ownedRows, ...leftoverRows];
  }, [bundle, componentRows, copy, evidence?.state.updatedAt, lang, launcherStatusDisconnected, locale, residualItems, startupSettings, status, uiLang]);

  const instanceProcessRows = buildAllInstanceMonitorRows(
    branchItems,
    {
      currentId: currentInstanceId,
      backendPid: bundle?.backend.pid,
      windowPid: bundle?.browser.windowPid,
      port: bundle?.backend.port,
      alive: Boolean(bundle?.backend.alive || bundle?.backend.healthy),
    },
    {
      running: humanState("running", uiLang),
      stopped: humanState("stopped", uiLang),
      owned: copy.ownedProcess,
      windowRunning: uiLang === "zh" ? "窗口运行中" : "Window running",
      windowStopped: uiLang === "zh" ? "窗口已停止" : "Window stopped",
    },
  );
  const sharedProcessRows = statusRows.filter((row) => (
    row.id === "launcher_control" || row.id === "runtime_manager" || row.id === "frontend" || row.id.startsWith("residual-")
  ));
  const selectedProcessRows = [...instanceProcessRows, ...sharedProcessRows];
  const selectedProcessHint = uiLang === "zh" ? "全部已打开分支的进程" : "Processes for every checked-out instance";
  const selectedResidualCount = residualCount;
  const diagnosticStatusRows = statusRows.filter((row) => row.id === "runtime_manager");
  const activeCommand = evidence?.state.activeCommand;
  const recovery = evidence?.recovery;
  const recentResults = (evidence?.results.recent ?? []).slice(0, 3);
  const recentEvents = (evidence?.events.recent ?? []).slice(0, 3);
  const controlPlaneSpecs = [
    { label: copy.overall, value: launcherSummary },
    { label: copy.guardian, value: guardianProgress },
    { label: copy.reason, value: bundle?.lastOperation.reason || bundle?.lastReason || "-" },
    { label: copy.requestTrigger, value: lastRequestTrigger },
    { label: copy.transition, value: transitionAt },
  ];
  const controlEvidenceSpecs = [
    { label: copy.state, value: humanState(evidence?.state.runtimeState, uiLang) },
    { label: copy.activeCommand, value: activeCommand?.commandId ? humanCommandType(activeCommand.type, uiLang) : "-" },
    { label: copy.pending, value: String(evidence?.queue.pendingCount ?? 0) },
    { label: copy.processing, value: String(evidence?.queue.processingCount ?? 0) },
    { label: copy.recovery, value: recovery?.active ? humanCommandType(recovery.commandType, uiLang) : copy.recoveryIdle },
  ];
  const recoveryLine = recovery?.active
    ? {
        label: copy.recovery,
        value: recovery.statusLine || humanCommandType(recovery.commandType, uiLang),
        meta: [recovery.commandId, compactDate(recovery.recoveredAt, locale)].filter(Boolean).join(" · ") || "-",
        tone: recovery.resultOk === false ? "warning" as const : "success" as const,
      }
    : null;
  const activeCommandLine = {
    label: copy.activeCommand,
    value: activeCommand?.commandId ? humanCommandType(activeCommand.type, uiLang) : "-",
    meta: [activeCommand?.requestedBy, activeCommand?.reason].filter(Boolean).join(" · ") || "-",
  };
  const diagnosticQueueItems = [
    ...recentResults.map((item) => ({
      id: item.commandId,
      primary: item.message || humanCommandType(item.commandId, uiLang),
      secondary: `${item.ok ? "ok" : "failed"} · ${item.message || item.errorType || "-"}`,
      tone: item.ok ? "success" as const : "error" as const,
    })),
    ...recentEvents.map((item) => ({
      id: `${item.at}-${item.type}-${item.commandId}`,
      primary: humanCommandType(item.type, uiLang),
      secondary: [item.commandId, compactDate(item.at, locale)].filter(Boolean).join(" · ") || "-",
      tone: item.ok === false ? "error" as const : item.ok === true ? "success" as const : "neutral" as const,
    })),
  ];
  const guardianResponsibilityRows = (guardian?.responsibilities ?? []).map((item) => ({
    id: item.id,
    label: responsibilityLabel(item.id, uiLang),
    owner: responsibilityOwner(item.owner, uiLang),
    state: responsibilityDisplayState(item, uiLang),
    detail: responsibilityDetail(item, uiLang),
    tone: stateTone(responsibilityToneState(item)),
  }));
  const diagnosticSpecs = [
    { label: copy.schema, value: String(bundle?.schemaVersion ?? "-") },
    { label: "bundle mode", value: bundle?.mode || "-" },
    { label: "url", value: bundle?.url || "-" },
    { label: copy.source, value: bundle?.lastOperation.source || "-" },
    { label: copy.requestEndpoint, value: lastRequestEndpoint },
    { label: copy.proof, value: status?.lifecycleProof.summary || "-" },
    { label: copy.supervisor, value: guardian?.supervisor?.blocking === false && guardian.supervisor.impact ? humanState(guardian.supervisor.impact, uiLang) : guardian?.supervisor?.status || "-" },
    { label: copy.internalMigrationDetails, value: [status?.launcher.mode, guardian?.mode, status?.launcher.controlPlane.nextPhase, guardian?.targetMode].filter(Boolean).join(" | ") || "-" },
    { label: copy.advancedDetails, value: [...statusRows, ...diagnosticStatusRows].map((row) => `${row.label}: ${row.technical}`).join(" | ") || "-" },
    { label: copy.scene, value: guardian?.supervisor?.runtimeSceneId || "-" },
    { label: copy.stdout, value: guardian?.supervisor?.stdoutPath || "-" },
    { label: copy.stderr, value: guardian?.supervisor?.stderrPath || "-" },
  ];
  const expectedStopDisconnect = statusQuery.isError && !launcherControlPlaneStarting && (lastControlOperation === "stop" || lastControlOperation === "force-stop" || launcherStatusDisconnected);
  const trackedResult = trackedCommand
    ? (evidence?.results.recent ?? []).find((item) => item.commandId === trackedCommand.commandId)
    : undefined;
  const trackedCommandSettledByStatus = Boolean(
    trackedCommand
    && !trackedResult
    && controlPlaneIdle
    && lifecycleSettled
    && !activeCommand?.commandId
    && launcherOperationSettledByStatus(trackedCommand.operation, { projectIsOpen, projectIsPartial, projectIsClosed }),
  );
  const shouldClearStaleLifecycleNotice = Boolean(
    notice.source === "lifecycle-control"
    && notice.tone === "error"
    && status
    && !statusQuery.isError
    && !controlMutation.isPending
    && !activeCommand?.commandId
    && !trackedResult
    && controlPlaneIdle
    && lifecycleSettled
    && !bundle?.failureMessage
    && (!trackedCommand || trackedCommandSettledByStatus),
  );
  const launcherCloseGuardMessage = projectWindowCloseGuardMessage(lang, "launcher");
  const controlledCloseOperationInFlight =
    (controlMutation.isPending && (lastControlOperation === "stop" || lastControlOperation === "force-stop" || lastControlOperation === "restart"))
    || trackedCommand?.operation === "stop"
    || trackedCommand?.operation === "force-stop"
    || trackedCommand?.operation === "restart";
  const launcherCloseBlocked = shouldBlockProjectWindowClose(status, {
    lifecycleOperationInFlight: controlledCloseOperationInFlight,
  });
  const launcherCloseGuardArmed = shouldArmBrowserProjectCloseGuard({
    closeBlocked: launcherCloseBlocked,
    electronDesktopShell: isElectronDesktopShell(),
  });

  useEffect(() => {
    if (!trackedCommand || !trackedResult) {
      return;
    }
    const message = resultMessage(trackedResult, trackedCommand.operation, uiLang);
    const tone = trackedResult.ok ? "success" : "error";
    if (notice.text !== message || notice.tone !== tone) {
      setNotice({ tone, text: message, source: "lifecycle-control" });
    }
    setTrackedCommand(null);
    setLastControlOperation(null);
    clearControlledProjectLifecycleOperation();
  }, [notice.text, notice.tone, trackedCommand, trackedResult, uiLang]);

  useEffect(() => {
    if (!trackedCommandSettledByStatus) {
      return;
    }
    setTrackedCommand(null);
    setLastControlOperation(null);
    clearControlledProjectLifecycleOperation();
  }, [trackedCommandSettledByStatus]);

  useEffect(() => {
    if (!shouldClearStaleLifecycleNotice) {
      return;
    }
    setNotice({ tone: "neutral", text: "" });
  }, [shouldClearStaleLifecycleNotice]);

  // Decision via ref; listener stays mounted (status poll must not re-bind beforeunload).
  const launcherCloseGuardRef = useRef({
    armed: launcherCloseGuardArmed,
    message: launcherCloseGuardMessage,
    status,
  });
  launcherCloseGuardRef.current = {
    armed: launcherCloseGuardArmed,
    message: launcherCloseGuardMessage,
    status,
  };

  useStableBeforeUnload((event) => {
    const guard = launcherCloseGuardRef.current;
    if (!guard.armed) {
      return;
    }
    const telemetry = buildProjectWindowCloseBlockedTelemetry({
      surface: "launcher",
      status: guard.status,
    });
    postBrowserTelemetry(
      {
        ...telemetry,
        fields: {
          ...collectBrowserPageSnapshot(),
          ...(telemetry.fields ?? {}),
        },
      },
      { preferBeacon: true },
    );
    applyBeforeUnloadProjectCloseGuard(event, guard.message);
  });

  return (
    <VDenseOpsPage
      className={styles.route}
      bodyClassName={styles.routeBody}
      fill
      hideHeader
      data-vui-domain-recipe="launcher-workbench"
      ariaLabel={copy.title}
    >
      <div
        className={styles.primaryRail}
        data-vui-region="launcher-primary-rail"
      >
        <div className={styles.primaryColumn} data-vui-region="launcher-primary">
          <LauncherBranchInstancesPanel
            copy={copy}
            items={branchItems}
            selectedId={selectedBranchId}
            onSelect={setSelectedInstanceId}
            launcherTitle={branchInstancesQuery.data?.currentLauncherTitle}
            launcherOnline={Boolean(status && !launcherStatusDisconnected && !launcherControlLimited)}
            launcherReading={Boolean(
              !status && (statusQuery.isPending || launcherControlPlaneStarting)
            )}
            pendingOperation={pendingBranchOperation}
            lifecyclePending={controlMutation.isPending}
            onLifecycle={(instanceId, operation) => {
              setSelectedInstanceId(instanceId);
              controlMutation.mutate({ operation, instanceId });
            }}
            onStopMany={(instanceIds) => {
              if (instanceIds[0]) {
                setSelectedInstanceId(instanceIds[0]);
              }
              controlMutation.mutate({ operation: "stop", instanceIds });
            }}
          />
        </div>
        <aside
          className={styles.settingsRail}
          data-vui-region="launcher-settings-rail"
          aria-label={copy.startupSettings}
        >
          <Suspense fallback={<VStateSurface className={styles.notice} tone="loading" title={copy.loading} skeletonLines={2} />}>
            <LauncherStartupSettingsPanel
              copy={copy}
              uiLang={uiLang}
              setting={startupSettings}
              configuredWindowMode={configuredWindowMode}
              effectiveWindowModeLabel={workbenchWindowModeLabel(effectiveWindowMode, copy)}
              windowModeDetail={windowModeDetail}
              controlPortOverride={controlPortOverride}
              backendPortOverride={backendPortOverride}
              frontendPortOverride={frontendPortOverride}
              pending={startupSettingsMutation.isPending || workbenchWindowSaveMutation.isPending}
              pendingWindowMode={pendingWindowMode}
              onSave={(nextSetting) => startupSettingsMutation.mutate(nextSetting)}
              onWindowModeChange={(request) => workbenchWindowSaveMutation.mutate(request)}
            />
          </Suspense>
        </aside>
      </div>

      {statusQuery.isError && !launcherControlPlaneStarting ? (
        <VStateSurface
          className={styles.notice}
          tone={expectedStopDisconnect ? "info" : launcherControlLimited ? "unavailable" : "error"}
          title={expectedStopDisconnect ? copy.stoppedStatusUnavailable : launcherControlLimited ? copy.controlLimitedDetail : copy.loadFailed}
        />
      ) : null}
      {launcherControlPlaneStarting ? (
        <VStateSurface
          className={styles.notice}
          tone="loading"
          title={copy.lifecycleStarting}
          skeletonLines={2}
        />
      ) : null}
      {notice.text ? (
        <VTooltip content={notice.text} tone={notice.tone === "error" ? "danger" : notice.tone === "warning" ? "warning" : "neutral"} width="wide">
          <VStateSurface
            className={styles.notice}
            tone={notice.tone === "error" ? "error" : notice.tone === "warning" ? "unavailable" : "info"}
            title={noticeTextShort}
            tabIndex={0}
          />
        </VTooltip>
      ) : null}
      {statusQuery.isPending && !status ? (
        <VStateSurface className={styles.notice} tone="loading" title={copy.loading} skeletonLines={2} />
      ) : null}

      <div
        className={styles.workspace}
        data-vui-recipe="launcher-workbench"
        data-vui-layout-id={LAUNCHER_LAYOUT_ID}
        data-vui-region="launcher-workspace"
      >
        <details className={styles.advancedFold}>
          <summary>
            <span>{copy.advancedFold}</span>
            <strong>{copy.advancedFoldHint}</strong>
          </summary>
          <div className={styles.advancedFoldBody}>
            <LauncherProcessMonitorPanel
              copy={{
                ...copy,
                processMonitorHint: selectedProcessHint,
              }}
              rows={selectedProcessRows}
              residualCount={selectedResidualCount}
              selectedId={selectedBranchId}
            />
            <Suspense fallback={<VStateSurface className={styles.notice} tone="loading" title={copy.loading} skeletonLines={2} />}>
              <LauncherProjectMaintenancePanel
                copy={copy}
                summary={maintenanceSummaryQuery.data}
                maintenanceProfile={maintenanceProfile}
                plan={maintenancePlan}
                loading={maintenanceSummaryQuery.isLoading || maintenanceSummaryQuery.isFetching}
                previewPending={maintenancePreviewMutation.isPending}
                applyPending={maintenanceApplyMutation.isPending}
                onProfileChange={(profile) => {
                  setMaintenanceProfile(profile);
                }}
                onPreview={previewMaintenancePlan}
                onApply={applyMaintenancePlan}
              />
              <LauncherDeveloperModePanel
                copy={copy}
                setting={developerModeSetting}
                noiseOverview={developerNoiseQuery.data}
                selectedAction={selectedCleanupAction}
                plan={cleanupPlan}
                pending={developerModeMutation.isPending}
                noiseLoading={developerNoiseQuery.isFetching}
                previewPending={cleanupPreviewMutation.isPending}
                applyPending={cleanupApplyMutation.isPending}
                resetPending={resetDeveloperSandboxMutation.isPending}
                onToggle={toggleDeveloperMode}
                onReset={resetDeveloperSandbox}
                onRefreshNoise={() => void developerNoiseQuery.refetch()}
                onSelectAction={(action) => {
                  setSelectedCleanupAction(action);
                  setCleanupPlan(null);
                }}
                onPreview={previewDeveloperCleanup}
                onApply={applyDeveloperCleanup}
              />
              <LauncherDiagnosticsPanel
                copy={copy}
                controlPlaneStatus={humanState(status?.runtimeManager.runtimeState, uiLang)}
                controlPlaneSpecs={controlPlaneSpecs}
                controlEvidenceStatus={evidence?.state.runtimeState || "-"}
                controlEvidenceSpecs={controlEvidenceSpecs}
                recoveryLine={recoveryLine}
                activeCommandLine={activeCommandLine}
                queueItemCount={recentResults.length + recentEvents.length}
                queueItems={diagnosticQueueItems}
                guardianProgress={guardianProgress}
                guardianOwnedCount={guardian?.ownedCount ?? 0}
                guardianAdapterCount={guardian?.adapterCount ?? 0}
                guardianRows={guardianResponsibilityRows}
                diagnosticSpecs={diagnosticSpecs}
                busy={busy}
                canRequestSupervisorReattach={canRequestSupervisorReattach}
                supervisorPending={supervisorMutation.isPending}
                onReattachSupervisor={() => supervisorMutation.mutate()}
              />
            </Suspense>
          </div>
        </details>
      </div>
    </VDenseOpsPage>
  );
}
