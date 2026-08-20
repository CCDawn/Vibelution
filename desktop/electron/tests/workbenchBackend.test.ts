import { describe, expect, it, vi } from "vitest";

import { probeBackendHealthy, waitForBackendHealthy, workbenchHealthUrl } from "../src/process/workbenchBackendHealth.js";
import {
  collectRegisteredHandles,
  retireRegisteredHandles,
  waitForPortRelease
} from "../src/process/workbenchBackendRetire.js";
import {
  executeMainLineWorkbench,
  mainLineBackendIsReachable,
  mainLineBackendIsReusable,
  mainLineRunningCodeIsCurrent,
  resolveNoConsolePython,
  resolveNodeExecutable,
  sameProjectRoot,
  workbenchBackendArgs,
  workbenchBackendEnv
} from "../src/process/workbenchBackend.js";
import { ACTIVE_WORK_BLOCK_MESSAGE_STOP, blockLifecycleIfActiveWork } from "../src/process/activeWorkGuard.js";
import { PythonJsonBridgeError } from "../src/process/pythonJsonBridge.js";
import { createMainLineCommandQueue } from "../src/lifecycle/mainLine/commandQueue.js";
import { runWorkbenchLifecycle, parseWorkbenchLifecycleResult } from "../src/process/workbenchLifecycle.js";

function fakeBackendChild(pid = 4242) {
  return {
    pid,
    exitCode: null as number | null,
    killed: false,
    unref: () => undefined,
    kill: () => true
  };
}

describe("workbenchBackendHealth", () => {
  it("skips HTTP when the TCP connect gate fails", async () => {
    const fetchHealth = vi.fn();
    await expect(
      probeBackendHealthy({
        port: 8000,
        connect: async () => false,
        fetchHealth
      })
    ).resolves.toBe(false);
    expect(fetchHealth).not.toHaveBeenCalled();
  });

  it("requires /api/health 200 after the TCP gate", async () => {
    const fetchHealth = vi.fn().mockResolvedValue({ status: 200 });
    await expect(
      probeBackendHealthy({
        port: 8011,
        host: "127.0.0.1",
        connect: async () => true,
        fetchHealth
      })
    ).resolves.toBe(true);
    expect(fetchHealth).toHaveBeenCalledWith(workbenchHealthUrl(8011, "127.0.0.1"));
  });

  it("treats a non-200 health response as not ready", async () => {
    await expect(
      probeBackendHealthy({
        port: 8000,
        connect: async () => true,
        fetchHealth: async () => ({ status: 503 })
      })
    ).resolves.toBe(false);
  });

  it("waits until the spawned child owns a healthy listener", async () => {
    const fetchHealth = vi.fn()
      .mockResolvedValueOnce({ status: 503 })
      .mockResolvedValueOnce({ status: 200 });
    await waitForBackendHealthy({
      port: 8000,
      timeoutMs: 50,
      pollIntervalMs: 0,
      connect: async () => true,
      fetchHealth
    });
    expect(fetchHealth).toHaveBeenCalledTimes(2);
  });
});

describe("workbenchBackendRetire", () => {
  it("collects registered launcher handles without scanning the process table", () => {
    expect(
      collectRegisteredHandles({
        backendPid: 11,
        backendLaunchPid: 12,
        spawnPid: 12,
        browserLaunchPid: 0
      }, [99, 11])
    ).toEqual([99, 12, 11]);
  });

  it("terminates registered pids and waits for the port to drop", async () => {
    const killed: number[] = [];
    const alive = new Set([11, 12]);
    let listening = true;
    await retireRegisteredHandles({
      pids: [11, 12],
      port: 8000,
      pidAlive: (pid) => alive.has(pid),
      killPid: (pid) => {
        killed.push(pid);
        alive.delete(pid);
      },
      connect: async () => {
        if (alive.size === 0) {
          listening = false;
        }
        return listening;
      },
      delay: async () => undefined
    });
    expect(killed).toEqual([12, 11]);
    await expect(waitForPortRelease({ port: 8000, connect: async () => false })).resolves.toBe(true);
  });
});

describe("resolveNoConsolePython", () => {
  it("prefers the pythonw sibling so DETACHED spawn does not flash a console", () => {
    expect(
      resolveNoConsolePython("C:/repo/.venv/Scripts/python.exe", (path) => path.endsWith("pythonw.exe"))
    ).toBe("C:/repo/.venv/Scripts/pythonw.exe");
  });
});

describe("resolveNodeExecutable", () => {
  it("does not treat Electron or Vibelution.exe as node for frontend rebuild", () => {
    expect(
      resolveNodeExecutable(
        (path) => path.toLowerCase().replace(/\\/g, "/").endsWith("/electron.exe"),
        "C:/app/electron.exe",
        ""
      )
    ).toBe("node");
  });
});

