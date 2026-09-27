/**
 * Pure collapse policy for oversized user message bubbles (ZCode-aligned):
 * the bubble body clamps to a short viewport with a bottom fade plus an
 * expand/collapse ghost toggle. Measurement-driven (scrollHeight), not
 * line-budget-driven, and never persisted — every render starts collapsed.
 */

/** Measured content height (px) above which a user message renders collapsed. */
export const USER_MESSAGE_COLLAPSE_THRESHOLD_PX = 120;

/**
 * Decide whether the measured content height should render collapsed.
 * Pure on purpose so the threshold policy stays machine-checkable without
 * mounting the component.
 */
export function shouldCollapseUserMessage(measuredHeight: number): boolean {
  return measuredHeight > USER_MESSAGE_COLLAPSE_THRESHOLD_PX;
}
