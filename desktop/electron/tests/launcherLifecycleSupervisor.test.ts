import { describe, expect, it, vi } from "vitest";

import {
  LauncherLifecycleSupervisor,
  type LauncherLifecycleLease,
} from "../src/lifecycle/launcherLifecycleSupervisor.js";
import { PythonJsonBridgeError } from "../src/process/pythonJsonBridge.js";

function bind(
  supervisor: LauncherLifecycleSupervisor,
  lease: LauncherLifecycleLease,
  commandId: string,
  generation?: number,
): LauncherLifecycleLease {
  const bound = supervisor.bindCommand(lease, { commandId, generation });
  if (bound === null) {
    throw new Error("expected lifecycle lease to remain current");
  }
  return bound;
}

describe("LauncherLifecycleSupervisor", () => {
  it("supersedes and aborts a start observer when stop arrives before READY", () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const start = bind(
      supervisor,
      supervisor.beginIntent({ instanceId: "main", operation: "start", desiredState: "open" }),
      "cmd-start",
    );

    const stop = supervisor.beginIntent({ instanceId: "main", operation: "stop", desiredState: "closed" });

    expect(stop.revision).toBeGreaterThan(start.revision);
    expect(start.signal.aborted).toBe(true);
    expect(supervisor.isCurrent(start)).toBe(false);
    expect(supervisor.claimReady(start)).toBe(false);
  });

  it("keeps only the newest consecutive restart lease current", () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const first = bind(
      supervisor,
      supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" }),
      "cmd-r1",
    );
    const second = bind(
      supervisor,
      supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" }),
      "cmd-r2",
    );
    const third = bind(
      supervisor,
      supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" }),
      "cmd-r3",
    );

    expect([first.revision, second.revision, third.revision]).toEqual([1, 2, 3]);
    expect([first.generation, second.generation, third.generation]).toEqual([1, 2, 3]);
    expect(supervisor.isCurrent(first)).toBe(false);
    expect(supervisor.isCurrent(second)).toBe(false);
    expect(supervisor.isCurrent(third)).toBe(true);
  });

  it("validates every lease identity field and drops duplicate READY", () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const lease = bind(
      supervisor,
      supervisor.beginIntent({ instanceId: "worktree:task", operation: "start", desiredState: "open", generation: 7 }),
      "cmd-7",
      7,
    );

    expect(supervisor.isCurrent({ ...lease, commandId: "old-command" })).toBe(false);
    expect(supervisor.isCurrent({ ...lease, generation: 6 })).toBe(false);
    expect(supervisor.isCurrent({ ...lease, desiredState: "closed" })).toBe(false);
    expect(supervisor.isCurrent({ ...lease, instanceId: "worktree:other" })).toBe(false);
    expect(supervisor.claimReady(lease)).toBe(true);
    expect(supervisor.snapshot("worktree:task")).toMatchObject({ phase: "observing", readyClaimed: true });
    expect(supervisor.claimReady(lease)).toBe(false);
    expect(supervisor.completeReady(lease)).toBe(true);
    expect(supervisor.snapshot("worktree:task")).toMatchObject({ phase: "ready", readyClaimed: true });
    expect(supervisor.completeReady(lease)).toBe(false);
  });

  it("releases a failed READY claim so the current observer can retry", () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const lease = bind(
      supervisor,
      supervisor.beginIntent({ instanceId: "worktree:task", operation: "start", desiredState: "open" }),
      "cmd-retry",
    );

    expect(supervisor.claimReady(lease)).toBe(true);
    expect(supervisor.releaseReadyClaim(lease)).toBe(true);
    expect(supervisor.snapshot("worktree:task")).toMatchObject({ phase: "observing", readyClaimed: false });
    expect(supervisor.claimReady(lease)).toBe(true);
  });

  it("serializes mutations per instance and skips a queued superseded intent", async () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const releaseFirst = vi.fn<() => void>();
    let resolveFirst!: () => void;
    let markFirstStarted!: () => void;
    const firstGate = new Promise<void>((resolve) => {
      resolveFirst = () => {
        releaseFirst();
        resolve();
      };
    });
    const firstStarted = new Promise<void>((resolve) => {
      markFirstStarted = resolve;
    });
    const first = supervisor.beginIntent({ instanceId: "main", operation: "start", desiredState: "open" });
    const firstMutation = supervisor.executeMutation({
      lease: first,
      mutate: async () => {
        markFirstStarted();
        await firstGate;
        return "first";
      },
      reconcile: vi.fn(),
    });
    await firstStarted;
    const second = supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" });
    const secondMutate = vi.fn(async () => "second");
    const secondMutation = supervisor.executeMutation({ lease: second, mutate: secondMutate, reconcile: vi.fn() });

    resolveFirst();
    await expect(firstMutation).resolves.toMatchObject({ outcome: "superseded", value: "first" });
    await expect(secondMutation).resolves.toMatchObject({ outcome: "committed", value: "second" });
    expect(secondMutate).toHaveBeenCalledOnce();
    expect(releaseFirst).toHaveBeenCalledOnce();
  });

  it("marks timed-out mutation uncertain, reconciles once, and never retries", async () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const lease = supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" });
    const mutate = vi.fn(async () => {
      throw new PythonJsonBridgeError(
        "uncertain_mutation",
        "lifecycle bridge timed out; outcome is uncertain",
        { causeCode: "timeout" },
      );
    });
    const reconcile = vi.fn(async () => undefined);

    await expect(supervisor.executeMutation({ lease, mutate, reconcile })).resolves.toEqual({ outcome: "uncertain" });
    expect(mutate).toHaveBeenCalledOnce();
    expect(reconcile).toHaveBeenCalledOnce();
    expect(supervisor.snapshot("main")?.phase).toBe("uncertain");
  });

  it("classifies an aborted superseded mutation as ignored instead of a command failure", async () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const lease = supervisor.beginIntent({ instanceId: "main", operation: "start", desiredState: "open" });
    const mutate = vi.fn(async () => {
      supervisor.beginIntent({ instanceId: "main", operation: "stop", desiredState: "closed" });
      throw new PythonJsonBridgeError("aborted", "lifecycle bridge aborted");
    });
    const reconcile = vi.fn(async () => undefined);

    await expect(supervisor.executeMutation({ lease, mutate, reconcile })).resolves.toEqual({ outcome: "ignored" });
    expect(reconcile).not.toHaveBeenCalled();
  });
});
