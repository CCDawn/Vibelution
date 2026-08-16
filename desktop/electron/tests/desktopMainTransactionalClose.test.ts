import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));
const closeStoreSource = readFileSync(
  fileURLToPath(new URL("../src/lifecycle/workbenchCloseTransactionStore.ts", import.meta.url)),
  "utf8",
);

describe("Electron main transactional Workbench close", () => {
  it("advertises the Electron close capability instead of reusing only Launcher capabilities", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain('WORKBENCH_CLOSE_TRANSACTION_CAPABILITY = "workbench_close.transaction.v1"');
    expect(source).toContain("function desktopSessionCapabilities(bootstrap: LauncherBootstrapResult): string[]");
    expect(source).toContain("capabilities: desktopSessionCapabilities(bootstrap)");
  });

  it("owns the close transaction state machine in Electron main", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain('from "./lifecycle/workbenchCloseTransactionStore.js"');
    expect(source).toContain("const mainWorkbenchCloseStore = new MainWorkbenchCloseTransactionStore();");
    expect(source).toContain("shouldInterceptWorkbenchClose: () => !shutdownApproved");
    expect(source).toContain("requestTransactionalWorkbenchClose(paths, bootstrap)");
    expect(source).toContain("mainWorkbenchCloseStore.submit(");
    expect(source).toContain("mainWorkbenchCloseStore.confirm(");
    expect(source).toContain("mainWorkbenchCloseStore.backendStopped(");
    expect(source).toContain("await provider.approveWorkbenchCloseOnce()");
    expect(source).toContain("buttons: [\"重试\", \"仍关闭窗口\"]");
    const providerStart = source.indexOf("function createWindowProvider(");
    const providerEnd = source.indexOf("\nfunction createConversationBadgeIcon", providerStart);
    const providerSource = source.slice(providerStart, providerEnd);
    expect(providerSource).toContain("requestTransactionalWorkbenchClose(paths, bootstrap)");
    expect(providerSource).not.toContain('requestDesktopShellExit("workbench_window_close")');
    expect(closeStoreSource).toContain("confirmation_required");
    expect(closeStoreSource).toContain("window_close_authorized");
  });

  it("stops the backend through the Python lifecycle bridge before authorizing the window close", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("electron.workbench_close.backend_stopping");
    expect(source).toContain("stopWorkbenchBackend(paths, bootstrap)");
    expect(source).toContain("runWorkbenchLifecycle({");
    expect(source).toContain('operation: "stop"');
    expect(source).toContain('from "./lifecycle/workbenchBackendCloseReadiness.js"');
    expect(source).toContain("waitForWorkbenchBackendSettledForWindowClose({");
    expect(source).toContain("timeoutMs: WORKBENCH_CLOSE_BACKEND_WAIT_MS");
    expect(source).toContain("mainWorkbenchCloseStore.fail(");
    expect(source).toContain('"backend_stop_timeout"');
    expect(source).toContain("onWorkbenchClosed: () =>");
    expect(source).toContain("mainWorkbenchCloseStore.windowClosed(transaction.closeId)");
    expect(source).toContain("desktopSessionRevision");
  });

  it("opens the named Workbench only in canary mode and writes proof after the closed acknowledgement", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("desktopCliArgs.workbenchCloseCanary");
    expect(source).toContain("await windowProvider.openOrFocusWorkbench()");
    expect(source).toContain("function writeWorkbenchCloseCanarySummary(");
    expect(source).toContain("desktopWorkbenchCloseCanarySummaryPath(paths.workspaceRoot)");
    expect(source).toContain("desktopWorkbenchCloseCanarySummary({");
  });

  it("keeps the Python desktop action claim loop stopped after the T6 reversal", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("startDesktopActionLoop stays");
    expect(source).not.toMatch(
      /if \(desktopCliArgs\.workbenchCloseCanary\) \{\s*await windowProvider\.openOrFocusWorkbench\(\);\s*return;\s*\}\s*startDesktopActionLoop\(paths, launcherBootstrap, windowProvider\);/
    );
  });

  it("keeps the registered Launcher session intact while opening a desktop action", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const actionOpenStart = source.indexOf("async function openWorkbenchAtCurrentLauncherUrl(");
    const actionOpenEnd = source.indexOf("\nasync function reportManagedWindowState", actionOpenStart);
    const actionOpenSource = source.slice(actionOpenStart, actionOpenEnd);

    expect(actionOpenStart).toBeGreaterThanOrEqual(0);
    expect(actionOpenEnd).toBeGreaterThan(actionOpenStart);
    expect(actionOpenSource).not.toContain("bootstrapLauncherIfEnabled(paths)");
    expect(actionOpenSource).toContain("payloadUrl || bootstrap.workbenchUrl");
    expect(actionOpenSource).toContain("resolveWorkbenchUrl(desktopEnvironment(), payloadUrl || bootstrap.workbenchUrl)");
    expect(actionOpenSource).toContain("currentWorkbenchUrl = workbenchUrl;");
    expect(actionOpenSource).toContain("await provider.openOrFocusWorkbench(workbenchUrl)");
    expect(source).toContain("const workbenchUrl = currentWorkbenchUrl || resolveWorkbenchUrl(desktopEnv, launcherBootstrap?.workbenchUrl)");
    expect(source).toContain(
      "openOrFocusWorkbench: (payload) => openWorkbenchAtCurrentLauncherUrl(paths, bootstrap, provider, payload)"
    );
  });

  it("keeps the control context recovery helper for session heartbeat and workbench close", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("async function recoverWorkbenchCloseControlContext(");
    expect(source).toContain("await fetchLauncherControlToken({ launcherOrigin })");
    expect(source).toContain("context = await resolveDesktopActionLoopContext(bootstrap);");
    expect(source).toContain("runtimeSceneBridge = null;");
  });
});
