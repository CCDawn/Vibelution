import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { createSourceFile, isFunctionDeclaration, ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi } from "vitest";
import { executeLauncherUpdate, projectLauncherUpdateFreshness, retainKnownDesktopShell, type LauncherUpdateProgress } from "../src/process/launcherUpdate.js";
import { decidePackagedDesktopShellRefresh, type DesktopShellStatus } from "../src/process/desktopShellFreshness.js";
import { createLauncherFreshnessObservation } from "../src/process/launcherFreshnessObservation.js";
import { parseBranchInstanceRecords } from "../src/protocol/launcherControlClient.js";
import { combineAssistantActiveWork } from "../src/assistant/lifecycleGuard.js";
import { activeWorkStatusFromLauncherStatus, type ActiveWorkStatus } from "../src/shutdown/shutdownCoordinator.js";

function updateInputs(state: ActiveWorkStatus = { state: "idle", message: "" }) {
  return {
    activeWork: vi.fn().mockResolvedValue(state),
    prepare: vi.fn().mockResolvedValue({}),
    stopWorkspaces: vi.fn().mockResolvedValue(undefined),
    scheduleReplacement: vi.fn().mockResolvedValue(undefined),
  };
}

function desktopExitHelper(mainSource: string): string {
  const source = createSourceFile("main.ts", mainSource, ScriptTarget.ES2022, true);
  const helper = source.statements.find(statement => isFunctionDeclaration(statement)
    && statement.name?.text === "exitDesktopShellProcess");
  if (!helper) throw new Error("main.ts is missing exitDesktopShellProcess");
  return helper.getText(source);
}

