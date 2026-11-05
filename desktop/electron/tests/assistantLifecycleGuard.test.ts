import { describe, expect, it, vi } from "vitest";
import { acquireAssistantLifecycleLease, combineAssistantActiveWork } from "../src/assistant/lifecycleGuard.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

function fixture() {
  const admission = { drained: Promise.resolve(), seal: vi.fn().mockResolvedValue(undefined), release: vi.fn(), check: vi.fn(), commit: vi.fn() };
  const registry = { drained: Promise.resolve(), release: vi.fn() };
  const input = {
    host: {
      snapshot: () => ({ state: "ready" as const, errorCode: null }),
      beginLifecycleAdmission: vi.fn(() => admission),
      migrationBarrier: vi.fn(async (operation: "prepare" | "status" | "release") =>
        operation === "prepare" ? "probing" as const : operation === "status" ? "ready" as const : "idle" as const),
    },
    projects: { beginMigrationTransition: vi.fn(() => registry) },
    reminders: { tryDrainForLifecycle: vi.fn<() => Promise<void> | null>(() => Promise.resolve()), resumeAfterMigration: vi.fn() },
    drainQueues: vi.fn().mockResolvedValue(undefined), current: () => true, reopen: () => true, releaseOwner: vi.fn(),
  };
  return { input, admission, registry };
}

