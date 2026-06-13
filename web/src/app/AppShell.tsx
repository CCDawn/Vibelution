import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useNavigationType } from "react-router-dom";
import { ChevronDown, LoaderCircle, Moon, Power, RefreshCw, Settings, Sun, Wrench } from "lucide-react";

import { fetchJson, setFetchJsonFailureReporter, type FetchJsonFailureReport } from "../api/client";
import { cancelRuntimeLifecycleCommand, forceStopLauncherBundle, restartLauncherBundle, stopLauncherBundle } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import {
  BackendHealth,
  ConfigSummary,
  RuntimeControlBlockedDetail,
  RuntimeSummary,
} from "../api/types";
import { useShellI18n } from "../i18n/useShellI18n";
import {
  collectBrowserMemorySnapshot,
  collectBrowserPageSnapshot,
  postBrowserTelemetry,
  summarizeConsoleArgs,
  type BrowserTelemetryEventInput,
} from "./browserTelemetry";
import {
  backendSystemTone,
  deriveActiveWorkIndicator,
  deriveBackendSystemState,
  deriveFrontendSystemState,
  deriveRuntimeControllerState,
  deriveStartupDisconnectedState,
  deriveStartupLoadingState,
  deriveStartupProgressState,
  frontendSystemTone,
  runtimeControllerTone,
  type SystemStatusTone,
} from "./systemStatus";
import { applyWorkbenchDocumentLanguage } from "./documentLanguage";
import { resolvePollingInterval, useStartupWarmup } from "./pollingPolicy";
import { recoverFromBuiltAssetResourceError, recoverFromDynamicImportFetchError } from "./routeChunkRecovery";
import { nextWorkbenchTheme, readStoredWorkbenchTheme, writeStoredWorkbenchTheme } from "./themePreference";
import { isWorkbenchDomainEnabled, isWorkbenchModeEnabled } from "./workbenchContract";
import { requestWorkbenchExitGuard } from "./workbenchExitGuard";
import {
  applyBeforeUnloadProjectCloseGuard,
  buildProjectWindowCloseBlockedTelemetry,
  hasRecentControlledProjectLifecycleOperation,
  projectWindowCloseGuardMessage,
  shouldBlockWorkbenchWindowClose,
} from "./projectCloseGuard";
import { getPageInstanceId } from "./pageInstance";
import styles from "./AppShell.module.css";
import packageJson from "../../package.json";

const LazyAppShellUtilityMenu = lazy(() =>
  import("./AppShellUtilityMenu")
    .then((module) => ({ default: module.AppShellUtilityMenu }))
    .catch((error) => {
      if (recoverFromDynamicImportFetchError(error, globalThis.window, postBrowserTelemetry)) {
        return new Promise<{ default: typeof import("./AppShellUtilityMenu").AppShellUtilityMenu }>(() => undefined);
      }
      throw error;
    }),
);

const LazyAppShellStatusGuidePanel = lazy(() =>
  import("./AppShellStatusGuidePanel")
    .then((module) => ({ default: module.AppShellStatusGuidePanel }))
    .catch((error) => {
      if (recoverFromDynamicImportFetchError(error, globalThis.window, postBrowserTelemetry)) {
        return new Promise<{ default: typeof import("./AppShellStatusGuidePanel").AppShellStatusGuidePanel }>(() => undefined);
      }
      throw error;
    }),
);

function linkClassName({ isActive }: { isActive: boolean }) {
  return isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink;
}

type RouteLocationLike = {
  pathname: string;
  search: string;
  hash: string;
};

export function routeLocationKey(location: RouteLocationLike): string {
  return `${location.pathname || "/"}${location.search || ""}${location.hash || ""}`;
}

export function routerLocationDesyncTarget(
  browserLocation: RouteLocationLike,
  routerLocation: RouteLocationLike,
): string | null {
  const browserTarget = routeLocationKey(browserLocation);
  const routerTarget = routeLocationKey(routerLocation);
  return browserTarget === routerTarget ? null : browserTarget;
}

export type RouterLocationDesyncRecoveryPlan = {
  target: string;
  restoreTarget: string;
};

export function routerLocationDesyncRecoveryPlan(
  browserLocation: RouteLocationLike,
  routerLocation: RouteLocationLike,
): RouterLocationDesyncRecoveryPlan | null {
  const browserTarget = routeLocationKey(browserLocation);
  const routerTarget = routeLocationKey(routerLocation);
  return browserTarget === routerTarget
    ? null
    : {
        target: browserTarget,
        restoreTarget: routerTarget,
      };
}

const API_FAILURE_TELEMETRY_THROTTLE_MS = 15_000;
const API_FAILURE_BACKGROUND_METHODS = new Set(["GET", "HEAD"]);
const APP_VERSION = packageJson.version;
const BROWSER_MEMORY_SAMPLE_INTERVAL_MS = 30_000;
const PAGEHIDE_NETWORK_FAILURE_SUPPRESSION_MS = 2_500;
const ROUTER_LOCATION_DESYNC_RECOVERY_DELAY_MS = 50;

export function shouldSuppressApiFailureTelemetry(
  failure: FetchJsonFailureReport,
  options: {
    shutdownRequested: boolean;
    restartRequested?: boolean;
    runtimeControllerState: string;
    visibilityState?: DocumentVisibilityState | string;
    pagehideAtMs?: number;
    nowMs?: number;
  },
): boolean {
  const {
    shutdownRequested,
    restartRequested,
    runtimeControllerState,
    visibilityState,
    pagehideAtMs,
    nowMs = Date.now(),
  } = options;
  if (shutdownRequested || restartRequested || runtimeControllerState === "closing") {
    return true;
  }
  if (
    failure.failureKind === "network" &&
    API_FAILURE_BACKGROUND_METHODS.has(failure.method.toUpperCase()) &&
    typeof pagehideAtMs === "number" &&
    pagehideAtMs > 0 &&
    nowMs >= pagehideAtMs &&
    nowMs - pagehideAtMs <= PAGEHIDE_NETWORK_FAILURE_SUPPRESSION_MS
  ) {
    return true;
  }
  if (
    failure.failureKind === "network" &&
    API_FAILURE_BACKGROUND_METHODS.has(failure.method.toUpperCase()) &&
    (visibilityState === "hidden" || visibilityState === "prerender")
  ) {
    return true;
  }
  return failure.status === 403
    && (failure.endpoint === "/api/control-token" || failure.endpoint === "/api/runtime/browser-telemetry");
}

export function shouldThrottleApiFailureTelemetry(
  failure: FetchJsonFailureReport,
  state: Map<string, number>,
  nowMs = Date.now(),
  windowMs = API_FAILURE_TELEMETRY_THROTTLE_MS,
): boolean {
  const key = [
    failure.method.toUpperCase(),
    failure.endpoint,
    failure.failureKind,
    failure.status ?? "network",
  ].join(" ");
  const previous = state.get(key);
  if (previous !== undefined && nowMs - previous < windowMs) {
    return true;
  }
  state.set(key, nowMs);
  for (const [entryKey, seenAt] of state) {
    if (nowMs - seenAt > windowMs * 4) {
      state.delete(entryKey);
    }
  }
  return false;
}

