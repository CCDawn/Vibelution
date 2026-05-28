import { describe, expect, it } from "vitest";

import styles from "./AppShell.module.css";
import indexHtml from "../../index.html?raw";
import manifestSource from "../../public/manifest.webmanifest?raw";
import shellSource from "./AppShell.tsx?raw";

describe("AppShell layout contract", () => {
  it("renders one compact status summary chip while keeping the detailed guide panel", () => {
    expect(shellSource).toContain("statusSummaryChip");
    expect(shellSource).toContain("statusGuidePanel");
    expect(shellSource).not.toContain("rightStatusCards.map((item) => (\n                <span key={item.id} className={styles.statusBadge}>");
  });

  it("keeps the global shell top bar compact", () => {
    expect(styles.statusSummaryChip).toBeTypeOf("string");
    expect(styles.statusSummaryCount).toBeTypeOf("string");
  });

  it("shows the current app version in the brand area", () => {
    expect(shellSource).toContain("APP_VERSION");
    expect(shellSource).toContain("packageJson.version");
    expect(shellSource).toContain("versionPill");
    expect(styles.versionPill).toBeTypeOf("string");
  });

  it("exposes the research preview from the primary navigation", () => {
    expect(shellSource).toContain('to="/research"');
    expect(shellSource).toContain('t("navResearch")');
  });

  it("collapses logs tools and git behind one hover utility menu", () => {
    const primaryNav = shellSource.slice(
      shellSource.indexOf("<nav className={styles.nav}>"),
      shellSource.indexOf("</nav>"),
    );

    expect(primaryNav).not.toContain('to="/logs"');
    expect(primaryNav).not.toContain('to="/tools"');
    expect(primaryNav).not.toContain('to="/agents/tools"');
    expect(primaryNav).not.toContain('to="/memory"');
    expect(primaryNav).not.toContain('to="/git"');
    expect(shellSource).toContain("utilityCluster");
    expect(shellSource).toContain("utilityClusterOpen");
    expect(shellSource).toContain("utilityPanel");
    expect(shellSource).toContain("aria-expanded={utilityOpen}");
    expect(shellSource).toContain("hidden={!utilityOpen}");
    expect(shellSource).toContain('event.key === "Escape"');
    expect(shellSource).toContain('to="/logs"');
    expect(shellSource).toContain('to="/agents/tools"');
    expect(shellSource).not.toContain('to="/tools"');
    expect(shellSource).not.toContain('to="/memory"');
    expect(shellSource).toContain("Wrench");
    expect(shellSource).toContain('to="/git"');
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

  it("treats locally completed shutdown as a settled state rather than a failed state", () => {
    expect(shellSource).toContain("shutdownSettled");
    expect(shellSource).toContain("aria-busy={!shutdownSettled}");
    expect(shellSource).toContain("shutdownLocallyCompleteTitle");
    expect(shellSource).not.toContain("shutdownFailed");
  });

  it("exposes a managed restart control beside the close control", () => {
    expect(shellSource).toContain("RefreshCw");
    expect(shellSource).toContain('"/api/runtime/restart"');
    expect(shellSource).toContain("restartWorkbenchLabel");
    expect(shellSource).toContain("beginRestart");
    expect(shellSource).toContain("requestWorkbenchExitGuard");
    expect(shellSource).toContain('requestWorkbenchExitGuard("restart"');
    expect(shellSource).toContain('requestWorkbenchExitGuard("shutdown"');
  });

  it("renders a startup progress overlay from loading and lifecycle state", () => {
    expect(shellSource).toContain("deriveStartupLoadingState");
    expect(shellSource).toContain("deriveStartupProgressState");
    expect(shellSource).toContain("startupPanel.active");
    expect(shellSource).toContain("startupLoadingShouldBlock");
    expect(shellSource).toContain('startupLoadingProgress.tone === "failed"');
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
