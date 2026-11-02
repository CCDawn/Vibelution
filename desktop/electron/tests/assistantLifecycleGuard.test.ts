import { describe, expect, it, vi } from "vitest";
import { acquireAssistantLifecycleLease, combineAssistantActiveWork } from "../src/assistant/lifecycleGuard.js";

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
});
