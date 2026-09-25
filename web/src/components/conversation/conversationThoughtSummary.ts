/**
 * Collapsed thinking-lane presentation helpers (ZCode reasoning parity).
 *
 * The collapsed thought header keeps a single-line horizontal summary of the
 * latest thought sentence: the viewport hides overflow, pins the newest words
 * to the right edge and fades both edges with a CSS mask. These helpers stay
 * DOM-free so the sentence extraction and the scroll-follow gate are unit
 * testable.
 */

export type ThoughtStreamingSummary = {
  /** Identity of the source line; lets the viewport re-sync when the line changes. */
  key: string;
  text: string;
};

/** Distance from the scroll bottom that still counts as "following". */
const THOUGHT_BOTTOM_LOCK_DISTANCE_PX = 2;

export type ThoughtScrollMetrics = {
  clientHeight: number;
  scrollHeight: number;
  scrollTop: number;
};

/**
 * Latest thought sentence: the last non-empty line of the streamed text, with
 * the source line index as identity so repeated renders of the same line do
 * not re-trigger viewport syncs.
 */
export function resolveThoughtStreamingSummary(text: string): ThoughtStreamingSummary | null {
  const lines = String(text ?? "").replace(/\r\n?/gu, "\n").split("\n");
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index]?.trim() ?? "";
    if (line.length > 0) {
      return { key: String(index), text: line };
    }
  }
  return null;
}

export function thoughtScrollDistanceFromBottom(metrics: ThoughtScrollMetrics): number {
  return Math.max(0, metrics.scrollHeight - metrics.clientHeight - metrics.scrollTop);
}

/** True when the scroll viewport sits at (or within tolerance of) the bottom. */
export function isThoughtScrollAtBottom(metrics: ThoughtScrollMetrics): boolean {
  return thoughtScrollDistanceFromBottom(metrics) <= THOUGHT_BOTTOM_LOCK_DISTANCE_PX;
}
