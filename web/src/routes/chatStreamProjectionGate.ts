import type { SessionStreamEvent } from "../api/types";

/**
 * Projection continuity gate for the session assistant-delta stream.
 *
 * Invariant pattern attribution (Apache-2.0): zai-org/ZCode
 * `conversationProjectionStore` — seq continuity gate, watermark resubscribe,
 * and optimistic-overlay reconciliation. This is a local adaptation for the
 * Vibelution SSE protocol, whose `assistant_delta.ledgerSeq` is the session
 * conversation ledger's watermark at publish time and whose server coalesces
 * stale queued frames by design (a later frame always carries the full turn
 * projection, never a fragment).
 *
 * Gate rules (deterministic, pure w.r.t. the tracked state):
 * - frames without a usable ledgerSeq are applied unchanged (legacy payloads);
 * - a new turnId re-baselines the gate (first frame of a turn always applies);
 * - `seq < lastAppliedSeq` is a stale/out-of-order regression → DROP;
 * - `seq === lastAppliedSeq` is a newer coalesced frame of the same ledger
 *   epoch (full turn projection) → APPLY;
 * - `seq === lastAppliedSeq + 1` is a dense ledger advance → APPLY;
 * - `seq > lastAppliedSeq + 1` is a sparse jump — the only client-visible
 *   signature of missed transport frames → HOLD and recover from
 *   `watermark = lastAppliedSeq + 1` (single-flight, exponential backoff);
 * - an authoritative snapshot (session_initial / session_detail ledgerSeq)
 *   that reaches the watermark re-baselines the gate and resumes the stream;
 * - a stream (re)open re-baselines the gate so the first post-reconnect frame
 *   applies unconditionally instead of staying stuck behind a pre-drop gap.
 */

export type AssistantDeltaPayload = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

export type AssistantDeltaGateDecision =
  | { action: "apply"; seq: number; firstFrameOfTurn: boolean }
  | { action: "drop-stale"; seq: number; lastAppliedSeq: number }
  | { action: "hold-gap"; seq: number; lastAppliedSeq: number; watermark: number };

export type AssistantDeltaSeqGateInput = {
  turnId?: string;
  ledgerSeq?: number;
};

export type SessionProjectionGate = {
  decide(payload: AssistantDeltaSeqGateInput): AssistantDeltaGateDecision;
  /** Re-baseline from an authoritative snapshot; completes recovery at the watermark. */
  noteAuthoritative(seq: number): void;
  /** A stream (re)open: next frame re-baselines instead of holding on a pre-drop gap. */
  noteStreamReopened(): void;
  /** A terminal turn boundary; the next turn re-baselines. */
  noteTurnBoundary(): void;
  readonly lastAppliedSeq: number;
  readonly turnId: string;
};

export function createAssistantDeltaSeqGate(): SessionProjectionGate {
  let lastAppliedSeq = 0;
  let turnId = "";
  let requireFreshTurnBaseline = false;

  return {
    get lastAppliedSeq() {
      return lastAppliedSeq;
    },
    get turnId() {
      return turnId;
    },
    decide(payload) {
      const incomingTurnId = String(payload.turnId ?? "").trim();
      const seq = normalizedSeq(payload.ledgerSeq);
      if (seq <= 0) {
        // Legacy frames without ledger bookkeeping keep today's ungated apply.
        return { action: "apply", seq: 0, firstFrameOfTurn: incomingTurnId !== turnId };
      }
      if (incomingTurnId !== turnId || requireFreshTurnBaseline) {
        turnId = incomingTurnId;
        lastAppliedSeq = seq;
        requireFreshTurnBaseline = false;
        return { action: "apply", seq, firstFrameOfTurn: true };
      }
      if (seq < lastAppliedSeq) {
        return { action: "drop-stale", seq, lastAppliedSeq };
      }
      if (seq === lastAppliedSeq || seq === lastAppliedSeq + 1) {
        lastAppliedSeq = seq;
        return { action: "apply", seq, firstFrameOfTurn: false };
      }
      // Sparse jump: hold (do not corrupt) and recover from the watermark.
      return { action: "hold-gap", seq, lastAppliedSeq, watermark: lastAppliedSeq + 1 };
    },
    noteAuthoritative(seq) {
      const authoritativeSeq = normalizedSeq(seq);
      if (authoritativeSeq <= 0) {
        return;
      }
      if (authoritativeSeq >= lastAppliedSeq) {
        lastAppliedSeq = authoritativeSeq;
      }
    },
    noteStreamReopened() {
      requireFreshTurnBaseline = true;
    },
    noteTurnBoundary() {
      requireFreshTurnBaseline = true;
    },
  };
}

