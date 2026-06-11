import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import styles from "./AppShell.module.css";
import indexHtml from "../../index.html?raw";
import manifestSource from "../../public/manifest.webmanifest?raw";
import shellSource from "./AppShell.tsx?raw";
import launcherShellSource from "./LauncherShell.tsx?raw";
import documentLanguageSource from "./documentLanguage.ts?raw";
import useShellI18nSource from "../i18n/useShellI18n.ts?raw";
import utilityMenuSource from "./AppShellUtilityMenu.tsx?raw";
import statusGuideSource from "./AppShellStatusGuidePanel.tsx?raw";

const shellStyles = readFileSync(fileURLToPath(new URL("./AppShell.module.css", import.meta.url)), "utf8");

describe("AppShell layout contract", () => {
  it("renders one compact status summary chip while keeping the detailed guide panel", () => {
    expect(shellSource).toContain("statusSummaryChip");
    expect(shellSource).toContain("LazyAppShellStatusGuidePanel");
    expect(shellSource).toContain("statusGuideOpen ? (");
    expect(shellSource).not.toContain("statusGuidePanel");
    expect(statusGuideSource).toContain("statusGuidePanel");
    expect(statusGuideSource).toContain("lifecycleProofCard");
    expect(statusGuideSource).toContain("lifecycleStateLabel");
    expect(statusGuideSource).toContain("systemFrontendPossible_connected");
    expect(shellSource).not.toContain("rightStatusCards.map((item) => (\n                <span key={item.id} className={styles.statusBadge}>");
  });

  it("keeps the global shell top bar compact", () => {
    expect(styles.statusSummaryChip).toBeTypeOf("string");
    expect(styles.statusSummaryCount).toBeTypeOf("string");
    expect(shellStyles).toContain("flex-wrap: nowrap");
    expect(shellStyles).toContain("@media (max-width: 1180px)");
    expect(shellStyles).toContain(".topClock span:last-child");
    expect(shellStyles).toContain("@media (max-width: 980px)");
    expect(shellStyles).toContain("overscroll-behavior-x: contain");
  });

  it("keeps the global shell background in the layered starfield treatment", () => {
    expect(shellStyles).toContain("--shell-star-color");
    expect(shellStyles).toContain("--shell-star-faint");
    expect(shellStyles).toContain("--shell-nebula-cool");
    expect(shellStyles).toContain(".shell::before");
    expect(shellStyles).toContain(".shell::after");
    expect(shellStyles).toContain("radial-gradient(circle at 8% 18%");
  });

  it("shows the current app version in the brand area", () => {
    expect(shellSource).toContain("APP_VERSION");
    expect(shellSource).toContain("packageJson.version");
    expect(shellSource).toContain("versionPill");
    expect(styles.versionPill).toBeTypeOf("string");
  });

  it("uses the lightweight shell dictionary instead of the full route dictionary", () => {
    expect(shellSource).toContain("useShellI18n");
    expect(shellSource).not.toContain("useAppI18n");
    expect(shellSource).not.toContain("../i18n/dictionary");
    expect(shellSource).not.toContain("../i18n/useAppI18n");
    expect(launcherShellSource).toContain("useShellI18n");
    expect(launcherShellSource).not.toContain("useAppI18n");
    expect(launcherShellSource).not.toContain("../i18n/dictionary");
    expect(launcherShellSource).not.toContain("../i18n/useAppI18n");
    expect(documentLanguageSource).toContain("../i18n/shellDictionary");
    expect(documentLanguageSource).not.toContain("../i18n/dictionary");
    expect(useShellI18nSource).toContain("shellDictionary");
    expect(useShellI18nSource).not.toContain("./dictionary");
  });

  it("exposes Teams from the primary navigation", () => {
    expect(shellSource).toContain('to="/teams"');
    expect(shellSource).toContain('t("navTeams")');
  });

  it("exposes the Memory Library from the primary navigation", () => {
    expect(shellSource).toContain('to="/memory"');
    expect(shellSource).toContain('t("navMemory")');
  });

  it("collapses logs git and files behind one hover utility menu", () => {
    const primaryNav = shellSource.slice(
      shellSource.indexOf("<nav className={styles.nav}>"),
      shellSource.indexOf("</nav>"),
    );

    expect(primaryNav).not.toContain('to="/logs"');
    expect(primaryNav).not.toContain('to="/tools"');
    expect(primaryNav).not.toContain('to="/agents/tools"');
    expect(primaryNav).not.toContain('to="/git"');
    expect(shellSource).toContain("utilityCluster");
    expect(shellSource).toContain("utilityClusterOpen");
    expect(shellSource).toContain("aria-expanded={utilityOpen}");
    expect(shellSource).toContain("LazyAppShellUtilityMenu");
    expect(shellSource).toContain("utilityOpen ? (");
    expect(shellSource).not.toContain("queryKeys.gitStatus()");
    expect(shellSource).not.toContain("queryKeys.fileTree()");
    expect(utilityMenuSource).toContain("utilityPanel");
    expect(utilityMenuSource).not.toContain("hidden={!utilityOpen}");
    expect(shellSource).toContain('event.key === "Escape"');
    expect(utilityMenuSource).toContain('to="/logs"');
    expect(shellSource).not.toContain('to="/agents/tools"');
    expect(shellSource).not.toContain('to="/tools"');
    expect(shellSource).toContain("Wrench");
    expect(utilityMenuSource).toContain('to="/git"');
    expect(utilityMenuSource).toContain('href="/launcher"');
    expect(utilityMenuSource).toContain('target="_blank"');
    expect(shellSource).toContain('data-browser-role="workbench"');
    expect(styles.utilityTrigger).toBeTypeOf("string");
    expect(styles.utilityPanel).toBeTypeOf("string");
    expect(styles.utilityClusterOpen).toBeTypeOf("string");
    expect(styles.utilityButtonGrid).toBeTypeOf("string");
  });

  it("keeps active work details out of the primary top bar chip", () => {
    expect(shellSource).toContain("activeWorkDetailPanel");
    expect(shellSource).toContain("activeWorkIndicator.items.map");
    expect(shellSource).not.toContain("className={styles.activeWorkSummary}");

    expect(styles.activeWorkDetailPanel).toBeTypeOf("string");
    expect(styles.activeWorkDetailItem).toBeTypeOf("string");
  });

  it("uses one shared page instance id and stops periodic memory sampling while hidden", () => {
    expect(shellSource).toContain("getPageInstanceId");
    expect(shellSource).toContain("useRef(getPageInstanceId())");
    expect(shellSource).toContain("if (!frontendVisible) {\n      return;\n    }");
    expect(shellSource).toContain("window.setInterval(() => emitMemorySample(\"periodic\"), BROWSER_MEMORY_SAMPLE_INTERVAL_MS)");
    expect(shellSource).toContain("frontendVisible, location.pathname, queryClient");
  });

  it("keeps startup data loading alive while the managed window is hidden", () => {
    expect(shellSource).toContain("const shellStartupWarmupActive = useStartupWarmup(shellStartupDataReady)");
    expect(shellSource).toContain("const shellPollingVisible = frontendVisible || shellStartupWarmupActive");
    expect(shellSource).toContain("resolvePollingInterval(\n    shellPollingVisible");
    expect(shellSource).toContain("refetchIntervalInBackground: shellStartupWarmupActive");
    expect(shellSource).toContain("if (configQuery.data && runtimeQuery.data && backendHealthQuery.data)");
    expect(shellSource).toContain("setShellStartupDataReady(true)");
    expect(shellSource).toContain("browser.startup_background_warmup.active");
    expect(shellSource).toContain("browser.startup_background_warmup.inactive");
    expect(shellSource).toContain("const startupWarmupTelemetryStateRef = useRef<\"active\" | \"inactive\" | null>(null)");
    expect(shellSource).toContain("if (startupWarmupTelemetryStateRef.current === warmupState)");
    expect(shellSource).toContain("telemetryReason: previousWarmupState === null ? \"initial\" : \"state_changed\"");
    expect(shellSource).toContain("startupDataReady: shellStartupDataReady");
  });

  it("treats locally completed shutdown as a settled state rather than a failed state", () => {
    expect(shellSource).toContain("shutdownSettled");
    expect(shellSource).toContain("aria-busy={!shutdownSettled}");
    expect(shellSource).toContain("shutdownLocallyCompleteTitle");
    expect(shellSource).not.toContain("shutdownFailed");
  });

  it("turns the top refresh icon into a frontend refresh and routes lifecycle actions through Launcher", () => {
    expect(shellSource).toContain("RefreshCw");
    expect(shellSource).toContain("refreshFrontendLabel");
    expect(shellSource).toContain("browser.user_action.frontend_refresh_requested");
    expect(shellSource).toContain("window.location.reload()");
    expect(shellSource).toContain("lifecycleMenuCluster");
    expect(shellSource).toContain("lifecycleMenuPanel");
    expect(shellSource).toContain("lifecycleMenuOpen");
    expect(shellSource).toContain("restartLauncherBundle");
    expect(shellSource).toContain("stopLauncherBundle");
    expect(shellSource).toContain("forceStopLauncherBundle");
    expect(shellSource).toContain("cancelRuntimeLifecycleCommand");
    expect(shellSource).not.toContain('"/api/runtime/restart"');
    expect(shellSource).not.toContain('"/api/runtime/shutdown"');
    expect(shellSource).toContain("restartWorkbenchLabel");
    expect(shellSource).toContain("forceCloseWorkbenchLabel");
    expect(shellSource).toContain("beginRestart");
    expect(shellSource).toContain("beginForceShutdown");
    expect(shellSource).toContain("restartActiveWorkBlockedMessage");
    expect(shellSource).toContain("shutdownActiveWorkBlockedMessage");
    expect(shellSource).not.toContain("confirmedActiveWork");
    expect(shellSource).toContain("restart_blocked_active_work");
    expect(shellSource).toContain("shutdown_blocked_active_work");
    expect(shellSource).toContain("browser.user_action.force_shutdown_requested");
    expect(shellSource).toContain("browser.user_action.force_shutdown_unconfirmed");
    expect(shellSource).toContain("requestWorkbenchExitGuard");
    expect(shellSource).toContain('requestWorkbenchExitGuard("restart"');
    expect(shellSource).toContain('requestWorkbenchExitGuard("shutdown"');
    expect(styles.lifecycleMenuCluster).toBeTypeOf("string");
    expect(styles.lifecycleMenuPanel).toBeTypeOf("string");
    expect(styles.lifecycleMenuItem).toBeTypeOf("string");
    expect(styles.lifecycleMenuDangerItem).toBeTypeOf("string");
  });

  it("lets lifecycle wait overlays be cancelled without stopping active work", () => {
    expect(shellSource).toContain("cancelLifecycleWait");
    expect(shellSource).toContain("cancelSupersededLifecycleCommand");
    expect(shellSource).toContain("lifecycleRequestSeqRef");
    expect(shellSource).toContain("lifecycleOverlayDismissedRef");
    expect(shellSource).toContain("setLifecycleAction(\"restart\")");
    expect(shellSource).toContain("setLifecycleAction(\"shutdown\")");
    expect(shellSource).toContain("cancelRestartLabel");
    expect(shellSource).toContain("cancelShutdownLabel");
    expect(shellSource).toContain("browser.user_action.lifecycle_wait_cancel_requested");
    expect(shellSource).toContain("browser.user_action.lifecycle_wait_cancel_completed");
    expect(shellSource).toContain("browser.user_action.lifecycle_wait_cancel_failed");
    expect(shellSource).toContain("browser.user_action.lifecycle_wait_cancel_superseded_command");
    expect(shellSource).toContain("cancelledBackendCommand");
    expect(shellSource).not.toContain("confirmedActiveWork");

    expect(styles.shutdownCancelButton).toBeTypeOf("string");
    expect(shellStyles).toContain(".shutdownCancelButton:hover:not(:disabled)");
    expect(shellStyles).toContain("white-space: pre-line");
  });

  it("renders a startup progress overlay from loading and lifecycle state", () => {
    expect(shellSource).toContain("deriveStartupLoadingState");
    expect(shellSource).toContain("deriveStartupProgressState");
    expect(shellSource).toContain("deriveStartupDisconnectedState");
    expect(shellSource).toContain("startupDisconnectedProgress");
    expect(shellSource).toContain("startupPanel.active");
    expect(shellSource).toContain("startupLoadingShouldBlock");
    expect(shellSource).toContain('startupLoadingProgress.tone === "failed"');
    expect(shellSource).toContain("runtimeQuery.isError || runtimeQuery.isRefetchError");
    expect(shellSource).toContain("backendHealthQuery.isError || backendHealthQuery.isRefetchError");
    expect(shellSource).toContain("startupOverlay");
    expect(shellSource).toContain("startupKicker");

    expect(styles.startupOverlay).toBeTypeOf("string");
    expect(styles.startupPanel).toBeTypeOf("string");
    expect(styles.startupKicker).toBeTypeOf("string");
  });

  it("keeps the global shell usable on narrow screens", () => {
    expect(styles.topClock).toBeTypeOf("string");
    expect(styles.utilityTriggerLabel).toBeTypeOf("string");
    expect(styles.statusBadgeLabel).toBeTypeOf("string");
  });

  it("themes the managed app window chrome to match the dark shell", () => {
    const manifest = JSON.parse(manifestSource);

    expect(indexHtml).toContain('name="theme-color" content="#12161a"');
    expect(indexHtml).toContain('name="color-scheme" content="dark"');
    expect(indexHtml).toContain('rel="manifest" href="/manifest.webmanifest"');
    expect(manifest.theme_color).toBe("#12161a");
    expect(manifest.background_color).toBe("#12161a");
    expect(manifest.display).toBe("standalone");
  });
});
