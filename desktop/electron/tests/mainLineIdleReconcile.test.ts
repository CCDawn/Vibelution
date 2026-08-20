import { describe, expect, it } from "vitest";

import { reconcileMainLineIdle } from "../src/lifecycle/mainLine/idleReconcile.js";
import type { MainLineIntentSnapshot } from "../src/lifecycle/mainLine/commandQueue.js";
import type { MainLineObservation } from "../src/lifecycle/mainLine/observation.js";

function intent(desiredState: "open" | "closed"): MainLineIntentSnapshot {
  return {
    schemaVersion: 1,
    desiredState,
    operation: desiredState === "open" ? "start" : "stop",
    commandId: "cmd_recovery",
    updatedAt: "2026-08-20T10:00:00Z",
  };
}

function observation(
  lifecycleState: MainLineObservation["lifecycleState"],
  extras: Partial<MainLineObservation> = {},
): MainLineObservation {
  return {
    lifecycleState,
    errorCode: "",
    backendAlive: false,
    backendListening: false,
    backendHealthy: false,
    livePids: [],
    ...extras,
  };
}

describe("reconcileMainLineIdle", () => {
  it("enqueues open after a crash left desired open and observed closed", () => {
    expect(
      reconcileMainLineIdle({
        intent: intent("open"),
        observation: observation("closed"),
      }),
    ).toBe("open");
  });

  it("enqueues close when desired is closed but a live backend remains", () => {
    expect(
      reconcileMainLineIdle({
        intent: intent("closed"),
        observation: observation("partial", { backendAlive: true, backendListening: true }),
      }),
    ).toBe("close");
  });

  it("does nothing while a command is in flight or the queue is busy", () => {
    expect(
      reconcileMainLineIdle({
        intent: intent("open"),
        observation: observation("starting"),
      }),
    ).toBeNull();
    expect(
      reconcileMainLineIdle({
        intent: intent("open"),
        observation: observation("closed"),
        queueBusy: true,
      }),
    ).toBeNull();
  });

  it("does nothing when desired and observed already match", () => {
    expect(
      reconcileMainLineIdle({
        intent: intent("open"),
        observation: observation("running", { backendAlive: true, backendListening: true }),
        windowOpen: true,
      }),
    ).toBeNull();
    expect(
      reconcileMainLineIdle({
        intent: null,
        observation: observation("closed"),
      }),
    ).toBeNull();
  });
});
