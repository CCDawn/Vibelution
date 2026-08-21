import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import {
  HOLDER_FILE_NAME,
  LOCKDIR_SUFFIX,
  LOCK_POLL_MS,
  LOCK_STALE_BROKEN_EVENT,
  LOCK_STALE_MS,
  LOCK_TIMEOUT_MS,
  MISSING_HOLDER_GRACE_MS,
  InstanceLockTimeoutError,
  plantLockdir,
  withInstanceLock
} from "../src/lifecycle/instanceLock.js";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const protocolPath = join(repoRoot, "tests", "fixtures", "launcher", "instance_lock_protocol.json");
const pythonExe = [
  join(repoRoot, ".venv", "Scripts", "python.exe"),
  join(repoRoot, "..", "..", ".venv", "Scripts", "python.exe")
].find((candidate) => existsSync(candidate));
if (!pythonExe) {
  throw new Error("python.exe not found beside the worktree or the main checkout .venv");
}
const tempDirs: string[] = [];
const children: ChildProcessWithoutNullStreams[] = [];

function makeRegistryPath(): string {
  const dir = mkdtempSync(join(tmpdir(), "vibelution-instance-lock-"));
  tempDirs.push(dir);
  return join(dir, "instances.json");
}

afterEach(async () => {
  while (children.length > 0) {
    const child = children.pop();
    if (!child) {
      continue;
    }
    if (child.exitCode === null && child.signalCode === null) {
      child.kill();
      await Promise.race([
        waitForExit(child, 2000),
        new Promise((resolve) => {
          setTimeout(resolve, 2000);
        })
      ]).catch(() => undefined);
    }
  }
  while (tempDirs.length > 0) {
    const dir = tempDirs.pop() as string;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        rmSync(dir, { recursive: true, force: true });
        break;
      } catch {
        await new Promise((resolve) => {
          setTimeout(resolve, 25);
        });
      }
    }
  }
});

function loadProtocol(): {
  lockdirSuffix: string;
  holderFileName: string;
  pollMs: number;
  timeoutMs: number;
  staleMs: number;
  missingHolderGraceMs: number;
  staleBrokenEvent: string;
} {
  return JSON.parse(readFileSync(protocolPath, "utf8")) as {
    lockdirSuffix: string;
    holderFileName: string;
    pollMs: number;
    timeoutMs: number;
    staleMs: number;
    missingHolderGraceMs: number;
    staleBrokenEvent: string;
  };
}

type JsonLineWaiter = {
  next: (timeoutMs: number) => Promise<Record<string, unknown>>;
};

const jsonLines = new WeakMap<ChildProcessWithoutNullStreams, JsonLineWaiter>();

function attachJsonLines(child: ChildProcessWithoutNullStreams): JsonLineWaiter {
  let buffer = "";
  const queue: Record<string, unknown>[] = [];
  const waiters: Array<{
    resolve: (value: Record<string, unknown>) => void;
    reject: (error: Error) => void;
    timer: ReturnType<typeof setTimeout>;
  }> = [];
  child.stdout.on("data", (chunk: Buffer) => {
    buffer += chunk.toString("utf8");
    const parts = buffer.split(/\r?\n/);
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("{")) {
        continue;
      }
      const parsed = JSON.parse(line) as Record<string, unknown>;
      const waiter = waiters.shift();
      if (waiter) {
        clearTimeout(waiter.timer);
        waiter.resolve(parsed);
      } else {
        queue.push(parsed);
      }
    }
  });
  return {
    next(timeoutMs: number) {
      return new Promise((resolve, reject) => {
        if (queue.length > 0) {
          resolve(queue.shift() as Record<string, unknown>);
          return;
        }
        const timer = setTimeout(() => {
          const index = waiters.findIndex((item) => item.timer === timer);
          if (index >= 0) {
            waiters.splice(index, 1);
          }
          reject(new Error(`timed out waiting for python lock helper: ${buffer}`));
        }, timeoutMs);
        waiters.push({ resolve, reject, timer });
      });
    }
  };
}

function spawnPython(args: string[]): ChildProcessWithoutNullStreams {
  const child = spawn(pythonExe, ["-m", "core.runtime_manager.instance_lock", ...args], {
    cwd: repoRoot,
    windowsHide: true,
    env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
    stdio: ["ignore", "pipe", "ignore"]
  });
  jsonLines.set(child, attachJsonLines(child));
  children.push(child);
  return child;
}

function waitForJsonLine(
  child: ChildProcessWithoutNullStreams,
  timeoutMs: number
): Promise<Record<string, unknown>> {
  const waiter = jsonLines.get(child);
  if (!waiter) {
    return Promise.reject(new Error("python lock helper has no JSON waiter"));
  }
  return waiter.next(timeoutMs);
}

