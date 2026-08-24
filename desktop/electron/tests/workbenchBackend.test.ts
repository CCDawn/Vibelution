import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { probeBackendHealthy, waitForBackendHealthy, workbenchHealthUrl } from "../src/process/workbenchBackendHealth.js";
import {
  collectRegisteredHandles,
  reconcileDeadRegisteredHandles,
  requestGracefulWorkbenchShutdown,
  retireRegisteredHandles,
  waitForPortRelease
} from "../src/process/workbenchBackendRetire.js";
import {
  classifyWorkbenchPortOccupant,
  clearWorkbenchLauncherRuntimeState,
  executeMainLineWorkbench,
  ensureFrontendRelease,
  ensureFrontendBuild,
  FRONTEND_BUILD_TIMEOUT_MS,
  mainLineBackendIsReachable,
  mainLineBackendIsReusable,
  mainLineRunningCodeIsCurrent,
  resolveBindableWorkbenchPort,
  reclaimStaleWorkbenchBackend,
  resolveNoConsolePython,
  resolveNodeExecutable,
  runWaitable,
  sameProjectRoot,
  spawnWorkbenchBackend,
  type WorkbenchFrontendBuildChild,
  writeLauncherStateFile,
  workbenchBackendArgs,
  workbenchBackendEnv
} from "../src/process/workbenchBackend.js";
import { resolveCanonicalRuntimeHome } from "../src/lifecycle/projectStoragePaths.js";
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

