import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LauncherLifecycleSupervisor } from "../src/lifecycle/launcherLifecycleSupervisor.js";
import { ProjectAdmission } from "../src/lifecycle/projectAdmission.js";
import { isWorkbenchStartBlockedByClose } from "../src/lifecycle/workbenchCloseTransactionStore.js";
import {
  peekFrontendBuild,
  resetFrontendBuildStateForTests,
  runWithFrontendBuildGate
} from "../src/lifecycle/frontendBuildState.js";
import { shouldInspectDesktopShellBeforeLifecycle, shouldRefreshBeforeLifecycle } from "../src/process/desktopShellFreshness.js";
import type { RunWorkbenchLifecycleInput } from "../src/process/workbenchLifecycle.js";

function harness(options: { live?: boolean; releaseChanged?: boolean; packaged?: boolean } = {}) {
  // Run the real Electron adapter without starting Electron or any process.
  const source = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
  const begin = source.indexOf("async function orchestrateLauncherLifecycle(");
  const end = source.indexOf("\nconst SHELL_STALE_NOTE", begin);
  expect(begin).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(begin);
  const supervisor = new LauncherLifecycleSupervisor();
  const admission = new ProjectAdmission();
  const beginIntent = vi.spyOn(supervisor, "beginIntentWithOptions");
  const beginMainLifecycle = vi.fn();
  const currentCloseTransaction = vi.fn((): { phase: string; windowAcknowledged?: boolean } | null => null);
  const backgroundRetirement = vi.fn((_workspaceRoot: string) => false);
  const ensure = vi.fn(async (_input: { signal?: AbortSignal }) => ({ skipped: !options.releaseChanged }));
  const reachable = vi.fn(async () => options.live ?? false);
  const reusable = vi.fn(async () => true);
  const servingInspect = vi.fn(async (_input: { signal?: AbortSignal }) => ({ ok: true }));
  const opened = vi.fn(async () => undefined);
  const notify = vi.fn();
  const trayNotify = vi.fn();
  const inspect = vi.fn(async () => ({ stale: true, launchBlocking: true }));
  const fullInspect = vi.fn(() => inspect());
  const launchInspect = vi.fn(() => inspect());
  const unpackagedInspect = vi.fn(async (_input: { signal?: AbortSignal }) => ({ stale: false }));
  const closed = vi.fn(async () => undefined);
  const promote = vi.fn(async () => ({
    schemaVersion: 1,
    accepted: true,
    operation: "restart-latest-shell",
    message: "promoted"
  }));
  const lifecycle = vi.fn(async (input: RunWorkbenchLifecycleInput) => {
    // The backend invokes this callback at its startup boundary, with its
    // execution signal. Preserve that contract in this process-free harness.
    if (["start", "restart", "rebuild-and-start"].includes(input.operation)) {
      await input.ensureFrontend?.({ force: input.operation === "rebuild-and-start", signal: input.signal });
    }
    return { schemaVersion: 1, accepted: true, operation: input.operation, commandId: "test-command" };
  });
  const sandbox: Record<string, unknown> = {
    AbortSignal, Error, console,
    launcherBootstrap: {},
    withProjectAdmission: (root: () => string, work: Parameters<ProjectAdmission["observe"]>[1]) => admission.observe(root, work),
    registeredAdmissionRoot: (root: string) => root,
    authorizeLauncherForceLifecycle: async () => null,
    desktopEnvironment: () => ({ VIBELUTION_PYTHON_PATH: "pythonw.exe" }),
    normalizeSupervisedLifecycleOperation: (operation: string) => operation,
    desiredStateForLifecycleOperation: (operation: string) => ["start", "restart", "rebuild-and-start"].includes(operation) ? "open" : "closed",
    createDesktopPathsForApp: () => ({ workspaceRoot: "C:/frontend-preflight-test" }),
    mainWorkbenchCloseStore: { currentTransaction: currentCloseTransaction },
    hasBackgroundWorkbenchRetirement: backgroundRetirement,
    isWorkbenchStartBlockedByClose, workbenchFailedCloseHandling: false, pendingWorkbenchCloseAck: null,
    app: { isPackaged: options.packaged ?? false },
    windowProvider: { approveWorkbenchCloseOnce: closed },
    shouldDeferOrchestratedWindowClose: () => false,
    mainLineBackendIsReachable: reachable,
    mainLineBackendIsReusable: reusable,
    inspectWorkbenchServingVersion: servingInspect,
    ensureFrontendRelease: ensure,
    runWithFrontendBuildGate,
    updateLauncherWindowTruth: notify,
    inspectUnpackagedShell: unpackagedInspect,
    inspectCurrentDesktopShell: fullInspect,
    inspectCurrentDesktopShellLaunchReadiness: launchInspect,
    // Real routing decision so the unpackaged rebuild-and-start promotion lane
    // is exercised end to end without Electron.
    shouldRefreshBeforeLifecycle,
    shouldInspectDesktopShellBeforeLifecycle,
    notifyDesktopTray: trayNotify,
    restartLauncherToLatestBuild: promote,
    joinDecisionForLauncherLifecycleStop: () => ({ waitForInFlightRestart: false, joinInFlightRestart: false }),
    launcherLifecycleSupervisor: supervisor,
    launcherStateStore: { beginMainLifecycle },
    readLauncherStateFile: () => ({}),
    launcherStatePath: () => "unused",
    runWorkbenchLifecycle: lifecycle,
    scheduleLauncherStatusCliRefresh: () => undefined,
    refreshLiveWorkbenchUrl: async () => "http://127.0.0.1:8000",
    openWorkbenchAtCurrentLauncherUrl: opened,
    openWorkbenchAfterLifecycleReady: async () => undefined,
    workbenchOpenedMessage: () => "opened",
    randomUUID: () => "reuse-command",
    supersededLifecycleResult: () => ({ accepted: false, code: "superseded" }),
    WORKBENCH_START_READY_WAIT_MS: 100,
    WORKBENCH_REBUILD_READY_WAIT_MS: 100,
    SHELL_STALE_NOTE: ""
  };
  runInNewContext(transpileModule(
    source.slice(begin, end) + "\nglobalThis.orchestrateUnderTest = orchestrateLauncherLifecycle;",
    { compilerOptions: { target: ScriptTarget.ES2022 } }
  ).outputText, sandbox);
  return {
    ensure, reachable, reusable, servingInspect, opened, closed, inspect, fullInspect, launchInspect, unpackagedInspect, notify, trayNotify, promote, lifecycle, supervisor,
    beginIntent, beginMainLifecycle, currentCloseTransaction, backgroundRetirement,
    run: sandbox.orchestrateUnderTest as (
      operation: string, payload: object, provenance?: string, signal?: AbortSignal
    ) => Promise<{ accepted: boolean; code?: string }>
  };
}

