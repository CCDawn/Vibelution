import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { captureFrontendBuildRetirement, runOwnedFrontendBuildBridge } from "../src/process/ownedFrontendBuildBridge.js";
import {
  __setWorkbenchJobNativeForTests, loadWorkbenchJobNative,
  type WorkbenchJobHandle, type WorkbenchJobNative, type WorkbenchJobSpawnInput
} from "../src/process/workbenchJob.js";

type BuildNative = WorkbenchJobNative & { exitCode: (job: WorkbenchJobHandle) => number | null };
type State = { job: object; input: WorkbenchJobSpawnInput; active: number; code: number | null; drained: boolean; closed: boolean };
const roots = new Set<string>();
let settleMock: (() => void) | undefined;
function launch(root = "C:/owned-frontend-test", signal?: AbortSignal) {
  roots.add(root);
  return runOwnedFrontendBuildBridge({ workspaceRoot: root, pythonPath: "pythonw.exe", args: ["build.py"], signal });
}

function mockNative() {
  const states: State[] = [];
  const state = (job: object): State => {
    const current = states.find((item) => item.job === job)!;
    if (current.closed) throw new Error("closed handle");
    return current;
  };
  const native: BuildNative = {
    spawn: vi.fn((input) => {
      const current: State = { job: { generation: states.length }, input, active: 1, code: null, drained: false, closed: false };
      states.push(current);
      writeFileSync(input.stdoutPath, '{"ok":true}');
      writeFileSync(input.stderrPath, "");
      return { pid: 100 + states.length, job: current.job };
    }),
    terminate: vi.fn((job) => { const current = state(job); current.active = 0; current.code ??= 1; return true; }),
    activeCount: (job) => state(job).active,
    exitCode: (job) => state(job).code,
    drainStatus: (job) => ({ complete: state(job).drained, channels: [
      { stream: "stdout", complete: state(job).drained, errorCode: 0, droppedBytes: 0, rotations: 0 }
    ] }),
    close: vi.fn((job) => { state(job).closed = true; })
  };
  __setWorkbenchJobNativeForTests(native);
  settleMock = () => { for (const current of states) Object.assign(current, { drained: true, active: 0, code: 0 }); };
  return { native, states };
}

afterEach(async () => {
  settleMock?.();
  if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(40);
  for (const root of roots) await captureFrontendBuildRetirement(root)();
  vi.useRealTimers();
  roots.clear();
  settleMock = undefined;
  __setWorkbenchJobNativeForTests(undefined);
});

