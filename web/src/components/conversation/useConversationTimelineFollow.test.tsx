// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";

import {
  useConversationTimelineFollow,
  type UseConversationTimelineFollowInput,
} from "./useConversationTimelineFollow";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("keeps following on a guidance remeasure while still releasing follow for a real upward scroll", async () => {
  const host = document.createElement("div");
  const timeline = document.createElement("div");
  document.body.append(host, timeline);
  Object.defineProperties(timeline, {
    scrollHeight: { value: 1000, configurable: true },
    clientHeight: { value: 400, configurable: true },
  });
  const input: UseConversationTimelineFollowInput = {
    timelineFollowApiRef: { current: null },
    sessionId: "steer-follow-test",
    timelineRef: { current: timeline },
    timelineContentRef: { current: null },
    readingViewportAnchorRef: { current: null },
    historyScrollAnchorRef: { current: null },
    historyAnchorCorrectingRef: { current: null },
    followLatestRef: { current: true },
    atBottomRef: { current: true },
    userScrollIntentRef: { current: "none" },
    userScrollIntentAtRef: { current: 0 },
    ignoreNextProgrammaticFollowRef: { current: false },
    lastTimelineScrollTopRef: { current: 0 },
    lastTimelineContentWidthRef: { current: 0 },
    contentWidthChangingUntilRef: { current: 0 },
    streamingScrollFrameRef: { current: null },
    autoScrollToLatestRef: { current: true },
    initializedSessionRef: { current: "steer-follow-test" },
    pinnedLatestUserMessageIdRef: { current: "user" },
    setIsAtBottom: vi.fn(),
    autoScrollToLatest: true,
    latestUserMessageId: "user",
    timelineScrollSignal: "unchanged-answer",
    streamingTimelineScrollSignal: "",
    narrowTimelineViewport: false,
    activeTimelineMessages: [],
    displayMessages: [],
    earlierMessagesLoading: false,
    hasEarlierMessages: false,
    hiddenHistorySignalCount: 0,
    visibleMessageCount: 0,
    timelineLiveTailStartIndex: 0,
    timelineVirtualizer: {} as UseConversationTimelineFollowInput["timelineVirtualizer"],
    preserveCurrentExpansionDefaults: vi.fn(),
  };
  function Harness({ count }: { count: number }) {
    useConversationTimelineFollow({ ...input, displayMessages: Array(count).fill({}) });
    return null;
  }
  const root = createRoot(host);
  // Keep geometry deterministic: this test exercises the effect's measurement
  // snapshot separately from the scroll event sent below.
  vi.stubGlobal("ResizeObserver", undefined);
  try {
    await act(async () => root.render(<Harness count={1} />));
    input.followLatestRef.current = true;
    input.ignoreNextProgrammaticFollowRef.current = false;
    input.userScrollIntentRef.current = "none";
    input.lastTimelineScrollTopRef.current = 220;
    timeline.scrollTop = 200;
    await act(async () => root.render(<Harness count={2} />));
    expect(input.followLatestRef.current).toBe(true);

    await act(async () => {
      timeline.dispatchEvent(new WheelEvent("wheel", { deltaY: -100 }));
      timeline.scrollTop = 100;
      timeline.dispatchEvent(new Event("scroll"));
    });
    expect(input.followLatestRef.current).toBe(false);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    timeline.remove();
    vi.unstubAllGlobals();
  }
});

it("drops the previous conversation's pending viewport work when the session switches", async () => {
  const host = document.createElement("div");
  const timeline = document.createElement("div");
  document.body.append(host, timeline);
  Object.defineProperties(timeline, {
    scrollHeight: { value: 1000, configurable: true },
    clientHeight: { value: 400, configurable: true },
  });
  const anchor = { rowKey: "old-row", offsetPx: 12 } as never;
  const historyAnchorCorrectingRef = {
    current: { anchor, startLength: 3, fallbackDone: true, geometryReflow: false } as never,
  };
  const historyScrollAnchorRef = { current: anchor };
  const readingViewportAnchorRef = { current: anchor };
  const contentWidthChangingUntilRef = { current: 9_999_999 };
  const input: UseConversationTimelineFollowInput = {
    timelineFollowApiRef: { current: null },
    sessionId: "session-old",
    timelineRef: { current: timeline },
    timelineContentRef: { current: null },
    readingViewportAnchorRef,
    historyScrollAnchorRef,
    historyAnchorCorrectingRef,
    followLatestRef: { current: true },
    atBottomRef: { current: true },
    userScrollIntentRef: { current: "none" },
    userScrollIntentAtRef: { current: 0 },
    ignoreNextProgrammaticFollowRef: { current: false },
    lastTimelineScrollTopRef: { current: 0 },
    lastTimelineContentWidthRef: { current: 0 },
    contentWidthChangingUntilRef,
    streamingScrollFrameRef: { current: null },
    autoScrollToLatestRef: { current: true },
    initializedSessionRef: { current: "session-old" },
    pinnedLatestUserMessageIdRef: { current: "" },
    setIsAtBottom: vi.fn(),
    autoScrollToLatest: true,
    latestUserMessageId: "",
    timelineScrollSignal: "steady",
    streamingTimelineScrollSignal: "",
    narrowTimelineViewport: false,
    activeTimelineMessages: [],
    displayMessages: [],
    earlierMessagesLoading: false,
    hasEarlierMessages: false,
    hiddenHistorySignalCount: 0,
    visibleMessageCount: 0,
    timelineLiveTailStartIndex: 0,
    timelineVirtualizer: {} as UseConversationTimelineFollowInput["timelineVirtualizer"],
    preserveCurrentExpansionDefaults: vi.fn(),
  };
  function Harness({ sessionId }: { sessionId: string }) {
    useConversationTimelineFollow({ ...input, sessionId });
    return null;
  }
  const root = createRoot(host);
  vi.stubGlobal("ResizeObserver", undefined);
  try {
    await act(async () => root.render(<Harness sessionId="session-old" />));
    // The same session keeps whatever viewport work it already owns.
    expect(historyAnchorCorrectingRef.current).not.toBeNull();
    // Re-arm the reading anchor right before the switch: the assertion below can
    // then only pass because the switch itself cleared it.
    readingViewportAnchorRef.current = anchor;

    await act(async () => root.render(<Harness sessionId="session-new" />));

    // Frames queued for the old conversation must not re-pin the new one.
    expect(historyAnchorCorrectingRef.current).toBeNull();
    expect(historyScrollAnchorRef.current).toBeNull();
    expect(readingViewportAnchorRef.current).toBeNull();
    expect(contentWidthChangingUntilRef.current).toBe(0);
  } finally {
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
    host.remove();
    timeline.remove();
  }
});
