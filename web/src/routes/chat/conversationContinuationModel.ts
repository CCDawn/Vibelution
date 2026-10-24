import type { SessionContinuationExpectation } from "../../api/chat";
import type { SessionDetail } from "../../api/types";
import { activityCanContinue, resolveSessionActivity, sessionIsAtRest } from "../sessionActivityState";

/** UI eligibility only; native admission revalidates this snapshot atomically. */
export function resolveConversationContinuation(
  detail: SessionDetail | null | undefined,
  sessionId: string | null | undefined,
): SessionContinuationExpectation | null {
  if (!detail || !sessionId || detail.id !== sessionId || detail.readOnly || detail.agentDirectSessionMismatch || detail.provisionalTranscript || detail.selectedLightweight
    || detail.stopRequested || detail.archiveState?.status === "archived" || detail.queuedTurns?.length) return null;
  const turnId = detail.lastTurnTerminalTurnId?.trim();
  const headId = detail.activeLeafId?.trim();
  const agentId = detail.agentId?.trim();
  const ledgerSeq = detail.ledgerSeq;
  if (!turnId || !headId || !agentId || !Number.isSafeInteger(ledgerSeq) || Number(ledgerSeq) < 1) return null;
  if (detail.activeTurnId && detail.activeTurnId !== turnId) return null;
  if (!sessionIsAtRest(detail)) return null;
  const terminal = resolveSessionActivity(detail).reason;
  const iterationStopped = terminal === "failed_runtime"
    && detail.lastTurnError?.reasonCode === "iteration_limit_reached"
    && detail.lastTurnError.turnId === turnId;
  if (!activityCanContinue(terminal) && !iterationStopped) return null;
  return { turnId, headId, ledgerSeq: Number(ledgerSeq), agentId };
}

export function continuationSnapshotKey(snapshot: SessionContinuationExpectation): string {
  return JSON.stringify([snapshot.turnId, snapshot.headId, snapshot.ledgerSeq, snapshot.agentId]);
}
