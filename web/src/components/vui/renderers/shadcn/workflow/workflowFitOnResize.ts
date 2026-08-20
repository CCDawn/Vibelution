/**
 * Decide whether a settled canvas host size change should re-run fitView.
 *
 * Initial fit can fire before the inspector column takes width. Re-fitting
 * after the host box stabilizes keeps the first row of cards inside the pane
 * instead of clipping under the right chrome. User pan/zoom must win.
 */
export function shouldRefitOnContainerResize(input: {
  width: number;
  height: number;
  previousWidth: number;
  previousHeight: number;
  userMovedViewport: boolean;
  minSize?: number;
  minDelta?: number;
}): boolean {
  if (input.userMovedViewport) {
    return false;
  }
  const minSize = input.minSize ?? 32;
  if (input.width < minSize || input.height < minSize) {
    return false;
  }
  const minDelta = input.minDelta ?? 8;
  if (input.previousWidth <= 0 || input.previousHeight <= 0) {
    return true;
  }
  return (
    Math.abs(input.width - input.previousWidth) >= minDelta
    || Math.abs(input.height - input.previousHeight) >= minDelta
  );
}
