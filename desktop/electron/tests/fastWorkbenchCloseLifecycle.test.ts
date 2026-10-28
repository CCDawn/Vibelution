import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { executeMainLineWorkbench } from "../src/process/workbenchBackend.js";
import { closeOwnedWorkbenchFast } from "../src/process/fastWorkbenchClose.js";
import { getBackgroundWorkbenchRetirement } from "../src/process/backgroundWorkbenchRetirement.js";
import { createMainLineCommandQueue, type MainLineQueuedCommand } from "../src/lifecycle/mainLine/commandQueue.js";

vi.mock("../src/process/fastWorkbenchClose.js", () => ({ closeOwnedWorkbenchFast: vi.fn() }));
const directories: string[] = [];
afterEach(() => { for (const path of directories.splice(0)) rmSync(path, { recursive: true, force: true }); vi.clearAllMocks(); });

describe("explicit fast close lifecycle", () => {
  function fixture() {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-fast-close-lifecycle-"));
    directories.push(workspaceRoot);
    const previous = { spawnPid: 123, backendPid: 456, workbenchPort: 8000, desiredState: "open" };
    const writeState = vi.fn();
    const listActiveWork = vi.fn(() => { throw new Error("must not scan active work"); });
    const captureProcessIdentity = vi.fn(async () => { throw new Error("must not spawn Python"); });
    return { input: { workspaceRoot, pythonPath: "unused", operation: "force-stop" as const,
      command: { commandId: "cmd_fast", type: "force_close" as const, operation: "force-stop" as const, noBrowser: true },
      fastCloseTiming: { deadlineAt: Date.now() + 1800, forceAt: Date.now() + 1200 },
      readState: () => previous, writeState, listActiveWork, captureProcessIdentity,
      readDaemonPid: () => 0, pidAlive: (pid: number) => pid > 0 }, writeState, previous, listActiveWork, captureProcessIdentity };
  }
  it("records closed only after owned Job and listener retirement succeeds", async () => {
    const f = fixture();
    vi.mocked(closeOwnedWorkbenchFast).mockResolvedValue(true);
    expect((await executeMainLineWorkbench(f.input)).accepted).toBe(true);
    expect(closeOwnedWorkbenchFast).toHaveBeenCalledWith(expect.objectContaining({ spawnPid: 123, ...f.input.fastCloseTiming }));
    expect(f.writeState).toHaveBeenCalledWith(expect.objectContaining({ desiredState: "closed", observedState: "closed", spawnPid: 0, backendPid: 0 }));
    expect(f.listActiveWork).not.toHaveBeenCalled();
    expect(f.captureProcessIdentity).not.toHaveBeenCalled();
  });
  it("retains every handle on failed retirement instead of reporting closed", async () => {
    const f = fixture();
    vi.mocked(closeOwnedWorkbenchFast).mockResolvedValue(false);
    expect((await executeMainLineWorkbench(f.input)).accepted).toBe(false);
    expect(f.writeState).not.toHaveBeenCalled();
    expect(f.previous.spawnPid).toBe(123);
  });
  it("does not erase the registration of a separately live daemon", async () => {
    const f = fixture();
    const result = await executeMainLineWorkbench({ ...f.input, readDaemonPid: () => 789 });
    expect(result.accepted).toBe(false);
    expect(closeOwnedWorkbenchFast).not.toHaveBeenCalled();
    expect(f.writeState).not.toHaveBeenCalled();
  });

  function backgroundFixture() {
    const f = fixture();
    let state: Record<string, unknown> = { ...f.previous };
    let jobRetired = false;
    let portListening = true;
    const retire = Object.assign(vi.fn(async () => jobRetired), { isCurrent: () => true });
    const captureRetirement = vi.fn(() => retire);
    const builds = vi.fn(async () => true);
    vi.mocked(closeOwnedWorkbenchFast).mockResolvedValue(false);
    return { ...f, captureRetirement, retire, builds,
      input: { ...f.input, readState: () => state,
        writeState: async (next: Record<string, unknown>) => { state = next; f.writeState(next); },
        connect: async () => portListening, captureRetirement,
        fastCloseTiming: { ...f.input.fastCloseTiming, background: { retireFrontendBuilds: builds } } },
      state: () => state, retireJob: () => { jobRetired = true; }, releasePort: () => { portListening = false; },
      supersede: () => { state = { ...state, spawnPid: 999, phase: "starting", desiredState: "open" }; }
    };
  }

  it("admits background closing, retains identities and blocks start until all resource proofs arrive", async () => {
    vi.useFakeTimers();
    const f = backgroundFixture();
    try {
      expect(await executeMainLineWorkbench(f.input)).toMatchObject({ accepted: true, code: "backend_retiring" });
      const owner = getBackgroundWorkbenchRetirement(f.input.workspaceRoot)!;
      expect(owner.status).toBe("pending");
      expect(f.state()).toMatchObject({ desiredState: "closed", phase: "stopping", spawnPid: 123, backendPid: 456 });
      expect(f.captureRetirement).toHaveBeenCalledTimes(1);
      expect((await executeMainLineWorkbench({ ...f.input, operation: "start" })).accepted).toBe(false);
      f.retireJob();
      await vi.advanceTimersByTimeAsync(251);
      expect(owner.status).toBe("pending");
      expect(f.state().spawnPid).toBe(123);
      f.releasePort();
      await vi.advanceTimersByTimeAsync(251);
      expect(await owner.completion).toBe("closed");
      expect(f.state()).toMatchObject({ observedState: "closed", phase: "steady", spawnPid: 0, backendPid: 0 });
      expect(f.builds).toHaveBeenCalledTimes(1);
      expect(f.captureRetirement).toHaveBeenCalledTimes(1);
    } finally {
      f.supersede();
      await vi.advanceTimersByTimeAsync(251);
      vi.useRealTimers();
    }
  });

  it("drains background retirement before exclusive queue execution", async () => {
    vi.useFakeTimers();
    const f = backgroundFixture(), queue = createMainLineCommandQueue();
    try {
      const closing = await queue.submit({ operation: "force-stop", execute: command =>
        executeMainLineWorkbench({ ...f.input, command }) });
      expect(closing).toMatchObject({ accepted: true, code: "backend_retiring" });
      await vi.advanceTimersByTimeAsync(0);
      expect(queue.snapshot().active).toBeNull();
      const execute = vi.fn(async (command: MainLineQueuedCommand) => ({ schemaVersion: 1 as const, accepted: true,
        operation: command.operation, commandId: command.commandId }));
      const safe = queue.submitExclusive!({ operation: "start", execute });
      await vi.advanceTimersByTimeAsync(0);
      expect(execute).not.toHaveBeenCalled();
      f.retireJob(); await vi.advanceTimersByTimeAsync(251);
      expect(execute).not.toHaveBeenCalled();
      f.releasePort(); await vi.advanceTimersByTimeAsync(251);
      expect((await safe).accepted).toBe(true);
      expect(execute).toHaveBeenCalledOnce();
      expect(f.state()).toMatchObject({ observedState: "closed", phase: "steady" });
    } finally {
      f.supersede(); await vi.advanceTimersByTimeAsync(251); vi.useRealTimers();
    }
  });

  it("releases an unsubmitted exclusive wait on cancellation while background retirement remains pending", async () => {
    vi.useFakeTimers();
    const f = backgroundFixture(), queue = createMainLineCommandQueue(), abort = new AbortController();
    try {
      const close = await queue.submit({ operation: "force-stop", execute: command =>
        executeMainLineWorkbench({ ...f.input, command }) });
      expect(close.code).toBe("backend_retiring");
      await vi.advanceTimersByTimeAsync(0);
      const owner = getBackgroundWorkbenchRetirement(f.input.workspaceRoot)!;
      expect(owner.status).toBe("pending");
      const safeExecute = vi.fn(async (command: MainLineQueuedCommand) => ({ schemaVersion: 1 as const,
        accepted: true, operation: command.operation }));
      const safe = queue.submitExclusive!({ operation: "start", signal: abort.signal, execute: safeExecute });
      const cancelled = expect(safe).rejects.toThrow("cancel pending start");
      abort.abort(new Error("cancel pending start")); await cancelled;
      const ordinary = await queue.submit({ operation: "shutdown", execute: async command => ({
        schemaVersion: 1, accepted: true, operation: command.operation }) });
      expect(ordinary.accepted).toBe(true);
      expect(owner.status).toBe("pending"); expect(safeExecute).not.toHaveBeenCalled();
      f.retireJob(); f.releasePort(); await vi.advanceTimersByTimeAsync(251);
      expect(await owner.completion).toBe("closed");
      expect(safeExecute).not.toHaveBeenCalled();
    } finally {
      f.supersede(); await vi.advanceTimersByTimeAsync(251); vi.useRealTimers();
    }
  });

  it("does not clear a new identity when the old background retirement completes late", async () => {
    vi.useFakeTimers();
    const f = backgroundFixture();
    try {
      await executeMainLineWorkbench(f.input);
      const owner = getBackgroundWorkbenchRetirement(f.input.workspaceRoot)!;
      f.supersede();
      f.retireJob();
      f.releasePort();
      await vi.advanceTimersByTimeAsync(251);
      expect(await owner.completion).toBe("superseded");
      expect(f.state()).toMatchObject({ spawnPid: 999, desiredState: "open", phase: "starting" });
      expect(f.writeState).toHaveBeenCalledTimes(1);
    } finally {
      f.supersede();
      await vi.advanceTimersByTimeAsync(251);
      vi.useRealTimers();
    }
  });

  it("keeps the original background owner through an unavailable state observation", async () => {
    vi.useFakeTimers();
    const f = backgroundFixture();
    const readState = vi.fn(() => f.state());
    try {
      await executeMainLineWorkbench({ ...f.input, readState });
      const owner = getBackgroundWorkbenchRetirement(f.input.workspaceRoot)!;
      readState.mockReturnValue({});
      f.retireJob();
      f.releasePort();
      await vi.advanceTimersByTimeAsync(501);
      expect(owner.status).toBe("pending");
      expect(f.retire).not.toHaveBeenCalled();
      readState.mockImplementation(() => f.state());
      await vi.advanceTimersByTimeAsync(251);
      expect(await owner.completion).toBe("closed");
      expect(f.captureRetirement).toHaveBeenCalledTimes(1);
    } finally {
      readState.mockImplementation(() => f.state());
      f.supersede();
      await vi.advanceTimersByTimeAsync(251);
      vi.useRealTimers();
    }
  });

  it("persists stopping and waits for captured builds even when no backend was registered", async () => {
    vi.useFakeTimers();
    const f = backgroundFixture();
    let state: Record<string, unknown> = { desiredState: "closed", phase: "steady", spawnPid: 0, backendPid: 0 };
    f.builds.mockResolvedValue(false);
    try {
      await executeMainLineWorkbench({ ...f.input, readState: () => state,
        writeState: async (next) => { state = next; }, captureRetirement: () => null, connect: async () => false });
      const owner = getBackgroundWorkbenchRetirement(f.input.workspaceRoot)!;
      expect(state).toMatchObject({ desiredState: "closed", phase: "stopping" });
      await vi.advanceTimersByTimeAsync(251);
      expect(owner.status).toBe("pending");
      expect(closeOwnedWorkbenchFast).not.toHaveBeenCalled();
      f.builds.mockResolvedValue(true);
      await vi.advanceTimersByTimeAsync(251);
      expect(await owner.completion).toBe("closed");
      expect(state).toMatchObject({ observedState: "closed", phase: "steady" });
    } finally {
      state = { ...state, desiredState: "open", phase: "starting" };
      await vi.advanceTimersByTimeAsync(251);
      vi.useRealTimers();
    }
  });

  it("preserves state metadata through a single unavailable observation at each retirement read", async () => {
    vi.useFakeTimers();
    const metadata = { schemaVersion: 1, backendPort: 8177, host: "127.0.0.1", url: "http://127.0.0.1:8177" };
    const scenario = async (faultAt?: number): Promise<number> => {
      const f = backgroundFixture();
      Object.assign(f.state(), metadata);
      let reads = 0;
      const readState = () => ++reads === faultAt ? {} : f.state();
      try {
        if (faultAt === 1) {
          await expect(executeMainLineWorkbench({ ...f.input, readState })).rejects.toThrow("admission state is unavailable");
          expect(f.writeState).not.toHaveBeenCalled();
        } else {
          await executeMainLineWorkbench({ ...f.input, readState });
          const owner = getBackgroundWorkbenchRetirement(f.input.workspaceRoot)!;
          f.retireJob();
          f.releasePort();
          for (let attempt = 0; attempt < 8 && owner.status === "pending"; attempt++) await vi.advanceTimersByTimeAsync(251);
          expect(owner.status).toBe("closed");
          expect(f.state()).toMatchObject({ ...metadata, observedState: "closed", phase: "steady" });
        }
        return reads;
      } finally {
        f.supersede();
        await vi.advanceTimersByTimeAsync(251);
      }
    };
    try {
      const reads = await scenario();
      for (let faultAt = 1; faultAt <= reads; faultAt++) await scenario(faultAt);
    } finally {
      vi.useRealTimers();
    }
  });
});
