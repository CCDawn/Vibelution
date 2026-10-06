import type { SessionStreamEvent } from "../api/types";

/**
 * Projection continuity gate for the session assistant-delta stream.
 *
 * Invariant pattern attribution (Apache-2.0): zai-org/ZCode
 * `conversationProjectionStore` — seq continuity gate, watermark resubscribe,
 * and optimistic-overlay reconciliation. This is a local adaptation for the
 * Vibelution SSE protocol, whose `assistant_delta.deltaSeq` is the frame's own
 * transport-continuity sequence and whose server coalesces stale queued frames
 * by design (a later frame always carries the full turn projection, never a
 * fragment).
 *
 * `deltaSeq` is deliberately independent of `assistant_delta.ledgerSeq` (the
 * journal watermark): mid-turn journal boundary appends (reasoning segment
 * commits, tool events) advance the ledger between applied frames, which made
 * a ledger-based gate misread dense streams as transport gaps. Coalesced
 * frames widen `deltaSeqFrom` to the oldest merged sequence, so a covered
 * range that starts beyond `lastAppliedSeq + 1` is the only true
 * transport-loss signature.
 *
 * Gate rules (deterministic, pure w.r.t. the tracked state):
 * - frames without a usable deltaSeq are applied unchanged (legacy payloads —
 *   prefer a slow ungated apply over stalling the stream);
 * - a new turnId re-baselines the gate (first frame of a turn always applies);
 * - `deltaSeq < lastAppliedSeq` is a stale/out-of-order regression → DROP;
 * - the covered range `[deltaSeqFrom, deltaSeq]` starting at or before
 *   `lastAppliedSeq + 1` is continuous (dense advance or designed coalescing)
 *   → APPLY and advance to `deltaSeq`;
 * - `deltaSeqFrom > lastAppliedSeq + 1` is a genuine transport gap → HOLD and
 *   recover from `watermark = lastAppliedSeq + 1` (single-flight, exponential
 *   backoff);
 * - an authoritative snapshot (session_initial / session_detail) rewrites the
 *   whole projection, so it re-baselines the gate (its ledgerSeq lives in a
 *   different sequence space and is informational here);
 * - a stream (re)open re-baselines the gate so the first post-reconnect frame
 *   applies unconditionally instead of staying stuck behind a pre-drop gap —
 *   this also covers a server restart, which resets the process-local
 *   deltaSeq counter.
 */

export type AssistantDeltaPayload = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

export type AssistantDeltaGateDecision =
  | { action: "apply"; seq: number; firstFrameOfTurn: boolean }
  | { action: "drop-stale"; seq: number; lastAppliedSeq: number }
  | { action: "hold-gap"; seq: number; lastAppliedSeq: number; watermark: number };

export type AssistantDeltaSeqGateInput = {
  turnId?: string;
  deltaSeq?: number;
  deltaSeqFrom?: number;
  /**
   * Present on real payloads (journal watermark) but intentionally ignored:
   * the ledger advances between frames by design and is not a continuity
   * signal. Kept in the input type so full frames can be passed verbatim.
   */
  ledgerSeq?: number;
};

export type SessionProjectionGate = {
  decide(payload: AssistantDeltaSeqGateInput): AssistantDeltaGateDecision;
  /**
   * An authoritative snapshot was applied: re-baseline the gate so the next
   * frame applies unconditionally. The journal seq argument is informational
   * only — authoritative snapshots live in the ledger sequence space, not the
   * delta sequence space.
   */
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
      const seq = normalizedSeq(payload.deltaSeq);
      if (seq <= 0) {
        // Legacy frames without delta bookkeeping keep the ungated apply:
        // prefer a slow ungated apply over stalling the stream.
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
      const coveredFrom = normalizedSeq(payload.deltaSeqFrom) || seq;
      if (coveredFrom > lastAppliedSeq + 1) {
        // The covered range starts beyond what was applied: sequences before
        // it were neither delivered nor coalesced — a genuine transport gap.
        // Hold (do not corrupt) and recover from the watermark.
        return { action: "hold-gap", seq, lastAppliedSeq, watermark: lastAppliedSeq + 1 };
      }
      lastAppliedSeq = seq;
      return { action: "apply", seq, firstFrameOfTurn: false };
    },
    noteAuthoritative(_seq) {
      // An authoritative snapshot rewrote the whole projection; the next
      // frame re-baselines. The journal seq is not comparable to deltaSeq.
      requireFreshTurnBaseline = true;
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
  /**
   * An authoritative snapshot was applied: the projection was rewritten from
   * the authority, so the episode retires. The journal seq argument is
   * informational only (recovery watermarks live in the delta sequence space).
   */
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
 * watermark); completion requires an authoritative snapshot application or a
 * stream reopen, which re-baselines the gate.
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
      // Any authoritative snapshot application rewrites the projection from
      // the authority, which heals whatever the gap hid; the numeric
      // watermark comparison is meaningless across sequence spaces.
      if (normalizedSeq(seq) > 0) {
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