function frontendBuildChild(): {
  child: WorkbenchFrontendBuildChild;
  close: (code?: number | null, signal?: NodeJS.Signals | null) => void;
  error: (error: Error) => void;
} {
  let errorListener: ((error: Error) => void) | undefined;
  let closeListener: ((code: number | null, signal: NodeJS.Signals | null) => void) | undefined;
  const child: WorkbenchFrontendBuildChild = {
    kill: vi.fn(() => true),
    once: (event: "error" | "close", listener: ((error: Error) => void) | ((code: number | null, signal: NodeJS.Signals | null) => void)) => {
      if (event === "error") {
        errorListener = listener as (error: Error) => void;
      } else {
        closeListener = listener as (code: number | null, signal: NodeJS.Signals | null) => void;
      }
      return child;
    }
  };
  return {
    child,
    close: (code = 0, signal = null) => closeListener?.(code, signal),
    error: (error) => errorListener?.(error)
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

  it("requires /api/health 200 with routesReady:true after the TCP gate", async () => {
    const fetchHealth = vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({ status: "ok", routesReady: true })
    });
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

  it("treats 200 with routesReady:false as not ready so the window never opens early", async () => {
    await expect(
      probeBackendHealthy({
        port: 8000,
        connect: async () => true,
        fetchHealth: async () => ({ status: 200, json: async () => ({ status: "ok", routesReady: false }) })
      })
    ).resolves.toBe(false);
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

  it("treats a 200 response without a health payload as not ready", async () => {
    await expect(
      probeBackendHealthy({
        port: 8000,
        connect: async () => true,
        fetchHealth: async () => ({ status: 200 })
      })
    ).resolves.toBe(false);
  });

  it("waits until the spawned child owns a healthy listener", async () => {
    const fetchHealth = vi.fn()
      .mockResolvedValueOnce({ status: 503 })
      .mockResolvedValueOnce({ status: 200, json: async () => ({ status: "ok", routesReady: true }) });
    await waitForBackendHealthy({
      port: 8000,
      timeoutMs: 50,
      pollIntervalMs: 0,
      connect: async () => true,
      fetchHealth
    });
    expect(fetchHealth).toHaveBeenCalledTimes(2);
  });

  it("fails immediately when the spawned child reports an error", async () => {
    const connect = vi.fn(async () => true);
    await expect(
      waitForBackendHealthy({
        port: 8000,
        timeoutMs: 45_000,
        childError: () => new Error("spawn ENOENT"),
        connect,
        fetchHealth: async () => ({ status: 503 })
      })
    ).rejects.toThrow("spawn ENOENT");
    expect(connect).not.toHaveBeenCalled();
  });
});

describe("workbenchBackendRetire", () => {
  it("waits for both the listener and backend pid after an accepted graceful shutdown", async () => {
    const connect = vi.fn()
      .mockResolvedValueOnce(true)
      .mockResolvedValueOnce(false);
    const pidAlive = vi.fn()
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);
    const request = vi.fn().mockResolvedValue({ status: 202 });

    await expect(
      requestGracefulWorkbenchShutdown({
        port: 8000,
        backendPid: 4242,
        controlToken: "test-control-token",
        request,
        connect,
        pidAlive,
        delay: async () => undefined
      })
    ).resolves.toMatchObject({ requested: true, completed: true, status: 202 });
    expect(request).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/runtime/shutdown",
      expect.objectContaining({
        method: "POST",
        signal: expect.any(AbortSignal),
        headers: { "X-Vibelution-Control-Token": "test-control-token" }
      })
    );
  });

  it("treats active-work refusal as a fallback signal without polling", async () => {
    const connect = vi.fn().mockResolvedValue(true);
    await expect(
      requestGracefulWorkbenchShutdown({
        port: 8000,
        controlToken: "test-control-token",
        request: async () => ({ status: 409 }),
        connect,
        delay: async () => undefined
      })
    ).resolves.toMatchObject({ requested: false, completed: false, status: 409 });
    expect(connect).not.toHaveBeenCalled();
  });

  it("uses the existing Electron control token when no override is supplied", async () => {
    const previousToken = process.env.VIBELUTION_WEB_CONTROL_TOKEN;
    process.env.VIBELUTION_WEB_CONTROL_TOKEN = "environment-control-token";
    const request = vi.fn().mockResolvedValue({ status: 409 });
    try {
      await requestGracefulWorkbenchShutdown({
        port: 8000,
        request,
        delay: async () => undefined
      });
    } finally {
      if (previousToken === undefined) {
        delete process.env.VIBELUTION_WEB_CONTROL_TOKEN;
      } else {
        process.env.VIBELUTION_WEB_CONTROL_TOKEN = previousToken;
      }
    }
    expect(request).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/runtime/shutdown",
      expect.objectContaining({
        headers: { "X-Vibelution-Control-Token": "environment-control-token" }
      })
    );
  });

  it("bootstraps a backend token only after health identity is verified", async () => {
    const previousToken = process.env.VIBELUTION_WEB_CONTROL_TOKEN;
    delete process.env.VIBELUTION_WEB_CONTROL_TOKEN;
    const request = vi.fn()
      .mockResolvedValueOnce({ status: 200, json: async () => ({ controlToken: "backend-control-token" }) })
      .mockResolvedValueOnce({ status: 202 });
    const connect = vi.fn()
      .mockResolvedValueOnce(true)
      .mockResolvedValueOnce(false);
    const pidAlive = vi.fn()
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false);
    try {
      await expect(
        requestGracefulWorkbenchShutdown({
          port: 8000,
          backendPid: 4242,
          healthVerified: true,
          request,
          connect,
          pidAlive,
          delay: async () => undefined
        })
      ).resolves.toMatchObject({ requested: true, completed: true, status: 202 });
    } finally {
      if (previousToken === undefined) {
        delete process.env.VIBELUTION_WEB_CONTROL_TOKEN;
      } else {
        process.env.VIBELUTION_WEB_CONTROL_TOKEN = previousToken;
      }
    }
    expect(request).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/control-token",
      expect.objectContaining({ method: "GET", signal: expect.any(AbortSignal) })
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/runtime/shutdown",
      expect.objectContaining({
        method: "POST",
        headers: { "X-Vibelution-Control-Token": "backend-control-token" }
      })
    );
  });

  it("fails closed instead of bootstrapping a token without verified backend identity", async () => {
    const previousToken = process.env.VIBELUTION_WEB_CONTROL_TOKEN;
    delete process.env.VIBELUTION_WEB_CONTROL_TOKEN;
    const request = vi.fn();
    try {
      await expect(
        requestGracefulWorkbenchShutdown({
          port: 8000,
          request,
          delay: async () => undefined
        })
      ).resolves.toMatchObject({
        requested: false,
        completed: false,
        reason: expect.stringContaining("control token is unavailable")
      });
    } finally {
      if (previousToken === undefined) {
        delete process.env.VIBELUTION_WEB_CONTROL_TOKEN;
      } else {
        process.env.VIBELUTION_WEB_CONTROL_TOKEN = previousToken;
      }
    }
    expect(request).not.toHaveBeenCalled();
  });

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

  it("reconciles a dead registered handle only after its identity and port are proven safe", async () => {
    await expect(
      reconcileDeadRegisteredHandles({
        pids: [11],
        port: 8000,
        expectedIdentities: {
          "11": { pid: 11, createTime: 123, executable: "C:/Python/python.exe" }
        },
        pidAlive: () => false,
        connect: async () => false
      })
    ).resolves.toEqual({
      reconciledPids: [11],
      retainedPids: [],
      reason: "reconciled 1 dead registered handle(s) after port 8000 was released"
    });
  });

  it("retains a dead handle when its persisted identity does not bind to that pid", async () => {
    await expect(
      reconcileDeadRegisteredHandles({
        pids: [11],
        port: 8000,
        expectedIdentities: {
          "11": { pid: 12, createTime: 123, executable: "C:/Python/python.exe" }
        },
        pidAlive: () => false,
        connect: async () => false
      })
    ).resolves.toMatchObject({ reconciledPids: [], retainedPids: [11] });
  });

  it("retains a handle when the pid is alive, even if the listener is released", async () => {
    await expect(
      reconcileDeadRegisteredHandles({
        pids: [11],
        port: 8000,
        expectedIdentities: {
          "11": { pid: 11, createTime: 123, executable: "C:/Python/python.exe" }
        },
        pidAlive: () => true,
        connect: async () => false
      })
    ).resolves.toMatchObject({ reconciledPids: [], retainedPids: [11] });
  });

  it("retains every registered handle while the owned backend port is still listening", async () => {
    await expect(
      reconcileDeadRegisteredHandles({
        pids: [11, 12],
        port: 8000,
        expectedIdentities: {
          "11": { pid: 11, createTime: 123, executable: "C:/Python/python.exe" },
          "12": { pid: 12, createTime: 456, executable: "C:/Python/python.exe" }
        },
        pidAlive: () => false,
        connect: async () => true
      })
    ).resolves.toMatchObject({ reconciledPids: [], retainedPids: [11, 12] });
  });

  it("terminates registered pids and waits for the port to drop", async () => {
    const killed: number[] = [];
    const alive = new Set([11, 12]);
    let listening = true;
    await retireRegisteredHandles({
      pids: [11, 12],
      port: 8000,
      pidAlive: (pid) => alive.has(pid),
      ownedDirectPids: [11, 12],
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

  it("fails retirement when the workbench port remains bound", async () => {
    let now = 0;
    await expect(
      retireRegisteredHandles({
        pids: [],
        port: 8000,
        connect: async () => true,
        now: () => now,
        delay: async (ms) => {
          now += ms;
        }
      })
    ).rejects.toThrow("Failed to release workbench port 8000");
  });

  it("refuses to kill a live registered browser handle without ownership evidence", async () => {
    const killPid = vi.fn();
    await expect(
      retireRegisteredHandles({
        pids: [9911],
        pidAlive: () => true,
        killPid,
        connect: async () => false
      })
    ).rejects.toThrow("unverified registered process handles: 9911");
    expect(killPid).not.toHaveBeenCalled();
  });

  it("propagates a failed owned-tree result instead of accepting root-pid death", async () => {
    const reported: number[] = [];
    await expect(
      retireRegisteredHandles({
        pids: [11, 9911],
        pidAlive: () => true,
        treePids: [11],
        terminateProcessTree: async () => false,
        reportUnverified: (pids) => reported.push(...pids),
        connect: async () => false
      })
    ).rejects.toThrow("process tree 11");
    expect(reported).toEqual([9911]);
  });

  it("does not accept a dead tree root as proof that its descendants are gone", async () => {
    const terminateProcessTree = vi.fn(async () => false);
    await expect(
      retireRegisteredHandles({
        pids: [11],
        pidAlive: () => false,
        treePids: [11],
        expectedIdentities: {
          "11": { pid: 11, createTime: 1, executable: "C:/Python/python.exe" }
        },
        terminateProcessTree
      })
    ).rejects.toThrow("process tree 11");
    expect(terminateProcessTree).toHaveBeenCalledWith(11, expect.objectContaining({ pid: 11 }));
  });
});

describe("classifyWorkbenchPortOccupant", () => {
  it("reports free when nothing listens on the port", async () => {
    await expect(
      classifyWorkbenchPortOccupant({
        port: 8000,
        workspaceRoot: "C:/repo",
        connect: async () => false
      })
    ).resolves.toEqual({ kind: "free" });
  });

  it("identifies a same-project stale backend by health identity", async () => {
    await expect(
      classifyWorkbenchPortOccupant({
        port: 8002,
        workspaceRoot: "C:/repo",
        connect: async () => true,
        fetchHealth: async () => ({
          status: 200,
          json: async () => ({ status: "ok", routesReady: true, pid: 34652, workspaceRoot: "C:\\repo\\" })
        })
      })
    ).resolves.toEqual({ kind: "same-project-backend", pid: 34652 });
  });

  it("flags a same-project backend without a reported pid as legacy", async () => {
    await expect(
      classifyWorkbenchPortOccupant({
        port: 8002,
        workspaceRoot: "C:/repo",
        connect: async () => true,
        fetchHealth: async () => ({
          status: 200,
          json: async () => ({ status: "ok", routesReady: true, workspaceRoot: "C:/repo" })
        })
      })
    ).resolves.toEqual({ kind: "same-project-legacy-backend" });
  });

  it("classifies a different workspaceRoot as another project", async () => {
    await expect(
      classifyWorkbenchPortOccupant({
        port: 8000,
        workspaceRoot: "C:/repo",
        connect: async () => true,
        fetchHealth: async () => ({
          status: 200,
          json: async () => ({ status: "ok", routesReady: true, pid: 11, workspaceRoot: "D:/other" })
        })
      })
    ).resolves.toEqual({ kind: "other-project-backend", workspaceRoot: "D:/other" });
  });

  it("classifies a non-Vibelution listener as unknown after bounded retries", async () => {
    const fetchHealth = vi.fn().mockResolvedValue({ status: 404 });
    await expect(
      classifyWorkbenchPortOccupant({
        port: 8000,
        workspaceRoot: "C:/repo",
        connect: async () => true,
        fetchHealth
      })
    ).resolves.toEqual({ kind: "unknown" });
    expect(fetchHealth).toHaveBeenCalledTimes(3);
  });
});

describe("reclaimStaleWorkbenchBackend", () => {
  it("prefers graceful shutdown after health identity is verified", async () => {
    const alive = new Set([4242]);
    const terminateProcessTree = vi.fn();
    const gracefulShutdown = vi.fn(async () => {
      alive.delete(4242);
      return { requested: true, completed: true, status: 202, reason: "closed" };
    });
    const result = await reclaimStaleWorkbenchBackend({
      port: 8012,
      workspaceRoot: "C:/repo",
      connect: async () => alive.has(4242),
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 4242, workspaceRoot: "C:/repo" })
      }),
      pidAlive: (pid) => alive.has(pid),
      terminateProcessTree,
      expectedIdentities: {
        "4242": { pid: 4242, createTime: 1, executable: "C:/Python/python.exe" }
      },
      gracefulShutdown,
      delay: async () => undefined
    });

    expect(result).toMatchObject({ reclaimed: true, verifiedPid: 4242 });
    expect(gracefulShutdown).toHaveBeenCalledOnce();
    expect(terminateProcessTree).not.toHaveBeenCalled();
  });

  it("only falls back to the owned process tree after an explicit force authorization", async () => {
    const alive = new Set([4242]);
    const terminateProcessTree = vi.fn(async (pid: number) => {
      alive.delete(pid);
      return true;
    });
    const gracefulShutdown = vi.fn(async () => ({
      requested: false,
      completed: false,
      status: 409,
      reason: "active work"
    }));
    const result = await reclaimStaleWorkbenchBackend({
      port: 8012,
      workspaceRoot: "C:/repo",
      connect: async () => alive.has(4242),
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 4242, workspaceRoot: "C:/repo" })
      }),
      pidAlive: (pid) => alive.has(pid),
      terminateProcessTree,
      expectedIdentities: {
        "4242": { pid: 4242, createTime: 1, executable: "C:/Python/python.exe" }
      },
      gracefulShutdown,
      forceRetireOnActiveWorkRefusal: true,
      delay: async () => undefined
    });

    expect(result).toMatchObject({ reclaimed: true, verifiedPid: 4242 });
    expect(gracefulShutdown).toHaveBeenCalledOnce();
    expect(terminateProcessTree).toHaveBeenCalledWith(4242, expect.objectContaining({ pid: 4242 }));
  });

  it("preserves the backend tree when graceful shutdown is refused by active work", async () => {
    const alive = new Set([4242]);
    const terminateProcessTree = vi.fn(async () => {
      alive.delete(4242);
      return true;
    });
    const gracefulShutdown = vi.fn(async () => ({
      requested: false,
      completed: false,
      status: 409,
      reason: "backend refused graceful shutdown because active work is running"
    }));
    const result = await reclaimStaleWorkbenchBackend({
      port: 8012,
      workspaceRoot: "C:/repo",
      connect: async () => alive.has(4242),
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 4242, workspaceRoot: "C:/repo" })
      }),
      pidAlive: (pid) => alive.has(pid),
      terminateProcessTree,
      expectedIdentities: {
        "4242": { pid: 4242, createTime: 1, executable: "C:/Python/python.exe" }
      },
      gracefulShutdown,
      delay: async () => undefined
    });

    expect(result).toMatchObject({
      reclaimed: false,
      activeWorkBlocked: true,
      verifiedPid: 4242
    });
    expect(result.reason).toContain("active work");
    expect(gracefulShutdown).toHaveBeenCalledOnce();
    expect(terminateProcessTree).not.toHaveBeenCalled();
    expect(alive.has(4242)).toBe(true);
  });

  it("does not claim a registered pid is safe when the health identity is not confirmed", async () => {
    const result = await reclaimStaleWorkbenchBackend({
      port: 8012,
      workspaceRoot: "C:/repo",
      connect: async () => true,
      fetchHealth: async () => ({ status: 404 }),
      pidAlive: () => true,
      killPid: vi.fn()
    });

    expect(result.reclaimed).toBe(false);
    expect(result.reason).toContain("unknown");
  });

  it("treats an already released port as a confirmed close", async () => {
    await expect(
      reclaimStaleWorkbenchBackend({
        port: 8012,
        workspaceRoot: "C:/repo",
        connect: async () => false
      })
    ).resolves.toMatchObject({ reclaimed: true });
  });

  it("does not confirm close when a registered backend pid is alive before listen", async () => {
    await expect(
      reclaimStaleWorkbenchBackend({
        port: 8012,
        workspaceRoot: "C:/repo",
        connect: async () => false,
        registeredPids: [4242],
        pidAlive: () => true
      })
    ).resolves.toMatchObject({
      reclaimed: false,
      reason: expect.stringContaining("registered backend pid 4242")
    });
  });

  it("does not reclaim a released port when the registered tree root is gone but descendants are unverified", async () => {
    const terminateProcessTree = vi.fn(async () => false);
    await expect(
      reclaimStaleWorkbenchBackend({
        port: 8012,
        workspaceRoot: "C:/repo",
        connect: async () => false,
        registeredPids: [4242],
        expectedIdentities: {
          "4242": { pid: 4242, createTime: 1, executable: "C:/Python/python.exe" }
        },
        pidAlive: () => false,
        terminateProcessTree
      })
    ).resolves.toMatchObject({
      reclaimed: false,
      reason: expect.stringContaining("retirement was not verified")
    });
    expect(terminateProcessTree).toHaveBeenCalledWith(4242, expect.objectContaining({ pid: 4242 }));
  });

  it("does not confirm close when a verified backend pid survives port release", async () => {
    let clock = 0;
    let listening = true;
    await expect(
      reclaimStaleWorkbenchBackend({
        port: 8012,
        workspaceRoot: "C:/repo",
        connect: async () => {
          const current = listening;
          listening = false;
          return current;
        },
        fetchHealth: async () => ({
          status: 200,
          json: async () => ({ status: "ok", routesReady: true, pid: 4242, workspaceRoot: "C:/repo" })
        }),
        pidAlive: () => true,
        killPid: () => undefined,
        now: () => (clock += 10_000),
        delay: async () => undefined
      })
    ).resolves.toMatchObject({
      reclaimed: false,
      reason: expect.stringContaining("remains alive after port")
    });
  });

  it("does not confirm stale reclaim when the owned tree helper reports failure", async () => {
    const result = await reclaimStaleWorkbenchBackend({
      port: 8012,
      workspaceRoot: "C:/repo",
      connect: async () => true,
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 4242, workspaceRoot: "C:/repo" })
      }),
      pidAlive: () => true,
      terminateProcessTree: async () => false,
      gracefulShutdown: async () => ({ requested: false, completed: false, reason: "refused" })
    });
    expect(result).toMatchObject({ reclaimed: false, verifiedPid: 4242 });
    expect(result.reason).toContain("not verified");
  });

  it("fails closed when a health-identified backend exits before tree retirement", async () => {
    const terminateProcessTree = vi.fn(async () => false);
    const result = await reclaimStaleWorkbenchBackend({
      port: 8012,
      workspaceRoot: "C:/repo",
      connect: async () => true,
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 4242, workspaceRoot: "C:/repo" })
      }),
      pidAlive: () => false,
      terminateProcessTree,
      expectedIdentities: {
        "4242": { pid: 4242, createTime: 1, executable: "C:/Python/python.exe" }
      }
    });

    expect(result).toMatchObject({ reclaimed: false, verifiedPid: 4242 });
    expect(result.reason).toContain("retirement was not verified");
    expect(terminateProcessTree).toHaveBeenCalledWith(4242, expect.objectContaining({ pid: 4242 }));
  });

  it("marks the same-project health identity before graceful token bootstrap", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ status: 200, json: async () => ({ controlToken: "backend-control-token" }) })
      .mockResolvedValueOnce({ status: 202 });
    const connect = vi.fn()
      .mockResolvedValueOnce(true)
      .mockResolvedValue(false);
    const pidAlive = vi.fn()
      .mockReturnValueOnce(true)
      .mockReturnValue(false);
    const gracefulShutdown = (input: Parameters<typeof requestGracefulWorkbenchShutdown>[0]) =>
      requestGracefulWorkbenchShutdown({ ...input, request });

    await expect(
      reclaimStaleWorkbenchBackend({
        port: 8012,
        workspaceRoot: "C:/repo",
        connect,
        fetchHealth: async () => ({
          status: 200,
          json: async () => ({ status: "ok", routesReady: true, pid: 4242, workspaceRoot: "C:/repo" })
        }),
        pidAlive,
        gracefulShutdown,
        delay: async () => undefined
      })
    ).resolves.toMatchObject({ reclaimed: true });

    expect(request).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8012/api/control-token",
      expect.objectContaining({ method: "GET" })
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8012/api/runtime/shutdown",
      expect.objectContaining({
        method: "POST",
        headers: { "X-Vibelution-Control-Token": "backend-control-token" }
      })
    );
  });
});

