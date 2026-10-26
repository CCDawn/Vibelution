import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getMainLineCommandQueueForProject,
  getSharedMainLineCommandQueue,
  resetSharedMainLineCommandQueueForTests,
  type MainLineCommandQueue,
  type MainLineLifecycleResult,
} from "../src/lifecycle/mainLine/commandQueue.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function makeWorkspace(parent: string, name: string): string {
  const path = join(parent, name);
  mkdirSync(path, { recursive: true });
  return path;
}

function activeCommand(queue: MainLineCommandQueue) {
  const command = queue.snapshot().active;
  expect(command).not.toBeNull();
  return command!;
}

let temporaryRoot = "";

afterEach(() => {
  resetSharedMainLineCommandQueueForTests();
  if (temporaryRoot) {
    rmSync(temporaryRoot, { recursive: true, force: true });
    temporaryRoot = "";
  }
});

describe("per-project main-line command queue ownership", () => {
  it("shares one queue per root so restart and start join one execution", async () => {
    temporaryRoot = mkdtempSync(join(tmpdir(), "main-line-queue-"));
    const workspaceRoot = makeWorkspace(temporaryRoot, "workspace-one");
    const runtimeManagerDir = makeWorkspace(temporaryRoot, "runtime-data-one");
    const originalOwnerMarker = vi.fn();
    const laterOwnerMarker = vi.fn();
    const queue = getMainLineCommandQueueForProject(workspaceRoot, runtimeManagerDir, {
      writeOwnerMarker: originalOwnerMarker,
    });
    const sameQueue = getMainLineCommandQueueForProject(workspaceRoot, runtimeManagerDir, {
      writeOwnerMarker: laterOwnerMarker,
    });
    const execution = deferred<MainLineLifecycleResult>();
    const executeRestart = vi.fn(() => execution.promise);
    const executeStart = vi.fn(async (): Promise<MainLineLifecycleResult> => ({
      schemaVersion: 1,
      accepted: true,
      operation: "start",
    }));

    expect(sameQueue).toBe(queue);
    const restartResult = queue.submit({ operation: "restart", execute: executeRestart });
    const startResult = sameQueue.submit({ operation: "start", execute: executeStart });
    const commandId = activeCommand(queue).commandId;
    execution.resolve({ schemaVersion: 1, accepted: true, operation: "restart", commandId });

    const [restart, start] = await Promise.all([restartResult, startResult]);
    expect(executeRestart).toHaveBeenCalledTimes(1);
    expect(executeStart).not.toHaveBeenCalled();
    expect(start.joined).toBe(true);
    expect(start.commandId).toBe(commandId);
    expect(restart.commandId).toBe(commandId);
    expect(originalOwnerMarker).toHaveBeenCalled();
    expect(laterOwnerMarker).not.toHaveBeenCalled();
  });

  it("keeps queues independent for different workspace roots", async () => {
    temporaryRoot = mkdtempSync(join(tmpdir(), "main-line-queue-"));
    const firstRoot = makeWorkspace(temporaryRoot, "workspace-one");
    const secondRoot = makeWorkspace(temporaryRoot, "workspace-two");
    const firstRuntimeDir = makeWorkspace(temporaryRoot, "runtime-data-one");
    const secondRuntimeDir = makeWorkspace(temporaryRoot, "runtime-data-two");
    const firstQueue = getMainLineCommandQueueForProject(firstRoot, firstRuntimeDir);
    const secondQueue = getMainLineCommandQueueForProject(secondRoot, secondRuntimeDir);
    const firstExecution = deferred<MainLineLifecycleResult>();
    const secondExecution = deferred<MainLineLifecycleResult>();
    const executeFirst = vi.fn(() => firstExecution.promise);
    const executeSecond = vi.fn(() => secondExecution.promise);

    const firstResult = firstQueue.submit({ operation: "start", execute: executeFirst });
    const secondResult = secondQueue.submit({ operation: "start", execute: executeSecond });
    const firstCommandId = activeCommand(firstQueue).commandId;
    const secondCommandId = activeCommand(secondQueue).commandId;

    expect(secondQueue).not.toBe(firstQueue);
    expect(executeFirst).toHaveBeenCalledTimes(1);
    expect(executeSecond).toHaveBeenCalledTimes(1);
    firstExecution.resolve({ schemaVersion: 1, accepted: true, operation: "start", commandId: firstCommandId });
    secondExecution.resolve({ schemaVersion: 1, accepted: true, operation: "start", commandId: secondCommandId });
    const [first, second] = await Promise.all([firstResult, secondResult]);
    expect(first.commandId).not.toBe(second.commandId);
    expect(first.joined).toBeUndefined();
    expect(second.joined).toBeUndefined();
  });

  it("normalizes relative aliases and Windows case aliases", () => {
    temporaryRoot = mkdtempSync(join(tmpdir(), "main-line-queue-"));
    const workspaceRoot = makeWorkspace(temporaryRoot, "workspace-one");
    const runtimeManagerDir = makeWorkspace(temporaryRoot, "runtime-data-one");
    const queue = getMainLineCommandQueueForProject(workspaceRoot, runtimeManagerDir);
    const relativeRoot = relative(process.cwd(), workspaceRoot);
    const relativeRuntimeDir = relative(process.cwd(), runtimeManagerDir);

    if (!isAbsolute(relativeRoot) && !isAbsolute(relativeRuntimeDir)) {
      expect(getMainLineCommandQueueForProject(relativeRoot, relativeRuntimeDir)).toBe(queue);
    }
    if (process.platform === "win32") {
      expect(getMainLineCommandQueueForProject(workspaceRoot.toUpperCase(), runtimeManagerDir.toUpperCase())).toBe(queue);
    }
  });

  it("rejects a changed runtime-manager owner without cancelling active work", async () => {
    temporaryRoot = mkdtempSync(join(tmpdir(), "main-line-queue-"));
    const workspaceRoot = makeWorkspace(temporaryRoot, "workspace-one");
    const originalRuntimeDir = makeWorkspace(temporaryRoot, "runtime-data-one");
    const changedRuntimeDir = makeWorkspace(temporaryRoot, "runtime-data-two");
    const queue = getMainLineCommandQueueForProject(workspaceRoot, originalRuntimeDir);
    const execution = deferred<MainLineLifecycleResult>();
    const execute = vi.fn(() => execution.promise);
    const result = queue.submit({ operation: "restart", execute });
    const commandId = activeCommand(queue).commandId;

    expect(() => getMainLineCommandQueueForProject(workspaceRoot, changedRuntimeDir))
      .toThrowError("MAIN_LINE_QUEUE_OWNER_CHANGED");
    expect(queue.snapshot().active?.commandId).toBe(commandId);
    expect(execute).toHaveBeenCalledTimes(1);
    execution.resolve({ schemaVersion: 1, accepted: true, operation: "restart", commandId });
    await expect(result).resolves.toMatchObject({ accepted: true, commandId });
    expect(queue.snapshot().active).toBeNull();
  });

  it("caps the registry at 128 roots without cancelling existing work", async () => {
    temporaryRoot = mkdtempSync(join(tmpdir(), "main-line-queue-"));
    const runtimeManagerDir = makeWorkspace(temporaryRoot, "runtime-data-one");
    const queueLimit = 128;
    const firstQueue = getMainLineCommandQueueForProject(join(temporaryRoot, "workspace-000"), runtimeManagerDir);
    const execution = deferred<MainLineLifecycleResult>();
    const execute = vi.fn(() => execution.promise);
    const result = firstQueue.submit({ operation: "start", execute });
    const commandId = activeCommand(firstQueue).commandId;

    for (let index = 1; index < queueLimit; index += 1) {
      getMainLineCommandQueueForProject(join(temporaryRoot, `workspace-${String(index).padStart(3, "0")}`), runtimeManagerDir);
    }

    expect(() => getMainLineCommandQueueForProject(join(temporaryRoot, "workspace-over-limit"), runtimeManagerDir))
      .toThrowError("MAIN_LINE_QUEUE_LIMIT");
    expect(firstQueue.snapshot().active?.commandId).toBe(commandId);
    expect(execute).toHaveBeenCalledTimes(1);
    execution.resolve({ schemaVersion: 1, accepted: true, operation: "start", commandId });
    await expect(result).resolves.toMatchObject({ accepted: true, commandId });
  });

  it("resets both shared and per-project queue registries for tests", () => {
    temporaryRoot = mkdtempSync(join(tmpdir(), "main-line-queue-"));
    const workspaceRoot = makeWorkspace(temporaryRoot, "workspace-one");
    const runtimeManagerDir = makeWorkspace(temporaryRoot, "runtime-data-one");
    const firstProjectQueue = getMainLineCommandQueueForProject(workspaceRoot, runtimeManagerDir);
    const firstSharedQueue = getSharedMainLineCommandQueue();

    resetSharedMainLineCommandQueueForTests();

    expect(getMainLineCommandQueueForProject(workspaceRoot, runtimeManagerDir)).not.toBe(firstProjectQueue);
    expect(getSharedMainLineCommandQueue()).not.toBe(firstSharedQueue);
  });
});
