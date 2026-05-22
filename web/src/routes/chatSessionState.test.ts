import { describe, expect, it } from "vitest";

import { SessionDetail, SessionSummary } from "../api/types";
import {
  markSessionSummaryRunning,
  markSessionDetailRunning,
  mergeSessionDetailIntoSummaries,
  sessionSummaryFromDetail,
} from "./chatSessionState";

function makeSummary(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "session-live",
    title: "当前会话",
    workspacePath: "workspace/chat_sessions/session-live",
    status: "failed",
    taskSummary: "上一轮失败",
    lastActive: "2026-05-22T10:00:00Z",
    updatedAt: "2026-05-22T10:00:00Z",
    currentPhase: "failed",
    ...overrides,
  };
}

function makeDetail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    ...makeSummary({
      status: "running",
      currentPhase: "running",
      taskSummary: "继续",
      updatedAt: "2026-05-22T10:01:00Z",
      lastActive: "2026-05-22T10:01:00Z",
    }),
    activeTask: null,
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    messages: [],
    lastTurnError: null,
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
    ...overrides,
  };
}

describe("chatSessionState", () => {
  it("derives a sidebar-safe summary from active session detail", () => {
    expect(sessionSummaryFromDetail(makeDetail())).toEqual({
      id: "session-live",
      title: "当前会话",
      workspacePath: "workspace/chat_sessions/session-live",
      status: "running",
      taskSummary: "继续",
      lastActive: "2026-05-22T10:01:00Z",
      updatedAt: "2026-05-22T10:01:00Z",
      currentPhase: "running",
    });
  });

  it("lets active detail override a stale failed session summary", () => {
    const merged = mergeSessionDetailIntoSummaries(
      [
        makeSummary(),
        makeSummary({ id: "older-session", title: "旧会话", status: "ready", currentPhase: "ready" }),
      ],
      makeDetail(),
    );

    expect(merged[0].status).toBe("running");
    expect(merged[0].currentPhase).toBe("running");
    expect(merged[0].taskSummary).toBe("继续");
    expect(merged[1].id).toBe("older-session");
  });

  it("marks the active summary as running during submit before list refetch finishes", () => {
    const marked = markSessionSummaryRunning([makeSummary()], "session-live");

    expect(marked?.[0].status).toBe("running");
    expect(marked?.[0].currentPhase).toBe("running");
  });

  it("clears stale turn errors from active detail while submit is pending", () => {
    const marked = markSessionDetailRunning(
      makeDetail({
        status: "failed",
        currentPhase: "failed",
        lastTurnError: {
          message: "上一轮失败",
          errorType: "provider_upstream_error",
          recoverable: true,
          timestamp: "2026-05-22T10:00:00Z",
          turnId: "turn-old",
        },
      }),
    );

    expect(marked?.status).toBe("running");
    expect(marked?.currentPhase).toBe("running");
    expect(marked?.lastTurnError).toBeNull();
  });
});