function waitForExit(child: ChildProcessWithoutNullStreams, timeoutMs: number): Promise<number | null> {
  return new Promise((resolve, reject) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve(child.exitCode);
      return;
    }
    const timer = setTimeout(() => reject(new Error("python helper did not exit")), timeoutMs);
    child.once("exit", (code) => {
      clearTimeout(timer);
      resolve(code);
    });
  });
}

describe("instanceLock protocol", () => {
  it("matches the shared fixture constants", () => {
    const protocol = loadProtocol();
    expect(LOCKDIR_SUFFIX).toBe(protocol.lockdirSuffix);
    expect(HOLDER_FILE_NAME).toBe(protocol.holderFileName);
    expect(LOCK_POLL_MS).toBe(protocol.pollMs);
    expect(LOCK_TIMEOUT_MS).toBe(protocol.timeoutMs);
    expect(LOCK_STALE_MS).toBe(protocol.staleMs);
    expect(MISSING_HOLDER_GRACE_MS).toBe(protocol.missingHolderGraceMs);
    expect(LOCK_STALE_BROKEN_EVENT).toBe(protocol.staleBrokenEvent);
  });

  it("waits while Python holds the lock, then acquires after release", async () => {
    const registryPath = makeRegistryPath();
    const child = spawnPython(["hold", "--registry", registryPath, "--seconds", "0.35", "--timeout", "3"]);
    const held = await waitForJsonLine(child, 4000);
    expect(held.status).toBe("held");

    const started = Date.now();
    await withInstanceLock(registryPath, async () => undefined, { timeoutMs: 3000 });
    expect(Date.now() - started).toBeGreaterThanOrEqual(200);
    expect(await waitForExit(child, 4000)).toBe(0);
  }, 10000);

  it("lets Python wait while TypeScript holds the lock", async () => {
    const registryPath = makeRegistryPath();
    let child: ChildProcessWithoutNullStreams | undefined;
    let line: Promise<Record<string, unknown>> | undefined;
    await withInstanceLock(
      registryPath,
      async () => {
        child = spawnPython([
          "wait-acquire",
          "--registry",
          registryPath,
          "--timeout",
          "3",
          "--hold-seconds",
          "0"
        ]);
        const waiting = await waitForJsonLine(child, 8000);
        expect(waiting.status).toBe("waiting");
        line = waitForJsonLine(child, 4000);
        await new Promise((resolve) => setTimeout(resolve, 250));
      },
      { timeoutMs: 3000 }
    );
    const result = await line!;
    expect(result.ok).toBe(true);
    expect(Number(result.waitedMs)).toBeGreaterThanOrEqual(180);
    expect(await waitForExit(child!, 4000)).toBe(0);
  }, 10000);

  it("breaks a Python-planted stale lockdir", async () => {
    const registryPath = makeRegistryPath();
    const child = spawnPython(["plant-stale", "--registry", registryPath, "--pid", "99"]);
    const planted = await waitForJsonLine(child, 4000);
    expect(planted.status).toBe("planted");
    expect(await waitForExit(child, 4000)).toBe(0);
    const events: Array<{ reason: string; previousPid: number | null }> = [];
    await withInstanceLock(registryPath, async () => undefined, {
      emitEvent: (_name, payload) => {
        events.push({ reason: payload.reason, previousPid: payload.previousPid });
      }
    });
    expect(events[0]?.reason).toBe("stale_started_at");
    expect(events[0]?.previousPid).toBe(99);
  }, 10000);

  it("does not break an old lock while its holder PID is still alive", async () => {
    const registryPath = makeRegistryPath();
    await plantLockdir(registryPath, {
      pid: 4242,
      startedAt: new Date(Date.now() - LOCK_STALE_MS - 1).toISOString()
    });

    await expect(
      withInstanceLock(registryPath, async () => undefined, {
        timeoutMs: 80,
        pollMs: 10,
        pidAlive: () => true
      })
    ).rejects.toBeInstanceOf(InstanceLockTimeoutError);
  });

  it("rechecks holder PID liveness after stale classification", async () => {
    const registryPath = makeRegistryPath();
    await plantLockdir(registryPath, {
      pid: 4243,
      startedAt: new Date(Date.now() - LOCK_STALE_MS - 1).toISOString()
    });
    let checks = 0;

    await expect(
      withInstanceLock(registryPath, async () => undefined, {
        timeoutMs: 80,
        pollMs: 10,
        pidAlive: () => checks++ > 0
      })
    ).rejects.toBeInstanceOf(InstanceLockTimeoutError);
    expect(checks).toBeGreaterThan(1);
  });

  it("times out when the lock is already held", async () => {
    const registryPath = makeRegistryPath();
    await withInstanceLock(
      registryPath,
      async () => {
        await expect(
          withInstanceLock(registryPath, async () => undefined, { timeoutMs: 120, pollMs: 10 })
        ).rejects.toBeInstanceOf(InstanceLockTimeoutError);
      },
      { timeoutMs: 2000 }
    );
  });
});
