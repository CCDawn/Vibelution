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

  it("joins an in-flight restart instead of aborting it when joinInFlightRestart is set", () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const restart = supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" });

    const stop = supervisor.beginIntentWithOptions(
      { instanceId: "main", operation: "stop", desiredState: "closed" },
      { joinInFlightRestart: true },
    );

    expect(stop.outcome).toBe("joined-in-flight-restart");
    if (stop.outcome !== "joined-in-flight-restart") {
      throw new Error("expected join outcome");
    }
    expect(stop.lease.revision).toBe(restart.revision);
    expect(restart.signal.aborted).toBe(false);
    expect(supervisor.isCurrent(restart)).toBe(true);
    expect(supervisor.snapshot("main")).toMatchObject({ operation: "restart", phase: "intent" });
  });

  it("joins an in-flight rebuild-and-start instead of aborting it when joinInFlightRestart is set", () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const rebuild = supervisor.beginIntent({
      instanceId: "main",
      operation: "rebuild-and-start",
      desiredState: "open"
    });

    const stop = supervisor.beginIntentWithOptions(
      { instanceId: "main", operation: "stop", desiredState: "closed" },
      { joinInFlightRestart: true },
    );

    // A forwarded stop must not kill a rebuild mid mutation, exactly like a
    // restart: the join returns the actively running rebuild lease.
    expect(stop.outcome).toBe("joined-in-flight-restart");
    if (stop.outcome !== "joined-in-flight-restart") {
      throw new Error("expected join outcome");
    }
    expect(stop.lease.revision).toBe(rebuild.revision);
    expect(rebuild.signal.aborted).toBe(false);
    expect(supervisor.isCurrent(rebuild)).toBe(true);
    expect(supervisor.snapshot("main")).toMatchObject({ operation: "rebuild-and-start", phase: "intent" });
  });

  it("keeps operator stop semantics: a default beginIntent still supersedes an in-flight rebuild-and-start", () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const rebuild = supervisor.beginIntent({
      instanceId: "main",
      operation: "rebuild-and-start",
      desiredState: "open"
    });

    // No join options: an operator-proven stop keeps the unconditional
    // supersede semantics against a rebuild exactly as before.
    const stop = supervisor.beginIntent({ instanceId: "main", operation: "stop", desiredState: "closed" });

    expect(rebuild.signal.aborted).toBe(true);
    expect(stop.revision).toBeGreaterThan(rebuild.revision);
    expect(supervisor.isCurrent(rebuild)).toBe(false);
  });

  it("keeps operator stop semantics: a default beginIntent still supersedes an in-flight restart", () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const restart = supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" });

    const stop = supervisor.beginIntent({ instanceId: "main", operation: "stop", desiredState: "closed" });

    expect(restart.signal.aborted).toBe(true);
    expect(restart.signal.reason).toBeInstanceOf(Error);
    expect((restart.signal.reason as Error).message).toContain("launcher lifecycle intent superseded for main");
    expect(stop.revision).toBeGreaterThan(restart.revision);
    expect(supervisor.isCurrent(restart)).toBe(false);
  });

  it("only joins a restart that is still executing its mutation in intent phase", () => {
    const supervisor = new LauncherLifecycleSupervisor();

    // A bound restart has settled its mutation (bindCommand moves the lease to
    // observing), so a join-eligible stop supersedes it as before.
    const settledRestart = bind(
      supervisor,
      supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" }),
      "cmd-restart-settled",
    );
    const settledJoin = supervisor.beginIntentWithOptions(
      { instanceId: "main", operation: "stop", desiredState: "closed" },
      { joinInFlightRestart: true },
    );
    expect(settledJoin.outcome).toBe("begun");
    expect(settledRestart.signal.aborted).toBe(true);

    // A restart whose READY was fully claimed is likewise joinable no longer.
    const readyRestart = bind(
      supervisor,
      supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" }),
      "cmd-restart-ready",
    );
    expect(supervisor.claimReady(readyRestart)).toBe(true);
    expect(supervisor.completeReady(readyRestart)).toBe(true);
    const readyJoin = supervisor.beginIntentWithOptions(
      { instanceId: "main", operation: "stop", desiredState: "closed" },
      { joinInFlightRestart: true },
    );
    expect(readyJoin.outcome).toBe("begun");
    expect(readyRestart.signal.aborted).toBe(true);

    // A non-restart in-flight lease never joins either.
    const start = supervisor.beginIntent({ instanceId: "main", operation: "start", desiredState: "open" });
    const startJoin = supervisor.beginIntentWithOptions(
      { instanceId: "main", operation: "stop", desiredState: "closed" },
      { joinInFlightRestart: true },
    );
    expect(startJoin.outcome).toBe("begun");
    expect(start.signal.aborted).toBe(true);

    // The intent-phase gate applies to rebuild-and-start too: a rebuild whose
    // mutation settled is superseded by a join-eligible stop, never joined.
    const settledRebuild = bind(
      supervisor,
      supervisor.beginIntent({ instanceId: "main", operation: "rebuild-and-start", desiredState: "open" }),
      "cmd-rebuild-settled",
    );
    const settledRebuildJoin = supervisor.beginIntentWithOptions(
      { instanceId: "main", operation: "stop", desiredState: "closed" },
      { joinInFlightRestart: true },
    );
    expect(settledRebuildJoin.outcome).toBe("begun");
    expect(settledRebuild.signal.aborted).toBe(true);
  });

  it("keeps beginIntentWithOptions without options identical to beginIntent", () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const restart = supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" });

    const stop = supervisor.beginIntentWithOptions(
      { instanceId: "main", operation: "stop", desiredState: "closed" },
    );

    expect(stop.outcome).toBe("begun");
    if (stop.outcome !== "begun") {
      throw new Error("expected begun outcome");
    }
    expect(stop.lease.revision).toBeGreaterThan(restart.revision);
    expect(restart.signal.aborted).toBe(true);
  });

  it("clears only the identical failed lease so dead restarts cannot absorb joins", () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const failed = supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" });

    expect(supervisor.clearSlotIfCurrent(failed)).toBe(true);
    expect(supervisor.snapshot("main")).toBeNull();
    expect(supervisor.clearSlotIfCurrent(failed)).toBe(false);

    // A cleared failed restart no longer absorbs a join-eligible stop.
    const joinAfterClear = supervisor.beginIntentWithOptions(
      { instanceId: "main", operation: "stop", desiredState: "closed" },
      { joinInFlightRestart: true },
    );
    expect(joinAfterClear.outcome).toBe("begun");

    // A newer intent is never cleared through a stale lease reference.
    const stale = supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" });
    const newer = supervisor.beginIntent({ instanceId: "main", operation: "restart", desiredState: "open" });
    expect(supervisor.clearSlotIfCurrent(stale)).toBe(false);
    expect(supervisor.isCurrent(newer)).toBe(true);
    expect(supervisor.snapshot("main")).toMatchObject({ revision: newer.revision });
  });
});
