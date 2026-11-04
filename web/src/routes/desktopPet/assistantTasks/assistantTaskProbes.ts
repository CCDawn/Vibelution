/** Bounded liveness probing for a failed task-feed read. The old behaviour kept
 * a failed feed silent forever; this preserves the anti-storm intent (no fixed
 * retries, page-visibility and identity gating stay in the interval closure)
 * while rejoining a recovered source without a manual refresh. Errors probe on
 * a growing cadence — 3s, 6s, then 12s — for at most five attempts and then
 * stop, leaving further recovery to the manual refresh. The anchor is the FIRST
 * failure time: query.state only exposes the last error time, so the caller
 * holds it in a ref, mirroring launcherAssistantWaitInterval's cold-start
 * backoff (which must not be imported across the route boundary). */
export const ASSISTANT_TASK_PROBE_INTERVALS_MS: readonly number[] = [3_000, 6_000, 12_000, 12_000, 12_000];
/** Cumulative elapsed time at which each probe fires after the first failure. */
const PROBE_DUE_MS = ASSISTANT_TASK_PROBE_INTERVALS_MS.map((_, index) =>
  ASSISTANT_TASK_PROBE_INTERVALS_MS.slice(0, index + 1).reduce((sum, delay) => sum + delay, 0));

/** Delay until the next scheduled probe for a feed whose first read failed at
 * `firstErrorAt` (null or non-finite → the first delay), or false once the
 * five-attempt budget is spent. Returning the remaining wait to the fixed due
 * point keeps the cadence stable even when unrelated re-renders re-arm the
 * interval timer. */
export function assistantTaskErrorProbeInterval(firstErrorAt: number | null, now: number): number | false {
  if (firstErrorAt === null || !Number.isFinite(firstErrorAt)) return ASSISTANT_TASK_PROBE_INTERVALS_MS[0];
  const elapsed = Number.isFinite(now) ? Math.max(0, now - firstErrorAt) : 0;
  for (let index = 0; index < PROBE_DUE_MS.length; index += 1) {
    if (elapsed < PROBE_DUE_MS[index]) return PROBE_DUE_MS[index] - elapsed;
  }
  return false;
}