describe("guarded local Launcher update", () => {
  it("reports native phases at the real asynchronous boundaries", async () => {
    const input = updateInputs();
    const phases: string[] = [];
    let prepared!: () => void;
    input.prepare.mockImplementation(() => new Promise<void>((resolve) => { prepared = resolve; }));
    const updating = executeLauncherUpdate({ ...input, onPhase: (phase) => phases.push(phase) });
    await vi.waitFor(() => expect(phases).toEqual(["checking", "preparing"]));
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
    prepared();
    expect(await updating).toMatchObject({ accepted: true });
    expect(phases).toEqual(["checking", "preparing", "saving", "replacing"]);
  });

  it("does not report replacement after task saving fails", async () => {
    const input = updateInputs();
    const phases: string[] = [];
    input.stopWorkspaces.mockRejectedValue(new Error("save failed"));
    await expect(executeLauncherUpdate({ ...input, onPhase: (phase) => phases.push(phase) })).rejects.toThrow("save failed");
    expect(phases).toEqual(["checking", "preparing", "saving"]);
    expect(input.scheduleReplacement).not.toHaveBeenCalled();
  });

  it("keeps progress observers outside update admission", async () => {
    const input = updateInputs();
    expect(await executeLauncherUpdate({ ...input, onPhase: () => { throw new Error("observer failed"); } })).toMatchObject({ accepted: true });
    expect(input.scheduleReplacement).toHaveBeenCalledOnce();
  });
  // Parse/transpile the large main module once during collection. The tests
  // below measure controlled shutdown promises, not a cold TypeScript JIT.
  const automaticMain = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
  const automaticRefresh = automaticMain.slice(automaticMain.indexOf("async function refreshPackagedDesktopShellIfStale("), automaticMain.indexOf("async function runSmokeAndQuit("));
  const automaticRestart = automaticMain.slice(automaticMain.indexOf("async function restartLauncherToLatestBuild("), automaticMain.indexOf("async function resolveLauncherUpdateActiveWork("));
  const automaticCode = transpileModule(desktopExitHelper(automaticMain) + automaticRefresh + automaticRestart
    + "\nglobalThis.refresh = refreshPackagedDesktopShellIfStale;\nglobalThis.restartLatest = restartLauncherToLatestBuild;\nglobalThis.exitDesktop = exitDesktopShellProcess;", {
    compilerOptions: { target: ScriptTarget.ES2022 },
  }).outputText;
  function automaticRefreshHarness() {
    const sandbox = {
      app: { isPackaged: true, exit: vi.fn() },
      desktopCliArgs: {}, shellRefreshInFlight: false, shellRefreshRequest: null, shutdownApproved: false,
      launcherUpdateProgress: null as LauncherUpdateProgress | null,
      decidePackagedDesktopShellRefresh,
      inspectCurrentDesktopShellLaunchReadiness: vi.fn().mockResolvedValue({ launchBlocking: true }),
      inspectCurrentDesktopShell: vi.fn().mockResolvedValue({ stale: true, launchBlocking: true }),
      notifyDesktopTray: vi.fn(), executeLauncherUpdate,
      resolveLauncherUpdateActiveWork: vi.fn().mockResolvedValue({ state: "idle", message: "" }),
      acquireResidentAssistantShutdownGuard: vi.fn().mockResolvedValue({ release: vi.fn().mockResolvedValue(undefined) }),
      ensureLatestLauncher: vi.fn().mockResolvedValue({}),
      createDesktopPathsForApp: () => ({ workspaceRoot: "test-workspace" }),
      desktopPythonPath: () => "pythonw.exe",
      stopMainRuntimeForApprovedShutdown: vi.fn().mockResolvedValue(undefined),
      stopIsolatedInstancesForApprovedShutdown: vi.fn().mockResolvedValue(undefined),
      stopLauncherAssistant: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
      scheduleCurrentDesktopShellRefresh: vi.fn().mockResolvedValue(undefined),
      // Exiting is simulated; no real windows or child processes are touched.
      setTimeout: (callback: () => void) => { callback(); },
      refresh: undefined as unknown as (operation: string) => Promise<boolean>,
      restartLatest: undefined as unknown as (interrupt?: boolean, operation?: string, options?: { shellKind?: "packaged" | "unpackaged";
        launchRequest?: { launchRequestId: string; launchRequestOperation: string; receipt: { handoff(operation: string): void } } }) => Promise<unknown>,
      exitDesktop: undefined as unknown as () => Promise<void>,
    };
    Object.assign(sandbox, {
      bestEffortStopIsolatedInstancesForShutdown: sandbox.stopIsolatedInstancesForApprovedShutdown,
      stopManagedRuntime: sandbox.stopMainRuntimeForApprovedShutdown,
    });
    runInNewContext(automaticCode, sandbox);
    return sandbox;
  }

  it("waits for the assistant to drain before exiting the desktop process", async () => {
    const input = automaticRefreshHarness();
    let completeDrain!: () => void;
    input.stopLauncherAssistant.mockImplementation(() => new Promise<void>(resolve => { completeDrain = resolve; }));

    const exiting = input.exitDesktop();
    expect(input.stopLauncherAssistant).toHaveBeenCalledOnce();
    expect(input.app.exit).not.toHaveBeenCalled();
    completeDrain();
    await exiting;
    expect(input.app.exit).toHaveBeenCalledExactlyOnceWith(0);
    expect(input.stopLauncherAssistant.mock.invocationCallOrder[0])
      .toBeLessThan(input.app.exit.mock.invocationCallOrder[0]);
  });

  it("keeps the desktop process alive when the assistant cannot drain", async () => {
    const input = automaticRefreshHarness();
    input.stopLauncherAssistant.mockRejectedValue(new Error("ASSISTANT_DRAIN_TIMEOUT"));

    await expect(input.exitDesktop()).rejects.toThrow("ASSISTANT_DRAIN_TIMEOUT");
    expect(input.app.exit).not.toHaveBeenCalled();
  });

  it("opens a launch-ready shell without waiting for full frontend freshness", async () => {
    const input = automaticRefreshHarness();
    input.inspectCurrentDesktopShellLaunchReadiness.mockResolvedValue({ launchBlocking: false });
    // A full source scan that never settles must not hold up first launch.
    input.inspectCurrentDesktopShell.mockImplementation(() => new Promise(() => {}));

    expect(await input.refresh("start")).toBe(false);
    expect(input.inspectCurrentDesktopShellLaunchReadiness).toHaveBeenCalledOnce();
    expect(input.inspectCurrentDesktopShell).not.toHaveBeenCalled();
    expect(input.ensureLatestLauncher).not.toHaveBeenCalled();
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(input.app.exit).not.toHaveBeenCalled();
  });

  it.each(["readiness", "full status"])("retains the current shell when %s inspection fails", async (probe) => {
    const input = automaticRefreshHarness();
    const inspect = probe === "readiness" ? input.inspectCurrentDesktopShellLaunchReadiness : input.inspectCurrentDesktopShell;
    inspect.mockRejectedValue(new Error("inspection unavailable"));

    expect(await input.refresh("start")).toBe(false);
    expect(input.ensureLatestLauncher).not.toHaveBeenCalled();
    expect(input.stopMainRuntimeForApprovedShutdown).not.toHaveBeenCalled();
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(input.app.exit).not.toHaveBeenCalled();
    expect(input.notifyDesktopTray).toHaveBeenCalled();
  });

  it("keeps the shell when a launch blocker clears during the full status probe", async () => {
    const input = automaticRefreshHarness();
    input.inspectCurrentDesktopShell.mockResolvedValue({ stale: true, launchBlocking: false });

    expect(await input.refresh("start")).toBe(false);
    expect(input.inspectCurrentDesktopShell).toHaveBeenCalledOnce();
    expect(input.ensureLatestLauncher).not.toHaveBeenCalled();
    expect(input.stopMainRuntimeForApprovedShutdown).not.toHaveBeenCalled();
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(input.app.exit).not.toHaveBeenCalled();
  });

  it.each(["active", "unknown"] as const)("keeps the automatic refresh idle when tasks are %s", async (state) => {
    const input = automaticRefreshHarness();
    input.resolveLauncherUpdateActiveWork.mockResolvedValue({ state, message: "" });
    expect(await input.refresh("")).toBe(false);
    expect(input.ensureLatestLauncher).not.toHaveBeenCalled();
    expect(input.stopMainRuntimeForApprovedShutdown).not.toHaveBeenCalled();
    expect(input.stopIsolatedInstancesForApprovedShutdown).not.toHaveBeenCalled();
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(input.app.exit).not.toHaveBeenCalled();
    expect(input.shellRefreshInFlight).toBe(false);
    expect(input.shutdownApproved).toBe(false);
  });

  it("defers automatic refresh when work starts during preparation", async () => {
    const input = automaticRefreshHarness();
    input.resolveLauncherUpdateActiveWork.mockResolvedValueOnce({ state: "idle", message: "" })
      .mockResolvedValueOnce({ state: "active", message: "" });
    expect(await input.refresh("")).toBe(false);
    expect(input.ensureLatestLauncher).toHaveBeenCalledOnce();
    expect(input.stopMainRuntimeForApprovedShutdown).not.toHaveBeenCalled();
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(input.app.exit).not.toHaveBeenCalled();
  });

  it("does not stop or replace when native admission becomes busy after preparation", async () => {
    const input = automaticRefreshHarness();
    input.acquireResidentAssistantShutdownGuard.mockRejectedValue(new Error("ASSISTANT_LIFECYCLE_BUSY"));
    expect(await input.refresh("")).toBe(false);
    expect(input.ensureLatestLauncher).toHaveBeenCalledOnce();
    expect(input.stopMainRuntimeForApprovedShutdown).not.toHaveBeenCalled();
    expect(input.stopIsolatedInstancesForApprovedShutdown).not.toHaveBeenCalled();
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(input.stopLauncherAssistant).not.toHaveBeenCalled();
    expect(input.app.exit).not.toHaveBeenCalled();
  });

  it("releases the captured native guard when a workspace stop fails", async () => {
    const input = automaticRefreshHarness();
    const release = vi.fn().mockResolvedValue(undefined);
    input.acquireResidentAssistantShutdownGuard.mockResolvedValue({ release });
    input.stopMainRuntimeForApprovedShutdown.mockRejectedValue(new Error("stop refused"));
    expect(await input.refresh("")).toBe(false);
    expect(release).toHaveBeenCalledOnce();
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
  });

  it("vetoes replacement when a new native request arrives while workspaces stop", async () => {
    const input = automaticRefreshHarness();
    const release = vi.fn().mockResolvedValue(undefined);
    const commit = vi.fn(() => { throw new Error("ASSISTANT_LIFECYCLE_BUSY"); });
    input.acquireResidentAssistantShutdownGuard.mockResolvedValue({ release, commit });
    expect(await input.refresh("")).toBe(false);
    expect(input.stopMainRuntimeForApprovedShutdown).toHaveBeenCalledOnce();
    expect(release).toHaveBeenCalledOnce();
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(input.app.exit).not.toHaveBeenCalled();
  });

  it("allows a later explicit update while the failed automatic guard is reconciling release", async () => {
    const input = automaticRefreshHarness();
    const release = vi.fn(() => new Promise<void>(() => undefined));
    input.acquireResidentAssistantShutdownGuard.mockResolvedValue({ release });
    input.stopMainRuntimeForApprovedShutdown.mockRejectedValueOnce(new Error("stop refused"));
    expect(await input.refresh("")).toBe(false);
    expect(await input.restartLatest()).toMatchObject({ accepted: true });
    expect(input.scheduleCurrentDesktopShellRefresh).toHaveBeenCalledOnce();
  });

  it.each(["main", "isolated"])("retains the shell if the %s runtime refuses automatic shutdown", async (target) => {
    const input = automaticRefreshHarness();
    const stop = target === "main" ? input.stopMainRuntimeForApprovedShutdown : input.stopIsolatedInstancesForApprovedShutdown;
    stop.mockRejectedValue(new Error("stop refused"));
    expect(await input.refresh("")).toBe(false);
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(input.app.exit).not.toHaveBeenCalled();
    expect(input.shellRefreshInFlight).toBe(false);
    expect(input.shutdownApproved).toBe(false);
  });

  it("only schedules and exits automatic refresh after both non-interrupting stops", async () => {
    const input = automaticRefreshHarness();
    expect(await input.refresh("open")).toBe(true);
    expect(input.inspectCurrentDesktopShellLaunchReadiness.mock.invocationCallOrder[0])
      .toBeLessThan(input.inspectCurrentDesktopShell.mock.invocationCallOrder[0]);
    expect(input.inspectCurrentDesktopShell.mock.invocationCallOrder[0])
      .toBeLessThan(input.ensureLatestLauncher.mock.invocationCallOrder[0]);
    expect(input.stopMainRuntimeForApprovedShutdown).toHaveBeenCalledWith(false);
    expect(input.stopIsolatedInstancesForApprovedShutdown).toHaveBeenCalledWith(false);
    expect(input.stopIsolatedInstancesForApprovedShutdown.mock.invocationCallOrder[0])
      .toBeLessThan(input.scheduleCurrentDesktopShellRefresh.mock.invocationCallOrder[0]);
    // The automatic path must not force: force clears the refresh cooldown,
    // which would let a repeatedly failing rebuild keep re-stopping the shell.
    expect(input.scheduleCurrentDesktopShellRefresh).toHaveBeenCalledWith("open", { force: false, shellKind: "packaged" });
    expect(input.stopLauncherAssistant).toHaveBeenCalledOnce();
    expect(input.scheduleCurrentDesktopShellRefresh.mock.invocationCallOrder[0])
      .toBeLessThan(input.stopLauncherAssistant.mock.invocationCallOrder[0]);
    expect(input.stopLauncherAssistant.mock.invocationCallOrder[0])
      .toBeLessThan(input.app.exit.mock.invocationCallOrder[0]);
    expect(input.app.exit).toHaveBeenCalledOnce();
    expect(input.shutdownApproved).toBe(true);
    const main = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
    const watch = main.slice(main.indexOf("function startPeriodicShellFreshnessWatch("), main.indexOf("async function runTrayBranchInstance("));
    expect(watch).toContain('refreshPackagedDesktopShellIfStale("start")');
    // The shared transaction owns this flag, including rejected overlapping probes.
    expect(watch).not.toContain("shellRefreshInFlight =");
  });

  it("rejects the automatic refresh before stopping while the refresh cooldown is active", async () => {
    const input = automaticRefreshHarness();
    input.inspectCurrentDesktopShell.mockResolvedValue({
      stale: true,
      launchBlocking: true,
      refreshBlocked: true,
      refreshBlockedReason: "rebuild_failed",
      refreshBlockedDetail: "still stale after rebuild: frontend_source_mismatch"
    });
    expect(await input.refresh("start")).toBe(false);
    // Cooldown rejection must land before the transaction stops anything.
    expect(input.ensureLatestLauncher).not.toHaveBeenCalled();
    expect(input.stopMainRuntimeForApprovedShutdown).not.toHaveBeenCalled();
    expect(input.stopIsolatedInstancesForApprovedShutdown).not.toHaveBeenCalled();
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(input.app.exit).not.toHaveBeenCalled();
    expect(input.notifyDesktopTray).toHaveBeenCalled();
  });

  it("lets an explicit operator update keep bypassing the refresh cooldown", async () => {
    const input = automaticRefreshHarness();
    await input.restartLatest();
    // restart-latest-shell is the user-clicked update entry: it still forces
    // so the Python scheduler clears any cooldown marker before scheduling.
    expect(input.scheduleCurrentDesktopShellRefresh).toHaveBeenCalledWith("open", { force: true, shellKind: "packaged" });
    expect(input.stopMainRuntimeForApprovedShutdown).toHaveBeenCalledWith(true);
    expect(input.stopLauncherAssistant).toHaveBeenCalledOnce();
    await vi.waitFor(() => expect(input.app.exit).toHaveBeenCalledOnce());
  });

  it("shares a live automatic refresh with a concurrent operator click without caching acceptance", async () => {
    const input = automaticRefreshHarness();
    let finishPreparation!: () => void;
    input.ensureLatestLauncher.mockImplementation(() => new Promise<void>(resolve => { finishPreparation = resolve; }));
    input.setTimeout = vi.fn(); // Keep the shell alive in the accepted handoff gap.
    const automatic = input.refresh("start");
    await vi.waitFor(() => expect(input.ensureLatestLauncher).toHaveBeenCalledOnce());
    const operator = input.restartLatest();
    finishPreparation();
    expect(await automatic).toBe(true);
    expect(await operator).toMatchObject({ accepted: true });
    expect(await input.restartLatest()).toMatchObject({ accepted: false });
    expect(input.ensureLatestLauncher).toHaveBeenCalledOnce();
    expect(input.stopMainRuntimeForApprovedShutdown).toHaveBeenCalledOnce();
    expect(input.scheduleCurrentDesktopShellRefresh).toHaveBeenCalledOnce();
    expect(input.setTimeout).toHaveBeenCalledOnce();
  });

  it("shares preparation failures and permits a fresh operator retry", async () => {
    const input = automaticRefreshHarness();
    let failPreparation!: (reason: Error) => void;
    input.ensureLatestLauncher.mockImplementationOnce(() => new Promise<void>((_resolve, reject) => { failPreparation = reject; }));
    const automatic = input.refresh("start");
    await vi.waitFor(() => expect(input.ensureLatestLauncher).toHaveBeenCalledOnce());
    const operator = expect(input.restartLatest()).rejects.toThrow("package failed");
    failPreparation(new Error("package failed"));
    expect(await automatic).toBe(false);
    await operator;
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(await input.restartLatest()).toMatchObject({ accepted: true });
    expect(input.ensureLatestLauncher).toHaveBeenCalledTimes(2);
    expect(input.scheduleCurrentDesktopShellRefresh).toHaveBeenCalledOnce();
  });

  it("carries the original request through the helper without claiming READY on schedule", async () => {
    const input = automaticRefreshHarness();
    const launchRequest = { launchRequestId: "launch_" + "a".repeat(32), launchRequestOperation: "restart",
      receipt: { handoff: vi.fn() } };
    expect(await input.restartLatest(true, "start", { shellKind: "packaged", launchRequest })).toMatchObject({ accepted: true });
    expect(launchRequest.receipt.handoff).toHaveBeenCalledExactlyOnceWith("start");
    expect(input.scheduleCurrentDesktopShellRefresh).toHaveBeenCalledExactlyOnceWith("start", {
      force: true, shellKind: "packaged", launchRequest
    });
  });

  it.each(["write", "rename"])("keeps the original shell when durable handoff %s fails", async stage => {
    const input = automaticRefreshHarness();
    const launchRequest = { launchRequestId: "launch_" + "c".repeat(32), launchRequestOperation: "restart",
      receipt: { handoff: vi.fn(() => { throw new Error(`LAUNCH_REQUEST_RECEIPT_PERSISTENCE_FAILED: handoff ${stage}`); }) } };
    await expect(input.restartLatest(true, "restart", { shellKind: "packaged", launchRequest }))
      .rejects.toThrow("LAUNCH_REQUEST_RECEIPT_PERSISTENCE_FAILED");
    expect(input.scheduleCurrentDesktopShellRefresh).not.toHaveBeenCalled();
    expect(input.app.exit).not.toHaveBeenCalled();
    expect(input.shutdownApproved).toBe(false);
    expect(input.shellRefreshInFlight).toBe(false);
  });

  it("does not attach an independent identified restart to an existing update", async () => {
    const input = automaticRefreshHarness(); let finish!: () => void;
    input.ensureLatestLauncher.mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
    const first = input.restartLatest(true, "restart");
    await vi.waitFor(() => expect(input.ensureLatestLauncher).toHaveBeenCalledOnce());
    const receipt = { handoff: vi.fn() };
    expect(await input.restartLatest(true, "restart", { launchRequest: {
      launchRequestId: "launch_" + "b".repeat(32), launchRequestOperation: "restart", receipt
    } })).toMatchObject({ accepted: false, code: "launcher_update_in_progress" });
    expect(receipt.handoff).not.toHaveBeenCalled();
    finish(); await first;
  });

  it.each([
    ["start", { shellKind: "packaged" as const }],
    ["rebuild-and-start", { shellKind: "packaged" as const }],
    ["open", { shellKind: "unpackaged" as const }],
  ])("does not acknowledge a different lifecycle or shell intent: %s", async (operation, options) => {
    const input = automaticRefreshHarness();
    let finishPreparation!: () => void;
    input.ensureLatestLauncher.mockImplementation(() => new Promise<void>(resolve => { finishPreparation = resolve; }));
    const first = input.restartLatest(true, "open", { shellKind: "packaged" });
    await vi.waitFor(() => expect(input.ensureLatestLauncher).toHaveBeenCalledOnce());
    expect(await input.restartLatest(true, operation, options)).toMatchObject({ accepted: false });
    finishPreparation();
    expect(await first).toMatchObject({ accepted: true });
    expect(input.scheduleCurrentDesktopShellRefresh).toHaveBeenCalledExactlyOnceWith("open", { force: true, shellKind: "packaged" });
  });

  it("does not replay old acceptance if the scheduled exit cannot drain the assistant", async () => {
    const input = automaticRefreshHarness();
    input.stopLauncherAssistant.mockRejectedValue(new Error("ASSISTANT_DRAIN_TIMEOUT"));
    expect(await input.restartLatest()).toMatchObject({ accepted: true });
    await vi.waitFor(() => expect(input.stopLauncherAssistant).toHaveBeenCalledOnce());
    expect(await input.restartLatest()).toMatchObject({ accepted: false });
    expect(input.scheduleCurrentDesktopShellRefresh).toHaveBeenCalledOnce();
    expect(input.app.exit).not.toHaveBeenCalled();
  });

  it.each(["active", "unknown"] as const)("does not build, stop or schedule when tasks are %s", async (state) => {
    const input = updateInputs({ state, count: state === "active" ? 1 : 0, message: "" });
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: false, operation: "restart-latest-shell" });
    expect(input.prepare).not.toHaveBeenCalled();
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
    expect(input.scheduleReplacement).not.toHaveBeenCalled();
  });

  it("fails closed if the task probe rejects", async () => {
    const input = updateInputs();
    input.activeWork.mockRejectedValue(new Error("offline"));
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: false, code: "active_work_status_unavailable" });
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
  });

  it("lets an operator update save running tasks before replacing the shell", async () => {
    const input = { ...updateInputs({ state: "active", count: 1, message: "" }), interruptActiveWork: true };
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: true });
    expect(input.prepare).toHaveBeenCalledOnce();
    expect(input.stopWorkspaces).toHaveBeenCalledOnce();
    expect(input.scheduleReplacement).toHaveBeenCalledOnce();
    expect(input.stopWorkspaces.mock.invocationCallOrder[0]).toBeLessThan(input.scheduleReplacement.mock.invocationCallOrder[0]);
  });

  it("retains the shell when an operator task-save acknowledgement fails", async () => {
    const input = { ...updateInputs({ state: "active", count: 1, message: "" }), interruptActiveWork: true };
    input.stopWorkspaces.mockRejectedValue(new Error("user_restart_pause_failed"));
    await expect(executeLauncherUpdate(input)).rejects.toThrow("user_restart_pause_failed");
    expect(input.scheduleReplacement).not.toHaveBeenCalled();
  });

  it("lets an operator update continue when task status cannot be confirmed", async () => {
    const input = { ...updateInputs({ state: "unknown", message: "" }), interruptActiveWork: true };
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: true });
    expect(input.prepare).toHaveBeenCalledOnce();
    expect(input.stopWorkspaces).toHaveBeenCalledOnce();
    expect(input.scheduleReplacement).toHaveBeenCalledOnce();
  });

  it("lets an operator update continue when the task observation is lost", async () => {
    // A pure observation failure carries no active-work claim; the operator
    // already authorized the interrupt and stopWorkspaces still saves first.
    const input = { ...updateInputs({ state: "unobservable", message: "assistant lifecycle status rpc timed out" }), interruptActiveWork: true };
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: true });
    expect(input.prepare).toHaveBeenCalledOnce();
    expect(input.stopWorkspaces).toHaveBeenCalledOnce();
    expect(input.scheduleReplacement).toHaveBeenCalledOnce();
  });

  it("keeps rejecting a lost observation for an update that lacks operator interrupt authorization", async () => {
    const input = updateInputs({ state: "unobservable", message: "assistant lifecycle status rpc timed out" });
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: false, code: "active_work_status_unavailable" });
    expect(input.prepare).not.toHaveBeenCalled();
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
    expect(input.scheduleReplacement).not.toHaveBeenCalled();
  });

  it("lets an operator update continue when the task probe rejects", async () => {
    const input = { ...updateInputs(), interruptActiveWork: true };
    input.activeWork.mockRejectedValue(new Error("offline"));
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: true });
    expect(input.stopWorkspaces).toHaveBeenCalledOnce();
    expect(input.scheduleReplacement).toHaveBeenCalledOnce();
  });

  it("keeps windows alive on preparation failure", async () => {
    const input = updateInputs();
    input.prepare.mockRejectedValue(new Error("tsc failed"));
    await expect(executeLauncherUpdate(input)).rejects.toThrow("tsc failed");
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
    expect(input.scheduleReplacement).not.toHaveBeenCalled();
  });

  it("rechecks tasks that start during a build", async () => {
    const input = updateInputs();
    input.activeWork.mockResolvedValueOnce({ state: "idle", message: "" }).mockResolvedValueOnce({ state: "active", count: 1, message: "" });
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: false, code: "active_work_blocked" });
    expect(input.prepare).toHaveBeenCalledOnce();
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
  });

  it("only schedules after a successful normal stop", async () => {
    const input = updateInputs();
    input.stopWorkspaces.mockRejectedValue(new Error("stop refused"));
    await expect(executeLauncherUpdate(input)).rejects.toThrow("stop refused");
    expect(input.scheduleReplacement).not.toHaveBeenCalled();
    input.stopWorkspaces.mockResolvedValue(undefined);
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: true });
    expect(input.scheduleReplacement).toHaveBeenCalledOnce();
  });

  it("wires the real IPC route through preparation and non-force shutdown", () => {
    const main = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
    const update = main.slice(main.indexOf("async function restartLauncherToLatestBuild"), main.indexOf("async function exitAndRelaunchLauncherShell"));
    expect(update).toContain("executeLauncherUpdate");
    expect(update).toContain("ensureLatestLauncher");
    expect(update).toContain('shellKind: options.shellKind ?? (app.isPackaged ? "packaged" : "unpackaged")');
    expect(update).toContain("stopMainRuntimeForApprovedShutdown");
    expect(update).toContain("stopIsolatedInstancesForApprovedShutdown");
    expect(update).not.toContain("bestEffortStopIsolatedInstancesForShutdown");
    expect(update).not.toContain('"force-stop"');
  });

  it("hands a prepared unpackaged tray update to the helper before exiting", async () => {
    const main = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
    const begin = main.indexOf("async function exitAndRelaunchLauncherShell(");
    const end = main.indexOf("async function runTrayRestartLauncher(", begin);
    expect(begin).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(begin);
    const events: string[] = [];
    const schedule = vi.fn(async () => { events.push("schedule"); });
    const relaunch = vi.fn();
    const sandbox: Record<string, unknown> = {
      app: { isPackaged: false, relaunch, exit: () => { events.push("exit"); } },
      shellRefreshInFlight: false, shutdownApproved: false,
      decideLauncherShellRestart: () => "ensure-and-relaunch",
      desktopPythonPath: () => "pythonw.exe",
      createDesktopPathsForApp: () => ({ workspaceRoot: "test-workspace" }),
      notifyDesktopTray: vi.fn(),
      ensureLatestLauncher: async () => { events.push("prepare"); },
      scheduleCurrentDesktopShellRefresh: schedule,
      stopLauncherAssistant: async () => { events.push("drain-assistant"); },
    };
    const code = transpileModule(desktopExitHelper(main) + main.slice(begin, end) + "\nglobalThis.restart = exitAndRelaunchLauncherShell;", {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText;
    runInNewContext(code, sandbox);
    await (sandbox.restart as () => Promise<void>)();
    expect(events).toEqual(["prepare", "schedule", "drain-assistant", "exit"]);
    // The replacement shell carries the start lifecycle so it restores the
    // workbench/backend instead of coming up as a bare tray.
    expect(schedule).toHaveBeenCalledWith("start", { force: true, shellKind: "unpackaged" });
    expect(relaunch).not.toHaveBeenCalled();
    expect(sandbox.shutdownApproved).toBe(true);
  });
});

