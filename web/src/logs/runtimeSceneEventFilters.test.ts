import { describe, expect, it } from "vitest";

import {
  isUserActionRuntimeSceneEvent,
  isUserActionStructuredLogRecord,
  matchesRuntimeSceneEventFocusFilter,
} from "./runtimeSceneEventFilters";

describe("runtimeSceneEventFilters", () => {
  it("detects browser.user_action timeline events", () => {
    expect(isUserActionRuntimeSceneEvent({
      eventCode: "browser.user_action.session_delete_started",
      phase: "user_action",
    })).toBe(true);
    expect(isUserActionRuntimeSceneEvent({
      eventCode: "browser.chat_submit.request_started",
      phase: "chat_submit",
    })).toBe(false);
  });

  it("filters timeline events by user_action focus", () => {
    const event = { eventCode: "browser.user_action.session_open_observed", phase: "user_action" };
    expect(matchesRuntimeSceneEventFocusFilter(event, "all")).toBe(true);
    expect(matchesRuntimeSceneEventFocusFilter(event, "user_action")).toBe(true);
    expect(matchesRuntimeSceneEventFocusFilter(
      { eventCode: "launcher.runtime.shutdown.requested", phase: "runtime" },
      "user_action",
    )).toBe(false);
  });

  it("detects user_action structured log records", () => {
    expect(isUserActionStructuredLogRecord({
      eventCode: "browser.user_action.session_create_succeeded",
      phase: "user_action",
    })).toBe(true);
    expect(isUserActionStructuredLogRecord({
      event_code: "browser.user_action.session_turn_stop_failed",
    })).toBe(true);
  });
});
