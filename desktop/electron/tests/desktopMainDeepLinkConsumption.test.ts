import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));

describe("Electron main public deep-link consumption", () => {
  it("routes second-instance protocol URLs through the public deep-link handler", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("findVibelutionDeepLinkArg(argv)");
    expect(source).toContain('handlePublicDeepLinkUrl(intent.rawUrl, "second_instance")');
    expect(source).toContain('handlePublicDeepLinkUrl(rawUrl, "open_url")');
    expect(source).toContain("parsePublicVibelutionDeepLink(rawUrl)");
    expect(source).not.toContain("parseVibelutionDeepLink(rawUrl)");
  });

  it("routes only an explicit second-instance CLI intent to the Workbench", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("let pendingOpenWorkbenchRequest = desktopCliArgs.openWorkbench");
    expect(source).toContain("const secondCli = parseDesktopCliArgs(argv)");
    expect(source).toContain("resolveSecondInstanceIntent({");
    expect(source).toContain("applyPendingProjectSlot(intent.projectRoot)");
    expect(source).toContain("secondCli.openWorkbench");
    expect(source).toContain("await windowProvider.openOrFocusWorkbench()");
    expect(source).toContain("windowProvider?.openLauncher()");
    expect(source).not.toContain("void windowProvider?.openLauncher();");
  });

  it("pins a shared userData lock and focuses the existing shell on a bare second launch", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const pinIndex = source.indexOf("pinSharedDesktopShellUserData(app, { smoke: desktopCliArgs.smoke, env: process.env })");
    const lockIndex = source.indexOf("app.requestSingleInstanceLock()");

    expect(pinIndex).toBeGreaterThan(0);
    expect(lockIndex).toBeGreaterThan(pinIndex);
    expect(source).toContain('intent.action === "focus_existing_shell"');
    expect(source).toContain("focusExistingDesktopShell()");
  });
});
