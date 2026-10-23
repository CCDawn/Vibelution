import type { SessionContinuationExpectation } from "../../api/chat";
import type { SessionDetail } from "../../api/types";
import { isBusyPhase } from "./chatCodingRouteViewModel";

const CONTINUABLE_TERMINALS = new Set(["stopped_by_user", "stopped", "cancelled", "aborted", "interrupted", "needs_continue", "paused_limit"]);

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
  if (isBusyPhase(detail.currentPhase)) return null;
  const terminal = String(detail.terminalReason || detail.lastTurnStatus || "").trim().toLowerCase();
  const iterationStopped = terminal === "failed_runtime"
    && detail.lastTurnError?.reasonCode === "iteration_limit_reached"
    && detail.lastTurnError.turnId === turnId;
  if (!CONTINUABLE_TERMINALS.has(terminal) && !iterationStopped) return null;
  return { turnId, headId, ledgerSeq: Number(ledgerSeq), agentId };
}

export function continuationSnapshotKey(snapshot: SessionContinuationExpectation): string {
  return JSON.stringify([snapshot.turnId, snapshot.headId, snapshot.ledgerSeq, snapshot.agentId]);
}