describe("resolveBindableWorkbenchPort", () => {
  it("binds the preferred port when it is free", async () => {
    await expect(
      resolveBindableWorkbenchPort({
        preferred: 8000,
        workspaceRoot: "C:/repo",
        connect: async () => false
      })
    ).resolves.toEqual({ port: 8000, note: "" });
  });

  it("reclaims a stale same-project backend and rebinds the preferred port", async () => {
    const alive = new Set([34652]);
    let listening = true;
    const result = await resolveBindableWorkbenchPort({
      preferred: 8002,
      workspaceRoot: "C:/repo",
      connect: async (port) => port === 8002 && listening,
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 34652, workspaceRoot: "C:\\repo" })
      }),
      pidAlive: (pid) => alive.has(pid),
      killPid: (pid) => {
        alive.delete(pid);
        listening = false;
      },
      delay: async () => undefined
    });
    expect(result.port).toBe(8002);
    expect(result.note).toContain("reclaimed");
  });

  it("fails loudly when a stale same-project backend does not release the port", async () => {
    let clock = 0;
    await expect(
      resolveBindableWorkbenchPort({
        preferred: 8002,
        workspaceRoot: "C:/repo",
        connect: async () => true,
        fetchHealth: async () => ({
          status: 200,
          json: async () => ({ status: "ok", routesReady: true, pid: 34652, workspaceRoot: "C:/repo" })
        }),
        pidAlive: () => true,
        killPid: () => undefined,
        now: () => (clock += 10_000),
        delay: async () => undefined
      })
    ).rejects.toThrow("still held by stale backend pid 34652");
  });

  it("relocates when another Vibelution project holds the preferred port", async () => {
    const result = await resolveBindableWorkbenchPort({
      preferred: 8000,
      workspaceRoot: "C:/repo",
      connect: async (port) => port === 8000,
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 11, workspaceRoot: "D:/other" })
      })
    });
    expect(result.port).toBe(8001);
    expect(result.note).toContain("another Vibelution project");
  });

  it("fails loudly when an unknown process holds the preferred port", async () => {
    const fetchHealth = vi.fn().mockRejectedValue(new Error("fetch failed"));
    await expect(
      resolveBindableWorkbenchPort({
        preferred: 8000,
        workspaceRoot: "C:/repo",
        connect: async () => true,
        fetchHealth
      })
    ).rejects.toThrow("occupied by an unknown process");
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
  it("does not treat Electron or Vibelution.exe as node for the compatibility build helper", () => {
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

describe("writeLauncherStateFile", () => {
  it("publishes complete JSON without leaving a shared temp file", () => {
    const dir = mkdtempSync(join(tmpdir(), "vibelution-workbench-state-"));
    try {
      const path = join(dir, "state.json");
      const sharedTempPath = `${path}.tmp`;
      writeFileSync(sharedTempPath, "sentinel", "utf8");
      writeLauncherStateFile(path, { backendPort: 8011, phase: "steady" });

      expect(JSON.parse(readFileSync(path, "utf8"))).toEqual({
        backendPort: 8011,
        phase: "steady"
      });
      expect(readFileSync(sharedTempPath, "utf8")).toBe("sentinel");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("clearWorkbenchLauncherRuntimeState", () => {
  it("removes both checkout and canonical launcher state after close", () => {
    const dir = mkdtempSync(join(tmpdir(), "vibelution-workbench-runtime-clear-"));
    const previousProjectsHome = process.env.VIBELUTION_PROJECTS_HOME;
    try {
      process.env.VIBELUTION_PROJECTS_HOME = join(dir, "projects");
      mkdirSync(join(dir, ".vibelution"), { recursive: true });
      writeFileSync(join(dir, ".vibelution", "project.json"), JSON.stringify({ projectId: "project-clear" }), "utf8");
      const runtimeDir = join(dir, ".runtime", "launcher");
      const canonicalRuntimeDir = join(resolveCanonicalRuntimeHome(dir) || "", "launcher");
      mkdirSync(runtimeDir, { recursive: true });
      mkdirSync(canonicalRuntimeDir, { recursive: true });
      const paths = [
        join(runtimeDir, "state.json"),
        join(runtimeDir, "ports.json"),
        join(canonicalRuntimeDir, "state.json"),
        join(canonicalRuntimeDir, "ports.json")
      ];
      writeFileSync(paths[0], JSON.stringify({ backendPid: 41, backendPort: 8012 }), "utf8");
      writeFileSync(paths[1], JSON.stringify({ backendPort: 8012 }), "utf8");
      writeFileSync(paths[2], JSON.stringify({ backendPid: 42, backendPort: 8012 }), "utf8");
      writeFileSync(paths[3], JSON.stringify({ backendPort: 8012 }), "utf8");

      expect(clearWorkbenchLauncherRuntimeState(dir)).toMatchObject({ cleared: true, removedCount: 4 });
      expect(paths.every((path) => !existsSync(path))).toBe(true);
    } finally {
      if (previousProjectsHome === undefined) {
        delete process.env.VIBELUTION_PROJECTS_HOME;
      } else {
        process.env.VIBELUTION_PROJECTS_HOME = previousProjectsHome;
      }
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("frontend build supervision", () => {
  it("routes release preparation through the shared Python builder", async () => {
    const runBridge = vi.fn(async (input) => {
      expect(input.pythonPath).toBe("C:/repo/.venv/Scripts/python.exe");
      expect(input.cwd).toBe("C:/repo");
      expect(input.args).toEqual([
        "C:\\repo\\scripts\\vibelution_desktop_entry.py",
        "--action",
        "ensure-frontend-build",
        "--workspace",
        "C:/repo",
        "--output",
        "json"
      ]);
      expect(input.mutation).toBe(true);
      return JSON.stringify({
        ok: true,
        skipped: false,
        rebuilt: true,
        buildKey: "build-key",
        release: "C:/repo/web/.vibelution-builds/release-build-key"
      });
    });

    await expect(ensureFrontendRelease({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      runBridge
    })).resolves.toEqual({
      skipped: false,
      rebuilt: true,
      buildKey: "build-key",
      release: "C:/repo/web/.vibelution-builds/release-build-key"
    });
    expect(runBridge).toHaveBeenCalledOnce();
  });

  it("does not use a direct-child kill when a build has no verifiable tree identity", async () => {
    const harness = frontendBuildChild();
    Object.assign(harness.child, { pid: 5151 });
    await expect(
      runWaitable("node", ["tsc", "-b"], "C:/repo/web", {
        phase: "tsc",
        timeoutMs: 10,
        spawnImpl: () => harness.child
      })
    ).rejects.toMatchObject({
      name: "WorkbenchFrontendBuildError",
      code: "frontend_build_failed",
      phase: "tsc"
    });
    expect(harness.child.kill).not.toHaveBeenCalled();
  });

  it("does not use a direct-child kill when an unverified build is aborted", async () => {
    const harness = frontendBuildChild();
    Object.assign(harness.child, { pid: 5151 });
    const controller = new AbortController();
    const pending = runWaitable("node", ["vite", "build"], "C:/repo/web", {
      phase: "vite",
      signal: controller.signal,
      timeoutMs: FRONTEND_BUILD_TIMEOUT_MS,
      spawnImpl: () => harness.child
    });
    controller.abort();
    await expect(pending).rejects.toMatchObject({
      code: "frontend_build_failed",
      phase: "vite"
    });
    expect(harness.child.kill).not.toHaveBeenCalled();
  });

  it("uses the verified frontend process tree when a build is interrupted", async () => {
    const harness = frontendBuildChild();
    Object.assign(harness.child, { pid: 5151 });
    const terminateProcessTree = vi.fn(async () => false);
    await expect(
      runWaitable("node", ["C:/repo/web/node_modules/vite/bin/vite.js", "build"], "C:/repo/web", {
        phase: "vite",
        workspaceRoot: "C:/repo",
        pythonPath: "C:/repo/.venv/Scripts/python.exe",
        timeoutMs: 10,
        spawnImpl: () => harness.child,
        captureProcessIdentity: async () => ({
          pid: 5151,
          createTime: 1,
          executable: "C:/Program Files/nodejs/node.exe"
        }),
        terminateProcessTree
      })
    ).rejects.toMatchObject({ code: "frontend_build_failed", phase: "vite" });
    expect(terminateProcessTree).toHaveBeenCalledWith(5151, expect.objectContaining({ pid: 5151 }));
    expect(harness.child.kill).not.toHaveBeenCalled();
  });

  it("fails closed after a non-zero root exit when tree retirement cannot be verified", async () => {
    const harness = frontendBuildChild();
    Object.assign(harness.child, { pid: 5151 });
    const terminateProcessTree = vi.fn(async () => false);
    const pending = runWaitable("node", ["tsc", "-b"], "C:/repo/web", {
      phase: "tsc",
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      timeoutMs: FRONTEND_BUILD_TIMEOUT_MS,
      spawnImpl: () => harness.child,
      captureProcessIdentity: async () => ({
        pid: 5151,
        createTime: 1,
        executable: "C:/Program Files/nodejs/node.exe"
      }),
      terminateProcessTree
    });
    harness.close(2, null);
    await expect(pending).rejects.toMatchObject({ code: "frontend_build_failed", phase: "tsc" });
    expect(terminateProcessTree).toHaveBeenCalledWith(5151, expect.objectContaining({ pid: 5151 }));
    expect(harness.child.kill).not.toHaveBeenCalled();
  });

  it("surfaces child spawn errors with the build phase", async () => {
    const failure = new Error("spawn ENOENT");
    await expect(
      runWaitable("node", ["tsc", "-b"], "C:/repo/web", {
        phase: "tsc",
        timeoutMs: 100,
        spawnImpl: () => {
          throw failure;
        }
      })
    ).rejects.toMatchObject({
      code: "frontend_build_failed",
      phase: "tsc",
      cause: failure
    });
  });

  it("surfaces a child error event without waiting for the timeout", async () => {
    const harness = frontendBuildChild();
    const failure = new Error("vite child failed");
    const pending = runWaitable("node", ["vite", "build"], "C:/repo/web", {
      phase: "vite",
      timeoutMs: FRONTEND_BUILD_TIMEOUT_MS,
      spawnImpl: (_command, _args, options) => {
        expect(options.windowsHide).toBe(true);
        expect(options.stdio).toEqual(["ignore", "ignore", "ignore"]);
        queueMicrotask(() => harness.error(failure));
        return harness.child;
      }
    });
    await expect(pending).rejects.toMatchObject({
      code: "frontend_build_failed",
      phase: "vite",
      cause: failure
    });
    expect(harness.child.kill).not.toHaveBeenCalled();
  });

  it("does not invoke Vite when tsc exits unsuccessfully", async () => {
    const harness = frontendBuildChild();
    const spawnImpl = vi.fn(() => {
      queueMicrotask(() => harness.close(2, null));
      return harness.child;
    });
    await expect(
      ensureFrontendBuild({
        workspaceRoot: "C:/repo",
        force: true,
        fileExists: () => false,
        spawnImpl
      })
    ).rejects.toMatchObject({
      code: "frontend_build_failed",
      phase: "tsc"
    });
    expect(spawnImpl).toHaveBeenCalledOnce();
    expect(spawnImpl.mock.calls[0]?.[1]?.[0]).toContain("typescript");
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
        fetchHealth: async () => ({
          status: 200,
          json: async () => ({ status: "ok", routesReady: true, pid: 4242, workspaceRoot: "C:/repo" })
        }),
        pidAlive: () => false,
        killPid: () => undefined,
        captureProcessIdentity: async ({ pid }) => ({
          pid,
          createTime: 1,
          executable: "C:/Python/python.exe"
        })
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

  it("starts when a stale dead Runtime Manager PID has no identity", async () => {
    const { spawnImpl, input, written } = harness();
    const result = await executeMainLineWorkbench({
      ...input,
      operation: "start",
      command: { commandId: "cmd_stale_daemon", type: "open", operation: "start", noBrowser: true },
      readDaemonPid: () => 7788,
      readDaemonIdentity: () => null,
      pidAlive: () => false,
    });
    expect(result.accepted).toBe(true);
    expect(spawnImpl).toHaveBeenCalledOnce();
    expect(written.at(-1)).toMatchObject({
      observedState: "open",
      lifecycleWarning: expect.stringContaining("7788"),
    });
  });

  it("reconciles a dead backend handle before start instead of invoking the tree terminator", async () => {
    const { spawnImpl, input, written } = harness();
    const terminateProcessTree = vi.fn(async () => false);
    let listening = false;
    const wrappedSpawn = vi.fn((...args: Parameters<typeof spawnImpl>) => {
      listening = true;
      return spawnImpl(...args);
    });
    const result = await executeMainLineWorkbench({
      ...input,
      operation: "start",
      command: { commandId: "cmd_reconcile_dead_backend", type: "open", operation: "start", noBrowser: true },
      spawnImpl: wrappedSpawn,
      readState: () => ({
        backendPid: 51,
        backendLaunchPid: 51,
        spawnPid: 51,
        backendPort: 8000,
        backendCreateTime: 123,
        backendExecutable: "C:/Python/python.exe",
        backendLaunchCreateTime: 123,
        backendLaunchExecutable: "C:/Python/python.exe",
        spawnCreateTime: 123,
        spawnExecutable: "C:/Python/python.exe"
      }),
      pidAlive: () => false,
      connect: async () => listening,
      terminateProcessTree
    });
    expect(result.accepted).toBe(true);
    expect(spawnImpl).toHaveBeenCalledOnce();
    expect(terminateProcessTree).not.toHaveBeenCalled();
    expect(written.at(-1)).toMatchObject({
      observedState: "open",
      lifecycleWarning: expect.stringContaining("reconciled 1 dead registered handle")
    });
  });

  it("does not re-persist reconciled backend handles when a later start preflight fails", async () => {
    const { spawnImpl, input } = harness();
    let written: Record<string, unknown> = {};
    await expect(executeMainLineWorkbench({
      ...input,
      operation: "start",
      command: { commandId: "cmd_reconcile_then_fail", type: "open", operation: "start", noBrowser: true },
      spawnImpl,
      readState: () => ({
        backendPid: 51,
        backendLaunchPid: 51,
        spawnPid: 51,
        backendPort: 8000,
        backendCreateTime: 123,
        backendExecutable: "C:/Python/python.exe",
        backendLaunchCreateTime: 123,
        backendLaunchExecutable: "C:/Python/python.exe",
        spawnCreateTime: 123,
        spawnExecutable: "C:/Python/python.exe",
        browserWindowPid: 9911
      }),
      writeState: (state) => {
        written = state;
      },
      connect: async () => false,
      pidAlive: (pid) => pid === 9911
    })).rejects.toThrow("unverified browser/window handles");
    expect(spawnImpl).not.toHaveBeenCalled();
    expect(written).toMatchObject({
      desiredState: "closed",
      observedState: "failed",
      backendPid: 0,
      backendLaunchPid: 0,
      spawnPid: 0,
      backendCreateTime: 0,
      backendExecutable: "",
      backendLaunchCreateTime: 0,
      backendLaunchExecutable: "",
      spawnCreateTime: 0,
      spawnExecutable: "",
      browserWindowPid: 9911
    });
  });

  it("persists a visible failure when an unverified Runtime Manager PID is still live", async () => {
    const { spawnImpl, input, written } = harness();
    await expect(executeMainLineWorkbench({
      ...input,
      operation: "start",
      command: { commandId: "cmd_live_unverified_daemon", type: "open", operation: "start", noBrowser: true },
      readDaemonPid: () => 7788,
      readDaemonIdentity: () => null,
      pidAlive: (pid) => pid === 7788,
    })).rejects.toThrow("Runtime Manager daemon pid 7788 is live but has no verifiable identity");
    expect(spawnImpl).not.toHaveBeenCalled();
    expect(written.at(-1)).toMatchObject({
      desiredState: "closed",
      observedState: "failed",
      phase: "failed",
      lifecycleWarning: expect.stringContaining("7788"),
      lastReason: "electron_main_start_preflight_failed",
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

  it("blocks shutdown before retiring handles when work is active", async () => {
    const killed: number[] = [];
    const result = await executeMainLineWorkbench({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operation: "shutdown",
      command: { commandId: "cmd_shutdown", type: "close", operation: "shutdown", noBrowser: true },
      readState: () => ({ backendPid: 51, backendPort: 8000 }),
      writeState: () => undefined,
      listActiveWork: () => [{ kind: "chat_turn", runId: "run-1", status: "running", sessionId: "s1" }],
      pidAlive: () => true,
      killPid: (pid) => killed.push(pid),
    });
    expect(result).toMatchObject({
      accepted: false,
      code: "active_work_blocked",
      message: ACTIVE_WORK_BLOCK_MESSAGE_STOP
    });
    expect(killed).toEqual([]);
  });

  it("keeps registered backend handles when HTTP shutdown reports active work", async () => {
    const terminateProcessTree = vi.fn(async () => false);
    let written: Record<string, unknown> = {};
    const result = await executeMainLineWorkbench({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operation: "shutdown",
      command: { commandId: "cmd_shutdown_http_active", type: "close", operation: "shutdown", noBrowser: true },
      readState: () => ({
        backendPid: 51,
        backendLaunchPid: 51,
        spawnPid: 51,
        backendPort: 8000,
        backendCreateTime: 1,
        backendExecutable: "C:/Python/python.exe",
        backendLaunchCreateTime: 1,
        backendLaunchExecutable: "C:/Python/python.exe",
        spawnCreateTime: 1,
        spawnExecutable: "C:/Python/python.exe"
      }),
      writeState: (state) => {
        written = state;
      },
      listActiveWork: () => [],
      connect: async () => true,
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 51, workspaceRoot: "C:/repo" })
      }),
      pidAlive: () => true,
      terminateProcessTree,
      gracefulShutdown: async () => ({
        requested: false,
        completed: false,
        status: 409,
        reason: "backend refused graceful shutdown because active work is running"
      })
    });

    expect(result).toMatchObject({ accepted: false, code: "active_work_blocked" });
    expect(result.message).toContain("active work");
    expect(terminateProcessTree).not.toHaveBeenCalled();
    expect(written).toMatchObject({
      backendPid: 51,
      backendLaunchPid: 51,
      spawnPid: 51,
      observedState: "failed"
    });
  });

  it("allows an explicit force-stop to retire a backend after HTTP active-work refusal", async () => {
    const alive = new Set([51]);
    const terminateProcessTree = vi.fn(async (pid: number) => {
      alive.delete(pid);
      return true;
    });
    const result = await executeMainLineWorkbench({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operation: "force-stop",
      command: { commandId: "cmd_force_http_active", type: "close", operation: "force-stop", noBrowser: true },
      readState: () => ({
        backendPid: 51,
        backendLaunchPid: 51,
        spawnPid: 51,
        backendPort: 8000,
        backendCreateTime: 1,
        backendExecutable: "C:/Python/python.exe",
        backendLaunchCreateTime: 1,
        backendLaunchExecutable: "C:/Python/python.exe",
        spawnCreateTime: 1,
        spawnExecutable: "C:/Python/python.exe"
      }),
      writeState: () => undefined,
      connect: async () => alive.has(51),
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 51, workspaceRoot: "C:/repo" })
      }),
      pidAlive: (pid) => alive.has(pid),
      terminateProcessTree,
      gracefulShutdown: async () => ({
        requested: false,
        completed: false,
        status: 409,
        reason: "backend refused graceful shutdown because active work is running"
      })
    });

    expect(result).toMatchObject({ accepted: true, operation: "force-stop" });
    expect(terminateProcessTree).toHaveBeenCalledWith(51, expect.objectContaining({ pid: 51 }));
    expect(alive.has(51)).toBe(false);
  });

  it("does not kill a backend during ordinary restart when its HTTP shutdown is protected", async () => {
    const terminateProcessTree = vi.fn(async () => false);
    let written: Record<string, unknown> = {};
    await expect(executeMainLineWorkbench({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operation: "restart",
      command: { commandId: "cmd_restart_http_active", type: "open", operation: "restart", noBrowser: true },
      readState: () => ({
        backendPid: 51,
        backendLaunchPid: 51,
        spawnPid: 51,
        backendPort: 8000,
        backendCreateTime: 1,
        backendExecutable: "C:/Python/python.exe",
        backendLaunchCreateTime: 1,
        backendLaunchExecutable: "C:/Python/python.exe",
        spawnCreateTime: 1,
        spawnExecutable: "C:/Python/python.exe"
      }),
      writeState: (state) => {
        written = state;
      },
      ensureFrontend: async () => undefined,
      listActiveWork: () => [],
      connect: async () => true,
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 51, workspaceRoot: "C:/repo" })
      }),
      pidAlive: () => true,
      terminateProcessTree,
      gracefulShutdown: async () => ({
        requested: false,
        completed: false,
        status: 409,
        reason: "backend refused graceful shutdown because active work is running"
      })
    })).rejects.toThrow("still held by stale backend pid 51");

    expect(terminateProcessTree).not.toHaveBeenCalled();
    expect(written).toMatchObject({ backendPid: 51, observedState: "failed" });
  });

  it("ordinary stop also retires the Runtime Manager daemon pid", async () => {
    const killed: number[] = [];
    const alive = new Set([51, 77]);
    const result = await executeMainLineWorkbench({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operation: "stop",
      command: { commandId: "cmd_stop", type: "close", operation: "stop", noBrowser: true },
      readState: () => ({ backendPid: 51, backendPort: 8000 }),
      writeState: () => undefined,
      listActiveWork: () => [],
      pidAlive: (pid) => alive.has(pid),
      killPid: (pid) => {
        killed.push(pid);
        alive.delete(pid);
      },
      connect: async () => false,
      readDaemonPid: () => 77,
      readDaemonIdentity: () => ({
        pid: 77,
        createTime: 1,
        executable: "C:/repo/.venv/Scripts/pythonw.exe"
      })
    });
    expect(result.accepted).toBe(true);
    expect(killed).toEqual([77, 51]);
  });

  it("shutdown ignores a stale Runtime Manager PID without an identity", async () => {
    const alive = new Set([51]);
    const terminateProcessTree = vi.fn(async (pid: number) => {
      alive.delete(pid);
      return true;
    });
    let written: Record<string, unknown> = {};
    const result = await executeMainLineWorkbench({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operation: "shutdown",
      command: { commandId: "cmd_shutdown_stale_daemon", type: "close", operation: "shutdown", noBrowser: true },
      readState: () => ({
        backendPid: 51,
        backendPort: 8000,
        backendCreateTime: 1,
        backendExecutable: "C:/repo/.venv/Scripts/pythonw.exe"
      }),
      writeState: (state) => {
        written = state;
      },
      pidAlive: (pid) => alive.has(pid),
      connect: async () => false,
      readDaemonPid: () => 7788,
      readDaemonIdentity: () => null,
      terminateProcessTree
    });

    expect(result.accepted).toBe(true);
    expect(terminateProcessTree).toHaveBeenCalledWith(51, expect.objectContaining({ pid: 51 }));
    expect(terminateProcessTree).not.toHaveBeenCalledWith(7788, expect.anything());
    expect(written).toMatchObject({
      observedState: "closed",
      lifecycleWarning: expect.stringContaining("7788")
    });
  });

  it("retains an unverified browser handle while allowing stop cleanup to finish", async () => {
    const killPid = vi.fn();
    let written: Record<string, unknown> = {};
    await expect(executeMainLineWorkbench({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operation: "force-stop",
      command: { commandId: "cmd_force_stop", type: "close", operation: "force-stop", noBrowser: true },
      readState: () => ({ browserWindowPid: 9911, backendPort: 8000 }),
      writeState: (state) => {
        written = state;
      },
      pidAlive: () => true,
      killPid,
      connect: async () => false,
      readDaemonPid: () => 0
    })).resolves.toMatchObject({ accepted: true, message: expect.stringContaining("9911") });
    expect(killPid).not.toHaveBeenCalled();
    expect(written).toMatchObject({ browserWindowPid: 9911, backendPid: 0 });
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

  it("surfaces a backend spawn error before waiting for health", async () => {
    const spawnError = new Error("spawn ENOENT");
    const child = {
      pid: 5151,
      exitCode: null as number | null,
      killed: false,
      unref: () => undefined,
      kill: vi.fn(() => true),
      once: (_event: "error", listener: (error: Error) => void) => {
        listener(spawnError);
      }
    };
    const spawned = spawnWorkbenchBackend({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      port: 8000,
      spawnImpl: () => child,
      fileExists: (path: string) => path.endsWith("pythonw.exe")
    });
    expect(spawned.spawnError()).toBe(spawnError);
  });

  it("does not double-kill when an injected killPid returns void", async () => {
    const { spawnImpl, input } = harness();
    const childKill = vi.fn(() => true);
    const child = {
      ...fakeBackendChild(5252),
      kill: childKill
    };
    const killPid = vi.fn(() => undefined);
    await expect(
      runWorkbenchLifecycle({
        ...input,
        spawnImpl: () => child,
        connect: async () => {
          child.exitCode = 1;
          return false;
        },
        fetchHealth: async () => ({ status: 503 }),
        killPid
      })
    ).rejects.toThrow("exited before it became healthy");
    expect(killPid).toHaveBeenCalledWith(5252);
    expect(childKill).not.toHaveBeenCalled();
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
