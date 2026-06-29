export type TimelineScrollHeightLike = {
  scrollTop: number;
  scrollHeight: number;
};

export type TimelineScrollHeightAnchor = {
  scrollTop: number;
  scrollHeight: number;
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
