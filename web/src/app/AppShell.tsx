import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useNavigationType } from "react-router-dom";
import { ChevronDown, ExternalLink, FolderTree, GitBranch, LoaderCircle, Moon, Power, RefreshCw, ScrollText, Search, Settings, Sun, Wrench } from "lucide-react";

import { fetchJson, setFetchJsonFailureReporter, type FetchJsonFailureReport } from "../api/client";
import { restartLauncherBundle, stopLauncherBundle } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import {
  BackendHealth,
  ConfigSummary,
  FileTreeNode,
  GitStatusSummary,
  RuntimeControlBlockedDetail,
  RuntimeSummary,
} from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
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
  lifecycleStateLabel,
  lifecycleStateTone,
  runtimeControllerTone,
  type SystemStatusTone,
} from "./systemStatus";
import { applyWorkbenchDocumentLanguage } from "./documentLanguage";
import { resolvePollingInterval } from "./pollingPolicy";
import { recoverFromBuiltAssetResourceError } from "./routeChunkRecovery";
import { nextWorkbenchTheme, readStoredWorkbenchTheme, writeStoredWorkbenchTheme } from "./themePreference";
import { isWorkbenchDomainEnabled, isWorkbenchModeEnabled } from "./workbenchContract";
import { requestWorkbenchExitGuard } from "./workbenchExitGuard";
import { useChatWorkbenchStore } from "../store/chatWorkbenchStore";
import { getPageInstanceId } from "./pageInstance";
import styles from "./AppShell.module.css";
import packageJson from "../../package.json";

function linkClassName({ isActive }: { isActive: boolean }) {
  return isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink;
}

const API_FAILURE_TELEMETRY_THROTTLE_MS = 15_000;
const API_FAILURE_BACKGROUND_METHODS = new Set(["GET", "HEAD"]);
const APP_VERSION = packageJson.version;
const BROWSER_MEMORY_SAMPLE_INTERVAL_MS = 30_000;
const PAGEHIDE_NETWORK_FAILURE_SUPPRESSION_MS = 2_500;

function filterUtilityFileTree(nodes: FileTreeNode[], query: string): FileTreeNode[] {
  const term = query.trim().toLowerCase();
  if (!term) {
    return nodes;
  }
  return nodes.flatMap((node) => {
    const matches = node.name.toLowerCase().includes(term) || node.path.toLowerCase().includes(term);
    if (node.type === "directory") {
      const filteredChildren = filterUtilityFileTree(node.children ?? [], query);
      if (matches) {
        return [{ ...node, children: node.children ?? [] }];
      }
      if (filteredChildren.length > 0) {
        return [{ ...node, children: filteredChildren }];
      }
      return [];
    }
    return matches ? [node] : [];
  });
}

