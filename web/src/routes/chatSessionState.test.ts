import { describe, expect, it } from "vitest";

import { SessionDetail, SessionSummary } from "../api/types";
import {
  appendOptimisticUserMessage,
  deriveSessionDetailQueryErrorState,
  deriveSessionListQueryErrorState,
  markSessionSummaryRunning,
  markSessionDetailRunning,
  mergeSessionDetailIntoSummaries,
  renameSessionDetail,
  renameSessionInSummaries,
  removeDeletedSessionFromSummaries,
  removeOptimisticUserMessage,
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
      activeChildSessionId: undefined,
      childSessionIds: undefined,
      childStatus: undefined,
      parentSessionId: undefined,
      resultCard: undefined,
      rootSessionId: undefined,
      sessionKind: undefined,
      taskTitle: undefined,
    });
  });

  it("preserves child-session fields when deriving a sidebar summary", () => {
    const summary = sessionSummaryFromDetail(
      makeDetail({
        sessionKind: "child",
        parentSessionId: "session-root",
        rootSessionId: "session-root",
        childSessionIds: [],
        activeChildSessionId: "",
        childStatus: "running",
        taskTitle: "修复子对话",
        resultCard: { status: "running", title: "修复子对话", summary: "正在处理" },
      }),
    );

    expect(summary).toMatchObject({
      sessionKind: "child",
      parentSessionId: "session-root",
      rootSessionId: "session-root",
      childSessionIds: [],
      activeChildSessionId: "",
      childStatus: "running",
      taskTitle: "修复子对话",
      resultCard: { status: "running", title: "修复子对话", summary: "正在处理" },
    });
  });

  it("preserves Agent instance fields without legacy profile/template identity", () => {
    const summary = sessionSummaryFromDetail(
      makeDetail({
        agentId: "agent-001",
        agentCode: "A001",
        agentDisplayName: "陈晨",
        agentWorkspacePath: "workspace/agents/agent-001",
        agentMissing: true,
        agentStatusCode: "archived",
        agentStatusMessage: "缺少有效 Agent",
      }),
    );

    expect(summary).toMatchObject({
      agentId: "agent-001",
      agentCode: "A001",
      agentDisplayName: "陈晨",
      agentWorkspacePath: "workspace/agents/agent-001",
      agentMissing: true,
      agentStatusCode: "archived",
      agentStatusMessage: "缺少有效 Agent",
    });
    expect(summary).not.toHaveProperty("agentProfileId");
    expect(summary).not.toHaveProperty("agentTemplateId");
    expect(summary).not.toHaveProperty("agentTemplateLabel");
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

  it("removes a deleted session before merging the next active detail", () => {
    const deletedSession = makeSummary({ id: "deleted-session", title: "删除的会话" });
    const olderSession = makeSummary({ id: "older-session", title: "旧会话", status: "ready", currentPhase: "ready" });
    const merged = removeDeletedSessionFromSummaries(
      [deletedSession, olderSession],
      "deleted-session",
      makeDetail({ id: "next-session", title: "下一个会话", taskSummary: "已切换" }),
    );

    expect(merged.map((session) => session.id)).toEqual(["next-session", "older-session"]);
    expect(merged[0]).toMatchObject({
      title: "下一个会话",
      taskSummary: "已切换",
    });
  });

  it("only marks the requested session summary as running", () => {
    const olderSession = makeSummary({ id: "older-session", title: "旧会话", status: "ready", currentPhase: "ready" });
    const marked = markSessionSummaryRunning([makeSummary(), olderSession], "session-live");

    expect(marked?.[0].status).toBe("running");
    expect(marked?.[0].currentPhase).toBe("running");
    expect(marked?.[1]).toEqual(olderSession);
  });

  it("renames only the requested session summary before the backend returns", () => {
    const olderSession = makeSummary({ id: "older-session", title: "旧会话" });
    const renamed = renameSessionInSummaries(
      [makeSummary(), olderSession],
      "session-live",
      "新名称",
      "2026-05-22T10:02:00Z",
    );

    expect(renamed?.[0].title).toBe("新名称");
    expect(renamed?.[0].updatedAt).toBe("2026-05-22T10:02:00Z");
    expect(renamed?.[1]).toEqual(olderSession);
  });

  it("renames active session detail without touching other details", () => {
    const renamed = renameSessionDetail(
      makeDetail({ title: "旧名称" }),
      "session-live",
      "新名称",
      "2026-05-22T10:02:00Z",
    );
    const untouched = renameSessionDetail(
      makeDetail({ id: "other-session", title: "其他会话" }),
      "session-live",
      "新名称",
      "2026-05-22T10:02:00Z",
    );

    expect(renamed?.title).toBe("新名称");
    expect(renamed?.updatedAt).toBe("2026-05-22T10:02:00Z");
    expect(untouched?.title).toBe("其他会话");
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

  it("appends a pending user message before the submit request finishes", () => {
    const detail = makeDetail({
      messages: [
        {
          id: "assistant-1",
          role: "assistant",
          content: "上一轮回复",
          timestamp: "2026-05-22T10:00:00Z",
        },
      ],
    });

    const nextDetail = appendOptimisticUserMessage(detail, {
      sessionId: "session-live",
      content: "先展示这条消息",
      attachmentIds: ["artifact-1"],
      createdAt: "2026-05-22T10:02:00Z",
    });

    expect(nextDetail?.messages).toHaveLength(2);
    expect(nextDetail?.messages[1]).toMatchObject({
      role: "user",
      content: "先展示这条消息",
      timestamp: "2026-05-22T10:02:00Z",
      metadata: {
        optimisticUserMessage: true,
        pending: true,
        attachmentIds: ["artifact-1"],
      },
    });
    expect(nextDetail?.messages[1].id).toContain("optimistic-user-session-live");
  });

  it("does not append the same pending user message twice", () => {
    const detail = makeDetail();
    const input = {
      sessionId: "session-live",
      content: "不要重复",
      createdAt: "2026-05-22T10:02:00Z",
    };

    const first = appendOptimisticUserMessage(detail, input);
    const second = appendOptimisticUserMessage(first, input);

    expect(second?.messages).toHaveLength(1);
  });

  it("removes only the pending optimistic user message when submit fails", () => {
    const detail = makeDetail({
      messages: [
        {
          id: "user-real",
          role: "user",
          content: "真实历史消息",
          timestamp: "2026-05-22T10:00:00Z",
        },
      ],
    });
    const withPending = appendOptimisticUserMessage(detail, {
      sessionId: "session-live",
      content: "失败时撤回",
      createdAt: "2026-05-22T10:02:00Z",
    });

    const nextDetail = removeOptimisticUserMessage(withPending, {
      sessionId: "session-live",
      content: "失败时撤回",
    });

    expect(nextDetail?.messages).toEqual(detail.messages);
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

  it("accepts assistant delta stream events only for the active session", () => {
    expect(
      shouldAcceptSessionStreamEvent(
        {
          type: "assistant_delta",
          sessionId: "session-live",
          turnId: "turn-running",
          stage: "model_response",
          content: "hello",
          thought: "",
          updatedAt: "2026-01-01T00:00:00Z",
          done: false,
        },
        "session-live",
      ),
    ).toBe(true);

    expect(
      shouldAcceptSessionStreamEvent(
        {
          type: "assistant_delta",
          sessionId: "older-session",
          turnId: "turn-running",
          stage: "model_response",
          content: "stale",
          thought: "",
          updatedAt: "2026-01-01T00:00:00Z",
          done: false,
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