describe("Launcher freshness is based on the real packaged shell", () => {
  it("projects only the native transaction's live progress", () => {
    const progress = { phase: "saving" as const, startedAt: 12345 };
    const read = { raw: { current: true, updatePhase: "spoofed", updateStartedAt: 1 }, packaged: false,
      activeWork: { state: "idle" as const, message: "" }, updating: true, progress };
    expect(projectLauncherUpdateFreshness(read)).toMatchObject({ updateInProgress: true, updatePhase: "saving", updateStartedAt: 12345 });
    expect(projectLauncherUpdateFreshness({ ...read, updating: false }).updatePhase).toBeUndefined();
    expect(projectLauncherUpdateFreshness({ ...read, progress: null }).updateStartedAt).toBeUndefined();
  });
  const input = { raw: { current: true, runningShort: "wrong-head-label" }, packaged: true, activeWork: { state: "idle", message: "" } as ActiveWorkStatus, updating: false };
  it("never turns a failed inspection into an up-to-date verdict", () => {
    expect(projectLauncherUpdateFreshness(input)).toMatchObject({ current: null, updateAvailable: false, runningShort: "", activeWorkState: "idle" });
  });
  it("detects stale frontend bytes even when the Python process claims current", () => {
    expect(projectLauncherUpdateFreshness({ ...input, shell: { schemaVersion: 1, stale: true, reason: "frontend_content_mismatch", currentElectronTree: "c".repeat(40), packagedSourceCommit: "a".repeat(40), currentCommit: "b".repeat(40) } })).toMatchObject({ current: false, updateAvailable: true, runningShort: "a".repeat(12), headShort: "b".repeat(12) });
  });
  it("does not advertise an update when the current frontend could not be inspected", () => {
    expect(projectLauncherUpdateFreshness({ ...input, shell: { schemaVersion: 1, stale: true, reason: "frontend_inspection_failed", currentElectronTree: "a".repeat(40) } })).toMatchObject({ current: null, updateAvailable: false, shellStale: false });
  });
  it("only reports current after a verified source identity and surfaces refresh failures", () => {
    expect(projectLauncherUpdateFreshness({ ...input, shell: { schemaVersion: 1, stale: false, reason: "current", currentElectronTree: "a".repeat(40), refreshBlocked: true, refreshBlockedDetail: "package failed" } })).toMatchObject({ current: true, refreshError: "package failed" });
  });
  it("returns a version when task status fails and keeps the last known shell", () => {
    const main = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
    const body = main.slice(main.indexOf("const observeLauncherFreshness"), main.indexOf("async function exitAndRelaunchLauncherShell"));
    expect(body).toContain("Promise.allSettled");
    expect(body).toContain("retainKnownDesktopShell");
    expect(body).toContain('state: "unknown"');
    expect(body).not.toContain("inspectCurrentDesktopShell().catch(() => undefined)");
  });

  it("keeps the last identified shell when the next read misses", () => {
    const known = { schemaVersion: 1 as const, stale: true, launchBlocking: true, reason: "provenance_mismatch", currentElectronTree: "c".repeat(40), packagedSourceCommit: "a".repeat(40), currentCommit: "b".repeat(40) };
    const missed = { schemaVersion: 1 as const, stale: true, launchBlocking: false, reason: "frontend_inspection_failed", currentElectronTree: "d".repeat(40) };
    expect(retainKnownDesktopShell(known, undefined)).toBe(known);
    expect(retainKnownDesktopShell(known, missed)).toBe(known);
    expect(retainKnownDesktopShell(undefined, missed)).toBeUndefined();
    const newer = { ...known, stale: false, reason: "current", currentElectronTree: "e".repeat(40) };
    expect(retainKnownDesktopShell(known, newer)).toBe(newer);
    expect(projectLauncherUpdateFreshness({ ...input, shell: retainKnownDesktopShell(known, missed) })).toMatchObject({ current: false, updateAvailable: true });
  });
});

