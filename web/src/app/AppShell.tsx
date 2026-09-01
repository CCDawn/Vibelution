import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, type CSSProperties, type MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, Outlet, useLocation, useNavigate, useNavigationType } from "react-router-dom";
import {
  ArrowLeft,
  ChevronDown,
  LoaderCircle,
  Moon,
  PanelTopClose,
  PanelTopOpen,
  RefreshCw,
  Settings,
  Sun,
  Wrench,
} from "lucide-react";

import { fetchJson, setFetchJsonFailureReporter, type FetchJsonFailureReport } from "../api/client";
import { fetchPublicConfig } from "../api/config";
import { cancelRuntimeLifecycleCommand, getLocalBranchInstances, requestWorkbenchWindowCloseOnPageHide } from "../api/launcher";
import { currentInstanceWindowTitle } from "./instanceWindowTitle";
import { queryKeys } from "../api/queryKeys";
import {
  BackendHealth,
  CodeFreshness,
  ConfigSummary,
  RuntimeSummary,
} from "../api/types";
import {
  formatActiveWorkRunsDetail,
  isActiveWorkRestartBlocked,
  isActiveWorkStopBlocked,
  parseRuntimeControlBlockedDetail,
} from "./workbenchLifecycleActions";
import { useWorkbenchLifecycleActions } from "./useWorkbenchLifecycleActions";
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
  shouldRenderStartupOverlay,
  type SystemStatusTone,
} from "./systemStatus";
import { applyWorkbenchDocumentLanguage } from "./documentLanguage";
import { resolvePollingInterval, useStartupWarmup } from "./pollingPolicy";
import { recoverFromBuiltAssetResourceError, recoverFromDynamicImportFetchError } from "./routeChunkRecovery";
import {
  isModifiedPrimaryNavClick,
  resolveUnmodifiedShellNavHref,
  shellNavAnchorFromEventTarget,
} from "./shellPrimaryNavClick";
import {
  nextWorkbenchTheme,
  readStoredWorkbenchTheme,
  writeStoredWorkbenchTheme,
  type WorkbenchTheme,
} from "./themePreference";
import { startWorkbenchUiPreferencesSync } from "./workbenchUiPreferencesSync";
import { startWorkbenchWindowMemory } from "./workbenchWindowMemory";
import { isWorkbenchDomainEnabled, isWorkbenchModeEnabled } from "./workbenchContract";
import {
  appendReturnNavigationEntry,
  consumeReturnNavigationTarget,
  isMeaningfulRouteChange,
  parseReturnNavigationStack,
  resolveReturnTarget,
  serializeReturnNavigationStack,
  type ReturnNavigationEntry,
} from "./navigationReturn";
import {
  allowNextWorkbenchWindowUnload,
  applyBeforeUnloadProjectCloseGuard,
  buildProjectWindowCloseBlockedTelemetry,
  clearPendingWorkbenchWindowCloseIntent,
  consumePendingWorkbenchWindowCloseIntent,
  consumeNextWorkbenchWindowUnloadAllowance,
  hasRecentControlledProjectLifecycleOperation,
  isElectronDesktopShell,
  isWorkbenchRefreshShortcut,
  markControlledProjectLifecycleOperation,
  projectWindowCloseGuardMessage,
  prepareWorkbenchWindowCloseIntent,
  shouldArmBrowserProjectCloseGuard,
  shouldBlockWorkbenchWindowClose,
} from "./projectCloseGuard";
import { useStableBeforeUnload } from "./useStableBeforeUnload";
import { VButton } from "../components/vui/primitives/VButton";
import { VIconButton } from "../components/vui/primitives/VIconButton";
import { VPopover } from "../components/vui/primitives/VPopover";
import { VRouteLinkButton } from "../components/vui/primitives/VRouteLinkButton";
import { VStatusChip, type VStatusTone } from "../components/vui";
import { getPageInstanceId } from "./pageInstance";
import { useShellStore } from "../store/shellStore";
import styles from "./AppShell.styles";
import { shareRuntimeSummaryIfOnlyVolatileChanged } from "./runtimeSummaryQueryShare";
import { CompanionDesktopAttention } from "../routes/companions/CompanionDesktopAttention";

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

/** Prefix-active match for primary shell routes (/agents covers /agents/prompts). */
export function isShellPrimaryNavActive(pathname: string, to: string): boolean {
  const path = String(pathname || "").trim() || "/";
  const target = String(to || "").trim() || "/";
  if (target === "/") {
    return path === "/";
  }
  return path === target || path.startsWith(`${target}/`);
}

function systemToneToStatus(tone: SystemStatusTone): VStatusTone {
  if (tone === "running") return "success";
  if (tone === "caution") return "warning";
  if (tone === "failed") return "danger";
  return "neutral";
}

function systemToneToDotClass(tone: SystemStatusTone): string {
  if (tone === "running") return styles.status_running;
  if (tone === "caution") return styles.status_caution;
  if (tone === "failed") return styles.status_failed;
  return styles.status_muted;
}

function shellPrimaryNavClass(pathname: string, to: string) {
  return isShellPrimaryNavActive(pathname, to)
    ? `${styles.navLink} ${styles.navLinkActive}`
    : styles.navLink;
}

function shellMobileNavClass(pathname: string, to: string) {
  return isShellPrimaryNavActive(pathname, to)
    ? `${styles.mobileRouteLink} ${styles.mobileRouteLinkActive}`
    : styles.mobileRouteLink;
}

let chatRoutePreloadPromise: Promise<unknown> | null = null;
/** Soft hover/focus preload — cancelled if a hard click starts first, or by idle timeout path. */
let chatRouteSoftPreloadHandle: number | null = null;

function browserNowMs(): number {
  return typeof performance === "undefined" ? Date.now() : performance.now();
}

function browserElapsedMs(startedAt: number): number {
  return Math.max(0, Math.round(browserNowMs() - startedAt));
}

function cancelChatRouteSoftPreload() {
  if (chatRouteSoftPreloadHandle == null || typeof window === "undefined") {
    chatRouteSoftPreloadHandle = null;
    return;
  }
  const idleCancel = (window as Window & {
    cancelIdleCallback?: (handle: number) => void;
  }).cancelIdleCallback;
  if (typeof idleCancel === "function") {
    idleCancel(chatRouteSoftPreloadHandle);
  } else {
    window.clearTimeout(chatRouteSoftPreloadHandle);
  }
  chatRouteSoftPreloadHandle = null;
}