describe("owned frontend build bridge", () => {
  it("registers before yielding and returns stdout only after root, group and drains complete", async () => {
    vi.useFakeTimers();
    const { native, states } = mockNative();
    const output = launch();
    const current = states[0];
    expect(states).toHaveLength(1);
    expect(current.input).toMatchObject({ containDescendants: true, maxLogBytes: 65536 });
    current.code = 0;
    current.active = 0;
    let resolved = false;
    void output.then(() => { resolved = true; });
    await vi.advanceTimersByTimeAsync(20);
    expect(resolved).toBe(false);
    current.drained = true;
    await vi.advanceTimersByTimeAsync(20);
    await expect(output).resolves.toBe('{"ok":true}');
    expect(native.close).toHaveBeenCalledOnce();
    expect(existsSync(dirname(current.input.stdoutPath))).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not spawn for an already aborted request", async () => {
    const { native } = mockNative();
    const controller = new AbortController();
    controller.abort();
    await expect(launch(undefined, controller.signal)).rejects.toMatchObject({ code: "aborted" });
    expect(native.spawn).not.toHaveBeenCalled();
  });

  it("keeps normal build output pending while the root is unsignaled despite empty accounting and completed drains", async () => {
    vi.useFakeTimers();
    const { native, states } = mockNative();
    const output = launch();
    Object.assign(states[0], { active: 0, drained: true });
    let settled = false;
    void output.then(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(40);
    expect(settled).toBe(false);
    expect(native.close).not.toHaveBeenCalled();
    expect(existsSync(states[0].input.stdoutPath)).toBe(true);
    states[0].code = 0;
    await vi.advanceTimersByTimeAsync(20);
    await expect(output).resolves.toBe('{"ok":true}');
    expect(native.close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("retains an unsignaled captured build after empty accounting and complete drains until exact retirement can retry", async () => {
    vi.useFakeTimers();
    const { native, states } = mockNative();
    vi.mocked(native.terminate).mockImplementation((job) => {
      states.find((current) => current.job === job)!.active = 0;
      return true;
    });
    const outcome = launch().catch((error: unknown) => error);
    states[0].drained = true;
    const retire = captureFrontendBuildRetirement("C:/owned-frontend-test");
    const first = retire();
    let settled = false;
    void first.then(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(599);
    expect(settled).toBe(false);
    expect(native.close).not.toHaveBeenCalled();
    expect(existsSync(states[0].input.stdoutPath)).toBe(true);
    await vi.advanceTimersByTimeAsync(1);
    await expect(first).resolves.toBe(false);
    expect(await outcome).toMatchObject({ message: expect.stringContaining("retirement was not confirmed") });
    expect(native.close).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    states[0].code = 1;
    await expect(retire()).resolves.toBe(true);
    expect(native.close).toHaveBeenCalledOnce();
    expect(existsSync(states[0].input.stdoutPath)).toBe(false);
  });

  it("terminates synchronously on abort and waits for real drain completion", async () => {
    vi.useFakeTimers();
    const { native, states } = mockNative();
    const controller = new AbortController();
    const output = launch(undefined, controller.signal);
    const rejected = expect(output).rejects.toMatchObject({ code: "aborted" });
    controller.abort();
    expect(native.terminate).toHaveBeenCalledWith(states[0].job);
    expect(native.close).not.toHaveBeenCalled();
    states[0].drained = true;
    await vi.advanceTimersByTimeAsync(20);
    await rejected;
    expect(native.close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reports nonzero exit rather than treating an idle Job as a successful build", async () => {
    vi.useFakeTimers();
    const { states } = mockNative();
    const output = launch();
    const rejected = expect(output).rejects.toMatchObject({ code: "nonzero_exit", message: "compiler failed" });
    Object.assign(states[0], { code: 9, active: 0, drained: true });
    writeFileSync(states[0].input.stderrPath, "compiler failed");
    await vi.advanceTimersByTimeAsync(20);
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("captures exact old Jobs and never terminates a replacement build", async () => {
    vi.useFakeTimers();
    const { native, states } = mockNative();
    const oldOutput = launch();
    const oldRejected = expect(oldOutput).rejects.toMatchObject({ code: "aborted" });
    const retireOld = captureFrontendBuildRetirement("C:/owned-frontend-test");
    const newOutput = launch();
    states[0].drained = true;
    await expect(retireOld()).resolves.toBe(true);
    await vi.advanceTimersByTimeAsync(20);
    await oldRejected;
    await expect(retireOld()).resolves.toBe(true);
    expect(native.terminate).toHaveBeenCalledTimes(1);
    expect(native.terminate).not.toHaveBeenCalledWith(states[1].job);
    Object.assign(states[1], { code: 0, active: 0, drained: true });
    await vi.advanceTimersByTimeAsync(20);
    await expect(newOutput).resolves.toBe('{"ok":true}');
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reclaims residual children in the original Job after root exit", async () => {
    vi.useFakeTimers();
    const { native, states } = mockNative();
    const output = launch();
    states[0].code = 0;
    await vi.advanceTimersByTimeAsync(20);
    expect(native.terminate).toHaveBeenCalledWith(states[0].job);
    expect(native.close).not.toHaveBeenCalled();
    states[0].drained = true;
    await vi.advanceTimersByTimeAsync(20);
    await expect(output).resolves.toBe('{"ok":true}');
    expect(vi.getTimerCount()).toBe(0);
  });

  it("retains unconfirmed Jobs and logs without a timer, allowing exact retirement retry", async () => {
    vi.useFakeTimers();
    const { native, states } = mockNative();
    const output = launch();
    const rejected = expect(output).rejects.toThrow("retirement was not confirmed");
    const retire = captureFrontendBuildRetirement("C:/owned-frontend-test");
    const first = retire();
    await vi.advanceTimersByTimeAsync(600);
    await expect(first).resolves.toBe(false);
    await rejected;
    expect(native.close).not.toHaveBeenCalled();
    expect(existsSync(states[0].input.stdoutPath)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    states[0].drained = true;
    await expect(retire()).resolves.toBe(true);
    expect(native.close).toHaveBeenCalledOnce();
  });

  it("keeps stdout output_limit behavior and drains bounded stderr", async () => {
    vi.useFakeTimers();
    const { states } = mockNative();
    const output = launch();
    const rejected = expect(output).rejects.toMatchObject({ code: "output_limit" });
    writeFileSync(states[0].input.stdoutPath, "x".repeat(64_001));
    states[0].drained = true;
    await vi.advanceTimersByTimeAsync(20);
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });
});

const windows = process.platform === "win32" ? describe : describe.skip;
windows("real Windows build Job", () => {
  it("distinguishes an active root from the legitimate Windows exit code 259", async () => {
    const addonPath = process.env.VIBELUTION_TEST_BUILD_JOB_ADDON;
    const native = (addonPath ? createRequire(import.meta.url)(addonPath) : loadWorkbenchJobNative()) as BuildNative;
    const directory = mkdtempSync(join(tmpdir(), "vibelution-build-exit-test-"));
    const spawned = native.spawn({ executable: process.execPath, arguments: ["-e", "setTimeout(()=>process.exit(259),100)"],
      cwd: directory, env: { ...process.env }, stdoutPath: join(directory, "stdout.log"), stderrPath: join(directory, "stderr.log") });
    try {
      expect(native.exitCode(spawned.job)).toBeNull();
      const deadline = Date.now() + 5_000;
      while ((native.activeCount(spawned.job) > 0 || !native.drainStatus(spawned.job).complete) && Date.now() < deadline) {
        await new Promise((done) => setTimeout(done, 20));
      }
      expect(native.exitCode(spawned.job)).toBe(259);
    } finally {
      native.terminate(spawned.job);
      const deadline = Date.now() + 1_000;
      while ((native.activeCount(spawned.job) > 0 || !native.drainStatus(spawned.job).complete) && Date.now() < deadline) {
        await new Promise((done) => setTimeout(done, 20));
      }
      native.close(spawned.job);
      rmSync(directory, { recursive: true, force: true });
    }
  }, 10_000);

  it("retains root exit status, reclaims child processes and rejects closed-handle queries", async () => {
    const addonPath = process.env.VIBELUTION_TEST_BUILD_JOB_ADDON;
    const native = (addonPath ? createRequire(import.meta.url)(addonPath) : loadWorkbenchJobNative()) as BuildNative;
    __setWorkbenchJobNativeForTests(native);
    const directory = mkdtempSync(join(tmpdir(), "vibelution-build-job-test-"));
    const childPidPath = join(directory, "child-pid.txt");
    const script = [
      "const {spawn}=require('node:child_process');const fs=require('node:fs');",
      "const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'inherit',windowsHide:true});",
      `fs.writeFileSync(${JSON.stringify(childPidPath)},String(child.pid));`,
      "process.stdout.write('{\"ok\":true}');setTimeout(()=>process.exit(0),100);"
    ].join("");
    let capturedJob: WorkbenchJobHandle | undefined;
    const spawn = native.spawn.bind(native);
    const wrapped: BuildNative = { ...native, spawn: (input) => { const result = spawn(input); capturedJob = result.job; return result; } };
    __setWorkbenchJobNativeForTests(wrapped);
    roots.add(directory);
    try {
      await expect(runOwnedFrontendBuildBridge({ workspaceRoot: directory, pythonPath: process.execPath, args: ["-e", script] }))
        .resolves.toBe('{"ok":true}');
      const childPid = Number(readFileSync(childPidPath, "utf8"));
      expect(childPid).toBeGreaterThan(0);
      expect(() => process.kill(childPid, 0)).toThrow();
      expect(() => native.exitCode(capturedJob!)).toThrow("closed");
    } finally {
      await captureFrontendBuildRetirement(directory)();
      rmSync(directory, { recursive: true, force: true });
    }
  }, 10_000);

  it("immediately cancels a real root and inherited-output child as one Job", async () => {
    const addonPath = process.env.VIBELUTION_TEST_BUILD_JOB_ADDON;
    const native = (addonPath ? createRequire(import.meta.url)(addonPath) : loadWorkbenchJobNative()) as BuildNative;
    __setWorkbenchJobNativeForTests(native);
    const directory = mkdtempSync(join(tmpdir(), "vibelution-build-cancel-test-"));
    const childPidPath = join(directory, "child-pid.txt");
    roots.add(directory);
    const controller = new AbortController();
    const output = runOwnedFrontendBuildBridge({ workspaceRoot: directory, pythonPath: process.execPath, signal: controller.signal, args: ["-e", [
      "const {spawn}=require('node:child_process');const fs=require('node:fs');",
      "const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'inherit',windowsHide:true});",
      `fs.writeFileSync(${JSON.stringify(childPidPath)},String(child.pid));setInterval(()=>{},1000);`
    ].join("")] });
    const rejected = expect(output).rejects.toMatchObject({ code: "aborted" });
    try {
      const deadline = Date.now() + 5_000;
      while (!existsSync(childPidPath) && Date.now() < deadline) await new Promise((done) => setTimeout(done, 20));
      const childPid = Number(readFileSync(childPidPath, "utf8"));
      const started = Date.now();
      controller.abort();
      await rejected;
      expect(Date.now() - started).toBeLessThan(800);
      expect(() => process.kill(childPid, 0)).toThrow();
      await expect(captureFrontendBuildRetirement(directory)()).resolves.toBe(true);
    } finally {
      controller.abort();
      await captureFrontendBuildRetirement(directory)();
      rmSync(directory, { recursive: true, force: true });
    }
  }, 10_000);
});