describe("Launcher freshness serves the settled state-refresh snapshot before spawning", () => {
  type SnapshotStoreOverrides = { observedAt?: Date; snapshotFreshness?: string; freshnessSource?: unknown; valid?: boolean };

  function settledSnapshotStore(overrides: SnapshotStoreOverrides = {}) {
    return {
      snapshot: () => ({
        schemaVersion: 1,
        revision: 7,
        observedAt: (overrides.observedAt ?? new Date()).toISOString(),
        freshness: overrides.snapshotFreshness ?? "fresh",
        main: { id: "main", kind: "main", current: true },
        instances: [],
        cleanup: { reconciliation: { active: false, reason: "" }, cleanedCount: 0, skippedCount: 0, failedCount: 0, classifications: [], portConflicts: [], removedInstanceIds: [], worktreeDryRun: [], orphanCriteria: [] }
      }),
      projectFreshness: () => "freshnessSource" in overrides ? overrides.freshnessSource : { current: true, reason: "current" },
      observationEpoch: () => 0,
      projectFreshnessObservation: () => ({ observedAtMs: (overrides.observedAt ?? new Date()).getTime(), epoch: 0, valid: overrides.valid ?? true }),
      projectStatus: () => ({ lifecycleProof: { activeWorkRuns: { count: 0, items: [] } } }),
      projectBranchInstances: () => ({ schemaVersion: 1, items: [] }),
    };
  }

  function snapshotFreshnessHarness(launcherStateStore: ReturnType<typeof settledSnapshotStore>, afterObservation?: () => void) {
    const main = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
    const region = main.slice(main.indexOf("async function resolveLauncherUpdateActiveWork"), main.indexOf("async function exitAndRelaunchLauncherShell"));
    const app = { isPackaged: false };
    const build = () => ({ kind: app.isPackaged ? "packaged" as const : "unpackaged" as const,
      id: "c".repeat(64), electronTree: "a".repeat(40), sourceCommit: "b".repeat(40) });
    const candidate = { get availableBuild() { return build(); }, availableBuildState: "ready" };
    const sandbox = {
      app,
      get runningLauncherBuild() { return build(); },
      launcherBuildCandidateObservation: { identity: JSON.stringify(["test-workspace", 0]), observedAtMs: Date.now(), raw: candidate },
      shellRefreshInFlight: false,
      launcherUpdateProgress: null as LauncherUpdateProgress | null,
      lastKnownDesktopShell: undefined as DesktopShellStatus | undefined,
      lastKnownDesktopShellObservation: undefined as { identity: string; observedAtMs: number } | undefined,
      createLauncherFreshnessObservation: <T>(identity: () => string, load: () => Promise<T>) => {
        const observe = createLauncherFreshnessObservation(identity, load);
        return async () => { const result = await observe(); afterObservation?.(); return result; };
      },
      createDesktopPathsForApp: () => ({ workspaceRoot: "test-workspace" }),
      recordSupervisorEventFallbackLocally: vi.fn(),
      projectLauncherUpdateFreshness,
      retainKnownDesktopShell,
      activeWorkStatusFromLauncherStatus,
      parseBranchInstanceRecords,
      combineAssistantActiveWork,
      residentAssistantActiveWork: vi.fn().mockResolvedValue({ state: "idle", message: "" }),
      listActiveWorkRuns: vi.fn(() => []),
      // The extracted region declares the real resolveLauncherUpdateActiveWork,
      // so the fallback's task probe flows through this path-aware bridge mock.
      orchestrateLauncherApi: vi.fn(async (path: string, _payload?: unknown) => path === "status"
        ? { lifecycleProof: { activeWorkRuns: { count: 0, items: [] } } }
        : { current: false, reason: "backend_behind_local_code", ...candidate }),
      inspectCurrentDesktopShell: vi.fn(),
      launcherStateStore,
      readFreshness: undefined as unknown as () => Promise<Record<string, unknown>>,
    };
    const code = transpileModule(`${region}\nglobalThis.readFreshness = currentLauncherUpdateFreshness;`, {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText;
    runInNewContext(code, sandbox);
    return sandbox;
  }

  it("answers a recent settled snapshot without spawning the launcher CLI", async () => {
    const input = snapshotFreshnessHarness(settledSnapshotStore({ observedAt: new Date(Date.now() - 5_000) }));
    expect(await input.readFreshness()).toMatchObject({
      current: true,
      label: "Launcher 已是最新",
      shellStale: false,
      updateAvailable: false,
      activeWorkState: "idle",
      activeWorkCount: 0,
      updateInProgress: false
    });
    expect(input.orchestrateLauncherApi).not.toHaveBeenCalled();
    expect(input.inspectCurrentDesktopShell).not.toHaveBeenCalled();
  });

  const verifiedShell: DesktopShellStatus = {
    schemaVersion: 1, stale: false, launchBlocking: false, reason: "current",
    currentElectronTree: "a".repeat(40), packagedSourceCommit: "b".repeat(40), currentCommit: "b".repeat(40),
  };

  it("shares one native inspection group for concurrent packaged requests", async () => {
    const input = snapshotFreshnessHarness(settledSnapshotStore({ observedAt: new Date(0) }));
    input.app.isPackaged = true;
    input.inspectCurrentDesktopShell.mockResolvedValue(verifiedShell);
    const results = await Promise.all([input.readFreshness(), input.readFreshness(), input.readFreshness()]);
    expect(results).toEqual(Array(3).fill(expect.objectContaining({ current: true })));
    expect(input.inspectCurrentDesktopShell).toHaveBeenCalledOnce();
    expect(input.orchestrateLauncherApi.mock.calls.filter(([path]) => path.startsWith("freshness?"))).toHaveLength(1);
    expect(input.orchestrateLauncherApi.mock.calls.filter(([path]) => path === "status")).toHaveLength(1);
    expect(input.recordSupervisorEventFallbackLocally).toHaveBeenCalledOnce();
  });

  it("requires current packaged-shell evidence before using a recent source snapshot", async () => {
    const input = snapshotFreshnessHarness(settledSnapshotStore());
    input.app.isPackaged = true;
    input.inspectCurrentDesktopShell.mockResolvedValue(verifiedShell);
    expect(await input.readFreshness()).toMatchObject({ current: true });
    expect(input.inspectCurrentDesktopShell).toHaveBeenCalledOnce();
    expect(await input.readFreshness()).toMatchObject({ current: true });
    expect(input.inspectCurrentDesktopShell).toHaveBeenCalledOnce();
    input.lastKnownDesktopShellObservation!.observedAtMs = Date.now() - 120_000;
    await input.readFreshness();
    expect(input.inspectCurrentDesktopShell).toHaveBeenCalledTimes(2);
  });

  it("keeps known version labels without claiming current when shell inspection fails", async () => {
    const input = snapshotFreshnessHarness(settledSnapshotStore({ valid: false }));
    input.app.isPackaged = true;
    input.lastKnownDesktopShell = verifiedShell;
    input.inspectCurrentDesktopShell.mockRejectedValue(new Error("inspection failed"));
    expect(await input.readFreshness()).toMatchObject({ current: null, runningShort: "b".repeat(12) });
    expect(input.lastKnownDesktopShellObservation).toBeUndefined();
  });

  it("projects the live update flag after shared inputs finish", async () => {
    const input = snapshotFreshnessHarness(settledSnapshotStore({ valid: false }));
    let finish!: (value: unknown) => void;
    input.orchestrateLauncherApi.mockImplementation(async path => path.startsWith("freshness?")
      ? new Promise(resolve => { finish = resolve; })
      : { lifecycleProof: { activeWorkRuns: { count: 0, items: [] } } });
    const reading = input.readFreshness();
    await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
    input.shellRefreshInFlight = true;
    finish({ current: true });
    expect(await reading).toMatchObject({ updateInProgress: true });
  });

  it("rechecks version inputs if the epoch changes during the fast-path native task probe", async () => {
    const input = snapshotFreshnessHarness(settledSnapshotStore());
    let epoch = 0;
    input.launcherStateStore.observationEpoch = () => epoch;
    input.residentAssistantActiveWork.mockImplementationOnce(async () => {
      epoch += 1;
      return { state: "idle", message: "" };
    });
    expect(await input.readFreshness()).toMatchObject({ current: false });
    expect(input.orchestrateLauncherApi.mock.calls.filter(([path]) => path.startsWith("freshness?"))).toHaveLength(1);
  });

  it("rejects a result invalidated between shared observation and consumer projection", async () => {
    let epoch = 0;
    const input = snapshotFreshnessHarness(settledSnapshotStore({ valid: false }), () => { epoch += 1; });
    input.launcherStateStore.observationEpoch = () => epoch;
    await expect(input.readFreshness()).rejects.toThrow("version changed during inspection");
  });

  it.each(["active", "unknown"] as const)("retains native %s in the actual main update aggregator with an idle backend", async state => {
    const input = snapshotFreshnessHarness(settledSnapshotStore({ observedAt: new Date(0) }));
    input.residentAssistantActiveWork.mockResolvedValue({ state, message: "native" });
    expect(await input.readFreshness()).toMatchObject({ activeWorkState: state });
    expect(input.residentAssistantActiveWork).toHaveBeenCalledOnce();
  });

  it.each([
    ["an idle-stale observation", { observedAt: new Date(Date.now() - 10 * 60_000) }],
    ["a mid-refresh snapshot", { snapshotFreshness: "refreshing" }],
    ["a missing freshness source", { freshnessSource: undefined }],
    ["an unsuccessful version observation", { valid: false }],
    ["a future version observation", { observedAt: new Date(Date.now() + 60_000) }]
  ] as Array<[string, SnapshotStoreOverrides]>)("falls back to the launcher read for %s", async (_reason, overrides) => {
    const input = snapshotFreshnessHarness(settledSnapshotStore(overrides));
    expect(await input.readFreshness()).toMatchObject({
      current: false,
      label: "Launcher 落后本地代码",
      updateAvailable: true,
      activeWorkState: "idle"
    });
    const freshnessCalls = input.orchestrateLauncherApi.mock.calls.filter(([path]) => path.startsWith("freshness?"));
    expect(freshnessCalls).toHaveLength(1);
    expect(freshnessCalls[0][1]).toMatchObject({ path: "freshness", schemaVersion: 1 });
  });
});
