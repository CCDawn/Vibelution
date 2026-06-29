export type TimelineScrollHeightLike = {
  scrollTop: number;
  scrollHeight: number;
};

export type TimelineScrollHeightAnchor = {
  scrollTop: number;
  scrollHeight: number;
};

export type TimelineRowKeyElementLike = {
  dataset?: {
    conversationRowKey?: string;
  };
  getBoundingClientRect(): {
    top: number;
  };
};

export type TimelineRowKeyLike = TimelineScrollHeightLike & {
  getBoundingClientRect(): {
    top: number;
  };
  querySelectorAll(selector: string): Iterable<Element | TimelineRowKeyElementLike>;
};

export type TimelineScrollRowKeyAnchor = {
  rowKey: string;
  offsetTop: number;
  heightAnchor: TimelineScrollHeightAnchor;
};

export function captureTimelineScrollHeightAnchor(
  timeline: TimelineScrollHeightLike | null | undefined,
): TimelineScrollHeightAnchor | null {
  if (!timeline) {
    return null;
  }
  return {
    scrollTop: timeline.scrollTop,
    scrollHeight: timeline.scrollHeight,
  };
}

export function captureTimelineRowKeyAnchor(
  timeline: TimelineRowKeyLike | null | undefined,
): TimelineScrollRowKeyAnchor | null {
  if (!timeline) {
    return null;
  }
  const rootTop = timeline.getBoundingClientRect().top;
  const rows = Array.from(timeline.querySelectorAll("[data-conversation-row-key]"));
  const visibleRow = rows.find((row) => {
    const rowKey = timelineRowKey(row);
    return Boolean(rowKey) && row.getBoundingClientRect().top >= rootTop;
  }) ?? rows.find((row) => Boolean(timelineRowKey(row)));
  const rowKey = visibleRow ? timelineRowKey(visibleRow) : "";
  if (!visibleRow || !rowKey) {
    return null;
  }
  return {
    rowKey,
    offsetTop: visibleRow.getBoundingClientRect().top - rootTop,
    heightAnchor: {
      scrollTop: timeline.scrollTop,
      scrollHeight: timeline.scrollHeight,
    },
  };
}

export function restoreTimelineScrollHeightAnchor(
  timeline: TimelineScrollHeightLike | null | undefined,
  anchor: TimelineScrollHeightAnchor | null | undefined,
) {
  if (!timeline || !anchor) {
    return false;
  }
  const scrollHeightDelta = timeline.scrollHeight - anchor.scrollHeight;
  timeline.scrollTop = anchor.scrollTop + Math.max(0, scrollHeightDelta);
  return true;
}

export function restoreTimelineRowKeyAnchor(
  timeline: TimelineRowKeyLike | null | undefined,
  anchor: TimelineScrollRowKeyAnchor | null | undefined,
) {
  if (!timeline || !anchor) {
    return false;
  }
  const rootTop = timeline.getBoundingClientRect().top;
  const rows = Array.from(timeline.querySelectorAll("[data-conversation-row-key]"));
  const target = rows.find((row) => timelineRowKey(row) === anchor.rowKey);
  if (!target) {
    return restoreTimelineScrollHeightAnchor(timeline, anchor.heightAnchor);
  }
  const nextOffsetTop = target.getBoundingClientRect().top - rootTop;
  timeline.scrollTop += nextOffsetTop - anchor.offsetTop;
  return true;
}

function timelineRowKey(row: Element | TimelineRowKeyElementLike) {
  if ("dataset" in row) {
    return row.dataset?.conversationRowKey?.trim() ?? "";
  }
  return "";
}
