import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LauncherLifecycleSupervisor } from "../src/lifecycle/launcherLifecycleSupervisor.js";
import {
  peekFrontendBuild,
  resetFrontendBuildStateForTests,
  runWithFrontendBuildGate
} from "../src/lifecycle/frontendBuildState.js";
import { shouldRefreshBeforeLifecycle } from "../src/process/desktopShellFreshness.js";
import type { RunWorkbenchLifecycleInput } from "../src/process/workbenchLifecycle.js";

function harness(options: { live?: boolean; releaseChanged?: boolean } = {}) {
  // Run the real Electron adapter without starting Electron or any process.
  const source = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
  const begin = source.indexOf("async function orchestrateLauncherLifecycle(");
  const end = source.indexOf("\nconst SHELL_STALE_NOTE", begin);
  expect(begin).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(begin);
  const supervisor = new LauncherLifecycleSupervisor();
  const ensure = vi.fn(async (_input: { signal?: AbortSignal }) => ({ skipped: !options.releaseChanged }));
  const reachable = vi.fn(async () => options.live ?? false);
  const reusable = vi.fn(async () => true);
  const opened = vi.fn(async () => undefined);
  const notify = vi.fn();
  const trayNotify = vi.fn();
  const promote = vi.fn(async () => ({
    schemaVersion: 1,
    accepted: true,
    operation: "restart-latest-shell",
    message: "promoted"
  }));
  const lifecycle = vi.fn(async (input: RunWorkbenchLifecycleInput) => {
    // The backend invokes this callback at its startup boundary, with its
    // execution signal. Preserve that contract in this process-free harness.
    await input.ensureFrontend?.({ force: input.operation === "rebuild-and-start", signal: input.signal });
    return { schemaVersion: 1, accepted: true, operation: input.operation, commandId: "test-command" };
  });
  const sandbox: Record<string, unknown> = {
    AbortSignal, Error, console,
    launcherBootstrap: {},
    authorizeLauncherForceLifecycle: async () => null,
    desktopEnvironment: () => ({ VIBELUTION_PYTHON_PATH: "pythonw.exe" }),
    normalizeSupervisedLifecycleOperation: (operation: string) => operation,
    desiredStateForLifecycleOperation: () => "open",
    createDesktopPathsForApp: () => ({ workspaceRoot: "C:/frontend-preflight-test" }),
    app: { isPackaged: false },
    windowProvider: {},
    mainLineBackendIsReachable: reachable,
    mainLineBackendIsReusable: reusable,
    inspectWorkbenchServingVersion: async () => ({ ok: true }),
    ensureFrontendRelease: ensure,
    runWithFrontendBuildGate,
    updateLauncherWindowTruth: notify,
    inspectUnpackagedShell: async () => ({ stale: false }),
    // Real routing decision so the unpackaged rebuild-and-start promotion lane
    // is exercised end to end without Electron.
    shouldRefreshBeforeLifecycle,
    notifyDesktopTray: trayNotify,
    restartLauncherToLatestBuild: promote,
    joinDecisionForLauncherLifecycleStop: () => ({ waitForInFlightRestart: false, joinInFlightRestart: false }),
    launcherLifecycleSupervisor: supervisor,
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
    ensure, reachable, reusable, opened, notify, trayNotify, promote, lifecycle, supervisor,
    run: sandbox.orchestrateUnderTest as (
      operation: string, payload: object, provenance?: string, signal?: AbortSignal
    ) => Promise<{ accepted: boolean; code?: string }>
  };
}

afterEach(resetFrontendBuildStateForTests);

describe("main-line frontend startup preflight", () => {
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
