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
    expect(shellSource).toContain('t("brandSubtle")');
    expect(shellSource).not.toContain("<span className={styles.statusBadgeLabel}>Gate</span>");
    expect(shellSource).not.toContain("className={`${styles.statusCluster} ${styles.brandGate}`}");
    expect(shellSource).toContain("LazyAppShellStatusGuidePanel");
    expect(shellSource).toContain("statusGuideOpen ? (");
    expect(shellSource).not.toContain("statusGuidePanel");
    expect(statusGuideSource).toContain("statusGuidePanel");
    expect(statusGuideSource).toContain("lifecycleProofCard");
    expect(statusGuideSource).toContain("lifecycleStateLabel");
    expect(statusGuideSource).toContain("systemFrontendPossible_connected");
    expect(statusGuideSource).toContain('title={t("systemStatusGuideHint")}');
    expect(statusGuideSource).toContain("title={item.note}");
    expect(statusGuideSource).toContain("data-current={state.label === item.value ? \"true\" : undefined}");
    expect(statusGuideSource).toContain("title={state.detail}");
    expect(statusGuideSource).toContain("title={component.detail}");
    expect(statusGuideSource).not.toContain("statusGuideNote");
    expect(shellSource).not.toContain("rightStatusCards.map((item) => (\n                <span key={item.id} className={styles.statusBadge}>");
  });

  it("keeps the global shell top bar compact", () => {
    expect(styles.statusSummaryChip).toBeTypeOf("string");
    expect(styles.statusSummaryCount).toBeTypeOf("string");
    expect(styles.returnButton).toBeTypeOf("string");
    expect(styles.statusGuideGrid).toBeTypeOf("string");
    expect(styles.lifecycleProofMeta).toBeTypeOf("string");
    expect(styles.lifecycleProofList).toBeTypeOf("string");
    expect(shellStyles).toContain("width: min(640px, calc(100vw - 40px))");
    expect(shellStyles).toContain("grid-template-columns: repeat(3, minmax(0, 1fr))");
    expect(shellStyles).toContain(".statusGuideListItem[data-current=\"true\"]");
    expect(shellStyles).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
    expect(shellStyles).toContain("flex-wrap: nowrap");
    expect(shellStyles).toContain("@media (max-width: 1180px)");
    expect(shellStyles).toContain(".topClock span:last-child");
    expect(shellStyles).toContain("@media (max-width: 980px)");
    expect(shellStyles).toContain("overscroll-behavior-x: contain");
    expect(shellStyles).toContain(".returnButton");
    expect(shellStyles).toContain("width: 32px");
  });

  it("exposes a shell-level semantic return action without visible helper copy", () => {
    expect(shellSource).toContain("resolveReturnTarget(routeLocationFromRouter(location), returnNavigationStack)");
    expect(shellSource).toContain("consumeReturnNavigationTarget(current, targetPath)");
    expect(shellSource).toContain("suppressNextReturnStackPushRef.current = true");
    expect(shellSource).toContain("RETURN_NAVIGATION_STACK_STORAGE_KEY");
    expect(shellSource).toContain("className={styles.returnButton}");
    expect(shellSource).toContain("aria-label={returnNavigationLabel}");
    expect(shellSource).toContain("title={returnNavigationLabel}");
    expect(shellSource).toContain("<ArrowLeft size={16} />");
    expect(shellSource).not.toContain("returnNavigationHelper");
  });

  it("keeps the global shell background in the layered starfield treatment", () => {
    expect(shellStyles).toContain("--shell-star-color");
    expect(shellStyles).toContain("--shell-star-faint");
    expect(shellStyles).toContain("--shell-nebula-cool");
    expect(shellStyles).toContain(".shell::before");
    expect(shellStyles).toContain(".shell::after");
    expect(shellStyles).toContain("radial-gradient(circle at 8% 18%");
    expect(shellSource).toContain("configThemeBackgroundImageUrl(configQuery.data)");
    expect(shellSource).toContain("configThemeBackgroundReadability(");
    expect(shellSource).toContain('data-theme-background={themeBackgroundImageUrl ? "custom" : "default"}');
    expect(shellSource).toContain("data-theme-background-readability={themeBackgroundImageUrl ? themeBackgroundReadability : undefined}");
    expect(shellSource).toContain("--workbench-theme-background-image");
    expect(shellSource).toContain("/api/config/theme-background-image/");
    expect(shellSource).toContain("themeBackgroundReadability");
    expect(shellStyles).toContain('.shell[data-theme-background="custom"]');
    expect(shellStyles).toContain('[data-theme-background-readability="soft"]');
    expect(shellStyles).toContain('[data-theme-background-readability="standard"]');
    expect(shellStyles).toContain('[data-theme-background-readability="strong"]');
    expect(shellStyles).toContain("--theme-background-blur");
    expect(shellStyles).toContain("backdrop-filter: blur(var(--theme-background-blur))");
    expect(shellStyles).toContain("var(--workbench-theme-background-image)");
    expect(shellStyles).toContain("background-size: auto, cover, auto");
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
    expect(utilityMenuSource).toContain("requiresAttention");
    expect(utilityMenuSource).toContain("gitStatusLevel");
    expect(utilityMenuSource).toContain("gitSignalGrid");
    expect(utilityMenuSource.indexOf("className={styles.gitMiniPanel}")).toBeLessThan(utilityMenuSource.indexOf('id="utility-file-navigator"'));
    expect(utilityMenuSource).toContain("gitStatus.localCommits.commits");
    expect(utilityMenuSource).toContain("gitPendingWorktrees");
    expect(shellSource).toContain('data-browser-role="workbench"');
    expect(styles.utilityTrigger).toBeTypeOf("string");
    expect(styles.utilityPanel).toBeTypeOf("string");
    expect(styles.utilityClusterOpen).toBeTypeOf("string");
    expect(styles.utilityButtonGrid).toBeTypeOf("string");
    expect(styles.gitSignalGrid).toBeTypeOf("string");
    expect(styles.gitSectionHeader).toBeTypeOf("string");
    expect(styles.gitCommitList).toBeTypeOf("string");
    expect(styles.gitWorktreeList).toBeTypeOf("string");
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

  it("routes direct workbench window close attempts through controlled shutdown", () => {
    expect(shellSource).toContain("markControlledProjectLifecycleOperation(\"stop\")");
    expect(shellSource).toContain("void beginShutdown()");
    expect(shellSource).toContain("applyBeforeUnloadProjectCloseGuard(event, workbenchCloseGuardMessage)");
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

  it("keeps restart completion dismissal stable across runtime polling refreshes", () => {
    expect(shellSource).toContain("restartCompletionDismissTimerRef");
    expect(shellSource).toContain("if (restartCompletionDismissTimerRef.current === null)");
    expect(shellSource).toContain("restartCompletionDismissTimerRef.current = window.setTimeout");
    expect(shellSource).toContain("restartCompletionDismissTimerRef.current = null");
    expect(shellSource).toContain("const clearRestartCompletionDismissTimer = useCallback");
    expect(shellSource).toContain("useEffect(() => clearRestartCompletionDismissTimer, [clearRestartCompletionDismissTimer])");
    expect(shellSource).not.toContain("return () => window.clearTimeout(timer)");
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