afterEach(resetFrontendBuildStateForTests);

describe("main-line frontend startup preflight", () => {
  describe.each(["start", "restart", "rebuild-and-start"])("retirement admission for %s", (operation) => {
    it.each([
      { phase: "backend_closing", windowAcknowledged: false, pendingOwner: false },
      { phase: "background_closing", windowAcknowledged: true, pendingOwner: false },
      { phase: "window_close_authorized", windowAcknowledged: false, pendingOwner: false },
      { phase: "succeeded", windowAcknowledged: true, pendingOwner: true },
    ])("keeps the existing intent untouched while $phase / owner pending=$pendingOwner", async ({ phase, windowAcknowledged, pendingOwner }) => {
      const h = harness({ live: true, packaged: true });
      const lease = h.supervisor.beginIntent({ instanceId: "main", operation: "stop", desiredState: "closed" });
      const before = h.supervisor.snapshot("main");
      const generation = h.supervisor.intentGeneration("main");
      h.beginIntent.mockClear();
      h.currentCloseTransaction.mockReturnValue({ phase, windowAcknowledged });
      h.backgroundRetirement.mockReturnValue(pendingOwner);
      await expect(h.run(operation, {})).resolves.toMatchObject({ accepted: false, operation, code: "backend_retiring" });
      expect(h.supervisor.snapshot("main")).toEqual(before);
      expect(h.supervisor.intentGeneration("main")).toBe(generation);
      expect(lease.signal.aborted).toBe(false);
      expect(h.beginIntent).not.toHaveBeenCalled();
      expect(h.beginMainLifecycle).not.toHaveBeenCalled();
      expect(h.lifecycle).not.toHaveBeenCalled();
      expect(h.ensure).not.toHaveBeenCalled();
      expect(h.inspect).not.toHaveBeenCalled();
      expect(h.unpackagedInspect).not.toHaveBeenCalled();
      expect(h.reachable).not.toHaveBeenCalled();
      expect(h.reusable).not.toHaveBeenCalled();
      expect(h.servingInspect).not.toHaveBeenCalled();
      expect(h.opened).not.toHaveBeenCalled();
      expect(h.promote).not.toHaveBeenCalled();
      expect(peekFrontendBuild("main")).toBe(false);
    });
  });

  it.each(["start", "restart"])("retains the original %s preflight after retirement succeeds", async (operation) => {
    const h = harness({ packaged: true });
    h.currentCloseTransaction.mockReturnValue({ phase: "succeeded", windowAcknowledged: true });
    h.inspect.mockResolvedValue({ stale: false, launchBlocking: false });
    await expect(h.run(operation, {})).resolves.toMatchObject({ accepted: true });
    expect(h.beginIntent).toHaveBeenCalledOnce();
    expect(h.beginMainLifecycle).toHaveBeenCalledWith(operation);
    expect(h.inspect).toHaveBeenCalledOnce();
    expect(h.ensure).toHaveBeenCalledOnce();
    expect(h.lifecycle).toHaveBeenCalledWith(expect.objectContaining({ operation }));
  });

  it.each([false, true])("cancels live serving verification when stop supersedes open (late result: %s)", async (lateResult) => {
    const h = harness({ live: true });
    let probeSignal: AbortSignal | undefined;
    h.servingInspect.mockImplementation(({ signal }) => {
      probeSignal = signal;
      return new Promise((resolve, reject) => signal!.addEventListener("abort", () => {
        if (lateResult) resolve({ ok: false });
        else reject(signal!.reason);
      }, { once: true }));
    });
    const opening = h.run("start", {}).catch((error: unknown) => error);
    await vi.waitFor(() => expect(h.servingInspect).toHaveBeenCalledOnce());
    await expect(h.run("force-stop", {})).resolves.toMatchObject({ accepted: true });
    expect(probeSignal?.aborted).toBe(true);
    expect(await opening).toBe(probeSignal?.reason);
    expect(h.reusable).not.toHaveBeenCalled();
    expect(h.opened).not.toHaveBeenCalled();
    expect(h.lifecycle.mock.calls.map(([input]) => input.operation)).toEqual(["force-stop"]);
    expect(h.supervisor.snapshot("main")?.desiredState).toBe("closed");
  });

  it("clears the current intent when only the caller cancels live serving verification", async () => {
    const h = harness({ live: true });
    const controller = new AbortController();
    const reason = new Error("caller cancelled");
    h.servingInspect.mockImplementation(({ signal }) => new Promise((_resolve, reject) => {
      signal!.addEventListener("abort", () => reject(signal!.reason), { once: true });
    }));
    const opening = h.run("start", {}, undefined, controller.signal).catch((error: unknown) => error);
    await vi.waitFor(() => expect(h.servingInspect).toHaveBeenCalledOnce());
    controller.abort(reason);
    expect(await opening).toBe(reason);
    expect(h.supervisor.snapshot("main")).toBeNull();
    expect(h.opened).not.toHaveBeenCalled();
    expect(h.lifecycle).not.toHaveBeenCalled();
  });

  it.each([false, true])("cancels the post-start verifier before ready claims, failure reporting or opening (late result: %s)", async (lateResult) => {
    const source = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
    const begin = source.indexOf("async function openWorkbenchAfterLifecycleReady(");
    const end = source.indexOf("\nasync function retireIsolatedBackendAfterStartFailure", begin);
    expect(begin).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(begin);
    const supervisor = new LauncherLifecycleSupervisor();
    const lease = supervisor.beginIntent({ instanceId: "main", operation: "start", desiredState: "open" });
    const opened = vi.fn();
    const failed = vi.fn();
    const claimReady = vi.spyOn(supervisor, "claimReady");
    const verify = vi.fn(({ signal }: { signal: AbortSignal }) => new Promise((resolve, reject) => {
      expect(signal).toBe(lease.signal);
      signal.addEventListener("abort", () => {
        if (lateResult) resolve({ ok: false, reason: "health_unreachable" });
        else reject(signal.reason);
      }, { once: true });
    }));
    const sandbox: Record<string, unknown> = {
      launcherLifecycleSupervisor: supervisor,
      verifyRestartedServingVersion: verify,
      openWorkbenchAtCurrentLauncherUrl: opened,
      console: { error: failed }
    };
    runInNewContext(transpileModule(
      source.slice(begin, end) + "\nglobalThis.openUnderTest = openWorkbenchAfterLifecycleReady;",
      { compilerOptions: { target: ScriptTarget.ES2022 } }
    ).outputText, sandbox);
    const open = sandbox.openUnderTest as (...args: unknown[]) => Promise<void>;
    const pending = open({ workspaceRoot: "C:/workspace" }, {}, {}, lease, 100).catch((error: unknown) => error);
    supervisor.beginIntent({ instanceId: "main", operation: "stop", desiredState: "closed" });
    expect(await pending).toBe(lease.signal.reason);
    expect(verify).toHaveBeenCalledOnce();
    expect(claimReady).not.toHaveBeenCalled();
    expect(opened).not.toHaveBeenCalled();
    expect(failed).not.toHaveBeenCalled();
  });

  it("cancels the unpackaged shell probe when close supersedes startup", async () => {
    const h = harness();
    let probeSignal: AbortSignal | undefined;
    h.unpackagedInspect.mockImplementation(({ signal }) => {
      probeSignal = signal;
      return new Promise((resolve) => signal!.addEventListener("abort", () => resolve({ stale: false }), { once: true }));
    });
    const opening = h.run("start", {}).catch((error: unknown) => error);
    await vi.waitFor(() => expect(h.unpackagedInspect).toHaveBeenCalledOnce());
    await expect(h.run("force-stop", {})).resolves.toMatchObject({ accepted: true });
    expect(probeSignal?.aborted).toBe(true);
    expect(await opening).toBeInstanceOf(Error);
    expect(h.ensure).not.toHaveBeenCalled();
    expect(h.opened).not.toHaveBeenCalled();
  });

  it("cancels live-backend preflight before mutation and prevents a late open after close", async () => {
    const h = harness({ live: true });
    let finishBuild!: () => void;
    let buildSignal: AbortSignal | undefined;
    h.ensure.mockImplementation(({ signal }) => {
      buildSignal = signal;
      return new Promise((resolve) => { finishBuild = () => resolve({ skipped: true }); });
    });
    const opening = h.run("start", {}).catch((error: unknown) => error);
    await vi.waitFor(() => expect(h.ensure).toHaveBeenCalledOnce());
    await expect(h.run("force-stop", {})).resolves.toMatchObject({ accepted: true });
    expect(buildSignal?.aborted).toBe(true);
    finishBuild();
    expect(await opening).toBeInstanceOf(Error);
    expect(h.opened).not.toHaveBeenCalled();
    expect(h.lifecycle.mock.calls.map(([input]) => input.operation)).toEqual(["force-stop"]);
    expect(h.supervisor.snapshot("main")?.desiredState).toBe("closed");
  });

  it.each(["stop", "force-stop", "shutdown"])("executes packaged %s without inspecting or building a release", async (operation) => {
    const h = harness({ packaged: true });
    h.inspect.mockImplementation(() => new Promise(() => undefined));
    await expect(h.run(operation, {})).resolves.toMatchObject({ accepted: true });
    expect(h.inspect).not.toHaveBeenCalled();
    expect(h.ensure).not.toHaveBeenCalled();
    expect(h.lifecycle).toHaveBeenCalledWith(expect.objectContaining({ operation }));
    expect(h.closed).toHaveBeenCalledOnce();
  });

  it.each(["start", "restart", "rebuild-and-start"])("retains the packaged version gate for %s", async (operation) => {
    const h = harness({ packaged: true });
    await expect(h.run(operation, {})).resolves.toMatchObject({ accepted: true });
    expect(h.inspect).toHaveBeenCalled();
    expect(h.promote).toHaveBeenCalledWith(operation === "restart", operation, { shellKind: "packaged" });
    expect(h.lifecycle).not.toHaveBeenCalled();
  });

  it("checks a current packaged shell once before a cold start", async () => {
    const h = harness({ packaged: true });
    h.inspect.mockResolvedValue({ stale: false, launchBlocking: false });
    await expect(h.run("start", {})).resolves.toMatchObject({ accepted: true });
    expect(h.inspect).toHaveBeenCalledOnce();
    expect(h.launchInspect).toHaveBeenCalledOnce();
    expect(h.fullInspect).not.toHaveBeenCalled();
    expect(h.ensure).toHaveBeenCalledOnce();
    expect(h.inspect.mock.invocationCallOrder[0]).toBeLessThan(h.ensure.mock.invocationCallOrder[0]!);
    expect(h.lifecycle).toHaveBeenCalledWith(expect.objectContaining({ operation: "start" }));
    expect(h.promote).not.toHaveBeenCalled();
  });

  it("checks a launch-blocking packaged shell once and promotes before a cold start", async () => {
    const h = harness({ packaged: true });
    await h.run("start", {});
    expect(h.inspect).toHaveBeenCalledOnce();
    expect(h.promote).toHaveBeenCalledOnce();
    expect(h.ensure).not.toHaveBeenCalled();
    expect(h.lifecycle).not.toHaveBeenCalled();
  });

  it("skips the reuse-only shell scan after rebuilding the live backend's frontend", async () => {
    const h = harness({ packaged: true, live: true, releaseChanged: true });
    h.inspect.mockResolvedValue({ stale: false, launchBlocking: false });
    await h.run("start", {});
    expect(h.inspect).toHaveBeenCalledOnce();
    expect(h.reusable).not.toHaveBeenCalled();
    // The earlier build cannot replace the queued mutation's fresh source check.
    expect(h.ensure).toHaveBeenCalledTimes(2);
    expect(h.lifecycle).toHaveBeenCalledWith(expect.objectContaining({ operation: "restart" }));
  });

  it("rechecks the shell before restart when a verified live backend cannot be reused", async () => {
    const h = harness({ packaged: true, live: true });
    h.inspect.mockResolvedValue({ stale: false, launchBlocking: false });
    h.reusable.mockResolvedValue(false);
    await h.run("start", {});
    expect(h.inspect).toHaveBeenCalledTimes(2);
    expect(h.ensure).toHaveBeenCalledTimes(2);
    expect(h.lifecycle).toHaveBeenCalledWith(expect.objectContaining({ operation: "restart" }));
  });

  it("promotes a shell that becomes launch-blocking after live-backend reuse fails", async () => {
    const h = harness({ packaged: true, live: true });
    h.inspect.mockResolvedValueOnce({ stale: false, launchBlocking: false });
    h.reusable.mockResolvedValue(false);
    await h.run("start", {});
    expect(h.inspect).toHaveBeenCalledTimes(2);
    expect(h.ensure).toHaveBeenCalledOnce();
    expect(h.promote).toHaveBeenCalledWith(false, "restart", { shellKind: "packaged" });
    expect(h.lifecycle).not.toHaveBeenCalled();
  });

  it("still checks the packaged shell before reusing a verified live backend", async () => {
    const h = harness({ packaged: true, live: true });
    h.inspect.mockResolvedValue({ stale: false, launchBlocking: false });
    await h.run("start", {});
    expect(h.inspect).toHaveBeenCalledOnce();
    expect(h.fullInspect).toHaveBeenCalledOnce();
    expect(h.launchInspect).not.toHaveBeenCalled();
    expect(h.ensure).toHaveBeenCalledOnce();
    expect(h.lifecycle).not.toHaveBeenCalled();
    expect(h.opened).toHaveBeenCalledOnce();
  });

  it.each(["start", "restart"])("verifies once at the startup boundary for %s", async (operation) => {
    const h = harness();
    await expect(h.run(operation, {})).resolves.toMatchObject({ accepted: true });
    expect(h.ensure).toHaveBeenCalledTimes(1);
    expect(h.lifecycle).toHaveBeenCalledTimes(1);
    expect(h.notify).toHaveBeenCalledTimes(2);
    expect(peekFrontendBuild("main")).toBe(false);
  });

  it("routes an unpackaged rebuild-and-start into the shell promotion lane instead of the workbench preflight", async () => {
    const h = harness();
    await expect(h.run("rebuild-and-start", {})).resolves.toMatchObject({
      accepted: true,
      operation: "restart-latest-shell"
    });
    // The helper must promote to a packaged shell, never relaunch unpackaged.
    expect(h.promote).toHaveBeenCalledWith(false, "rebuild-and-start", { shellKind: "packaged" });
    expect(h.lifecycle).not.toHaveBeenCalled();
    expect(h.ensure).not.toHaveBeenCalled();
    expect(h.trayNotify).toHaveBeenCalledTimes(1);
  });

  it("still verifies before reusing a live backend", async () => {
    const h = harness({ live: true });
    await h.run("start", {});
    expect(h.ensure).toHaveBeenCalledTimes(1);
    expect(h.lifecycle).not.toHaveBeenCalled();
    expect(h.opened).toHaveBeenCalledTimes(1);
    expect(h.ensure.mock.invocationCallOrder[0]).toBeLessThan(h.reusable.mock.invocationCallOrder[0]!);
  });

  it.each([false, true])("rechecks sources when live-backend reuse falls back to restart (rebuilt: %s)", async (releaseChanged) => {
    const h = harness({ live: true, releaseChanged });
    h.reusable.mockResolvedValue(false);
    await h.run("start", {});
    expect(h.ensure).toHaveBeenCalledTimes(2);
    expect(h.lifecycle).toHaveBeenCalledWith(expect.objectContaining({ operation: "restart" }));
    expect(h.opened).not.toHaveBeenCalled();
  });

  it("cannot reuse a backend that appeared after the initial reachability probe", async () => {
    const h = harness();
    h.reachable.mockResolvedValueOnce(false).mockResolvedValue(true);
    await h.run("start", {});
    expect(h.reusable).not.toHaveBeenCalled();
    expect(h.ensure).toHaveBeenCalledTimes(1);
    expect(h.lifecycle).toHaveBeenCalledWith(expect.objectContaining({ operation: "restart" }));
  });

  it("forwards cancellation and clears the build marker and failed intent", async () => {
    const h = harness();
    const caller = new AbortController();
    let buildStarted!: () => void;
    const started = new Promise<void>((resolve) => { buildStarted = resolve; });
    h.ensure.mockImplementation(({ signal }) => new Promise((_resolve, reject) => {
      expect(signal).toBeDefined();
      expect(peekFrontendBuild("main")).toBe(true);
      signal!.addEventListener("abort", () => reject(signal!.reason), { once: true });
      buildStarted();
    }));
    const result = h.run("restart", {}, "operator", caller.signal);
    await started;
    caller.abort(new Error("test cancellation"));
    await expect(result).rejects.toThrow("test cancellation");
    expect(peekFrontendBuild("main")).toBe(false);
    expect(h.supervisor.snapshot("main")).toBeNull();
  });
});