function startChatRoutePreloadImport(trigger: "pointerenter" | "focus" | "click") {
  if (chatRoutePreloadPromise) {
    return;
  }
  const startedAt = browserNowMs();
  // D1: warm chat dictionary packs alongside the route graph (soft preload).
  void import("../i18n/loadDictionaryDomains").then((module) => {
    module.prefetchDictionaryDomains(["chat"]);
  });
  chatRoutePreloadPromise = import("../routes/ChatCodingRoute")
    .then(() => {
      postBrowserTelemetry({
        phase: "navigation",
        eventCode: "browser.chat_route.preload_loaded",
        message: "Chat route preload loaded.",
        fields: {
          trigger,
          durationMs: browserElapsedMs(startedAt),
          pathname: window.location.pathname,
        },
      });
    })
    .catch((error: unknown) => {
      chatRoutePreloadPromise = null;
      postBrowserTelemetry({
        phase: "navigation",
        eventCode: "browser.chat_route.preload_failed",
        message: "Chat route preload failed.",
        level: "warning",
        fields: {
          trigger,
          durationMs: browserElapsedMs(startedAt),
          pathname: window.location.pathname,
          errorName: error instanceof Error ? error.name : typeof error,
        },
      });
    });
}

/**
 * Balanced preload (F1):
 * - click → hard immediate import of Chat route
 * - pointerenter/focus → soft idle (does not compete with first paint)
 */
function preloadChatRouteForNav(trigger: "pointerenter" | "focus" | "click") {
  if (typeof window === "undefined") {
    return;
  }
  const alreadyStarted = Boolean(chatRoutePreloadPromise);
  postBrowserTelemetry({
    phase: "navigation",
    eventCode: "browser.chat_route.preload_requested",
    message: "Chat route preload requested from navigation.",
    fields: {
      trigger,
      alreadyStarted,
      soft: trigger !== "click",
      pathname: window.location.pathname,
    },
  });
  if (alreadyStarted) {
    return;
  }

  if (trigger === "click") {
    cancelChatRouteSoftPreload();
    startChatRoutePreloadImport(trigger);
    return;
  }

  // Soft path: schedule once; do not stack multiple idle timers.
  if (chatRouteSoftPreloadHandle != null) {
    return;
  }
  const scheduleSoft = () => {
    chatRouteSoftPreloadHandle = null;
    if (chatRoutePreloadPromise) {
      return;
    }
    startChatRoutePreloadImport(trigger);
  };
  const idleRequest = (window as Window & {
    requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
  }).requestIdleCallback;
  if (typeof idleRequest === "function") {
    chatRouteSoftPreloadHandle = idleRequest(scheduleSoft, { timeout: 1_200 });
  } else {
    chatRouteSoftPreloadHandle = window.setTimeout(scheduleSoft, 250);
  }
}

type RouteLocationLike = {
  pathname: string;
  search: string;
  hash: string;
};

type ConfigSummaryWithThemeBackground = ConfigSummary & {
  themeBackgroundImageUrl?: unknown;
  themeBackgroundReadability?: unknown;
};

type WorkbenchShellStyle = CSSProperties & {
  "--workbench-theme-background-image"?: string;
};

type ThemeBackgroundReadability = "soft" | "standard" | "strong";

export function syncWorkbenchThemeRoot(theme: WorkbenchTheme): () => void {
  if (typeof document === "undefined") {
    return () => undefined;
  }
  const root = document.documentElement;
  const previousTheme = root.dataset.theme;
  const previousColorScheme = root.style.colorScheme;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  return () => {
    if (previousTheme === undefined) {
      delete root.dataset.theme;
    } else {
      root.dataset.theme = previousTheme;
    }
    root.style.colorScheme = previousColorScheme;
  };
}

function configThemeBackgroundImageUrl(summary: ConfigSummary | undefined): string {
  const value = (summary as ConfigSummaryWithThemeBackground | undefined)?.themeBackgroundImageUrl;
  const url = typeof value === "string" ? value.trim() : "";
  if (!url.startsWith("/api/config/theme-background-image/")) {
    return "";
  }
  return url;
}

function configThemeBackgroundReadability(
  summary: ConfigSummary | undefined,
  hasBackgroundImage: boolean,
): ThemeBackgroundReadability {
  if (!hasBackgroundImage) {
    return "standard";
  }
  const value = (summary as ConfigSummaryWithThemeBackground | undefined)?.themeBackgroundReadability;
  if (value === "soft" || value === "standard" || value === "strong") {
    return value;
  }
  return "standard";
}

export function routeLocationKey(location: RouteLocationLike): string {
  return `${location.pathname || "/"}${location.search || ""}${location.hash || ""}`;
}

const API_FAILURE_TELEMETRY_THROTTLE_MS = 15_000;
const API_FAILURE_BACKGROUND_METHODS = new Set(["GET", "HEAD"]);
const BROWSER_MEMORY_SAMPLE_INTERVAL_MS = 30_000;
const PAGEHIDE_NETWORK_FAILURE_SUPPRESSION_MS = 2_500;
const RETURN_NAVIGATION_STACK_STORAGE_KEY = "vibelution:return-navigation-stack";

function readStoredReturnNavigationStack(): ReturnNavigationEntry[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    return parseReturnNavigationStack(window.sessionStorage.getItem(RETURN_NAVIGATION_STACK_STORAGE_KEY));
  } catch {
    return [];
  }
}

function writeStoredReturnNavigationStack(stack: ReturnNavigationEntry[]) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.sessionStorage.setItem(RETURN_NAVIGATION_STACK_STORAGE_KEY, serializeReturnNavigationStack(stack));
  } catch {
    // Session storage may be unavailable in restricted browser modes; the in-memory stack still works.
  }
}

