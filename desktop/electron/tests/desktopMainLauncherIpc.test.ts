import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
const preloadSource = readFileSync(fileURLToPath(new URL("../src/preload.ts", import.meta.url)), "utf8");
const launcherWindowSource = readFileSync(
  fileURLToPath(new URL("../src/windows/launcherWindow.ts", import.meta.url)),
  "utf8",
);

describe("Electron main Launcher IPC facade", () => {
  it("registers a control-window-only launcher invoke handler", () => {
    expect(mainSource).toContain("IPC_CHANNELS.launcherInvoke");
    expect(mainSource).toContain("from \"./protocol/launcherIpcHost.js\"");
    expect(mainSource).toContain("resolveLauncherIpcHost()");
  });

  it("validates the launcher invoke sender against the Launcher control origin only", () => {
    const invokeStart = mainSource.indexOf("IPC_CHANNELS.launcherInvoke");
    const invokeEnd = mainSource.indexOf("});", invokeStart);
    const handlerSource = mainSource.slice(invokeStart, invokeEnd);
    expect(handlerSource).toContain("assertTrustedIpcSender");
    expect(handlerSource).not.toContain("trustedIpcOrigins()");
    expect(mainSource).toContain("launcherIpcTrustedOrigins()");
    const trustedStart = mainSource.indexOf("function launcherIpcTrustedOrigins");
    const trustedEnd = mainSource.indexOf("}", trustedStart);
    expect(mainSource.slice(trustedStart, trustedEnd)).toContain("resolveLauncherWindowUrl");
  });

  it("keeps the workbench sender away from Launcher control IPC", () => {
    expect(launcherWindowSource).toContain('"--vibelution-window-role=launcher-control"');
    expect(preloadSource).toContain('process.argv.includes("--vibelution-window-role=launcher-control")');
    expect(preloadSource).toContain("launcherInvoke");
    expect(launcherWindowSource).toContain('additionalArguments: ["--vibelution-window-role=launcher-control"]');
    expect(mainSource).toContain("launcherIpcTrustedOrigins");
  });

  it("does not require a workbench control token before serving launcher status", () => {
    const hostSource = readFileSync(fileURLToPath(new URL("../src/protocol/launcherIpcHost.ts", import.meta.url)), "utf8");
    const invokeStart = hostSource.indexOf("async invoke(");
    const contextStart = hostSource.indexOf("await input.resolveContext()", invokeStart);
    const statusApi = hostSource.indexOf('"status"', hostSource.indexOf("const LAUNCHER_API_PATHS"));
    expect(statusApi).toBeGreaterThan(0);
    expect(statusApi).toBeLessThan(contextStart);
    expect(mainSource).toContain("createLocalLauncherStatusSnapshot");
    expect(mainSource).toContain("resolveLocalStatus");
    expect(mainSource).toContain("scheduleStatusRefresh");
  });

  it("opens the current workbench window after start even without an isolated port", () => {
    expect(mainSource).toContain("openOrchestratedWorkbenchWindow");
    expect(mainSource).toContain("isCurrentCheckoutInstance(instanceId)");
    expect(mainSource).toContain("provider.openOrFocusWorkbench(url)");
    const branchStart = mainSource.indexOf("async function orchestrateBranchInstanceLifecycle");
    const branchBody = mainSource.slice(branchStart, branchStart + 1800);
    expect(branchBody).toContain('operation === "start" || operation === "restart"');
    expect(branchBody).toContain("isCurrentCheckoutInstance(instanceId) || (result.port && result.port > 0)");
  });

  it("closes Electron workbench windows on stop instead of waiting for Python to own them", () => {
    expect(mainSource).toContain("closeOrchestratedWorkbenchWindow");
    expect(mainSource).toContain("approveWorkbenchCloseOnce");
    const lifecycleStart = mainSource.indexOf("async function orchestrateLauncherLifecycle");
    const lifecycleBody = mainSource.slice(lifecycleStart, mainSource.indexOf("async function orchestrateBranchInstanceLifecycle"));
    expect(lifecycleBody).toContain('operation === "stop" || operation === "force-stop"');
    expect(lifecycleBody).toContain("approveWorkbenchCloseOnce");
  });
});
