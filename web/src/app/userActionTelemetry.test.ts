import { afterEach, describe, expect, it, vi } from "vitest";

import { postBrowserTelemetry } from "./browserTelemetry";
import { currentClientOperationId } from "./clientOperationContext";
import {
  isDestructiveUserAction,
  postUserActionObservation,
  resetUserActionTelemetryForTests,
  shouldSuppressUserActionTimelineIndex,
  startUserAction,
  USER_ACTION_SLOW_THRESHOLD_MS,
  userActionEventCode,
} from "./userActionTelemetry";

vi.mock("./browserTelemetry", () => ({
  collectBrowserPageSnapshot: () => ({
    pathname: "/chat",
    search: "?session=session-a",
    activeNavHref: "/chat",
    pageInstanceId: "page-test",
  }),
  postBrowserTelemetry: vi.fn(),
}));

describe("user action telemetry", () => {
  afterEach(() => {
    vi.clearAllMocks();
    resetUserActionTelemetryForTests();
  });

  it("names events under browser.user_action.*", () => {
    expect(userActionEventCode("session_create", "started")).toBe("browser.user_action.session_create_started");
    expect(userActionEventCode("session_delete", "failed")).toBe("browser.user_action.session_delete_failed");
  });

  it("marks destructive actions", () => {
    expect(isDestructiveUserAction("session_delete")).toBe(true);
    expect(isDestructiveUserAction("session_create")).toBe(false);
  });

  it("suppresses fast successful timeline indexing while keeping failures visible", () => {
    expect(shouldSuppressUserActionTimelineIndex({
      outcome: "succeeded",
      durationMs: USER_ACTION_SLOW_THRESHOLD_MS - 1,
      destructive: false,
    })).toBe(true);
    expect(shouldSuppressUserActionTimelineIndex({
      outcome: "succeeded",
      durationMs: USER_ACTION_SLOW_THRESHOLD_MS,
      destructive: false,
    })).toBe(false);
    expect(shouldSuppressUserActionTimelineIndex({
      outcome: "failed",
      durationMs: 10,
      destructive: false,
    })).toBe(false);
    expect(shouldSuppressUserActionTimelineIndex({
      outcome: "succeeded",
      durationMs: 10,
      destructive: true,
    })).toBe(false);
  });

  it("emits started and succeeded events with clientOperationId and durationMs", () => {
    vi.stubGlobal("performance", { now: () => 1000 });
    const tracker = startUserAction("session_create", { agentId: "agent-a" });
    tracker.succeeded({ sessionId: "session-b", tempSessionId: "temp-1" });

    expect(postBrowserTelemetry).toHaveBeenCalledTimes(2);
    const started = vi.mocked(postBrowserTelemetry).mock.calls[0]?.[0];
    const succeeded = vi.mocked(postBrowserTelemetry).mock.calls[1]?.[0];
    expect(started).toMatchObject({
      phase: "user_action",
      eventCode: "browser.user_action.session_create_started",
      fields: expect.objectContaining({
        action: "session_create",
        outcome: "started",
        agentId: "agent-a",
        clientOperationId: expect.stringMatching(/^session_create-/),
        pathname: "/chat",
      }),
    });
    expect(succeeded).toMatchObject({
      eventCode: "browser.user_action.session_create_succeeded",
      fields: expect.objectContaining({
        sessionId: "session-b",
        tempSessionId: "temp-1",
        durationMs: 0,
        controlSignal: true,
      }),
    });
  });

  it("records blocked and failed outcomes without controlSignal", () => {
    const tracker = startUserAction("session_delete", { sessionId: "session-a" }, { destructive: true });
    tracker.blocked("session_busy");
    tracker.failed(new Error("network down"), { sessionId: "session-a" });

    const blocked = vi.mocked(postBrowserTelemetry).mock.calls[1]?.[0];
    const failed = vi.mocked(postBrowserTelemetry).mock.calls[2]?.[0];
    expect(blocked?.level).toBe("warning");
    expect(blocked?.fields).toMatchObject({
      guardReason: "session_busy",
      outcome: "blocked",
    });
    expect(blocked?.fields).not.toHaveProperty("controlSignal");
    expect(failed?.level).toBe("error");
    expect(failed?.fields).toMatchObject({
      errorName: "Error",
      errorMessage: "network down",
    });
  });

  it("binds client operation context until the tracker finishes", () => {
    const tracker = startUserAction("session_create", { agentId: "agent-a" });
    expect(tracker.clientOperationId).toMatch(/^session_create-/);
    expect(currentClientOperationId()).toBe(tracker.clientOperationId);
    tracker.succeeded({ sessionId: "session-b" });
    expect(currentClientOperationId()).toBe("");
  });

  it("supports one-shot observations for route switches", () => {
    postUserActionObservation("session_open", {
      sessionId: "session-b",
      previousSessionId: "session-a",
      source: "tab_strip",
    });

    expect(postBrowserTelemetry).toHaveBeenCalledWith(expect.objectContaining({
      eventCode: "browser.user_action.session_open_observed",
      phase: "user_action",
      fields: expect.objectContaining({
        sessionId: "session-b",
        previousSessionId: "session-a",
        source: "tab_strip",
        controlSignal: true,
      }),
    }));
  });
});
