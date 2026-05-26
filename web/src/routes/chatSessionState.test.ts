import { describe, expect, it } from "vitest";

import { SessionDetail, SessionSummary } from "../api/types";
import {
  deriveSessionDetailQueryErrorState,
  deriveSessionListQueryErrorState,
  markSessionSummaryRunning,
  markSessionDetailRunning,
  mergeSessionDetailIntoSummaries,
  sessionSummaryFromDetail,
  shouldAcceptSessionStreamEvent,
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

  it("adds a newly returned active detail to the top without dropping existing summaries", () => {
    const olderSession = makeSummary({ id: "older-session", title: "旧会话", status: "ready", currentPhase: "ready" });
    const merged = mergeSessionDetailIntoSummaries(
      [olderSession],
      makeDetail({ id: "new-session", title: "新会话", taskSummary: "刚创建" }),
    );

    expect(merged).toHaveLength(2);
    expect(merged[0]).toMatchObject({
      id: "new-session",
      title: "新会话",
      taskSummary: "刚创建",
      status: "running",
      currentPhase: "running",
    });
    expect(merged[1]).toEqual(olderSession);
  });

  it("only marks the requested session summary as running", () => {
    const olderSession = makeSummary({ id: "older-session", title: "旧会话", status: "ready", currentPhase: "ready" });
    const marked = markSessionSummaryRunning([makeSummary(), olderSession], "session-live");

    expect(marked?.[0].status).toBe("running");
    expect(marked?.[0].currentPhase).toBe("running");
    expect(marked?.[1]).toEqual(olderSession);
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

  it("keeps stale detail visible when a refetch fails", () => {
    expect(deriveSessionDetailQueryErrorState(makeDetail(), true)).toEqual({
      blockingError: false,
      transientError: true,
      backgroundError: false,
    });
  });

  it("only blocks detail rendering when a failed query has no cached detail", () => {
    expect(deriveSessionDetailQueryErrorState(undefined, true)).toEqual({
      blockingError: true,
      transientError: false,
      backgroundError: false,
    });
  });

  it("keeps live stream detail authoritative when a background refetch fails", () => {
    expect(
      deriveSessionDetailQueryErrorState(makeDetail(), true, {
        dataUpdatedAt: 2_000,
        errorUpdatedAt: 3_000,
        streamConnected: true,
      }),
    ).toEqual({
      blockingError: false,
      transientError: false,
      backgroundError: true,
    });
  });

  it("clears a query error once a newer session detail snapshot arrives", () => {
    expect(
      deriveSessionDetailQueryErrorState(makeDetail(), true, {
        dataUpdatedAt: 4_000,
        errorUpdatedAt: 3_000,
        streamConnected: true,
      }),
    ).toEqual({
      blockingError: false,
      transientError: false,
      backgroundError: false,
    });
  });

  it("keeps stale session list visible when a list refetch fails", () => {
    expect(deriveSessionListQueryErrorState([makeSummary()], true)).toEqual({
      blockingError: false,
      transientError: true,
    });
  });

  it("only blocks session list rendering when no cached sessions exist", () => {
    expect(deriveSessionListQueryErrorState([], true)).toEqual({
      blockingError: true,
      transientError: false,
    });
  });

  it("accepts stream detail events only for the active session", () => {
    const activeDetail = makeDetail({ id: "session-live" });
    const staleDetail = makeDetail({ id: "older-session", title: "旧会话" });

    expect(
      shouldAcceptSessionStreamEvent(
        {
          type: "session_detail",
          sessionId: "session-live",
          detail: activeDetail,
        },
        "session-live",
      ),
    ).toBe(true);

    expect(
      shouldAcceptSessionStreamEvent(
        {
          type: "session_detail",
          sessionId: "older-session",
          detail: staleDetail,
        },
        "session-live",
      ),
    ).toBe(false);
  });

  it("rejects malformed stream events even if their detail looks current", () => {
    expect(
      shouldAcceptSessionStreamEvent(
        {
          type: "session_detail",
          sessionId: "older-session",
          detail: makeDetail({ id: "session-live" }),
        },
        "session-live",
      ),
    ).toBe(false);
  });
});
