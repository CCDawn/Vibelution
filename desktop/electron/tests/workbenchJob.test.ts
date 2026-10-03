import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
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

const completeDrainStatus = () => ({ complete: true, channels: [] });

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
      activeCount: () => active, drainStatus: completeDrainStatus, close
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

  it("keeps the old job registered until both output drains finish before replacement", async () => {
    vi.useFakeTimers();
    let generation = 0;
    const counts = new Map<object, number>();
    const drains = new Map<object, boolean>();
    const jobs: object[] = [];
    const close = vi.fn((job) => counts.set(job, 0));
    const terminate = vi.fn((job: object) => { counts.set(job, 0); return true; });
    __setWorkbenchJobNativeForTests({
      spawn: () => {
        const job = {};
        jobs.push(job);
        counts.set(job, 1);
        drains.set(job, false);
        return { pid: process.pid + (++generation), job };
      }, terminate, activeCount: (job) => counts.get(job) ?? 0,
      drainStatus: (job) => ({ complete: drains.get(job) ?? true, channels: [] }), close
    });
    const input = { executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err" };
    const old = spawnTrackedWorkbenchProcess("C:/replacement", input);
    const retireOld = captureTrackedWorkbenchJobRetirement("C:/replacement", old.pid)!;
    const retirement = terminateTrackedWorkbenchJob("C:/replacement", old.pid);
    expect(() => spawnTrackedWorkbenchProcess("C:/replacement", input)).toThrow("still terminating or draining");
    expect(hasTrackedWorkbenchJob("C:/replacement")).toBe(true);
    drains.set(jobs[0], true);
    await vi.advanceTimersByTimeAsync(100);
    await retirement;
    expect(hasTrackedWorkbenchJob("C:/replacement")).toBe(false);
    const replacement = spawnTrackedWorkbenchProcess("C:/replacement", input);
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
      let active = failure === "close throws" ? 0 : 1;
      const terminate = vi.fn(() => { active = 0; return true; });
      const close = vi.fn();
      __setWorkbenchJobNativeForTests({ spawn, terminate, activeCount: () => active, drainStatus: completeDrainStatus, close });
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

  it("retains the captured job when native termination is not confirmed", async () => {
    const terminate = vi.fn(() => false);
    const close = vi.fn();
    __setWorkbenchJobNativeForTests({
      spawn: () => ({ pid: process.pid, job: {} }), terminate, activeCount: () => 0,
      drainStatus: completeDrainStatus, close
    });
    const old = spawnTrackedWorkbenchProcess("C:/unconfirmed-retirement", {
      executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err"
    });
    const retire = captureTrackedWorkbenchJobRetirement("C:/unconfirmed-retirement", old.pid)!;
    await expect(terminateTrackedWorkbenchJob("C:/unconfirmed-retirement", old.pid)).resolves.toBe(false);
    await expect(retire()).resolves.toBe(false);
    expect(close).not.toHaveBeenCalled();
    expect(hasTrackedWorkbenchJob("C:/unconfirmed-retirement")).toBe(true);
    terminate.mockReturnValue(true);
    await expect(retire()).resolves.toBe(true);
    expect(hasTrackedWorkbenchJob("C:/unconfirmed-retirement")).toBe(false);
  });

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
      drainStatus: completeDrainStatus,
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
      let childPid = 0;
      while (Date.now() < deadline) {
        try {
          childPid = Number(readFileSync(childPidPath, "utf8"));
        } catch {
          // The child publishes its identity after the owned root starts.
        }
        // Windows Job accounting and process-exit visibility can settle on
        // different ticks. Require both within the original cleanup budget.
        if (childPid > 0 && !hasTrackedWorkbenchJob(directory)
          && !pidAlive(spawned.pid) && !pidAlive(childPid)) break;
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      expect(childPid).toBeGreaterThan(0);
      expect(pidAlive(spawned.pid), `owned root ${spawned.pid} still alive`).toBe(false);
      expect(pidAlive(childPid), `owned child ${childPid} still alive`).toBe(false);
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
      while (Date.now() < gone && (native.activeCount(spawned.job) > 0 || !native.drainStatus(spawned.job).complete)) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      expect(native.activeCount(spawned.job)).toBe(0);
      expect(native.drainStatus(spawned.job).complete).toBe(true);
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

  it("bounds both output logs, drains both streams, and releases file handles on exit", async () => {
    __setWorkbenchJobNativeForTests(undefined);
    const directory = mkdtempSync(join(tmpdir(), "vibelution-bounded-job-"));
    const stdoutPath = join(directory, "stdout.log");
    const stderrPath = join(directory, "stderr.log");
    const maxLogBytes = 64 * 1024;
    const native = (await import("../src/process/workbenchJob.js")).loadWorkbenchJobNative();
    const script = [
      "const fs=require('node:fs');const out=Buffer.alloc(4096,65);const err=Buffer.alloc(4096,66);",
      "for(let i=0;i<1024;i++){fs.writeSync(1,out);fs.writeSync(2,err);}"
    ].join("");
    const spawned = native.spawn({
      executable: process.execPath,
      arguments: ["-e", script],
      cwd: directory,
      env: { ...process.env },
      stdoutPath,
      stderrPath,
      maxLogBytes
    });
    try {
      const deadline = Date.now() + 12_000;
      let status = native.drainStatus(spawned.job);
      while (Date.now() < deadline && (native.activeCount(spawned.job) > 0 || !status.complete)) {
        await new Promise((resolve) => setTimeout(resolve, 50));
        status = native.drainStatus(spawned.job);
      }
      expect(native.activeCount(spawned.job)).toBe(0);
      expect(status.complete).toBe(true);
      expect(status.channels).toEqual(expect.arrayContaining([
        expect.objectContaining({ stream: "stdout", complete: true, errorCode: 0 }),
        expect.objectContaining({ stream: "stderr", complete: true, errorCode: 0 })
      ]));
      expect(status.channels.every((channel) => channel.rotations > 0)).toBe(true);
      for (const path of [stdoutPath, stderrPath]) {
        const files = [path, `${path}.1`, `${path}.2`, `${path}.3`].filter(existsSync);
        expect(files.length).toBeGreaterThan(1);
        expect(files.every((file) => statSync(file).size <= maxLogBytes)).toBe(true);
        expect(files.reduce((total, file) => total + statSync(file).size, 0)).toBeLessThanOrEqual(maxLogBytes * 4);
      }
      expect(pidAlive(spawned.pid)).toBe(false);
      native.close(spawned.job);
      rmSync(directory, { recursive: true, force: false });
      expect(existsSync(directory)).toBe(false);
    } finally {
      try {
        if (native.activeCount(spawned.job) > 0) native.terminate(spawned.job);
        const deadline = Date.now() + 8_000;
        while (Date.now() < deadline && (native.activeCount(spawned.job) > 0 || !native.drainStatus(spawned.job).complete)) {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        if (native.activeCount(spawned.job) === 0 && native.drainStatus(spawned.job).complete) {
          native.close(spawned.job);
        }
      } catch {
        // Preserve the original assertion; the native finalizer remains the last cleanup owner.
      }
      rmSync(directory, { recursive: true, force: true });
    }
  }, 20_000);

  it("keeps the newest bytes when bounding an existing log before appending", async () => {
    __setWorkbenchJobNativeForTests(undefined);
    const directory = mkdtempSync(join(tmpdir(), "vibelution-trimmed-job-"));
    const stdoutPath = join(directory, "stdout.log");
    const stderrPath = join(directory, "stderr.log");
    const maxLogBytes = 64 * 1024;
    const recentBytes = Buffer.alloc(maxLogBytes, 0x42);
    writeFileSync(stdoutPath, Buffer.concat([Buffer.alloc(maxLogBytes, 0x41), recentBytes]));
    const native = (await import("../src/process/workbenchJob.js")).loadWorkbenchJobNative();
    const spawned = native.spawn({
      executable: process.execPath,
      arguments: ["-e", "require('node:fs').writeSync(1, Buffer.from('current-output'))"],
      cwd: directory,
      env: { ...process.env },
      stdoutPath,
      stderrPath,
      maxLogBytes
    });
    try {
      const deadline = Date.now() + 8_000;
      while (Date.now() < deadline
        && (native.activeCount(spawned.job) > 0 || !native.drainStatus(spawned.job).complete)) {
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      expect(native.activeCount(spawned.job)).toBe(0);
      expect(native.drainStatus(spawned.job).complete).toBe(true);
      expect(readFileSync(`${stdoutPath}.1`)).toEqual(recentBytes);
      expect(readFileSync(stdoutPath, "utf8")).toBe("current-output");
      expect(statSync(`${stdoutPath}.1`).size).toBe(maxLogBytes);
      native.close(spawned.job);
    } finally {
      try {
        if (native.activeCount(spawned.job) > 0) native.terminate(spawned.job);
        const deadline = Date.now() + 8_000;
        while (Date.now() < deadline
          && (native.activeCount(spawned.job) > 0 || !native.drainStatus(spawned.job).complete)) {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        if (native.activeCount(spawned.job) === 0 && native.drainStatus(spawned.job).complete) {
          native.close(spawned.job);
        }
      } catch {
        // Preserve the original assertion; the native finalizer remains the last cleanup owner.
      }
      rmSync(directory, { recursive: true, force: true });
    }
  }, 15_000);

  it("fills the remaining log capacity before rotating a drain buffer", async () => {
    __setWorkbenchJobNativeForTests(undefined);
    const directory = mkdtempSync(join(tmpdir(), "vibelution-split-job-"));
    const stdoutPath = join(directory, "stdout.log");
    const stderrPath = join(directory, "stderr.log");
    const maxLogBytes = 32 * 1024;
    const existingBytes = 30_000;
    const outputBytes = maxLogBytes;
    writeFileSync(stdoutPath, Buffer.alloc(existingBytes, 0x41));
    const native = (await import("../src/process/workbenchJob.js")).loadWorkbenchJobNative();
    const spawned = native.spawn({
      executable: process.execPath,
      arguments: ["-e", `require('node:fs').writeSync(1, Buffer.alloc(${outputBytes}, 0x42))`],
      cwd: directory,
      env: { ...process.env },
      stdoutPath,
      stderrPath,
      maxLogBytes
    });
    try {
      const deadline = Date.now() + 8_000;
      while (Date.now() < deadline
        && (native.activeCount(spawned.job) > 0 || !native.drainStatus(spawned.job).complete)) {
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      expect(native.activeCount(spawned.job)).toBe(0);
      const status = native.drainStatus(spawned.job);
      expect(status.complete).toBe(true);
      expect(status.channels).toEqual(expect.arrayContaining([
        expect.objectContaining({ stream: "stdout", errorCode: 0, rotations: 1 })
      ]));
      expect(readFileSync(`${stdoutPath}.1`)).toEqual(Buffer.concat([
        Buffer.alloc(existingBytes, 0x41),
        Buffer.alloc(maxLogBytes - existingBytes, 0x42)
      ]));
      expect(readFileSync(stdoutPath)).toEqual(Buffer.alloc(outputBytes - (maxLogBytes - existingBytes), 0x42));
      native.close(spawned.job);
    } finally {
      try {
        if (native.activeCount(spawned.job) > 0) native.terminate(spawned.job);
        const deadline = Date.now() + 8_000;
        while (Date.now() < deadline
          && (native.activeCount(spawned.job) > 0 || !native.drainStatus(spawned.job).complete)) {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        if (native.activeCount(spawned.job) === 0 && native.drainStatus(spawned.job).complete) {
          native.close(spawned.job);
        }
      } catch {
        // Preserve the original assertion; the native finalizer remains the last cleanup owner.
      }
      rmSync(directory, { recursive: true, force: true });
    }
  }, 15_000);
});

function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
