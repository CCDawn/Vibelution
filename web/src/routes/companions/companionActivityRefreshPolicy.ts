import type { Query } from "@tanstack/react-query";

export const COMPANION_ACTIVITY_NORMAL_POLL_MS = 5_000;
export const COMPANION_ACTIVITY_ERROR_BACKOFF_STEPS_MS = [30_000, 60_000, 120_000, 300_000] as const;

/**
 * Consecutive-failure backoff state for the shared companion-activity poll.
 * The caller owns the instance (useRef in the polling observer) so the state
 * lives exactly as long as the poller and cannot be double-counted by a second
 * observer on the same query key.
 */
export interface CompanionActivityRefreshState {
  consecutiveFailures: number;
  lastFailureAt: number;
  lastSuccessAt: number;
}

export function createCompanionActivityRefreshState(): CompanionActivityRefreshState {
  return {
    consecutiveFailures: 0,
    lastFailureAt: 0,
    lastSuccessAt: 0,
  };
}

/**
 * Interval for a given consecutive-failure level. Level 0 polls at the normal
 * cadence; each further failure climbs the ladder and level 4+ stays capped at
 * the last step.
 */
export function companionActivityFailureIntervalMs(consecutiveFailures: number): number {
  if (consecutiveFailures <= 0) {
    return COMPANION_ACTIVITY_NORMAL_POLL_MS;
  }
  const stepIndex = Math.min(
    consecutiveFailures - 1,
    COMPANION_ACTIVITY_ERROR_BACKOFF_STEPS_MS.length - 1,
  );
  return COMPANION_ACTIVITY_ERROR_BACKOFF_STEPS_MS[stepIndex];
}

/**
 * Resolves the next poll interval from a shared-query state snapshot and
 * records the success/failure transition into the caller-held state.
 *
 * Transitions are detected by comparing query timestamps against the
 * timestamps this state last observed, deliberately not via react-query's
 * built-in counters: the global config sets retry:false, where the retryer
 * never increments its per-attempt counter, and query.state.fetchFailureCount
 * is zeroed on every fetch start, so neither is a consecutive-failure count.
 * dataUpdatedAt/errorUpdatedAt are maintained unconditionally by the query
 * reducer for every finished fetch and are the reliable transition signal.
 *
 * When one invocation observes both timestamps advanced (batched dispatches),
 * the failure wins: erring toward a slower poll is the safe direction, and the
 * next success still resets the state. Repeated invocations with unchanged
 * timestamps are idempotent, so extra observer updates never climb the ladder.
 */
export function resolveCompanionActivityRefetchInterval(
  state: CompanionActivityRefreshState,
  queryState: Pick<Query["state"], "dataUpdatedAt" | "errorUpdatedAt">,
): number {
  if (queryState.errorUpdatedAt > state.lastFailureAt) {
    state.lastFailureAt = queryState.errorUpdatedAt;
    state.consecutiveFailures += 1;
  } else if (queryState.dataUpdatedAt > state.lastSuccessAt) {
    state.lastSuccessAt = queryState.dataUpdatedAt;
    state.consecutiveFailures = 0;
  }
  return companionActivityFailureIntervalMs(state.consecutiveFailures);
}
