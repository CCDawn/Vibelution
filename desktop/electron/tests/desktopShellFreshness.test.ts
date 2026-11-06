import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ADVISORY_FRONTEND_ENSURE_DEBOUNCE_MS,
  advisoryFrontendEnsureKey,
  createAdvisoryFrontendEnsureScheduler,
  decideLauncherShellRestart,
  decidePackagedDesktopShellRefresh,
  decidePeriodicDesktopShellRefresh,
  shouldProbePeriodicDesktopShell,
  formatTrayLauncherFreshness,
  inspectDesktopShell,
  inspectDesktopShellLaunchReadiness,
  parseDesktopShellStatus,
  scheduleDesktopShellRefresh,
  ensureLatestLauncher,
  shouldDeferWorkbenchOpenUntilLifecycleStart,
  shouldInspectDesktopShellBeforeLifecycle,
  shouldRefreshBeforeLifecycle,
  thenLifecycleFromDesktopCli,
  type AdvisoryFrontendEnsureEvent,
  type AdvisoryFrontendEnsureRequest
} from "../src/process/desktopShellFreshness.js";

type SpawnChild = {
  kill(): void;
  once(event: string, listener: (...args: unknown[]) => void): unknown;
  stdout: { on(event: string, listener: (chunk: Buffer) => void): unknown };
  stderr: { on(event: string, listener: () => void): unknown };
};

function fakeSpawnWithOutput(output: string, exitCode = 0): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((_command: string, _args: string[], _options: unknown) => {
    const child: SpawnChild = {
      kill: () => undefined,
      once: (event, listener) => {
        if (event === "error") {
          return undefined;
        }
        queueMicrotask(() => listener(exitCode));
        return undefined;
      },
      stdout: {
        on: (_event, listener) => {
          queueMicrotask(() => listener(Buffer.from(output, "utf8")));
          return undefined;
        }
      },
      stderr: {
        on: () => undefined
      }
    };
    return child;
  });
}

