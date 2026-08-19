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
    expect(source).toContain("await startOrFocusWorkbenchFromProductEntryOnShell()");
    expect(source).not.toContain("await windowProvider.openOrFocusWorkbench()");
    expect(source).toContain("windowProvider?.openLauncher()");
    expect(source).not.toContain("void windowProvider?.openLauncher();");
  });

  it("pins a shared userData lock and focuses the existing shell on a bare second launch", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const pinIndex = source.indexOf("pinSharedDesktopShellUserData(app,");
    const lockIndex = source.indexOf("app.requestSingleInstanceLock()");

    expect(pinIndex).toBeGreaterThan(0);
    expect(lockIndex).toBeGreaterThan(pinIndex);
    expect(source).toContain('intent.action === "focus_existing_shell"');
    expect(source).toContain("focusExistingDesktopShell()");
  });

  it("recovers the desktop session before a second-instance Workbench open", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const helperIndex = source.indexOf("async function requestOpenWorkbenchFromSecondInstance()");
    const recoveryIndex = source.indexOf(
      'recoverDesktopControlContext(paths, bootstrap, provider, "second_instance_open_workbench")',
      helperIndex
    );
    const startOrFocusIndex = source.indexOf("await startOrFocusWorkbenchFromProductEntryOnShell()", helperIndex);

    expect(helperIndex).toBeGreaterThan(0);
    expect(recoveryIndex).toBeGreaterThan(helperIndex);
    expect(startOrFocusIndex).toBeGreaterThan(recoveryIndex);
    expect(source).toContain("void requestOpenWorkbenchFromSecondInstance().catch((error: unknown) => {");
  });

  it("treats a product-entry open as start-or-focus instead of a window-only open", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const openIndex = source.indexOf('if (firstLifecycle === "open")');
    const openBlock = source.slice(openIndex, source.indexOf("} else {", openIndex));

    expect(openIndex).toBeGreaterThan(0);
    expect(openBlock).toContain("startOrFocusWorkbenchFromProductEntryOnShell()");
    expect(openBlock).not.toContain("await windowProvider.openOrFocusWorkbench()");
    expect(source).toContain('orchestrateLauncherLifecycle("start", { schemaVersion: 1, path: "open" })');
  });

  it("opens the Launcher window on a bare first launch and resolves the workbench URL without python", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("await windowProvider.openLauncher()");
    expect(source).toContain('else if (!desktopCliArgs.workbenchCloseCanary && !desktopCliArgs.projectRoot)');
    expect(source).toContain("bootstrapMainOwnedLauncher(paths)");
    expect(source).toContain("resolveWorkbenchUrl(desktopEnv, workbenchUrl || undefined)");
    expect(source).not.toContain("bootstrapPythonLauncherService(");
  });
});
