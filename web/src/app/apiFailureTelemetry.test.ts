import { describe, expect, it } from "vitest";

import { shouldSuppressApiFailureTelemetry } from "./AppShell";

describe("api failure telemetry", () => {
  it("suppresses expected failures while shutdown is in progress", () => {
    expect(
      shouldSuppressApiFailureTelemetry(
        {
          endpoint: "/api/runtime/summary",
          method: "GET",
          status: null,
          message: "Failed to fetch",
          failureKind: "network",
        },
        { shutdownRequested: true, runtimeControllerState: "managed" },
      ),
    ).toBe(true);
  });

  it("suppresses control-token telemetry auth noise", () => {
    expect(
      shouldSuppressApiFailureTelemetry(
        {
          endpoint: "/api/runtime/browser-telemetry",
          method: "POST",
          status: 403,
          message: "Missing or invalid web control token",
          failureKind: "http",
        },
        { shutdownRequested: false, runtimeControllerState: "managed" },
      ),
    ).toBe(true);
  });

  it("keeps normal API failures visible", () => {
    expect(
      shouldSuppressApiFailureTelemetry(
        {
          endpoint: "/api/evolution/runs",
          method: "POST",
          status: 409,
          message: "active run",
          failureKind: "http",
        },
        { shutdownRequested: false, runtimeControllerState: "managed" },
      ),
    ).toBe(false);
  });
});