describe("resident assistant lifecycle admission", () => {
  it.each(["active", "unknown"] as const)("does not erase native %s when the backend is idle", state => {
    expect(combineAssistantActiveWork({ state: "idle", message: "" }, { state, message: "native" }).state).toBe(state);
    // The fallback file scan cannot override native unknown either.
    expect(combineAssistantActiveWork({ state: "idle", message: "fallback" }, { state, message: "native" }).state).toBe(state);
  });

  it("never lets an unobservable observation poison the other source's conclusion", () => {
    // An idle reading beside a lost observation degrades to unobservable, so
    // the coordinator can still consult the local file scan.
    expect(combineAssistantActiveWork({ state: "idle", message: "" }, { state: "unobservable", message: "lost observation" }).state).toBe("unobservable");
    expect(combineAssistantActiveWork({ state: "unobservable", message: "lost observation" }, { state: "idle", message: "" }).state).toBe("unobservable");
    // An active reading still blocks; a lost observation cannot erase it.
    expect(combineAssistantActiveWork({ state: "active", message: "native" }, { state: "unobservable", message: "lost" }).state).toBe("active");
    expect(combineAssistantActiveWork({ state: "unobservable", message: "lost" }, { state: "active", message: "native" }).state).toBe("active");
    // Producer ambiguity outranks an unobservable reading: the fail-closed
    // unknown survives and no local idle scan may pass it.
    expect(combineAssistantActiveWork({ state: "unobservable", message: "lost" }, { state: "unknown", message: "producer" }).state).toBe("unknown");
    expect(combineAssistantActiveWork({ state: "unknown", message: "producer" }, { state: "unobservable", message: "lost" }).state).toBe("unknown");
  });

  it("holds every producer and native fence after idle proof until explicitly released", async () => {
    const { input, admission, registry } = fixture();
    const lease = await acquireAssistantLifecycleLease(input);
    expect(input.reminders.tryDrainForLifecycle).toHaveBeenCalledOnce();
    expect(admission.seal).toHaveBeenCalledOnce();
    expect(input.host.migrationBarrier.mock.calls).toEqual([["prepare"], ["status"]]);
    expect(registry.release).not.toHaveBeenCalled();
    expect(admission.release).not.toHaveBeenCalled();
    expect(input.reminders.resumeAfterMigration).not.toHaveBeenCalled();
    await lease.release();
    await lease.release();
    expect(input.host.migrationBarrier.mock.calls).toEqual([["prepare"], ["status"], ["release"]]);
    expect(registry.release).toHaveBeenCalledOnce();
    expect(admission.release).toHaveBeenCalledOnce();
    expect(input.reminders.resumeAfterMigration).toHaveBeenCalledOnce();
    expect(input.releaseOwner).toHaveBeenCalledOnce();
  });

  it("does not begin native shutdown admission while a reminder sender or dialog is busy", async () => {
    const { input } = fixture();
    input.reminders.tryDrainForLifecycle.mockReturnValue(null);
    await expect(acquireAssistantLifecycleLease(input)).rejects.toThrow("ASSISTANT_LIFECYCLE_BUSY");
    expect(input.host.beginLifecycleAdmission).not.toHaveBeenCalled();
    expect(input.host.migrationBarrier).not.toHaveBeenCalled();
    expect(input.releaseOwner).toHaveBeenCalledOnce();
  });

  it("defers if a native turn arrives between the idle poll and held proof", async () => {
    const { input, admission, registry } = fixture();
    input.host.migrationBarrier.mockImplementation(async operation =>
      operation === "prepare" ? "probing" : operation === "status" ? "busy" : "idle");
    await expect(acquireAssistantLifecycleLease(input)).rejects.toThrow("ASSISTANT_LIFECYCLE_BUSY");
    await vi.waitFor(() => expect(input.releaseOwner).toHaveBeenCalledOnce());
    expect(input.host.migrationBarrier.mock.calls).toEqual([["prepare"], ["status"], ["release"]]);
    expect(registry.release).toHaveBeenCalledOnce();
    expect(admission.release).toHaveBeenCalledOnce();
  });

  it("retains gates on an ambiguous release until the same native barrier confirms idle", async () => {
    vi.useFakeTimers();
    try {
      const { input, admission } = fixture();
      const lease = await acquireAssistantLifecycleLease(input);
      let attempts = 0;
      input.host.migrationBarrier.mockImplementation(async () => { if (++attempts === 1) throw new Error("lost ACK"); return "idle"; });
      const released = lease.release();
      await Promise.resolve();
      expect(admission.release).not.toHaveBeenCalled();
      expect(input.reminders.resumeAfterMigration).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(100);
      await released;
      expect(admission.release).toHaveBeenCalledOnce();
      expect(attempts).toBe(2);
    } finally { vi.useRealTimers(); }
  });

  it("does not start acquisition for an already cancelled signal", async () => {
    const { input } = fixture();
    const controller = new AbortController();
    controller.abort();
    await expect(acquireAssistantLifecycleLease({ ...input, signal: controller.signal }))
      .rejects.toMatchObject({ name: "AbortError" });
    expect(input.reminders.tryDrainForLifecycle).not.toHaveBeenCalled();
    expect(input.host.migrationBarrier).not.toHaveBeenCalled();
    expect(input.releaseOwner).toHaveBeenCalledOnce();
  });

  it("releases the drained producers without preparing a barrier when cancelled before prepare", async () => {
    const { input, admission, registry } = fixture();
    const controller = new AbortController();
    const queues = deferred<void>();
    input.drainQueues.mockReturnValue(queues.promise);
    const pending = acquireAssistantLifecycleLease({ ...input, signal: controller.signal });
    const outcome = pending.catch(error => error);
    await vi.waitFor(() => expect(input.drainQueues).toHaveBeenCalledOnce());
    controller.abort();
    queues.resolve();
    expect(await outcome).toMatchObject({ name: "AbortError" });
    expect(input.host.migrationBarrier).not.toHaveBeenCalled();
    expect(admission.release).toHaveBeenCalledOnce();
    expect(registry.release).toHaveBeenCalledOnce();
    expect(input.releaseOwner).toHaveBeenCalledOnce();
  });

  it("settles a delayed prepare before release and rejects cancellation only after native idle", async () => {
    vi.useFakeTimers();
    try {
      const { input, admission, registry } = fixture();
      const controller = new AbortController();
      const prepared = deferred<"probing">();
      const released = deferred<"idle">();
      input.host.migrationBarrier.mockImplementation(operation =>
        operation === "prepare" ? prepared.promise : operation === "release" ? released.promise : Promise.resolve("ready"));
      let settled = false;
      const outcome = acquireAssistantLifecycleLease({ ...input, signal: controller.signal })
        .then(value => { settled = true; return value; }, error => { settled = true; return error; });
      await vi.advanceTimersByTimeAsync(0);
      expect(input.host.migrationBarrier.mock.calls).toEqual([["prepare"]]);
      controller.abort();
      await vi.advanceTimersByTimeAsync(0);
      expect(input.host.migrationBarrier.mock.calls).toEqual([["prepare"]]);
      expect(settled).toBe(false);
      prepared.resolve("probing");
      await vi.advanceTimersByTimeAsync(0);
      expect(input.host.migrationBarrier.mock.calls).toEqual([["prepare"], ["release"]]);
      expect(settled).toBe(false);
      expect(admission.release).not.toHaveBeenCalled();
      expect(registry.release).not.toHaveBeenCalled();
      expect(input.releaseOwner).not.toHaveBeenCalled();
      released.resolve("idle");
      expect(await outcome).toMatchObject({ name: "AbortError" });
      expect(admission.release).toHaveBeenCalledOnce();
      expect(registry.release).toHaveBeenCalledOnce();
      expect(input.reminders.resumeAfterMigration).toHaveBeenCalledOnce();
      expect(input.releaseOwner).toHaveBeenCalledOnce();
    } finally { vi.useRealTimers(); }
  });

  it("keeps cancellation pending and all gates held across a lost release acknowledgement", async () => {
    vi.useFakeTimers();
    try {
      const { input, admission, registry } = fixture();
      const controller = new AbortController();
      const idle = deferred<"idle">();
      let releaseAttempts = 0;
      input.host.migrationBarrier.mockImplementation(async operation => {
        if (operation === "prepare") { controller.abort(); return "probing"; }
        if (operation === "status") return "ready";
        if (++releaseAttempts === 1) throw new Error("lost ACK");
        return idle.promise;
      });
      let settled = false;
      const outcome = acquireAssistantLifecycleLease({ ...input, signal: controller.signal })
        .then(value => { settled = true; return value; }, error => { settled = true; return error; });
      await vi.advanceTimersByTimeAsync(0);
      expect(releaseAttempts).toBe(1);
      expect(settled).toBe(false);
      expect(admission.release).not.toHaveBeenCalled();
      expect(registry.release).not.toHaveBeenCalled();
      expect(input.releaseOwner).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(100);
      expect(releaseAttempts).toBe(2);
      expect(settled).toBe(false);
      expect(input.reminders.resumeAfterMigration).not.toHaveBeenCalled();
      idle.resolve("idle");
      expect(await outcome).toMatchObject({ name: "AbortError" });
      expect(admission.release).toHaveBeenCalledOnce();
      expect(registry.release).toHaveBeenCalledOnce();
      expect(input.releaseOwner).toHaveBeenCalledOnce();
    } finally { vi.useRealTimers(); }
  });

  it("refuses commit after cancellation while leaving explicit release with the lease owner", async () => {
    const { input, admission } = fixture();
    const controller = new AbortController();
    const lease = await acquireAssistantLifecycleLease({ ...input, signal: controller.signal });
    const reason = new Error("acquisition cancelled");
    controller.abort(reason);
    expect(() => lease.commit()).toThrow(reason);
    expect(admission.commit).not.toHaveBeenCalled();
    await lease.release();
    expect(admission.release).toHaveBeenCalledOnce();
  });

  it("never commits a lease whose release has already started", async () => {
    const { input, admission } = fixture();
    const idle = deferred<"idle">();
    const lease = await acquireAssistantLifecycleLease(input);
    input.host.migrationBarrier.mockImplementation(() => idle.promise);
    const released = lease.release();
    expect(() => lease.commit()).toThrow("ASSISTANT_LIFECYCLE_BUSY");
    expect(admission.commit).not.toHaveBeenCalled();
    idle.resolve("idle");
    await released;
  });

  it("retains committed native and producer fences when the acquisition signal is later cancelled", async () => {
    const { input, admission, registry } = fixture();
    const controller = new AbortController();
    const lease = await acquireAssistantLifecycleLease({ ...input, signal: controller.signal });
    lease.commit();
    controller.abort();
    await Promise.resolve();
    expect(admission.commit).toHaveBeenCalledOnce();
    expect(input.host.migrationBarrier.mock.calls).toEqual([["prepare"], ["status"]]);
    expect(admission.release).not.toHaveBeenCalled();
    expect(registry.release).not.toHaveBeenCalled();
    expect(input.releaseOwner).not.toHaveBeenCalled();
    expect(input.reminders.resumeAfterMigration).not.toHaveBeenCalled();
  });
});
