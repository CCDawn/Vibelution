/**
 * Mock conversation projection implementing the three ZCode invariants
 * (zai-org/ZCode conversationProjectionStore.ts, Apache-2.0 — pattern only;
 * this is a deterministic mock, no network):
 *
 * 1. seq continuity gate — a delta applies only when seq === lastAppliedSeq+1;
 *    duplicates (seq <= last) drop; gaps HOLD the delta instead of corrupting.
 * 2. gap recovery with watermark — on gap, issue a resubscribe from
 *    watermark = lastAppliedSeq+1, single-flight (one recovery at a time),
 *    exponential backoff 200/400/800/1600ms capped at 5s.
 * 3. optimistic overlay reconciliation — optimistic user echo + assistant
 *    prefix render immediately from an overlay; the authoritative snapshot
 *    reconciles them and the overlay is removed.
 */

export type ProjectionDecision =
  | { kind: "applied"; seq: number }
  | { kind: "dropped-duplicate"; seq: number }
  | { kind: "held-gap"; seq: number; watermark: number }
  | { kind: "recovery-start"; watermark: number }
  | { kind: "recovery-backoff"; attempt: number; delayMs: number }
  | { kind: "recovery-done"; through: number }
  | { kind: "overlay-added"; overlayId: string }
  | { kind: "overlay-reconciled"; overlayId: string };

export type ProjectionState = {
  text: string;
  lastAppliedSeq: number;
  watermark: number;
  recoveryInFlight: boolean;
  recoveryAttempt: number;
  heldCount: number;
  appliedSeqs: Array<{ seq: number; status: "applied" | "held" | "dropped" }>;
  overlayIds: string[];
  overlayCleared: boolean;
  naiveText: string;
};

export type ProjectionStore = {
  getState(): ProjectionState;
  subscribe(listener: () => void): () => void;
  applyDelta(seq: number, text: string): ProjectionDecision;
  /** Simulates the authoritative snapshot reply for a watermark resubscribe. */
  injectSnapshot(through: number, fillText: string): void;
  addOverlay(overlayId: string): ProjectionDecision;
  reconcileOverlay(overlayId: string): ProjectionDecision;
  reset(): void;
};

const BACKOFF_MS = [200, 400, 800, 1600, 5000];

