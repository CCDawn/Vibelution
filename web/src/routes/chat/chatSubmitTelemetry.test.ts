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
});
