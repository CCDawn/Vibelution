import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import {
  CLOSE_BACKOFF_BASE_MS,
  CLOSE_BACKOFF_MAX_MS,
  closeBackoffWindowMs,
  createMainLineCommandQueue,
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
    release(); await active;
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
