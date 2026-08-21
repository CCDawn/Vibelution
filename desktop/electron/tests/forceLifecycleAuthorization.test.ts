import { describe, expect, it, vi } from "vitest";

import {
  authorizeForceLifecycleOperation,
  ForceLifecycleAuthorizationDeniedError
} from "../src/lifecycle/forceLifecycleAuthorization.js";

describe("authorizeForceLifecycleOperation", () => {
  it("does not probe or confirm ordinary lifecycle operations", async () => {
    const probe = vi.fn();
    const confirm = vi.fn();
    const record = vi.fn();

    await expect(authorizeForceLifecycleOperation({
      operation: "stop",
      instanceId: "main",
      operatorIntent: "stop",
      probe,
      confirm,
      record,
      requestIdFactory: () => "request-1"
    })).resolves.toBeNull();
    expect(probe).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
    expect(record).not.toHaveBeenCalled();
  });

  it("requires confirmation and records request identity plus probe result", async () => {
    const record = vi.fn(async () => undefined);
    await expect(authorizeForceLifecycleOperation({
      operation: "force-stop",
      instanceId: "worktree:task",
      operatorIntent: "force_stop_instance",
      probe: async () => ({ state: "active", message: "one task running" }),
      confirm: async (request) => request.requestId === "request-2",
      record,
      requestIdFactory: () => "request-2"
    })).resolves.toMatchObject({
      requestId: "request-2",
      instanceId: "worktree:task",
      probeState: "active",
      operatorIntent: "force_stop_instance"
    });
    expect(record).toHaveBeenCalledWith(expect.objectContaining({ requestId: "request-2", probeState: "active" }));
  });

  it("fails closed when the operator does not confirm", async () => {
    const record = vi.fn();
    await expect(authorizeForceLifecycleOperation({
      operation: "force-stop",
      instanceId: "main",
      operatorIntent: "force_stop",
      probe: async () => ({ state: "idle", message: "" }),
      confirm: async () => false,
      record,
      requestIdFactory: () => "request-3"
    })).rejects.toBeInstanceOf(ForceLifecycleAuthorizationDeniedError);
    expect(record).not.toHaveBeenCalled();
  });

  it("classifies probe failures as unknown before confirmation", async () => {
    const confirm = vi.fn(async () => false);
    await expect(authorizeForceLifecycleOperation({
      operation: "force-stop",
      instanceId: "main",
      operatorIntent: "force_stop",
      probe: async () => {
        throw new Error("status timed out");
      },
      confirm,
      record: async () => undefined,
      requestIdFactory: () => "request-4"
    })).rejects.toThrow("not confirmed");
    expect(confirm).toHaveBeenCalledWith(expect.objectContaining({
      probeState: "unknown",
      probeMessage: "status timed out"
    }));
  });

  it("accepts an already-confirmed transaction without a second prompt", async () => {
    const probe = vi.fn();
    const confirm = vi.fn();
    const record = vi.fn(async () => undefined);
    await expect(authorizeForceLifecycleOperation({
      operation: "force-stop",
      instanceId: "main",
      operatorIntent: "force_close",
      preconfirmed: {
        requestId: "close-request",
        probeState: "unknown",
        probeMessage: "projection unavailable"
      },
      probe,
      confirm,
      record,
      requestIdFactory: () => "unused"
    })).resolves.toMatchObject({ requestId: "close-request", probeState: "unknown" });
    expect(probe).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
    expect(record).toHaveBeenCalledOnce();
  });
});
