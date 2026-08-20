import type { MainLineIntentSnapshot, MainLineQueueType } from "./commandQueue.js";
import type { MainLineObservation } from "./observation.js";

export type MainLineIdleReconcileInput = {
  intent: MainLineIntentSnapshot | null;
  observation: MainLineObservation;
  queueBusy?: boolean;
  windowOpen?: boolean;
};

/**
 * Crash-recovery reconcile for the main line. Persist desiredState, observe
 * with I1 projection, enqueue at most one compensating open/close when idle.
 * In-flight and matching states are left alone. Admission/backoff is I4a.
 */
export function reconcileMainLineIdle(input: MainLineIdleReconcileInput): MainLineQueueType | null {
  if (input.queueBusy || !input.intent) {
    return null;
  }
  const state = input.observation.lifecycleState;
  if (state === "starting" || state === "restarting" || state === "stopping") {
    return null;
  }
  const live = Boolean(
    input.observation.backendAlive
    || input.observation.backendListening
    || input.windowOpen,
  );
  if (input.intent.desiredState === "open" && state === "closed") {
    return "open";
  }
  if (input.intent.desiredState === "closed" && (state === "running" || state === "partial" || live)) {
    return "close";
  }
  return null;
}
