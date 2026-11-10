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
/** A normal workbench restart is seconds, not an outage. */
export const CONNECTION_FAILURE_PERSISTENCE_MS = 45_000;

export type HealthFailureStreak = { errorAt: number; count: number; startedAt: number };

export const EMPTY_HEALTH_FAILURE_STREAK: HealthFailureStreak = { errorAt: 0, count: 0, startedAt: 0 };

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
  return {
    errorAt,
    count: previous.count + 1,
    // The outage clock starts at the first failed poll, not at the last
    // successful one. A long idle gap before a restart must not make the
    // first post-restart failure look like a 45s outage.
    startedAt: previous.startedAt || errorAt,
  };
}

/**
 * The notice only earns screen space once the failure has persisted. Two
 * failed polls during a normal restart are expected, not an outage; showing a
 * recovery card there makes every update look broken. A real outage still
 * surfaces after the same 45s window used for the persistent copy.
 */
export function connectionNoticeVisible(input: {
  unavailable: boolean;
  failureCount: number;
  failureStartedAt: number;
  failedAt: number;
  startupOverlayActive: boolean;
  shutdownOpen: boolean;
}): boolean {
  if (input.startupOverlayActive || input.shutdownOpen) return false;
  if (!input.unavailable) return false;
  if (input.failureCount < CONNECTION_FAILURE_STREAK_THRESHOLD) return false;
  if (!input.failureStartedAt || !input.failedAt) return false;
  return input.failedAt - input.failureStartedAt >= CONNECTION_FAILURE_PERSISTENCE_MS;
}
