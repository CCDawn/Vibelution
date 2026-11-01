/**
 * Evidence gate for Launcher runtime-directory file hints.
 *
 * `fs.watch` on Windows (ReadDirectoryChangesW) frequently reports events with
 * `filename === null`, and the launcher runtime directory historically carried
 * high-frequency CLI bridge log writes. A null event used to fall through the
 * filename filter and trigger a full state refresh whose own logging then
 * re-triggered the next refresh — a self-exciting storm (measured 84,588
 * refreshes in 36h). The gate makes null events evidence-based:
 *
 * 1. A null event may only schedule a refresh when the stat signature of an
 *    actually observed state/port file really changed since the last sample.
 * 2. Even then, null events inside the refresh quiet window (a refresh that is
 *    running or just finished) are merged away — the in-flight refresh already
 *    samples the latest facts, and the periodic stat poll is the safety net.
 *
 * Named events for the observed files (`state.json`, `ports.json`) bypass the
 * gate: they are authoritative write evidence from the state owner itself.
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