function normalizedSeq(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) && numeric > 0 ? Math.floor(numeric) : 0;
}

/** Backoff ladder for watermark recovery: 200/400/800/1600ms capped at 5s. */
export const SESSION_STREAM_RECOVERY_BACKOFF_MS = [200, 400, 800, 1600, 5000] as const;

export const SESSION_STREAM_RECOVERY_MAX_ATTEMPTS = SESSION_STREAM_RECOVERY_BACKOFF_MS.length;

export function resolveSessionStreamRecoveryDelayMs(attempt: number): number {
  const index = Math.min(
    Math.max(0, Math.floor(attempt)),
    SESSION_STREAM_RECOVERY_BACKOFF_MS.length - 1,
  );
  return SESSION_STREAM_RECOVERY_BACKOFF_MS[index] ?? 5000;
}

export type SessionStreamRecoveryControllerOptions = {
  /**
   * Performs the actual watermark resubscribe: authoritative refetch + stream
   * reconnect. Called once per scheduled attempt.
   */
  requestRecovery: (input: { watermark: number; attempt: number }) => void;
  /** Timer injection for deterministic tests; defaults to window timers. */
  scheduleDelay?: (delayMs: number, callback: () => void) => () => void;
};

export type SessionStreamRecoveryState = {
  inFlight: boolean;
  attempt: number;
  watermark: number;
  singleFlightSuppressed: number;
};

export type SessionStreamRecoveryController = {
  /** Request recovery from a watermark; single-flight while an attempt is pending. */
  request(watermark: number): void;
  /** Authoritative progress at/above the watermark completes the recovery loop. */
  noteAuthoritative(seq: number): void;
  /** A stream reopen re-baselines the gate; a pending recovery loop is retired. */
  noteStreamReopened(): void;
  dispose(): void;
  state(): SessionStreamRecoveryState;
};

const noopCancel = () => undefined;

function defaultSchedule(delayMs: number, callback: () => void): () => void {
  if (typeof window === "undefined" || typeof window.setTimeout !== "function") {
    const timer = setTimeout(callback, delayMs);
    return () => clearTimeout(timer);
  }
  const timer = window.setTimeout(callback, delayMs);
  return () => window.clearTimeout(timer);
}

/**
 * Single-flight watermark recovery with exponential backoff. Recovery requests
 * that arrive while an attempt is pending are absorbed (they only raise the
 * watermark); completion requires an authoritative seq at/above the watermark
 * or a stream reopen, which re-baselines the gate.
 */
export function createSessionStreamRecoveryController(
  options: SessionStreamRecoveryControllerOptions,
): SessionStreamRecoveryController {
  const scheduleDelay = options.scheduleDelay ?? defaultSchedule;
  let inFlight = false;
  let attempt = 0;
  let watermark = 0;
  let singleFlightSuppressed = 0;
  let cancelTimer: () => void = noopCancel;

  const retireEpisode = () => {
    cancelTimer();
    cancelTimer = noopCancel;
    inFlight = false;
    attempt = 0;
    singleFlightSuppressed = 0;
  };

  const controller: SessionStreamRecoveryController = {
    request(nextWatermark) {
      const boundedWatermark = Math.max(1, Math.floor(nextWatermark) || 1);
      if (inFlight) {
        singleFlightSuppressed += 1;
        watermark = Math.max(watermark, boundedWatermark);
        return;
      }
      inFlight = true;
      watermark = boundedWatermark;
      const delayMs = resolveSessionStreamRecoveryDelayMs(attempt);
      cancelTimer = scheduleDelay(delayMs, () => {
        cancelTimer = noopCancel;
        const attemptNumber = attempt + 1;
        attempt = attemptNumber;
        inFlight = false;
        options.requestRecovery({ watermark, attempt: attemptNumber });
      });
    },
    noteAuthoritative(seq) {
      if (!inFlight) {
        return;
      }
      if (normalizedSeq(seq) >= watermark) {
        retireEpisode();
      }
    },
    noteStreamReopened() {
      if (!inFlight) {
        return;
      }
      retireEpisode();
    },
    dispose() {
      retireEpisode();
      watermark = 0;
    },
    state() {
      return { inFlight, attempt, watermark, singleFlightSuppressed };
    },
  };
  return controller;
}
