import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

describe("isolated lifecycle recovery", () => {
  it("returns a command id for already-alive starts so the window supervisor can open it", () => {
    const marker = 'message: "已打开该分支工作台窗口。"';
    const markerStart = mainSource.indexOf(marker);
    expect(markerStart).toBeGreaterThan(0);
    const resultBlock = mainSource.slice(Math.max(0, markerStart - 320), markerStart + marker.length);
    expect(resultBlock).toContain("commandId: randomUUID()");
  });

  it("uses health-identity reclaim and runtime cleanup before completing isolated stop", () => {
    const functionStart = mainSource.indexOf("async function runIsolatedRegistryMutation");
    const functionEnd = mainSource.indexOf("\nasync function orchestrateBranchInstanceLifecycle", functionStart);
    expect(functionStart).toBeGreaterThan(0);
    expect(functionEnd).toBeGreaterThan(functionStart);
    const body = mainSource.slice(functionStart, functionEnd);
    expect(body).toContain("reclaimStaleWorkbenchBackend");
    expect(body).toContain("clearWorkbenchLauncherRuntimeState");
    expect(body).not.toContain("retireRegisteredHandles");

    const stopReturnStart = body.indexOf('if (input.operation === "stop" || input.operation === "force-stop")');
    const stopReturn = body.slice(stopReturnStart);
    expect(stopReturn).toContain("const stopCommandId = randomUUID()");
    expect(stopReturn).toContain("const commandId = String(claimed.entry.commandId || stopCommandId)");
    expect(stopReturn).toContain("      commandId,");
    expect(stopReturn).toContain("backend_retire_incomplete");
    expect(stopReturn).toContain("knownPidIsAlive");
    expect(stopReturn).toContain("registeredPids");
    expect(stopReturn).toContain("registeredSpawnPidAlive");
    expect(stopReturn).toContain("backendConfirmedClosed");
  });

  it("awaits isolated window close after a successful stop result", () => {
    const closeStart = mainSource.indexOf("async function closeOrchestratedWorkbenchWindow");
    const closeEnd = mainSource.indexOf("\nasync function closeWindowIfSupersededByClosedIntent", closeStart);
    expect(mainSource.slice(closeStart, closeEnd)).toContain("await provider.closeInstanceWorkbench(instanceId)");
    const branchStart = mainSource.indexOf("async function orchestrateBranchInstanceLifecycle");
    const stopGate = mainSource.indexOf('desiredState === "closed"', branchStart);
    expect(mainSource.slice(stopGate, stopGate + 320)).toContain("await closeOrchestratedWorkbenchWindow(instanceId)");
  });

  it("reclaims expired stopping rows through the TS registry writer before refresh", () => {
    const schedulerStart = mainSource.indexOf("const reconcileDeadlineScheduler =");
    const schedulerEnd = mainSource.indexOf("launcherStateStore.subscribe", schedulerStart);
    const schedulerBody = mainSource.slice(schedulerStart, schedulerEnd);
    expect(schedulerBody).toContain("reclaimExpiredIsolatedStops");
    expect(schedulerBody.indexOf("reclaimExpiredIsolatedStops")).toBeLessThan(
      schedulerBody.indexOf('launcherStateStore.refresh("reconcile_deadline")')
    );

    const reclaimStart = mainSource.indexOf("async function reclaimExpiredIsolatedStops");
    const reclaimEnd = mainSource.indexOf("\nfunction scheduleLauncherStatusCliRefresh", reclaimStart);
    const reclaimBody = mainSource.slice(reclaimStart, reclaimEnd);
    expect(reclaimBody).toContain("reclaimStaleInFlightStops");
    expect(reclaimBody).toContain("instancesRegistryPath()");
    expect(reclaimBody).not.toContain("launcherStateStore.snapshot()");

    const userRecheck = mainSource.slice(mainSource.indexOf("ipcMain.handle(IPC_CHANNELS.refreshLauncherState"));
    expect(userRecheck).toContain("await reclaimExpiredIsolatedStops();");
  });
});
