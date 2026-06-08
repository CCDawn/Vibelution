import { describe, expect, it } from "vitest";

import routeSource from "./LauncherRoute.tsx?raw";
import styles from "./LauncherRoute.module.css";
import routerSource from "../app/router.tsx?raw";
import shellSource from "../app/AppShell.tsx?raw";
import launcherShellSource from "../app/LauncherShell.tsx?raw";
import launcherShellStyles from "../app/LauncherShell.module.css";

describe("LauncherRoute layout contract", () => {
  it("mounts the Launcher as an independent top-level control surface", () => {
    expect(routerSource).toContain("const LauncherRoute = lazyRoute");
    expect(routerSource).toContain('path: "/launcher"');
    expect(routerSource).toContain("element: <LauncherShell />");
    expect(routerSource).toContain("lazyElement(<LauncherRoute />)");
    expect(routerSource).not.toContain('{ path: "launcher", element: lazyElement(<LauncherRoute />) }');
    expect(shellSource).toContain('href="/launcher"');
    expect(shellSource).toContain('target="_blank"');
    expect(shellSource).toContain('lang === "zh" ? "启动器" : "Launcher"');
    expect(launcherShellSource).toContain('data-shell="launcher"');
    expect(launcherShellSource).toContain('data-browser-role="launcher_control_surface"');
    expect(launcherShellSource).toContain('reason: "launcher_shell_mounted"');
    expect(launcherShellSource).toContain("<Outlet />");
    expect(launcherShellSource).not.toContain("<nav");
    expect(launcherShellSource).not.toContain("NavLink");
    expect(launcherShellStyles.shell).toBeTypeOf("string");
  });

  it("uses the typed launcher lifecycle API client", () => {
    expect(routeSource).toContain("getLauncherStatus");
    expect(routeSource).toContain("startLauncherBundle");
    expect(routeSource).toContain("stopLauncherBundle");
    expect(routeSource).toContain("restartLauncherBundle()");
    expect(routeSource).toContain("updateWorkbenchWindowMode");
    expect(routeSource).toContain("reattachLauncherSupervisor");
    expect(routeSource).toContain("queryKeys.launcherStatus()");
    expect(routeSource).toContain("queryKeys.runtimeSummary()");
  });

  it("keeps launcher controls fresh while the control surface is minimized", () => {
    expect(routeSource).toContain("isControlPlaneIdle");
    expect(routeSource).toContain("refetchInterval: resolvePollingInterval(pageVisible, 4_000, { backgroundMs: 4_000 })");
    expect(routeSource).toContain("refetchIntervalInBackground: true");
    expect(routeSource).toContain("const controlPlaneIdle = isControlPlaneIdle(evidence)");
    expect(routeSource).toContain("const controlBusy = controlMutation.isPending && !(controlPlaneIdle && lifecycleSettled)");
    expect(routeSource).toContain("const busy = controlBusy || supervisorMutation.isPending");
    expect(routeSource).toContain("startDisabledReason");
    expect(routeSource).toContain("startDisabledBusy");
    expect(routeSource).toContain("title={startDisabled ? startDisabledReason : copy.start}");
    expect(routeSource).toContain("const destructiveActionDisabled = busy || activeWorkCount > 0");
    expect(routeSource).toContain("lifecycleActionDisabledActiveWork");
    expect(routeSource).toContain("title={destructiveActionDisabled ? destructiveActionDisabledReason : copy.stop}");
    expect(routeSource).toContain("title={destructiveActionDisabled ? destructiveActionDisabledReason : copy.restart}");
  });

  it("renders a dense lifecycle console rather than a landing page", () => {
    expect(routeSource).toContain("summaryStrip");
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
    expect(routeSource).toContain("segmentedControl");
    expect(routeSource).toContain("guardian?.supervisor?.stdoutPath");
    expect(routeSource).toContain("guardian?.supervisor?.stderrPath");
    expect(routeSource).not.toContain("hero");
    expect(routeSource).not.toContain("cardGrid");
    expect(styles.summaryStrip).toBeTypeOf("string");
    expect(styles.settingsStrip).toBeTypeOf("string");
    expect(styles.segmentedControl).toBeTypeOf("string");
    expect(styles.guardStrip).toBeTypeOf("string");
    expect(styles.statusTable).toBeTypeOf("string");
    expect(styles.matrixPanel).toBeTypeOf("string");
    expect(styles.guardianTable).toBeTypeOf("string");
    expect(styles.diagnosticsPanel).toBeTypeOf("string");
    expect(styles.diagnosticsBody).toBeTypeOf("string");
    expect(styles.diagnosticSection).toBeTypeOf("string");
    expect(styles.recoveryLine).toBeTypeOf("string");
    expect(styles.specGrid).toBeTypeOf("string");
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
    expect(routeSource).toContain("lifecycleStarting");
    expect(routeSource).toContain("lifecycleStopping");
    expect(routeSource).toContain("lifecycleRestarting");
    expect(routeSource).toContain("lifecycleReadingLimited");
    expect(routeSource).toContain("controlLimited");
    expect(routeSource).toContain("controlReady");
    expect(routeSource).toContain("safeToUse");
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

  it("keeps internal lifecycle fields out of the first-read labels", () => {
    expect(routeSource).toContain('matrix: "项目组成"');
    expect(routeSource).toContain('keyStatus: "关键状态"');
    expect(routeSource).toContain('controlPlane: "维护范围"');
    expect(routeSource).toContain('guardian: "托管明细"');
    expect(routeSource).toContain('advancedDiagnostics: "高级诊断"');
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
    expect(routeSource).toContain('tone: response.accepted ? "neutral" : "warning"');
    expect(routeSource).toContain('setNotice({ tone, text: message })');
    expect(routeSource).toContain("Restart preflight failed before closing the workbench");
  });

  it("keeps lifecycle actions icon-backed and compact", () => {
    expect(routeSource).toContain("<Play size={15} />");
    expect(routeSource).toContain("<Square size={15} />");
    expect(routeSource).toContain("<RefreshCw size={15} />");
    expect(routeSource).toContain("<ExternalLink size={15} />");
    expect(routeSource).toContain("<Maximize2 size={14} />");
    expect(routeSource).toContain("<Minimize2 size={14} />");
    expect(routeSource).toContain('controlMutation.mutate("start")');
    expect(routeSource).toContain('controlMutation.mutate("stop")');
    expect(routeSource).toContain('controlMutation.mutate("restart")');
    expect(routeSource).toContain('windowModeMutation.mutate("fullscreen")');
    expect(routeSource).toContain('windowModeMutation.mutate("windowed")');
    expect(routeSource).toContain("supervisorMutation.mutate()");
  });

  it("labels start as Workbench startup instead of opening the Launcher control surface", () => {
    expect(routeSource).toContain('useStartAction: "启动工作台"');
    expect(routeSource).toContain('useStartAction: "Start Workbench"');
    expect(routeSource).toContain("工作台未运行时，从这里启动后端、前端资源和工作台窗口。");
    expect(routeSource).toContain("When the Workbench is closed, start backend, frontend assets, and the workbench window from here.");
    expect(routeSource).not.toContain('useStartAction: "启动项目"');
    expect(routeSource).not.toContain('useStartAction: "Start project"');
  });

  it("lets Launcher choose the Workbench launch window mode without restarting immediately", () => {
    expect(routeSource).toContain("workbenchWindowSetting");
    expect(routeSource).toContain("configuredWindowMode");
    expect(routeSource).toContain("effectiveWindowMode");
    expect(routeSource).toContain("envOverrideMode");
    expect(routeSource).toContain("workbenchWindowModeLabel");
    expect(routeSource).toContain("windowModeRestartRequired");
    expect(routeSource).toContain("windowModeEnvOverride");
    expect(routeSource).toContain("settings?.workbenchWindow");
    expect(routeSource).toContain("mutationFn: updateWorkbenchWindowMode");
    expect(routeSource).not.toContain("windowModeMutation.mutate(\"fullscreen\"); controlMutation.mutate(\"restart\")");
  });

  it("treats status disconnect after stop as an expected closed state", () => {
    expect(routeSource).toContain("stoppedStatusUnavailable");
    expect(routeSource).toContain("isLauncherStatusNetworkDisconnect");
    expect(routeSource).toContain("launcherControlLimited");
    expect(routeSource).toContain("launcherStatusDisconnected");
    expect(routeSource).toContain("lastControlOperation");
    expect(routeSource).toContain('setLastControlOperation(operation === "stop" && response.accepted ? "stop" : null)');
    expect(routeSource).toContain('statusQuery.isError && (lastControlOperation === "stop" || launcherStatusDisconnected)');
    expect(routeSource).toContain('data-tone={expectedStopDisconnect ? "success" : launcherControlLimited ? "warning" : "error"}');
    expect(routeSource).toContain("工作台已关闭，Launcher 后端连接已断开。重新启动后会恢复状态。");
    expect(routeSource).toContain("当前看到的是旧前端页面，不代表项目仍在运行。");
    expect(routeSource).toContain("当前缺少有效控制 token；请刷新后再执行启动、停止或重启。");
    expect(routeSource).toContain("项目可能仍在运行，但 Launcher 状态接口需要重新取得控制权限。");
    expect(routeSource).toContain("Workbench is closed; the Launcher backend connection is no longer available. Start again to restore status.");
    expect(routeSource).toContain("This is a stale frontend page and does not mean the project is still running.");
    expect(routeSource).toContain("A valid control token is missing; refresh before start, stop, or restart.");
  });
});
