/**
 * Evidence gate for Launcher state file-hint watch targets.
 *
 * `fs.watch` on Windows (ReadDirectoryChangesW) frequently reports events with
 * `filename === null`, and the watched directories all carry high-frequency
 * churn that is a state refresh's OWN side effect, never new evidence:
 *
 * - the launcher runtime directory carries the CLI bridge log and atomic
 *   state/port writes;
 * - `%LOCALAPPDATA%\Vibelution` carries the instance registry directory lock
 *   (`instances.json.lockdir` create/remove plus its `release-<pid>-<uuid>`
 *   marker), which every state refresh takes and releases while it
 *   reconciles the registry;
 * - `.git` carries `index` / `index.lock` rewrites that `git status` produces
 *   on stat drift during the very same refresh.
 *
 * A refresh that treats its own side effects as evidence schedules the next
 * refresh — a self-exciting storm (measured 84,588 refreshes in 36h at
 * 0.65/s, then again ~0.6/s through the lockdir loop after the first fix).
 * The gate makes every hint evidence-based:
 *
 * 1. Named events only count for an explicit per-target allowlist of files
 *    whose change proves an observed fact moved (state.json/ports.json,
 *    instances.json, HEAD/ORIG_HEAD/packed-refs). Everything else — lockdir
 *    lifecycle, temp files, sqlite -wal/-shm, git index — is ignored.
 * 2. A null event may only schedule a refresh when the stat signature of the
 *    target's observed files really changed since the last sample.
 * 3. Even then, null events inside the refresh quiet window (a refresh that
 *    is running or just finished) are merged away — the in-flight refresh
 *    already samples the latest facts, and the periodic stat poll is the
 *    safety net.
 */

export type LauncherStateFileHintGate = {
  /** Decide a null-filename event; true means a refresh hint may fire. */
  consumeNullFilenameEvent(): boolean;
  /** Record that a refresh started; null events inside the quiet window merge away. */
  markRefreshStarted(): void;
  /** Sample signatures for the periodic stat safety net; true when something changed. */
  consumeStatPoll(): boolean;
};

/** Null events within this window after a refresh started are treated as that refresh's own tail. */
export const LAUNCHER_STATE_NULL_EVENT_QUIET_MS = 8_000;

export function createLauncherStateFileHintGate(input: {
  observedPaths: readonly string[];
  statSignature: (path: string) => string;
  now?: () => number;
  quietMs?: number;
}): LauncherStateFileHintGate {
  const now = input.now ?? Date.now;
  const quietMs = input.quietMs ?? LAUNCHER_STATE_NULL_EVENT_QUIET_MS;
  const signatures = new Map<string, string>();
  for (const path of input.observedPaths) {
    signatures.set(path, input.statSignature(path));
  }
  let lastRefreshStartedAt = Number.NEGATIVE_INFINITY;

  const sampleChanged = (): boolean => {
    let changed = false;
    for (const path of input.observedPaths) {
      const next = input.statSignature(path);
      if (signatures.get(path) !== next) {
        signatures.set(path, next);
        changed = true;
      }
    }
    return changed;
  };

  return {
    consumeNullFilenameEvent() {
      // Sample first so a dropped hint cannot resurface later from the stat poll.
      if (!sampleChanged()) {
        return false;
      }
      if (now() - lastRefreshStartedAt < quietMs) {
        return false;
      }
      return true;
    },
    markRefreshStarted() {
      lastRefreshStartedAt = now();
    },
    consumeStatPoll() {
      return sampleChanged();
    },
  };
}

export type LauncherStateHintBackoff = {
  /** Debounce delay to use right now for a file_change hint schedule. */
  currentDelayMs(): number;
  /** Record an actual hint fire; escalates backoff when the sliding window breaches. */
  recordFire(): void;
  /** True while the current delay is escalated above the base debounce. */
  isEscalated(): boolean;
};

/** Sliding window for the file_change storm breaker. */
export const LAUNCHER_STATE_HINT_WINDOW_MS = 60_000;
/** More than this many file_change refreshes inside the window trips the breaker. */
export const LAUNCHER_STATE_HINT_WINDOW_LIMIT = 8;
export const LAUNCHER_STATE_HINT_BASE_DELAY_MS = 200;
export const LAUNCHER_STATE_HINT_MAX_DELAY_MS = 30_000;

/**
 * Storm breaker for file_change hints. The evidence gates above make each
 * hint legitimate in isolation, but an unknown churn source could still feed
 * the loop one legitimate-looking hint at a time. More than
 * LAUNCHER_STATE_HINT_WINDOW_LIMIT fires inside the sliding window doubles
 * the debounce (200ms → 400ms → … → 30s cap), warns once per episode, and
 * silently resets to the plain debounce after the window goes quiet.
 */
export function createLauncherStateHintBackoff(input: {
  now?: () => number;
  windowMs?: number;
  limit?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  onEscalate?: (fireCount: number, delayMs: number) => void;
}): LauncherStateHintBackoff {
  const now = input.now ?? Date.now;
  const windowMs = input.windowMs ?? LAUNCHER_STATE_HINT_WINDOW_MS;
  const limit = input.limit ?? LAUNCHER_STATE_HINT_WINDOW_LIMIT;
  const baseDelayMs = input.baseDelayMs ?? LAUNCHER_STATE_HINT_BASE_DELAY_MS;
  const maxDelayMs = input.maxDelayMs ?? LAUNCHER_STATE_HINT_MAX_DELAY_MS;
  let delayMs = baseDelayMs;
  let warned = false;
  let fires: number[] = [];

  const prune = (): number[] => {
    const t = now();
    fires = fires.filter((ts) => t - ts < windowMs);
    return fires;
  };

  const resetIfQuiet = (): void => {
    if (prune().length === 0 && delayMs !== baseDelayMs) {
      delayMs = baseDelayMs;
      warned = false;
    }
  };

  return {
    currentDelayMs() {
      resetIfQuiet();
      return delayMs;
    },
    isEscalated() {
      resetIfQuiet();
      return delayMs !== baseDelayMs;
    },
    recordFire() {
      const firesInWindow = prune();
      firesInWindow.push(now());
      if (firesInWindow.length > limit) {
        delayMs = Math.min(maxDelayMs, delayMs * 2);
        if (!warned) {
          warned = true;
          input.onEscalate?.(firesInWindow.length, delayMs);
        }
      }
    },
  };
}
