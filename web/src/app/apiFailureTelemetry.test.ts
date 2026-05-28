import { describe, expect, it } from "vitest";

import {
  apiFailureTelemetryEventCode,
  apiFailureTelemetryLevel,
  buildRestartRequestUnconfirmedTelemetry,
  buildRestartRequestedTelemetry,
  buildShutdownLocallyCompleteTelemetry,
  buildShutdownRequestUnconfirmedTelemetry,
  buildShutdownRequestedTelemetry,
  restartRequestUnconfirmedBody,
  shouldSuppressApiFailureTelemetry,
  shouldTreatShutdownAsLocallyComplete,
  shouldThrottleApiFailureTelemetry,
  shutdownLocallyCompleteBody,
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

  it("suppresses expected failures while restart is in progress", () => {
    expect(
      shouldSuppressApiFailureTelemetry(
        {
          endpoint: "/api/runtime/summary",
          method: "GET",
          status: null,
          message: "Failed to fetch",
          failureKind: "network",
        },
        {
          shutdownRequested: false,
          restartRequested: true,
          runtimeControllerState: "managed",
          visibilityState: "visible",
        },
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

  it("suppresses pagehide-adjacent background GET cancellations", () => {
    expect(
      shouldSuppressApiFailureTelemetry(
        {
          endpoint: "/api/conversations",
          method: "GET",
          status: null,
          message: "Failed to fetch",
          failureKind: "network",
        },
        {
          shutdownRequested: false,
          runtimeControllerState: "managed",
          visibilityState: "visible",
          pagehideAtMs: 10_000,
          nowMs: 10_500,
        },
      ),
    ).toBe(true);
  });

  it("keeps foreground network failures visible outside pagehide cancellation window", () => {
    expect(
      shouldSuppressApiFailureTelemetry(
        {
          endpoint: "/api/conversations",
          method: "GET",
          status: null,
          message: "Failed to fetch",
          failureKind: "network",
        },
        {
          shutdownRequested: false,
          runtimeControllerState: "managed",
          visibilityState: "visible",
          pagehideAtMs: 10_000,
          nowMs: 14_000,
        },
      ),
    ).toBe(false);
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

  it("names config model discovery failures as domain-specific telemetry", () => {
    expect(
      apiFailureTelemetryEventCode({
        endpoint: "/api/config/discover-models",
        method: "POST",
        status: 422,
        message: "认证失败",
        failureKind: "http",
      }),
    ).toBe("config.model_discovery.failed");
    expect(
      apiFailureTelemetryEventCode({
        endpoint: "/api/config/discover-models?retry=1",
        method: "POST",
        status: null,
        message: "Failed to fetch",
        failureKind: "network",
      }),
    ).toBe("config.model_discovery.network_error");
    expect(
      apiFailureTelemetryEventCode({
        endpoint: "/api/evolution/runs",
        method: "POST",
        status: 409,
        message: "active run",
        failureKind: "http",
      }),
    ).toBe("browser.api.request_failed");
  });

  it("keeps model discovery validation failures below system-error severity", () => {
    expect(
      apiFailureTelemetryLevel({
        endpoint: "/api/config/discover-models",
        method: "POST",
        status: 422,
        message: "未找到环境变量 OPENAI_API_KEY",
        failureKind: "http",
      }),
    ).toBe("warning");
    expect(
      apiFailureTelemetryLevel({
        endpoint: "/api/config/discover-models",
        method: "POST",
        status: null,
        message: "Failed to fetch",
        failureKind: "network",
      }),
    ).toBe("error");
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

  it("builds explicit user-action telemetry for restart requests", () => {
    expect(buildRestartRequestedTelemetry()).toMatchObject({
      phase: "restart",
      eventCode: "browser.user_action.restart_requested",
      level: "info",
      fields: {
        action: "restart",
        source: "app_shell",
      },
    });
    expect(restartRequestUnconfirmedBody("zh")).toContain("重启流程已经开始");
    expect(buildRestartRequestUnconfirmedTelemetry("Failed to fetch")).toMatchObject({
      phase: "restart",
      eventCode: "browser.user_action.restart_request_unconfirmed",
      level: "warning",
      fields: {
        action: "restart",
        source: "app_shell",
        errorMessage: "Failed to fetch",
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

  it("treats shutdown as locally complete when the backend and runtime summary are both unreachable", () => {
    expect(
      shouldTreatShutdownAsLocallyComplete({
        shutdownRequested: true,
        backendState: "healthy",
        backendUnavailable: true,
        runtimeSummaryUnavailable: true,
        workbench: null,
      }),
    ).toBe(true);
    expect(shutdownLocallyCompleteBody("zh")).toContain("残留窗口");
    expect(shutdownLocallyCompleteBody("en")).toContain("remaining window");
    expect(buildShutdownLocallyCompleteTelemetry("backend_unreachable")).toMatchObject({
      phase: "shutdown",
      eventCode: "browser.user_action.shutdown_locally_completed",
      level: "info",
      fields: {
        action: "shutdown",
        source: "app_shell",
        reason: "backend_unreachable",
      },
    });
  });

  it("does not infer shutdown completion from ordinary foreground API loss", () => {
    expect(
      shouldTreatShutdownAsLocallyComplete({
        shutdownRequested: false,
        backendState: "offline",
        runtimeSummaryUnavailable: true,
      }),
    ).toBe(false);
    expect(
      shouldTreatShutdownAsLocallyComplete({
        shutdownRequested: true,
        backendState: "offline",
        runtimeSummaryUnavailable: false,
      }),
    ).toBe(false);
  });

  it("treats a runtime-manager orphaned browser signal as locally complete during shutdown", () => {
    expect(
      shouldTreatShutdownAsLocallyComplete({
        shutdownRequested: true,
        backendState: "healthy",
        runtimeSummaryUnavailable: false,
        workbench: {
          frontendOrphaned: true,
          lifecycleConsistency: "orphaned_browser",
        } as never,
      }),
    ).toBe(true);
  });

  it("treats residual frontend shutdown diagnostics as locally complete during shutdown", () => {
    expect(
      shouldTreatShutdownAsLocallyComplete({
        shutdownRequested: true,
        backendState: "healthy",
        runtimeSummaryUnavailable: false,
        workbench: {
          desiredState: "closed",
          phase: "failed",
          failureMessage:
            "Workbench frontend window is still open, but no backend service is reachable. Close this remaining window manually.",
        } as never,
      }),
    ).toBe(true);
  });

  it("keeps ordinary closed-state runtime-manager failures visible during shutdown", () => {
    expect(
      shouldTreatShutdownAsLocallyComplete({
        shutdownRequested: true,
        backendState: "healthy",
        runtimeSummaryUnavailable: false,
        workbench: {
          desiredState: "closed",
          phase: "failed",
          failureMessage: "Failed to stop backend process.",
        } as never,
      }),
    ).toBe(false);
  });
});
