import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import {
  CLOSE_BACKOFF_BASE_MS,
  CLOSE_BACKOFF_MAX_MS,
  closeBackoffWindowMs,
  createMainLineCommandQueue,
  trackMainLineBackgroundWork,
  waitForMainLineIntentPersistence,
  type CloseBackoffCoalescedInfo,
  type MainLineLifecycleResult,
  type MainLineQueuedCommand,
} from "../src/lifecycle/mainLine/commandQueue.js";
import { writeMainLineQueueOwnerMarker } from "../src/lifecycle/mainLine/ownerMarker.js";

function ok(operation: string, commandId: string): MainLineLifecycleResult {
  return { schemaVersion: 1, accepted: true, operation, commandId };
}

function blocked(operation: string): MainLineLifecycleResult {
  return {
    schemaVersion: 1,
    accepted: false,
    operation,
    code: "active_work_blocked",
    message: "有进行中的任务，无法停止 Vibelution。请等待任务完成或先停止任务。"
  };
}

describe("mainLineCommandQueue", () => {
  it("exclusive admission fences a detached execution and refuses ordinary and duplicate submissions", async () => {
    const queue = createMainLineCommandQueue(), previousAbort = new AbortController();
    let entered!: () => void, release!: () => void;
    const started = new Promise<void>(resolve => { entered = resolve; });
    const oldWork = new Promise<void>(resolve => { release = resolve; });
    const old = queue.submit({ operation: "start", signal: previousAbort.signal,
      execute: async cmd => { entered(); await oldWork; return ok("start", cmd.commandId); } });
    const oldRejected = old.catch(() => undefined);
    await started; previousAbort.abort(); await oldRejected;
    const execute = vi.fn(async (cmd: MainLineQueuedCommand) => ok(cmd.operation, cmd.commandId));
    const safe = queue.submitExclusive!({ operation: "start", execute });
    await Promise.resolve();
    expect(execute).not.toHaveBeenCalled();
    await expect(queue.submit({ operation: "start", execute })).rejects.toThrow("MAIN_LINE_EXCLUSIVE_BUSY");
    await expect(queue.submit({ operation: "shutdown", execute })).rejects.toThrow("MAIN_LINE_EXCLUSIVE_BUSY");
    await expect(queue.submitExclusive!({ operation: "start", execute })).rejects.toThrow("MAIN_LINE_EXCLUSIVE_BUSY");
    release(); expect((await safe).accepted).toBe(true);
    expect(execute).toHaveBeenCalledTimes(1);
    expect((await queue.submit({ operation: "stop", execute })).accepted).toBe(true);
  });

  it("releases the fence when cancelled before submitting while prior work is still stuck", async () => {
    const queue = createMainLineCommandQueue(), priorAbort = new AbortController(), safeAbort = new AbortController();
    let release!: () => void, entered!: () => void;
    const callback = new Promise<void>(resolve => { release = resolve; });
    const started = new Promise<void>(resolve => { entered = resolve; });
    const prior = queue.submit({ operation: "start", signal: priorAbort.signal,
      onCommand: async () => { entered(); await callback; }, execute: async cmd => ok("start", cmd.commandId) });
    const priorRejected = prior.catch(() => undefined);
    await started; priorAbort.abort(); await priorRejected;
    const execute = vi.fn(async (cmd: MainLineQueuedCommand) => ok(cmd.operation, cmd.commandId));
    const removeListener = vi.spyOn(safeAbort.signal, "removeEventListener");
    const safe = queue.submitExclusive!({ operation: "start", signal: safeAbort.signal, execute });
    const safeRejected = expect(safe).rejects.toThrow("cancel wait");
    await expect(queue.submit({ operation: "stop", execute })).rejects.toThrow("MAIN_LINE_EXCLUSIVE_BUSY");
    safeAbort.abort(new Error("cancel wait"));
    await safeRejected;
    expect(removeListener).toHaveBeenCalledWith("abort", expect.any(Function));
    expect(execute).not.toHaveBeenCalled();
    const ordinary = vi.fn(async (cmd: MainLineQueuedCommand) => ok(cmd.operation, cmd.commandId));
    expect((await queue.submit({ operation: "stop", execute: ordinary })).accepted).toBe(true);
    expect(ordinary).toHaveBeenCalledOnce(); expect(execute).not.toHaveBeenCalled();
    release(); await queue.captureExecutionDrain!();
    expect(execute).not.toHaveBeenCalled();
  });

  it("keeps exclusive admission fenced until aborted work and asynchronous cleanup settle", async () => {
    let releaseWork!: () => void, releaseMarker!: () => void, workEntered!: () => void, markerEntered!: () => void;
    const work = new Promise<void>(resolve => { releaseWork = resolve; });
    const marker = new Promise<void>(resolve => { releaseMarker = resolve; });
    const started = new Promise<void>(resolve => { workEntered = resolve; });
    const markerStarted = new Promise<void>(resolve => { markerEntered = resolve; });
    const queue = createMainLineCommandQueue({ writeOwnerMarker: async () => { markerEntered(); await marker; } });
    const controller = new AbortController();
    const execution = queue.submitExclusive!({ operation: "start", signal: controller.signal,
      execute: async cmd => { workEntered(); await work; return ok("start", cmd.commandId); } });
    let settled = false;
    const rejected = execution.catch(() => { settled = true; });
    await Promise.all([started, markerStarted]);
    controller.abort();
    const normal = vi.fn(async (cmd: MainLineQueuedCommand) => ok(cmd.operation, cmd.commandId));
    await expect(queue.submit({ operation: "stop", execute: normal })).rejects.toThrow("MAIN_LINE_EXCLUSIVE_BUSY");
    releaseWork(); await work; await Promise.resolve();
    expect(settled).toBe(false);
    await expect(queue.submit({ operation: "shutdown", execute: normal })).rejects.toThrow("MAIN_LINE_EXCLUSIVE_BUSY");
    releaseMarker(); await rejected; expect(settled).toBe(true);
    expect((await queue.submit({ operation: "stop", execute: normal })).accepted).toBe(true);
  });

  it("rejects exclusive admission while an ordinary slot is active and does not coalesce with close backoff", async () => {
    const queue = createMainLineCommandQueue(); let release!: () => void, entered!: () => void;
    const work = new Promise<void>(resolve => { release = resolve; });
    const started = new Promise<void>(resolve => { entered = resolve; });
    const execute = vi.fn(async (cmd: MainLineQueuedCommand) => ok(cmd.operation, cmd.commandId));
    const old = queue.submit({ operation: "start", execute: async cmd => { entered(); await work; return ok("start", cmd.commandId); } });
    await started;
    await expect(queue.submitExclusive!({ operation: "start", execute })).rejects.toThrow("MAIN_LINE_EXCLUSIVE_BUSY");
    expect(execute).not.toHaveBeenCalled(); release(); await old;
    await queue.submit({ operation: "stop", execute });
    await queue.captureExecutionDrain!();
    const safe = await queue.submitExclusive!({ operation: "stop", execute });
    expect(safe.joined).toBeUndefined(); expect(execute).toHaveBeenCalledTimes(2);
  });
  it("drains a concurrent passthrough command before exclusive execution", async () => {
    const queue = createMainLineCommandQueue(); let enter!: () => void, release!: () => void;
    const started = new Promise<void>(resolve => { enter = resolve; });
    const work = new Promise<void>(resolve => { release = resolve; });
    const ordinary = queue.submit({ operation: "shutdown", execute: async cmd => {
      enter(); await work; return ok(cmd.operation, cmd.commandId);
    }});
    await started;
    const execute = vi.fn(async (cmd: MainLineQueuedCommand) => ok(cmd.operation, cmd.commandId));
    const safe = queue.submitExclusive!({ operation: "start", execute });
    await Promise.resolve(); expect(execute).not.toHaveBeenCalled();
    await expect(queue.submit({ operation: "shutdown", execute })).rejects.toThrow("MAIN_LINE_EXCLUSIVE_BUSY");
    release(); await ordinary; await safe;
    expect(execute).toHaveBeenCalledOnce();
  });

  it("exclusive admission drains background settlement and owner-marker writes without delaying ordinary results", async () => {
    let releaseMarker!: () => void, releaseSettlement!: () => void;
    const marker = new Promise<void>(resolve => { releaseMarker = resolve; });
    const settlement = new Promise<void>(resolve => { releaseSettlement = resolve; });
    const queue = createMainLineCommandQueue({ writeOwnerMarker: () => marker });
    const ordinary = await queue.submit({ operation: "start", execute: async cmd => {
      trackMainLineBackgroundWork(cmd, settlement);
      return ok("start", cmd.commandId);
    }});
    expect(ordinary.accepted).toBe(true);
    await vi.waitFor(() => expect(queue.snapshot().active).toBeNull());
    const execute = vi.fn(async (cmd: MainLineQueuedCommand) => ok(cmd.operation, cmd.commandId));
    const safe = queue.submitExclusive!({ operation: "start", execute });
    await Promise.resolve(); expect(execute).not.toHaveBeenCalled();
    releaseSettlement(); await settlement; await Promise.resolve();
    expect(execute).not.toHaveBeenCalled();
    releaseMarker(); expect((await safe).accepted).toBe(true);
    expect(execute).toHaveBeenCalledOnce();
  });

  it("waits for an aborted admission callback's actual completion", async () => {
    const queue = createMainLineCommandQueue(), abort = new AbortController();
    let entered!: () => void, release!: () => void;
    const started = new Promise<void>(resolve => { entered = resolve; });
    const pending = new Promise<void>(resolve => { release = resolve; });
    const request = queue.submit({ operation: "start", signal: abort.signal,
      onCommand: async () => { entered(); await pending; }, execute: async cmd => ok("start", cmd.commandId) });
    const rejected = request.catch(() => undefined);
    await started; abort.abort(); await rejected;
    let drained = false;
    const drain = queue.captureExecutionDrain!().then(() => { drained = true; });
    await Promise.resolve(); expect(drained).toBe(false);
    release(); await drain; expect(drained).toBe(true);
  });

  it("waits for real intent and owner-marker writes after command settlement", async () => {
    let releaseIntent!: () => void, releaseMarker!: () => void, enteredIntent!: () => void, enteredMarker!: () => void;
    const intent = new Promise<void>(resolve => { releaseIntent = resolve; });
    const marker = new Promise<void>(resolve => { releaseMarker = resolve; });
    const intentStarted = new Promise<void>(resolve => { enteredIntent = resolve; });
    const markerStarted = new Promise<void>(resolve => { enteredMarker = resolve; });
    const queue = createMainLineCommandQueue({ persistIntent: async () => { enteredIntent(); await intent; },
      writeOwnerMarker: async () => { enteredMarker(); await marker; } });
    await queue.submit({ operation: "start", execute: async cmd => ok("start", cmd.commandId) });
    await Promise.all([intentStarted, markerStarted]);
    let drained = false;
    const drain = queue.captureExecutionDrain!().then(() => { drained = true; });
    releaseIntent(); await intent; await Promise.resolve();
    expect(drained).toBe(false);
    releaseMarker(); await drain; expect(drained).toBe(true);
  });
  it("drains underlying execution after abort without delaying a subsequent command", async () => {
    const queue = createMainLineCommandQueue();
    const controller = new AbortController();
    let finish!: () => void;
    let entered!: () => void;
    const started = new Promise<void>(resolve => { entered = resolve; });
    const work = new Promise<void>(resolve => { finish = resolve; });
    const first = queue.submit({ operation: "start", signal: controller.signal, execute: async cmd => {
      entered(); await work; return ok("start", cmd.commandId);
    }});
    const rejected = first.catch(() => undefined);
    await started;
    controller.abort();
    await rejected;
    const next = await queue.submit({ operation: "stop", execute: async cmd => ok("stop", cmd.commandId) });
    expect(next.accepted).toBe(true);
    let drained = false;
    const drain = queue.captureExecutionDrain!().then(() => { drained = true; });
    await Promise.resolve();
    expect(drained).toBe(false);
    finish();
    await drain;
    expect(drained).toBe(true);
  });

  it("captures a queued command even when its execution begins after capture", async () => {
    const queue = createMainLineCommandQueue();
    let releaseFirst!: () => void;
    let releaseSecond!: () => void;
    let enteredSecond!: () => void;
    const firstWork = new Promise<void>(resolve => { releaseFirst = resolve; });
    const secondWork = new Promise<void>(resolve => { releaseSecond = resolve; });
    const secondStarted = new Promise<void>(resolve => { enteredSecond = resolve; });
    const first = queue.submit({ operation: "start", execute: async cmd => { await firstWork; return ok("start", cmd.commandId); } });
    const second = queue.submit({ operation: "stop", execute: async cmd => { enteredSecond(); await secondWork; return ok("stop", cmd.commandId); } });
    let drained = false;
    const drain = queue.captureExecutionDrain!().then(() => { drained = true; });
    releaseFirst();
    await first;
    await secondStarted;
    expect(drained).toBe(false);
    releaseSecond();
    await second;
    await drain;
    expect(drained).toBe(true);
  });
  it("records the Electron executable with the marker timestamp", async () => {
    const dir = mkdtempSync(join(tmpdir(), "vibelution-main-line-owner-"));
    try {
      const marker = await writeMainLineQueueOwnerMarker(dir, {
        pid: 4242,
        executable: "C:/Vibelution/Vibelution.exe",
        nowMs: Date.parse("2026-08-20T10:00:00Z"),
      });
      expect(marker).toMatchObject({
        pid: 4242,
        executable: "C:/Vibelution/Vibelution.exe",
        updatedAt: "2026-08-20T10:00:00.000Z",
      });
      expect(JSON.parse(readFileSync(join(dir, "main_line_queue_owner.json"), "utf8"))).toEqual(marker);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("joins ten restarts in one second onto a single execute", async () => {
    const execute = vi.fn().mockImplementation(
      (command: { commandId: string; operation: string }) =>
        new Promise<MainLineLifecycleResult>((resolve) => {
          setTimeout(() => resolve(ok(command.operation, command.commandId)), 25);
        }),
    );
    const queue = createMainLineCommandQueue({ now: () => Date.parse("2026-08-20T10:00:00Z") });
    const results = await Promise.all(
      Array.from({ length: 10 }, () => queue.submit({ operation: "restart", noBrowser: true, execute })),
    );
    expect(execute).toHaveBeenCalledTimes(1);
    const commandId = results[0]?.commandId;
    expect(commandId).toMatch(/^cmd_/);
    expect(results.every((result) => result.accepted && result.commandId === commandId)).toBe(true);
    expect(results.slice(1).every((result) => result.joined === true)).toBe(true);
    expect(queue.snapshot()).toEqual({ active: null, pending: [] });
  });

  it("lets close supersede a pending restart while the current start finishes", async () => {
    let releaseStart: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      releaseStart = resolve;
    });
    const execute = vi.fn().mockImplementation(
      (command: { commandId: string; operation: string }) => {
        if (command.operation === "start") {
          return gate.then(() => ok("start", command.commandId));
        }
        return Promise.resolve(ok(command.operation, command.commandId));
      },
    );
    const queue = createMainLineCommandQueue();
    const start = queue.submit({ operation: "start", noBrowser: true, execute });
    await Promise.resolve();
    const restart = queue.submit({ operation: "restart", noBrowser: true, execute });
    const close = queue.submit({ operation: "stop", execute });
    releaseStart?.();
    const [started, restarted, closed] = await Promise.all([start, restart, close]);
    expect(started.accepted).toBe(true);
    expect(restarted).toMatchObject({ accepted: false, code: "lifecycle_intent_superseded" });
    expect(closed.accepted).toBe(true);
    expect(execute.mock.calls.map((call) => call[0].operation)).toEqual(["start", "stop"]);
  });

  it("lets restart supersede a pending close", async () => {
    let releaseStart: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      releaseStart = resolve;
    });
    const execute = vi.fn().mockImplementation(
      (command: { commandId: string; operation: string }) => {
        if (command.operation === "start") {
          return gate.then(() => ok("start", command.commandId));
        }
        return Promise.resolve(ok(command.operation, command.commandId));
      },
    );
    const queue = createMainLineCommandQueue();
    const start = queue.submit({ operation: "start", noBrowser: true, execute });
    await Promise.resolve();
    const close = queue.submit({ operation: "stop", execute });
    const restart = queue.submit({ operation: "restart", noBrowser: true, execute });
    releaseStart?.();
    const [, closed, restarted] = await Promise.all([start, close, restart]);
    expect(closed).toMatchObject({ accepted: false, code: "lifecycle_intent_superseded" });
    expect(restarted.accepted).toBe(true);
    expect(execute.mock.calls.map((call) => call[0].operation)).toEqual(["start", "restart"]);
  });

  it("does not join a visible-browser open onto a no-browser open", async () => {
    const execute = vi.fn().mockImplementation(
      (command: { commandId: string; operation: string }) => Promise.resolve(ok(command.operation, command.commandId)),
    );
    const queue = createMainLineCommandQueue();
    const first = await queue.submit({ operation: "start", noBrowser: true, execute });
    const second = await queue.submit({ operation: "start", noBrowser: false, execute });
    expect(first.commandId).not.toBe(second.commandId);
    expect(execute).toHaveBeenCalledTimes(2);
  });

  it("persists desired intent for crash recovery", async () => {
    const intents: Array<{ desiredState: string; operation: string }> = [];
    const queue = createMainLineCommandQueue({
      persistIntent: (intent) => {
        intents.push({ desiredState: intent.desiredState, operation: intent.operation });
      },
    });
    await queue.submit({
      operation: "restart",
      noBrowser: true,
      execute: (command) => Promise.resolve(ok("restart", command.commandId)),
    });
    expect(intents.some((intent) => intent.desiredState === "open" && intent.operation === "restart")).toBe(true);
  });
});

