import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { createSourceFile, isFunctionDeclaration, ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi } from "vitest";
import { executeLauncherUpdate, projectLauncherUpdateFreshness, retainKnownDesktopShell } from "../src/process/launcherUpdate.js";
import { decidePackagedDesktopShellRefresh } from "../src/process/desktopShellFreshness.js";
import type { ActiveWorkStatus } from "../src/shutdown/shutdownCoordinator.js";

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
  function automaticRefreshHarness() {
    const main = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
    const refresh = main.slice(main.indexOf("async function refreshPackagedDesktopShellIfStale("), main.indexOf("async function runSmokeAndQuit("));
    const restart = main.slice(main.indexOf("async function restartLauncherToLatestBuild("), main.indexOf("async function resolveLauncherUpdateActiveWork("));
    const sandbox = {
      app: { isPackaged: true, exit: vi.fn() },
      desktopCliArgs: {}, shellRefreshInFlight: false, shutdownApproved: false,
      decidePackagedDesktopShellRefresh,
      inspectCurrentDesktopShellLaunchReadiness: vi.fn().mockResolvedValue({ launchBlocking: true }),
      inspectCurrentDesktopShell: vi.fn().mockResolvedValue({ stale: true, launchBlocking: true }),
      notifyDesktopTray: vi.fn(), executeLauncherUpdate,
      resolveLauncherUpdateActiveWork: vi.fn().mockResolvedValue({ state: "idle", message: "" }),
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
      restartLatest: undefined as unknown as () => Promise<unknown>,
      exitDesktop: undefined as unknown as () => Promise<void>,
    };
    Object.assign(sandbox, {
      bestEffortStopIsolatedInstancesForShutdown: sandbox.stopIsolatedInstancesForApprovedShutdown,
      stopManagedRuntime: sandbox.stopMainRuntimeForApprovedShutdown,
    });
    const code = transpileModule(desktopExitHelper(main) + refresh + restart
      + "\nglobalThis.refresh = refreshPackagedDesktopShellIfStale;\nglobalThis.restartLatest = restartLauncherToLatestBuild;\nglobalThis.exitDesktop = exitDesktopShellProcess;", {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText;
    runInNewContext(code, sandbox);
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
    const body = main.slice(main.indexOf("async function currentLauncherUpdateFreshness"), main.indexOf("async function exitAndRelaunchLauncherShell"));
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
