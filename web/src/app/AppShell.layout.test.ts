import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import styles from "./AppShell.styles";
import indexHtml from "../../index.html?raw";
import manifestSource from "../../public/manifest.webmanifest?raw";
import shellSource from "./AppShell.tsx?raw";
import launcherShellSource from "./LauncherShell.tsx?raw";
import documentLanguageSource from "./documentLanguage.ts?raw";
import useShellI18nSource from "../i18n/useShellI18n.ts?raw";
import utilityMenuSource from "./AppShellUtilityMenu.tsx?raw";
import statusGuideSource from "./AppShellStatusGuidePanel.tsx?raw";

const shellStyles = readFileSync(fileURLToPath(new URL("../design/workbench-shell.css", import.meta.url)), "utf8");

describe("AppShell layout contract", () => {
  it("routes shell controls through VUI primitives", () => {
    expect(shellSource).toContain("from \"../components/vui\"");
    expect(shellSource).toContain("<VButton");
    expect(shellSource).toContain("<VIconButton");
    expect(shellSource).not.toMatch(/<button\b/);
  });

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
    expect(shellStyles).toContain(":where(.vui-app-appshell).statusGuideCard");
    expect(shellStyles).toContain("width: 100%");
    expect(shellStyles).toContain("max-width: none");
    expect(shellStyles).toContain(".vui-app-appshell.statusGuidePanel");
    expect(shellStyles).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
    expect(shellStyles).toContain("flex-wrap: nowrap");
    expect(styles.topActions).toContain("flex-nowrap");
    expect(styles.utilityTrigger).toContain("h-8");
    expect(styles.utilityTrigger).toContain("[&_[data-slot=vui-button-content]]:whitespace-nowrap");
    expect(styles.statusSummaryChip).toContain("whitespace-nowrap");
    expect(shellStyles).toContain("@media (max-width: 1420px)");
    expect(shellStyles).toContain("@media (max-width: 1180px)");
    expect(shellStyles).toContain(".topClock span:last-child");
    expect(shellStyles).toContain("@media (max-width: 980px)");
    expect(shellStyles).toContain("overscroll-behavior-x: contain");
    expect(shellStyles).toContain(".returnButton");
    expect(shellStyles).toContain("width: 32px");
    expect(shellStyles).toContain("grid-template-columns: minmax(0, max-content) minmax(0, 1fr) max-content;");
    expect(shellStyles).toContain("max-width: 100%");
    expect(shellStyles).toContain("width: min(520px, calc(100vw - 40px))");
    expect(shellStyles).toContain("max-height: min(78vh, 760px)");
    expect(shellStyles).toContain("grid-template-columns: repeat(4, minmax(0, 1fr))");
    expect(shellStyles).toContain("grid-template-columns: 36px minmax(0, 1fr)");
    expect(shellStyles).toContain("@media (max-width: 640px)");
    expect(shellStyles).toContain("width: min(360px, calc(100vw - 20px))");
    expect(shellStyles).toContain("left: 0");
    expect(shellStyles).toContain("grid-template-columns: repeat(2, minmax(72px, max-content))");
    expect(shellStyles).toContain("word-break: keep-all");

    const compactDesktopBlock = shellStyles.slice(
      shellStyles.indexOf("@media (max-width: 1420px)"),
      shellStyles.indexOf("@media (max-width: 1180px)"),
    );
    expect(compactDesktopBlock).toContain(":where(.vui-app-appshell).topClock span:last-child");
    expect(compactDesktopBlock).not.toContain(":where(.vui-app-appshell).statusBadgeValue");
    expect(compactDesktopBlock).toContain("display: none");

    const narrowDesktopBlock = shellStyles.slice(
      shellStyles.indexOf("@media (max-width: 1180px)"),
      shellStyles.indexOf("@media (max-width: 980px)"),
    );
    expect(narrowDesktopBlock).toContain(":where(.vui-app-appshell).topClock span:last-child");
    expect(narrowDesktopBlock).not.toContain(":where(.vui-app-appshell).statusBadgeValue");

    const wrappedTopBarBlock = shellStyles.slice(
      shellStyles.indexOf("@media (max-width: 980px)"),
      shellStyles.indexOf("@media (max-width: 520px)"),
    );
    expect(wrappedTopBarBlock).toContain(".vui-app-appshell.statusGuidePanel");
    expect(wrappedTopBarBlock).toContain("position: fixed");
    expect(wrappedTopBarBlock).toContain("top: 108px");
    expect(wrappedTopBarBlock).toContain("max-height: calc(100dvh - 124px)");
  });

  it("keeps the light shell top bar on light surfaces with a stable brand stack", () => {
    const lightThemeBlock = shellStyles.slice(
      shellStyles.indexOf('.shell[data-theme="light"] {'),
      shellStyles.indexOf('.shell[data-theme="light"][data-theme-background="custom"]'),
    );

    expect(lightThemeBlock).toContain("--shell-page-end: var(--bg-canvas)");
    expect(lightThemeBlock).toContain("--shell-surface: color-mix(in srgb, var(--surface-panel) 92%, transparent)");
    expect(lightThemeBlock).not.toContain("--shell-surface: color-mix(in srgb, var(--fg-primary)");
    expect(lightThemeBlock).not.toContain("--shell-panel: var(--fg-primary)");
    expect(shellStyles).toContain('.shell[data-theme="light"] .topBar::before');
    expect(shellStyles).toContain("color-mix(in srgb, var(--surface-panel) 68%, transparent)");
    expect(shellStyles).not.toContain("background: color-mix(in srgb, var(--surface-panel) 86%, transparent)");
    expect(shellStyles).toContain('grid-template-areas:\n    "brand version"\n    "subtle subtle";');
    expect(shellStyles).toContain("max-width: min(230px, 34vw)");
  });

  it("syncs the selected theme to the document root for global VUI tokens", () => {
    expect(shellSource).toContain("syncWorkbenchThemeRoot(theme)");
    expect(shellSource).toContain("useEffect(() => syncWorkbenchThemeRoot(theme), [theme])");
    expect(launcherShellSource).toContain("applyWorkbenchDocumentTheme(document, theme)");
    expect(launcherShellSource).toContain("}, [lang, theme])");
  });

  it("can hide the web top bar while keeping a restore control", () => {
    expect(shellSource).toContain("useShellStore");
    expect(shellSource).toContain("topBarMode");
    expect(shellSource).toContain('const topBarHidden = topBarMode === "hidden"');
    expect(shellSource).toContain("setTopBarMode(\"hidden\")");
    expect(shellSource).toContain("setTopBarMode(\"full\")");
    expect(shellSource).toContain('data-topbar-mode={topBarMode}');
    expect(shellSource).toContain("topBarRestoreButton");
    expect(shellSource).toContain("hideTopBarLabel");
    expect(shellSource).toContain("showTopBarLabel");
    expect(shellStyles).toContain('.shell[data-topbar-mode="hidden"]');
    expect(shellStyles).toContain("--shell-topbar-height: 0px");
    expect(shellStyles).toContain('.shell[data-topbar-mode="hidden"] .topBar');
    expect(shellStyles).toContain("display: none");
    expect(styles.topBarRestoreButton).toBeTypeOf("string");
  });

  it("exposes a shell-level semantic return action without visible helper copy", () => {
    expect(shellSource).toContain("resolveReturnTarget(routeLocationFromRouter(location), returnNavigationStack)");
    expect(shellSource).toContain("consumeReturnNavigationTarget(current, targetPath)");
    expect(shellSource).toContain("suppressNextReturnStackPushRef.current = true");
    expect(shellSource).toContain("RETURN_NAVIGATION_STACK_STORAGE_KEY");
    expect(shellSource).toContain("className={styles.returnButton}");
    expect(shellSource).toContain("label={returnNavigationLabel}");
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
    expect(utilityMenuSource).toContain("<VNativeInput");
    expect(utilityMenuSource).not.toMatch(/<input\b/);
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
    expect(shellSource).toMatch(/if \(!frontendVisible\) \{\s+return;\s+\}/);
    expect(shellSource).toContain("window.setInterval(() => emitMemorySample(\"periodic\"), BROWSER_MEMORY_SAMPLE_INTERVAL_MS)");
    expect(shellSource).toContain("frontendVisible, location.pathname, queryClient");
  });

  it("keeps startup data loading alive while the managed window is hidden", () => {
    expect(shellSource).toContain("const shellStartupWarmupActive = useStartupWarmup(shellStartupDataReady)");
    expect(shellSource).toContain("const shellPollingVisible = frontendVisible || shellStartupWarmupActive");
    expect(shellSource).toMatch(/resolvePollingInterval\(\s+shellPollingVisible/);
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

  it("keeps browser unload guards from stopping the workbench backend", () => {
    const beforeUnloadBody = shellSource.match(/function handleBeforeUnload\(event: BeforeUnloadEvent\) \{[\s\S]*?\n    \}/)?.[0] ?? "";

    expect(beforeUnloadBody).toContain("applyBeforeUnloadProjectCloseGuard(event, workbenchCloseGuardMessage)");
    expect(beforeUnloadBody).not.toContain("markControlledProjectLifecycleOperation(\"stop\")");
    expect(beforeUnloadBody).not.toContain("beginShutdown");
  });

  it("turns the top refresh icon into a frontend refresh and routes lifecycle actions through Launcher", () => {
    expect(shellSource).toContain("VIconButton");
    expect(shellSource).toContain("label={refreshFrontendLabel}");
    expect(shellSource).not.toContain("<button\n            type=\"button\"\n            className={styles.actionIconButton}");
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
    expect(shellStyles).toContain("@media (max-width: 520px)");

    const narrowShellStyles = shellStyles.slice(shellStyles.indexOf("@media (max-width: 520px)"));
    expect(narrowShellStyles).toContain("grid-template-columns: minmax(0, 1fr) auto");
    expect(narrowShellStyles).toContain(".nav {");
    expect(narrowShellStyles).toContain("justify-self: stretch");
    expect(narrowShellStyles).toContain("width: 100%");
    expect(narrowShellStyles).toContain(".navLink {");
    expect(narrowShellStyles).toContain("flex: 1 1 0");
    expect(narrowShellStyles).toContain("min-width: 0");
    expect(narrowShellStyles).toContain("overflow: hidden");
    expect(narrowShellStyles).toContain("text-overflow: ellipsis");
  });

  it("themes the managed app window chrome to match the light-first shell", () => {
    const manifest = JSON.parse(manifestSource);

    expect(indexHtml).toContain('data-theme="light"');
    expect(indexHtml).toContain('localStorage.getItem("vibelution.workbench.theme")');
    expect(indexHtml).toContain('name="theme-color" content="#f7f8fa"');
    expect(indexHtml).toContain('name="color-scheme" content="light dark"');
    expect(indexHtml).toContain('rel="manifest" href="/manifest.webmanifest"');
    expect(manifest.theme_color).toBe("#f7f8fa");
    expect(manifest.background_color).toBe("#f7f8fa");
    expect(manifest.display).toBe("standalone");
    expect(shellSource).toContain("syncWorkbenchThemeRoot(theme)");
    expect(shellSource).toContain("isElectronDesktopShell()");
    expect(shellSource).toContain('data-desktop-shell={desktopShell ? "electron" : "browser"}');
    expect(shellStyles).toContain('.shell[data-desktop-shell="electron"] .topBar');
    expect(shellStyles).toContain("--shell-window-control-inset");
    expect(shellStyles).not.toMatch(/font-size:\s*0\.(?:[0-6]\d?|7(?:0|1)?)rem/);
  });
});
