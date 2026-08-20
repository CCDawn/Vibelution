import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import {
  decideLauncherShellRestart,
  decidePackagedDesktopShellRefresh,
  decidePeriodicDesktopShellRefresh,
  formatTrayLauncherFreshness,
  inspectDesktopShell,
  parseDesktopShellStatus,
  scheduleDesktopShellRefresh,
  ensureLatestLauncher,
  shouldDeferWorkbenchOpenUntilLifecycleStart,
  shouldRefreshBeforeLifecycle,
  thenLifecycleFromDesktopCli
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
        refreshInFlight: false,
        shutdownApproved: true
      })
    ).toBe("skip");
    expect(
      decidePeriodicDesktopShellRefresh({
        isPackaged: true,
        smoke: false,
        stale: true,
        refreshInFlight: false,
        shutdownApproved: false
      })
    ).toBe("refresh");
  });

  it("rebuilds a stale packaged launcher instead of relaunching the same asar", () => {
    expect(decideLauncherShellRestart({ isPackaged: true, stale: true })).toBe("rebuild-and-exit");
    expect(decideLauncherShellRestart({ isPackaged: true, stale: false })).toBe("relaunch");
    expect(decideLauncherShellRestart({ isPackaged: false, stale: true })).toBe("relaunch");
    expect(decideLauncherShellRestart({ isPackaged: true, stale: false, forceRefresh: true })).toBe("rebuild-and-exit");
    expect(decideLauncherShellRestart({ isPackaged: false, stale: false, forceRefresh: true })).toBe("ensure-and-relaunch");
  });

  it("keeps start/restart/rebuild-and-start on a stale packaged shell", () => {
    expect(shouldRefreshBeforeLifecycle("start", { isPackaged: true, stale: true })).toBe(true);
    expect(shouldRefreshBeforeLifecycle("stop", { isPackaged: true, stale: true })).toBe(false);
    expect(shouldRefreshBeforeLifecycle("start", { isPackaged: false, stale: true })).toBe(false);
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
    expect(shouldDeferWorkbenchOpenUntilLifecycleStart("open")).toBe(false);
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
      spawnImpl
    });
    expect(result.helperPid).toBe(88);
    const [, args] = spawnImpl.mock.calls[0] as [string, string[], Record<string, unknown>];
    expect(args).toContain("schedule-desktop-shell-refresh");
    expect(args[args.indexOf("--wait-pid") + 1]).toBe("12");
    expect(args[args.indexOf("--then-lifecycle") + 1]).toBe("start");
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

  it("rejects a status payload without schemaVersion", () => {
    expect(() => parseDesktopShellStatus(JSON.stringify({ stale: true }))).toThrow(
      "desktop shell status returned an invalid result shape"
    );
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
});
