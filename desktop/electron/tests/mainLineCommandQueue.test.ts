import { describe, expect, it, vi } from "vitest";

import {
  createMainLineCommandQueue,
  type MainLineLifecycleResult,
} from "../src/lifecycle/mainLine/commandQueue.js";

function ok(operation: string, commandId: string): MainLineLifecycleResult {
  return { schemaVersion: 1, accepted: true, operation, commandId };
}

describe("mainLineCommandQueue", () => {
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
