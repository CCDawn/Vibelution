export const RECONCILE_DEADLINE_MIN_DELAY_MS = 250;
export const RECONCILE_DEADLINE_MAX_DELAY_MS = 30_000;

export type ReconcileDeadlineScheduler = {
  schedule(nextReconcileAt: string | undefined, nowMs?: number): void;
  clear(): void;
};

export function clampReconcileDeadlineDelayMs(nextReconcileAt: string | undefined, nowMs = Date.now()): number | null {
  const raw = String(nextReconcileAt || "").trim();
  if (!raw) {
    return null;
  }
  const dueAt = Date.parse(raw);
  if (!Number.isFinite(dueAt)) {
    return null;
  }
  const delay = dueAt - nowMs;
  if (delay <= 0) {
    return RECONCILE_DEADLINE_MIN_DELAY_MS;
  }
  return Math.min(RECONCILE_DEADLINE_MAX_DELAY_MS, delay);
}

export function createReconcileDeadlineScheduler(input: {
  onDue: () => void;
  setTimeout?: typeof setTimeout;
  clearTimeout?: typeof clearTimeout;
}): ReconcileDeadlineScheduler {
  const scheduleTimeout = input.setTimeout ?? setTimeout;
  const cancelTimeout = input.clearTimeout ?? clearTimeout;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let scheduledAt = "";

  const clear = (): void => {
    if (timer !== null) {
      cancelTimeout(timer);
      timer = null;
    }
    scheduledAt = "";
  };

  return {
    schedule(nextReconcileAt, nowMs = Date.now()) {
      const raw = String(nextReconcileAt || "").trim();
      const delay = clampReconcileDeadlineDelayMs(raw, nowMs);
      if (delay === null) {
        clear();
        return;
      }
      if (timer !== null && scheduledAt === raw) {
        return;
      }
      if (timer !== null) {
        cancelTimeout(timer);
        timer = null;
      }
      scheduledAt = raw;
      timer = scheduleTimeout(() => {
        timer = null;
        scheduledAt = "";
        input.onDue();
      }, delay);
    },
    clear,
  };
}