export function createProjectionStore(): ProjectionStore {
  let state: ProjectionState = {
    text: "",
    lastAppliedSeq: 0,
    watermark: 1,
    recoveryInFlight: false,
    recoveryAttempt: 0,
    heldCount: 0,
    appliedSeqs: [],
    overlayIds: [],
    overlayCleared: false,
    naiveText: "",
  };
  const listeners = new Set<() => void>();
  const recoveryTimers = new Set<number>();

  const notify = () => {
    for (const listener of Array.from(listeners)) {
      listener();
    }
  };
  const setState = (patch: Partial<ProjectionState>) => {
    state = { ...state, ...patch };
    notify();
  };

  const clearRecoveryTimers = () => {
    for (const timer of recoveryTimers) {
      window.clearTimeout(timer);
    }
    recoveryTimers.clear();
  };

  const startRecovery = (watermark: number): ProjectionDecision => {
    if (state.recoveryInFlight) {
      // Single-flight: an in-flight recovery absorbs new gap requests.
      return { kind: "held-gap", seq: -1, watermark };
    }
    const attempt = state.recoveryAttempt;
    const delayMs = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 5000;
    setState({ recoveryInFlight: true, watermark });
    const decision: ProjectionDecision = { kind: "recovery-start", watermark };
    const timer = window.setTimeout(() => {
      recoveryTimers.delete(timer);
      // Mock server: a resubscribe from the watermark always succeeds with a
      // snapshot that fills the gap up to `watermark + 2` (deterministic).
      store.injectSnapshot(watermark + 2, "⟦snapshot " + watermark + ".." + (watermark + 2) + "⟧");
    }, delayMs);
    recoveryTimers.add(timer);
    return decision;
  };

  const store: ProjectionStore = {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    applyDelta(seq, text) {
      const last = state.lastAppliedSeq;
      let decision: ProjectionDecision;
      if (seq === last + 1) {
        decision = { kind: "applied", seq };
        const chip = { seq, status: "applied" as const };
        setState({
          text: state.text + text,
          naiveText: state.naiveText + text,
          lastAppliedSeq: seq,
          appliedSeqs: [...state.appliedSeqs, chip].slice(-48),
        });
        return decision;
      }
      if (seq <= last) {
        decision = { kind: "dropped-duplicate", seq };
        setState({
          appliedSeqs: [...state.appliedSeqs, { seq, status: "dropped" as const }].slice(-48),
        });
        return decision;
      }
      // seq > last + 1: gap.
      decision = { kind: "held-gap", seq, watermark: last + 1 };
      setState({
        heldCount: state.heldCount + 1,
        recoveryAttempt: state.recoveryInFlight ? state.recoveryAttempt : state.recoveryAttempt + 1,
        appliedSeqs: [...state.appliedSeqs, { seq, status: "held" as const }].slice(-48),
      });
      startRecovery(last + 1);
      return decision;
    },
    injectSnapshot(through, fillText) {
      const last = state.lastAppliedSeq;
      if (through <= last) {
        setState({ recoveryInFlight: false });
        return;
      }
      // Naive mode never held anything: text may already contain later deltas
      // out of order, which is exactly the corruption the gate prevents.
      setState({
        text: state.text + fillText,
        lastAppliedSeq: through,
        watermark: through + 1,
        recoveryInFlight: false,
        overlayCleared: state.overlayIds.length > 0,
        overlayIds: [],
      });
    },
    addOverlay(overlayId) {
      const decision: ProjectionDecision = { kind: "overlay-added", overlayId };
      setState({ overlayIds: [...state.overlayIds, overlayId], overlayCleared: false });
      return decision;
    },
    reconcileOverlay(overlayId) {
      const decision: ProjectionDecision = { kind: "overlay-reconciled", overlayId };
      setState({
        overlayIds: state.overlayIds.filter((id) => id !== overlayId),
        overlayCleared: true,
      });
      return decision;
    },
    reset() {
      clearRecoveryTimers();
      state = {
        text: "",
        lastAppliedSeq: 0,
        watermark: 1,
        recoveryInFlight: false,
        recoveryAttempt: 0,
        heldCount: 0,
        appliedSeqs: [],
        overlayIds: [],
        overlayCleared: false,
        naiveText: "",
      };
      notify();
    },
  };
  return store;
}

export function describeDecision(decision: ProjectionDecision): { line: string; tone: "ok" | "hold" | "err" | "dim" } {
  switch (decision.kind) {
    case "applied":
      return { line: `APPLY  seq=${decision.seq}`, tone: "ok" };
    case "dropped-duplicate":
      return { line: `DROP   seq=${decision.seq}（重复/乱序回退）`, tone: "err" };
    case "held-gap":
      return { line: `HOLD   seq=${decision.seq} 断档 → 水位=${decision.watermark}`, tone: "hold" };
    case "recovery-start":
      return { line: `RESUB  单飞恢复 from 水位=${decision.watermark}（退避 200ms 起）`, tone: "hold" };
    case "recovery-backoff":
      return { line: `BACKOFF 第 ${decision.attempt} 次，等 ${decision.delayMs}ms`, tone: "hold" };
    case "recovery-done":
      return { line: `RESUME 权威快照补齐 through=${decision.through}`, tone: "ok" };
    case "overlay-added":
      return { line: `OVERLAY +${decision.overlayId}（乐观显示）`, tone: "dim" };
    case "overlay-reconciled":
      return { line: `RECONCILE ${decision.overlayId} 被权威投影对账移除`, tone: "ok" };
  }
}