function routeLocationFromRouter(location: RouteLocationLike): RouteLocationLike {
  return {
    pathname: location.pathname,
    search: location.search || "",
    hash: location.hash || "",
  };
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

/** Shorten long session/run ids for the active-work popover (full value stays on title). */
export function formatActiveWorkRunId(runId: string | null | undefined): string {
  const value = String(runId ?? "").trim();
  if (!value) {
    return "";
  }
  if (value.length <= 28) {
    return value;
  }
  return `${value.slice(0, 12)}…${value.slice(-10)}`;
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
  const { request: requestLifecycle } = useWorkbenchLifecycleActions("app_shell");
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
  const [statusGuideOpen, setStatusGuideOpen] = useState(false);
  const topBarMode = useShellStore((state) => state.topBarMode);
  const setTopBarMode = useShellStore((state) => state.setTopBarMode);
  const topBarHidden = topBarMode === "hidden";
  const desktopShell = useMemo(() => isElectronDesktopShell(), []);
  const [theme, setTheme] = useState(() => readStoredWorkbenchTheme());
  const [frontendVisible, setFrontendVisible] = useState(
    () => (typeof document === "undefined" ? true : document.visibilityState === "visible"),
  );
  const [frontendOnline, setFrontendOnline] = useState(
    () => (typeof navigator === "undefined" ? true : navigator.onLine),
  );
  const [frontendRefreshRequested, setFrontendRefreshRequested] = useState(false);
  const [shellStartupDataReady, setShellStartupDataReady] = useState(false);
  const [returnNavigationStack, setReturnNavigationStack] = useState(() => readStoredReturnNavigationStack());
  const shutdownPromiseRef = useRef<Promise<void> | null>(null);
  const restartPromiseRef = useRef<Promise<void> | null>(null);
  const restartCompletionDismissTimerRef = useRef<number | null>(null);
  const lifecycleRequestSeqRef = useRef(0);
  const lifecycleOverlayDismissedRef = useRef(false);


  const shutdownLocalCompletionLoggedRef = useRef(false);
  const telemetrySeqRef = useRef(0);
  const pageInstanceIdRef = useRef(getPageInstanceId());
  const startupWarmupTelemetryStateRef = useRef<"active" | "inactive" | null>(null);
  const apiFailureTelemetrySeenRef = useRef(new Map<string, number>());
  const pagehideAtMsRef = useRef(0);
  const previousReturnLocationRef = useRef<RouteLocationLike>(routeLocationFromRouter(location));
  const suppressNextReturnStackPushRef = useRef(false);
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: ({ signal }) => fetchPublicConfig({ signal }),
  });
  const branchInstancesQuery = useQuery({
    queryKey: queryKeys.launcherBranchInstances(),
    queryFn: () => getLocalBranchInstances(),
    staleTime: 15_000,
  });
  const workbenchWindowTitle = currentInstanceWindowTitle("workbench", branchInstancesQuery.data);
  const themeBackgroundImageUrl = configThemeBackgroundImageUrl(configQuery.data);
  const themeBackgroundReadability = configThemeBackgroundReadability(
    configQuery.data,
    Boolean(themeBackgroundImageUrl),
  );
  const shellStyle = useMemo<WorkbenchShellStyle | undefined>(
    () =>
      themeBackgroundImageUrl
        ? {
            "--workbench-theme-background-image": `url(${JSON.stringify(themeBackgroundImageUrl)})`,
          }
        : undefined,
    [themeBackgroundImageUrl],
  );
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
  const backendHealthQuery = useQuery({
    queryKey: queryKeys.backendHealth(),
    queryFn: ({ signal }) =>
      fetchJson<BackendHealth>("/api/health", {
        cache: "no-store",
        signal,
      }),
    refetchInterval: runtimeRefetchInterval,
    refetchIntervalInBackground: shellStartupWarmupActive,
    staleTime: 0,
    retry: false,
    // Ignore fetchStatus churn so background health polls do not re-render the whole shell.
    notifyOnChangeProps: ["data", "error", "isError", "isPending", "isSuccess", "isRefetchError"],
  });
  // Phase-1 shell ready depends only on config + health; runtime summary is a phase-2 enhancement.
  useEffect(() => {
    if (configQuery.data && backendHealthQuery.data) {
      setShellStartupDataReady(true);
    }
  }, [backendHealthQuery.data, configQuery.data]);
  const runtimeQuery = useQuery<RuntimeSummary>({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: ({ signal }) => fetchJson<RuntimeSummary>("/api/runtime/summary", { signal }),
    enabled: shellStartupDataReady,
    refetchInterval: runtimeRefetchInterval,
    refetchIntervalInBackground: shellStartupWarmupActive,
    // Heartbeat-only field churn must not re-render the whole shell + route tree.
    structuralSharing: shareRuntimeSummaryIfOnlyVolatileChanged,
    notifyOnChangeProps: ["data", "error", "isError", "isPending", "isSuccess", "isRefetchError"],
  });
  // Running-code freshness: compare the commit this backend was started from
  // with disk HEAD. Refetched on window focus + periodic poll; git reads are
  // lock-free (GIT_OPTIONAL_LOCKS=0) and cheap.
  const codeFreshnessQuery = useQuery<CodeFreshness>({
    queryKey: queryKeys.codeFreshness(),
    queryFn: ({ signal }) => fetchJson<CodeFreshness>("/api/runtime/code-freshness", { signal }),
    enabled: shellStartupDataReady,
    refetchInterval: resolvePollingInterval(shellPollingVisible, 120_000),
    refetchIntervalInBackground: false,
    staleTime: 30_000,
    notifyOnChangeProps: ["data", "error", "isError", "isPending", "isSuccess", "isRefetchError"],
  });

  useEffect(() => syncWorkbenchThemeRoot(theme), [theme]);

  // Project-local layout memory (port/origin stable) + F11/windowed size memory.
  useEffect(() => startWorkbenchUiPreferencesSync(), []);
  useEffect(() => startWorkbenchWindowMemory(), []);

  useEffect(() => {
    const previous = previousReturnLocationRef.current;
    const current = routeLocationFromRouter(location);
    if (suppressNextReturnStackPushRef.current) {
      suppressNextReturnStackPushRef.current = false;
      previousReturnLocationRef.current = current;
      return;
    }
    if (isMeaningfulRouteChange(previous, current)) {
      setReturnNavigationStack((existing) => {
        const next = appendReturnNavigationEntry(existing, previous, current);
        writeStoredReturnNavigationStack(next);
        return next;
      });
    }
    previousReturnLocationRef.current = current;
  }, [location, navigationType]);

  const workbench = runtimeQuery.data?.workbench;
  const lifecycleProof = runtimeQuery.data?.lifecycleProof;
  const shutdownInFlight = workbench?.desiredState === "closed" && workbench?.observedState !== "closed";
  const chatEnabled = isWorkbenchDomainEnabled(configQuery.data, "chat");
  const supervisedEvolutionEnabled = isWorkbenchModeEnabled(configQuery.data, "supervised_evolution");
  const selfEvolutionEnabled = isWorkbenchModeEnabled(configQuery.data, "self_evolution");
  const refreshFrontendLabel = lang === "en" ? "Refresh frontend" : "刷新前端";
  const hideTopBarLabel = lang === "en" ? "Hide top bar" : "隐藏顶部栏";
  const showTopBarLabel = lang === "en" ? "Show top bar" : "显示顶部栏";
  const cancelShutdownLabel = lang === "en" ? "Cancel close" : "取消关闭";
  const cancelRestartLabel = lang === "en" ? "Cancel restart" : "取消重启";
  const cancellingLifecycleLabel = lang === "en" ? "Cancelling..." : "正在取消...";
  const themeToggleLabel = theme === "dark" ? t("switchToLightTheme") : t("switchToDarkTheme");
  const returnNavigationTarget = useMemo(
    () => resolveReturnTarget(routeLocationFromRouter(location), returnNavigationStack),
    [location, returnNavigationStack],
  );
  const returnNavigationLabel = useMemo(() => {
    if (!returnNavigationTarget) {
      return "";
    }
    if (returnNavigationTarget.source === "explicit") {
      const raw = String(new URLSearchParams(location.search).get("returnLabel") || "").trim();
      if (raw && raw.length <= 80) {
        return raw;
      }
    }
    return lang === "en" ? "Back" : "返回";
  }, [lang, location.search, returnNavigationTarget]);
  const activePrimaryRouteLabel = useMemo(() => {
    const pathname = location.pathname;
    if (pathname.startsWith("/companions")) return t("navCompanions");
    if (pathname.startsWith("/chat")) return t("navChat");
    if (pathname.startsWith("/supervised-evolution")) return t("navSupervisedEvolution");
    if (pathname.startsWith("/self-evolution")) return t("navSelfEvolution");
    if (pathname.startsWith("/teams")) return t("navTeams");
    if (pathname.startsWith("/kernel")) return "Kernel";
    if (pathname.startsWith("/memory")) return t("navMemory");
    if (pathname.startsWith("/agents")) return t("navAgents");
    return t("appTitle");
  }, [location.pathname, t]);
  const handleReturnNavigation = useCallback(() => {
    if (!returnNavigationTarget) {
      return;
    }
    const targetPath = returnNavigationTarget.path;
    suppressNextReturnStackPushRef.current = true;
    setReturnNavigationStack((current) => {
      const next = consumeReturnNavigationTarget(current, targetPath);
      writeStoredReturnNavigationStack(next);
      return next;
    });
    navigate(targetPath);
  }, [navigate, returnNavigationTarget]);
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
  const startupOverlayActive = shouldRenderStartupOverlay(startupPanel, desktopShell);
  const shutdownLocallyComplete = shouldTreatShutdownAsLocallyComplete({
    shutdownRequested,
    backendState,
    backendUnavailable: backendHealthQuery.isError || backendHealthQuery.isRefetchError,
    runtimeSummaryUnavailable: runtimeQuery.isError || runtimeQuery.isRefetchError,
    workbench,
  });
  const activeWorkIndicator = deriveActiveWorkIndicator(runtimeQuery.data, lang);
  // Human-readable only (no raw session ids). Used for shutdown/restart copy and aria, not native title.
  const activeWorkDetailsTitle = activeWorkIndicator?.items.map((item) => item.detail).join(" · ") ?? "";
  const activeWorkChipAriaLabel = activeWorkIndicator
    ? [
      t("activeWorkNow"),
      activeWorkIndicator.label,
      statusLabel(activeWorkIndicator.status),
      activeWorkIndicator.count > 1
        ? `${activeWorkIndicator.count} ${t("activeWorkCountSuffix")}`
        : "",
      activeWorkIndicator.items[0]?.summary,
    ].filter(Boolean).join(" · ")
    : "";
  const buildId = __VIBELUTION_BUILD_ID__;
  const clearRestartCompletionDismissTimer = useCallback(() => {
    if (restartCompletionDismissTimerRef.current === null) {
      return;
    }
    window.clearTimeout(restartCompletionDismissTimerRef.current);
    restartCompletionDismissTimerRef.current = null;
  }, []);
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

  // Keep the latest router location for primary-nav telemetry and no-op click
  // detection without stale closures.
  const routerLocationRef = useRef(location);
  routerLocationRef.current = location;

  const navigatePrimaryNav = useCallback((to: string) => {
    emitBrowserTelemetry({
      phase: "navigation",
      eventCode: "browser.primary_nav.click",
      message: `Primary navigation click to ${to}`,
      fields: {
        to,
        fromPathname: routerLocationRef.current.pathname,
      },
    });
    if (to === "/chat" || to.startsWith("/chat?")) {
      preloadChatRouteForNav("click");
    }
    if (routeLocationKey(routerLocationRef.current) !== to) {
      navigate(to);
    }
  }, [emitBrowserTelemetry, navigate]);

  const handlePrimaryNavClick = useCallback(
    (event: ReactMouseEvent<HTMLAnchorElement>, to: string) => {
      if (event.defaultPrevented || isModifiedPrimaryNavClick(event)) {
        return;
      }
      // Force SPA navigation so Electron/title-bar hit testing cannot leave a focused but inert link.
      event.preventDefault();
      navigatePrimaryNav(to);
    },
    [navigatePrimaryNav],
  );

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
      clearRestartCompletionDismissTimer();
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

      const payload = await requestLifecycle("stop");
      if (requestSeq !== lifecycleRequestSeqRef.current) {
        if (payload.commandId) {
          cancelSupersededLifecycleCommand(payload.commandId, "shutdown");
        }
        return;
      }
      markControlledProjectLifecycleOperation("stop");
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
      const blocked = parseRuntimeControlBlockedDetail(error);
      if (isActiveWorkStopBlocked(blocked)) {
        lifecycleOverlayDismissedRef.current = false;
        const blockedDetails = formatActiveWorkRunsDetail(blocked?.activeWorkRuns);
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
    clearRestartCompletionDismissTimer,
    emitBrowserTelemetry,
    lang,
    requestLifecycle,
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
      clearRestartCompletionDismissTimer();
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

      const payload = await requestLifecycle("force-stop");
      if (requestSeq !== lifecycleRequestSeqRef.current) {
        return;
      }
      markControlledProjectLifecycleOperation("force-stop");
      allowNextWorkbenchWindowUnload();
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
    clearRestartCompletionDismissTimer,
    emitBrowserTelemetry,
    forceShutdownBody,
    forceShutdownHeading,
    requestLifecycle,
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
      clearRestartCompletionDismissTimer();
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

      const payload = await requestLifecycle("restart");
      if (requestSeq !== lifecycleRequestSeqRef.current) {
        if (payload.commandId) {
          cancelSupersededLifecycleCommand(payload.commandId, "restart");
        }
        return;
      }
      markControlledProjectLifecycleOperation("restart");
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
      const blocked = parseRuntimeControlBlockedDetail(error);
      if (isActiveWorkRestartBlocked(blocked)) {
        lifecycleOverlayDismissedRef.current = false;
        const blockedDetails = formatActiveWorkRunsDetail(blocked?.activeWorkRuns);
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
    clearRestartCompletionDismissTimer,
    emitBrowserTelemetry,
    lang,
    requestLifecycle,
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
    // Synchronous pass before reload — React state alone races beforeunload (dialog flash).
    allowNextWorkbenchWindowUnload();
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
    window.location.reload();
  }, [emitBrowserTelemetry]);

  // Stable beforeunload via useStableBeforeUnload (ref + no polled deps).
  // Re-binding on status poll makes Edge flash "重新加载应用?" then dismiss it.
  const projectCloseGuardRef = useRef({
    activeWorkCount: activeWorkIndicator?.count ?? 0,
    emitBrowserTelemetry,
    frontendRefreshRequested,
    restartRequested,
    runtimeControllerState,
    shutdownRequested,
    workbenchCloseGuardMessage,
  });
  projectCloseGuardRef.current = {
    activeWorkCount: activeWorkIndicator?.count ?? 0,
    emitBrowserTelemetry,
    frontendRefreshRequested,
    restartRequested,
    runtimeControllerState,
    shutdownRequested,
    workbenchCloseGuardMessage,
  };

  useStableBeforeUnload((event) => {
    // Intentional refresh / chunk recovery — skip prompt (sync one-shot flag).
    if (consumeNextWorkbenchWindowUnloadAllowance()) {
      clearPendingWorkbenchWindowCloseIntent();
      return;
    }
    if (hasRecentControlledProjectLifecycleOperation()) {
      clearPendingWorkbenchWindowCloseIntent();
      return;
    }
    const guard = projectCloseGuardRef.current;
    const closeBlocked = shouldBlockWorkbenchWindowClose({
      controlledLifecycleOperationInFlight: hasRecentControlledProjectLifecycleOperation(),
      frontendRefreshRequested: guard.frontendRefreshRequested,
      restartRequested: guard.restartRequested,
      runtimeControllerState: guard.runtimeControllerState,
      shutdownRequested: guard.shutdownRequested,
    });
    if (!shouldArmBrowserProjectCloseGuard({
      closeBlocked,
      electronDesktopShell: desktopShell,
    })) {
      clearPendingWorkbenchWindowCloseIntent();
      return;
    }
    const closeIntent = prepareWorkbenchWindowCloseIntent({
      activeWorkCount: guard.activeWorkCount,
      confirmationAvailable: navigator.userActivation?.hasBeenActive !== false,
    });
    if (closeIntent.requiresConfirmation) {
      guard.emitBrowserTelemetry(
        buildProjectWindowCloseBlockedTelemetry({
          surface: "workbench",
          runtimeControllerState: guard.runtimeControllerState,
        }),
        { preferBeacon: true },
      );
      applyBeforeUnloadProjectCloseGuard(event, guard.workbenchCloseGuardMessage);
    }
  });

  useEffect(() => {
    function handleReloadShortcut(event: KeyboardEvent) {
      if (isWorkbenchRefreshShortcut(event)) {
        allowNextWorkbenchWindowUnload();
        clearPendingWorkbenchWindowCloseIntent();
      }
    }

    window.addEventListener("keydown", handleReloadShortcut);
    return () => window.removeEventListener("keydown", handleReloadShortcut);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next = nextWorkbenchTheme(current);
      writeStoredWorkbenchTheme(next);
      return next;
    });
  }, []);

  useEffect(() => {
    applyWorkbenchDocumentLanguage(document, lang);
    document.title = workbenchWindowTitle;
  }, [lang, workbenchWindowTitle]);

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
    const handleDocumentClick = (event: MouseEvent) => {
      const navLink = shellNavAnchorFromEventTarget(event.target);
      if (navLink && !isModifiedPrimaryNavClick(event)) {
        const to = resolveUnmodifiedShellNavHref(navLink.getAttribute("href"), window.location.origin);
        if (to) {
          // Capture-phase preventDefault stops Electron from doing a full document
          // load of /teams (blank #f7fafc window) when React's onClick does not fire.
          event.preventDefault();
          navigatePrimaryNav(to);
        }
      }
    };

    window.addEventListener("click", handleDocumentClick, true);
    return () => {
      window.removeEventListener("click", handleDocumentClick, true);
    };
  }, [navigatePrimaryNav]);

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
      const windowCloseIntent = desktopShell ? null : consumePendingWorkbenchWindowCloseIntent();
      if (!desktopShell && !event.persisted && windowCloseIntent) {
        requestWorkbenchWindowCloseOnPageHide(windowCloseIntent);
      }
      emitBrowserTelemetry(
        {
          phase: "lifecycle",
          eventCode: "browser.page.hide",
          message: `Page hide at ${window.location.pathname || "/"}`,
          fields: {
            persisted: event.persisted,
            windowCloseIntent: windowCloseIntent ?? "",
            desktopShell,
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
  }, [desktopShell, emitBrowserTelemetry]);

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
      if (restartCompletionDismissTimerRef.current === null) {
        restartCompletionDismissTimerRef.current = window.setTimeout(() => {
          restartCompletionDismissTimerRef.current = null;
          setShutdownOpen(false);
        }, 1_600);
      }
      return;
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

  useEffect(() => clearRestartCompletionDismissTimer, [clearRestartCompletionDismissTimer]);

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
  // Code-freshness: a behind instance is a caution-grade system condition the
  // user should act on (restart), without masking a real failure.
  const codeStale = Boolean(
    codeFreshnessQuery.data
    && (
      codeFreshnessQuery.data.verdict === "backend_behind"
      || codeFreshnessQuery.data.verdict === "frontend_behind"
      || codeFreshnessQuery.data.verdict === "backend_and_frontend_behind"
    ),
  );
  const effectivePrimaryStatusCard = codeStale && primaryStatusCard.tone !== "failed"
    ? { ...primaryStatusCard, tone: "caution" as const }
    : primaryStatusCard;
  const statusSummaryTitle = rightStatusCards.map((item) => `${item.label}: ${item.value}`).join(" · ");

  return (
    <div
      className={styles.shell}
      data-theme={theme}
      data-desktop-shell={desktopShell ? "electron" : "browser"}
      data-vui-app="workbench"
      data-theme-background={themeBackgroundImageUrl ? "custom" : "default"}
      data-theme-background-readability={themeBackgroundImageUrl ? themeBackgroundReadability : undefined}
      data-topbar-mode={topBarMode}
      data-shell="workbench"
      data-browser-role="workbench"
      style={shellStyle}
    >
      {startupOverlayActive && !shutdownOpen ? (
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
                <VButton
                  type="button"
                  variant="secondary"
                  className={styles.shutdownCancelButton}
                  onPress={cancelLifecycleWait}
                  isDisabled={lifecycleCancelPending}
                >
                  {lifecycleCancelPending
                    ? cancellingLifecycleLabel
                    : lifecycleAction === "restart"
                      ? cancelRestartLabel
                      : cancelShutdownLabel}
                </VButton>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
      {topBarHidden ? (
        <VButton
          type="button"
          variant="secondary"
          className={styles.topBarRestoreButton}
          aria-label={showTopBarLabel}
          title={showTopBarLabel}
          onPress={() => setTopBarMode("full")}
          icon={<PanelTopOpen size={15} />}
        >
          <span>{showTopBarLabel}</span>
        </VButton>
      ) : null}
      <header className={styles.topBar}>
        <div className={styles.brandBlock} data-shell-group="brand">
          {returnNavigationTarget ? (
            <VIconButton
              type="button"
              variant="secondary"
              className={styles.returnButton}
              onPress={handleReturnNavigation}
              label={returnNavigationLabel}
              title={returnNavigationLabel}
              icon={<ArrowLeft size={16} />}
            />
          ) : null}
          {activeWorkIndicator ? (
            <VPopover
              align="start"
              side="bottom"
              sideOffset={8}
              aria-label={t("activeWorkDetails")}
              contentClassName={styles.activeWorkPopoverContent}
              data-vui="active-work-popover"
              trigger={(
                <VButton
                  type="button"
                  variant="secondary"
                  contentLayout="plain"
                  className={styles.activeWorkChip}
                  aria-haspopup="dialog"
                  aria-label={activeWorkChipAriaLabel}
                >
                  <VStatusChip
                    tone={systemToneToStatus(activeWorkIndicator.tone)}
                    className={styles.activeWorkToneChip}
                  >
                    {activeWorkIndicator.tone === "running"
                      ? t("activeWorkNow")
                      : statusLabel(activeWorkIndicator.status)}
                  </VStatusChip>
                  <strong>{activeWorkIndicator.label}</strong>
                  <span className={styles.activeWorkInlineDetails} aria-hidden="true">
                    {activeWorkIndicator.items.slice(0, 2).map((item) => (
                      <span key={`${item.kind}-${item.runId || item.status}-inline`} className={styles.activeWorkInlineItem}>
                        <span>{item.summary}</span>
                      </span>
                    ))}
                  </span>
                  {activeWorkIndicator.overflowCount > 0 ? (
                    <span className={styles.activeWorkMore}>
                      {t("activeWorkMorePrefix")}
                      {activeWorkIndicator.overflowCount}
                    </span>
                  ) : null}
                </VButton>
              )}
            >
              <div className={styles.activeWorkDetailPanel} role="note">
                <div className={styles.activeWorkDetailHeader}>
                  <strong>{t("activeWorkDetails")}</strong>
                  <span>
                    {activeWorkIndicator.count} {t("activeWorkCountSuffix")}
                  </span>
                </div>
                <ul className={styles.activeWorkDetailList}>
                  {activeWorkIndicator.items.map((item) => {
                    const runIdDisplay = formatActiveWorkRunId(item.runId);
                    const detailAria = [item.label, statusLabel(item.status), item.summary].filter(Boolean).join(" · ");
                    const detailCopy = (
                      <div className={styles.activeWorkDetailCopy}>
                        <div className={styles.activeWorkDetailTitle}>
                          <strong>{item.label}</strong>
                        </div>
                        {item.fullSummary ? <p>{item.fullSummary}</p> : null}
                        {runIdDisplay ? (
                          <code title={item.runId || undefined}>{runIdDisplay}</code>
                        ) : null}
                      </div>
                    );
                    return (
                      <li key={`${item.kind}-${item.runId || item.status}`} className={styles.activeWorkDetailItem}>
                        <VStatusChip tone={systemToneToStatus(item.tone)} className={styles.activeWorkItemToneChip}>
                          {statusLabel(item.status)}
                        </VStatusChip>
                        {item.href ? (
                          <Link className={styles.activeWorkDetailLink} to={item.href} aria-label={detailAria}>
                            {detailCopy}
                          </Link>
                        ) : detailCopy}
                      </li>
                    );
                  })}
                </ul>
              </div>
            </VPopover>
          ) : null}
        </div>

        <nav className={styles.nav} data-shell-group="navigation" aria-label={lang === "en" ? "Primary navigation" : "主导航"}>
          {chatEnabled ? (
            <VRouteLinkButton
              chrome="shell-nav"
              to="/chat"
              className={shellPrimaryNavClass(location.pathname, "/chat")}
              aria-current={isShellPrimaryNavActive(location.pathname, "/chat") ? "page" : undefined}
              onPointerEnter={() => preloadChatRouteForNav("pointerenter")}
              onFocus={() => preloadChatRouteForNav("focus")}
              onClick={(event) => handlePrimaryNavClick(event, "/chat")}
            >
              {t("navChat")}
            </VRouteLinkButton>
          ) : (
            <span className={`${styles.navLink} ${styles.navLinkDisabled}`} aria-disabled="true" title={lang === "en" ? "Chat is disabled" : "对话未启用"}>
              {t("navChat")}
            </span>
          )}
          {chatEnabled ? (
            <VRouteLinkButton
              chrome="shell-nav"
              to="/companions"
              className={shellPrimaryNavClass(location.pathname, "/companions")}
              aria-current={isShellPrimaryNavActive(location.pathname, "/companions") ? "page" : undefined}
              onClick={(event) => handlePrimaryNavClick(event, "/companions")}
            >
              {t("navCompanions")}
            </VRouteLinkButton>
          ) : (
            <span className={`${styles.navLink} ${styles.navLinkDisabled}`} aria-disabled="true" title={lang === "en" ? "Chat is disabled" : "对话未启用"}>
              {t("navCompanions")}
            </span>
          )}
          {supervisedEvolutionEnabled ? (
            <VRouteLinkButton
              chrome="shell-nav"
              to="/supervised-evolution"
              className={shellPrimaryNavClass(location.pathname, "/supervised-evolution")}
              aria-current={isShellPrimaryNavActive(location.pathname, "/supervised-evolution") ? "page" : undefined}
              onClick={(event) => handlePrimaryNavClick(event, "/supervised-evolution")}
            >
              {t("navSupervisedEvolution")}
            </VRouteLinkButton>
          ) : (
            <span className={`${styles.navLink} ${styles.navLinkDisabled}`} aria-disabled="true" title={lang === "en" ? "Supervised evolution is disabled" : "监督进化未启用"}>
              {t("navSupervisedEvolution")}
            </span>
          )}
          {selfEvolutionEnabled ? (
            <VRouteLinkButton
              chrome="shell-nav"
              to="/self-evolution"
              className={shellPrimaryNavClass(location.pathname, "/self-evolution")}
              aria-current={isShellPrimaryNavActive(location.pathname, "/self-evolution") ? "page" : undefined}
              onClick={(event) => handlePrimaryNavClick(event, "/self-evolution")}
            >
              {t("navSelfEvolution")}
            </VRouteLinkButton>
          ) : (
            <span className={`${styles.navLink} ${styles.navLinkDisabled}`} aria-disabled="true" title={lang === "en" ? "Self evolution is disabled" : "自进化未启用"}>
              {t("navSelfEvolution")}
            </span>
          )}
          <VRouteLinkButton
            chrome="shell-nav"
            to="/teams"
            className={shellPrimaryNavClass(location.pathname, "/teams")}
            aria-current={isShellPrimaryNavActive(location.pathname, "/teams") ? "page" : undefined}
            onClick={(event) => handlePrimaryNavClick(event, "/teams")}
          >
            {t("navTeams")}
          </VRouteLinkButton>
          <VRouteLinkButton
            chrome="shell-nav"
            to="/kernel"
            className={shellPrimaryNavClass(location.pathname, "/kernel")}
            aria-current={isShellPrimaryNavActive(location.pathname, "/kernel") ? "page" : undefined}
            onClick={(event) => handlePrimaryNavClick(event, "/kernel")}
          >
            Kernel
          </VRouteLinkButton>
          <VRouteLinkButton
            chrome="shell-nav"
            to="/memory"
            className={shellPrimaryNavClass(location.pathname, "/memory")}
            aria-current={isShellPrimaryNavActive(location.pathname, "/memory") ? "page" : undefined}
            onClick={(event) => handlePrimaryNavClick(event, "/memory")}
          >
            {t("navMemory")}
          </VRouteLinkButton>
          <VRouteLinkButton
            chrome="shell-nav"
            to="/agents"
            className={shellPrimaryNavClass(location.pathname, "/agents")}
            aria-current={isShellPrimaryNavActive(location.pathname, "/agents") ? "page" : undefined}
            onClick={(event) => handlePrimaryNavClick(event, "/agents")}
            onPointerEnter={() => {
              // C1.1: soft-warm Agents structured workbench copy (not flat TranslationKey).
              void import("../i18n/loadAgentsWorkbenchCopy").then((module) => {
                module.prefetchAgentsWorkbenchCopy();
              });
            }}
          >
            {t("navAgents")}
          </VRouteLinkButton>
        </nav>
        <div className={styles.mobileNav} data-shell-group="mobile-navigation" aria-label={activePrimaryRouteLabel}>
          <span className={styles.mobileNavLabel}>{activePrimaryRouteLabel}</span>
        </div>

        <div className={styles.topActions} data-shell-group="system-actions">
          <div
            className={
              utilityOpen
                ? `${styles.utilityCluster} ${styles.utilityClusterOpen}`
                : styles.utilityCluster
            }
            aria-label={t("topUtilityMenu")}
            title={t("topUtilityMenu")}
          >
            <VPopover
              open={utilityOpen}
              onOpenChange={setUtilityOpen}
              align="end"
              side="bottom"
              sideOffset={8}
              aria-label={t("topUtilityMenu")}
              contentClassName={styles.utilityPopoverContent}
              trigger={(
                <VButton
                  type="button"
                  variant="ghost"
                  className={styles.utilityTrigger}
                  aria-haspopup="dialog"
                  aria-expanded={utilityOpen}
                  aria-label={t("topUtilityMenu")}
                  title={t("topUtilityMenu")}
                  icon={<Wrench size={15} />}
                  trailingIcon={<ChevronDown size={13} className={styles.utilityChevron} />}
                >
                  <span className={styles.utilityTriggerLabel}>{t("topUtilityMenuShort")}</span>
                </VButton>
              )}
            >
              <div className={styles.utilityPopoverBody}>
                <nav id="shell-mobile-route-menu" className={styles.mobileRouteMenu} aria-label={lang === "en" ? "Primary navigation" : "主导航"}>
                  {chatEnabled ? (
                    <VRouteLinkButton
                      chrome="shell-nav"
                      to="/chat"
                      className={shellMobileNavClass(location.pathname, "/chat")}
                      aria-current={isShellPrimaryNavActive(location.pathname, "/chat") ? "page" : undefined}
                      onClick={() => {
                        preloadChatRouteForNav("click");
                        closeUtilityMenu();
                      }}
                    >
                      {t("navChat")}
                    </VRouteLinkButton>
                  ) : <span className={styles.mobileRouteLink} aria-disabled="true">{t("navChat")}</span>}
                  {supervisedEvolutionEnabled ? (
                    <VRouteLinkButton
                      chrome="shell-nav"
                      to="/supervised-evolution"
                      className={shellMobileNavClass(location.pathname, "/supervised-evolution")}
                      aria-current={isShellPrimaryNavActive(location.pathname, "/supervised-evolution") ? "page" : undefined}
                      onClick={closeUtilityMenu}
                    >
                      {t("navSupervisedEvolution")}
                    </VRouteLinkButton>
                  ) : <span className={styles.mobileRouteLink} aria-disabled="true">{t("navSupervisedEvolution")}</span>}
                  {selfEvolutionEnabled ? (
                    <VRouteLinkButton
                      chrome="shell-nav"
                      to="/self-evolution"
                      className={shellMobileNavClass(location.pathname, "/self-evolution")}
                      aria-current={isShellPrimaryNavActive(location.pathname, "/self-evolution") ? "page" : undefined}
                      onClick={closeUtilityMenu}
                    >
                      {t("navSelfEvolution")}
                    </VRouteLinkButton>
                  ) : <span className={styles.mobileRouteLink} aria-disabled="true">{t("navSelfEvolution")}</span>}
                  <VRouteLinkButton chrome="shell-nav" to="/teams" className={shellMobileNavClass(location.pathname, "/teams")} aria-current={isShellPrimaryNavActive(location.pathname, "/teams") ? "page" : undefined} onClick={closeUtilityMenu}>
                    {t("navTeams")}
                  </VRouteLinkButton>
                  <VRouteLinkButton chrome="shell-nav" to="/kernel" className={shellMobileNavClass(location.pathname, "/kernel")} aria-current={isShellPrimaryNavActive(location.pathname, "/kernel") ? "page" : undefined} onClick={closeUtilityMenu}>
                    Kernel
                  </VRouteLinkButton>
                  <VRouteLinkButton chrome="shell-nav" to="/memory" className={shellMobileNavClass(location.pathname, "/memory")} aria-current={isShellPrimaryNavActive(location.pathname, "/memory") ? "page" : undefined} onClick={closeUtilityMenu}>
                    {t("navMemory")}
                  </VRouteLinkButton>
                  <VRouteLinkButton chrome="shell-nav" to="/agents" className={shellMobileNavClass(location.pathname, "/agents")} aria-current={isShellPrimaryNavActive(location.pathname, "/agents") ? "page" : undefined} onClick={closeUtilityMenu}>
                    {t("navAgents")}
                  </VRouteLinkButton>
                </nav>
                <Suspense fallback={null}>
                  <LazyAppShellUtilityMenu
                    lang={lang}
                    t={t}
                    frontendVisible={frontendVisible}
                    onClose={closeUtilityMenu}
                  />
                </Suspense>
              </div>
            </VPopover>
          </div>
          <div className={styles.statusCluster} data-shell-group="status-guide">
            <VPopover
              open={statusGuideOpen}
              onOpenChange={setStatusGuideOpen}
              align="end"
              side="bottom"
              sideOffset={10}
              aria-label={t("systemStatusGuide")}
              contentClassName={styles.statusGuidePopoverContent}
              data-vui="status-guide-popover"
              trigger={(
                <VButton
                  type="button"
                  variant="ghost"
                  contentLayout="plain"
                  className={styles.statusSummaryChip}
                  title={statusSummaryTitle}
                  aria-haspopup="dialog"
                  aria-expanded={statusGuideOpen}
                  aria-label={`${t("systemStatusGuide")}: ${effectivePrimaryStatusCard.label} ${effectivePrimaryStatusCard.value}`}
                >
                  <span
                    aria-hidden="true"
                    className={`${styles.statusSummaryDot} ${systemToneToDotClass(effectivePrimaryStatusCard.tone)}`}
                  />
                  <span className={styles.statusSummaryLabel}>
                    {effectivePrimaryStatusCard.label} {effectivePrimaryStatusCard.value}
                  </span>
                </VButton>
              )}
            >
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
                  codeFreshness={codeFreshnessQuery.data}
                />
              </Suspense>
            </VPopover>
          </div>
          <div className={styles.toolCluster} data-shell-group="tool-actions">
            <VIconButton
              type="button"
              variant="ghost"
              className={styles.actionIconButton}
              label={themeToggleLabel}
              tooltip={themeToggleLabel}
              title={themeToggleLabel}
              icon={theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
              onPress={toggleTheme}
            />
            <VIconButton
              type="button"
              variant="ghost"
              className={styles.actionIconButton}
              label={refreshFrontendLabel}
              tooltip={refreshFrontendLabel}
              title={refreshFrontendLabel}
              icon={<RefreshCw size={16} />}
              onPress={refreshFrontend}
              isDisabled={restartRequested || shutdownRequested || (shutdownInFlight && !shutdownSettled)}
            />
            <VIconButton
              type="button"
              variant="ghost"
              className={styles.actionIconButton}
              label={hideTopBarLabel}
              tooltip={hideTopBarLabel}
              title={hideTopBarLabel}
              icon={<PanelTopClose size={16} />}
              onPress={() => setTopBarMode("hidden")}
            />
            <VRouteLinkButton
              to="/config"
              variant="ghost"
              className={styles.actionIconButton}
              aria-label={t("navConfig")}
              title={t("navConfig")}
              icon={<Settings size={16} aria-hidden="true" />}
            />
          </div>
        </div>
      </header>

      <main className={styles.mainArea}>
        <CompanionDesktopAttention />
        <Outlet />
      </main>
    </div>
  );
}
