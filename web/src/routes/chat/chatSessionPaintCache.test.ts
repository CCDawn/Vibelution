import { describe, expect, it, beforeEach } from "vitest";

import type { SessionDetail } from "../../api/types";
import {
  clearSessionDetailPaintCacheForTests,
  forgetSessionDetailPaint,
  nextSessionKeepAliveIds,
  rememberSessionDetailPaint,
  resolveStickySessionDetailPaint,
  shouldShowStickyTranscriptPending,
} from "./chatSessionPaintCache";

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

describe("chatSessionPaintCache", () => {
  beforeEach(() => {
    clearSessionDetailPaintCacheForTests();
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
    forgetSessionDetailPaint("s1");
    expect(
      resolveStickySessionDetailPaint({
        activeSessionId: "s1",
        detail: detail("s1", 0, true),
      })?.provisionalTranscript,
    ).toBe(true);
    expect(
      nextSessionKeepAliveIds({
        activeSessionId: "b",
        previousIds: ["a", "c"],
        limit: 2,
      }),
    ).toEqual(["b", "a"]);
  });
});