describe("mainLineCommandQueue durable request admission", () => {
  it("does not let a failed pending association erase a valid active intent", async () => {
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const intents: string[] = [];
    const queue = createMainLineCommandQueue({ persistIntent: intent => { intents.push(intent.operation); } });
    const active = queue.submit({ operation: "start", onCommand: () => gate, execute: async command => {
      await waitForMainLineIntentPersistence(command);
      return ok(command.operation, command.commandId);
    } });
    const pending = queue.submit({ operation: "stop", onCommand: async () => { throw new Error("bind failed"); }, execute: async command => ok(command.operation, command.commandId) });
    const rejected = expect(pending).rejects.toThrow("bind failed");
    release();
    await active; await rejected;
    expect(intents).toContain("start");
    expect(intents).not.toContain("stop");
  });

  it.each(["join", "passthrough"])("cancels a stalled %s association without waiting for its callback", async kind => {
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const signal = new AbortController();
    const queue = createMainLineCommandQueue();
    const execute = vi.fn(async command => ok(command.operation, command.commandId));
    let entered!: () => void;
    const started = new Promise<void>(resolve => { entered = resolve; });
    const active = kind === "join" ? queue.submit({ operation: "restart", execute: async command => { await gate; return ok(command.operation, command.commandId); } }) : Promise.resolve();
    const request = queue.submit({ operation: kind === "join" ? "restart" : "shutdown", signal: signal.signal, onCommand: () => { entered(); return gate; }, execute });
    const outcome = request.then(() => "resolved", () => "cancelled");
    await started;
    signal.abort(new Error("cancel stalled bind"));
    expect(await Promise.race([outcome, new Promise(resolve => setTimeout(() => resolve("stalled"), 30))])).toBe("cancelled");
    let drained = false;
    const drain = queue.captureExecutionDrain!().then(() => { drained = true; });
    await Promise.resolve(); expect(drained).toBe(false);
    release(); await active; await drain;
  });
  it("waits for durable association before native intent and execution", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const events: string[] = [];
    const queue = createMainLineCommandQueue({ persistIntent: () => { events.push("intent"); } });
    const result = queue.submit({
      operation: "restart",
      onCommand: async (command) => {
        expect(Object.keys(command).sort()).toEqual(["commandId", "noBrowser", "operation", "type"]);
        command.operation = "stop"; // Only the detached projection can be changed.
        await gate;
        events.push("bound");
      },
      execute: async (command) => {
        events.push("execute");
        expect(command.operation).toBe("restart");
        return ok(command.operation, command.commandId);
      },
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(events).toEqual([]);
    release();
    await result;
    expect(events[0]).toBe("bound");
    expect(events).toContain("intent");
    expect(events).toContain("execute");
  });

  it("does not persist or execute when the association fails", async () => {
    const persistIntent = vi.fn();
    const execute = vi.fn(async (command: MainLineQueuedCommand) => ok(command.operation, command.commandId));
    const queue = createMainLineCommandQueue({ persistIntent });
    await expect(queue.submit({
      operation: "start", execute,
      onCommand: async () => { throw new Error("association failed"); },
    })).rejects.toThrow("association failed");
    expect(persistIntent).not.toHaveBeenCalled();
    expect(execute).not.toHaveBeenCalled();
  });

  it("associates joined and backoff requests with the actual native command", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const commands: MainLineQueuedCommand[] = [];
    const onCommand = async (command: MainLineQueuedCommand) => { commands.push(command); };
    const execute = vi.fn(async (command: MainLineQueuedCommand) => {
      if (command.operation === "restart") await gate;
      return ok(command.operation, command.commandId);
    });
    const queue = createMainLineCommandQueue();
    const restart = queue.submit({ operation: "restart", onCommand, execute });
    const joined = queue.submit({ operation: "start", onCommand, execute });
    release();
    const [first, second] = await Promise.all([restart, joined]);
    expect(first.commandId).toBe(second.commandId);
    expect(commands.slice(0, 2)).toEqual([
      expect.objectContaining({ commandId: first.commandId, operation: "restart" }),
      expect.objectContaining({ commandId: first.commandId, operation: "restart" }),
    ]);
    const stop = await queue.submit({ operation: "stop", onCommand, execute });
    const backoff = await queue.submit({ operation: "stop", onCommand, execute });
    expect(backoff.code).toBe("close_backoff_coalesced");
    expect(commands.slice(2).map((command) => command.commandId)).toEqual([stop.commandId, stop.commandId]);
    expect(execute).toHaveBeenCalledTimes(2);
  });

  it("cancels an admission without blocking its replacement or writing a late intent", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const signal = new AbortController();
    const intents: string[] = [];
    const queue = createMainLineCommandQueue({ persistIntent: (intent) => { intents.push(intent.operation); } });
    const execute = vi.fn(async (command: MainLineQueuedCommand) => {
      await waitForMainLineIntentPersistence(command);
      return ok(command.operation, command.commandId);
    });
    const first = queue.submit({ operation: "start", signal: signal.signal, onCommand: () => gate, execute });
    const rejected = expect(first).rejects.toThrow("cancel admission");
    signal.abort(new Error("cancel admission"));
    const replacement = queue.submit({ operation: "stop", execute });
    await replacement;
    release();
    await rejected;
    await Promise.resolve();
    expect(intents.length).toBeGreaterThan(0);
    expect(intents.every((operation) => operation === "stop")).toBe(true);
    expect(execute.mock.calls.map(([command]) => command.operation)).toEqual(["stop"]);
  });
});

