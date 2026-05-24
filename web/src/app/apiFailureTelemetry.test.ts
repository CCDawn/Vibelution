import { describe, expect, it } from "vitest";

import {
  buildShutdownRequestUnconfirmedTelemetry,
  buildShutdownRequestedTelemetry,
  shouldSuppressApiFailureTelemetry,
  shouldThrottleApiFailureTelemetry,
  shutdownRequestUnconfirmedBody,
} from "./AppShell";

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
        { shutdownRequested: true, runtimeControllerState: "managed", visibilityState: "visible" },
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
        { shutdownRequested: false, runtimeControllerState: "managed", visibilityState: "visible" },
      ),
    ).toBe(true);
  });

  it("suppresses background GET network noise", () => {
    expect(
      shouldSuppressApiFailureTelemetry(
        {
          endpoint: "/api/sessions",
          method: "GET",
          status: null,
          message: "Failed to fetch",
          failureKind: "network",
        },
        { shutdownRequested: false, runtimeControllerState: "managed", visibilityState: "hidden" },
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
        { shutdownRequested: false, runtimeControllerState: "managed", visibilityState: "visible" },
      ),
    ).toBe(false);
  });

  it("throttles repeated failures for the same endpoint window", () => {
    const state = new Map<string, number>();
    const failure = {
      endpoint: "/api/runtime/summary",
      method: "GET",
      status: null,
      message: "Failed to fetch",
      failureKind: "network" as const,
    };

    expect(shouldThrottleApiFailureTelemetry(failure, state, 1_000)).toBe(false);
    expect(shouldThrottleApiFailureTelemetry(failure, state, 2_000)).toBe(true);
    expect(shouldThrottleApiFailureTelemetry(failure, state, 17_000)).toBe(false);
  });

  it("builds an explicit user-action telemetry event for shutdown requests", () => {
    expect(buildShutdownRequestedTelemetry()).toMatchObject({
      phase: "shutdown",
      eventCode: "browser.user_action.shutdown_requested",
      level: "info",
      fields: {
        action: "shutdown",
        source: "app_shell",
      },
    });
  });

  it("keeps shutdown request errors as pending confirmation instead of manager failure", () => {
    expect(shutdownRequestUnconfirmedBody("zh")).toContain("还没有收到最终确认");
    expect(shutdownRequestUnconfirmedBody("en")).toContain("did not receive a final confirmation");
    expect(buildShutdownRequestUnconfirmedTelemetry("Failed to fetch")).toMatchObject({
      phase: "shutdown",
      eventCode: "browser.user_action.shutdown_request_unconfirmed",
      level: "warning",
      fields: {
        action: "shutdown",
        source: "app_shell",
        errorMessage: "Failed to fetch",
      },
    });
  });
});
