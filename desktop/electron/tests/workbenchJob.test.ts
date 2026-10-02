import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  __setWorkbenchJobNativeForTests,
  captureTrackedWorkbenchJobRetirement,
  hasTrackedWorkbenchJob,
  spawnTrackedWorkbenchProcess,
  terminateTrackedWorkbenchJob,
  type WorkbenchJobHandle,
  type WorkbenchJobNative
} from "../src/process/workbenchJob.js";

describe("workbench job registry", () => {
  afterEach(() => {
    __setWorkbenchJobNativeForTests(undefined);
    vi.useRealTimers();
  });

  it("releases an idle job after natural exit without another lifecycle command", async () => {
    vi.useFakeTimers();
    let active = 1;
    const close = vi.fn();
    __setWorkbenchJobNativeForTests({
      spawn: () => ({ pid: process.pid, job: {} }), terminate: () => true,
      activeCount: () => active, close
    });
    spawnTrackedWorkbenchProcess("C:/natural-exit", {
      executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err"
    });
    active = 0;
    await vi.advanceTimersByTimeAsync(1_000);
    expect(close).toHaveBeenCalledOnce();
    expect(hasTrackedWorkbenchJob("C:/natural-exit")).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not let an old retirement delete or terminate a replacement job", async () => {
    vi.useFakeTimers();
    let generation = 0;
    const counts = new Map<object, number>();
    const close = vi.fn((job) => counts.set(job, 0));
    const terminate = vi.fn(() => true);
    __setWorkbenchJobNativeForTests({
      spawn: () => {
        const job = {};
        counts.set(job, 1);
        return { pid: process.pid + (++generation), job };
      }, terminate, activeCount: (job) => counts.get(job) ?? 0, close
    });
    const input = { executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err" };
    const old = spawnTrackedWorkbenchProcess("C:/replacement", input);
    const retireOld = captureTrackedWorkbenchJobRetirement("C:/replacement", old.pid)!;
    const retirement = terminateTrackedWorkbenchJob("C:/replacement", old.pid);
    const replacement = spawnTrackedWorkbenchProcess("C:/replacement", input);
    await vi.advanceTimersByTimeAsync(100);
    await retirement;
    expect(hasTrackedWorkbenchJob("C:/replacement")).toBe(true);
    const calls = terminate.mock.calls.length;
    await expect(terminateTrackedWorkbenchJob("C:/replacement", old.pid)).resolves.toBe(false);
    expect(terminate.mock.calls.length).toBe(calls);
    await expect(retireOld()).resolves.toBe(true);
    expect(terminate.mock.calls.length).toBe(calls);
    expect(replacement.pid).not.toBe(old.pid);
  });

  it.each(["terminate throws", "terminate rejects", "close throws"])(
    "retains ownership and blocks replacement when %s",
    async (failure) => {
      const spawn = vi.fn(() => ({ pid: process.pid, job: {} }));
      const terminate = vi.fn(() => true);
      const close = vi.fn();
      __setWorkbenchJobNativeForTests({ spawn, terminate, activeCount: () => 0, close });
      const input = { executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err" };
      const old = spawnTrackedWorkbenchProcess("C:/failed-replacement", input);
      if (failure === "terminate throws") terminate.mockImplementationOnce(() => { throw new Error("terminate failed"); });
      if (failure === "terminate rejects") terminate.mockReturnValueOnce(false);
      if (failure === "close throws") close.mockImplementationOnce(() => { throw new Error("close failed"); });
      expect(() => spawnTrackedWorkbenchProcess("C:/failed-replacement", input)).toThrow();
      expect(spawn).toHaveBeenCalledOnce();
      expect(hasTrackedWorkbenchJob("C:/failed-replacement")).toBe(true);
      await expect(terminateTrackedWorkbenchJob("C:/failed-replacement", old.pid)).resolves.toBe(true);
      expect(hasTrackedWorkbenchJob("C:/failed-replacement")).toBe(false);
    }
  );

  it("terminates the tracked group before a later tree walk would be needed", async () => {
    const jobs: WorkbenchJobHandle[] = [];
    let active = 2;
    const native: WorkbenchJobNative = {
      spawn: () => {
        const job = { id: jobs.length + 1 };
        jobs.push(job);
        active = 2;
        return { pid: 4100 + jobs.length, job };
      },
      terminate: () => {
        active = 0;
        return true;
      },
      activeCount: () => active,
      close: () => undefined
    };
    __setWorkbenchJobNativeForTests(native);
    spawnTrackedWorkbenchProcess("C:/repo", {
      executable: "pythonw.exe",
      arguments: ["scripts/web_workbench.py"],
      cwd: "C:/repo",
      env: {},
      stdoutPath: "C:/repo/out.log",
      stderrPath: "C:/repo/err.log"
    });
    expect(hasTrackedWorkbenchJob("c:/repo")).toBe(true);
    await expect(terminateTrackedWorkbenchJob("C:\\repo")).resolves.toBe(true);
    expect(hasTrackedWorkbenchJob("C:/repo")).toBe(false);
    __setWorkbenchJobNativeForTests(undefined);
  });
});

const nativeAddon = process.platform === "win32"
  ? describe
  : describe.skip;

nativeAddon("windows workbench job", () => {
  it("reclaims surviving children when their owned root exits naturally", async () => {
    __setWorkbenchJobNativeForTests(undefined);
    const directory = mkdtempSync(join(tmpdir(), "vibelution-orphan-job-"));
    const childPidPath = join(directory, "child-pid.txt");
    const script = [
      "const {spawn}=require('node:child_process');const fs=require('node:fs');",
      "const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore',windowsHide:true});",
      `fs.writeFileSync(${JSON.stringify(childPidPath)},String(child.pid));`,
      "setTimeout(()=>process.exit(0),100);"
    ].join("");
    const spawned = spawnTrackedWorkbenchProcess(directory, {
      executable: process.execPath, arguments: ["-e", script], cwd: directory, env: { ...process.env },
      stdoutPath: join(directory, "stdout.log"), stderrPath: join(directory, "stderr.log")
    });
    try {
      const deadline = Date.now() + 8_000;
      while (hasTrackedWorkbenchJob(directory) && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      const childPid = Number(readFileSync(childPidPath, "utf8"));
      expect(childPid).toBeGreaterThan(0);
      expect(pidAlive(spawned.pid)).toBe(false);
      expect(pidAlive(childPid)).toBe(false);
      expect(hasTrackedWorkbenchJob(directory)).toBe(false);
    } finally {
      await terminateTrackedWorkbenchJob(directory);
      rmSync(directory, { recursive: true, force: true });
    }
  }, 12_000);

  it("reaps the native handle after a process exits by itself", async () => {
    __setWorkbenchJobNativeForTests(undefined);
    const directory = mkdtempSync(join(tmpdir(), "vibelution-natural-job-"));
    const spawned = spawnTrackedWorkbenchProcess(directory, {
      executable: process.execPath, arguments: ["-e", "setTimeout(()=>{},100)"],
      cwd: directory, env: { ...process.env },
      stdoutPath: join(directory, "stdout.log"), stderrPath: join(directory, "stderr.log")
    });
    try {
      const deadline = Date.now() + 5_000;
      while (hasTrackedWorkbenchJob(directory) && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      expect(pidAlive(spawned.pid)).toBe(false);
      expect(hasTrackedWorkbenchJob(directory)).toBe(false);
    } finally {
      await terminateTrackedWorkbenchJob(directory);
      rmSync(directory, { recursive: true, force: true });
    }
  }, 10_000);
  it("kills the spawned process and the child it starts", async () => {
    const { loadWorkbenchJobNative } = await import("../src/process/workbenchJob.js");
    const native = loadWorkbenchJobNative();
    const directory = mkdtempSync(join(tmpdir(), "vibelution-job-"));
    const childPidPath = join(directory, "child-pid.txt");
    const stdoutPath = join(directory, "stdout.log");
    const stderrPath = join(directory, "stderr.log");
    const script = [
      "const {spawn}=require('node:child_process');",
      "const fs=require('node:fs');",
      "const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore',windowsHide:true});",
      `fs.writeFileSync(${JSON.stringify(childPidPath)}, String(child.pid));`,
      "setInterval(()=>{},1000);"
    ].join("");
    const spawned = native.spawn({
      executable: process.execPath,
      arguments: ["-e", script],
      cwd: directory,
      env: { ...process.env, PATH: process.env.PATH ?? "" },
      stdoutPath,
      stderrPath
    });
    try {
      const deadline = Date.now() + 5_000;
      let childPid = 0;
      while (Date.now() < deadline && childPid <= 0) {
        try {
          childPid = Number(readFileSync(childPidPath, "utf8"));
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
      }
      expect(childPid).toBeGreaterThan(0);
      expect(native.activeCount(spawned.job)).toBeGreaterThan(0);
      native.terminate(spawned.job);
      const gone = Date.now() + 8_000;
      while (Date.now() < gone && native.activeCount(spawned.job) > 0) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      expect(native.activeCount(spawned.job)).toBe(0);
      expect(pidAlive(spawned.pid)).toBe(false);
      expect(pidAlive(childPid)).toBe(false);
    } finally {
      try {
        native.close(spawned.job);
      } catch {
        // Already closed after a verified termination.
      }
      for (let attempt = 0; attempt < 10; attempt += 1) {
        try {
          rmSync(directory, { recursive: true, force: true });
          break;
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
      }
    }
  }, 20_000);
});

function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
