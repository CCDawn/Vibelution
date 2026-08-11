import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const appShellSourcePath = fileURLToPath(new URL("./AppShell.tsx", import.meta.url));

describe("AppShell Electron lifecycle fallback boundary", () => {
  it("does not arm the browser close guard when Electron owns the desktop lifecycle", () => {
    const source = readFileSync(appShellSourcePath, "utf8");
    const beforeUnloadBody = source.match(/useStableBeforeUnload\(\(event\) => \{[\s\S]*?\n  \}\);/)?.[0] ?? "";

    expect(beforeUnloadBody).toContain("electronDesktopShell: desktopShell");
    expect(beforeUnloadBody).not.toContain("electronDesktopShell: false");
  });

  it("keeps the Edge pagehide stop fallback but suppresses it under Electron", () => {
    const source = readFileSync(appShellSourcePath, "utf8");
    const pageHideBody = source.slice(
      source.indexOf("function handlePageHide(event: PageTransitionEvent)"),
      source.indexOf('window.addEventListener("pagehide", handlePageHide)')
    );

    expect(pageHideBody).toContain("desktopShell ? null : consumePendingWorkbenchWindowCloseIntent()");
    expect(pageHideBody).toContain("!desktopShell && !event.persisted && windowCloseIntent");
    expect(pageHideBody).toContain("requestWorkbenchWindowCloseOnPageHide(windowCloseIntent)");
  });
});