function renderUtilityFileTree(
  nodes: FileTreeNode[],
  onOpenFile: (path: string) => void,
  activeFilePath: string,
) {
  return nodes.map((node) => {
    if (node.type === "directory") {
      return (
        <details key={node.path} className={styles.utilityFileDir} open>
          <summary>{node.name}</summary>
          <div className={styles.utilityFileChildren}>
            {renderUtilityFileTree(node.children ?? [], onOpenFile, activeFilePath)}
          </div>
        </details>
      );
    }
    const active = activeFilePath === node.path;
    return (
      <button
        key={node.path}
        type="button"
        className={active ? `${styles.utilityFileButton} ${styles.utilityFileButtonActive}` : styles.utilityFileButton}
        onClick={() => onOpenFile(node.path)}
        title={node.path}
      >
        <span>{node.name}</span>
        <small>{node.path}</small>
      </button>
    );
  });
}

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
  const { lang, t, statusLabel } = useAppI18n();
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
  const [utilityOpen, setUtilityOpen] = useState(false);
  const [lifecycleMenuOpen, setLifecycleMenuOpen] = useState(false);
  const [utilityFileFilter, setUtilityFileFilter] = useState("");
  const [clockNow, setClockNow] = useState(() => Date.now());
  const [theme, setTheme] = useState(() => readStoredWorkbenchTheme());
  const [frontendVisible, setFrontendVisible] = useState(
    () => (typeof document === "undefined" ? true : document.visibilityState === "visible"),
  );
  const [frontendOnline, setFrontendOnline] = useState(
    () => (typeof navigator === "undefined" ? true : navigator.onLine),
  );
  const shutdownPromiseRef = useRef<Promise<void> | null>(null);
  const restartPromiseRef = useRef<Promise<void> | null>(null);
  const utilityMenuRef = useRef<HTMLDivElement | null>(null);
  const lifecycleMenuRef = useRef<HTMLDivElement | null>(null);
  const shutdownLocalCompletionLoggedRef = useRef(false);
  const telemetrySeqRef = useRef(0);
  const pageInstanceIdRef = useRef(getPageInstanceId());
  const apiFailureTelemetrySeenRef = useRef(new Map<string, number>());
  const pagehideAtMsRef = useRef(0);
  const activeSessionId = useChatWorkbenchStore((state) => state.activeSessionId);
  const activeSessionWorkspace = useChatWorkbenchStore((state) =>
    state.activeSessionId ? state.sessionWorkspaces[state.activeSessionId] : undefined,
  );
  const openPreviewTab = useChatWorkbenchStore((state) => state.openPreviewTab);
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
  });
  const lifecycleControlActive = shutdownOpen || shutdownRequested || restartRequested;
  const runtimeRefetchInterval = resolvePollingInterval(
    frontendVisible,
    lifecycleControlActive ? 1_000 : 5_000,
    {
      backgroundMs: lifecycleControlActive ? 1_000 : 30_000,
      force: lifecycleControlActive,
    },
  );
  const gitRefetchInterval = resolvePollingInterval(frontendVisible, 6_000, { backgroundMs: 60_000 });
  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchJson<RuntimeSummary>("/api/runtime/summary"),
    refetchInterval: runtimeRefetchInterval,
    refetchIntervalInBackground: false,
  });
  const backendHealthQuery = useQuery({
    queryKey: queryKeys.backendHealth(),
    queryFn: () =>
      fetchJson<BackendHealth>("/api/health", {
        cache: "no-store",
      }),
    refetchInterval: runtimeRefetchInterval,
    refetchIntervalInBackground: false,
    staleTime: 0,
    retry: false,
  });
  const gitStatusQuery = useQuery({
    queryKey: queryKeys.gitStatus(),
    queryFn: () => fetchJson<GitStatusSummary>("/api/git/status"),
    refetchInterval: gitRefetchInterval,
    refetchIntervalInBackground: false,
  });
  const fileTreeQuery = useQuery({
    queryKey: queryKeys.fileTree(),
    queryFn: () => fetchJson<FileTreeNode[]>("/api/files/tree"),
    enabled: utilityOpen,
    staleTime: 8_000,
  });

  const workbench = runtimeQuery.data?.workbench;
  const lifecycleProof = runtimeQuery.data?.lifecycleProof;
  const shutdownInFlight = workbench?.desiredState === "closed" && workbench?.observedState !== "closed";
  const chatEnabled = isWorkbenchDomainEnabled(configQuery.data, "chat");
  const supervisedEvolutionEnabled = isWorkbenchModeEnabled(configQuery.data, "supervised_evolution");
  const selfEvolutionEnabled = isWorkbenchModeEnabled(configQuery.data, "self_evolution");
  const refreshFrontendLabel = lang === "en" ? "Refresh frontend" : "刷新前端";
  const lifecycleMenuLabel = lang === "en" ? "Workbench power actions" : "工作台电源操作";
  const closeWorkbenchLabel = lang === "en" ? "Close workbench" : "关闭工作台";
  const restartWorkbenchLabel = lang === "en" ? "Restart workbench" : "重启工作台";
  const themeToggleLabel = theme === "dark" ? t("switchToLightTheme") : t("switchToDarkTheme");
  const shutdownHeading = lang === "en" ? "Closing workbench" : "正在关闭工作台";
  const shutdownBody = lang === "en"
    ? "Please keep this window open. The runtime manager will close the backend and app window."
    : "请先保持这个窗口打开。运行时管理器会负责关闭后端和应用窗口。";
  const shutdownErrorBody = lang === "en"
    ? "The runtime manager could not close the workbench. Check the launcher and runtime-manager logs."
    : "运行时管理器没有成功关闭工作台。请检查 launcher 和 runtime-manager 日志。";
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
  const activeWorkIndicator = deriveActiveWorkIndicator(runtimeQuery.data, lang);
  const activeWorkDetailsTitle = activeWorkIndicator?.items.map((item) => item.detail).join(" · ") ?? "";
  const currentTime = clockFormatter.format(clockNow);
  const buildId = __VIBELUTION_BUILD_ID__;
  const gitStatus = gitStatusQuery.data;
  const utilityFilteredFileTree = useMemo(
    () => filterUtilityFileTree(fileTreeQuery.data ?? [], utilityFileFilter),
    [fileTreeQuery.data, utilityFileFilter],
  );
  const utilityActiveFilePath = activeSessionWorkspace?.activeTab && activeSessionWorkspace.activeTab !== "agent"
    ? activeSessionWorkspace.activeTab
    : "";
  const gitAvailable = Boolean(gitStatus?.available);
  const gitDirty = Boolean(gitStatus?.dirty);
  const gitTone: SystemStatusTone = gitAvailable ? (gitDirty ? "caution" : "running") : "idle";
  const gitBranch = gitStatus?.branch || gitStatus?.headRevShort || "-";
  const gitValue = gitAvailable
    ? gitDirty
      ? `${gitStatus?.counts.total ?? 0}`
      : t("gitClean")
    : gitStatusQuery.isPending
      ? t("gitChecking")
      : t("gitUnavailable");
  const gitTitle = gitAvailable
    ? `${t("gitStatus")}: ${gitStatus?.summary ?? ""}`
    : gitStatus?.error || t("gitUnavailable");
  const closeUtilityMenu = useCallback(() => {
    setUtilityOpen(false);
  }, []);
  const handleUtilityOpenFile = useCallback((path: string) => {
    if (!activeSessionId) {
      navigate("/chat");
      closeUtilityMenu();
      return;
    }
    openPreviewTab(activeSessionId, path);
    navigate("/chat");
    closeUtilityMenu();
  }, [activeSessionId, closeUtilityMenu, navigate, openPreviewTab]);

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

  const beginShutdown = useCallback(() => {
    if (restartPromiseRef.current || restartRequested) {
      return restartPromiseRef.current ?? Promise.resolve();
    }
    if (shutdownPromiseRef.current) {
      return shutdownPromiseRef.current;
    }

    const task = (async () => {
      setShutdownRequested(true);
      setShutdownSettled(false);
      setShutdownOpen(true);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(shutdownBody);
      shutdownLocalCompletionLoggedRef.current = false;
      emitBrowserTelemetry(buildShutdownRequestedTelemetry(), { preferBeacon: true });

      const payload = await stopLauncherBundle();
      if (payload.message) {
        setShutdownDetail(payload.message);
      }
    })().catch((error) => {
      const errorMessage = error instanceof Error ? error.message : String(error || "");
      setShutdownRequested(true);
      setShutdownOpen(true);
      setShutdownSettled(false);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(shutdownUnconfirmedBody);
      emitBrowserTelemetry(buildShutdownRequestUnconfirmedTelemetry(errorMessage), { preferBeacon: true });
    }).finally(() => {
      shutdownPromiseRef.current = null;
    });

    shutdownPromiseRef.current = task;
    return task;
  }, [emitBrowserTelemetry, restartRequested, shutdownBody, shutdownHeading, shutdownUnconfirmedBody]);

  const beginRestart = useCallback(() => {
    if (shutdownPromiseRef.current || shutdownRequested) {
      return shutdownPromiseRef.current ?? Promise.resolve();
    }
    if (restartPromiseRef.current) {
      return restartPromiseRef.current;
    }

    const task = (async () => {
      setRestartRequested(true);
      setShutdownRequested(false);
      setShutdownSettled(false);
      setShutdownOpen(true);
      setShutdownTitle(restartHeading);
      setShutdownDetail(restartBody);
      emitBrowserTelemetry(buildRestartRequestedTelemetry(), { preferBeacon: true });

      const payload = await restartLauncherBundle();
      if (payload.message) {
        setShutdownDetail(payload.message);
      }
    })().catch((error) => {
      const blocked = runtimeBlockedDetail(error);
      if (blocked?.code === "active_work_restart_blocked" || blocked?.code === "active_work_requires_confirmation") {
        setRestartRequested(false);
        setShutdownOpen(false);
        setShutdownSettled(false);
        setShutdownTitle("");
        setShutdownDetail("");
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
      setShutdownOpen(true);
      setShutdownSettled(false);
      setShutdownTitle(restartHeading);
      setShutdownDetail(restartUnconfirmedBody);
      emitBrowserTelemetry(buildRestartRequestUnconfirmedTelemetry(errorMessage), { preferBeacon: true });
    }).finally(() => {
      restartPromiseRef.current = null;
    });

    restartPromiseRef.current = task;
    return task;
  }, [emitBrowserTelemetry, restartBody, restartHeading, restartUnconfirmedBody, shutdownRequested]);

  const refreshFrontend = useCallback(() => {
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
      setShutdownRequested(false);
      setShutdownOpen(true);
      setShutdownSettled(true);
      setShutdownTitle(shutdownHeading);
      setShutdownDetail(workbench.failureMessage || shutdownErrorBody);
      return;
    }

    if (closing) {
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
      setShutdownOpen(true);
      setShutdownSettled(false);
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
      setRestartRequested(false);
      setShutdownOpen(true);
      setShutdownSettled(true);
      setShutdownTitle(restartHeading);
      setShutdownDetail(workbench.failureMessage || restartErrorBody);
      return;
    }

    if (ready) {
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

  const systemStatusCards: Array<{
    id: string;
    label: string;
    value: string;
    tone: SystemStatusTone;
    note: string;
    states: Array<{ label: string; tone: SystemStatusTone; detail: string }>;
  }> = [
    {
      id: "frontend",
      label: t("systemFrontend"),
      value: frontendStateLabel,
      tone: frontendSystemTone(frontendState),
      note: `${t("systemFrontendHint")} · ${t("frontendBuild")} ${buildId}`,
      states: [
        {
          label: t("systemFrontend_connected"),
          tone: frontendSystemTone("connected"),
          detail: t("systemFrontendPossible_connected"),
        },
        {
          label: t("systemFrontend_background"),
          tone: frontendSystemTone("background"),
          detail: t("systemFrontendPossible_background"),
        },
        {
          label: t("systemFrontend_offline"),
          tone: frontendSystemTone("offline"),
          detail: t("systemFrontendPossible_offline"),
        },
      ],
    },
    {
      id: "backend",
      label: t("systemBackend"),
      value: backendStateLabel,
      tone: backendSystemTone(backendState),
      note:
        backendState === "healthy"
          ? t("backendReachable")
          : backendState === "checking"
            ? t("backendNeverReached")
            : backendState === "offline"
              ? t("backendNoResponse")
              : t("systemBackendHint"),
      states: [
        {
          label: t("backendHealthy"),
          tone: backendSystemTone("healthy"),
          detail: t("systemBackendPossible_healthy"),
        },
        {
          label: t("backendChecking"),
          tone: backendSystemTone("checking"),
          detail: t("systemBackendPossible_checking"),
        },
        {
          label: t("backendOffline"),
          tone: backendSystemTone("offline"),
          detail: t("systemBackendPossible_offline"),
        },
        {
          label: t("backendUnhealthy"),
          tone: backendSystemTone("unhealthy"),
          detail: t("systemBackendPossible_unhealthy"),
        },
      ],
    },
    {
      id: "runtime",
      label: t("systemRuntime"),
      value: runtimeControllerLabel,
      tone: runtimeControllerTone(runtimeControllerState),
      note: lifecycleProof?.summary || workbench?.statusLine || t("systemRuntimeHint"),
      states: [
        {
          label: t("systemRuntime_managed"),
          tone: runtimeControllerTone("managed"),
          detail: t("systemRuntimePossible_managed"),
        },
        {
          label: t("systemRuntime_closing"),
          tone: runtimeControllerTone("closing"),
          detail: t("systemRuntimePossible_closing"),
        },
        {
          label: t("systemRuntime_unmanaged"),
          tone: runtimeControllerTone("unmanaged"),
          detail: t("systemRuntimePossible_unmanaged"),
        },
        {
          label: t("systemRuntime_failed"),
          tone: runtimeControllerTone("failed"),
          detail: t("systemRuntimePossible_failed"),
        },
      ],
    },
    {
      id: "time",
      label: t("systemTime"),
      value: currentTime,
      tone: "idle",
      note: timezone,
      states: [
        {
          label: t("systemTimeLive"),
          tone: "idle",
          detail: t("systemTimePossible_live"),
        },
      ],
    },
  ];
  const rightStatusCards = systemStatusCards.filter((item) => item.id !== "time");
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
              <span className={`${styles.statusDot} ${styles[`status_${gitTone}`]}`} />
              <ChevronDown size={13} className={styles.utilityChevron} />
            </button>
            <div
              className={styles.utilityPanel}
              role="menu"
              aria-label={t("topUtilityMenu")}
              hidden={!utilityOpen}
            >
              <div className={styles.utilityPanelHeader}>
                <strong>{t("topUtilityMenu")}</strong>
                <span>{t("topUtilityMenuHint")}</span>
              </div>
              <div className={styles.utilityButtonGrid}>
                <a href="/launcher" target="_blank" rel="noreferrer" className={styles.utilityButton} role="menuitem" onClick={closeUtilityMenu}>
                  <ExternalLink size={16} />
                  <span>{lang === "zh" ? "启动器" : "Launcher"}</span>
                </a>
                <NavLink to="/logs" className={({ isActive }) => isActive ? `${styles.utilityButton} ${styles.utilityButtonActive}` : styles.utilityButton} role="menuitem" onClick={closeUtilityMenu}>
                  <ScrollText size={16} />
                  <span>{t("navLogs")}</span>
                </NavLink>
                <NavLink to="/git" className={({ isActive }) => isActive ? `${styles.utilityButton} ${styles.utilityButtonActive}` : styles.utilityButton} role="menuitem" onClick={closeUtilityMenu}>
                  <GitBranch size={16} />
                  <span>{t("navGit")}</span>
                </NavLink>
                <button
                  type="button"
                  className={styles.utilityButton}
                  role="menuitem"
                  onClick={() => document.getElementById("utility-file-navigator")?.scrollIntoView({ block: "nearest" })}
                >
                  <FolderTree size={16} />
                  <span>{t("files")}</span>
                </button>
              </div>
              <section id="utility-file-navigator" className={styles.utilityFilePanel} aria-label={t("files")}>
                <div className={styles.utilityFileHeader}>
                  <div>
                    <strong>{t("files")}</strong>
                    <span>
                      {activeSessionId
                        ? (lang === "zh" ? "点击文件会在当前会话工作区打开预览。" : "Click a file to open it in the current chat workspace.")
                        : (lang === "zh" ? "先进入会话后可打开文件预览。" : "Open a chat first to preview files.")}
                    </span>
                  </div>
                </div>
                <div className={styles.utilityFileSearch}>
                  <Search size={14} />
                  <input
                    value={utilityFileFilter}
                    onChange={(event) => setUtilityFileFilter(event.target.value)}
                    placeholder={t("searchFilesPlaceholder")}
                  />
                </div>
                <div className={styles.utilityFileTree}>
                  {fileTreeQuery.isError ? (
                    <p className={styles.utilityFileState}>{t("loadFailed")}</p>
                  ) : fileTreeQuery.isPending && !fileTreeQuery.data ? (
                    <p className={styles.utilityFileState}>{t("loadingFiles")}</p>
                  ) : utilityFilteredFileTree.length === 0 ? (
                    <p className={styles.utilityFileState}>{t("noFileMatches")}</p>
                  ) : (
                    renderUtilityFileTree(utilityFilteredFileTree, handleUtilityOpenFile, utilityActiveFilePath)
                  )}
                </div>
              </section>
              <div className={styles.gitMiniPanel} aria-label={t("gitStatusGuide")} title={gitTitle}>
                <div className={styles.gitMiniHeader}>
                  <div className={styles.gitChip}>
                    <GitBranch size={14} />
                    <span className={`${styles.statusDot} ${styles[`status_${gitTone}`]}`} />
                    <span className={styles.gitBranchName}>{gitBranch}</span>
                    <strong className={styles.gitCount}>{gitValue}</strong>
                  </div>
                  <span>{gitStatus?.summary || t("gitStatusGuideHint")}</span>
                </div>
                <div className={styles.gitMetaGrid}>
                  <span>{t("gitBranch")}</span>
                  <strong>{gitBranch}</strong>
                  <span>{t("gitUpstream")}</span>
                  <strong>{gitStatus?.upstream?.name || gitStatus?.upstream?.remote || t("gitNoUpstream")}</strong>
                </div>
                <div className={styles.gitCountGrid}>
                  <span>
                    <strong>{gitStatus?.counts.staged ?? 0}</strong>
                    {t("gitStaged")}
                  </span>
                  <span>
                    <strong>{gitStatus?.counts.unstaged ?? 0}</strong>
                    {t("gitUnstaged")}
                  </span>
                  <span>
                    <strong>{gitStatus?.counts.untracked ?? 0}</strong>
                    {t("gitUntracked")}
                  </span>
                  <span>
                    <strong>{gitStatus?.counts.deleted ?? 0}</strong>
                    {t("gitDeleted")}
                  </span>
                </div>
                <div className={styles.gitFileList}>
                  {(gitStatus?.files ?? []).slice(0, 6).map((file) => (
                    <div key={`${file.status}-${file.path}`} className={styles.gitFileItem}>
                      <code>{file.status}</code>
                      <span>{file.path}</span>
                    </div>
                  ))}
                  {gitStatus?.truncated ? <p>{t("gitTruncated")}</p> : null}
                  {gitStatus && gitStatus.available && !gitStatus.files.length ? <p>{t("gitNoChanges")}</p> : null}
                  {gitStatus && !gitStatus.available ? <p>{gitStatus.error || t("gitUnavailable")}</p> : null}
                </div>
              </div>
            </div>
          </div>
          <div
            className={styles.statusCluster}
            tabIndex={0}
            aria-label={t("systemStatusGuide")}
            title={statusSummaryTitle}
          >
            <div className={styles.statusSummaryChip}>
              <span className={`${styles.statusDot} ${styles[`status_${primaryStatusCard.tone}`]}`} />
              <span className={styles.statusBadgeLabel}>{primaryStatusCard.label}</span>
              <strong className={styles.statusBadgeValue}>{primaryStatusCard.value}</strong>
              <span className={styles.statusSummaryCount}>{rightStatusCards.length}</span>
            </div>
            <div className={styles.statusGuidePanel} role="note" aria-live="polite">
              <div className={styles.statusGuideHeader}>
                <strong>{t("systemStatusGuide")}</strong>
                <span>{t("systemStatusGuideHint")}</span>
              </div>
              <div className={styles.statusGuideGrid}>
                {rightStatusCards.map((item) => (
                  <section key={item.id} className={styles.statusGuideCard}>
                    <div className={styles.statusGuideCardHeader}>
                      <span>{item.label}</span>
                      <strong>{item.value}</strong>
                    </div>
                    <p className={styles.statusGuideNote}>{item.note}</p>
                    <ul className={styles.statusGuideList}>
                      {item.states.map((state) => (
                        <li key={`${item.id}-${state.label}`} className={styles.statusGuideListItem}>
                          <span className={`${styles.statusDot} ${styles[`status_${state.tone}`]}`} />
                          <span className={styles.statusGuideStateLabel}>{state.label}</span>
                          <span className={styles.statusGuideStateDetail}>{state.detail}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
              <section className={styles.lifecycleProofCard}>
                <div className={styles.lifecycleProofHeader}>
                  <span>{t("lifecycleProofTitle")}</span>
                  <strong>
                    <span
                      className={`${styles.statusDot} ${styles[`status_${lifecycleStateTone(lifecycleProof?.overallState)}`]}`}
                    />
                    {lifecycleProof?.overallLabel || t("lifecycleProofUnavailable")}
                  </strong>
                </div>
                <p className={styles.statusGuideNote}>
                  {lifecycleProof?.summary || t("lifecycleProofUnavailable")}
                </p>
                {lifecycleProof ? (
                  <>
                    <div className={styles.lifecycleProofMeta}>
                      <span>{t("lifecycleProofDesiredObserved")}</span>
                      <strong>
                        {lifecycleProof.desiredState} / {lifecycleProof.observedState}
                      </strong>
                      <span>{t("lifecycleProofVerifiedAt")}</span>
                      <strong>{lifecycleProof.verifiedAt || "-"}</strong>
                    </div>
                    <ul className={styles.lifecycleProofList}>
                      {lifecycleProof.components.map((component) => (
                        <li key={component.id} className={styles.lifecycleProofItem}>
                          <span
                            className={`${styles.statusDot} ${styles[`status_${lifecycleStateTone(component.state)}`]}`}
                          />
                          <span className={styles.lifecycleProofName}>{component.label}</span>
                          <strong>{lifecycleStateLabel(component.state, lang)}</strong>
                          <span>{component.detail}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </section>
            </div>
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
                      setRestartRequested(false);
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