describe("workbenchBackendEnv", () => {
  it("injects slot data home and shared operator config", () => {
    const env = workbenchBackendEnv({
      workspaceRoot: "C:/wt",
      port: 8011,
      dataHome: "C:/slots/ab/data",
      configHome: "C:/Users/op/Documents/Vibelution/config",
      controlPort: 8766,
      allowDirty: true,
      allowNonMain: true
    });
    expect(env.VIBELUTION_DATA_HOME).toBe("C:/slots/ab/data");
    expect(env.VIBELUTION_CONFIG_HOME).toBe("C:/Users/op/Documents/Vibelution/config");
    expect(env.VIBELUTION_LAUNCHER_PORT).toBe("8766");
    expect(env.VIBELUTION_ALLOW_DIRTY_LAUNCH).toBe("1");
  });
});

describe("runWorkbenchLifecycle", () => {
  function harness() {
    let spawned = false;
    const spawnImpl = vi.fn().mockImplementation((command: string, args: string[], options: Record<string, unknown>) => {
      spawned = true;
      expect(command.toLowerCase().endsWith("pythonw.exe") || command.includes("python")).toBe(true);
      expect(args[0]).toContain("web_workbench.py");
      expect(args).toEqual([
        args[0],
        ...workbenchBackendArgs({ host: "127.0.0.1", port: 8000 })
      ]);
      expect(options.windowsHide).toBe(true);
      expect(options.detached).toBe(true);
      expect(String(args)).not.toContain("vibelution_desktop_entry.py");
      expect(String(args)).not.toContain("lifecycle");
      return fakeBackendChild();
    });
    const written: Record<string, unknown>[] = [];
    return {
      spawnImpl,
      written,
      input: {
        workspaceRoot: "C:/repo",
        pythonPath: "C:/repo/.venv/Scripts/python.exe",
        operatorConfigPath: "C:/Users/op/config.toml",
        spawnImpl,
        fileExists: (path: string) => path.endsWith("pythonw.exe") || path.endsWith("index.html"),
        readState: () => ({ backendPid: 0, backendPort: 8000 }),
        writeState: (state: Record<string, unknown>) => {
          written.push(state);
        },
        listActiveWork: () => [],
        ensureFrontend: async () => undefined,
        connect: async () => spawned,
        fetchHealth: async () => ({ status: 200 }),
        pidAlive: () => false,
        killPid: () => undefined
      }
    };
  }

  it("spawns pythonw web_workbench.py instead of the lifecycle CLI", async () => {
    const { spawnImpl, input, written } = harness();
    const result = await runWorkbenchLifecycle({
      ...input,
      operation: "start"
    });
    expect(result.accepted).toBe(true);
    expect(result.operation).toBe("start");
    expect(spawnImpl).toHaveBeenCalledTimes(1);
    expect(written.at(-1)).toMatchObject({
      backendPid: 4242,
      backendPort: 8000,
      lastSource: "electron_main"
    });
  });

  it("coalesces a 1s restart storm into one backend spawn", async () => {
    const { spawnImpl, input } = harness();
    const queue = createMainLineCommandQueue();
    const results = await Promise.all(
      Array.from({ length: 10 }, () =>
        runWorkbenchLifecycle({
          ...input,
          operation: "restart",
          queue
        })
      )
    );
    expect(spawnImpl).toHaveBeenCalledTimes(1);
    expect(new Set(results.map((result) => result.commandId)).size).toBe(1);
    expect(results.every((result) => result.accepted)).toBe(true);
  });

  it("surfaces active-work blocks as structured results without spawning", async () => {
    const { spawnImpl, input } = harness();
    const result = await runWorkbenchLifecycle({
      ...input,
      operation: "stop",
      listActiveWork: () => [{ kind: "chat_turn", runId: "run-1", status: "running", sessionId: "s1" }]
    });
    expect(result).toMatchObject({
      accepted: false,
      code: "active_work_blocked",
      message: ACTIVE_WORK_BLOCK_MESSAGE_STOP
    });
    expect(spawnImpl).not.toHaveBeenCalled();
  });

  it("lets force-stop retire registered handles even when work is active", async () => {
    const killed: number[] = [];
    const alive = new Set([77, 76]);
    const { spawnImpl, input } = harness();
    const result = await runWorkbenchLifecycle({
      ...input,
      operation: "force-stop",
      readState: () => ({ backendPid: 77, backendLaunchPid: 76, backendPort: 8000 }),
      listActiveWork: () => [{ kind: "chat_turn", runId: "run-1", status: "running", sessionId: "s1" }],
      pidAlive: (pid) => alive.has(pid),
      killPid: (pid) => {
        killed.push(pid);
        alive.delete(pid);
      },
      connect: async () => false
    });
    expect(result.accepted).toBe(true);
    expect(spawnImpl).not.toHaveBeenCalled();
    expect(killed).toEqual([77, 76]);
  });

  it("shutdown also retires the registered Runtime Manager daemon pid", async () => {
    const killed: number[] = [];
    const alive = new Set([51, 77]);
    const result = await executeMainLineWorkbench({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operation: "shutdown",
      command: { commandId: "cmd_shutdown", type: "close", operation: "shutdown", noBrowser: true },
      readState: () => ({ backendPid: 51, backendPort: 8000 }),
      writeState: () => undefined,
      listActiveWork: () => [{ kind: "chat_turn", runId: "run-1", status: "running", sessionId: "s1" }],
      pidAlive: (pid) => alive.has(pid),
      killPid: (pid) => {
        killed.push(pid);
        alive.delete(pid);
      },
      connect: async () => false,
      readDaemonPid: () => 77
    });
    expect(result.accepted).toBe(true);
    expect(killed).toEqual([77, 51]);
  });

  it("rejects with the bounded-helper abort classification before spawning", async () => {
    const { spawnImpl, input } = harness();
    const controller = new AbortController();
    controller.abort();
    await expect(
      runWorkbenchLifecycle({
        ...input,
        operation: "start",
        signal: controller.signal
      })
    ).rejects.toMatchObject({ code: "aborted" });
    expect(spawnImpl).not.toHaveBeenCalled();
  });
});

