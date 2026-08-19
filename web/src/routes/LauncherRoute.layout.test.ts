import { describe, expect, it } from "vitest";

import routeSource from "./LauncherRoute.tsx?raw";
import developerModePanelSource from "./LauncherDeveloperModePanel.tsx?raw";
import developerModePanelStylesSource from "./LauncherDeveloperModePanel.styles.ts?raw";
import developerModePanelStyles from "./LauncherDeveloperModePanel.styles";
import diagnosticsPanelSource from "./LauncherDiagnosticsPanel.tsx?raw";
import diagnosticsPanelStylesSource from "./LauncherDiagnosticsPanel.styles.ts?raw";
import diagnosticsPanelStyles from "./LauncherDiagnosticsPanel.styles";
import projectMaintenancePanelSource from "./LauncherProjectMaintenancePanel.tsx?raw";
import projectMaintenancePanelStylesSource from "./LauncherProjectMaintenancePanel.styles.ts?raw";
import projectMaintenancePanelStyles from "./LauncherProjectMaintenancePanel.styles";
import startupSettingsPanelSource from "./LauncherStartupSettingsPanel.tsx?raw";
import startupSettingsPanelStylesSource from "./LauncherStartupSettingsPanel.styles.ts?raw";
import startupSettingsPanelStyles from "./LauncherStartupSettingsPanel.styles";
import processMonitorPanelSource from "./LauncherProcessMonitorPanel.tsx?raw";
import processMonitorPanelStylesSource from "./LauncherProcessMonitorPanel.styles.ts?raw";
import processMonitorPanelStyles from "./LauncherProcessMonitorPanel.styles";
import branchInstancesPanelSource from "./LauncherBranchInstancesPanel.tsx?raw";
import branchInstancesPanelStylesSource from "./LauncherBranchInstancesPanel.styles.ts?raw";
import branchInstancesPanelStyles from "./LauncherBranchInstancesPanel.styles";
import stylesSource from "./LauncherRoute.styles.ts?raw";
import { launcherRouteStyles as styles } from "./LauncherRoute.styles";
import launcherApiSource from "../api/launcher.ts?raw";
import routerSource from "../app/router.tsx?raw";
import shellSource from "../app/AppShell.tsx?raw";
import utilityMenuSource from "../app/AppShellUtilityMenu.tsx?raw";
import launcherShellSource from "../app/LauncherShell.tsx?raw";
import launcherShellStylesSource from "../app/LauncherShell.styles.ts?raw";

