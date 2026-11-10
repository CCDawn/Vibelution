/**
 * Pure collapse policy for oversized assistant answers. This is the same
 * ZCode-aligned policy the user bubble already uses, applied to the other half
 * of the transcript: an answer past the threshold clamps to a bounded viewport
 * with a bottom fade plus an expand/collapse ghost toggle. Measurement-driven
 * (ResizeObserver content height, so async media growth counts) and never
 * persisted, so every mount starts collapsed.
 *
 * The assistant threshold is deliberately looser than the user bubble: the
 * answer is the payload the reader came for, so it earns several times the
 * visible height before folding.
 */

/** Measured content height (px) above which an assistant answer renders collapsed. */
export const ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX = 480;

/**
 * Decide whether the measured content height should render collapsed.
 * Pure on purpose so the threshold policy stays machine-checkable without
 * mounting the component.
 */
export function shouldCollapseAssistantMessage(measuredHeight: number): boolean {
  return measuredHeight > ASSISTANT_MESSAGE_COLLAPSE_THRESHOLD_PX;
}