export function apiFailureTelemetryEventCode(failure: FetchJsonFailureReport): string {
  const endpoint = failure.endpoint.split(/[?#]/, 1)[0];
  if (endpoint === "/api/config/discover-models") {
    return failure.failureKind === "network" ? "config.model_discovery.network_error" : "config.model_discovery.failed";
  }
  return failure.failureKind === "network" ? "browser.api.network_error" : "browser.api.request_failed";
}

export function apiFailureTelemetryLevel(failure: FetchJsonFailureReport): BrowserTelemetryEventInput["level"] {
  const endpoint = failure.endpoint.split(/[?#]/, 1)[0];
  if (endpoint === "/api/config/discover-models" && failure.failureKind === "http" && failure.status !== null && failure.status < 500) {
    return "warning";
  }
  return "error";
}

export function buildShutdownRequestedTelemetry(): BrowserTelemetryEventInput {
  return {
    phase: "shutdown",
    eventCode: "browser.user_action.shutdown_requested",
    message: "User requested workbench shutdown.",
    level: "info",
    fields: {
      action: "shutdown",
      source: "app_shell",
    },
  };
}

export function buildRestartRequestedTelemetry(): BrowserTelemetryEventInput {
  return {
    phase: "restart",
    eventCode: "browser.user_action.restart_requested",
    message: "User requested workbench restart.",
    level: "info",
    fields: {
      action: "restart",
      source: "app_shell",
    },
  };
}

export function buildShutdownRequestUnconfirmedTelemetry(errorMessage: string): BrowserTelemetryEventInput {
  return {
    phase: "shutdown",
    eventCode: "browser.user_action.shutdown_request_unconfirmed",
    message: "Shutdown confirmation was not received; keeping pending shutdown feedback.",
    level: "warning",
    fields: {
      action: "shutdown",
      source: "app_shell",
      errorMessage,
    },
  };
}

export function buildRestartRequestUnconfirmedTelemetry(errorMessage: string): BrowserTelemetryEventInput {
  return {
    phase: "restart",
    eventCode: "browser.user_action.restart_request_unconfirmed",
    message: "Restart confirmation was not received; keeping pending restart feedback.",
    level: "warning",
    fields: {
      action: "restart",
      source: "app_shell",
      errorMessage,
    },
  };
}

type LifecycleControlAction = "shutdown" | "force_shutdown" | "restart";

type LifecycleControlResponseLike = {
  accepted?: boolean;
  completed?: boolean;
  commandId?: string;
  message?: string;
  operation?: string;
};

export function buildLifecycleControlResponseTelemetry(
  action: LifecycleControlAction,
  response: LifecycleControlResponseLike,
): BrowserTelemetryEventInput {
  const accepted = response.accepted !== false;
  const phase = action === "restart" ? "restart" : "shutdown";
  const suffix = accepted ? "accepted" : "rejected";
  return {
    phase,
    eventCode: `browser.user_action.${action}_request_${suffix}`,
    message: accepted
      ? "Launcher accepted the lifecycle control request."
      : "Launcher rejected the lifecycle control request.",
    level: accepted ? "info" : "warning",
    fields: {
      action,
      source: "app_shell",
      accepted,
      completed: Boolean(response.completed),
      commandId: String(response.commandId || ""),
      operation: String(response.operation || ""),
      responseMessage: String(response.message || ""),
    },
  };
}

export function shutdownRequestUnconfirmedBody(lang: string): string {
  return lang === "en"
    ? "The close flow has started, but this window did not receive a final confirmation yet. The workbench is still checking the runtime state."
    : "关闭流程已经开始，但这个窗口还没有收到最终确认。工作台正在继续检查运行状态。";
}

export function restartRequestUnconfirmedBody(lang: string): string {
  return lang === "en"
    ? "The restart flow has started, but this window did not receive a final confirmation yet. The workbench is still checking the runtime state."
    : "重启流程已经开始，但这个窗口还没有收到最终确认。工作台正在继续检查运行状态。";
}

export function restartActiveWorkBlockedMessage(lang: string, activeWorkDetails: string): string {
  const details = activeWorkDetails.trim();
  if (lang === "en") {
    return [
      "Vibelution cannot restart while work is still running.",
      details ? `Running now: ${details}` : "",
      "Wait for the task to finish or stop it first.",
    ].filter(Boolean).join("\n\n");
  }
  return [
    "有进行中的任务，无法重启 Vibelution。",
    details ? `正在运行：${details}` : "",
    "请等待任务完成，或先停止任务。",
  ].filter(Boolean).join("\n\n");
}

export function shutdownActiveWorkBlockedMessage(lang: string, activeWorkDetails: string): string {
  const details = activeWorkDetails.trim();
  if (lang === "en") {
    return [
      "Vibelution cannot close while work is still running.",
      details ? `Running now: ${details}` : "",
      "Wait for the task to finish or stop it first.",
    ].filter(Boolean).join("\n\n");
  }
  return [
    "有进行中的任务，无法关闭 Vibelution。",
    details ? `正在运行：${details}` : "",
    "请等待任务完成，或先停止任务。",
  ].filter(Boolean).join("\n\n");
}

function runtimeBlockedDetail(error: unknown): RuntimeControlBlockedDetail | null {
  if (!(error instanceof Error)) {
    return null;
  }
  try {
    const parsed = JSON.parse(error.message) as { detail?: RuntimeControlBlockedDetail };
    const detail = parsed?.detail;
    return detail && typeof detail === "object" ? detail : null;
  } catch {
    return null;
  }
}

export function shutdownLocallyCompleteBody(lang: string): string {
  return lang === "en"
    ? "The backend is no longer reachable, so the close flow has already passed the point where this window can receive a final confirmation. You can close this remaining window."
    : "后端已经不可达，关闭流程已经越过这个窗口能收到最终确认的阶段。可以直接关闭这个残留窗口。";
}

export function buildShutdownLocallyCompleteTelemetry(reason: string): BrowserTelemetryEventInput {
  return {
    phase: "shutdown",
    eventCode: "browser.user_action.shutdown_locally_completed",
    message: "Shutdown was inferred locally after the backend became unreachable.",
    level: "info",
    fields: {
      action: "shutdown",
      source: "app_shell",
      reason,
    },
  };
}

function isFrontendOrphanedWorkbench(workbench: RuntimeSummary["workbench"] | null | undefined): boolean {
  const lifecycleConsistency = String(workbench?.lifecycleConsistency ?? "").trim().toLowerCase();
  return Boolean(workbench?.frontendOrphaned) || lifecycleConsistency === "orphaned_browser";
}

function isShutdownResidualFrontendFailure(workbench: RuntimeSummary["workbench"] | null | undefined): boolean {
  if (workbench?.desiredState !== "closed" || workbench?.phase !== "failed") {
    return false;
  }
  if (isFrontendOrphanedWorkbench(workbench)) {
    return true;
  }
  const failureMessage = String(workbench?.failureMessage ?? "").trim().toLowerCase();
  return failureMessage.includes("frontend window is still open")
    || failureMessage.includes("no backend service is reachable");
}

export function shouldTreatShutdownAsLocallyComplete({
  shutdownRequested,
  backendState,
  backendUnavailable,
  runtimeSummaryUnavailable,
  workbench,
}: {
  shutdownRequested: boolean;
  backendState: string;
  backendUnavailable?: boolean;
  runtimeSummaryUnavailable: boolean;
  workbench?: RuntimeSummary["workbench"] | null;
}): boolean {
  if (!shutdownRequested) {
    return false;
  }
  if (isFrontendOrphanedWorkbench(workbench)) {
    return true;
  }
  if (isShutdownResidualFrontendFailure(workbench)) {
    return true;
  }
  return (backendState === "offline" || Boolean(backendUnavailable)) && runtimeSummaryUnavailable;
}

export function AppShell() {
  const { lang, t, statusLabel } = useShellI18n();
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();
  const [shutdownOpen, setShutdownOpen] = useState(false);
  const [shutdownTitle, setShutdownTitle] = useState("");
  const [shutdownDetail, setShutdownDetail] = useState("");
  const [shutdownSettled, setShutdownSettled] = useState(false);
  const [shutdownRequested, setShutdownRequested] = useState(false);
  const [restartRequested, setRestartRequested] = useState(false);
  const [lifecycleAction, setLifecycleAction] = useState<"shutdown" | "restart" | "">("");
  const [lifecycleCommandId, setLifecycleCommandId] = useState("");
  const [lifecycleCancelPending, setLifecycleCancelPending] = useState(false);
  const [utilityOpen, setUtilityOpen] = useState(false);
  const [lifecycleMenuOpen, setLifecycleMenuOpen] = useState(false);
  const [statusGuideOpen, setStatusGuideOpen] = useState(false);
  const [clockNow, setClockNow] = useState(() => Date.now());
  const [theme, setTheme] = useState(() => readStoredWorkbenchTheme());
  const [frontendVisible, setFrontendVisible] = useState(
    () => (typeof document === "undefined" ? true : document.visibilityState === "visible"),
  );
  const [frontendOnline, setFrontendOnline] = useState(
    () => (typeof navigator === "undefined" ? true : navigator.onLine),
  );
  const [frontendRefreshRequested, setFrontendRefreshRequested] = useState(false);
  const [shellStartupDataReady, setShellStartupDataReady] = useState(false);
  const shutdownPromiseRef = useRef<Promise<void> | null>(null);
  const restartPromiseRef = useRef<Promise<void> | null>(null);
  const lifecycleRequestSeqRef = useRef(0);
  const lifecycleOverlayDismissedRef = useRef(false);
  const utilityMenuRef = useRef<HTMLDivElement | null>(null);
  const lifecycleMenuRef = useRef<HTMLDivElement | null>(null);
  const shutdownLocalCompletionLoggedRef = useRef(false);
  const telemetrySeqRef = useRef(0);
  const pageInstanceIdRef = useRef(getPageInstanceId());
  const lastRouterLocationDesyncTargetRef = useRef<string | null>(null);
  const startupWarmupTelemetryStateRef = useRef<"active" | "inactive" | null>(null);
  const apiFailureTelemetrySeenRef = useRef(new Map<string, number>());
  const pagehideAtMsRef = useRef(0);
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
  });
  const shellStartupWarmupActive = useStartupWarmup(shellStartupDataReady);
  const shellPollingVisible = frontendVisible || shellStartupWarmupActive;
  const lifecycleControlActive = shutdownOpen || shutdownRequested || restartRequested;
  const runtimeRefetchInterval = resolvePollingInterval(
    shellPollingVisible,
    lifecycleControlActive ? 1_000 : 5_000,
    {
      backgroundMs: lifecycleControlActive ? 1_000 : 30_000,
      force: lifecycleControlActive,
    },
  );
  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchJson<RuntimeSummary>("/api/runtime/summary"),
    refetchInterval: runtimeRefetchInterval,
    refetchIntervalInBackground: shellStartupWarmupActive,
  });
  const backendHealthQuery = useQuery({
    queryKey: queryKeys.backendHealth(),
    queryFn: () =>
      fetchJson<BackendHealth>("/api/health", {
        cache: "no-store",
      }),
    refetchInterval: runtimeRefetchInterval,
    refetchIntervalInBackground: shellStartupWarmupActive,
    staleTime: 0,
    retry: false,
  });
  useEffect(() => {
    if (configQuery.data && runtimeQuery.data && backendHealthQuery.data) {
      setShellStartupDataReady(true);
    }
  }, [backendHealthQuery.data, configQuery.data, runtimeQuery.data]);

  const workbench = runtimeQuery.data?.workbench;
  const lifecycleProof = runtimeQuery.data?.lifecycleProof;
  const shutdownInFlight = workbench?.desiredState === "closed" && workbench?.observedState !== "closed";
  const chatEnabled = isWorkbenchDomainEnabled(configQuery.data, "chat");
  const supervisedEvolutionEnabled = isWorkbenchModeEnabled(configQuery.data, "supervised_evolution");
  const selfEvolutionEnabled = isWorkbenchModeEnabled(configQuery.data, "self_evolution");
  const refreshFrontendLabel = lang === "en" ? "Refresh frontend" : "刷新前端";
  const lifecycleMenuLabel = lang === "en" ? "Workbench power actions" : "工作台电源操作";
  const closeWorkbenchLabel = lang === "en" ? "Close workbench" : "关闭工作台";
  const forceCloseWorkbenchLabel = lang === "en" ? "Force close workbench" : "强制关闭工作台";
  const restartWorkbenchLabel = lang === "en" ? "Restart workbench" : "重启工作台";
  const cancelShutdownLabel = lang === "en" ? "Cancel close" : "取消关闭";
  const cancelRestartLabel = lang === "en" ? "Cancel restart" : "取消重启";
  const cancellingLifecycleLabel = lang === "en" ? "Cancelling..." : "正在取消...";
  const themeToggleLabel = theme === "dark" ? t("switchToLightTheme") : t("switchToDarkTheme");
  const shutdownHeading = lang === "en" ? "Closing workbench" : "正在关闭工作台";
  const shutdownBody = lang === "en"
    ? "Please keep this window open. The runtime manager will close the backend and app window."
    : "请先保持这个窗口打开。运行时管理器会负责关闭后端和应用窗口。";
  const shutdownErrorBody = lang === "en"
    ? "The runtime manager could not close the workbench. Check the launcher and runtime-manager logs."
    : "运行时管理器没有成功关闭工作台。请检查 launcher 和 runtime-manager 日志。";
  const forceShutdownHeading = lang === "en" ? "Force closing workbench" : "正在强制关闭工作台";
  const forceShutdownBody = lang === "en"
    ? "The runtime manager is terminating the managed backend and app window."
    : "运行时管理器正在终止受管后端和工作台窗口。";
  const shutdownUnconfirmedBody = shutdownRequestUnconfirmedBody(lang);
  const shutdownLocallyCompleteTitle = lang === "en" ? "Workbench backend stopped" : "工作台后端已停止";
  const shutdownLocallyCompleteDetail = shutdownLocallyCompleteBody(lang);
  const restartHeading = lang === "en" ? "Restarting workbench" : "正在重启工作台";
  const restartBody = lang === "en"
    ? "Please keep this window open. The runtime manager is stopping the old backend and starting a fresh workbench."
    : "请先保持这个窗口打开。运行时管理器正在停稳旧后端并重新拉起工作台。";
  const restartCompleteTitle = lang === "en" ? "Workbench restarted" : "工作台已重启";
  const restartCompleteBody = lang === "en"
    ? "The backend and app window are reachable again."
    : "后端和应用窗口已经重新可达。";
  const restartErrorBody = lang === "en"
    ? "The runtime manager could not restart the workbench. Check the launcher and runtime-manager logs."
    : "运行时管理器没有成功重启工作台。请检查 launcher 和 runtime-manager 日志。";
  const restartUnconfirmedBody = restartRequestUnconfirmedBody(lang);
  const workbenchCloseGuardMessage = projectWindowCloseGuardMessage(lang, "workbench");
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const timezone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || (lang === "en" ? "Local time" : "本地时间"),
    [lang],
  );
  const clockFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        weekday: "long",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: true,
      }),
    [locale],
  );
  const frontendState = deriveFrontendSystemState({
    online: frontendOnline,
    visible: frontendVisible,
  });
  const backendState = deriveBackendSystemState({
    isPending: backendHealthQuery.isPending,
    hasData: Boolean(backendHealthQuery.data),
    isError: backendHealthQuery.isError,
    health: backendHealthQuery.data,
  });
  const runtimeControllerState = deriveRuntimeControllerState(runtimeQuery.data);
  const startupProgress = deriveStartupProgressState(runtimeQuery.data, lang);
  const startupLoadingProgress = deriveStartupLoadingState(
    {
      configPending: configQuery.isPending && !configQuery.data,
      runtimePending: runtimeQuery.isPending && !runtimeQuery.data,
      backendPending: backendHealthQuery.isPending && !backendHealthQuery.data,
      configError: configQuery.isError && !configQuery.data,
      runtimeError: runtimeQuery.isError && !runtimeQuery.data,
      backendError: backendHealthQuery.isError && !backendHealthQuery.data,
    },
    lang,
  );
  const startupLoadingShouldBlock =
    startupLoadingProgress.active
    && startupLoadingProgress.tone === "failed"
    && !configQuery.data
    && !runtimeQuery.data
    && !backendHealthQuery.data;
  const startupDisconnectedProgress = deriveStartupDisconnectedState(
    {
      startupActive: startupProgress.active,
      runtimeUnavailable: runtimeQuery.isError || runtimeQuery.isRefetchError,
      backendUnavailable: backendHealthQuery.isError || backendHealthQuery.isRefetchError,
    },
    lang,
  );
  const startupPanel = startupProgress.active
    ? startupDisconnectedProgress.active
      ? startupDisconnectedProgress
      : startupProgress
    : startupLoadingShouldBlock
      ? startupLoadingProgress
      : { active: false, title: "", detail: "", stage: "", tone: "idle" as const };
  const shutdownLocallyComplete = shouldTreatShutdownAsLocallyComplete({
    shutdownRequested,
    backendState,
    backendUnavailable: backendHealthQuery.isError || backendHealthQuery.isRefetchError,
    runtimeSummaryUnavailable: runtimeQuery.isError || runtimeQuery.isRefetchError,
    workbench,
  });
  const forceCloseVisible =
    runtimeControllerState === "failed"
    || shutdownInFlight
    || String(workbench?.observedState ?? "").toLowerCase() === "open"
    || String(workbench?.lifecycleConsistency ?? "").toLowerCase() !== "consistent";
  const activeWorkIndicator = deriveActiveWorkIndicator(runtimeQuery.data, lang);
  const activeWorkDetailsTitle = activeWorkIndicator?.items.map((item) => item.detail).join(" · ") ?? "";
  const currentTime = clockFormatter.format(clockNow);
  const buildId = __VIBELUTION_BUILD_ID__;
  const closeUtilityMenu = useCallback(() => {
    setUtilityOpen(false);
  }, []);

  const frontendStateLabel = {
    connected: t("systemFrontend_connected"),
    background: t("systemFrontend_background"),
    offline: t("systemFrontend_offline"),
  }[frontendState];
  const backendStateLabel = {
    healthy: t("backendHealthy"),
    checking: t("backendChecking"),
    offline: t("backendOffline"),
    unhealthy: t("backendUnhealthy"),
  }[backendState];
  const runtimeControllerLabel = {
    managed: t("systemRuntime_managed"),
    closing: t("systemRuntime_closing"),
    unmanaged: t("systemRuntime_unmanaged"),
    failed: t("systemRuntime_failed"),
  }[runtimeControllerState];
  const emitBrowserTelemetry = useCallback((
    payload: BrowserTelemetryEventInput,
    options?: { preferBeacon?: boolean },
  ) => {
    telemetrySeqRef.current += 1;
    postBrowserTelemetry(
      {
        ...payload,
        fields: {
          pageInstanceId: pageInstanceIdRef.current,
          seq: telemetrySeqRef.current,
          ...collectBrowserPageSnapshot(),
          ...(payload.fields ?? {}),
        },
      },
      options,
    );
  }, []);

  const recoverRouterLocationDesync = useCallback((trigger: string) => {
    const recovery = routerLocationDesyncRecoveryPlan(window.location, location);
    if (!recovery) {
      lastRouterLocationDesyncTargetRef.current = null;
      return;
    }

    const { target } = recovery;
    const duplicateTarget = lastRouterLocationDesyncTargetRef.current === target;
    lastRouterLocationDesyncTargetRef.current = target;
    const recoveryFields = {
      trigger,
      target,
      duplicateTarget,
      browserPathnameBefore: window.location.pathname,
      browserSearchBefore: window.location.search,
      browserHashBefore: window.location.hash,
      routerPathnameBefore: location.pathname,
      routerSearchBefore: location.search,
      routerHashBefore: location.hash,
      restoreTarget: recovery.restoreTarget,
    };
    try {
      window.history.replaceState(window.history.state, "", recovery.restoreTarget);
    } catch {
      // Keep the recovery best-effort; navigate still attempts to bring the router to the browser target.
    }
    navigate(target, { replace: true });
    const emitRecoveredTelemetry = () => {
      emitBrowserTelemetry({
        phase: "navigation",
        eventCode: "browser.router_location_desync.recovered",
        message: `Recovered browser/router route desync to ${target}`,
        level: duplicateTarget ? "info" : "warning",
        fields: recoveryFields,
      });
    };
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => window.setTimeout(emitRecoveredTelemetry, 0));
    } else {
      window.setTimeout(emitRecoveredTelemetry, 0);
    }
  }, [emitBrowserTelemetry, location, navigate]);

  const cancelSupersededLifecycleCommand = useCallback((commandId: string, action: "shutdown" | "restart") => {
    const normalizedCommandId = commandId.trim();
    if (!normalizedCommandId) {
      return;
    }
    void cancelRuntimeLifecycleCommand({
      commandId: normalizedCommandId,
      operation: action === "restart" ? "restart" : "stop",
      source: "app_shell_superseded_request",
    })
      .then((payload) => {
        emitBrowserTelemetry(
          {
            phase: action === "restart" ? "restart" : "shutdown",
            eventCode: "browser.user_action.lifecycle_wait_cancel_superseded_command",
            message: "A lifecycle command returned after the overlay was cancelled and was cancelled through the queue.",
            fields: {
              action,
              source: "app_shell",
              commandId: normalizedCommandId,
              cancelledBackendCommand: payload.cancelled,
              cancelStatus: payload.status,
            },
          },
          { preferBeacon: true },
        );
      })
      .catch((error) => {
        emitBrowserTelemetry(
          {
            phase: action === "restart" ? "restart" : "shutdown",
            eventCode: "browser.user_action.lifecycle_wait_cancel_superseded_failed",
            message: "A superseded lifecycle command could not be cancelled through the queue.",
            level: "warning",
            fields: {
              action,
              source: "app_shell",
              commandId: normalizedCommandId,
              errorMessage: error instanceof Error ? error.message : String(error || ""),
            },
          },
          { preferBeacon: true },
        );
      });
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    const warmupState = shellStartupWarmupActive ? "active" : "inactive";
    if (startupWarmupTelemetryStateRef.current === warmupState) {
      return;
    }
    const previousWarmupState = startupWarmupTelemetryStateRef.current;
    startupWarmupTelemetryStateRef.current = warmupState;
    emitBrowserTelemetry({
      phase: "startup",
      eventCode: shellStartupWarmupActive
        ? "browser.startup_background_warmup.active"
        : "browser.startup_background_warmup.inactive",
      message: shellStartupWarmupActive
        ? "Startup background warmup is keeping shell polling alive."
        : "Startup background warmup is inactive.",
      fields: {
        startupDataReady: shellStartupDataReady,
        frontendVisible,
        warmupState,
        previousWarmupState: previousWarmupState ?? "",
        telemetryReason: previousWarmupState === null ? "initial" : "state_changed",
      },
    });
  }, [emitBrowserTelemetry, frontendVisible, shellStartupDataReady, shellStartupWarmupActive]);

  const beginShutdown = useCallback(() => {
    if (restartPromiseRef.current || restartRequested) {
      return restartPromiseRef.current ?? Promise.resolve();
    }
    if (shutdownPromiseRef.current) {
      return shutdownPromiseRef.current;
    }

    lifecycleRequestSeqRef.current += 1;
    const requestSeq = lifecycleRequestSeqRef.current;
    const task = (async () => {
      lifecycleOverlayDismissedRef.current = false;
      setShutdownRequested(true);
      setRestartRequested(false);
      setShutdownSettled(false);
      setShutdownOpen(true);
      setLifecycleAction("shutdown");
      setLifecycleCommandId("");
      setLifecycleCancelPending(false);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(shutdownBody);
      shutdownLocalCompletionLoggedRef.current = false;
      emitBrowserTelemetry(buildShutdownRequestedTelemetry(), { preferBeacon: true });

      const payload = await stopLauncherBundle();
      if (requestSeq !== lifecycleRequestSeqRef.current) {
        if (payload.commandId) {
          cancelSupersededLifecycleCommand(payload.commandId, "shutdown");
        }
        return;
      }
      emitBrowserTelemetry(buildLifecycleControlResponseTelemetry("shutdown", payload), { preferBeacon: true });
      if (payload.commandId) {
        setLifecycleCommandId(payload.commandId);
      }
      if (payload.message) {
        setShutdownDetail(payload.message);
      }
    })().catch((error) => {
      const errorMessage = error instanceof Error ? error.message : String(error || "");
      if (requestSeq !== lifecycleRequestSeqRef.current) {
        return;
      }
      const blocked = runtimeBlockedDetail(error);
      if (blocked?.code === "active_work_stop_blocked" || blocked?.code === "active_work_requires_confirmation") {
        lifecycleOverlayDismissedRef.current = false;
        const blockedDetails = blocked.activeWorkRuns
          ?.map((item) => [item.kind, item.status, item.runId || item.sessionId].filter(Boolean).join(" · "))
          .filter(Boolean)
          .join(" · ") ?? "";
        setShutdownRequested(false);
        setRestartRequested(false);
        setShutdownOpen(true);
        setShutdownSettled(false);
        setLifecycleAction("shutdown");
        setLifecycleCommandId("");
        setLifecycleCancelPending(false);
        setShutdownTitle(shutdownHeading);
        setShutdownDetail(shutdownActiveWorkBlockedMessage(lang, blockedDetails || activeWorkDetailsTitle));
        emitBrowserTelemetry(
          {
            phase: "shutdown",
            eventCode: "browser.user_action.shutdown_blocked_active_work",
            message: "Shutdown was blocked because active work is running.",
            level: "warning",
            fields: {
              action: "shutdown",
              source: "app_shell",
              activeWorkCount: blocked.activeWorkRuns?.length ?? 0,
            },
          },
          { preferBeacon: true },
        );
        return;
      }
      setShutdownRequested(true);
      setRestartRequested(false);
      setShutdownOpen(true);
      setShutdownSettled(false);
      setLifecycleAction("shutdown");
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(shutdownUnconfirmedBody);
      emitBrowserTelemetry(buildShutdownRequestUnconfirmedTelemetry(errorMessage), { preferBeacon: true });
    }).finally(() => {
      shutdownPromiseRef.current = null;
    });

    shutdownPromiseRef.current = task;
    return task;
  }, [
    activeWorkDetailsTitle,
    cancelSupersededLifecycleCommand,
    emitBrowserTelemetry,
    lang,
    restartRequested,
    shutdownBody,
    shutdownHeading,
    shutdownUnconfirmedBody,
  ]);

  const beginForceShutdown = useCallback(() => {
    if (restartPromiseRef.current || restartRequested) {
      return restartPromiseRef.current ?? Promise.resolve();
    }

    lifecycleRequestSeqRef.current += 1;
    const requestSeq = lifecycleRequestSeqRef.current;
    shutdownPromiseRef.current = null;
    const task = (async () => {
      lifecycleOverlayDismissedRef.current = false;
      setShutdownRequested(true);
      setRestartRequested(false);
      setShutdownSettled(false);
      setShutdownOpen(true);
      setLifecycleAction("shutdown");
      setLifecycleCommandId("");
      setLifecycleCancelPending(false);
      setShutdownTitle(forceShutdownHeading);
      setShutdownDetail(forceShutdownBody);
      shutdownLocalCompletionLoggedRef.current = false;
      emitBrowserTelemetry(
        {
          phase: "shutdown",
          eventCode: "browser.user_action.force_shutdown_requested",
          message: "User requested a force close for the managed workbench.",
          level: "warning",
          fields: {
            action: "force_shutdown",
            source: "app_shell",
            activeWorkCount: activeWorkIndicator?.count ?? 0,
          },
        },
        { preferBeacon: true },
      );

      const payload = await forceStopLauncherBundle();
      if (requestSeq !== lifecycleRequestSeqRef.current) {
        return;
      }
      emitBrowserTelemetry(buildLifecycleControlResponseTelemetry("force_shutdown", payload), { preferBeacon: true });
      if (payload.commandId) {
        setLifecycleCommandId(payload.commandId);
      }
      if (payload.message) {
        setShutdownDetail(payload.message);
      }
    })().catch((error) => {
      if (requestSeq !== lifecycleRequestSeqRef.current) {
        return;
      }
      const errorMessage = error instanceof Error ? error.message : String(error || "");
      setShutdownRequested(true);
      setRestartRequested(false);
      setShutdownOpen(true);
      setShutdownSettled(false);
      setLifecycleAction("shutdown");
      setShutdownTitle(forceShutdownHeading);
      setShutdownDetail(errorMessage || shutdownErrorBody);
      emitBrowserTelemetry(
        {
          phase: "shutdown",
          eventCode: "browser.user_action.force_shutdown_unconfirmed",
          message: "Force shutdown request could not be confirmed by the launcher API.",
          level: "error",
          fields: {
            action: "force_shutdown",
            source: "app_shell",
            errorMessage,
          },
        },
        { preferBeacon: true },
      );
    }).finally(() => {
      if (shutdownPromiseRef.current === task) {
        shutdownPromiseRef.current = null;
      }
    });

    shutdownPromiseRef.current = task;
    return task;
  }, [
    activeWorkIndicator?.count,
    emitBrowserTelemetry,
    forceShutdownBody,
    forceShutdownHeading,
    restartRequested,
    shutdownErrorBody,
  ]);

  const beginRestart = useCallback(() => {
    if (shutdownPromiseRef.current || shutdownRequested) {
      return shutdownPromiseRef.current ?? Promise.resolve();
    }
    if (restartPromiseRef.current) {
      return restartPromiseRef.current;
    }

    lifecycleRequestSeqRef.current += 1;
    const requestSeq = lifecycleRequestSeqRef.current;
    const task = (async () => {
      lifecycleOverlayDismissedRef.current = false;
      setRestartRequested(true);
      setShutdownRequested(false);
      setShutdownSettled(false);
      setShutdownOpen(true);
      setLifecycleAction("restart");
      setLifecycleCommandId("");
      setLifecycleCancelPending(false);
      setShutdownTitle(restartHeading);
      setShutdownDetail(restartBody);
      emitBrowserTelemetry(buildRestartRequestedTelemetry(), { preferBeacon: true });

      const payload = await restartLauncherBundle();
      if (requestSeq !== lifecycleRequestSeqRef.current) {
        if (payload.commandId) {
          cancelSupersededLifecycleCommand(payload.commandId, "restart");
        }
        return;
      }
      emitBrowserTelemetry(buildLifecycleControlResponseTelemetry("restart", payload), { preferBeacon: true });
      if (payload.commandId) {
        setLifecycleCommandId(payload.commandId);
      }
      if (payload.message) {
        setShutdownDetail(payload.message);
      }
    })().catch((error) => {
      if (requestSeq !== lifecycleRequestSeqRef.current) {
        return;
      }
      const blocked = runtimeBlockedDetail(error);
      if (blocked?.code === "active_work_restart_blocked" || blocked?.code === "active_work_requires_confirmation") {
        lifecycleOverlayDismissedRef.current = false;
        const blockedDetails = blocked.activeWorkRuns
          ?.map((item) => [item.kind, item.status, item.runId || item.sessionId].filter(Boolean).join(" · "))
          .filter(Boolean)
          .join(" · ") ?? "";
        setRestartRequested(false);
        setShutdownRequested(false);
        setShutdownOpen(true);
        setShutdownSettled(false);
        setLifecycleAction("restart");
        setLifecycleCommandId("");
        setLifecycleCancelPending(false);
        setShutdownTitle(restartHeading);
        setShutdownDetail(restartActiveWorkBlockedMessage(lang, blockedDetails || activeWorkDetailsTitle));
        emitBrowserTelemetry(
          {
            phase: "restart",
            eventCode: "browser.user_action.restart_blocked_active_work",
            message: "Restart was blocked because active work is running.",
            level: "warning",
            fields: {
              action: "restart",
              source: "app_shell",
              activeWorkCount: blocked.activeWorkRuns?.length ?? 0,
            },
          },
          { preferBeacon: true },
        );
        return;
      }
      const errorMessage = error instanceof Error ? error.message : String(error || "");
      setRestartRequested(true);
      setShutdownRequested(false);
      setShutdownOpen(true);
      setShutdownSettled(false);
      setLifecycleAction("restart");
      setShutdownTitle(restartHeading);
      setShutdownDetail(restartUnconfirmedBody);
      emitBrowserTelemetry(buildRestartRequestUnconfirmedTelemetry(errorMessage), { preferBeacon: true });
    }).finally(() => {
      restartPromiseRef.current = null;
    });

    restartPromiseRef.current = task;
    return task;
  }, [
    activeWorkDetailsTitle,
    cancelSupersededLifecycleCommand,
    emitBrowserTelemetry,
    lang,
    restartBody,
    restartHeading,
    restartUnconfirmedBody,
    shutdownRequested,
  ]);

  const cancelLifecycleWait = useCallback(() => {
    if (lifecycleCancelPending) {
      return;
    }
    const action = lifecycleAction || (restartRequested ? "restart" : "shutdown");
    const commandId = lifecycleCommandId.trim();
    lifecycleRequestSeqRef.current += 1;
    setLifecycleCancelPending(true);
    emitBrowserTelemetry(
      {
        phase: action === "restart" ? "restart" : "shutdown",
        eventCode: "browser.user_action.lifecycle_wait_cancel_requested",
        message: "User cancelled the current lifecycle wait overlay.",
        fields: {
          action,
          source: "app_shell",
          commandId,
          hadQueuedCommand: Boolean(commandId),
        },
      },
      { preferBeacon: true },
    );

    const resetOverlay = () => {
      lifecycleOverlayDismissedRef.current = true;
      shutdownPromiseRef.current = null;
      restartPromiseRef.current = null;
      setShutdownRequested(false);
      setRestartRequested(false);
      setShutdownOpen(false);
      setShutdownSettled(false);
      setShutdownTitle("");
      setShutdownDetail("");
      setLifecycleAction("");
      setLifecycleCommandId("");
      setLifecycleCancelPending(false);
    };

    if (!commandId) {
      emitBrowserTelemetry(
        {
          phase: action === "restart" ? "restart" : "shutdown",
          eventCode: "browser.user_action.lifecycle_wait_cancel_completed",
          message: "Lifecycle wait overlay was cancelled locally.",
          fields: {
            action,
            source: "app_shell",
            cancelledBackendCommand: false,
          },
        },
        { preferBeacon: true },
      );
      resetOverlay();
      return;
    }

    const cancellation = cancelRuntimeLifecycleCommand({
      commandId,
      operation: action === "restart" ? "restart" : "stop",
      source: "app_shell",
    })
      .then((payload) => {
        emitBrowserTelemetry(
          {
            phase: action === "restart" ? "restart" : "shutdown",
            eventCode: "browser.user_action.lifecycle_wait_cancel_completed",
            message: "Lifecycle wait cancellation request completed.",
            fields: {
              action,
              source: "app_shell",
              commandId,
              cancelledBackendCommand: payload.cancelled,
              cancelStatus: payload.status,
            },
          },
          { preferBeacon: true },
        );
      })
      .catch((error) => {
        emitBrowserTelemetry(
          {
            phase: action === "restart" ? "restart" : "shutdown",
            eventCode: "browser.user_action.lifecycle_wait_cancel_failed",
            message: "Lifecycle wait cancellation request failed.",
            level: "warning",
            fields: {
              action,
              source: "app_shell",
              commandId,
              errorMessage: error instanceof Error ? error.message : String(error || ""),
            },
          },
          { preferBeacon: true },
        );
      });
    resetOverlay();
    void cancellation;
  }, [
    emitBrowserTelemetry,
    lifecycleAction,
    lifecycleCancelPending,
    lifecycleCommandId,
    restartRequested,
  ]);

  const refreshFrontend = useCallback(() => {
    setFrontendRefreshRequested(true);
    emitBrowserTelemetry(
      {
        phase: "refresh",
        eventCode: "browser.user_action.frontend_refresh_requested",
        message: "User requested frontend refresh.",
        fields: {
          action: "frontend_refresh",
        },
      },
      { preferBeacon: true },
    );
    window.setTimeout(() => window.location.reload(), 0);
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    const closeBlocked = shouldBlockWorkbenchWindowClose({
      controlledLifecycleOperationInFlight: hasRecentControlledProjectLifecycleOperation(),
      frontendRefreshRequested,
      restartRequested,
      runtimeControllerState,
      shutdownRequested,
    });
    if (!closeBlocked) {
      return;
    }

    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (hasRecentControlledProjectLifecycleOperation()) {
        return;
      }
      emitBrowserTelemetry(
        buildProjectWindowCloseBlockedTelemetry({
          surface: "workbench",
          runtimeControllerState,
        }),
        { preferBeacon: true },
      );
      applyBeforeUnloadProjectCloseGuard(event, workbenchCloseGuardMessage);
    }

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [
    emitBrowserTelemetry,
    frontendRefreshRequested,
    restartRequested,
    runtimeControllerState,
    shutdownRequested,
    workbenchCloseGuardMessage,
  ]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next = nextWorkbenchTheme(current);
      writeStoredWorkbenchTheme(next);
      return next;
    });
  }, []);

  useEffect(() => {
    applyWorkbenchDocumentLanguage(document, lang);
    document.title = t("appTitle");
  }, [lang, t]);

  useEffect(() => {
    if (!utilityOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (target instanceof Node && utilityMenuRef.current?.contains(target)) {
        return;
      }
      setUtilityOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setUtilityOpen(false);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [utilityOpen]);

  useEffect(() => {
    if (!lifecycleMenuOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (target instanceof Node && lifecycleMenuRef.current?.contains(target)) {
        return;
      }
      setLifecycleMenuOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setLifecycleMenuOpen(false);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [lifecycleMenuOpen]);

  useEffect(() => {
    setFetchJsonFailureReporter((failure) => {
      if (shouldSuppressApiFailureTelemetry(failure, {
        shutdownRequested,
        restartRequested,
        runtimeControllerState,
        visibilityState: typeof document === "undefined" ? "visible" : document.visibilityState,
        pagehideAtMs: pagehideAtMsRef.current,
      })) {
        return;
      }
      if (shouldThrottleApiFailureTelemetry(failure, apiFailureTelemetrySeenRef.current)) {
        return;
      }
      emitBrowserTelemetry({
        phase: "api",
        eventCode: apiFailureTelemetryEventCode(failure),
        message: `${failure.method} ${failure.endpoint} failed${failure.status === null ? "" : ` (${failure.status})`}`,
        level: apiFailureTelemetryLevel(failure),
        fields: {
          endpoint: failure.endpoint,
          method: failure.method,
          status: failure.status,
          failureKind: failure.failureKind,
          failureMessage: failure.message,
        },
      });
    });
    return () => setFetchJsonFailureReporter(null);
  }, [emitBrowserTelemetry, restartRequested, runtimeControllerState, shutdownRequested]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClockNow(Date.now());
    }, 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    function handleVisibilityChange() {
      setFrontendVisible(document.visibilityState === "visible");
      emitBrowserTelemetry({
        phase: "lifecycle",
        eventCode: "browser.visibility.changed",
        message: `Visibility changed to ${document.visibilityState}`,
        fields: {
          visibilityState: document.visibilityState,
        },
      });
    }

    function handleOnline() {
      setFrontendOnline(true);
      emitBrowserTelemetry({
        phase: "network",
        eventCode: "browser.network.changed",
        message: "Browser is online",
        fields: {
          online: true,
        },
      });
    }

    function handleOffline() {
      setFrontendOnline(false);
      emitBrowserTelemetry({
        phase: "network",
        eventCode: "browser.network.changed",
        message: "Browser is offline",
        level: "warning",
        fields: {
          online: false,
        },
      });
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    let recoveryTimer: number | null = null;
    const scheduleRecovery = (trigger: string) => {
      if (recoveryTimer !== null) {
        window.clearTimeout(recoveryTimer);
      }
      recoveryTimer = window.setTimeout(() => {
        recoveryTimer = null;
        recoverRouterLocationDesync(trigger);
      }, ROUTER_LOCATION_DESYNC_RECOVERY_DELAY_MS);
    };

    const handleFocus = () => scheduleRecovery("window_focus");
    const handlePageShow = () => scheduleRecovery("pageshow");
    const handlePopState = () => scheduleRecovery("popstate");
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        scheduleRecovery("visibility_visible");
      }
    };

    window.addEventListener("focus", handleFocus);
    window.addEventListener("pageshow", handlePageShow);
    window.addEventListener("popstate", handlePopState);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    scheduleRecovery("app_shell_mounted");

    return () => {
      if (recoveryTimer !== null) {
        window.clearTimeout(recoveryTimer);
      }
      window.removeEventListener("focus", handleFocus);
      window.removeEventListener("pageshow", handlePageShow);
      window.removeEventListener("popstate", handlePopState);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [recoverRouterLocationDesync]);

  useEffect(() => {
    const snapshotTimer = window.setTimeout(() => {
      emitBrowserTelemetry({
        phase: "page",
        eventCode: "browser.page.snapshot",
        message: `Page snapshot for ${window.location.pathname || "/"}`,
        fields: {
          reason: "app_shell_mounted",
        },
      });
    }, 0);

    function handlePageHide(event: PageTransitionEvent) {
      pagehideAtMsRef.current = Date.now();
      emitBrowserTelemetry(
        {
          phase: "lifecycle",
          eventCode: "browser.page.hide",
          message: `Page hide at ${window.location.pathname || "/"}`,
          fields: {
            persisted: event.persisted,
          },
        },
        { preferBeacon: true },
      );
    }

    window.addEventListener("pagehide", handlePageHide);
    return () => {
      window.clearTimeout(snapshotTimer);
      window.removeEventListener("pagehide", handlePageHide);
    };
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    emitBrowserTelemetry({
      phase: "navigation",
      eventCode: "browser.route.changed",
      message: `React route changed to ${location.pathname || "/"}`,
      fields: {
        routerPathname: location.pathname,
        routerSearch: location.search,
        routerHash: location.hash,
        navigationType,
      },
    });
  }, [emitBrowserTelemetry, location.hash, location.pathname, location.search, navigationType]);

  useEffect(() => {
    if (!frontendVisible) {
      return;
    }

    function queryCacheSummary() {
      const queries = queryClient.getQueryCache().getAll();
      const activeQueries = queries.filter((query) => query.getObserversCount() > 0);
      const fetchingQueries = queries.filter((query) => query.state.fetchStatus === "fetching");
      return {
        queryCount: queries.length,
        activeQueryCount: activeQueries.length,
        fetchingQueryCount: fetchingQueries.length,
        staleQueryCount: queries.filter((query) => query.isStale()).length,
        sessionQueryCount: queries.filter((query) => String(query.queryKey[0] ?? "") === "sessions").length,
        logQueryCount: queries.filter((query) => String(query.queryKey[0] ?? "") === "logs").length,
      };
    }

    const emitMemorySample = (reason: string) => {
      emitBrowserTelemetry({
        phase: "memory",
        eventCode: "browser.memory.sampled",
        message: `Browser memory sampled: ${reason}`,
        fields: {
          reason,
          ...collectBrowserMemorySnapshot(),
          ...queryCacheSummary(),
        },
      });
    };

    const initialTimer = window.setTimeout(() => emitMemorySample("route_settled"), 1_000);
    const interval = frontendVisible
      ? window.setInterval(() => emitMemorySample("periodic"), BROWSER_MEMORY_SAMPLE_INTERVAL_MS)
      : null;
    return () => {
      window.clearTimeout(initialTimer);
      if (interval !== null) {
        window.clearInterval(interval);
      }
    };
  }, [emitBrowserTelemetry, frontendVisible, location.pathname, queryClient]);

  useEffect(() => {
    function handlePopState() {
      emitBrowserTelemetry({
        phase: "navigation",
        eventCode: "browser.history.pop_state",
        message: `popstate -> ${window.location.pathname || "/"}`,
      });
    }

    window.addEventListener("popstate", handlePopState);
    return () => {
      window.removeEventListener("popstate", handlePopState);
    };
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    const originalWarn = window.console.warn.bind(window.console) as Console["warn"];
    const originalError = window.console.error.bind(window.console) as Console["error"];

    window.console.warn = ((...args: Parameters<Console["warn"]>) => {
      emitBrowserTelemetry({
        phase: "console",
        eventCode: "browser.console.warn",
        message: summarizeConsoleArgs(args as unknown[], 240) || "Console warn",
        level: "warning",
        fields: {
          argsPreview: summarizeConsoleArgs(args as unknown[], 1200),
        },
      });
      originalWarn(...args);
    }) as Console["warn"];

    window.console.error = ((...args: Parameters<Console["error"]>) => {
      emitBrowserTelemetry({
        phase: "console",
        eventCode: "browser.console.error",
        message: summarizeConsoleArgs(args as unknown[], 240) || "Console error",
        level: "error",
        fields: {
          argsPreview: summarizeConsoleArgs(args as unknown[], 1200),
        },
      });
      originalError(...args);
    }) as Console["error"];

    return () => {
      window.console.warn = originalWarn;
      window.console.error = originalError;
    };
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    function handleWindowError(event: ErrorEvent) {
      const target = event.target;
      if (target instanceof Element && target !== document.documentElement && target !== document.body) {
        const resourceUrl = target instanceof HTMLLinkElement
          ? target.href
          : target instanceof HTMLScriptElement
            ? target.src
            : target instanceof HTMLImageElement
              ? target.currentSrc || target.src
              : target.getAttribute("src") || target.getAttribute("href") || "";

        emitBrowserTelemetry({
          phase: "error",
          eventCode: "browser.resource.error",
          message: resourceUrl ? `Resource failed to load: ${resourceUrl}` : "Resource failed to load",
          level: "error",
          fields: {
            resourceUrl,
            tagName: target.tagName.toLowerCase(),
          },
        });
        recoverFromBuiltAssetResourceError(resourceUrl, globalThis.window, emitBrowserTelemetry);
        return;
      }

      const stack = event.error instanceof Error ? event.error.stack || "" : "";
      emitBrowserTelemetry({
        phase: "error",
        eventCode: "browser.page.error",
        message: event.message || "Uncaught browser error",
        level: "error",
        fields: {
          filename: event.filename,
          lineno: event.lineno,
          colno: event.colno,
          stack: stack || summarizeConsoleArgs([event.error], 1200),
        },
      });
    }

    function handleUnhandledRejection(event: PromiseRejectionEvent) {
      emitBrowserTelemetry({
        phase: "error",
        eventCode: "browser.promise.rejected",
        message: summarizeConsoleArgs([event.reason], 240) || "Unhandled promise rejection",
        level: "error",
        fields: {
          reason: summarizeConsoleArgs([event.reason], 1200),
        },
      });
    }

    window.addEventListener("error", handleWindowError, true);
    window.addEventListener("unhandledrejection", handleUnhandledRejection);
    return () => {
      window.removeEventListener("error", handleWindowError, true);
      window.removeEventListener("unhandledrejection", handleUnhandledRejection);
    };
  }, [emitBrowserTelemetry]);

  useEffect(() => {
    if (shutdownLocallyComplete) {
      setShutdownOpen(true);
      setShutdownSettled(true);
      setShutdownTitle(shutdownLocallyCompleteTitle);
      setShutdownDetail(shutdownLocallyCompleteDetail);
      if (!shutdownLocalCompletionLoggedRef.current) {
        shutdownLocalCompletionLoggedRef.current = true;
        emitBrowserTelemetry(
          buildShutdownLocallyCompleteTelemetry(
            workbench?.frontendOrphaned || workbench?.lifecycleConsistency === "orphaned_browser"
              ? "frontend_orphaned"
              : "backend_unreachable",
          ),
          { preferBeacon: true },
        );
      }
      return;
    }

    if (!workbench) {
      return;
    }

    const closing = workbench.desiredState === "closed" && workbench.observedState !== "closed";
    const failed = (workbench.phase === "failed" && workbench.desiredState === "closed")
      || isFrontendOrphanedWorkbench(workbench);

    if (failed) {
      if (lifecycleOverlayDismissedRef.current) {
        return;
      }
      setShutdownRequested(false);
      setShutdownOpen(true);
      setShutdownSettled(true);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(workbench.failureMessage || shutdownErrorBody);
      return;
    }

    if (closing) {
      if (lifecycleOverlayDismissedRef.current) {
        return;
      }
      setShutdownOpen(true);
      setShutdownSettled(false);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(workbench.statusLine || shutdownBody);
      return;
    }

    if (!shutdownRequested) {
      return;
    }

    if (workbench.desiredState === "closed" && workbench.observedState === "closed") {
      if (lifecycleOverlayDismissedRef.current) {
        return;
      }
      setShutdownOpen(true);
      setShutdownSettled(true);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(workbench.statusLine || shutdownBody);
    }
  }, [
    emitBrowserTelemetry,
    shutdownBody,
    shutdownErrorBody,
    shutdownHeading,
    shutdownLocallyComplete,
    shutdownLocallyCompleteDetail,
    shutdownLocallyCompleteTitle,
    shutdownRequested,
    workbench,
  ]);

  useEffect(() => {
    if (!restartRequested || !workbench) {
      return;
    }

    const failed = workbench.phase === "failed";
    const ready = workbench.desiredState === "open"
      && workbench.observedState === "open"
      && workbench.backendHealthy
      && workbench.browserWindowAlive;

    if (failed) {
      if (lifecycleOverlayDismissedRef.current) {
        return;
      }
      setRestartRequested(false);
      setShutdownOpen(true);
      setShutdownSettled(true);
      setShutdownTitle(restartHeading);
      setShutdownDetail(workbench.failureMessage || restartErrorBody);
      return;
    }

    if (ready) {
      lifecycleOverlayDismissedRef.current = false;
      setRestartRequested(false);
      setShutdownOpen(true);
      setShutdownSettled(true);
      setShutdownTitle(restartCompleteTitle);
      setShutdownDetail(workbench.statusLine || restartCompleteBody);
      const timer = window.setTimeout(() => {
        setShutdownOpen(false);
      }, 1_600);
      return () => window.clearTimeout(timer);
    }

    if (lifecycleOverlayDismissedRef.current) {
      return;
    }
    setShutdownOpen(true);
    setShutdownSettled(false);
    setShutdownTitle(restartHeading);
    setShutdownDetail(workbench.statusLine || restartBody);
  }, [
    restartBody,
    restartCompleteBody,
    restartCompleteTitle,
    restartErrorBody,
    restartHeading,
    restartRequested,
    workbench,
  ]);

  const rightStatusCards: Array<{
    id: "frontend" | "backend" | "runtime";
    label: string;
    value: string;
    tone: SystemStatusTone;
  }> = [
    {
      id: "frontend",
      label: t("systemFrontend"),
      value: frontendStateLabel,
      tone: frontendSystemTone(frontendState),
    },
    {
      id: "backend",
      label: t("systemBackend"),
      value: backendStateLabel,
      tone: backendSystemTone(backendState),
    },
    {
      id: "runtime",
      label: t("systemRuntime"),
      value: runtimeControllerLabel,
      tone: runtimeControllerTone(runtimeControllerState),
    },
  ];
  const statusPriority = { failed: 0, caution: 1, running: 2, idle: 3 } satisfies Record<SystemStatusTone, number>;
  const primaryStatusCard = rightStatusCards.reduce((selected, item) =>
    statusPriority[item.tone] < statusPriority[selected.tone] ? item : selected,
  rightStatusCards[0]);
  const statusSummaryTitle = rightStatusCards.map((item) => `${item.label}: ${item.value}`).join(" · ");

  return (
    <div className={styles.shell} data-theme={theme} data-shell="workbench" data-browser-role="workbench">
      {startupPanel.active && !shutdownOpen ? (
        <div
          className={styles.startupOverlay}
          role="status"
          aria-live="polite"
          aria-busy={startupPanel.tone !== "failed"}
        >
          <div className={styles.startupPanel}>
            <div className={styles.startupSpinner} aria-hidden="true">
              <LoaderCircle
                size={24}
                className={startupPanel.tone === "failed" ? styles.shutdownIconStill : styles.shutdownIconSpin}
              />
            </div>
            <div className={styles.startupCopy}>
              <span className={styles.startupKicker}>{startupPanel.stage}</span>
              <strong>{startupPanel.title}</strong>
              <p>{startupPanel.detail}</p>
            </div>
          </div>
        </div>
      ) : null}
      {shutdownOpen ? (
        <div className={styles.shutdownOverlay} role="status" aria-live="polite" aria-busy={!shutdownSettled}>
          <div className={styles.shutdownPanel}>
            <LoaderCircle size={22} className={shutdownSettled ? styles.shutdownIconStill : styles.shutdownIconSpin} />
            <div className={styles.shutdownCopy}>
              <strong>{shutdownTitle}</strong>
              <p>{shutdownDetail}</p>
              {!shutdownSettled ? (
                <button
                  type="button"
                  className={styles.shutdownCancelButton}
                  onClick={cancelLifecycleWait}
                  disabled={lifecycleCancelPending}
                >
                  {lifecycleCancelPending
                    ? cancellingLifecycleLabel
                    : lifecycleAction === "restart"
                      ? cancelRestartLabel
                      : cancelShutdownLabel}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
      <header className={styles.topBar}>
        <div className={styles.brandBlock}>
          <div className={styles.brandCopy}>
            <span className={styles.brand}>Vibelution</span>
            <span className={styles.versionPill} title={`Vibelution v${APP_VERSION}`}>
              v{APP_VERSION}
            </span>
            <span className={styles.brandSubtle}>{t("brandSubtle")}</span>
          </div>
          <div className={styles.topClock} title={timezone} aria-label={`${t("systemTime")}: ${currentTime}`}>
            <span className={`${styles.statusDot} ${styles.status_idle}`} />
            <span>{currentTime}</span>
          </div>
          {activeWorkIndicator ? (
            <div
              className={styles.activeWorkChip}
              tabIndex={0}
              title={activeWorkDetailsTitle}
              aria-label={`${t("activeWorkNow")}: ${activeWorkIndicator.label} ${statusLabel(activeWorkIndicator.status)}${
                activeWorkIndicator.count > 1 ? `, ${activeWorkIndicator.count} ${t("activeWorkCountSuffix")}` : ""
              }. ${activeWorkDetailsTitle}`}
            >
              <span className={`${styles.statusDot} ${styles[`status_${activeWorkIndicator.tone}`]}`} />
              <span className={styles.activeWorkKicker}>{t("activeWorkNow")}</span>
              <strong>{activeWorkIndicator.label}</strong>
              <span className={styles.activeWorkStatus}>{statusLabel(activeWorkIndicator.status)}</span>
              {activeWorkIndicator.overflowCount > 0 ? (
                <span className={styles.activeWorkMore}>
                  {t("activeWorkMorePrefix")}
                  {activeWorkIndicator.overflowCount}
                </span>
              ) : null}
              <div className={styles.activeWorkDetailPanel} role="note">
                <div className={styles.activeWorkDetailHeader}>
                  <strong>{t("activeWorkDetails")}</strong>
                  <span>
                    {activeWorkIndicator.count} {t("activeWorkCountSuffix")}
                  </span>
                </div>
                <ul className={styles.activeWorkDetailList}>
                  {activeWorkIndicator.items.map((item) => (
                    <li key={`${item.kind}-${item.runId || item.status}`} className={styles.activeWorkDetailItem}>
                      <span className={`${styles.statusDot} ${styles[`status_${item.tone}`]}`} />
                      <div className={styles.activeWorkDetailCopy}>
                        <div className={styles.activeWorkDetailTitle}>
                          <strong>{item.label}</strong>
                          <span>{statusLabel(item.status)}</span>
                        </div>
                        <p>{item.summary}</p>
                        {item.runId ? <code>{item.runId}</code> : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null}
        </div>

        <nav className={styles.nav}>
          {chatEnabled ? (
            <NavLink to="/chat" className={linkClassName}>
              {t("navChat")}
            </NavLink>
          ) : (
            <span className={`${styles.navLink} ${styles.navLinkDisabled}`} aria-disabled="true">
              {t("navChat")}
            </span>
          )}
          {supervisedEvolutionEnabled ? (
            <NavLink to="/supervised-evolution" className={linkClassName}>
              {t("navSupervisedEvolution")}
            </NavLink>
          ) : (
            <span className={`${styles.navLink} ${styles.navLinkDisabled}`} aria-disabled="true">
              {t("navSupervisedEvolution")}
            </span>
          )}
          {selfEvolutionEnabled ? (
            <NavLink to="/self-evolution" className={linkClassName}>
              {t("navSelfEvolution")}
            </NavLink>
          ) : (
            <span className={`${styles.navLink} ${styles.navLinkDisabled}`} aria-disabled="true">
              {t("navSelfEvolution")}
            </span>
          )}
          <NavLink to="/teams" className={linkClassName}>
            {t("navTeams")}
          </NavLink>
          <NavLink to="/memory" className={linkClassName}>
            {t("navMemory")}
          </NavLink>
          <NavLink to="/agents" className={linkClassName}>
            {t("navAgents")}
          </NavLink>
        </nav>

        <div className={styles.topActions}>
          <div
            ref={utilityMenuRef}
            className={
              utilityOpen
                ? `${styles.utilityCluster} ${styles.utilityClusterOpen}`
                : styles.utilityCluster
            }
            aria-label={t("topUtilityMenu")}
            title={t("topUtilityMenu")}
            onMouseEnter={() => setUtilityOpen(true)}
            onMouseLeave={(event) => {
              if (!event.currentTarget.contains(document.activeElement)) {
                setUtilityOpen(false);
              }
            }}
            onBlur={(event) => {
              const nextTarget = event.relatedTarget;
              if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) {
                setUtilityOpen(false);
              }
            }}
          >
            <button
              type="button"
              className={styles.utilityTrigger}
              aria-haspopup="menu"
              aria-expanded={utilityOpen}
              aria-label={t("topUtilityMenu")}
              title={t("topUtilityMenu")}
              onClick={() => setUtilityOpen(true)}
              onFocus={() => setUtilityOpen(true)}
            >
              <Wrench size={15} />
              <span className={styles.utilityTriggerLabel}>{t("topUtilityMenuShort")}</span>
              <span className={`${styles.statusDot} ${styles.status_idle}`} />
              <ChevronDown size={13} className={styles.utilityChevron} />
            </button>
            {utilityOpen ? (
              <Suspense fallback={null}>
                <LazyAppShellUtilityMenu
                  lang={lang}
                  t={t}
                  frontendVisible={frontendVisible}
                  onClose={closeUtilityMenu}
                />
              </Suspense>
            ) : null}
          </div>
          <div
            className={styles.statusCluster}
            tabIndex={0}
            aria-label={t("systemStatusGuide")}
            title={statusSummaryTitle}
            onMouseEnter={() => setStatusGuideOpen(true)}
            onMouseLeave={(event) => {
              if (!event.currentTarget.contains(document.activeElement)) {
                setStatusGuideOpen(false);
              }
            }}
            onFocus={() => setStatusGuideOpen(true)}
            onBlur={(event) => {
              const nextTarget = event.relatedTarget;
              if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) {
                setStatusGuideOpen(false);
              }
            }}
          >
            <div className={styles.statusSummaryChip}>
              <span className={`${styles.statusDot} ${styles[`status_${primaryStatusCard.tone}`]}`} />
              <span className={styles.statusBadgeLabel}>{primaryStatusCard.label}</span>
              <strong className={styles.statusBadgeValue}>{primaryStatusCard.value}</strong>
              <span className={styles.statusSummaryCount}>{rightStatusCards.length}</span>
            </div>
            {statusGuideOpen ? (
              <Suspense fallback={null}>
                <LazyAppShellStatusGuidePanel
                  lang={lang}
                  t={t}
                  cards={rightStatusCards}
                  frontendState={frontendState}
                  backendState={backendState}
                  runtimeControllerState={runtimeControllerState}
                  lifecycleProof={lifecycleProof}
                  workbench={workbench}
                  buildId={buildId}
                />
              </Suspense>
            ) : null}
          </div>
          <button
            type="button"
            className={styles.actionIconButton}
            aria-label={themeToggleLabel}
            title={themeToggleLabel}
            onClick={toggleTheme}
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button
            type="button"
            className={styles.actionIconButton}
            aria-label={refreshFrontendLabel}
            title={refreshFrontendLabel}
            onClick={refreshFrontend}
            disabled={restartRequested || shutdownRequested || (shutdownInFlight && !shutdownSettled)}
          >
            <RefreshCw size={16} />
          </button>
          <div
            ref={lifecycleMenuRef}
            className={
              lifecycleMenuOpen
                ? `${styles.lifecycleMenuCluster} ${styles.lifecycleMenuClusterOpen}`
                : styles.lifecycleMenuCluster
            }
          >
            <button
              type="button"
              className={styles.actionIconButton}
              aria-label={lifecycleMenuLabel}
              title={lifecycleMenuLabel}
              aria-haspopup="menu"
              aria-expanded={lifecycleMenuOpen}
              onClick={() => setLifecycleMenuOpen((current) => !current)}
              disabled={restartRequested || (shutdownInFlight && !shutdownSettled)}
            >
              <Power size={16} />
            </button>
            <div
              className={styles.lifecycleMenuPanel}
              role="menu"
              aria-label={lifecycleMenuLabel}
              hidden={!lifecycleMenuOpen}
            >
              <button
                type="button"
                className={styles.lifecycleMenuItem}
                role="menuitem"
                onClick={() => {
                  setLifecycleMenuOpen(false);
                  const proceed = () => {
                    void beginShutdown();
                  };
                  if (requestWorkbenchExitGuard("shutdown", proceed)) {
                    proceed();
                  }
                }}
                disabled={restartRequested || (shutdownInFlight && !shutdownSettled)}
              >
                <Power size={15} />
                <span>{closeWorkbenchLabel}</span>
              </button>
              {forceCloseVisible ? (
                <button
                  type="button"
                  className={`${styles.lifecycleMenuItem} ${styles.lifecycleMenuDangerItem}`}
                  role="menuitem"
                  onClick={() => {
                    setLifecycleMenuOpen(false);
                    void beginForceShutdown();
                  }}
                  disabled={restartRequested}
                >
                  <Power size={15} />
                  <span>{forceCloseWorkbenchLabel}</span>
                </button>
              ) : null}
              <button
                type="button"
                className={styles.lifecycleMenuItem}
                role="menuitem"
                onClick={() => {
                  setLifecycleMenuOpen(false);
                  const proceed = () => {
                    if (activeWorkIndicator) {
                      setShutdownOpen(true);
                      setShutdownSettled(false);
                      setShutdownRequested(false);
                      setRestartRequested(false);
                      setLifecycleAction("restart");
                      setLifecycleCommandId("");
                      setLifecycleCancelPending(false);
                      setShutdownTitle(restartHeading);
                      setShutdownDetail(restartActiveWorkBlockedMessage(lang, activeWorkDetailsTitle));
                      emitBrowserTelemetry(
                        {
                          phase: "restart",
                          eventCode: "browser.user_action.restart_blocked_active_work",
                          message: "Restart was blocked because active work is running.",
                          level: "warning",
                          fields: {
                            action: "restart",
                            source: "app_shell",
                            activeWorkCount: activeWorkIndicator.count,
                            activeWorkKinds: activeWorkIndicator.items.map((item) => item.kind),
                          },
                        },
                        { preferBeacon: true },
                      );
                      return;
                    }
                    void beginRestart();
                  };
                  if (requestWorkbenchExitGuard("restart", proceed)) {
                    proceed();
                  }
                }}
                disabled={restartRequested || shutdownRequested || (shutdownInFlight && !shutdownSettled)}
              >
                <RefreshCw size={15} />
                <span>{restartWorkbenchLabel}</span>
              </button>
            </div>
          </div>
          <NavLink
            to="/config"
            className={styles.actionIconButton}
            aria-label={t("navConfig")}
            title={t("navConfig")}
          >
            <Settings size={16} />
          </NavLink>
        </div>
      </header>

      <main className={styles.mainArea}>
        <Outlet />
      </main>
    </div>
  );
}
