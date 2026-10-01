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
import { shellDictionary } from "../i18n/shellDictionary";

const shellStyles = readFileSync(fileURLToPath(new URL("../design/workbench-shell.css", import.meta.url)), "utf8");

describe("AppShell layout contract", () => {
  it("routes shell controls through VUI primitives", () => {
    // Prefer direct primitive paths so the shell entry does not pull the VUI barrel graph.
    expect(shellSource).toContain('from "../components/vui/primitives/VButton"');
    expect(shellSource).toContain('from "../components/vui/primitives/VIconButton"');
    expect(shellSource).toContain("<VButton");
    expect(shellSource).toContain("<VIconButton");
    expect(shellSource).not.toMatch(/<button\b/);
  });

  it("keeps the top bar free of per-second tickers and isolates the volatile runtime poll", () => {
    // The brand-block live clock was removed (visual noise); keep it from coming back inline.
    expect(shellSource).not.toContain("AppShellTopClock");
    expect(shellSource).not.toContain("setClockNow");
    expect(shellSource).not.toContain("setInterval(() => {\n      setClockNow");
    expect(shellSource).toContain("shareRuntimeSummaryIfOnlyVolatileChanged");
    expect(shellSource).toContain("structuralSharing: shareRuntimeSummaryIfOnlyVolatileChanged");
  });

  it("keeps the desktop title bar focused on navigation and moves utilities into settings", () => {
    expect(shellSource).toContain('data-shell-group="brand"');
    expect(shellSource).toContain('data-shell-group="navigation"');
    expect(shellSource).toContain('data-shell-group="window-drag-region"');
    expect(shellSource).toContain('data-shell-group="settings"');
    expect(shellSource).not.toContain('data-shell-group="system-actions"');
    expect(shellSource).not.toContain('data-shell-group="tool-actions"');
    // 方案A: the nav container is flattened — only the active tab keeps a pill.
    expect(styles.nav).not.toContain("rounded-[var(--vui-radius-panel-soft)]");
    expect(styles.nav).not.toMatch(/bg-vui-surface-toolbar|bg-\[var\(--vui-surface-toolbar\)\]/);
    expect(styles.nav).not.toContain("shadow-[var(--vui-elevation-panel)]");
    const navLayoutBlock = shellStyles.slice(
      shellStyles.indexOf(":where(.vui-app-appshell).nav {"),
      shellStyles.indexOf(":where(.vui-app-appshell).nav::-webkit-scrollbar"),
    );
    expect(navLayoutBlock).toContain("justify-self: start");
    const titleBar = shellSource.slice(
      shellSource.indexOf('<header className={styles.topBar}>'),
      shellSource.indexOf("</header>"),
    );
    expect(titleBar).not.toContain("RefreshCw");
    expect(titleBar).toContain("<Settings size={17}");
    expect(titleBar).not.toContain("statusSummaryChip");
    expect(titleBar).toContain("windowDragRegion");
    expect(styles.settingsTrigger).toContain("!size-8");
    expect(styles.settingsTrigger).toContain("!rounded-md");
  });

  it("keeps desktop primary navigation labels at their intrinsic readable width", () => {
    const navStyles = shellStyles.slice(
      shellStyles.indexOf(":where(.vui-app-appshell).nav {"),
      shellStyles.indexOf(":where(.vui-app-appshell).navLinkActive {")
    );

    expect(navStyles).toContain("overflow-x: auto");
    expect(navStyles).toContain("flex-shrink: 0");
    expect(navStyles).toContain("white-space: nowrap");
  });

  it("keeps the top bar interactive-first so Electron drag does not swallow primary nav clicks", () => {
    const topBarBlock = shellStyles.slice(
      shellStyles.indexOf(":where(.vui-app-appshell).topBar {"),
      shellStyles.indexOf(":where(.vui-app-appshell).topBar > * {"),
    );
    expect(topBarBlock).toContain("pointer-events: auto");
    expect(topBarBlock).toMatch(/(?:^|\n)\s*-webkit-app-region:\s*no-drag\s*;/);
    // Whole-bar drag is forbidden; only the blank spacer owns dragging.
    expect(topBarBlock).not.toMatch(/(?:^|\n)\s*-webkit-app-region:\s*drag\s*;/);

    // Real specificity on interactive descendants (not only :where).
    expect(shellStyles).toContain(".vui-app-appshell.topBar a");
    expect(shellStyles).toContain(".vui-app-appshell.topBar .nav");
    expect(shellStyles).toContain(".vui-app-appshell.topBar .navLink");
    expect(shellStyles).toContain("-webkit-app-region: no-drag !important");

    const dragBlock = shellStyles.slice(
      shellStyles.indexOf(":where(.vui-app-appshell).windowDragRegion"),
      shellStyles.indexOf(":where(.vui-app-appshell).topBar::before"),
    );
    expect(dragBlock).toContain("-webkit-app-region: drag");
    expect(dragBlock).toContain("min-width: 24px");

    const navBlock = shellStyles.slice(
      shellStyles.indexOf(":where(.vui-app-appshell).nav {"),
      shellStyles.indexOf(":where(.vui-app-appshell).nav::-webkit-scrollbar"),
    );
    expect(navBlock).toContain("pointer-events: auto");
    expect(navBlock).toContain("-webkit-app-region: no-drag");
    expect(navBlock).toContain("z-index: 3");

    const navLinkBlock = shellStyles.slice(
      shellStyles.indexOf(":where(.vui-app-appshell).navLink {"),
      shellStyles.indexOf(":where(.vui-app-appshell).navLink:hover {"),
    );
    expect(navLinkBlock).toContain("color: var(--fg-primary)");
    expect(navLinkBlock).not.toContain("color: var(--fg-secondary)");
  });

  it("renders the status summary inside settings without restoring the diagnostic guide panel", () => {
    expect(shellSource).toContain("settingsStatus");
    expect(shellSource).not.toContain('t("brandSubtle")');
    expect(shellSource).not.toContain("<span className={styles.statusBadgeLabel}>Gate</span>");
    expect(shellSource).not.toContain("className={`${styles.statusCluster} ${styles.brandGate}`}");
    // The diagnostic guide popover stays gone; settings keeps a bare tone dot + text.
    expect(shellSource).not.toContain("LazyAppShellStatusGuidePanel");
    expect(shellSource).not.toContain('data-vui="status-guide-popover"');
    expect(shellSource).not.toContain("statusGuidePopoverContent");
    expect(shellSource).not.toContain("statusGuideOpen");
    expect(shellSource).toContain("systemToneToDotClass");
    expect(shellSource).toContain("styles.statusSummaryDot");
    expect(shellSource).not.toContain('data-shell-group="status-guide"');
    expect(shellSource).not.toContain("rightStatusCards.map((item) => (\n                <span key={item.id} className={styles.statusBadge}>");
  });

  it("keeps the global shell top bar and settings trigger compact", () => {
    expect(styles.statusSummaryDot).toBeTypeOf("string");
    expect(styles.returnButton).toBeTypeOf("string");
    expect(shellStyles).toContain("--shell-topbar-height: 40px");
    expect(shellStyles).not.toContain("--shell-settings-dock-height");
    expect(shellStyles).toContain("env(titlebar-area-width");
    expect(styles.settingsPopoverContent).toContain("w-[min(280px,calc(100vw-20px))]");
    expect(styles.settingsPopoverContent).toContain("max-h-[min(650px,calc(100dvh-90px))]");
    expect(styles.settingsActionList).toContain("grid-cols-1");
    expect(styles.settingsTrigger).toContain("!min-h-8");
    expect(styles.settingsTrigger).toContain("!size-8");
    expect(shellSource).toContain("VStatusChip");
    expect(shellSource).toContain("systemToneToStatus");
    expect(shellSource).toContain("systemToneToDotClass");
    expect(shellSource).toContain("styles.statusSummaryDot");
    expect(shellSource).not.toContain("statusSummaryCount");
    expect(shellSource).not.toContain("styles.statusDot");
    expect(styles.statusBadgeValue).toContain("leading-none");
    expect(styles.statusBadgeValue).toContain("[font-size:var(--vui-font-xs)]");
    expect(shellStyles).toContain("@media (max-width: 1279px)");
    expect(shellStyles).toContain("@media (max-width: 1180px)");
    expect(shellStyles).not.toContain(".topClock");
    expect(shellStyles).toContain("@media (max-width: 980px)");
    expect(shellStyles).toContain("overscroll-behavior-x: contain");
    expect(shellStyles).toContain(".returnButton");
    expect(shellStyles).toContain("width: 32px");
    expect(shellStyles).toContain("max-width: 100%");
    expect(shellStyles).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
    expect(shellStyles).toContain("grid-template-columns: 36px minmax(0, 1fr)");
    expect(shellStyles).toContain("@media (max-width: 639px)");
    expect(shellStyles).toContain("cursor: pointer");

    const compactDesktopBlock = shellStyles.slice(
      shellStyles.indexOf("@media (max-width: 1279px)"),
      shellStyles.indexOf("@media (max-width: 1180px)"),
    );
    expect(compactDesktopBlock).not.toContain(":where(.vui-app-appshell).settingsStatus");
    expect(compactDesktopBlock).not.toContain(":where(.vui-app-appshell).statusBadgeValue");
    expect(compactDesktopBlock).toContain("display: none");

    const narrowDesktopBlock = shellStyles.slice(
      shellStyles.indexOf("@media (max-width: 1180px)"),
      shellStyles.indexOf("@media (max-width: 980px)"),
    );
    expect(narrowDesktopBlock).not.toContain(":where(.vui-app-appshell).settingsStatus");
    expect(narrowDesktopBlock).not.toContain(":where(.vui-app-appshell).statusBadgeValue");

    const narrowTopBarBlock = shellStyles.slice(
      shellStyles.indexOf("@media (max-width: 980px)"),
      shellStyles.indexOf("@media (max-width: 520px)"),
    );
    // The top bar stays on one row at every width; the nav band scrolls horizontally instead of wrapping.
    expect(narrowTopBarBlock).not.toContain("grid-template-areas");
    expect(narrowTopBarBlock).not.toContain("--shell-topbar-height");
  });

  it("keeps AppShell popover headers layout-only instead of card-like", () => {
    const panelChromeTokens = [
      "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)]",
      "bg-[var(--vui-surface-glass)]",
      "shadow-[var(--vui-shadow-hairline)]",
    ];
    const headerStyles = [
      styles.activeWorkDetailHeader,
    ];

    for (const value of headerStyles) {
      expect(value).toContain("flex");
      expect(value).toContain("items-center");
      for (const token of panelChromeTokens) {
        expect(value).not.toContain(token);
      }
    }
    expect(styles.activeWorkDetailHeader).toContain("border-b");
    expect(styles.activeWorkDetailHeader).toContain("text-[var(--fg-primary)]");
  });

  it("routes card-like shell controls through shared quiet hover tokens", () => {
    const loudHoverRecipe =
      "hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)]";
    const shellControlStyles = [
      styles.actionButton,
      styles.returnButton,
      styles.shutdownCancelButton,
      styles.settingsChoiceButton,
      styles.utilityButton,
      styles.utilityFileButton,
    ];

    for (const value of shellControlStyles) {
      expect(value).not.toContain(loudHoverRecipe);
      expect(value).toContain("hover:border-[var(--vui-control-hover-border)]");
      expect(value).toContain("hover:bg-[var(--vui-control-hover-bg)]");
      expect(value).toContain("hover:text-[var(--vui-control-hover-fg)]");
    }
    expect(styles.settingsTrigger).not.toContain("hover:border-");
  });

  it("keeps the light shell top bar on light surfaces without brand text stacks", () => {
    const lightThemeBlock = shellStyles.slice(
      shellStyles.indexOf('.shell[data-theme="light"] {'),
      shellStyles.indexOf('.shell[data-theme="light"][data-theme-background="custom"]'),
    );

    expect(lightThemeBlock).toContain("--shell-page-end: var(--bg-canvas)");
    expect(shellStyles).toContain("--shell-surface: var(--vui-surface-rail)");
    expect(shellStyles).toContain("--shell-panel: var(--vui-surface-panel)");
    expect(shellStyles).toContain("--shell-card: var(--vui-surface-row)");
    expect(shellStyles).toContain("var(--vui-gradient-route-soft),\n    var(--shell-surface)");
    expect(shellStyles).not.toContain("color-mix(in srgb, var(--shell-panel)");
    expect(shellStyles).not.toContain("color-mix(in srgb, var(--shell-card)");
    expect(shellStyles).not.toContain("brandCopy");
    expect(shellStyles).not.toContain("brandSubtle");
    expect(shellStyles).not.toContain("versionPill");
  });

  it("syncs the selected theme to the document root for global VUI tokens", () => {
    expect(shellSource).toContain("syncWorkbenchThemeRoot(theme)");
    expect(shellSource).toContain("useEffect(() => syncWorkbenchThemeRoot(theme), [theme])");
    expect(launcherShellSource).toContain("applyWorkbenchDocumentTheme(document, theme)");
    expect(launcherShellSource).toContain("}, [lang, theme, launcherWindowTitle])");
  });

  it("keeps the unified title bar visible and exposes a compact settings trigger on the title bar", () => {
    expect(shellSource).toContain("useShellStore");
    expect(shellSource).not.toContain("topBarMode");
    expect(shellSource).not.toContain("setTopBarMode");
    expect(shellSource).not.toContain("topBarRestoreButton");
    expect(shellStyles).not.toContain("data-topbar-mode");
    expect(shellSource).not.toContain("--shell-settings-dock-width");
    expect(shellSource).toContain('side="bottom"');
    expect(shellSource).toContain('align="end"');
    expect(styles.settingsTrigger).toContain("!size-8");
    expect(styles.settingsTrigger).toContain("!rounded-md");
    expect(shellStyles).not.toContain(".settingsDock");
    expect(shellSource).toContain("[location.key, closeUtilityMenu]");
  });

  it("keeps the focus ring alive on the settings trigger family", () => {
    // VUI focus indication rides on box-shadow (vuiButtonFocusClass), so any
    // !shadow-none on the trigger would make keyboard focus invisible.
    expect(styles.settingsTrigger).not.toContain("!shadow-none");
    expect(styles.settingsTrigger).not.toContain("shadow-none");
    // The active-work trigger is the consistency baseline and never suppressed it.
    expect(styles.activeWorkTrigger).not.toContain("shadow-none");
  });

  it("wires the git trigger to status-aware labels, summary title and a pending-work dot", () => {
    expect(shellSource).toContain('aria-label={t("navGit")}');
    expect(shellSource).toContain("const shellGitNeedsAttention = Boolean(");
    expect(shellSource).toContain("shellGitStatus.worktrees?.withCommits ?? 0) > 0 || (shellGitStatus.upstream?.ahead ?? 0) > 0");
    expect(shellSource).toContain("`${t(\"navGit\")}：${shellGitStatus.summary}`");
    expect(shellSource).toContain("queryKeys.gitStatus()");
    expect(shellSource).toContain("fetchGitStatus({ limit: 500, signal })");
    expect(shellSource).toContain("styles.settingsTriggerAlertDot");
    // Low-frequency, foreground-only shell poll (shares the /git cache).
    expect(shellSource).toContain("refetchInterval: resolvePollingInterval(shellPollingVisible, 120_000)");
  });

  it("renames the bell to the agent broadcast and tracks unseen broadcasts via a cursor", () => {
    expect(shellSource).toContain("<Bell size={17} />");
    expect(shellSource).not.toContain("BellRing");
    expect(shellSource).toContain("t(\"agentBroadcastLabel\")");
    expect(shellSource).toContain("queryKeys.projectAgentBusLatestEvent()");
    expect(shellSource).toContain("listProjectAgentBusTimeline(1, { signal })");
    // Every left click (modifier or not) counts as having looked at the bell.
    expect(shellSource).toContain("if (event.button === 0) {\n            markAgentBroadcastSeen();\n          }");
    // First visit silently adopts the baseline instead of flagging all history.
    expect(shellSource).toContain("resolveAgentBroadcastBadgeState(agentBroadcastLatestEventMs, agentBroadcastReadAtMs)");
    expect(shellSource).toContain("agentBroadcastBadgeState.adoptedBaseline");
    // Gentle foreground-only poll; no background churn for a badge.
    expect(shellSource).toContain("refetchInterval: resolvePollingInterval(shellPollingVisible, 60_000)");
    expect(styles.settingsTriggerIconSlot).toContain("relative");
    expect(styles.settingsTriggerAlertDot).toContain("bg-[var(--accent-cool)]");
  });

  it("defines the agent broadcast copy for both shell languages", () => {
    expect(shellDictionary.zh.agentBroadcastLabel).toBe("助手广播");
    expect(shellDictionary.zh.agentBroadcastUnread).toBe("有新广播");
    expect(shellDictionary.en.agentBroadcastLabel).toBe("Agent broadcast");
    expect(shellDictionary.en.agentBroadcastUnread).toBe("new broadcasts");
  });

  it("exposes the aux task center from the title bar with a running-count badge", () => {
    // The entry sits in the settings trigger family next to the git shortcut.
    expect(shellSource).toContain('to="/aux"');
    expect(shellSource).toContain("<ListTree size={17} />");
    expect(shellSource).toContain("const auxCenterLabel = lang === \"en\" ? \"Background tasks\" : \"后台任务\";");
    expect(shellSource).toContain('aria-label={auxCenterLabel}');
    // Global active-only badge poll: revision-aware payload, gentle foreground
    // beat, no background churn, cache entry distinct from /aux and strips.
    expect(shellSource).toContain('queryKeys.runtimeTasks("", "shell")');
    expect(shellSource).toContain('listRuntimeTasksRevisionAware(\n        { status: "active" }');
    expect(shellSource).toContain("refetchInterval: resolvePollingInterval(shellPollingVisible, 15_000)");
    expect(shellSource).toContain("refetchIntervalInBackground: false");
    // Badge reads running.length: digit when busy, hidden at zero, 9+ clamp.
    expect(shellSource).toContain('shellAuxRunningCount > 9 ? "9+" : String(shellAuxRunningCount)');
    expect(shellSource).toContain("{shellAuxRunningBadge ? (");
    expect(shellSource).toContain("styles.settingsTriggerCountBadge");
    expect(styles.settingsTriggerCountBadge).toContain("absolute");
    expect(styles.settingsTriggerCountBadge).toContain("bg-[var(--accent-cool)]");
    expect(styles.settingsTriggerCountBadge).toContain("rounded-full");
    // /aux stops falling back to the app title in the return-navigation label.
    expect(shellSource).toContain('if (pathname.startsWith("/aux")) return auxCenterLabel;');
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

  it("keeps the default shell on a flat canvas and custom images optional", () => {
    expect(shellStyles).toContain("background: var(--vui-surface-base)");
    expect(shellStyles).not.toContain("--shell-star-color");
    expect(shellStyles).not.toContain(".shell::before");
    expect(shellStyles).not.toContain("radial-gradient(circle at 8% 18%");
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
    // Full-window blur + fixed attachment caused Edge --app whole-window flicker.
    expect(shellStyles).toContain("backdrop-filter: none");
    expect(shellStyles).toContain("background-attachment: scroll, scroll, scroll");
    expect(shellStyles).toContain("var(--workbench-theme-background-image)");
    expect(shellStyles).toContain("background-size: auto, cover, auto");
  });

  it("avoids background health/runtime fetchStatus re-renders of the whole shell", () => {
    expect(shellSource).toContain('notifyOnChangeProps: ["data", "error", "isError", "isPending", "isSuccess", "isRefetchError"]');
    expect(shellSource).toContain("shareRuntimeSummaryIfOnlyVolatileChanged");
  });

  it("keeps the top bar free of brand text so every control shares one row", () => {
    expect(shellSource).not.toContain("brandCopy");
    expect(shellSource).not.toContain("versionPill");
    expect(shellSource).not.toContain("APP_VERSION");
    expect(shellSource).not.toContain('t("brandSubtle")');
    expect(styles).not.toHaveProperty("brandCopy");
    expect(styles).not.toHaveProperty("versionPill");
    expect(shellStyles).toContain("--shell-topbar-height: 40px");
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

  it("keeps common settings separate from maintenance and project tools", () => {
    expect(shellSource).toContain("LazyAppShellSettingsMenu");
    expect(shellSource).toContain("onThemeChange={selectTheme}");
    expect(shellSource).toContain("onRefresh={refreshFrontend}");
    expect(shellSource).toContain('to="/git"');
    expect(shellSource).toContain('kind: "project_bus"');
    expect(shellSource).not.toContain("gitHeroLabel");
    expect(styles.settingsPopoverContent).toContain("280px");
  });

  it("moves active work details into a title-bar popover", () => {
    expect(shellSource).not.toContain("settingsActiveWork");
    expect(shellSource).toContain("activeWorkIndicator.items.map");
    expect(shellSource).toContain("className={styles.activeWorkDetailLink}");
    expect(shellSource).toContain("to={item.href}");
    expect(shellSource).toContain("contentClassName={styles.activeWorkPopoverContent}");
    expect(shellSource).toContain('data-shell-group="active-work"');
    expect(shellSource).not.toContain('data-vui="active-work-popover"');
    expect(shellSource).not.toContain("className={styles.activeWorkSummary}");
    expect(shellSource).not.toContain("[&:hover_.activeWorkDetailPanel]:visible");
    // Native title stays human-readable; task details live in the clicked popover.
    expect(shellSource).not.toContain("title={activeWorkDetailsTitle}");
    expect(shellSource).not.toContain("formatActiveWorkRunId");
    expect(shellSource).not.toContain("activeWorkChipAriaLabel");

    expect(styles.activeWorkPanel).toBeTypeOf("string");
    expect(styles.activeWorkDetailItem).toBeTypeOf("string");
    expect(styles.activeWorkDetailLink).toContain("block");
    expect(styles.activeWorkDetailLink).toContain("focus-visible:ring-2");
  });

  it("tells the truth when the backend is half dead", () => {
    // Health passes but /api/runtime/summary keeps failing: the runtime card
    // speaks at caution grade so the primary status cannot stay a pure green
    // "connected" driven by the frontend card.
    // The outage predicate must be runtimeQuery.isError alone: TanStack v5
    // keeps stale data beside a failed refetch, so requiring !runtimeQuery.data
    // would miss exactly the cached-data half-dead shape. (startupLoading keeps
    // its own !data guard — a pre-first-load concern, untouched here.)
    const outageDeclaration = shellSource.match(/const runtimeSummaryUnavailable = [^;]+;/)?.[0] ?? "";
    expect(outageDeclaration).toBe("const runtimeSummaryUnavailable = runtimeQuery.isError;");
    expect(shellSource).toContain("applyRuntimeSummaryOutage(");
    expect(shellSource).toContain('t("systemRuntime_unavailable")');
    expect(shellSource).toContain("pickPrimarySystemStatusCard(rightStatusCards)");
    // Heartbeat probes carry bounded timeouts; a hung backend degrades instead
    // of pending forever.
    expect(shellSource).toContain("fetchJsonWithTimeout<BackendHealth>");
    expect(shellSource).toContain("fetchJsonWithTimeout<RuntimeSummary>");
    expect(shellSource).toContain("timeoutMs: BACKEND_HEALTH_TIMEOUT_MS");
    expect(shellSource).toContain("timeoutMs: RUNTIME_SUMMARY_TIMEOUT_MS");
  });

  it("makes the status chip speak the code-freshness verdict and retryable on failure", () => {
    // B-4: a behind build must say "restart recommended" (and an unknown
    // version must stop reading as a green "connected"), not only change color.
    expect(shellSource).toContain("codeFreshnessCardOverride(codeFreshnessQuery.data?.verdict)");
    expect(shellSource).toContain("value: t(codeFreshnessOverride.valueKey)");
    expect(shellSource).toContain('t("codeFreshnessTitle")');
    // Freshness rides both the tooltip summary and the accessible name.
    expect(shellSource).toContain("const statusSummaryAriaLabel = codeFreshnessOverride");
    expect(shellSource).toContain("codeFreshnessStatusPart");
    // Caution never overrides a real failed primary card.
    expect(shellSource).toContain('primaryStatusCard.tone !== "failed"');
    // B-7: a failed primary card turns the chip into an explicit retry control.
    expect(shellSource).toContain("const statusRetryable = effectivePrimaryStatusCard.tone === \"failed\";");
    expect(shellSource).toContain("role={statusRetryable ? \"button\" : undefined}");
    expect(shellSource).toContain("tabIndex={statusRetryable ? 0 : undefined}");
    expect(shellSource).toContain('t("systemStatusRetryHint")');
    expect(shellSource).toContain("queryKeys.backendHealth()");
    expect(shellSource).toContain("queryKeys.runtimeSummary()");
    expect(shellSource).toContain("event.key === \"Enter\" || event.key === \" \"");
    expect(styles.settingsStatusRetry).toContain("cursor-pointer");
    expect(styles.settingsStatusRetry).toContain("focus-visible:ring-2");
  });

  it("refreshes the shell status probes as soon as the window returns to the foreground", () => {
    // A-7: background tabs throttle timers, so the first paint after refocus
    // otherwise shows minutes-old health/runtime state.
    const effectStart = shellSource.indexOf("function handleVisibleRefetch");
    expect(effectStart).toBeGreaterThan(0);
    const refetchEffect = shellSource.slice(effectStart, shellSource.indexOf("}, [queryClient]);", effectStart));
    expect(refetchEffect).toContain('document.visibilityState !== "visible"');
    expect(refetchEffect).toContain("invalidateQueries({ queryKey: queryKeys.backendHealth() })");
    expect(refetchEffect).toContain("invalidateQueries({ queryKey: queryKeys.runtimeSummary() })");
    expect(shellSource).toContain("document.addEventListener(\"visibilitychange\", handleVisibleRefetch)");
  });

  it("tracks popover-switch grace timers in a ref and clears them on open changes", () => {
    // A-8: the 80ms switch timer must not resurrect a popover after the user
    // clicked somewhere else.
    expect(shellSource).toContain("const popoverSwitchTimerRef = useRef<number | null>(null);");
    expect(shellSource).toContain("schedulePopoverSwitch(() => setActiveWorkOpen(true))");
    expect(shellSource).toContain("schedulePopoverSwitch(() => setUtilityOpen(true))");
    expect(shellSource).not.toContain("window.setTimeout(() => setActiveWorkOpen(true), 80)");
    expect(shellSource).not.toContain("window.setTimeout(() => setUtilityOpen(true), 80)");
    const onOpenChangeBlocks = shellSource.match(/clearPopoverSwitchTimer\(\);/g) ?? [];
    expect(onOpenChangeBlocks.length).toBeGreaterThanOrEqual(2);
    expect(shellSource).toContain("useEffect(() => clearPopoverSwitchTimer, [clearPopoverSwitchTimer])");
  });

  it("uniquifies active-work rows and deep-links self evolution to its board", () => {
    // A-6: kind+runId can repeat when the backend mirrors one run in both the
    // active snapshot and its activeItems list.
    expect(shellSource).toContain("key={`${item.kind}-${item.runId || item.status}-${index}`}");
    expect(shellSource).toContain("(item: ActiveWorkIndicatorItem, index: number)");
  });

  it("distinguishes a dirty-workspace behind banner from a moved-ahead main", () => {
    // B-6: behindCount null/0 with a behind verdict = uncommitted changes only.
    const bannerCall = shellSource.match(/const updateBannerText = updateBannerCopy\([\s\S]*?\);/)?.[0] ?? "";
    expect(bannerCall).toContain("updateBannerVerdict === \"backend_and_frontend_behind\"");
    expect(bannerCall).toContain("codeFreshnessQuery.data?.backend.behindCount ?? null");
    expect(shellDictionary.zh.updateBannerDirtyTitle).toBe("工作区有未提交变化，重启后生效");
    expect(shellDictionary.zh.updateBannerDirtyDetail).toContain("工作区");
    expect(shellDictionary.en.updateBannerDirtyTitle).toBe("Working tree changed — restart to apply");
  });

  it("renders terminal failed runs as a caution leftover section instead of hiding them", () => {
    expect(shellSource).toContain("activeWorkStaleFailures");
    expect(shellSource).toContain("activeWorkStaleFailures.map(renderActiveWorkItem)");
    expect(shellSource).toContain("className={styles.activeWorkStaleSection}");
    expect(shellSource).toContain('t("activeWorkStaleFailureSection")');
    expect(shellSource).toContain('t("activeWorkEmptyStaleFailure")');
    expect(shellSource).toContain('t("activeWorkEmpty")');
    // The trigger dot turns caution while leftover failures exist.
    expect(shellSource).toContain("activeWorkTriggerTone");
    // Running work shows an interruption notice; it never disables the user restart.
    const restartDisabledRegion = shellSource.slice(
      shellSource.indexOf("const updateBannerRestartDisabled"),
      shellSource.indexOf("const updateBannerRestartNotice"),
    );
    expect(restartDisabledRegion).not.toContain("activeWork");
    expect(restartDisabledRegion).toContain("restartRequested");
    expect(restartDisabledRegion).toContain("shutdownRequested");
    expect(restartDisabledRegion).toContain("shutdownOpen && !shutdownSettled");
    expect(shellSource).toContain("restartActiveWorkNoticeMessage(lang, activeWorkLabels)");
    expect(shellSource).toContain("activeWorkIndicator?.items.map((item) => item.label)");
    expect(shellSource).not.toContain("restartActiveWorkNoticeMessage(lang, activeWorkDetailsTitle)");

    expect(styles.activeWorkStaleSection).toContain("border-t");
    expect(styles.activeWorkStaleHeader).toContain("var(--state-warning)");
  });

  it("bounds active work details inside their own popover", () => {
    expect(shellSource).not.toContain("activeWorkInlineDetails");
    expect(shellSource).not.toContain("activeWorkInlineItem");
    expect(styles.activeWorkPopoverContent).toContain("overflow-y-auto");
    expect(styles.activeWorkPopoverContent).toContain("w-[min(370px,calc(100vw-20px))]");
    expect(shellStyles).toContain("max-height: min(330px, 45vh)");
    expect(styles.activeWorkDetailCopy).toContain("[&_p]:truncate");
    expect(styles.activeWorkDetailList).not.toContain("max-h-");
    expect(shellStyles).not.toContain("activeWorkChip:hover .activeWorkInlineDetails");
    expect(shellStyles).not.toContain("activeWorkInlineItem");
  });

  it("keeps active work in the title bar without swallowing the drag region", () => {
    const titleBar = shellSource.slice(
      shellSource.indexOf('<header className={styles.topBar}>'),
      shellSource.indexOf("</header>"),
    );
    expect(titleBar).toContain("activeWorkIndicator");
    expect(titleBar).toContain("activeWorkSlot");
    expect(titleBar).toContain('data-shell-group="active-work"');
    expect(titleBar.indexOf('data-shell-group="window-drag-region"')).toBeLessThan(titleBar.indexOf('data-shell-group="active-work"'));
    // Empty states live in the shell dictionary (zh/en) via t("activeWorkEmpty").
    expect(shellSource).toContain('t("activeWorkEmpty")');
    expect(shellSource).toContain('activeWorkUnavailable ? "—"');
  });

  it("keeps active work compact without nested cards or horizontal overflow", () => {
    expect(shellSource).toContain("className={styles.activeWorkPanel}");
    expect(shellStyles).toContain("overflow-x: hidden");
    expect(shellStyles).toContain(":where(.vui-app-appshell).activeWorkDetailHeader");
    expect(shellStyles).toContain("padding: 6px 8px 9px");
    expect(shellStyles).toContain(":where(.vui-app-appshell).activeWorkDetailList");
    expect(shellStyles).toContain("padding: 0");
    expect(shellStyles).toContain(":where(.vui-app-appshell).activeWorkDetailCopy");
    expect(shellStyles).toContain("background: transparent");
    expect(shellStyles).toContain(":where(.vui-app-appshell).activeWorkDetailTitle");
    expect(shellStyles).toContain("grid-template-columns: 7px minmax(0, 1fr) max-content");
    expect(shellStyles).toContain("border: 0");
    expect(shellStyles).toContain("text-overflow: ellipsis");

    expect(styles.activeWorkPopoverContent).toContain("calc(100dvh-70px)");
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
    expect(shellSource).toContain("if (configQuery.data && backendHealthQuery.data)");
    expect(shellSource).not.toContain("if (configQuery.data && runtimeQuery.data && backendHealthQuery.data)");
    expect(shellSource).toContain("setShellStartupDataReady(true)");
    expect(shellSource).toContain("enabled: shellStartupDataReady");
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

  it("routes accepted browser window closes through controlled Launcher lifecycle", () => {
    const beforeUnloadBody = shellSource.match(/useStableBeforeUnload\(\(event\) => \{[\s\S]*?\n  \}\);/)?.[0] ?? "";

    expect(beforeUnloadBody).toContain("prepareWorkbenchWindowCloseIntent");
    expect(beforeUnloadBody).toContain("consumeNextWorkbenchWindowUnloadAllowance");
    expect(beforeUnloadBody).toContain("projectCloseGuardRef");
    expect(shellSource).toContain("useStableBeforeUnload");
    expect(shellSource).toContain("consumePendingWorkbenchWindowCloseIntent");
    expect(shellSource).toContain("requestWorkbenchWindowCloseOnPageHide");
    expect(shellSource).toContain("event.persisted");
    expect(shellSource).toContain("isWorkbenchRefreshShortcut");
    expect(beforeUnloadBody).not.toContain("beginShutdown");
  });

  it("keeps frontend refresh in the shell while Launcher exclusively owns lifecycle controls", () => {
    expect(shellSource).toContain("onRefresh={refreshFrontend}");
    expect(shellSource).not.toContain("className={styles.actionIconButton}");
    expect(shellSource).toContain("refreshDisabled={restartRequested || shutdownRequested");
    expect(shellSource).toContain("browser.user_action.frontend_refresh_requested");
    expect(shellSource).toContain("allowNextWorkbenchWindowUnload");
    expect(shellSource).toContain("window.location.reload()");
    expect(shellSource).not.toContain("window.setTimeout(() => window.location.reload(), 0)");
    // Stable beforeunload: shared hook + ref decision, not re-armed on every polled state tick.
    expect(shellSource).toContain("projectCloseGuardRef");
    expect(shellSource).toContain("useStableBeforeUnload");
    expect(shellSource).not.toContain("lifecycleMenuOpen");
    expect(shellSource).not.toContain("VWorkbenchPowerMenu");
    expect(shellSource).not.toContain("restartWorkbenchLabel");
    expect(shellSource).not.toContain("forceCloseWorkbenchLabel");
    expect(shellSource).not.toContain("closeWorkbenchLabel");
    // Native Workbench X is the sole close entry; browser fallback close stays guarded.
    expect(shellSource).toContain("shouldArmBrowserProjectCloseGuard");
    expect(shellSource).toContain("electronDesktopShell: desktopShell");
    expect(shellSource).not.toContain("stopLauncherBundle");
    expect(shellSource).not.toContain("forceStopLauncherBundle");
    expect(shellSource).not.toContain("restartLauncherBundle");
    expect(shellSource).toContain("cancelRuntimeLifecycleCommand");
    expect(shellSource).toContain("parseRuntimeControlBlockedDetail");
    expect(shellSource).toContain("isActiveWorkStopBlocked");
    expect(shellSource).toContain("isActiveWorkRestartBlocked");
    expect(shellSource).not.toContain('"/api/runtime/restart"');
    expect(shellSource).not.toContain('"/api/runtime/shutdown"');
    expect(shellSource).toContain("restartActiveWorkBlockedMessage");
    expect(shellSource).toContain("HTTP 409");
    expect(shellSource).toContain("Close this notice to retry.");
    expect(shellSource).toContain("关闭此提示后可以重试。");
    expect(shellSource).toContain("shutdownActiveWorkBlockedMessage");
    expect(shellSource).not.toContain("confirmedActiveWork");
    expect(shellSource).toContain("restart_blocked_active_work");
    expect(shellSource).toContain("shutdown_blocked_active_work");
    expect(shellSource).toContain("browser.user_action.force_shutdown_requested");
    expect(shellSource).toContain("browser.user_action.force_shutdown_unconfirmed");
    expect(shellSource).not.toContain("lifecycleMenuRef");
    // The update banner restart rides the same dormant shell lifecycle path
    // (beginRestart -> requestLifecycle) — never a direct restart API call.
    expect(shellSource).toContain("onPress={beginRestart}");
    const restartRegion = shellSource.slice(
      shellSource.indexOf("const beginRestart"),
      shellSource.indexOf("const cancelLifecycleWait"),
    );
    expect(restartRegion).toContain("restartWaitsForDocumentReloadRef.current = true");
    expect(restartRegion).toContain("updateBannerRestartReloadsDocument(payload.code, payload.accepted)");
    expect(restartRegion).toContain('payload.code === "user_restart_pause_failed"');
    expect(restartRegion).toContain("重启前未能保存任务状态，已有记录仍保留");
    expect(restartRegion).toContain("window.location.reload()");
    expect(shellSource).toContain("ready && restartWaitsForDocumentReloadRef.current");
  });

  it("surfaces a dismissible update banner only when the backend is behind disk HEAD", () => {
    expect(shellSource).toContain('from "./updateBanner"');
    expect(shellSource).toContain("shouldShowUpdateBanner");
    expect(shellSource).toContain("readStoredUpdateBannerDismissedHead");
    expect(shellSource).toContain("storeUpdateBannerDismissedHead");
    // Only backend-stale verdicts prompt; frontend-only stays on refresh-frontend.
    expect(shellSource).toContain("updateBannerVerdict === \"backend_and_frontend_behind\"");

    // Notification is a collapsed top-bar popover, never a workspace row.
    const bannerRegion = shellSource.slice(
      shellSource.indexOf("{updateBannerVisible ?"),
      shellSource.indexOf('data-shell-group="active-work"'),
    );
    expect(shellSource.indexOf("{updateBannerVisible ?")).toBeLessThan(shellSource.lastIndexOf("</header>"));
    expect(bannerRegion).toContain("<VPopover");
    expect(bannerRegion).not.toContain("defaultOpen");
    expect(bannerRegion).toContain('role="status"');
    expect(bannerRegion).toContain("updateBannerVisible ?");
    expect(bannerRegion).toContain("onPress={beginRestart}");
    expect(bannerRegion).toContain("isDisabled={updateBannerRestartDisabled}");
    expect(bannerRegion).toContain("{updateBannerRestartNotice}");
    expect(bannerRegion).toContain("title={updateBannerRestartNotice || updateBannerRestartActionLabel}");
    expect(shellSource).toContain("activeWorkRestartNotice = (activeWorkIndicator?.items.length ?? 0) > 0");
    expect(shellSource).toContain("updateBannerRestartNotice = activeWorkRestartNotice");
    // The initial restart overlay explains interruption using task labels only.
    expect(shellSource).toContain("restartActiveWorkNoticeMessage(lang, activeWorkLabels)");
    expect(shellSource).toContain("const activeWorkLabels = [...new Set(activeWorkIndicator?.items.map((item) => item.label)");
    const restartWaitEffect = shellSource.slice(
      shellSource.indexOf('if (!restartRequested || !workbench)'),
      shellSource.indexOf("useEffect(() => clearRestartCompletionDismissTimer"),
    );
    expect(restartWaitEffect).toContain("restartDetailWithActiveWorkNotice");
    expect(restartWaitEffect).toContain("activeWorkRestartNotice,");
    expect(bannerRegion).toContain("onPress={dismissUpdateBanner}");
    expect(bannerRegion).not.toContain("/api/runtime/");

    // Dismissal is keyed to the disk HEAD commit, so a new commit re-prompts.
    expect(shellSource).toContain("dismissedHead: updateBannerDismissedHead");
    expect(shellSource).toContain("diskHead: updateBannerDiskHead");

    expect(shellSource).not.toContain("UPDATE_BANNER_MAIN_AREA_STYLE");
    expect(shellSource).not.toContain("UPDATE_BANNER_SHELL_GRID_ROWS");
    expect(shellSource).toContain('<main className={styles.mainArea}>');

    // It rides the whitelisted code-freshness poll — no per-second ticker.
    expect(shellSource).not.toContain("setClockNow");
    expect(shellSource).not.toMatch(/updateBanner[\s\S]{0,200}setInterval/);

    expect(styles.updateBanner).not.toContain("mt-[var(--shell-topbar-height)]");
    expect(styles.updateBannerPopover).toContain("overflow-y-auto");
    expect(styles.updateBanner).not.toMatch(/rounded-\[\d/);
    expect(styles.updateBannerTitle).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.updateBannerRestartButton).toBeTypeOf("string");
    expect(styles.updateBannerNote).toContain("whitespace-pre-line");
  });

  it("lets lifecycle wait overlays be cancelled without stopping active work", () => {
    expect(shellSource).toContain("cancelLifecycleWait");
    expect(shellSource).toContain("cancelSupersededLifecycleCommand");
    expect(shellSource).toContain("lifecycleRequestSeqRef");
    expect(shellSource).toContain("lifecycleOverlayDismissedRef");
    expect(shellSource).toContain("setLifecycleAction(\"restart\")");
    expect(shellSource).toContain("setLifecycleAction(\"shutdown\")");
    expect(shellSource).toContain("cancelRestartLabel");
    expect(shellSource).toContain("closeLifecycleNoticeLabel");
    expect(shellSource).toContain("!restartRequested && !lifecycleCommandId.trim()");
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
    expect(shellSource).toContain("shouldRenderStartupOverlay(startupPanel, desktopShell)");
    expect(shellSource).toContain("startupOverlayActive");
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
    expect(styles.settingsSlot).toContain("shrink-0");
    expect(styles.statusBadgeLabel).toBeTypeOf("string");
    expect(styles.nav).not.toContain("max-[639px]");
    expect(styles.mobileNav).not.toContain("max-[639px]");
    expect(styles.mobileRouteMenu).not.toContain("max-[639px]");
    expect(shellSource).toContain("activePrimaryRouteLabel");
    expect(shellSource).toContain('data-shell-group="mobile-navigation"');
    expect(shellSource).toContain('id="shell-mobile-route-menu"');
    expect(shellSource).toContain('aria-haspopup="dialog"');
    expect(shellSource).toContain("shellMobileNavClass");
    expect(shellSource).toContain("closeUtilityMenu");
    expect(shellSource).toContain("SpecialistAgentMenu");
    expect(shellStyles).toContain("@media (max-width: 639px)");
    expect(shellStyles).not.toContain("padding-bottom: var(--shell-settings-dock-height)");
    expect(shellSource).not.toContain('data-shell-group="settings-dock"');
    const mobileShellBlock = shellStyles.slice(shellStyles.indexOf("@media (max-width: 639px)"));
    expect(mobileShellBlock).toContain(":where(.vui-app-appshell).topBar .nav");
    expect(mobileShellBlock).toContain(":where(.vui-app-appshell).topBar .mobileNav");
    expect(mobileShellBlock).toContain(":where(.vui-app-appshell).settingsPopoverBody .mobileRouteMenu");
    expect(mobileShellBlock).toMatch(/\.topBar \.nav\s*\{\s*display: none;/);
    expect(mobileShellBlock).toMatch(/\.topBar \.mobileNav\s*\{\s*display: flex;/);
    expect(mobileShellBlock).toMatch(/\.settingsPopoverBody \.mobileRouteToggle\s*\{\s*display: flex;/);
    expect(mobileShellBlock).toMatch(/\.settingsPopoverBody \.mobileRouteMenu\s*\{\s*display: none;/);
    expect(mobileShellBlock).toMatch(/\.settingsPopoverBody \.mobileRouteMenuOpen\s*\{\s*display: grid;/);
  });

  it("themes the managed app window chrome to match the light-first shell", () => {
    const manifest = JSON.parse(manifestSource);

    expect(indexHtml).toContain('data-theme="light"');
    expect(indexHtml).toContain('localStorage.getItem("vibelution.workbench.theme")');
    expect(indexHtml).not.toContain("devicePixelRatio");
    expect(indexHtml).toContain("100svw");
    expect(indexHtml).toContain('node.style.overflowX = "clip"');
    expect(indexHtml).toContain('node.style.width = "100%"');
    expect(indexHtml).toContain('--vui-window-width');
    expect(indexHtml).toContain('name="theme-color" content="#f7f8fa"');
    expect(indexHtml).toContain('name="color-scheme" content="light dark"');
    expect(indexHtml).toContain('rel="manifest" href="/manifest.webmanifest"');
    expect(indexHtml).toContain('rel="icon" href="/favicon.ico" sizes="any"');
    expect(indexHtml).toContain('rel="icon" type="image/png" href="/vibelution-icon.png"');
    expect(indexHtml).toContain('rel="apple-touch-icon" href="/vibelution-icon-192.png"');
    expect(manifest.theme_color).toBe("#f7f8fa");
    expect(manifest.background_color).toBe("#f7f8fa");
    expect(manifest.display).toBe("standalone");
    expect(manifest.icons).toEqual([
      {
        src: "/vibelution-icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/vibelution-icon.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/vibelution-icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ]);
    expect(shellSource).toContain("syncWorkbenchThemeRoot(theme)");
    expect(shellSource).toContain("isElectronDesktopShell()");
    expect(shellSource).toContain('data-desktop-shell={desktopShell ? "electron" : "browser"}');
    // Native caption controls overlay the web title bar, so navigation reserves
    // the reported Window Controls Overlay area with a Windows fallback.
    expect(shellStyles).toContain('.shell[data-desktop-shell="electron"]');
    expect(shellStyles).toContain("--shell-window-control-inset: 138px");
    expect(shellStyles).toContain("env(titlebar-area-x, 0px)");
    expect(shellStyles).toContain("env(titlebar-area-width");
    expect(shellStyles).toContain("--shell-window-control-inset: 0px");
    expect(shellStyles).not.toMatch(/font-size:\s*0\.(?:[0-6]\d?|7(?:0|1)?)rem/);
  });
});
