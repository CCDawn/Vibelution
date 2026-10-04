import { describe, expect, it, beforeEach } from "vitest";

import type { SessionDetail } from "../../api/types";
import {
  clearSessionTimelineScrollMemoryForTests,
  peekSessionTimelineScroll,
  rememberSessionTimelineScroll,
} from "../../components/conversation/conversationSessionScrollMemory";
import {
  clearSessionDetailPaintCacheForTests,
  forgetSessionDetailPaint,
  listSessionKeepAliveIds,
  nextSessionKeepAliveIds,
  rememberSessionDetailPaint,
  removeOptimisticUserMessagePaint,
  resolveStickySessionDetailPaint,
  shouldShowStickyTranscriptPending,
  touchSessionKeepAlive,
} from "./chatSessionPaintCache";
import { appendOptimisticUserMessage, applyOptimisticEditResubmit, removeOptimisticUserMessage } from "../chatSessionState";

function detail(id: string, messages: number, provisional = false): SessionDetail {
  return {
    id,
    title: id,
    messages: Array.from({ length: messages }, (_, index) => ({
      id: `${id}-m${index}`,
      role: "user",
      content: "x",
    })),
    provisionalTranscript: provisional || undefined,
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
  } as SessionDetail;
}

function windowedDetail(
  id: string,
  ledgerSeq: number,
  messages: Array<{ index: number; role: "user" | "assistant"; content: string }>,
  window: { total: number; oldest: number; newest: number },
): SessionDetail {
  return {
    id,
    title: id,
    ledgerSeq,
    messages: messages.map((message) => ({
      id: `${id}-message-${message.index}`,
      role: message.role,
      content: message.content,
    })),
    messageWindow: {
      mode: "window",
      totalMessages: window.total,
      returnedMessages: messages.length,
      oldestMessageIndex: window.oldest,
      newestMessageIndex: window.newest,
      hasEarlier: window.oldest > 1,
      hasLater: false,
      nextBeforeMessageIndex: window.oldest > 1 ? window.oldest : null,
      transcriptScope: "window",
    },
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
  } as SessionDetail;
}