describe("mainLineBackendIsReachable", () => {
  it("reuses a live backend when the known pid is alive or the port listens", async () => {
    await expect(
      mainLineBackendIsReachable("C:/repo", {
        readState: () => ({ backendPid: 4242, backendPort: 8002, host: "127.0.0.1" }),
        pidAlive: (pid) => pid === 4242,
        connect: async () => false
      })
    ).resolves.toBe(true);
    await expect(
      mainLineBackendIsReachable("C:/repo", {
        readState: () => ({ backendPid: 9, backendPort: 8002 }),
        pidAlive: () => false,
        connect: async () => true
      })
    ).resolves.toBe(true);
  });

  it("does not reuse a dead backend with a closed port", async () => {
    await expect(
      mainLineBackendIsReachable("C:/repo", {
        readState: () => ({ backendPid: 9, backendPort: 8002 }),
        pidAlive: () => false,
        connect: async () => false
      })
    ).resolves.toBe(false);
  });
});

describe("mainLineBackendIsReusable", () => {
  const live = {
    readState: () => ({ backendPid: 4242, backendPort: 8002, host: "127.0.0.1" }),
    pidAlive: (pid: number) => pid === 4242,
    connect: async () => true
  };
  const fingerprint = {
    schemaVersion: 1,
    projectRoot: "C:/repo",
    runningHead: "abc123def456"
  };

  it("reuses only when the live backend was started from this checkout HEAD", async () => {
    await expect(
      mainLineBackendIsReusable("C:/repo", {
        ...live,
        fingerprint,
        diskHead: "abc123def456"
      })
    ).resolves.toBe(true);
  });

  it("does not reuse a live backend from another project root", async () => {
    await expect(
      mainLineBackendIsReusable("C:/repo", {
        ...live,
        fingerprint: { ...fingerprint, projectRoot: "D:/other" },
        diskHead: "abc123def456"
      })
    ).resolves.toBe(false);
  });

  it("does not reuse a live backend that is behind disk HEAD", async () => {
    await expect(
      mainLineBackendIsReusable("C:/repo", {
        ...live,
        fingerprint,
        diskHead: "fff000111222"
      })
    ).resolves.toBe(false);
  });

  it("does not reuse when the running-code fingerprint is missing", async () => {
    await expect(
      mainLineBackendIsReusable("C:/repo", {
        ...live,
        fingerprint: null,
        diskHead: "abc123def456"
      })
    ).resolves.toBe(false);
  });

  it("treats slash and case differences as the same Windows project root", () => {
    expect(sameProjectRoot("C:\\repo\\", "c:/repo")).toBe(true);
    expect(mainLineRunningCodeIsCurrent({
      workspaceRoot: "C:\\repo",
      fingerprint: { schemaVersion: 1, projectRoot: "c:/repo", runningHead: "abc" },
      diskHead: "abc"
    })).toBe(true);
  });
});

describe("parseWorkbenchLifecycleResult", () => {
  it("validates the bridge schema", () => {
    expect(() => parseWorkbenchLifecycleResult("{}")).toThrow();
    expect(() =>
      parseWorkbenchLifecycleResult(JSON.stringify({ schemaVersion: 2, accepted: true, operation: "start" }))
    ).toThrow();
    expect(() => parseWorkbenchLifecycleResult("{}")).toThrow(PythonJsonBridgeError);
  });
});

describe("blockLifecycleIfActiveWork", () => {
  it("does not block when the snapshot list is empty", () => {
    expect(blockLifecycleIfActiveWork("stop", [])).toBeNull();
  });
});