describe("desktop shell freshness", () => {
  it("inspects packaged launch operations without scanning versions for stops", () => {
    for (const operation of ["start", "restart", "rebuild-and-start"]) {
      expect(shouldInspectDesktopShellBeforeLifecycle(operation, true)).toBe(true);
      expect(shouldInspectDesktopShellBeforeLifecycle(operation, false)).toBe(false);
    }
    for (const operation of ["stop", "force-stop", "shutdown", ""]) {
      expect(shouldInspectDesktopShellBeforeLifecycle(operation, true)).toBe(false);
    }
  });

  it("refreshes only a packaged stale shell outside smoke and canary", () => {
    expect(decidePackagedDesktopShellRefresh({ isPackaged: false, smoke: false, stale: true })).toBe("skip");
    expect(decidePackagedDesktopShellRefresh({ isPackaged: true, smoke: true, stale: true })).toBe("skip");
    expect(decidePackagedDesktopShellRefresh({ isPackaged: true, smoke: false, workbenchCloseCanary: true, stale: true })).toBe(
      "skip"
    );
    expect(decidePackagedDesktopShellRefresh({ isPackaged: true, smoke: false, stale: false })).toBe("skip");
    expect(decidePackagedDesktopShellRefresh({ isPackaged: true, smoke: false, stale: true })).toBe("refresh");
    expect(
      decidePackagedDesktopShellRefresh({ isPackaged: true, smoke: false, stale: true, refreshBlocked: true })
    ).toBe("skip");
    expect(
      decidePeriodicDesktopShellRefresh({
        isPackaged: true,
        smoke: false,
        stale: true,
        refreshInFlight: false,
        shutdownApproved: false,
        refreshBlocked: true
      })
    ).toBe("skip");
  });

  it("skips periodic refresh while another shell refresh is in flight or shutdown is approved", () => {
    expect(
      decidePeriodicDesktopShellRefresh({
        isPackaged: true,
        smoke: false,
        stale: true,
        refreshInFlight: true,
        shutdownApproved: false
      })
    ).toBe("skip");
    expect(
      decidePeriodicDesktopShellRefresh({
        isPackaged: true,
        smoke: false,
        stale: true,
        launchBlocking: true,
        refreshInFlight: false,
        shutdownApproved: true
      })
    ).toBe("skip");
    expect(
      decidePeriodicDesktopShellRefresh({
        isPackaged: true,
        smoke: false,
        stale: true,
        launchBlocking: true,
        refreshInFlight: false,
        shutdownApproved: false
      })
    ).toBe("refresh");
  });

  it("rebuilds only a launch-blocking packaged shell; advisory frontend staleness relaunches", () => {
    expect(decideLauncherShellRestart({ isPackaged: true, launchBlocking: true })).toBe("rebuild-and-exit");
    expect(decideLauncherShellRestart({ isPackaged: true, launchBlocking: false })).toBe("relaunch");
    expect(decideLauncherShellRestart({ isPackaged: false, launchBlocking: true })).toBe("relaunch");
    expect(decideLauncherShellRestart({ isPackaged: true, launchBlocking: false, forceRefresh: true })).toBe(
      "rebuild-and-exit"
    );
    expect(decideLauncherShellRestart({ isPackaged: false, launchBlocking: false, forceRefresh: true })).toBe(
      "ensure-and-relaunch"
    );
  });

  it("keeps start/restart/rebuild-and-start on a launch-blocking packaged shell", () => {
    expect(shouldRefreshBeforeLifecycle("start", { isPackaged: true, launchBlocking: true })).toBe(true);
    expect(shouldRefreshBeforeLifecycle("start", { isPackaged: true, launchBlocking: false })).toBe(false);
    expect(shouldRefreshBeforeLifecycle("stop", { isPackaged: true, launchBlocking: true })).toBe(false);
    expect(shouldRefreshBeforeLifecycle("start", { isPackaged: false, launchBlocking: true })).toBe(false);
    // Packaged shells keep their existing semantics exactly: rebuild-and-start
    // only refreshes when the shell is launch-blocking.
    expect(shouldRefreshBeforeLifecycle("rebuild-and-start", { isPackaged: true, launchBlocking: true })).toBe(true);
    expect(shouldRefreshBeforeLifecycle("rebuild-and-start", { isPackaged: true, launchBlocking: false })).toBe(false);
    expect(shouldRefreshBeforeLifecycle("restart", { isPackaged: true, launchBlocking: true })).toBe(true);
    expect(shouldRefreshBeforeLifecycle("restart", { isPackaged: true, launchBlocking: false })).toBe(false);
  });

  it("promotes rebuild-and-start on an unpackaged shell while start/restart keep workbench semantics", () => {
    expect(shouldRefreshBeforeLifecycle("rebuild-and-start", { isPackaged: false, launchBlocking: false })).toBe(true);
    expect(shouldRefreshBeforeLifecycle("rebuild-and-start", { isPackaged: false, launchBlocking: true })).toBe(true);
    expect(shouldRefreshBeforeLifecycle("start", { isPackaged: false, launchBlocking: true })).toBe(false);
    expect(shouldRefreshBeforeLifecycle("restart", { isPackaged: false, launchBlocking: true })).toBe(false);
    expect(shouldRefreshBeforeLifecycle("open", { isPackaged: false, launchBlocking: false })).toBe(false);
    expect(shouldRefreshBeforeLifecycle("", { isPackaged: false, launchBlocking: true })).toBe(false);
  });

  it("probes a resident packaged shell before it knows whether the snapshot is stale", () => {
    expect(shouldProbePeriodicDesktopShell({
      isPackaged: true,
      smoke: false,
      refreshInFlight: false,
      shutdownApproved: false,
    })).toBe(true);
    expect(shouldProbePeriodicDesktopShell({
      isPackaged: false,
      smoke: false,
      refreshInFlight: false,
      shutdownApproved: false,
    })).toBe(false);
    expect(shouldProbePeriodicDesktopShell({
      isPackaged: true,
      smoke: true,
      refreshInFlight: false,
      shutdownApproved: false,
    })).toBe(false);
    expect(shouldProbePeriodicDesktopShell({
      isPackaged: true,
      smoke: false,
      workbenchCloseCanary: true,
      refreshInFlight: false,
      shutdownApproved: false,
    })).toBe(false);
    expect(shouldProbePeriodicDesktopShell({
      isPackaged: true,
      smoke: false,
      refreshInFlight: true,
      shutdownApproved: false,
    })).toBe(false);
    expect(shouldProbePeriodicDesktopShell({
      isPackaged: true,
      smoke: false,
      refreshInFlight: false,
      shutdownApproved: true,
    })).toBe(false);
  });

  it("keeps periodic refresh from stopping for advisory staleness; only launch-blocking staleness refreshes", () => {
    // A periodic probe is not a user action. Advisory frontend staleness
    // (launchBlocking false, windows still served from a usable release)
    // downgrades to "advisory": the caller notifies/logs and must not enter
    // the stop-and-replace transaction. Only a launch-blocking shell may be
    // replaced automatically; unknown launchBlocking is treated as advisory.
    expect(
      decidePeriodicDesktopShellRefresh({
        isPackaged: true,
        smoke: false,
        stale: true,
        launchBlocking: false,
        refreshInFlight: false,
        shutdownApproved: false
      })
    ).toBe("advisory");
    expect(
      decidePeriodicDesktopShellRefresh({
        isPackaged: true,
        smoke: false,
        stale: true,
        refreshInFlight: false,
        shutdownApproved: false
      })
    ).toBe("advisory");
    expect(
      decidePeriodicDesktopShellRefresh({
        isPackaged: true,
        smoke: false,
        stale: false,
        launchBlocking: false,
        refreshInFlight: false,
        shutdownApproved: false
      })
    ).toBe("skip");
    expect(
      decidePeriodicDesktopShellRefresh({
        isPackaged: true,
        smoke: false,
        stale: true,
        launchBlocking: true,
        refreshInFlight: false,
        shutdownApproved: false
      })
    ).toBe("refresh");
  });

  it("falls back to stale semantics when the payload predates launchBlocking", () => {
    const legacy = parseDesktopShellStatus(
      JSON.stringify({ schemaVersion: 1, stale: true, reason: "frontend_source_stale" })
    );
    expect(legacy.launchBlocking).toBe(true);
    const current = parseDesktopShellStatus(
      JSON.stringify({ schemaVersion: 1, stale: true, reason: "frontend_source_stale", launchBlocking: false })
    );
    expect(current.launchBlocking).toBe(false);
    expect(current.stale).toBe(true);
  });

  it("maps first-instance CLI into a post-refresh lifecycle token", () => {
    expect(thenLifecycleFromDesktopCli({ lifecycleCommand: "start", openWorkbench: false })).toBe("start");
    expect(thenLifecycleFromDesktopCli({ lifecycleCommand: "status", openWorkbench: true })).toBe("open");
    expect(thenLifecycleFromDesktopCli({ lifecycleCommand: "toggle", openWorkbench: false })).toBe("");
  });

  it("defers first-window loadURL until start/restart/rebuild-and-start can bring the backend up", () => {
    expect(shouldDeferWorkbenchOpenUntilLifecycleStart("start")).toBe(true);
    expect(shouldDeferWorkbenchOpenUntilLifecycleStart("restart")).toBe(true);
    expect(shouldDeferWorkbenchOpenUntilLifecycleStart("rebuild-and-start")).toBe(true);
    expect(shouldDeferWorkbenchOpenUntilLifecycleStart("open")).toBe(true);
    expect(shouldDeferWorkbenchOpenUntilLifecycleStart("stop")).toBe(false);
    expect(shouldDeferWorkbenchOpenUntilLifecycleStart("")).toBe(false);
  });

  it("inspects through the Python desktop-entry JSON bridge", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({ schemaVersion: 1, stale: true, reason: "provenance_mismatch" })
    );
    const result = await inspectDesktopShell({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      spawnImpl
    });
    expect(result.stale).toBe(true);
    expect(result.reason).toBe("provenance_mismatch");
    const [, args, options] = spawnImpl.mock.calls[0] as [string, string[], Record<string, unknown>];
    expect(args).toEqual([
      resolve("C:/repo", "scripts", "vibelution_desktop_entry.py"),
      "--action",
      "desktop-shell-status",
      "--output",
      "json",
      "--workspace",
      "C:/repo",
      "--python-exe",
      "C:/repo/.venv/Scripts/python.exe",
      "--no-browser"
    ]);
    expect(options.windowsHide).toBe(true);
    const source = readFileSync(new URL("../src/process/desktopShellFreshness.ts", import.meta.url), "utf8");
    const start = source.indexOf("export async function inspectDesktopShell");
    const end = source.indexOf("export async function scheduleDesktopShellRefresh");
    const inspectSource = source.slice(start, end);
    expect(inspectSource).toContain("timeoutMs: PYTHON_JSON_BRIDGE_COMMAND_TIMEOUT_MS");
    expect(inspectSource).not.toContain("PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS");
  });

  it("reads launch readiness through a hidden read-only Python bridge", async () => {
    const spawnImpl = fakeSpawnWithOutput(JSON.stringify({
      schemaVersion: 1, launchBlocking: false, reason: "active_frontend_release"
    }));
    const result = await inspectDesktopShellLaunchReadiness({
      workspaceRoot: "C:/repo", pythonPath: "C:/repo/.venv/Scripts/python.exe", spawnImpl
    });
    expect(result).toEqual({ schemaVersion: 1, launchBlocking: false, reason: "active_frontend_release" });
    const [, args, options] = spawnImpl.mock.calls[0] as [string, string[], Record<string, unknown>];
    expect(args[0]).toBe("-c");
    expect(args[1]).toContain("inspect_desktop_shell_launch_readiness");
    expect(args.at(-1)).toBe("C:/repo");
    expect(options.windowsHide).toBe(true);
  });

  it.each([
    { schemaVersion: 1, reason: "missing_blocking_field" },
    { schemaVersion: 1, launchBlocking: "false", reason: "invalid_boolean" },
    { schemaVersion: 2, launchBlocking: false, reason: "invalid_schema" },
  ])("rejects malformed launch readiness %j", async (payload) => {
    await expect(inspectDesktopShellLaunchReadiness({
      workspaceRoot: "C:/repo", pythonPath: "python.exe", spawnImpl: fakeSpawnWithOutput(JSON.stringify(payload))
    })).rejects.toThrow("invalid result shape");
  });

  it("schedules a detached refresh helper with the live Electron pid", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({ schemaVersion: 1, scheduled: true, helperPid: 88, waitPid: 12, thenLifecycle: "start" })
    );
    const result = await scheduleDesktopShellRefresh({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      waitPid: 12,
      thenLifecycle: "start",
      launchRequestId: "launch_" + "a".repeat(32),
      launchRequestOperation: "restart",
      spawnImpl
    });
    expect(result.helperPid).toBe(88);
    const [, args] = spawnImpl.mock.calls[0] as [string, string[], Record<string, unknown>];
    expect(args).toContain("schedule-desktop-shell-refresh");
    expect(args[args.indexOf("--wait-pid") + 1]).toBe("12");
    expect(args[args.indexOf("--then-lifecycle") + 1]).toBe("start");
    expect(args[args.indexOf("--launch-request-id") + 1]).toBe("launch_" + "a".repeat(32));
    expect(args[args.indexOf("--launch-request-operation") + 1]).toBe("restart");
  });

  it("passes force refresh when the tray restart-all path retries after a failure", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({ schemaVersion: 1, scheduled: true, helperPid: 99, waitPid: 12, thenLifecycle: "" })
    );
    await scheduleDesktopShellRefresh({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      waitPid: 12,
      force: true,
      spawnImpl
    });
    const [, args] = spawnImpl.mock.calls[0] as [string, string[], Record<string, unknown>];
    expect(args).toContain("--force-refresh");
  });

  it("forwards the packaged shell kind so the helper promotes instead of relaunching unpackaged", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({
        schemaVersion: 1,
        scheduled: true,
        helperPid: 97,
        waitPid: 12,
        thenLifecycle: "rebuild-and-start"
      })
    );
    await scheduleDesktopShellRefresh({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      waitPid: 12,
      thenLifecycle: "rebuild-and-start",
      shellKind: "packaged",
      spawnImpl
    });
    const [, args] = spawnImpl.mock.calls[0] as [string, string[], Record<string, unknown>];
    expect(args[args.indexOf("--shell-kind") + 1]).toBe("packaged");
    expect(args[args.indexOf("--then-lifecycle") + 1]).toBe("rebuild-and-start");
  });

  it("ensures unpackaged launcher assets through the Python JSON bridge", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({
        schemaVersion: 1,
        ok: true,
        electron: { rebuilt: false, reason: "current" },
        frontend: { skipped: true, ok: true, reason: "frontend build is current" }
      })
    );
    const result = await ensureLatestLauncher({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      spawnImpl
    });
    expect(result.ok).toBe(true);
    expect(result.frontend?.skipped).toBe(true);
    const [, args] = spawnImpl.mock.calls[0] as [string, string[], Record<string, unknown>];
    expect(args).toContain("ensure-latest-launcher");
  });

  it("streams bounded build stages before completion, ignoring split, noisy and invalid records", async () => {
    let stderr!: (chunk: Buffer) => void;
    let stdout!: (chunk: Buffer) => void;
    let close!: (code: number) => void;
    const spawnImpl = vi.fn(() => ({
      kill: vi.fn(),
      once: (event: string, listener: typeof close) => { if (event === "close") close = listener; },
      stdout: { on: (_event: string, listener: typeof stdout) => { stdout = listener; } },
      stderr: { on: (_event: string, listener: typeof stderr) => { stderr = listener; } }
    }));
    const onProgress = vi.fn();
    const pending = ensureLatestLauncher({ workspaceRoot: "C:/repo", pythonPath: "python.exe", spawnImpl, onProgress });
    stderr(Buffer.from("x".repeat(2_000) + '\n{"event":"launcher-update-progress","phase":"desk'));
    expect(onProgress).not.toHaveBeenCalled();
    stderr(Buffer.from('top"}\n{"event":"launcher-update-progress","phase":"frontend"}\n'));
    expect(onProgress.mock.calls).toEqual([["desktop"], ["frontend"]]);
    for (const record of [
      { event: "launcher-update-progress", phase: "complete" },
      { event: "launcher-update-progress", phase: "package", detail: "private build output" },
      { event: "unrelated", phase: "package" },
    ]) stderr(Buffer.from(JSON.stringify(record) + "\n"));
    expect(onProgress).toHaveBeenCalledTimes(2);
    onProgress.mockImplementationOnce(() => { throw new Error("observer"); });
    stderr(Buffer.from('{"event":"launcher-update-progress","phase":"package"}\n'));
    stdout(Buffer.from('{"schemaVersion":1,"ok":true}'));
    close(0);
    expect(await pending).toMatchObject({ ok: true });
    expect(onProgress).toHaveBeenLastCalledWith("package");
  });

  it("rejects a status payload without schemaVersion", () => {
    expect(() => parseDesktopShellStatus(JSON.stringify({ stale: true }))).toThrow(
      "desktop shell status returned an invalid result shape"
    );
  });

  it("prepares the packaged replacement when the running app is packaged", async () => {
    const spawnImpl = fakeSpawnWithOutput(JSON.stringify({ schemaVersion: 1, ok: true, electron: { prepared: true } }));
    await ensureLatestLauncher({ workspaceRoot: "C:/repo", pythonPath: "C:/repo/.venv/Scripts/python.exe", shellKind: "packaged", spawnImpl });
    const args = spawnImpl.mock.calls[0][1] as string[];
    expect(args[args.indexOf("--shell-kind") + 1]).toBe("packaged");
  });

  it("lets the Python frontend and package owners finish within their combined deadlines", async () => {
    vi.useFakeTimers();
    try {
      const spawnImpl = fakeSpawnWithOutput(JSON.stringify({ schemaVersion: 1, ok: true }));
      const spawn = spawnImpl.getMockImplementation()!;
      spawnImpl.mockImplementation((...args: unknown[]) => {
        const child = spawn(...args) as SpawnChild;
        child.once = (event, listener) => {
          if (event === "close") setTimeout(() => listener(0), 1_440_000);
          return undefined;
        };
        return child;
      });
      const pending = ensureLatestLauncher({ workspaceRoot: "C:/repo", pythonPath: "python.exe", shellKind: "packaged", spawnImpl });
      await vi.advanceTimersByTimeAsync(1_440_000);
      expect((await pending).ok).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("formats tray launcher version from desktop shell status, not workbench HTTP", () => {
    expect(
      formatTrayLauncherFreshness({
        stale: false,
        reason: "current",
        packagedElectronTree: "abcdef1234567890",
        currentElectronTree: "abcdef1234567890"
      })
    ).toEqual({
      current: true,
      label: "Launcher 已是最新 · abcdef123456"
    });
    expect(
      formatTrayLauncherFreshness({
        stale: true,
        reason: "provenance_mismatch",
        packagedElectronTree: "oldtree000001",
        currentElectronTree: "newtree000002"
      }).label
    ).toContain("Launcher 落后本地 desktop/electron · oldtree00000 → newtree00000");
    expect(
      formatTrayLauncherFreshness({
        stale: true,
        reason: "missing_package"
      }).label
    ).toBe("Launcher 壳未就绪 · missing_package");
  });

  it("passes the frontend BuildKey and release facts through the status parser", () => {
    const parsed = parseDesktopShellStatus(JSON.stringify({
      schemaVersion: 1,
      stale: true,
      launchBlocking: false,
      reason: "frontend_source_stale",
      activeFrontendReleaseUsable: true,
      frontendBuildCurrent: false,
      currentFrontendBuildKey: "key-123"
    }));
    expect(parsed.activeFrontendReleaseUsable).toBe(true);
    expect(parsed.frontendBuildCurrent).toBe(false);
    expect(parsed.currentFrontendBuildKey).toBe("key-123");

    const failed = parseDesktopShellStatus(JSON.stringify({
      schemaVersion: 1, stale: true, launchBlocking: false, reason: "frontend_inspection_failed", frontendBuildCurrent: null
    }));
    expect(failed.frontendBuildCurrent).toBeNull();
    expect("currentFrontendBuildKey" in failed).toBe(false);
  });

  it("keys the advisory ensure on the source BuildKey, falling back to the reason", () => {
    expect(advisoryFrontendEnsureKey({ reason: "frontend_source_stale", currentFrontendBuildKey: " key-1 " })).toBe("key-1");
    expect(advisoryFrontendEnsureKey({ reason: "frontend_inspection_failed" })).toBe("reason:frontend_inspection_failed");
    expect(advisoryFrontendEnsureKey({ reason: "", currentFrontendBuildKey: "" })).toBe("reason:unknown");
  });
});

describe("advisory frontend ensure scheduler", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  type Deferred = { resolve: (value: { rebuilt?: boolean; skipped?: boolean }) => void; reject: (error: Error) => void };

  function harness(options: { debounceMs?: number; manual?: boolean } = {}) {
    const events: AdvisoryFrontendEnsureEvent[] = [];
    const runs: AdvisoryFrontendEnsureRequest[] = [];
    const deferred: Deferred[] = [];
    const run = vi.fn(async (request: AdvisoryFrontendEnsureRequest) => {
      runs.push(request);
      if (!options.manual) {
        return { rebuilt: true, skipped: false };
      }
      return await new Promise<{ rebuilt?: boolean; skipped?: boolean }>((resolve, reject) => {
        deferred.push({ resolve, reject });
      });
    });
    const scheduler = createAdvisoryFrontendEnsureScheduler({
      run,
      onEvent: (event) => events.push(event),
      ...(options.debounceMs === undefined ? {} : { debounceMs: options.debounceMs })
    });
    return { scheduler, events, runs, run, deferred, kinds: () => events.map((event) => event.kind) };
  }

  it("runs one debounced background ensure without blocking the caller", async () => {
    const h = harness({ debounceMs: 2_000 });
    expect(h.scheduler.schedule({ buildKey: "key-a", reason: "frontend_source_stale" })).toBe("scheduled");
    expect(h.scheduler.inFlight()).toBe(true);
    expect(h.run).not.toHaveBeenCalled();
    expect(h.kinds()).toEqual(["scheduled"]);
    expect(h.events[0]).toMatchObject({ kind: "scheduled", buildKey: "key-a", reason: "frontend_source_stale", delayMs: 2_000 });

    await vi.advanceTimersByTimeAsync(1_999);
    expect(h.run).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(h.run).toHaveBeenCalledTimes(1);
    expect(h.runs[0]).toEqual({ buildKey: "key-a", reason: "frontend_source_stale" });
    await vi.runAllTimersAsync();
    expect(h.kinds()).toEqual(["scheduled", "started", "completed"]);
    expect(h.events[2]).toMatchObject({ kind: "completed", rebuilt: true, skipped: false });
    expect(h.scheduler.inFlight()).toBe(false);
  });

  it("is idempotent per BuildKey: repeated advisories for one key never re-queue", async () => {
    const h = harness({ debounceMs: 1_000 });
    expect(h.scheduler.schedule({ buildKey: "key-a", reason: "frontend_source_stale" })).toBe("scheduled");
    expect(h.scheduler.schedule({ buildKey: "key-a", reason: "frontend_source_stale" })).toBe("deduplicated");
    await vi.runAllTimersAsync();
    expect(h.run).toHaveBeenCalledTimes(1);

    // The same key after completion (snapshot still stale for a reason the
    // workspace build cannot fix) must not loop every probe tick.
    expect(h.scheduler.schedule({ buildKey: "key-a", reason: "frontend_package_content_mismatch" })).toBe("deduplicated");
    await vi.runAllTimersAsync();
    expect(h.run).toHaveBeenCalledTimes(1);
    expect(h.kinds().filter((kind) => kind === "deduplicated")).toHaveLength(2);

    // A new key is a new source state and runs again.
    expect(h.scheduler.schedule({ buildKey: "key-b", reason: "frontend_source_stale" })).toBe("scheduled");
    await vi.runAllTimersAsync();
    expect(h.run).toHaveBeenCalledTimes(2);
    expect(h.runs[1].buildKey).toBe("key-b");
  });

  it("coalesces a burst within the debounce window to the latest key", async () => {
    const h = harness({ debounceMs: 1_000 });
    h.scheduler.schedule({ buildKey: "key-a", reason: "frontend_source_stale" });
    await vi.advanceTimersByTimeAsync(500);
    h.scheduler.schedule({ buildKey: "key-b", reason: "frontend_source_stale" });
    await vi.advanceTimersByTimeAsync(999);
    expect(h.run).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(h.run).toHaveBeenCalledTimes(1);
    expect(h.runs[0].buildKey).toBe("key-b");
    await vi.runAllTimersAsync();
    expect(h.run).toHaveBeenCalledTimes(1);
  });

  it("keeps the ensure single-flight: a new key waits for the running build", async () => {
    const h = harness({ debounceMs: 100, manual: true });
    h.scheduler.schedule({ buildKey: "key-a", reason: "frontend_source_stale" });
    await vi.advanceTimersByTimeAsync(100);
    expect(h.run).toHaveBeenCalledTimes(1);
    expect(h.scheduler.inFlight()).toBe(true);

    expect(h.scheduler.schedule({ buildKey: "key-b", reason: "frontend_source_stale" })).toBe("scheduled");
    await vi.advanceTimersByTimeAsync(1_000);
    // key-a is still running: key-b must not start concurrently.
    expect(h.run).toHaveBeenCalledTimes(1);

    h.deferred[0].resolve({ rebuilt: false, skipped: true });
    await vi.runAllTimersAsync();
    expect(h.run).toHaveBeenCalledTimes(2);
    expect(h.runs[1].buildKey).toBe("key-b");
    expect(h.kinds()).toEqual(["scheduled", "started", "scheduled", "completed", "scheduled", "started"]);
    expect(h.events[3]).toMatchObject({ kind: "completed", buildKey: "key-a", rebuilt: false, skipped: true });

    h.deferred[1].resolve({ rebuilt: true });
    await vi.runAllTimersAsync();
    expect(h.scheduler.inFlight()).toBe(false);
  });

  it("records a failed ensure as an event and never throws or escalates", async () => {
    const h = harness({ debounceMs: 10, manual: true });
    h.scheduler.schedule({ buildKey: "key-a", reason: "frontend_source_stale" });
    await vi.advanceTimersByTimeAsync(10);
    h.deferred[0].reject(new Error("tsc exploded"));
    await vi.runAllTimersAsync();
    expect(h.kinds()).toEqual(["scheduled", "started", "failed"]);
    expect(h.events[2]).toMatchObject({ kind: "failed", buildKey: "key-a", error: "tsc exploded" });
    expect(h.scheduler.inFlight()).toBe(false);

    // The failed key is not retried on the next tick; a new key still runs.
    expect(h.scheduler.schedule({ buildKey: "key-a", reason: "frontend_source_stale" })).toBe("deduplicated");
    expect(h.scheduler.schedule({ buildKey: "key-b", reason: "frontend_source_stale" })).toBe("scheduled");
    await vi.advanceTimersByTimeAsync(10);
    expect(h.run).toHaveBeenCalledTimes(2);
  });

  it("survives a throwing observer and a synchronously throwing run", async () => {
    const run = vi.fn(() => { throw new Error("sync boom"); });
    const events: AdvisoryFrontendEnsureEvent[] = [];
    const scheduler = createAdvisoryFrontendEnsureScheduler({
      run: run as unknown as (request: AdvisoryFrontendEnsureRequest) => Promise<void>,
      onEvent: (event) => {
        events.push(event);
        throw new Error("observer boom");
      },
      debounceMs: 1
    });
    expect(scheduler.schedule({ buildKey: "key-a", reason: "r" })).toBe("scheduled");
    await vi.runAllTimersAsync();
    expect(events.map((event) => event.kind)).toEqual(["scheduled", "started", "failed"]);
    expect(scheduler.inFlight()).toBe(false);
  });

  it("skips empty keys, honors reset, and cancels on dispose", async () => {
    const h = harness({ debounceMs: 50 });
    expect(h.scheduler.schedule({ buildKey: "", reason: "frontend_source_stale" })).toBe("skipped");
    expect(h.scheduler.schedule({ buildKey: "   ", reason: "frontend_source_stale" })).toBe("skipped");
    expect(h.events).toEqual([]);

    h.scheduler.schedule({ buildKey: "key-a", reason: "r" });
    await vi.runAllTimersAsync();
    expect(h.run).toHaveBeenCalledTimes(1);
    expect(h.scheduler.schedule({ buildKey: "key-a", reason: "r" })).toBe("deduplicated");
    h.scheduler.reset();
    expect(h.scheduler.schedule({ buildKey: "key-a", reason: "r" })).toBe("scheduled");
    await vi.runAllTimersAsync();
    expect(h.run).toHaveBeenCalledTimes(2);

    h.scheduler.schedule({ buildKey: "key-b", reason: "r" });
    expect(h.scheduler.inFlight()).toBe(true);
    h.scheduler.dispose();
    expect(h.scheduler.inFlight()).toBe(false);
    await vi.runAllTimersAsync();
    expect(h.run).toHaveBeenCalledTimes(2);
    expect(h.scheduler.schedule({ buildKey: "key-c", reason: "r" })).toBe("skipped");
  });

  it("uses the default debounce when none is configured", () => {
    const h = harness();
    h.scheduler.schedule({ buildKey: "key-a", reason: "r" });
    expect(h.events[0]).toMatchObject({ kind: "scheduled", delayMs: ADVISORY_FRONTEND_ENSURE_DEBOUNCE_MS });
    h.scheduler.dispose();
  });
});