describe("chatSessionPaintCache", () => {
  beforeEach(() => {
    clearSessionDetailPaintCacheForTests();
    clearSessionTimelineScrollMemoryForTests();
  });

  it.each([false, true])("does not resurrect a removed optimistic submission (windowed=%s)", (windowed) => {
    const original = windowed
      ? windowedDetail("s1", 40, [{ index: 1, role: "user", content: "真实历史" }], { total: 1, oldest: 1, newest: 1 })
      : detail("s1", 1);
    const submission = { sessionId: "s1", clientSubmissionId: "failed-submit", content: "没有发出的消息" };
    const pending = appendOptimisticUserMessage(original, submission)!;
    rememberSessionDetailPaint(pending);
    const removed = removeOptimisticUserMessage(pending, submission)!;
    removeOptimisticUserMessagePaint("s1", submission);

    const paint = resolveStickySessionDetailPaint({ activeSessionId: "s1", detail: removed });
    expect(paint?.messages).toEqual(original.messages);
    // A later provisional shell must not revive the removed submission either.
    expect(resolveStickySessionDetailPaint({ activeSessionId: "s1", detail: detail("s1", 0, true) })?.messages).toEqual(original.messages);
  });

  it("keeps a pending submission while only a provisional shell is available", () => {
    const pending = appendOptimisticUserMessage(detail("s1", 1), {
      sessionId: "s1", clientSubmissionId: "still-pending", content: "等待中的消息",
    })!;
    rememberSessionDetailPaint(pending);
    const paint = resolveStickySessionDetailPaint({ activeSessionId: "s1", detail: detail("s1", 0, true) });
    expect(paint?.messages).toHaveLength(pending.messages.length);
    expect(paint?.messages).toEqual(expect.arrayContaining(pending.messages));
  });

  it("withdraws only the failed submission in its own session", () => {
    const failed = { sessionId: "s1", clientSubmissionId: "failed", content: "相同正文" };
    const other = { ...failed, clientSubmissionId: "still-pending" };
    const first = appendOptimisticUserMessage(detail("s1", 1), failed)!;
    const both = appendOptimisticUserMessage(first, other)!;
    const foreign = appendOptimisticUserMessage(detail("s2", 1), { ...failed, sessionId: "s2" })!;
    rememberSessionDetailPaint(both);
    rememberSessionDetailPaint(foreign);
    removeOptimisticUserMessagePaint("s1", failed);
    const live = removeOptimisticUserMessage(both, failed)!;

    const paint = resolveStickySessionDetailPaint({ activeSessionId: "s1", detail: live });
    expect(paint?.messages.map((message) => message.id).sort()).toEqual(live.messages.map((message) => message.id).sort());
    const foreignPaint = resolveStickySessionDetailPaint({ activeSessionId: "s2", detail: detail("s2", 0, true) });
    expect(foreignPaint?.messages).toEqual(expect.arrayContaining(foreign.messages));
    expect(foreignPaint?.messages).toHaveLength(foreign.messages.length);
  });

  it("keeps current optimistic submissions and committed history outside a thin live window", () => {
    const submission = { sessionId: "s1", clientSubmissionId: "still-pending", content: "等待中的消息" };
    const pending = appendOptimisticUserMessage(detail("s1", 3), submission)!;
    rememberSessionDetailPaint(pending);
    const live = appendOptimisticUserMessage(detail("s1", 1), submission)!;
    expect(resolveStickySessionDetailPaint({ activeSessionId: "s1", detail: live })?.messages.map((message) => message.id).sort())
      .toEqual(pending.messages.map((message) => message.id).sort());
  });

  it("does not resurrect messages a strictly newer authoritative window truncated", () => {
    rememberSessionDetailPaint(
      windowedDetail("s1", 40, [
        { index: 1, role: "user", content: "第一问" },
        { index: 2, role: "assistant", content: "第一答" },
        { index: 3, role: "user", content: "第二问" },
        { index: 4, role: "assistant", content: "本轮已按请求停止。" },
      ], { total: 4, oldest: 1, newest: 4 }),
    );

    const paint = resolveStickySessionDetailPaint({
      activeSessionId: "s1",
      detail: windowedDetail("s1", 48, [
        { index: 1, role: "user", content: "第一问" },
        { index: 2, role: "assistant", content: "第一答" },
        { index: 3, role: "user", content: "第二问（改写后重发）" },
      ], { total: 3, oldest: 1, newest: 3 }),
    });

    expect(paint?.messages.map((message) => message.id)).toEqual([
      "s1-message-1",
      "s1-message-2",
      "s1-message-3",
    ]);
    expect(paint?.messageWindow?.totalMessages).toBe(3);
  });

  it("remembers non-provisional detail and reuses it while a provisional shell is active", () => {
    rememberSessionDetailPaint(detail("s1", 3));
    const paint = resolveStickySessionDetailPaint({
      activeSessionId: "s1",
      detail: detail("s1", 0, true),
    });
    expect(paint?.messages?.length).toBeGreaterThanOrEqual(3);
    expect(paint?.provisionalTranscript).toBeFalsy();
  });

  it("does not let a thin live window erase richer sticky history while turn is running", () => {
    rememberSessionDetailPaint(detail("s1", 8));
    const paint = resolveStickySessionDetailPaint({
      activeSessionId: "s1",
      // Live window only has the latest few messages (common mid-turn GET).
      detail: detail("s1", 2, false),
    });
    expect(paint?.messages?.length).toBeGreaterThanOrEqual(8);
  });

  it("keeps a pending edit tail hidden when a stale no-window detail arrives after a session switch", () => {
    const original = detail("s1", 4);
    const optimistic = applyOptimisticEditResubmit(original, {
      messageId: "s1-m0",
      content: "改写后的第一问",
      clientSubmissionId: "submission-edit-switch",
    });
    rememberSessionDetailPaint(optimistic);
    const paint = resolveStickySessionDetailPaint({
      activeSessionId: "s1",
      detail: original,
    });
    expect(paint?.messages).toHaveLength(1);
    expect(paint?.messages[0]?.content).toBe("改写后的第一问");
  });

  it("does not treat sticky messages as transcript-pending", () => {
    const sticky = detail("s1", 2);
    expect(
      shouldShowStickyTranscriptPending({
        activeSessionId: "s1",
        paintDetail: sticky,
        liveDetail: detail("s1", 0, true),
        isFetching: true,
      }),
    ).toBe(false);
  });

  it("shows pending only when there is no usable paint and hydration is in flight", () => {
    expect(
      shouldShowStickyTranscriptPending({
        activeSessionId: "s1",
        paintDetail: detail("s1", 0, true),
        liveDetail: detail("s1", 0, true),
        isFetching: true,
      }),
    ).toBe(true);
    expect(
      shouldShowStickyTranscriptPending({
        activeSessionId: "s1",
        paintDetail: detail("s1", 0, false),
        liveDetail: detail("s1", 0, false),
        isFetching: false,
      }),
    ).toBe(false);
  });

  it("forgets deleted sessions and keeps an active-first keep-alive window", () => {
    rememberSessionDetailPaint(detail("s1", 1));
    rememberSessionTimelineScroll("s1", { scrollTop: 88, followingLatest: false });
    forgetSessionDetailPaint("s1");
    expect(
      resolveStickySessionDetailPaint({
        activeSessionId: "s1",
        detail: detail("s1", 0, true),
      })?.provisionalTranscript,
    ).toBe(true);
    expect(peekSessionTimelineScroll("s1")).toBeUndefined();
    expect(
      nextSessionKeepAliveIds({
        activeSessionId: "b",
        previousIds: ["a", "c"],
        limit: 2,
      }),
    ).toEqual(["b", "a"]);
  });

  it("touches keep-alive ring with active-first order", () => {
    expect(touchSessionKeepAlive("a", 3)).toEqual(["a"]);
    expect(touchSessionKeepAlive("b", 3)).toEqual(["b", "a"]);
    expect(touchSessionKeepAlive("c", 3)).toEqual(["c", "b", "a"]);
    expect(touchSessionKeepAlive("d", 3)).toEqual(["d", "c", "b"]);
    expect(listSessionKeepAliveIds()).toEqual(["d", "c", "b"]);
    forgetSessionDetailPaint("c");
    expect(listSessionKeepAliveIds()).toEqual(["d", "b"]);
  });
});
