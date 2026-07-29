type ScrollContainer = {
  scrollTop: number;
};

type ScrollAnchorElement = {
  getBoundingClientRect: () => { top: number };
};

export type ConversationProcessScrollAnchor = {
  summaryTop: number;
};

export function captureConversationProcessScrollAnchor(
  _timeline: ScrollContainer,
  summary: ScrollAnchorElement,
): ConversationProcessScrollAnchor {
  return {
    summaryTop: summary.getBoundingClientRect().top,
  };
}

export function restoreConversationProcessScrollAnchor(
  timeline: ScrollContainer,
  summary: ScrollAnchorElement,
  anchor: ConversationProcessScrollAnchor,
) {
  const summaryDelta = summary.getBoundingClientRect().top - anchor.summaryTop;
  timeline.scrollTop = Math.max(0, timeline.scrollTop + summaryDelta);
}
