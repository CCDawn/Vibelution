type ScrollContainer = {
  clientHeight: number;
  scrollHeight: number;
  scrollTop: number;
};

type ScrollAnchorElement = {
  getBoundingClientRect: () => { top: number };
};

export type ConversationProcessScrollAnchor = {
  summaryTop: number;
};

export function captureConversationProcessScrollAnchor(
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
  if (Math.abs(summaryDelta) < 0.5) {
    return;
  }
  const maxScrollTop = Math.max(0, timeline.scrollHeight - timeline.clientHeight);
  timeline.scrollTop = Math.min(
    maxScrollTop,
    Math.max(0, timeline.scrollTop + summaryDelta),
  );
}
