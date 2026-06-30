import { describe, expect, it } from "vitest";

import routeSource from "./LauncherRoute.tsx?raw";
import stylesSource from "./LauncherRoute.styles.ts?raw";
import { launcherRouteStyles as styles } from "./LauncherRoute.styles";
import launcherApiSource from "../api/launcher.ts?raw";
import routerSource from "../app/router.tsx?raw";
import shellSource from "../app/AppShell.tsx?raw";
import utilityMenuSource from "../app/AppShellUtilityMenu.tsx?raw";
import launcherShellSource from "../app/LauncherShell.tsx?raw";

const routeStylesSource = stylesSource;

const sourceSlice = (source: string, startMarker: string, endMarker: string): string => {
  const startIndex = source.indexOf(startMarker);
  expect(startIndex).toBeGreaterThanOrEqual(0);
  const endIndex = source.indexOf(endMarker, startIndex + startMarker.length);
  expect(endIndex).toBeGreaterThan(startIndex);
  return source.slice(startIndex, endIndex);
};

describe("LauncherRoute layout contract", () => {
  it("routes launcher controls through VUI primitives", () => {
    expect(routeSource).toContain("from \"../components/vui\"");
    expect(routeSource).toContain("<VButton");
    expect(routeSource).toContain("<VNativeInput");
    expect(routeSource).toContain("<VNativeSelect");
    expect(routeSource).not.toMatch(/<button\b/);
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
  });

  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("mounts the Launcher as an independent top-level control surface", () => {
    expect(routerSource).toContain("const LauncherRoute = lazyRoute");
    expect(routerSource).toContain('path: "/launcher"');
    expect(routerSource).toContain("element: <LauncherShell />");
    expect(routerSource).toContain('guardedLazyElement(<LauncherRoute />, "launcher")');
    expect(routerSource).not.toContain('{ path: "launcher", element: lazyElement(<LauncherRoute />) }');
    expect(shellSource).toContain("LazyAppShellUtilityMenu");
    expect(utilityMenuSource).toContain('href="/launcher"');
    expect(utilityMenuSource).toContain('target="_blank"');
    expect(utilityMenuSource).toContain('lang === "zh" ? "启动器" : "Launcher"');
    expect(launcherShellSource).toContain('data-shell="launcher"');
    expect(launcherShellSource).toContain('data-browser-role="launcher_control_surface"');
    expect(launcherShellSource).toContain('reason: "launcher_shell_mounted"');
    expect(launcherShellSource).toContain("<Outlet />");
    expect(launcherShellSource).not.toContain("<nav");
    expect(launcherShellSource).not.toContain("NavLink");
    expect(launcherShellSource).toContain('data-vui-app="launcher"');
    expect(launcherShellSource).toContain("text-vui-fg-primary");
  });

  it("uses the typed launcher lifecycle API client", () => {
    expect(routeSource).toContain("getLauncherStatus");
    expect(routeSource).toContain("startLauncherBundle");
    expect(routeSource).toContain("stopLauncherBundle");
    expect(routeSource).toContain("forceStopLauncherBundle");
    expect(routeSource).toContain("restartLauncherBundle()");
    expect(routeSource).toContain("updateLauncherStartupSettings");
    expect(routeSource).toContain("updateLauncherDeveloperMode");
    expect(routeSource).toContain("previewLauncherDeveloperCleanup");
    expect(routeSource).toContain("applyLauncherDeveloperCleanup");
    expect(routeSource).not.toContain("updateWorkbenchWindowMode");
    expect(routeSource).toContain("reattachLauncherSupervisor");
    expect(routeSource).toContain("queryKeys.launcherStatus()");
    expect(routeSource).toContain("queryKeys.launcherDeveloperNoiseOverview()");
    expect(routeSource).toContain("queryKeys.runtimeSummary()");
  });

  it("keeps launcher controls fresh while the control surface is minimized", () => {
    expect(routeSource).toContain("isControlPlaneIdle");
    expect(routeSource).toContain("refetchInterval: resolvePollingInterval(pageVisible, 4_000, { backgroundMs: 4_000 })");
    expect(routeSource).toContain("refetchIntervalInBackground: true");
    expect(routeSource).toContain("const controlPlaneIdle = isControlPlaneIdle(evidence)");
    expect(routeSource).toContain("const controlBusy = controlMutation.isPending && !(controlPlaneIdle && lifecycleSettled)");
    expect(routeSource).toContain("const busy = controlBusy || supervisorMutation.isPending");
    expect(routeSource).toContain("const startDisabled = launcherStatusDisconnected || busy || !controlPlaneIdle || projectIsOpen || projectIsChanging");
    expect(routeSource).toContain("const startDisabledReason = launcherStatusDisconnected");
    expect(routeSource).toContain("startDisabledReason");
    expect(routeSource).toContain("startDisabledBusy");
    expect(routeSource).toContain("title={startDisabled ? startDisabledReason : copy.start}");
    expect(routeSource).toContain("projectIsClosed\n        ? copy.noActiveWork\n      : copy.restartClear");
    expect(routeSource).toContain("const destructiveActionDisabled = busy || !controlPlaneIdle || activeWorkCount > 0 || projectIsChanging || projectIsClosed");
    expect(routeSource).toContain("lifecycleActionDisabledActiveWork");
    expect(routeSource).toContain("const stopDisabled = destructiveActionDisabled || closeCommandInFlight");
    expect(routeSource).toContain("const stopDisabledReason = projectIsClosed");
    expect(routeSource).toContain("stopDisabledClosed");
    expect(routeSource).toContain("stopDisabledInFlight");
    expect(routeSource).toContain("title={stopDisabled ? stopDisabledReason : copy.stop}");
    expect(routeSource).toContain("title={destructiveActionDisabled ? destructiveActionDisabledReason : copy.restart}");
    expect(routeSource).toContain("restartDisabledClosed");
    expect(routeSource).toContain("actionsStartOnly");
    expect(routeSource).toContain("controlPlaneHasCommandType(evidence, [\"close_workbench\", \"force_close_workbench\"])");
    expect(routeSource).toContain("const forceStopDisabled = busy || projectIsClosed || closeCommandInFlight");
    expect(routeSource).toContain("forceStopDisabledReason");
    expect(routeSource).toContain("forceStopDisabledInFlight");
    expect(routeSource).toContain("title={forceStopDisabled ? forceStopDisabledReason : copy.forceStop}");
  });

  it("renders a dense lifecycle console rather than a landing page", () => {
    expect(routeSource).toContain("summaryStrip");
    expect(routeSource).toContain("userGuide");
    expect(routeSource).toContain("guardStrip");
    expect(routeSource).toContain("statusTable");
    expect(routeSource).toContain("matrixPanel");
    expect(routeSource).toContain("specGrid");
    expect(routeSource).toContain("projectBundle");
    expect(routeSource).toContain("StatusRow");
    expect(routeSource).toContain("statusRows");
    expect(routeSource).toContain("keyStatusRows");
    expect(routeSource).toContain("diagnosticStatusRows");
    expect(routeSource).toContain("activeWorkCount");
    expect(routeSource).toContain("controlPlaneEvidence");
    expect(routeSource).toContain("guardianAdapter");
    expect(routeSource).toContain("recoveryLine");
    expect(routeSource).toContain("evidence?.recovery");
    expect(routeSource).toContain("CompactList");
    expect(routeSource).toContain("guardianTable");
    expect(routeSource).toContain("diagnosticsPanel");
    expect(routeSource).toContain("diagnosticsBody");
    expect(routeSource).toContain("diagnosticSection");
    expect(routeSource).toContain("settingsStrip");
    expect(routeSource).toContain("settingsHeader");
    expect(routeSource).toContain("settingField");
    expect(routeSource).toContain("settingToggle");
    expect(routeSource).toContain("settingsSaveButton");
    expect(routeSource).toContain("segmentedControl");
    expect(routeSource).toContain("DeveloperModePanel");
    expect(routeSource).toContain("developerPanel");
    expect(routeSource).toContain("cleanupPlan");
    expect(routeSource).toContain("guardian?.supervisor?.stdoutPath");
    expect(routeSource).toContain("guardian?.supervisor?.stderrPath");
    expect(routeSource).not.toContain("hero");
    expect(routeSource).not.toContain("cardGrid");
    expect(styles.summaryStrip).toBeTypeOf("string");
    expect(styles.userGuide).toBeTypeOf("string");
    expect(styles.settingsStrip).toBeTypeOf("string");
    expect(styles.settingsHeader).toBeTypeOf("string");
    expect(styles.settingField).toBeTypeOf("string");
    expect(styles.settingToggle).toBeTypeOf("string");
    expect(styles.settingsSaveButton).toBeTypeOf("string");
    expect(styles.settingError).toBeTypeOf("string");
    expect(styles.segmentedControl).toBeTypeOf("string");
    expect(styles.developerPanel).toBeTypeOf("string");
    expect(styles.developerGrid).toBeTypeOf("string");
    expect(styles.cleanupConsole).toBeTypeOf("string");
    expect(styles.cleanupPlan).toBeTypeOf("string");
    expect(styles.guardStrip).toBeTypeOf("string");
    expect(styles.statusTable).toBeTypeOf("string");
    expect(styles.matrixPanel).toBeTypeOf("string");
    expect(styles.guardianTable).toBeTypeOf("string");
    expect(styles.diagnosticsPanel).toBeTypeOf("string");
    expect(styles.diagnosticsBody).toBeTypeOf("string");
    expect(styles.diagnosticSection).toBeTypeOf("string");
    expect(styles.recoveryLine).toBeTypeOf("string");
    expect(styles.specGrid).toBeTypeOf("string");
    expect(styles.dangerButton).toBeTypeOf("string");
  });

  it("puts user-readable launcher status before technical diagnostics", () => {
    expect(routeSource).toContain("projectStatus");
    expect(routeSource).toContain("launcherStatus");
    expect(routeSource).toContain("lifecycleStatus");
    expect(routeSource).toContain("resolveLifecycleDisplay");
    expect(routeSource).toContain("isControlTokenError");
    expect(routeSource).toContain("activeWork");
    expect(routeSource).toContain("restartProtected");
    expect(routeSource).toContain("noActiveWork");
    expect(routeSource).toContain("userAction");
    expect(routeSource).toContain("projectRunning");
    expect(routeSource).toContain("lifecycleRunning");
    expect(routeSource).toContain("lifecyclePartial");
    expect(routeSource).toContain('observed === "partial"');
    expect(routeSource).toContain("lifecycleStarting");
    expect(routeSource).toContain("lifecycleStopping");
    expect(routeSource).toContain("lifecycleRestarting");
    expect(routeSource).toContain("lifecycleReadingLimited");
    expect(routeSource).toContain("controlLimited");
    expect(routeSource).toContain("controlReady");
    expect(routeSource).toContain("safeToUse");
    expect(routeSource).toContain("userGuideTitle");
    expect(routeSource).toContain("userGuideDetail");
    expect(routeSource).toContain("actionLockLabel");
    expect(routeSource).toContain("actionsLocked");
    expect(routeSource).toContain("actionsAvailable");
    expect(routeSource).toContain("nextActionDetail");
    expect(routeSource).toContain("openWorkbenchSummary");
    expect(routeSource).toContain("componentLabel");
    expect(routeSource).toContain("responsibilityLabel");
    expect(routeSource).toContain("responsibilityOwner");
    expect(routeSource).toContain("humanState");
    expect(routeSource).toContain("humanCommandType");
    expect(routeSource).toContain("advancedDetails");
    expect(routeSource).toContain("advancedDiagnostics");
    expect(routeSource).toContain("internalMigrationDetails");
    expect(routeSource).toContain("title={row.technical}");
    expect(routeSource).not.toContain("部分接管");
    expect(routeSource).not.toContain("Partially owned");
    expect(routeSource).not.toContain("<span role=\"columnheader\">{copy.pid}</span>");
    expect(routeSource).not.toContain("helper={`${copy.queue}:");
    expect(styles.metric).toBeTypeOf("string");
  });

  it("summarizes raw lifecycle errors before they reach the first-read Launcher UI", () => {
    expect(routeSource).toContain("function summarizeLauncherMessage");
    expect(routeSource).toContain("workbench is not ready");
    expect(routeSource).toContain("backendportlistening=false");
    expect(routeSource).toContain("backendPortUnavailableSummary");
    expect(routeSource).toContain("technicalDetailAvailable");
    expect(routeSource).toContain("lifecycleDetailShort");
    expect(routeSource).toContain("userGuideDetailShort");
    expect(routeSource).toContain("noticeTextShort");
    expect(routeSource).toContain("helperTitle={lifecycleDisplay.detail}");
    expect(routeSource).toContain("aria-label={lifecycleDisplay.detail || copy.subtitle}");
    expect(routeSource).toContain("title={notice.text}");
    expect(routeSource).toContain("title={row.technical}");
    expect(routeSource).not.toContain("<p className={styles.subtitle}>{lifecycleDisplay.detail || copy.subtitle}</p>");
    expect(routeSource).not.toContain("<small>{userGuideDetail}</small>");
    expect(routeSource).not.toContain("{notice.text !== noticeTextShort ? <span>{copy.technicalDetailAvailable}</span> : null}");
  });

  it("keeps guidance terse while preserving detail in hover titles", () => {
    expect(routeSource).toContain('className={styles.userGuide} data-tone={userGuideTone} title={userGuideDetail}');
    expect(routeSource).not.toContain("<small title={userGuideDetail}>{userGuideDetailShort}</small>");
    expect(routeStylesSource).toContain("userGuide:");
    expect(routeStylesSource).toContain("overflow-wrap-anywhere");
    expect(routeStylesSource).toContain("whitespace-normal");
    expect(routeStylesSource).toContain("col-auto");
  });

  it("uses a light dense Launcher surface with muted action buttons", () => {
    expect(routeStylesSource).toContain("bg-[var(--surface-page)]");
    expect(routeStylesSource).toContain("bg-[color-mix(in_srgb,var(--surface-panel)_86%,transparent)]");
    expect(routeStylesSource).toContain("bg-[color-mix(in_srgb,var(--accent-primary)_10%,var(--surface-card))]");
    expect(routeStylesSource).toContain("bg-[color-mix(in_srgb,var(--danger)_7%,var(--surface-card))]");
    expect(routeStylesSource).toContain("min-h-7");
    expect(routeStylesSource).toContain("px-2");
    expect(routeStylesSource).toContain("w-fit");
    expect(routeStylesSource).toContain("whitespace-nowrap");
    expect(launcherShellSource).toContain("var(--vui-gradient-route-soft)");
    expect(launcherShellSource).toContain("var(--fg-primary)");
  });

  it("keeps the complete launcher surface reachable when the window is short", () => {
    expect(routeStylesSource).toContain("content-start");
    expect(routeStylesSource).toContain("overflow-y-auto");
    expect(routeStylesSource).toContain("overflow-x-hidden");
    expect(routeStylesSource).toContain("overscroll-contain");
    expect(routeStylesSource).toContain("[scrollbar-gutter:stable]");
    expect(routeStylesSource).toContain("pb-[max(12px,env(safe-area-inset-bottom))]");
    expect(routeStylesSource).toContain("pb-[max(14px,env(safe-area-inset-bottom))]");
    expect(routeStylesSource).toContain("overflow-visible");
    expect(routeStylesSource).not.toContain("grid-rows-[auto_auto_auto_auto_auto_minmax(0,1fr)]");
  });

  it("keeps internal lifecycle fields out of the first-read labels", () => {
    expect(routeSource).toContain('matrix: "项目组成"');
    expect(routeSource).toContain('keyStatus: "关键状态"');
    expect(routeSource).toContain('controlPlane: "维护范围"');
    expect(routeSource).toContain('guardian: "托管明细"');
    expect(routeSource).toContain('advancedDiagnostics: "高级诊断"');
    expect(routeSource).toContain('userGuide: "当前建议"');
    expect(routeSource).toContain('userGuideReady: "可以继续使用"');
    expect(routeSource).toContain('userGuideBlocked: "先等任务完成"');
    expect(routeSource).toContain('actionsLocked: "停止/重启已保护"');
    expect(routeSource).toContain('diagnosticsCollapsedHint: "排查时展开"');
    expect(routeSource).toContain("后台守护检查未运行，不影响当前项目使用。");
    expect(routeSource).toContain("Launcher 正在维护项目启动、停止、重启、后端、窗口和日志证据。");
    expect(routeSource).toContain("有任务运行时，Launcher 会拒绝停止或重启");
    expect(routeSource).not.toContain("任务结束后自动重启");
    expect(routeSource).toContain("内部迁移细节");
    expect(routeSource).not.toContain('controlPlane: "启动器职责"');
    expect(routeSource).not.toContain('guardian: "接管进度"');
    expect(routeSource).not.toContain("旧守护进程未运行");
    expect(routeSource).not.toContain("<span role=\"columnheader\">{copy.adapter}</span>");
    expect(routeSource).toContain("后端服务");
    expect(routeSource).toContain("工作台窗口");
  });

  it("keeps command streams and guardian details collapsed by default", () => {
    expect(routeSource).toContain("<details className={`${styles.panel} ${styles.diagnosticsPanel}`}>");
    expect(routeSource).not.toContain("<details open");
    expect(routeSource).toContain("queueAndEvents");
    expect(routeSource).toContain("diagnosticsCollapsedHint");
    expect(routeSource).toContain("recoveryIdle");
    expect(routeSource).toContain("recovery.statusLine");
    expect(routeSource).toContain("maintenanceDetails");
    expect(routeSource).toContain("recentResults.map");
    expect(routeSource).toContain("guardian?.responsibilities");
    expect(routeSource).toContain("diagnosticsGrid");
  });

  it("promotes the final queued command result to the main notice", () => {
    expect(routeSource).toContain("LauncherTrackedCommand");
    expect(routeSource).toContain("trackedCommand");
    expect(routeSource).toContain("trackedResult");
    expect(routeSource).toContain("resultMessage");
    expect(routeSource).toContain("launcherControlNoticeMessage");
    expect(routeSource).toContain('operation === "force-stop"');
    expect(routeSource).toContain("force_close_workbench");
    expect(routeSource).toContain("activeWorkCount");
    expect(routeSource).toContain('tone: response.accepted ? "neutral" : "warning"');
    expect(routeSource).toContain('setNotice({ tone, text: message, source: "lifecycle-control" })');
    expect(routeSource).toContain("Restart preflight failed before closing the workbench");
  });

  it("records launcher lifecycle requests and clears stale lifecycle errors from source-of-truth status", () => {
    expect(routeSource).toContain("setTrackedCommand(response.accepted && response.commandId ? { commandId: response.commandId, operation } : null)");
    expect(routeSource).toContain("clearControlledProjectLifecycleOperation()");
    expect(routeSource).toContain("trackedCommand?.operation === \"stop\"");
    expect(routeSource).toContain("trackedCommand?.operation === \"force-stop\"");
    expect(routeSource).toContain("trackedCommand?.operation === \"restart\"");
    expect(routeSource).toContain("if (!trackedCommand || !trackedResult) {");
    expect(routeSource).toContain('setNotice({ tone, text: message, source: "lifecycle-control" })');
    expect(routeSource).toContain("setTrackedCommand(null)");
    expect(routeSource).toContain("setLastControlOperation(null)");
    expect(routeSource).toContain("postLauncherLifecycleControlTelemetry(operation, \"requested\")");
    expect(routeSource).toContain("launcher.lifecycle_control.${status}");
    expect(routeSource).toContain('status: "requested" | "accepted" | "rejected" | "request_failed"');
    expect(routeSource).toContain('response.accepted ? "accepted" : "rejected"');
    expect(routeSource).toContain('postLauncherLifecycleControlTelemetry(operation, "request_failed"');
    expect(routeSource).toContain('source: "lifecycle-control"');
    expect(routeSource).toContain("launcherOperationSettledByStatus");
    expect(routeSource).toContain("trackedCommandSettledByStatus");
    expect(routeSource).toContain("shouldClearStaleLifecycleNotice");
    expect(routeSource).toContain('setNotice({ tone: "neutral", text: "" })');
  });

  it("surfaces last close request provenance in Launcher diagnostics", () => {
    expect(routeSource).toContain("lastRequestAudit = bundle?.lastOperation.requestAudit ?? {}");
    expect(routeSource).toContain("lastRequestTrigger");
    expect(routeSource).toContain("lastRequestEndpoint");
    expect(routeSource).toContain("requestTrigger");
    expect(routeSource).toContain("requestEndpoint");
    expect(routeSource).toContain("<Spec label={copy.requestTrigger} value={lastRequestTrigger} />");
    expect(routeSource).toContain("<Spec label={copy.requestEndpoint} value={lastRequestEndpoint} />");
  });

  it("keeps lifecycle actions icon-backed and compact", () => {
    expect(routeSource).toContain("<Play size={15} />");
    expect(routeSource).toContain("<Square size={15} />");
    expect(routeSource).toContain("<Power size={15} />");
    expect(routeSource).toContain("<RefreshCw size={15} />");
    expect(routeSource).toContain("<ExternalLink size={15} />");
    expect(routeSource).toContain("<Maximize2 size={14} />");
    expect(routeSource).toContain("<Minimize2 size={14} />");
    expect(routeSource).toContain('controlMutation.mutate("start")');
    expect(routeSource).toContain('controlMutation.mutate("stop")');
    expect(routeSource).toContain('controlMutation.mutate("force-stop")');
    expect(routeSource).toContain('controlMutation.mutate("restart")');
    expect(routeSource).toContain('windowMode: "fullscreen"');
    expect(routeSource).toContain('windowMode: "windowed"');
    expect(routeSource).toContain("supervisorMutation.mutate()");
  });

  it("collects normal lifecycle controls into the Launcher status bar", () => {
    expect(styles.statusBar).toBeTypeOf("string");
    expect(styles.statusBarReason).toBeTypeOf("string");
    expect(styles.statusBarActions).toBeTypeOf("string");
    expect(styles.statusBarButton).toBeTypeOf("string");
    expect(styles.dangerActions).toBeTypeOf("string");

    expect(routeSource).toContain("lifecycleControls");
    expect(routeSource).toContain("const statusBarBlockerReason =");
    expect(routeSource).toContain("const statusBarReasonText =");
    expect(routeSource).toContain("title={statusBarBlockerReason}");

    const statusBarActions = sourceSlice(
      routeSource,
      '<div className={styles.statusBarActions} aria-label={copy.lifecycleControls}>',
      "\n              {bundle?.url ? (",
    );
    const refreshIndex = statusBarActions.indexOf("statusQuery.refetch()");
    const startIndex = statusBarActions.indexOf('controlMutation.mutate("start")');
    const restartIndex = statusBarActions.indexOf('controlMutation.mutate("restart")');
    const stopIndex = statusBarActions.indexOf('controlMutation.mutate("stop")');
    expect(refreshIndex).toBeGreaterThanOrEqual(0);
    expect(startIndex).toBeGreaterThan(refreshIndex);
    expect(restartIndex).toBeGreaterThan(startIndex);
    expect(stopIndex).toBeGreaterThan(restartIndex);
    expect(statusBarActions).not.toContain('controlMutation.mutate("force-stop")');
    expect(statusBarActions).not.toContain("copy.forceStop");
    expect(statusBarActions).not.toContain("dangerButton");

    const dangerActions = sourceSlice(
      routeSource,
      '<div className={styles.dangerActions}>',
      "\n        </div>\n      </div>\n\n      <LauncherStartupSettingsPanel",
    );
    expect(dangerActions).toContain('controlMutation.mutate("force-stop")');
    expect(dangerActions).toContain("copy.forceStop");
    expect(dangerActions).toContain("dangerButton");
  });

  it("lets Launcher own startup settings without restarting immediately", () => {
    expect(routeSource).toContain("LauncherStartupSettingsPanel");
    expect(routeSource).toContain("startupSettingsMutation");
    expect(routeSource).toContain("mutationFn: updateLauncherStartupSettings");
    expect(routeSource).toContain("WorkbenchWindowModeUpdateRequest");
    expect(routeSource).toContain("settings?.startup");
    expect(launcherApiSource).toContain("baseHash: setting.configHash");
    expect(launcherApiSource).toContain("WorkbenchWindowModeUpdateRequest");
    expect(routeSource).toContain("onWindowModeChange({ mode, baseHash: current.configHash })");
    expect(routeSource).toContain('onError: (error) => {\n      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error), source: "window-mode" });\n      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });');
    expect(routeSource).toContain("configHash");
    expect(routeSource).toContain("runtimeProfile");
    expect(routeSource).toContain("launcherControlPort");
    expect(routeSource).toContain("backendPort");
    expect(routeSource).toContain("frontendPort");
    expect(routeSource).toContain("windowSize");
    expect(routeSource).toContain("windowSizeOptions");
    expect(routeSource).toContain("interfaceLanguage");
    expect(routeSource).toContain("preflightDoctor");
    expect(routeSource).toContain("requireVenv");
    expect(routeSource).toContain("parsePortDraft");
    expect(routeSource).toContain("setValidationError(copy.invalidPort)");
    expect(routeSource).toContain('role="alert"');
    expect(routeSource).toContain("configuredWindowMode");
    expect(routeSource).toContain("effectiveWindowMode");
    expect(routeSource).toContain("envOverrideMode");
    expect(routeSource).toContain("workbenchWindowModeLabel");
    expect(routeSource).toContain("windowModeRestartRequired");
    expect(routeSource).toContain("windowModeEnvOverride");
    expect(routeSource).toContain("queryKeys.configWorkspace()");
    expect(launcherApiSource).toContain("controlPort: setting.launcher.controlPort");
    expect(launcherApiSource).toContain("windowSize: setting.workbench.windowSize");
    expect(routeSource).not.toContain("windowModeMutation");
  });

  it("keeps developer mode launcher-owned with preview and plan-hash cleanup guards", () => {
    expect(routeSource).toContain("developerModeSetting = status?.settings?.developerMode");
    expect(routeSource).toContain("developerModeMutation");
    expect(routeSource).toContain("mutationFn: updateLauncherDeveloperMode");
    expect(routeSource).toContain("cleanupPreviewMutation");
    expect(routeSource).toContain("cleanupApplyMutation");
    expect(routeSource).toContain("getLauncherDeveloperNoiseOverview");
    expect(routeSource).toContain("previewLauncherDeveloperCleanup");
    expect(routeSource).toContain("applyLauncherDeveloperCleanup");
    expect(routeSource).toContain("planId: cleanupPlan.planId");
    expect(routeSource).toContain("planHash: cleanupPlan.planHash");
    expect(routeSource).toContain("confirm: true");
    expect(routeSource).toContain("window.confirm(copy.cleanupRequiresConfirm)");
    expect(routeSource).toContain("开发者模式");
    expect(routeSource).toContain("当前状态");
    expect(routeSource).toContain("最近保存");
    expect(routeSource).toContain("developerModeStateLabel");
    expect(routeSource).toContain("developerModeCurrentState}: ${developerModeStateLabel}");
    expect(routeSource).toContain("设置页只读展示，不能在工作台设置里改动");
    expect(launcherApiSource).toContain("developer-mode/cleanup/preview");
    expect(launcherApiSource).toContain("developer-mode/cleanup/apply");
  });

  it("makes Launcher the owner of project reset and initialization maintenance", () => {
    expect(routeSource).toContain("ProjectMaintenancePanel");
    expect(routeSource).toContain("getLauncherMaintenanceSummary");
    expect(routeSource).toContain("previewLauncherMaintenancePlan");
    expect(routeSource).toContain("applyLauncherMaintenancePlan");
    expect(routeSource).toContain("maintenanceProfile");
    expect(routeSource).toContain("maintenancePlansByProfile");
    expect(routeSource).toContain("setMaintenancePlansByProfile");
    expect(routeSource).toContain('useState<LauncherMaintenanceProfileId>("clean_start")');
    expect(routeSource).not.toContain('useState<LauncherMaintenanceProfileId>("factory_runtime")');
    expect(routeSource).toContain("profileId: maintenanceProfile");
    expect(routeSource).toContain("launcherMaintenanceSummary()");
    expect(routeSource).toContain("maintenance/reset/summary");
    expect(routeSource).toContain("maintenance/reset/preview");
    expect(routeSource).toContain("maintenance/reset/apply");
    expect(routeSource).toContain("Launcher 维护中心");
    expect(routeSource).toContain("恢复初始化");
    expect(routeSource).toContain("active work");
    expect(launcherApiSource).toContain("maintenance/reset/summary");
    expect(launcherApiSource).toContain("maintenance/reset/preview");
    expect(launcherApiSource).toContain("maintenance/reset/apply");
    expect(routeSource).not.toContain('"/api/reset/');
    expect(sourceSlice(routeSource, "onProfileChange={(profile) => {", "onPreview={previewMaintenancePlan}")).not.toContain(
      "setMaintenancePlan(null)",
    );
  });

  it("treats status disconnect after stop as an expected closed state", () => {
    expect(routeSource).toContain("stoppedStatusUnavailable");
    expect(routeSource).toContain("isLauncherStatusNetworkDisconnect");
    expect(routeSource).toContain("launcherControlLimited");
    expect(routeSource).toContain("launcherStatusDisconnected");
    expect(routeSource).toContain("lastControlOperation");
    expect(routeSource).toContain('setLastControlOperation((operation === "stop" || operation === "force-stop") && response.accepted ? operation : null)');
    expect(routeSource).toContain('statusQuery.isError && (lastControlOperation === "stop" || lastControlOperation === "force-stop" || launcherStatusDisconnected)');
    expect(routeSource).toContain('data-tone={expectedStopDisconnect ? "success" : launcherControlLimited ? "warning" : "error"}');
    expect(routeSource).toContain("工作台已关闭，Launcher 后端连接已断开。重新启动后会恢复状态。");
    expect(routeSource).toContain("当前看到的是旧前端页面，不代表项目仍在运行。");
    expect(routeSource).toContain("当前缺少有效控制 token；请刷新后再执行启动、停止或重启。");
    expect(routeSource).toContain("项目可能仍在运行，但 Launcher 状态接口需要重新取得控制权限。");
    expect(routeSource).toContain("Workbench is closed; the Launcher backend connection is no longer available. Start again to restore status.");
    expect(routeSource).toContain("This is a stale frontend page and does not mean the project is still running.");
    expect(routeSource).toContain("A valid control token is missing; refresh before start, stop, or restart.");
  });

  it("blocks direct Launcher window closes while preserving controlled stop force-stop and restart", () => {
    expect(routeSource).toContain("launcherCloseBlocked");
    expect(routeSource).toContain("controlledCloseOperationInFlight");
    expect(routeSource).toContain('lastControlOperation === "stop" || lastControlOperation === "force-stop" || lastControlOperation === "restart"');
    expect(routeSource).toContain("trackedCommand?.operation === \"stop\"");
    expect(routeSource).toContain("trackedCommand?.operation === \"force-stop\"");
    expect(routeSource).toContain("trackedCommand?.operation === \"restart\"");
    expect(routeSource).toContain("buildProjectWindowCloseBlockedTelemetry");
    expect(routeSource).toContain("markControlledProjectLifecycleOperation(operation)");
    expect(routeSource).toContain("clearControlledProjectLifecycleOperation()");
    expect(routeSource).toContain('window.addEventListener("beforeunload", handleBeforeUnload)');
  });
});
