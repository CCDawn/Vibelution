import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { afterEach, describe, expect, it, vi } from "vitest";
import { beginNaturalWorkbenchShutdown } from "../src/process/workbenchBackend.js";

import {
  __setWorkbenchJobNativeForTests,
  captureTrackedWorkbenchJobNaturalRetirement,
  captureTrackedWorkbenchJobRetirement,
  closeTrackedWorkbenchJob,
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

  it("holds a captured natural Job without force when root, children or output remain", async () => {
    vi.useFakeTimers();
    let active = 1, exited = false, drained = false;
    const terminate = vi.fn(() => true), close = vi.fn();
    __setWorkbenchJobNativeForTests({ spawn: () => ({ pid: 987654321, job: {} }), terminate,
      activeCount: () => active, exitCode: () => exited ? 0 : null,
      drainStatus: () => ({ complete: drained, channels: [] }), close });
    const input = { executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err" };
    spawnTrackedWorkbenchProcess("C:/natural-protected", input);
    const captured = captureTrackedWorkbenchJobNaturalRetirement("C:/natural-protected", 987654321)!;
    await vi.advanceTimersByTimeAsync(2_000);
    expect(await captured()).toBe(false);
    expect(await terminateTrackedWorkbenchJob("C:/natural-protected")).toBe(false);
    expect(() => spawnTrackedWorkbenchProcess("C:/natural-protected", input)).toThrow("natural retirement");
    expect(terminate).not.toHaveBeenCalled();
    active = 0;
    expect(await captured()).toBe(false);
    exited = true;
    expect(await captured()).toBe(false);
    drained = true;
    await vi.advanceTimersByTimeAsync(2_000);
    expect(close).not.toHaveBeenCalled();
    expect(() => spawnTrackedWorkbenchProcess("C:/natural-protected", input)).toThrow("natural retirement");
    expect(await captured()).toBe(true);
    expect(close).toHaveBeenCalledOnce();
    expect(terminate).not.toHaveBeenCalled();
    captured.release();
  });

  it("retains the captured Job until the root exit is signaled after empty accounting and completed drains", async () => {
    vi.useFakeTimers();
    let exitCode: number | null = null;
    const close = vi.fn();
    __setWorkbenchJobNativeForTests({
      spawn: () => ({ pid: process.pid, job: {} }), terminate: () => true,
      activeCount: () => 0, drainStatus: completeDrainStatus, exitCode: () => exitCode, close
    });
    spawnTrackedWorkbenchProcess("C:/root-exit-retirement", {
      executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err"
    });
    const retire = captureTrackedWorkbenchJobRetirement("C:/root-exit-retirement", process.pid)!;
    const attempt = retire();
    await vi.advanceTimersByTimeAsync(8_000);
    await expect(attempt).resolves.toBe(false);
    expect(close).not.toHaveBeenCalled();
    expect(hasTrackedWorkbenchJob("C:/root-exit-retirement")).toBe(true);
    expect(retire.isCurrent()).toBe(true);
    exitCode = 1;
    await expect(retire()).resolves.toBe(true);
    expect(close).toHaveBeenCalledOnce();
    expect(hasTrackedWorkbenchJob("C:/root-exit-retirement")).toBe(false);
  });

  it("does not let the reaper release an unsignaled root with empty accounting and completed drains", async () => {
    vi.useFakeTimers();
    let exitCode: number | null = null;
    const close = vi.fn();
    __setWorkbenchJobNativeForTests({
      spawn: () => ({ pid: process.pid, job: {} }), terminate: () => true,
      activeCount: () => 0, drainStatus: completeDrainStatus, exitCode: () => exitCode, close
    });
    spawnTrackedWorkbenchProcess("C:/root-exit-reaper", {
      executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err"
    });
    await vi.advanceTimersByTimeAsync(2_000);
    expect(close).not.toHaveBeenCalled();
    expect(hasTrackedWorkbenchJob("C:/root-exit-reaper")).toBe(true);
    exitCode = 1;
    await vi.advanceTimersByTimeAsync(1_000);
    expect(close).toHaveBeenCalledOnce();
    expect(hasTrackedWorkbenchJob("C:/root-exit-reaper")).toBe(false);
  });

  it("waits for root exit when gracefully closing a Job whose drains already completed", async () => {
    vi.useFakeTimers();
    let exitCode: number | null = null;
    const close = vi.fn();
    __setWorkbenchJobNativeForTests({
      spawn: () => ({ pid: process.pid, job: {} }), terminate: () => true,
      activeCount: () => 0, drainStatus: completeDrainStatus, exitCode: () => exitCode, close
    });
    spawnTrackedWorkbenchProcess("C:/root-exit-graceful", {
      executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err"
    });
    const closing = closeTrackedWorkbenchJob("C:/root-exit-graceful");
    await vi.advanceTimersByTimeAsync(100);
    expect(close).not.toHaveBeenCalled();
    expect(hasTrackedWorkbenchJob("C:/root-exit-graceful")).toBe(true);
    exitCode = 1;
    await vi.advanceTimersByTimeAsync(20);
    await expect(closing).resolves.toBe(true);
    expect(close).toHaveBeenCalledOnce();
  });

  it("blocks replacement until the previous root is signaled even when accounting and drains are empty", () => {
    vi.useFakeTimers();
    let exitCode: number | null = null;
    const spawn = vi.fn(() => ({ pid: process.pid, job: {} }));
    const close = vi.fn();
    __setWorkbenchJobNativeForTests({
      spawn, terminate: () => true, activeCount: () => 0,
      drainStatus: completeDrainStatus, exitCode: () => exitCode, close
    });
    const input = { executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err" };
    spawnTrackedWorkbenchProcess("C:/root-exit-replacement", input);
    expect(() => spawnTrackedWorkbenchProcess("C:/root-exit-replacement", input)).toThrow("still terminating or draining");
    expect(spawn).toHaveBeenCalledOnce();
    expect(close).not.toHaveBeenCalled();
    exitCode = 1;
    spawnTrackedWorkbenchProcess("C:/root-exit-replacement", input);
    expect(spawn).toHaveBeenCalledTimes(2);
    expect(close).toHaveBeenCalledOnce();
  });

  it("confirms completed retirement on the next 20 ms poll while preserving incomplete drains", async () => {
    vi.useFakeTimers();
    let drained = false;
    const close = vi.fn();
    __setWorkbenchJobNativeForTests({
      spawn: () => ({ pid: process.pid, job: {} }), terminate: () => true,
      activeCount: () => 0, drainStatus: () => ({ complete: drained, channels: [] }), close
    });
    spawnTrackedWorkbenchProcess("C:/fast-retirement", {
      executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err"
    });
    const retirement = terminateTrackedWorkbenchJob("C:/fast-retirement", process.pid);
    await vi.advanceTimersByTimeAsync(20);
    expect(close).not.toHaveBeenCalled();
    drained = true;
    await vi.advanceTimersByTimeAsync(19);
    expect(close).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await expect(retirement).resolves.toBe(true);
    expect(close).toHaveBeenCalledOnce();
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

  it("waits for the remaining log drains after a graceful process exit", async () => {
    vi.useFakeTimers();
    let drained = false;
    const close = vi.fn();
    const terminate = vi.fn(() => true);
    __setWorkbenchJobNativeForTests({
      spawn: () => ({ pid: process.pid, job: {} }), terminate,
      activeCount: () => 0, drainStatus: () => ({ complete: drained, channels: [] }), close
    });
    spawnTrackedWorkbenchProcess("C:/graceful-drain", {
      executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err"
    });
    const closing = closeTrackedWorkbenchJob("C:/graceful-drain");
    await vi.advanceTimersByTimeAsync(200);
    expect(close).not.toHaveBeenCalled();
    expect(hasTrackedWorkbenchJob("C:/graceful-drain")).toBe(true);
    drained = true;
    await vi.advanceTimersByTimeAsync(100);
    await expect(closing).resolves.toBe(true);
    expect(close).toHaveBeenCalledOnce();
    expect(terminate).not.toHaveBeenCalled();
    expect(hasTrackedWorkbenchJob("C:/graceful-drain")).toBe(false);
  });

  it("accepts the same job already released by the reaper during graceful close", async () => {
    vi.useFakeTimers();
    let drained = false;
    let closed = false;
    const close = vi.fn(() => { closed = true; });
    __setWorkbenchJobNativeForTests({
      spawn: () => ({ pid: process.pid, job: {} }), terminate: () => true,
      activeCount: () => { if (closed) throw new Error("released native handle"); return 0; },
      drainStatus: () => { if (closed) throw new Error("released native handle"); return { complete: drained, channels: [] }; },
      close
    });
    spawnTrackedWorkbenchProcess("C:/graceful-reaper", {
      executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err"
    });
    await vi.advanceTimersByTimeAsync(50);
    const closing = closeTrackedWorkbenchJob("C:/graceful-reaper");
    await vi.advanceTimersByTimeAsync(900);
    drained = true;
    await vi.advanceTimersByTimeAsync(100);
    await expect(closing).resolves.toBe(true);
    expect(close).toHaveBeenCalledOnce();
  });

  it("keeps ownership when graceful log draining exceeds its bounded deadline", async () => {
    vi.useFakeTimers();
    const close = vi.fn();
    __setWorkbenchJobNativeForTests({
      spawn: () => ({ pid: process.pid, job: {} }), terminate: () => true,
      activeCount: () => 0, drainStatus: () => ({ complete: false, channels: [] }), close
    });
    spawnTrackedWorkbenchProcess("C:/graceful-timeout", {
      executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err"
    });
    const closing = closeTrackedWorkbenchJob("C:/graceful-timeout");
    await vi.advanceTimersByTimeAsync(8_000);
    await expect(closing).resolves.toBe(false);
    expect(hasTrackedWorkbenchJob("C:/graceful-timeout")).toBe(true);
    expect(close).not.toHaveBeenCalled();
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
    expect(retireOld.isCurrent()).toBe(true);
    const retirement = terminateTrackedWorkbenchJob("C:/replacement", old.pid);
    expect(() => spawnTrackedWorkbenchProcess("C:/replacement", input)).toThrow("still terminating or draining");
    expect(hasTrackedWorkbenchJob("C:/replacement")).toBe(true);
    drains.set(jobs[0], true);
    await vi.advanceTimersByTimeAsync(100);
    await retirement;
    expect(hasTrackedWorkbenchJob("C:/replacement")).toBe(false);
    expect(retireOld.isCurrent()).toBe(false);
    const replacement = spawnTrackedWorkbenchProcess("C:/replacement", input);
    expect(retireOld.isCurrent()).toBe(false);
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

  it("does not authorize HTTP or native termination of a replacement that reused the same PID", async () => {
    const jobs: object[] = [];
    const terminate = vi.fn(() => true);
    __setWorkbenchJobNativeForTests({
      spawn: () => { const job = {}; jobs.push(job); return { pid: process.pid, job }; },
      terminate, activeCount: () => 0, drainStatus: completeDrainStatus, close: () => undefined
    });
    const input = { executable: "pythonw.exe", arguments: [], cwd: "C:/", env: {}, stdoutPath: "out", stderrPath: "err" };
    spawnTrackedWorkbenchProcess("C:/same-pid-replacement", input);
    const retireOld = captureTrackedWorkbenchJobRetirement("C:/same-pid-replacement", process.pid)!;
    expect(retireOld.isCurrent()).toBe(true);
    spawnTrackedWorkbenchProcess("C:/same-pid-replacement", input);
    expect(retireOld.isCurrent()).toBe(false);
    expect(captureTrackedWorkbenchJobRetirement("C:/same-pid-replacement", process.pid)!.isCurrent()).toBe(true);
    await expect(retireOld()).resolves.toBe(true);
    expect(terminate).not.toHaveBeenCalled();
    expect(hasTrackedWorkbenchJob("C:/same-pid-replacement")).toBe(true);
    expect(jobs).toHaveLength(2);
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
  it("does not terminate a live descendant after the captured root exits", async () => {
    __setWorkbenchJobNativeForTests(undefined);
    const { loadWorkbenchJobNative } = await import("../src/process/workbenchJob.js");
    const native = process.env.VIBELUTION_TEST_JOB_ADDON
      ? createRequire(import.meta.url)(process.env.VIBELUTION_TEST_JOB_ADDON) as WorkbenchJobNative
      : loadWorkbenchJobNative();
    const terminate = vi.fn((job: WorkbenchJobHandle) => native.terminate(job));
    const observed: string[] = [];
    __setWorkbenchJobNativeForTests({ ...native, terminate, activeCount: (job) => { const value = native.activeCount(job); observed.push(`active:${value}`); return value; }, close: (job) => { observed.push("close"); native.close(job); } });
    const directory = mkdtempSync(join(tmpdir(), "vibelution-natural-child-"));
    const childPath = join(directory, "child.txt"), donePath = join(directory, "done.txt"), startPath = join(directory, "start.txt");
    const python = spawnSync("python", ["-c", "import sys; print(sys.executable)"], { encoding: "utf8", windowsHide: true });
    expect(python.status).toBe(0);
    const childCode = `import os,time,pathlib; pathlib.Path(${JSON.stringify(startPath)}).write_text(str(os.getpid())); time.sleep(5); pathlib.Path(${JSON.stringify(donePath)}).write_text('done')`;
    const script = ["import sys,subprocess,pathlib,time;",
      `child=subprocess.Popen([sys.executable,'-c',${JSON.stringify(childCode)}],creationflags=0x08000000);`,
      `pathlib.Path(${JSON.stringify(childPath)}).write_text(str(child.pid));print('root-out',flush=True);print('root-err',file=sys.stderr,flush=True);time.sleep(1.5)`].join("");
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => ["SYSTEMROOT", "WINDIR", "PATH", "PATHEXT"].includes(key.toUpperCase())));
    env.TEMP = directory; env.TMP = directory;
    const spawned = spawnTrackedWorkbenchProcess(directory, { executable: python.stdout.trim(), arguments: ["-c", script], cwd: directory,
      env, containDescendants: true, stdoutPath: join(directory, "stdout.log"), stderrPath: join(directory, "stderr.log") });
    const captured = captureTrackedWorkbenchJobNaturalRetirement(directory, spawned.pid)!;
    try {
      const deadline = Date.now() + 10_000;
      while (!existsSync(childPath) && Date.now() < deadline) await new Promise(done => setTimeout(done, 20));
      const childPid = Number(readFileSync(childPath, "utf8"));
      const monitorPath = join(directory, "monitor.txt");
      const monitor = spawn("python", ["-c", [
        "import ctypes,sys",
        "k=ctypes.WinDLL('kernel32',use_last_error=True)",
        "k.OpenProcess.restype=ctypes.c_void_p",
        "k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]",
        "k.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]",
        "h=k.OpenProcess(0x101000,False,int(sys.argv[1]))",
        "result=k.WaitForSingleObject(h,8000) if h else -1",
        "code=ctypes.c_ulong()",
        "ok=k.GetExitCodeProcess(h,ctypes.byref(code)) if h else 0",
        "open(sys.argv[2],'w').write(f'{result},{ok},{code.value},{ctypes.get_last_error()}')",
      ].join(";"), String(childPid), monitorPath], { windowsHide: true, stdio: "ignore" });
      const monitorExited = new Promise<number | null>(done => monitor.once("exit", done));
      expect(await captured()).toBe(false);
      await new Promise(done => setTimeout(done, 2300));
      expect(pidAlive(spawned.pid)).toBe(false);
      expect(readFileSync(startPath, "utf8")).toBe(String(childPid));
      expect(pidAlive(childPid), `child pid ${childPid}, native exit ${existsSync(monitorPath) ? readFileSync(monitorPath, "utf8") : "missing"}, done ${existsSync(donePath)}, tracked ${hasTrackedWorkbenchJob(directory)}, terminate ${terminate.mock.calls.length}, observations ${observed.join(";")}, stderr: ${existsSync(join(directory, "stderr.log")) ? readFileSync(join(directory, "stderr.log"), "utf8") : "missing"}`).toBe(true);
      expect(await captured()).toBe(false);
      expect(terminate).not.toHaveBeenCalled();
      while (!existsSync(donePath) && Date.now() < deadline) await new Promise(done => setTimeout(done, 20));
      expect(readFileSync(donePath, "utf8")).toBe("done");
      let drained = await captured();
      while (!drained && Date.now() < deadline) { await new Promise(done => setTimeout(done, 20)); drained = await captured(); }
      expect(drained).toBe(true);
      expect(await monitorExited).toBe(0);
      expect(readFileSync(monitorPath, "utf8")).toMatch(/^0,1,0,/);
      expect(readFileSync(join(directory, "stdout.log"), "utf8")).toContain("root-out");
      expect(readFileSync(join(directory, "stderr.log"), "utf8")).toContain("root-err");
      expect(terminate).not.toHaveBeenCalled();
    } finally {
      captured.release();
      if (hasTrackedWorkbenchJob(directory)) await terminateTrackedWorkbenchJob(directory);
      __setWorkbenchJobNativeForTests(undefined);
      rmSync(directory, { recursive: true, force: true });
    }
  }, 15_000);

  it("waits for a real task and graceful backend exit without terminating its Job", async () => {
    __setWorkbenchJobNativeForTests(undefined);
    const { loadWorkbenchJobNative } = await import("../src/process/workbenchJob.js");
    const native = process.env.VIBELUTION_TEST_JOB_ADDON
      ? createRequire(import.meta.url)(process.env.VIBELUTION_TEST_JOB_ADDON) as WorkbenchJobNative
      : loadWorkbenchJobNative();
    const terminate = vi.fn((job: WorkbenchJobHandle) => native.terminate(job));
    const observed: string[] = [];
    __setWorkbenchJobNativeForTests({ ...native, terminate, activeCount: (job) => { const value = native.activeCount(job); observed.push(`active:${value}`); return value; }, close: (job) => { observed.push("close"); native.close(job); } });
    const directory = mkdtempSync(join(tmpdir(), "vibelution-natural-task-"));
    const portPath = join(directory, "port.txt"), donePath = join(directory, "done.txt");
    const script = [
      "const http=require('node:http'),fs=require('node:fs');let active=true;",
      `setTimeout(()=>{active=false;fs.writeFileSync(${JSON.stringify(donePath)},'done');},1800);`,
      "const server=http.createServer((req,res)=>{if(req.url!=='/api/runtime/shutdown'){res.writeHead(404).end();return;}",
      "if(active){res.writeHead(409).end();return;}res.writeHead(202).end();server.close(()=>process.exit(0));});",
      `server.listen(0,'127.0.0.1',()=>fs.writeFileSync(${JSON.stringify(portPath)},String(server.address().port)));`,
    ].join("");
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => ["SYSTEMROOT", "WINDIR", "PATH", "PATHEXT"].includes(key.toUpperCase())));
    env.TEMP = directory; env.TMP = directory;
    const spawned = spawnTrackedWorkbenchProcess(directory, { executable: process.execPath, arguments: ["-e", script], cwd: directory,
      env, containDescendants: true, stdoutPath: join(directory, "stdout.log"), stderrPath: join(directory, "stderr.log") });
    const captured = captureTrackedWorkbenchJobNaturalRetirement(directory, spawned.pid)!;
    try {
      const deadline = Date.now() + 10_000;
      while (!existsSync(portPath) && Date.now() < deadline) await new Promise(done => setTimeout(done, 20));
      expect(existsSync(portPath)).toBe(true);
      const owner = beginNaturalWorkbenchShutdown({ job: captured, port: Number(readFileSync(portPath, "utf8")),
        controlToken: "private-fixture-token", verifyBinding: () => undefined });
      expect(await owner.observe()).toBe("pending");
      expect(pidAlive(spawned.pid)).toBe(true);
      expect(existsSync(donePath)).toBe(false);
      expect(terminate).not.toHaveBeenCalled();
      while (!existsSync(donePath) && Date.now() < deadline) await new Promise(done => setTimeout(done, 20));
      expect(readFileSync(donePath, "utf8")).toBe("done");
      await vi.waitFor(async () => expect(await owner.observe()).toBe("drained"), { timeout: 10_000 });
      expect(pidAlive(spawned.pid)).toBe(false);
      expect(terminate).not.toHaveBeenCalled();
    } finally {
      captured.release();
      if (hasTrackedWorkbenchJob(directory)) await terminateTrackedWorkbenchJob(directory);
      __setWorkbenchJobNativeForTests(undefined);
      rmSync(directory, { recursive: true, force: true });
    }
  }, 30_000);

  it("gracefully closes real output pipes after delayed drain completion", async () => {
    __setWorkbenchJobNativeForTests(undefined);
    const { loadWorkbenchJobNative } = await import("../src/process/workbenchJob.js");
    const native = loadWorkbenchJobNative();
    const directory = mkdtempSync(join(tmpdir(), "vibelution-graceful-drain-"));
    const stdoutPath = join(directory, "stdout.log");
    const stderrPath = join(directory, "stderr.log");
    const releaseAt = Date.now() + 1_200;
    __setWorkbenchJobNativeForTests({
      ...native,
      drainStatus: (job) => {
        const status = native.drainStatus(job);
        return { ...status, complete: status.complete && Date.now() >= releaseAt };
      }
    });
    const spawned = spawnTrackedWorkbenchProcess(directory, {
      executable: process.execPath,
      arguments: ["-e", "process.stdout.write('x'.repeat(65536));process.stderr.write('y'.repeat(65536));"],
      cwd: directory, env: { ...process.env }, stdoutPath, stderrPath
    });
    try {
      await expect(closeTrackedWorkbenchJob(directory)).resolves.toBe(true);
      expect(pidAlive(spawned.pid)).toBe(false);
      expect(hasTrackedWorkbenchJob(directory)).toBe(false);
      expect(readFileSync(stdoutPath, "utf8")).toBe("x".repeat(65536));
      expect(readFileSync(stderrPath, "utf8")).toBe("y".repeat(65536));
    } finally {
      await terminateTrackedWorkbenchJob(directory);
      __setWorkbenchJobNativeForTests(undefined);
      rmSync(directory, { recursive: true, force: true });
    }
  }, 10_000);

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

describe("workbench job native capability", () => {
  it("rejects production addons missing root exit status instead of caching an unsafe binding", async () => {
    vi.resetModules();
    const load = vi.fn(() => ({ drainStatus: completeDrainStatus }));
    vi.doMock("node:module", async (importOriginal) => ({
      ...await importOriginal<typeof import("node:module")>(), createRequire: () => load
    }));
    vi.doMock("node:fs", async (importOriginal) => ({
      ...await importOriginal<typeof import("node:fs")>(), existsSync: () => true
    }));
    try {
      const isolated = await import("../src/process/workbenchJob.js");
      expect(() => isolated.loadWorkbenchJobNative()).toThrow("root process exit status; rebuild the desktop addon");
      expect(() => isolated.loadWorkbenchJobNative()).toThrow("root process exit status; rebuild the desktop addon");
      expect(load).toHaveBeenCalledTimes(2);
      isolated.__setWorkbenchJobNativeForTests({
        spawn: () => ({ pid: process.pid, job: {} }), terminate: () => true,
        activeCount: () => 0, drainStatus: completeDrainStatus, close: () => undefined
      });
      expect(isolated.loadWorkbenchJobNative().exitCode).toBeUndefined();
    } finally {
      vi.doUnmock("node:module");
      vi.doUnmock("node:fs");
      vi.resetModules();
    }
  });
});

function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
