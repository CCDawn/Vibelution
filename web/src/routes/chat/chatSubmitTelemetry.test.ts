import { describe, expect, it } from "vitest";

import { submitTelemetryFields } from "./chatSubmitTelemetry";

describe("submitTelemetryFields", () => {
  it("keeps the runtime status choice as a boolean telemetry field", () => {
    expect(
      submitTelemetryFields("session-1", {
        runtimeStatusEnabled: false,
      }),
    ).toMatchObject({
      sessionId: "session-1",
      runtimeStatusEnabled: false,
    });
  });

  it("projects optimistic paint latency and its active status source", () => {
    expect(
      submitTelemetryFields("session-1", {
        submitToOptimisticPaintMs: 16,
        activeStatusSource: "optimistic_submit",
      }),
    ).toMatchObject({
      sessionId: "session-1",
      submitToOptimisticPaintMs: 16,
      activeStatusSource: "optimistic_submit",
    });
  });
});