describe("mainLineCommandQueue close backoff", () => {
  it("grows the window exponentially and caps it", () => {
    expect(closeBackoffWindowMs(1)).toBe(2_000);
    expect(closeBackoffWindowMs(2)).toBe(4_000);
    expect(closeBackoffWindowMs(3)).toBe(8_000);
    expect(closeBackoffWindowMs(4)).toBe(16_000);
    expect(closeBackoffWindowMs(5)).toBe(32_000);
    expect(closeBackoffWindowMs(6)).toBe(CLOSE_BACKOFF_MAX_MS);
    expect(closeBackoffWindowMs(50)).toBe(CLOSE_BACKOFF_MAX_MS);
  });

  it("coalesces a close retry storm onto the previous close result", async () => {
    let clock = Date.parse("2026-08-20T10:00:00Z");
    const coalesced: CloseBackoffCoalescedInfo[] = [];
    const execute = vi.fn().mockImplementation((command: { commandId: string; operation: string }) =>
      Promise.resolve(blocked(command.operation)));
    const queue = createMainLineCommandQueue({
      now: () => clock,
      onCloseBackoffCoalesced: (info) => coalesced.push(info),
    });
    const first = await queue.submit({ operation: "stop", execute });
    expect(first).toMatchObject({ accepted: false, code: "active_work_blocked" });
    expect(execute).toHaveBeenCalledTimes(1);

    // A 1.5s retry storm is absorbed by the first backoff window.
    clock += 1_500;
    const second = await queue.submit({ operation: "stop", execute });
    expect(second).toMatchObject({
      joined: true,
      code: "close_backoff_coalesced",
      accepted: false,
      operation: "stop",
    });
    expect(execute).toHaveBeenCalledTimes(1);
    expect(coalesced).toEqual([
      { operation: "stop", runs: 1, backoffMs: CLOSE_BACKOFF_BASE_MS, ageMs: 1_500 }
    ]);
  });

  it("re-executes the close after the window expires and widens the next window", async () => {
    let clock = Date.parse("2026-08-20T10:00:00Z");
    const execute = vi.fn().mockImplementation((command: { commandId: string; operation: string }) =>
      Promise.resolve(blocked(command.operation)));
    const queue = createMainLineCommandQueue({ now: () => clock });
    await queue.submit({ operation: "stop", execute });

    clock += CLOSE_BACKOFF_BASE_MS + 1;
    await queue.submit({ operation: "stop", execute });
    expect(execute).toHaveBeenCalledTimes(2);

    // Second execution extends the chain: the window is now 4s.
    clock += 3_000;
    const coalesced = await queue.submit({ operation: "stop", execute });
    expect(coalesced.code).toBe("close_backoff_coalesced");
    expect(execute).toHaveBeenCalledTimes(2);

    clock += 1_500;
    await queue.submit({ operation: "stop", execute });
    expect(execute).toHaveBeenCalledTimes(3);
  });

  it("counts a failed close execution into the backoff chain", async () => {
    let clock = Date.parse("2026-08-20T10:00:00Z");
    const execute = vi.fn().mockImplementation(() => Promise.reject(new Error("graceful shutdown timed out")));
    const queue = createMainLineCommandQueue({ now: () => clock });
    await expect(queue.submit({ operation: "stop", execute })).rejects.toThrow("graceful shutdown timed out");
    clock += 1_000;
    const coalesced = await queue.submit({ operation: "stop", execute });
    expect(coalesced.code).toBe("close_backoff_coalesced");
    expect(execute).toHaveBeenCalledTimes(1);
  });

  it("never coalesces an explicit force-close request", async () => {
    let clock = Date.parse("2026-08-20T10:00:00Z");
    const execute = vi.fn().mockImplementation((command: { commandId: string; operation: string }) =>
      Promise.resolve(ok(command.operation, command.commandId)));
    const queue = createMainLineCommandQueue({ now: () => clock });
    await queue.submit({ operation: "stop", execute });
    clock += 500;
    await queue.submit({ operation: "force-stop", execute });
    expect(execute).toHaveBeenCalledTimes(2);
  });

  it("breaks the backoff chain when an open or restart runs in between", async () => {
    let clock = Date.parse("2026-08-20T10:00:00Z");
    const execute = vi.fn().mockImplementation((command: { commandId: string; operation: string }) =>
      Promise.resolve(ok(command.operation, command.commandId)));
    const queue = createMainLineCommandQueue({ now: () => clock });
    await queue.submit({ operation: "stop", execute });
    clock += 100;
    await queue.submit({ operation: "start", noBrowser: true, execute });
    clock += 100;
    await queue.submit({ operation: "stop", execute });
    expect(execute).toHaveBeenCalledTimes(3);
  });
});
