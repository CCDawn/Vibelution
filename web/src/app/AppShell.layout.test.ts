import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import styles from "./AppShell.module.css";
import indexHtml from "../../index.html?raw";
import manifestSource from "../../public/manifest.webmanifest?raw";
import shellSource from "./AppShell.tsx?raw";

const shellStyles = readFileSync(fileURLToPath(new URL("./AppShell.module.css", import.meta.url)), "utf8");

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
    expect(shellSource).toContain("utilityPanel");
    expect(shellSource).toContain("aria-expanded={utilityOpen}");
    expect(shellSource).toContain("hidden={!utilityOpen}");
    expect(shellSource).toContain('event.key === "Escape"');
    expect(shellSource).toContain('to="/logs"');
    expect(shellSource).not.toContain('to="/agents/tools"');
    expect(shellSource).not.toContain('to="/tools"');
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

  it("turns the top refresh icon into a frontend refresh and keeps restart inside the power menu", () => {
    expect(shellSource).toContain("RefreshCw");
    expect(shellSource).toContain("refreshFrontendLabel");
    expect(shellSource).toContain("browser.user_action.frontend_refresh_requested");
    expect(shellSource).toContain("window.location.reload()");
    expect(shellSource).toContain("lifecycleMenuCluster");
    expect(shellSource).toContain("lifecycleMenuPanel");
    expect(shellSource).toContain("lifecycleMenuOpen");
    expect(shellSource).toContain('"/api/runtime/restart"');
    expect(shellSource).toContain("restartWorkbenchLabel");
    expect(shellSource).toContain("beginRestart");
    expect(shellSource).toContain("restartActiveWorkConfirmMessage");
    expect(shellSource).toContain("confirmedActiveWork");
    expect(shellSource).toContain("restart_blocked_active_work");
    expect(shellSource).toContain("requestWorkbenchExitGuard");
    expect(shellSource).toContain('requestWorkbenchExitGuard("restart"');
    expect(shellSource).toContain('requestWorkbenchExitGuard("shutdown"');
    expect(styles.lifecycleMenuCluster).toBeTypeOf("string");
    expect(styles.lifecycleMenuPanel).toBeTypeOf("string");
    expect(styles.lifecycleMenuItem).toBeTypeOf("string");
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
