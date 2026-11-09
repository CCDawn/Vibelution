/**
 * Connection health is a poll observation, not a verdict.
 *
 * `/api/health` runs on a bounded 8s timeout and the query keeps `retry: false`,
 * so a single slow response (GC pause, a long tool call holding the loop) is
 * reported as an error even though the workbench is alive. Covering the page
 * with a recovery notice on that one sample turns ordinary jitter into an
 * incident, so the notice waits until the failure repeats.
 */
export const CONNECTION_FAILURE_STREAK_THRESHOLD = 2;

export type HealthFailureStreak = { errorAt: number; count: number };

export const EMPTY_HEALTH_FAILURE_STREAK: HealthFailureStreak = { errorAt: 0, count: 0 };

/**
 * Advance the streak for one health poll result.
 *
 * Keyed on the error stamp so it is idempotent: a repeated render (StrictMode,
 * concurrent re-render, or a parent re-render) observing the same failed poll
 * cannot inflate the count, and a recovered poll resets it immediately.
 */
export function nextHealthFailureStreak(
  previous: HealthFailureStreak,
  input: { healthy: boolean; errorAt: number },
): HealthFailureStreak {
  if (input.healthy) return EMPTY_HEALTH_FAILURE_STREAK;
  const errorAt = Number(input.errorAt) || 0;
  if (!errorAt || errorAt === previous.errorAt) return previous;
  return { errorAt, count: previous.count + 1 };
}

/**
 * The notice only earns screen space once the failure repeats; a single failed
 * poll stays silent so the page and drafts are never covered by noise.
 */
export function connectionNoticeVisible(input: {
  unavailable: boolean;
  failureCount: number;
  startupOverlayActive: boolean;
  shutdownOpen: boolean;
}): boolean {
  if (input.startupOverlayActive || input.shutdownOpen) return false;
  if (!input.unavailable) return false;
  return input.failureCount >= CONNECTION_FAILURE_STREAK_THRESHOLD;
}
