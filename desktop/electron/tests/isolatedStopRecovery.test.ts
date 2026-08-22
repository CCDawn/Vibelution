import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
const registryHostSource = readFileSync(
  fileURLToPath(new URL("../src/lifecycle/isolatedInstanceRegistryHost.ts", import.meta.url)),
  "utf8"
);

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
    expect(body).toContain("retireClaimedIsolatedRuntime");
    expect(body).not.toContain("completeIsolatedStop");

    const retireStart = registryHostSource.indexOf("export async function retireClaimedIsolatedRuntime");
    const retireEnd = registryHostSource.indexOf("\nexport async function claimIsolatedStop", retireStart);
    const retireBody = registryHostSource.slice(retireStart, retireEnd);
    expect(retireBody).toContain("dependencies.reclaimBackend");
    expect(retireBody).toContain("dependencies.clearRuntimeState");
    expect(retireBody).toContain("dependencies.completeStop");
    expect(retireBody).toContain("settleFailed");

    const stopReturnStart = body.indexOf('if (input.operation === "stop" || input.operation === "force-stop")');
    const stopReturn = body.slice(stopReturnStart);
    expect(stopReturn).toContain("const stopCommandId = randomUUID()");
    expect(stopReturn).toContain("const commandId = String(claimed.entry.commandId || stopCommandId)");
    expect(stopReturn).toContain("      commandId,");
    expect(stopReturn).toContain("backend_retire_incomplete");
    expect(stopReturn).toContain('desiredStateOnFailure: "closed"');
  });

  it("admits once before retiring and claiming a new isolated start", () => {
    const prepareStart = registryHostSource.indexOf("export async function prepareIsolatedStart");
    const prepareEnd = registryHostSource.indexOf("\nfunction normalizedStatus", prepareStart);
    const prepareBody = registryHostSource.slice(prepareStart, prepareEnd);
    expect(prepareBody.indexOf("assertLifecycleAdmitted({")).toBeGreaterThan(-1);
    expect(prepareBody.indexOf("assertLifecycleAdmitted({")).toBeLessThan(
      prepareBody.indexOf("retireIsolatedRuntimeBeforeStart({")
    );
    expect(prepareBody.indexOf("retireIsolatedRuntimeBeforeStart({")).toBeLessThan(
      prepareBody.indexOf("claimResolvedIsolatedStart")
    );

    const mutationStart = mainSource.indexOf("async function runIsolatedRegistryMutation");
    const mutationEnd = mainSource.indexOf("\nasync function orchestrateBranchInstanceLifecycle", mutationStart);
    const body = mainSource.slice(mutationStart, mutationEnd);
    expect(body).toContain("const claimed = await prepareIsolatedStart({");
    expect(body).not.toContain("claimIsolatedStart({");
  });

  it("passes a backend retirement compensation callback to isolated start supervision", () => {
    const orchestrationStart = mainSource.indexOf("async function orchestrateBranchInstanceLifecycle");
    const orchestrationBody = mainSource.slice(orchestrationStart);
    expect(orchestrationBody).toContain("retireBackend: async (message)");
    expect(orchestrationBody).toContain("retireIsolatedBackendAfterStartFailure");
    expect(orchestrationBody).toContain("if (!observed.applied)");
  });

  it("claims the failed start generation before killing its spawned child", () => {
    const compensationStart = mainSource.indexOf("async function retireIsolatedBackendAfterStartFailure");
    const compensationEnd = mainSource.indexOf("\nasync function runIsolatedRegistryMutation", compensationStart);
    const compensationBody = mainSource.slice(compensationStart, compensationEnd);
    expect(compensationBody.indexOf("claimStopIfGeneration")).toBeGreaterThan(-1);
    expect(compensationBody.indexOf("claimStopIfGeneration")).toBeLessThan(
      compensationBody.indexOf("input.beforeRetire?.()")
    );

    const mutationStart = mainSource.indexOf("async function runIsolatedRegistryMutation");
    const mutationEnd = mainSource.indexOf("\nasync function orchestrateBranchInstanceLifecycle", mutationStart);
    const mutationBody = mainSource.slice(mutationStart, mutationEnd);
    const healthCatch = mutationBody.slice(mutationBody.indexOf("} catch (error: unknown) {"));
    expect(healthCatch).toContain("retireIsolatedBackendAfterStartFailure");
    expect(healthCatch).toContain("beforeRetire: () =>");
    expect(healthCatch).toContain("spawned.child.kill();");
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