const routeStylesSource = stylesSource;
const launcherPanelStylesSource = [
  developerModePanelStylesSource,
  diagnosticsPanelStylesSource,
  projectMaintenancePanelStylesSource,
  startupSettingsPanelStylesSource,
  processMonitorPanelStylesSource,
  branchInstancesPanelStylesSource,
].join("\n");

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
    expect(developerModePanelSource).toContain("from \"../components/vui\"");
    expect(startupSettingsPanelSource).toContain("from \"../components/vui\"");
    expect(branchInstancesPanelSource).toContain("from \"../components/vui\"");
    expect(branchInstancesPanelStyles.statusTable).toBeTypeOf("string");
    expect(branchInstancesPanelStyles.statusTable).toContain("w-full");
    expect(developerModePanelSource).toContain('from "./LauncherDeveloperModePanel.styles"');
    expect(diagnosticsPanelSource).toContain('from "./LauncherDiagnosticsPanel.styles"');
    expect(projectMaintenancePanelSource).toContain('from "./LauncherProjectMaintenancePanel.styles"');
    expect(projectMaintenancePanelSource).toContain("<VTabs");
    expect(projectMaintenancePanelSource).toContain("listClassName={styles.segmentedControl}");
    expect(projectMaintenancePanelStyles.segmentedTrigger).toContain("data-[state=active]");
    expect(startupSettingsPanelSource).toContain('from "./LauncherStartupSettingsPanel.styles"');
    expect(developerModePanelSource).not.toContain("LauncherRoute.styles");
    expect(diagnosticsPanelSource).not.toContain("LauncherRoute.styles");
    expect(projectMaintenancePanelSource).not.toContain("LauncherRoute.styles");
    expect(startupSettingsPanelSource).not.toContain("LauncherRoute.styles");
    expect(routeSource).not.toContain("<VButton");
    expect(branchInstancesPanelSource).toContain("<VButton");
    expect(developerModePanelSource).toContain("<VButton");
    expect(startupSettingsPanelSource).toContain("<VButton");
    expect(startupSettingsPanelSource).toContain("<VNativeInput");
    expect(developerModePanelSource).toContain("<VStringSelect");
    expect(startupSettingsPanelSource).toContain("<VStringSelect");
    expect(routeSource).not.toMatch(/<button\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
    expect(developerModePanelSource).not.toMatch(/<button\b/);
    expect(developerModePanelSource).not.toMatch(/<input\b/);
    expect(developerModePanelSource).not.toMatch(/<select\b/);
    expect(developerModePanelSource).not.toMatch(/<textarea\b/);
    expect(startupSettingsPanelSource).not.toMatch(/<button\b/);
    expect(startupSettingsPanelSource).not.toMatch(/<input\b/);
    expect(startupSettingsPanelSource).not.toMatch(/<select\b/);
    expect(startupSettingsPanelSource).not.toMatch(/<textarea\b/);
  });

  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n({ configEnabled: false })");
    expect(routeSource).not.toContain("useAppI18n");
    expect(routeSource).not.toContain("../i18n/dictionary");
    expect(routeSource).not.toContain("../i18n/useAppI18n");
  });

  it("loads secondary launcher panels as lazy route packs (T4)", () => {
    expect(routeSource).toContain('import("./LauncherStartupSettingsPanel")');
    expect(routeSource).toContain('import("./LauncherProjectMaintenancePanel")');
    expect(routeSource).toContain('import("./LauncherDeveloperModePanel")');
    expect(routeSource).toContain('import("./LauncherDiagnosticsPanel")');
    expect(routeSource).not.toMatch(/import \{ LauncherStartupSettingsPanel \} from/);
    expect(routeSource).not.toMatch(/import \{ LauncherDiagnosticsPanel \} from/);
    expect(routeSource).toContain("<Suspense");
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
    expect(launcherShellSource).toContain("className={styles.root}");
    expect(launcherShellStylesSource).toContain("text-vui-fg-primary");
  });

  it("uses the typed launcher lifecycle API client", () => {
    expect(routeSource).toContain("getLauncherStatus");
    expect(routeSource).toContain("getLauncherBranchInstances");
    expect(launcherApiSource).toContain("branch-instances");
    expect(launcherApiSource).toContain("requestBranchInstanceCleanup");
    expect(branchInstancesPanelSource).toContain("VConfirmDialog");
    expect(branchInstancesPanelSource).toContain("BRANCH_INSTANCE_PAGE_SIZE");
    // Lifecycle start/stop/force-stop/restart share one action path with AppShell.
    expect(routeSource).toContain('useWorkbenchLifecycleActions("launcher_route")');
    expect(routeSource).toContain("requestLifecycle(operation)");
    expect(routeSource).toContain("requestBranchInstanceLifecycle");
    expect(routeSource).toContain("buildAllInstanceMonitorRows");
    expect(routeSource).not.toContain("startLauncherBundle");
    expect(routeSource).not.toContain("stopLauncherBundle");
    expect(routeSource).not.toContain("forceStopLauncherBundle");
    expect(routeSource).not.toContain("restartLauncherBundle");
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

  it("uses the Electron state event instead of periodic launcher polling", () => {
    expect(routeSource).toContain("isControlPlaneIdle");
    expect(routeSource).toContain("onLauncherStateChanged");
    expect(routeSource).toContain("queryClient.setQueryData(queryKeys.launcherState(), snapshot)");
    expect(routeSource).toContain('queryKey: ["launcher", "branch-instances"]');
    expect(routeSource).not.toContain("refetchIntervalInBackground");
    expect(routeSource).not.toContain("resolvePollingInterval");
    expect(routeSource).not.toContain("resolveLauncherStatusPollingInterval");
    expect(routeSource).toContain("const controlPlaneIdle = isControlPlaneIdle(evidence)");
    expect(routeSource).toContain("const controlBusy = controlMutation.isPending && !(controlPlaneIdle && lifecycleSettled)");
    expect(routeSource).toContain("const busy = controlBusy || supervisorMutation.isPending");
    expect(routeSource).toContain("const projectSummary = selectedIsCurrent");
    expect(routeSource).toContain("const startDisabled = selectedIsCurrent");
    expect(routeSource).toContain("const startDisabledReason = launcherControlPlaneStarting");
    expect(routeSource).toContain("startDisabledReason");
    expect(routeSource).toContain("startDisabledBusy");
    expect(routeSource).toContain("const destructiveActionDisabled = selectedIsCurrent");
    expect(routeSource).toContain("lifecycleActionDisabledActiveWork");
    expect(routeSource).toContain("const stopDisabled = selectedIsCurrent");
    expect(routeSource).toContain("const stopDisabledReason = selectedIsCurrent");
    expect(routeSource).toContain("stopDisabledClosed");
    expect(routeSource).toContain("stopDisabledInFlight");
    expect(routeSource).toContain("restartDisabledClosed");
    expect(routeSource).toContain("actionsStartOnly");
    expect(routeSource).toContain("controlPlaneHasCommandType(evidence, [\"close_workbench\", \"force_close_workbench\"])");
    expect(routeSource).toContain("const forceStopDisabled = selectedIsCurrent");
    expect(routeSource).toContain("forceStopDisabledReason");
    expect(routeSource).toContain("forceStopDisabledInFlight");
    expect(routeSource).not.toContain("VWorkbenchPowerMenu");
    expect(routeSource).not.toContain("disabledReason={startDisabledReason}");
    expect(routeSource).not.toContain("tooltip={copy.start}");
    expect(routeSource).not.toContain("stopDisabled={stopDisabled}");
    expect(routeSource).not.toContain("forceStopDisabled={forceStopDisabled}");
    expect(routeSource).not.toContain("restartDisabled={destructiveActionDisabled}");
    expect(branchInstancesPanelSource).toContain("onLifecycle");
    expect(branchInstancesPanelSource).toContain("onStopMany");
    expect(branchInstancesPanelSource).toContain('onLifecycle?.(item.id, "start")');
    expect(routeSource).toContain("lifecycleIntents");
    expect(routeSource).toContain("acceptLifecycleIntent");
    expect(routeSource).toContain("shouldApplyLifecycleMutationFeedback");
    expect(routeSource).toContain("requestInstanceLifecycle");
    expect(routeSource).toContain("onSettled:");
    expect(routeSource).not.toContain("lifecycleInFlightRef");
    expect(routeSource).not.toContain("optimisticBranchOperation");
    expect(routeSource).toContain("lifecyclePending={controlMutation.isPending}");
    expect(routeSource.match(/shouldApplyLifecycleMutationFeedback/g)?.length ?? 0).toBeGreaterThanOrEqual(4);
    expect(branchInstancesPanelSource).toContain("isPending={state === \"starting\" || state === \"restarting\"}");
    expect(branchInstancesPanelSource).toContain("clickGuardRef");
    expect(branchInstancesPanelSource).toContain("const startBusy");
    expect(branchInstancesPanelSource).toContain("isDisabled={stopBusy}");
  });

  it("renders a dense lifecycle console rather than a landing page", () => {
    expect(routeSource).toContain("LauncherProcessMonitorPanel");
    expect(routeSource).toContain("advancedFold");
    expect(processMonitorPanelSource).toContain("statusTable");
    expect(routeSource).toContain("LauncherDiagnosticsPanel");
    expect(diagnosticsPanelSource).toContain("specGrid");
    expect(routeSource).toContain("projectBundle");
    expect(routeSource).toContain("StatusRow");
    expect(routeSource).toContain("statusRows");
    expect(routeSource).toContain("statusRows");
    expect(routeSource).toContain("diagnosticStatusRows");
    expect(routeSource).toContain("activeWorkCount");
    expect(routeSource).toContain("controlPlaneEvidence");
    expect(routeSource).toContain("guardianAdapter");
    expect(routeSource).toContain("recoveryLine");
    expect(routeSource).toContain("evidence?.recovery");
    expect(routeSource).toContain("diagnosticQueueItems");
    expect(routeSource).toContain("guardianResponsibilityRows");
    expect(diagnosticsPanelSource).toContain("CompactList");
    expect(diagnosticsPanelSource).toContain("guardianTable");
    expect(diagnosticsPanelSource).toContain("diagnosticsPanel");
    expect(diagnosticsPanelSource).toContain("diagnosticsBody");
    expect(diagnosticsPanelSource).toContain("diagnosticSection");
    expect(routeSource).toContain("LauncherStartupSettingsPanel");
    expect(startupSettingsPanelSource).toContain("settingsStrip");
    expect(startupSettingsPanelSource).toContain("settingsTitle");
    expect(startupSettingsPanelSource).toContain("settingsWindow");
    expect(startupSettingsPanelSource).toContain("settingField");
    expect(startupSettingsPanelSource).toContain("settingToggle");
    expect(startupSettingsPanelSource).toContain("settingsSaveButton");
    expect(startupSettingsPanelSource).toContain("<VTabs");
    expect(startupSettingsPanelSource).toContain("windowModeTabs");
    expect(startupSettingsPanelSource).not.toContain("segmentedControl");
    expect(routeSource).toContain("LauncherDeveloperModePanel");
    expect(developerModePanelSource).toContain("developerPanel");
    expect(routeSource).toContain("cleanupPlan");
    expect(routeSource).toContain("guardian?.supervisor?.stdoutPath");
    expect(routeSource).toContain("guardian?.supervisor?.stderrPath");
    expect(routeSource).not.toContain("hero");
    expect(routeSource).not.toContain("cardGrid");
    expect(styles.advancedFold).toBeTypeOf("string");
    expect(processMonitorPanelStyles.statusTable).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.settingsStrip).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.settingsPrimary).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.settingsSecondary).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.settingsTitle).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.settingsWindow).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.settingField).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.settingToggle).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.settingsSaveButton).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.settingError).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.windowModeTabsList).toBeTypeOf("string");
    expect(startupSettingsPanelStyles.windowModeTabsTrigger).toContain("data-[state=active]");
    expect(developerModePanelStyles.developerPanel).toBeTypeOf("string");
    expect(developerModePanelStyles.developerGrid).toBeTypeOf("string");
    expect(developerModePanelStyles.cleanupConsole).toBeTypeOf("string");
    expect(developerModePanelStyles.cleanupPlan).toBeTypeOf("string");
    expect(projectMaintenancePanelStyles.developerPanel).toBeTypeOf("string");
    expect(styles.guardStrip).toBeTypeOf("string");
    expect(styles.statusTable).toBeTypeOf("string");
    expect(styles.matrixPanel).toBeTypeOf("string");
    expect(diagnosticsPanelStyles.guardianTable).toBeTypeOf("string");
    expect(diagnosticsPanelStyles.diagnosticsPanel).toBeTypeOf("string");
    expect(diagnosticsPanelStyles.diagnosticsBody).toBeTypeOf("string");
    expect(diagnosticsPanelStyles.diagnosticSection).toBeTypeOf("string");
    expect(diagnosticsPanelStyles.recoveryLine).toBeTypeOf("string");
    expect(diagnosticsPanelStyles.specGrid).toBeTypeOf("string");
  });

  it("puts process monitor and startup settings before collapsed advanced tools", () => {
    const branchIndex = routeSource.indexOf("<LauncherBranchInstancesPanel");
    const processIndex = routeSource.indexOf("<LauncherProcessMonitorPanel");
    const settingsIndex = routeSource.indexOf("<LauncherStartupSettingsPanel");
    const advancedIndex = routeSource.indexOf("className={styles.advancedFold}");
    const maintenanceIndex = routeSource.indexOf("<LauncherProjectMaintenancePanel");
    const developerIndex = routeSource.indexOf("<LauncherDeveloperModePanel");
    const diagnosticsIndex = routeSource.indexOf("<LauncherDiagnosticsPanel");
    expect(branchIndex).toBeGreaterThan(0);
    expect(settingsIndex).toBeGreaterThan(branchIndex);
    expect(advancedIndex).toBeGreaterThan(settingsIndex);
    expect(processIndex).toBeGreaterThan(advancedIndex);
    expect(maintenanceIndex).toBeGreaterThan(advancedIndex);
    expect(developerIndex).toBeGreaterThan(maintenanceIndex);
    expect(diagnosticsIndex).toBeGreaterThan(developerIndex);
    expect(routeSource).not.toContain("toolbarSlot");
    expect(routeSource).not.toContain("<details open");
    expect(routeSource).toContain("residualProcesses");
    expect(startupSettingsPanelSource).toContain("settingsPrimary");
    expect(startupSettingsPanelSource).toContain("effectiveValue");
    expect(developerModePanelStyles.dangerButton).toBeTypeOf("string");
    expect(launcherPanelStylesSource).toContain("settingsStrip");
    expect(launcherPanelStylesSource).toContain("developerPanel");
    expect(launcherPanelStylesSource).toContain("diagnosticsPanel");
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
    expect(processMonitorPanelSource).toContain("<VTooltip key={row.id} content={row.technical} width=\"wide\">");
    expect(processMonitorPanelSource).toContain("<span role=\"columnheader\">{copy.pid}</span>");
    expect(processMonitorPanelSource).toContain("<span role=\"columnheader\">{copy.port}</span>");
    expect(processMonitorPanelSource).toContain("<span role=\"columnheader\">{copy.ownership}</span>");
    expect(routeSource).not.toContain("部分接管");
    expect(routeSource).not.toContain("Partially owned");
    expect(routeSource).not.toContain("helper={`${copy.queue}:");
    expect(styles.metric).toBeTypeOf("string");
  });

  it("summarizes raw lifecycle errors before they reach the first-read Launcher UI", () => {
    expect(routeSource).toContain("function summarizeLauncherMessage");
    expect(routeSource).toContain("workbench is not ready");
    expect(routeSource).toContain("backendportlistening=false");
    expect(routeSource).toContain("backendPortUnavailableSummary");
    expect(routeSource).toContain("technicalDetailAvailable");
    expect(routeSource).toContain("noticeTextShort");
    expect(routeSource).not.toContain("lifecycleDetailShort");
    expect(routeSource).not.toContain("selectedAlive ? copy.lifecycleRunningDetail : copy.lifecycleClosedDetail");
    expect(routeSource).not.toContain("meta={selectedIsCurrent");
    expect(routeSource).toContain("VDenseOpsPage");
    expect(routeSource).toContain('data-vui-domain-recipe="launcher-workbench"');
    expect(routeSource).toContain("<VTooltip content={notice.text}");
    expect(processMonitorPanelSource).toContain("<VTooltip key={row.id} content={row.technical} width=\"wide\">");
    expect(routeSource).not.toContain("<p className={styles.subtitle}>{lifecycleDisplay.detail || copy.subtitle}</p>");
    expect(routeSource).not.toContain("<small>{userGuideDetail}</small>");
    expect(routeSource).not.toContain("{notice.text !== noticeTextShort ? <span>{copy.technicalDetailAvailable}</span> : null}");
  });

  it("keeps guidance terse while preserving detail in the shared hover surface", () => {
    expect(routeSource).toContain("<VTooltip content={notice.text}");
    expect(routeSource).not.toContain("<VTooltip content={statusBarBlockerReason}");
    expect(routeSource).not.toContain("className={styles.statusBarReason} data-tone={userGuideTone} tabIndex={0}");
    expect(routeSource).not.toContain('title={userGuideDetail}');
    expect(routeStylesSource).toContain("userGuide:");
    expect(routeStylesSource).toContain("overflow-wrap-anywhere");
    expect(routeStylesSource).toContain("whitespace-normal");
    expect(routeStylesSource).toContain("col-auto");
  });

  it("uses a light dense Launcher surface with muted action buttons", () => {
    expect(routeStylesSource).toContain("const panelSurface");
    expect(routeStylesSource).toContain("const rowSurface");
    expect(routeStylesSource).toContain("const mutedControl");
    expect(routeStylesSource).toContain("const primaryControl");
    expect(routeStylesSource).toContain("const dangerControl");
    expect(routeStylesSource).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(routeStylesSource).toContain("var(--vui-surface-row)");
    expect(routeStylesSource).toContain("bg-vui-control-muted");
    expect(routeStylesSource).toContain("var(--vui-control-muted)");
    expect(launcherPanelStylesSource).toContain("const panelSurface");
    expect(launcherPanelStylesSource).toContain("const primaryControl");
    expect(routeStylesSource).toContain("min-h-7");
    expect(routeStylesSource).toContain("px-2");
    expect(routeStylesSource).toContain("w-fit");
    expect(routeStylesSource).toContain("whitespace-nowrap");
    expect(launcherShellStylesSource).toContain("var(--vui-gradient-route-soft)");
    expect(launcherShellStylesSource).toContain("var(--fg-primary)");
  });

  it("keeps the Launcher route root and header background-aware", () => {
    expect(styles.route).not.toContain("bg-[var(--surface-page)]");
    expect(styles.route).not.toMatch(/bg-\[|!bg-\[|var\(--vui-surface/);
    expect(styles.header).not.toMatch(/bg-\[|!bg-\[|var\(--vui-surface/);
    expect(styles.header).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(styles.header).toContain("!bg-transparent");
    expect(styles.header).toContain("!shadow-none");
    expect(styles.header).toContain("!backdrop-blur-none");
    expect(styles.panel).not.toContain("bg-[var(--surface-panel)]");
    expect(styles.panel).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
  });

  it("keeps the complete launcher surface reachable when the window is short", () => {
    expect(routeSource).toContain("bodyClassName={styles.routeBody}");
    expect(routeSource).toContain("useLayoutEffect(() => pinLauncherDocumentViewport(document), [])");
    expect(routeSource).toContain("fill");
    expect(routeStylesSource).toContain("routeBody:");
    expect(routeStylesSource).toContain("overflow-y-auto");
    expect(routeStylesSource).toContain("overflow-x-clip");
    expect(routeStylesSource).toContain("overscroll-contain");
    expect(routeStylesSource).toContain("[scrollbar-gutter:stable]");
    expect(routeStylesSource).toContain("pb-[max(12px,env(safe-area-inset-bottom))]");
    expect(routeStylesSource).toContain("pb-[max(14px,env(safe-area-inset-bottom))]");
    expect(routeStylesSource).toContain("overflow-visible");
    expect(routeStylesSource).not.toContain("grid-rows-[auto_auto_auto_auto_auto_minmax(0,1fr)]");
  });

  it("keeps Launcher strips and actions from overflowing narrow windows", () => {
    expect(styles.dangerZone).toContain("max-[860px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.workspace).toContain("grid-cols-[minmax(0,1fr)]");
    expect(styles.statusBarReason).toContain("max-[860px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.dangerActions).toContain("min-w-0");
    expect(styles.primaryButton).toContain("max-w-full");
    expect(styles.statusBarButton).toContain("max-w-full");
    expect(styles.iconButton).toContain("max-w-full");
  });

  it("keeps Launcher panels compact with content-sized controls and internal scroll", () => {
    expect(styles.route).toContain("max-w-full");
    expect(routeStylesSource).toContain("[&_[data-vui=button]]:w-fit");
    expect(routeStylesSource).toContain("[&_[data-vui=button]]:[max-width:100%]");
    expect(routeStylesSource).toContain("[&_[data-vui=button]]:[white-space:nowrap]");

    expect(styles.workspace).toContain("grid-cols-[minmax(0,1fr)]");
    expect(styles.advancedFold).toContain("overflow-hidden");
    expect(routeSource).not.toContain("PaneResizeHandle");
    expect(styles.statusBar).toContain("w-full");
    expect(styles.statusBar).toContain("max-w-none");
    expect(styles.statusBar).not.toContain("w-[min(760px,58vw)]");
    expect(styles.panel).toContain("overflow-hidden");
    expect(styles.panelHeader).toContain("min-h-0");

    expect(startupSettingsPanelStyles.settingsStrip).toContain("mx-2");
    expect(startupSettingsPanelStyles.settingsStrip).toContain("overflow-hidden");
    expect(startupSettingsPanelStyles.settingsPrimary).toContain("grid-cols-");
    expect(startupSettingsPanelStyles.settingsSaveButton).toContain("justify-self-end");
    expect(startupSettingsPanelStyles.settingsStrip).not.toContain("mx-3");

    for (const panelStyles of [developerModePanelStyles, projectMaintenancePanelStyles]) {
      expect(panelStyles.developerPanel).toContain("mx-2");
      expect(panelStyles.developerPanel).toContain("overflow-hidden");
      expect(panelStyles.developerGrid).toContain("min-h-0");
      expect(panelStyles.developerNoise).toContain("overflow-hidden");
      expect(panelStyles.noiseItemGrid).toContain("overflow-auto");
      expect(panelStyles.noiseItemGrid).not.toContain("max-h-[150px]");
      expect(panelStyles.cleanupConsole).toContain("overflow-auto");
      expect(panelStyles.developerPanel).not.toContain("mx-3");
    }

    expect(developerModePanelStyles.cleanupActions).toContain("justify-start");
    expect(developerModePanelStyles.cleanupActions).not.toContain("max-[620px]:grid");

    expect(diagnosticsPanelStyles.diagnosticsPanel).toContain("overflow-hidden");
    // Wave 6C: diagnostics body height is shared PaneHeight, not a fixed max-h cap.
    expect(diagnosticsPanelStyles.diagnosticsBody).not.toContain("max-h-[min(42vh,420px)]");
    expect(diagnosticsPanelStyles.diagnosticsBody).toContain("overflow-auto");
    expect(diagnosticsPanelSource).toContain("usePersistedPaneHeight");
    expect(diagnosticsPanelSource).toContain("PaneHeightResizeHandle");
    expect(diagnosticsPanelSource).toContain("diagnostics-body");
    expect(diagnosticsPanelStyles.diagnosticsBodyResizeHandle).not.toContain("cursor-row-resize");
    // Wave 6F: guardian table + cleanup consoles use PersistedHeightListShell.
    expect(diagnosticsPanelStyles.guardianTable).not.toContain("max-h-[220px]");
    expect(diagnosticsPanelSource).toContain("PersistedHeightListShell");
    expect(diagnosticsPanelSource).toContain("LAUNCHER_GUARDIAN_TABLE_HEIGHT_PANE");
    expect(developerModePanelStyles.cleanupConsole).not.toContain("max-h-[220px]");
    expect(developerModePanelSource).toContain("PersistedHeightListShell");
    expect(developerModePanelSource).toContain("LAUNCHER_CLEANUP_CONSOLE_HEIGHT_PANE");
    expect(projectMaintenancePanelStyles.cleanupConsole).not.toContain("max-h-[220px]");
    expect(projectMaintenancePanelSource).toContain("PersistedHeightListShell");
    expect(diagnosticsPanelStyles.guardianTable).toContain("overflow-auto");
    // Wave 6G: noise overview grids use PersistedHeightListShell.
    expect(developerModePanelSource).toContain("LAUNCHER_NOISE_ITEM_GRID_HEIGHT_PANE");
    expect(projectMaintenancePanelSource).toContain("LAUNCHER_NOISE_ITEM_GRID_HEIGHT_PANE");
  });

  it("keeps internal lifecycle fields out of the first-read labels", () => {
    expect(routeSource).toContain('matrix: "进程监控"');
    expect(routeSource).toContain('keyStatus: "托管进程"');
    expect(routeSource).toContain('processMonitor: "进程监控"');
    expect(routeSource).toContain('advancedFold: "高级"');
    expect(routeSource).toContain('controlPlane: "维护范围"');
    expect(routeSource).toContain('guardian: "托管明细"');
    expect(routeSource).toContain('advancedDiagnostics: "高级诊断"');
    expect(routeSource).toContain('userGuide: "当前建议"');
    expect(routeSource).toContain('userGuideReady: "可以继续使用"');
    expect(routeSource).toContain('userGuideBlocked: "先等任务完成"');
    expect(routeSource).toContain('actionsLocked: "停止/重启已保护"');
    expect(routeSource).toContain('diagnosticsCollapsedHint: "排查时展开"');
    expect(routeSource).toContain("托管进程与残留子进程");
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
    expect(routeSource).toContain("LauncherDiagnosticsPanel");
    expect(routeSource).toContain("className={styles.advancedFold}");
    expect(diagnosticsPanelSource).toContain("<details className={`${styles.panel} ${styles.diagnosticsPanel}`}>");
    expect(diagnosticsPanelSource).not.toContain("<details open");
    expect(routeSource).toContain("queueAndEvents");
    expect(routeSource).toContain("diagnosticsCollapsedHint");
    expect(routeSource).toContain("recoveryIdle");
    expect(routeSource).toContain("recovery.statusLine");
    expect(routeSource).toContain("maintenanceDetails");
    expect(routeSource).toContain("recentResults.map");
    expect(routeSource).toContain("guardian?.responsibilities");
    expect(diagnosticsPanelSource).toContain("diagnosticsGrid");
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
    expect(routeSource).toContain('postLauncherLifecycleControlTelemetry(request.operation, "request_failed"');
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
    expect(routeSource).toContain("{ label: copy.requestTrigger, value: lastRequestTrigger }");
    expect(routeSource).toContain("{ label: copy.requestEndpoint, value: lastRequestEndpoint }");
    expect(diagnosticsPanelSource).toContain("<Spec key={item.label} {...item} />");
  });

  it("keeps lifecycle actions icon-backed and compact", () => {
    expect(routeSource).not.toContain("<Play size={15} />");
    expect(routeSource).not.toContain("<RefreshCw size={15} />");
    expect(routeSource).not.toContain("<ExternalLink size={15} />");
    expect(routeSource).not.toContain("VWorkbenchPowerMenu");
    expect(routeSource).not.toContain("<Square size={15} />");
    expect(startupSettingsPanelSource).toContain("<Maximize2 size={14}");
    expect(startupSettingsPanelSource).toContain("<Minimize2 size={14}");
    expect(routeSource).not.toContain('controlMutation.mutate("start")');
    expect(routeSource).not.toContain('controlMutation.mutate("stop")');
    expect(routeSource).not.toContain('controlMutation.mutate("force-stop")');
    expect(routeSource).not.toContain('controlMutation.mutate("restart")');
    expect(routeSource).toContain("controlMutation.mutate({");
    expect(routeSource).toContain("requestId: accepted.intent.requestId");
    expect(routeSource).toContain("localRevision: accepted.intent.localRevision");
    expect(startupSettingsPanelSource).toContain('id: "fullscreen"');
    expect(startupSettingsPanelSource).toContain('id: "windowed"');
    expect(startupSettingsPanelSource).toContain("saveWindowMode({ windowMode: value })");
    expect(routeSource).toContain("supervisorMutation.mutate()");
  });

  it("keeps project power off the Launcher page and puts branch instances first", () => {
    expect(styles.statusBar).toBeTypeOf("string");
    expect(styles.statusBarReason).toBeTypeOf("string");
    expect(styles.statusBarActions).toBeTypeOf("string");
    expect(styles.statusBarButton).toBeTypeOf("string");
    expect(styles.dangerActions).toBeTypeOf("string");

    expect(routeSource).not.toContain("statusBarActions");
    expect(routeSource).not.toContain("VWorkbenchPowerMenu");
    expect(routeSource).not.toContain("statusQuery.refetch()");
    expect(routeSource).not.toContain('controlMutation.mutate("start")');
    expect(routeSource).not.toContain("copy.powerMenu");
    expect(routeSource).not.toContain("styles.dangerZone");
    expect(routeSource).not.toContain("styles.dangerActions");
    expect(routeSource).toContain("forceStopHint:");
    expect(routeSource).not.toContain("showForceStop");

    const pageStart = routeSource.indexOf("<VDenseOpsPage");
    const branchIndex = routeSource.indexOf("<LauncherBranchInstancesPanel", pageStart);
    const settingsIndex = routeSource.indexOf("<LauncherStartupSettingsPanel", branchIndex);
    expect(pageStart).toBeGreaterThanOrEqual(0);
    expect(branchIndex).toBeGreaterThan(pageStart);
    expect(settingsIndex).toBeGreaterThan(branchIndex);
    expect(routeSource.slice(pageStart, branchIndex)).not.toContain("actions=");
    expect(routeSource.slice(pageStart, branchIndex)).toContain("hideHeader");
    expect(routeSource.slice(pageStart, branchIndex)).not.toContain("eyebrow={copy.eyebrow}");
    expect(routeSource.slice(pageStart, branchIndex)).not.toContain("title={copy.title}");
  });

  it("shows registry reconciliation evidence without adding a force-kill control", () => {
    expect(routeSource).toContain("Registry 判定");
    expect(routeSource).toContain("端口冲突");
    expect(routeSource).toContain("最近自动清理");
    expect(routeSource).toContain("Worktree dry-run");
    expect(routeSource).toContain("Orphan 判据");
    expect(routeSource).toContain("worktree 仅 dry-run");
    expect(routeSource).not.toContain("taskkill");
  });

  it("lets Launcher own startup settings without restarting immediately", () => {
    expect(routeSource).toContain("LauncherStartupSettingsPanel");
    expect(startupSettingsPanelSource).toContain("export function LauncherStartupSettingsPanel");
    expect(routeSource).toContain("startupSettingsMutation");
    expect(routeSource).toContain("mutationFn: updateLauncherStartupSettings");
    expect(startupSettingsPanelSource).toContain("WorkbenchWindowModeUpdateRequest");
    expect(routeSource).toContain("settings?.startup");
    expect(launcherApiSource).toContain("baseHash: setting.configHash");
    expect(launcherApiSource).toContain("WorkbenchWindowModeUpdateRequest");
    expect(startupSettingsPanelSource).toContain("onWindowModeChange({ mode, baseHash: current.configHash })");
    expect(routeSource).toContain("const workbenchWindowSaveMutation = useMutation({");
    expect(routeSource).toContain('source: "window-mode"');
    expect(routeSource).toContain("queryKeys.launcherStatus()");
    expect(startupSettingsPanelSource).toContain("configHash");
    expect(startupSettingsPanelSource).toContain("runtimeProfile");
    expect(startupSettingsPanelSource).toContain("launcherControlPort");
    expect(startupSettingsPanelSource).toContain("launcherControlPortHint");
    expect(startupSettingsPanelSource).toContain("backendPortHint");
    expect(startupSettingsPanelSource).toContain("frontendPortHint");
    expect(startupSettingsPanelSource).toContain("settingsWindow");
    expect(startupSettingsPanelSource).toContain("settingsTitle");
    expect(startupSettingsPanelSource).toContain("backendPort");
    expect(startupSettingsPanelSource).toContain("frontendPort");
    expect(routeSource).toContain("Launcher 端口");
    expect(routeSource).toContain("默认后端");
    expect(routeSource).toContain("开发前端");
    expect(branchInstancesPanelSource).toContain('backend: "后端"');
    expect(branchInstancesPanelSource).not.toContain("实例端口");
    expect(startupSettingsPanelSource).toContain("windowSize");
    expect(startupSettingsPanelSource).toContain("windowSizeOptions");
    expect(startupSettingsPanelSource).toContain("interfaceLanguage");
    expect(startupSettingsPanelSource).toContain("preflightDoctor");
    expect(startupSettingsPanelSource).toContain("requireVenv");
    expect(startupSettingsPanelSource).toContain("parsePortDraft");
    expect(startupSettingsPanelSource).toContain("setValidationError(copy.invalidPort)");
    expect(startupSettingsPanelSource).toContain('role="alert"');
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

  it("collapses startup settings into an accessible summary that expands to the unchanged form", () => {
    expect(startupSettingsPanelSource).toContain("<details");
    expect(startupSettingsPanelSource).toContain("<summary");
    expect(startupSettingsPanelSource).not.toContain("<details open");
    expect(startupSettingsPanelSource).toContain("onToggle={(event) => setSettingsOpen(event.currentTarget.open)}");
    expect(startupSettingsPanelSource).toContain("expandSettings");
    expect(startupSettingsPanelSource).toContain("collapseSettings");
    // The concise summary is built from current profile, ports, and effective window mode.
    expect(startupSettingsPanelSource).toContain("runtimeProfileLabel(current.runtime.profile, uiLang)");
    expect(startupSettingsPanelSource).toContain("effectiveWindowModeLabel");
    expect(startupSettingsPanelSource).toContain("effectiveControlPort || current.launcher.controlPort");
    expect(startupSettingsPanelSource).toContain("effectiveBackendPort || current.workbench.backendPort");
    expect(startupSettingsPanelSource).toContain("effectiveFrontendPort || current.workbench.frontendPort");
    // The editable form stays inside the fold body with save/validation/window-mode semantics intact.
    expect(startupSettingsPanelSource).toContain("settingsBody");
    expect(startupSettingsPanelSource).toContain("saveDraft");
    expect(startupSettingsPanelSource).toContain("setValidationError(copy.invalidPort)");
    expect(startupSettingsPanelSource).toContain("saveWindowMode({ windowMode: value })");
    expect(startupSettingsPanelSource).toContain("controlsDisabled");
    // The collapsed summary title must stay on one line in the compact top strip.
    expect(startupSettingsPanelStyles.settingsTitle).toContain("shrink-0");
    expect(startupSettingsPanelStyles.settingsTitle).toContain("whitespace-nowrap");
  });

  it("keeps branch management and startup settings stacked without an empty side rail", () => {
    expect(routeSource).toContain("styles.primaryRail");
    expect(routeSource).toContain("styles.primaryColumn");
    expect(routeSource).toContain("styles.settingsRail");
    expect(routeSource).toContain('data-vui-region="launcher-primary-rail"');
    expect(routeSource).toContain('data-vui-region="launcher-primary"');
    expect(routeSource).toContain('data-vui-region="launcher-settings-rail"');
    // Both the branch panel and the settings Suspense/panel live inside the rail container.
    const railStart = routeSource.indexOf("className={styles.primaryRail}");
    const statusErrorIndex = routeSource.indexOf("{statusQuery.isError && !launcherControlPlaneStarting ? (");
    expect(railStart).toBeGreaterThan(0);
    expect(statusErrorIndex).toBeGreaterThan(railStart);
    expect(routeSource.slice(railStart, statusErrorIndex)).toContain("<LauncherBranchInstancesPanel");
    expect(routeSource.slice(railStart, statusErrorIndex)).toContain("<LauncherStartupSettingsPanel");
    // Status notices and advanced maintenance/diagnostics stay below the primary layout.
    const settingsIndex = routeSource.indexOf("<LauncherStartupSettingsPanel");
    const workspaceIndex = routeSource.indexOf("className={styles.workspace}");
    const advancedIndex = routeSource.indexOf("className={styles.advancedFold}");
    expect(settingsIndex).toBeGreaterThan(routeSource.indexOf("<LauncherBranchInstancesPanel"));
    expect(statusErrorIndex).toBeGreaterThan(settingsIndex);
    expect(workspaceIndex).toBeGreaterThan(statusErrorIndex);
    expect(advancedIndex).toBeGreaterThan(workspaceIndex);
    // Collapsed settings sit in an auto-height top strip; the branch table fills the rest.
    // Expanding the form grows that strip full-width instead of reserving an empty side column.
    expect(styles.primaryRail).toContain("grid-cols-1");
    expect(styles.primaryRail).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(styles.primaryRail).not.toContain("minmax(250px,");
    expect(styles.primaryRail).toContain("flex-1");
    expect(styles.primaryColumn).toContain("min-w-0");
    expect(styles.primaryColumn).toContain("flex-col");
    expect(styles.primaryColumn).toContain("row-start-2");
    expect(styles.settingsRail).toContain("min-w-0");
    expect(styles.settingsRail).toContain("row-start-1");
    expect(styles.settingsRail).not.toContain("col-span-full");
    expect(startupSettingsPanelStyles.settingsStrip).not.toContain("self-start");
    expect(startupSettingsPanelStyles.settingsStrip).toContain("w-full");
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
    expect(developerModePanelSource).toContain("developerModeStateLabel");
    expect(developerModePanelSource).toContain("developerModeCurrentState}: ${developerModeStateLabel}");
    expect(developerModePanelSource).toContain("copy.developerModeSettingsReadonly");
    expect(routeSource).toContain("设置页只读展示，不能在工作台设置里改动");
    expect(launcherApiSource).toContain("developer-mode/cleanup/preview");
    expect(launcherApiSource).toContain("developer-mode/cleanup/apply");
  });

  it("makes Launcher the owner of project reset and initialization maintenance", () => {
    expect(routeSource).toContain("LauncherProjectMaintenancePanel");
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
    expect(projectMaintenancePanelSource).toContain("maintenance/reset/summary");
    expect(projectMaintenancePanelSource).toContain("maintenance/reset/preview");
    expect(projectMaintenancePanelSource).toContain("maintenance/reset/apply");
    expect(projectMaintenancePanelSource).toContain("Launcher 维护中心");
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
    expect(routeSource).toContain('statusQuery.isError && !launcherControlPlaneStarting && (lastControlOperation === "stop" || lastControlOperation === "force-stop" || launcherStatusDisconnected)');
    expect(routeSource).toContain("expectedStopDisconnect ? copy.stoppedStatusUnavailable");
    expect(routeSource).toContain('tone={expectedStopDisconnect ? "info" : launcherControlLimited ? "unavailable" : "error"}');
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
    expect(routeSource).toContain("useStableBeforeUnload");
    expect(routeSource).toContain("launcherCloseGuardRef");
    // Must not re-bind beforeunload when status / armed flags poll-change.
    expect(routeSource).not.toMatch(
      /addEventListener\("beforeunload"[\s\S]*?\}, \[launcherCloseGuardArmed/,
    );
  });

  it("gates the control window on IPC host readiness instead of painting a disconnected empty dashboard", () => {
    expect(routeSource).toContain("isLauncherControlPlaneNotReady");
    expect(routeSource).toContain("launcherControlPlaneStarting");
    expect(routeSource).toContain("!launcherControlPlaneStarting");
    expect(routeSource).toContain("launcherStatusDisconnected = statusQuery.isError");
    // Not-ready must not be classified as a network disconnect idle surface.
    expect(routeSource).not.toMatch(/launcherStatusDisconnected = statusQuery\.isError && isLauncherStatusNetworkDisconnect\(statusQuery\.error\);\s*\n/);
    // Start stays disabled while the control plane host is still starting.
    expect(sourceSlice(routeSource, "const startDisabled =", "const startDisabledReason =")).toContain(
      "launcherControlPlaneStarting",
    );
    expect(sourceSlice(routeSource, "const startDisabledReason =", "const projectSummary =")).toContain(
      "launcherControlPlaneStarting",
    );
    // The first-read surface shows a starting state instead of 未连接 with an empty dashboard.
    expect(sourceSlice(routeSource, "const launcherSummary =", "const controlSummary =")).toContain(
      "launcherControlPlaneStarting || statusQuery.isPending ? copy.launcherMaintaining : copy.launcherOffline",
    );
    expect(sourceSlice(routeSource, "{statusQuery.isError && !launcherControlPlaneStarting ? (", "launcherControlPlaneStarting ? (")).toContain(
      "copy.loadFailed",
    );
    expect(routeSource).toContain("launcherControlPlaneStarting ? (");
    expect(routeSource).toContain('title={copy.lifecycleStarting}');
    expect(routeSource).toContain("launcherReading={Boolean(");
    expect(routeSource).toContain("listLoading={Boolean(");
    expect(routeSource).toContain("branchInstancesQuery.isPending || (branchInstancesQuery.isFetching && !branchInstancesQuery.data)");
    // The lifecycle display must expose a dedicated starting state while the host is not ready.
    expect(routeSource).toContain("starting: launcherControlPlaneStarting");
  });
});
