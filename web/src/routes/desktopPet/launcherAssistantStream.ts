import { parseLauncherAssistantSessionEvent, type LauncherAssistantSessionEvent } from "../../api/launcherAssistant";
import type { SessionAssistantDeltaStreamEvent, SessionDetail, SessionTurnItem } from "../../api/types";
import {
  isActiveTurnSettledByDetail,
  mergeAssistantDeltaIntoActiveTurnLayer,
  reconcileActiveTurnLayerItemsWithMessages,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import { sessionStreamAppendBaseline } from "../chat/sessionStreamAppendBaseline";
import { createSessionStreamAppendReassembler } from "../chatSessionStreamProtocol";
import { mergeSessionDetailMessageWindowWithOutcome } from "../chatSessionState";
import { createAssistantDeltaSeqGate } from "../chatStreamProjectionGate";
import { hasTerminalCanonicalTurnOutcome } from "../chatTurnProtocol";

export { activeTurnLayerToConversationMessage } from "../chatActiveTurnLayer";

const sequence = (value: number | undefined) => Number.isSafeInteger(value) && (value ?? 0) > 0 ? value! : 0;

function messageTurnId(message: SessionDetail["messages"][number]): string {
  const id = String(message.metadata?.turnId || message.metadata?.turn_id
    || (message.role === "assistant" ? message.turnId : "")).trim();
  return id.startsWith("live:") ? id.slice(5) : id;
}

function detailItems(detail: SessionDetail | undefined, turnId: string): SessionTurnItem[] {
  return (detail?.messages ?? []).flatMap(message => message.role === "assistant"
    && message.metadata?.kind !== "session_active_turn_layer" && messageTurnId(message) === turnId
    ? message.turnItems ?? [] : []);
}

/** Assistant-window adapter of the ordinary chat stream. This owns only the
 * temporary active layer and decoder cursors; detail/Journal own the transcript.
 * Create one controller per leased assistant session, replacing it on identity
 * changes. Refetch detail when apply reports needsRefresh, then reconcile it.
 * Explicit reconcile marks a completed authority read, including a structurally
 * shared detail object; apply's optional cached detail is only a change hint. */
export function createLauncherAssistantStream(sessionId: string) {
  const decoder = createSessionStreamAppendReassembler();
  const gate = createAssistantDeltaSeqGate();
  let layer: ActiveTurnLayerState | undefined;
  let authority: SessionDetail | undefined;
  let lastDetailInput: SessionDetail | undefined;
  let recovering = false;
  let lastDeltaTurn = "";
  let lastDeltaSeq = 0;
  let ledgerWatermark = 0;
  let recoveryWatermark = 0;
  let connectionEpoch = 0;
  let epochRecovery = false;
  const retiredTurns = new Set<string>();

  function retire(turnId: string) {
    if (!turnId) return;
    retiredTurns.add(turnId);
    if (retiredTurns.size > 64) retiredTurns.delete(retiredTurns.values().next().value!);
  }

  function reconcile(detail: SessionDetail): ActiveTurnLayerState | undefined {
    if (detail.id !== sessionId) return layer;
    lastDetailInput = detail;
    const outcome = mergeSessionDetailMessageWindowWithOutcome(authority, detail);
    if (!outcome.authorityAccepted) return layer;
    authority = outcome.detail;
    const detailSeq = sequence(authority.ledgerSeq);
    ledgerWatermark = Math.max(ledgerWatermark, detailSeq);
    const coversLayer = !layer || !sequence(layer.ledgerSeq) || detailSeq >= layer.ledgerSeq;
    const nextTurn = String(authority.activeTurnId || "");
    if (layer && coversLayer && (isActiveTurnSettledByDetail(layer, authority)
      || nextTurn && nextTurn !== layer.turnId)) {
      retire(layer.turnId);
      layer = undefined;
      gate.noteTurnBoundary();
    } else {
      layer = reconcileActiveTurnLayerItemsWithMessages(layer, authority.messages);
    }
    const baselineTurn = layer?.turnId || nextTurn;
    decoder.rebase(sessionId, baselineTurn, sessionStreamAppendBaseline(
      sessionId, baselineTurn, detailItems(authority, baselineTurn), epochRecovery ? undefined : layer?.turnItems,
    ), !recovering);
    // A lagging same-turn snapshot may reconcile items but cannot release a
    // transport-loss hold or reset continuity beyond the state it contains.
    if (coversLayer && detailSeq >= recoveryWatermark) {
      recovering = false;
      epochRecovery = false;
      recoveryWatermark = 0;
      gate.noteAuthoritative(detailSeq);
    }
    return layer;
  }

  function apply(input: LauncherAssistantSessionEvent, detail?: SessionDetail) {
    const event = parseLauncherAssistantSessionEvent(input);
    if (!event || event.sessionId !== sessionId) return { layer, needsRefresh: false };
    const incomingEpoch = sequence(event.connectionEpoch);
    if (connectionEpoch > 0 && incomingEpoch < connectionEpoch) return { layer, needsRefresh: false };
    if (incomingEpoch > connectionEpoch) {
      connectionEpoch = incomingEpoch;
      lastDeltaTurn = "";
      lastDeltaSeq = 0;
      gate.noteStreamReopened();
      decoder.rebase(sessionId, "", []);
      recovering = true;
      epochRecovery = true;
      recoveryWatermark = sequence(event.ledgerSeq);
      // The detail passed alongside this event predates the observed new
      // connection. Only a subsequent authority read may release recovery.
      if (detail) lastDetailInput = detail;
      return { layer, needsRefresh: true };
    }
    if (detail && detail !== lastDetailInput) reconcile(detail);
    if (event.type !== "assistant_delta") {
      return { layer, needsRefresh: recovering || event.needsRefresh === true
        || ["session_detail", "session_initial", "session_journal_event", "stream_resume"].includes(event.type) };
    }
    if (event.needsRefresh || !event.turnId || !event.turnItems) {
      recovering = true;
      recoveryWatermark = Math.max(recoveryWatermark, sequence(event.ledgerSeq));
      return { layer, needsRefresh: true };
    }
    const payload = event as SessionAssistantDeltaStreamEvent;
    const incomingLedger = sequence(payload.ledgerSeq);
    const deltaSeq = sequence(payload.deltaSeq);
    // deltaSeq is transport order; ledgerSeq rejects old-turn replay. Neither
    // timestamp nor a fabricated item identity may replace those native facts.
    if (retiredTurns.has(payload.turnId) || incomingLedger > 0 && incomingLedger < ledgerWatermark
      || deltaSeq > 0 && lastDeltaSeq > 0 && deltaSeq <= lastDeltaSeq
        && (lastDeltaTurn === payload.turnId || incomingLedger <= ledgerWatermark)
      || authority?.messages.some(message => messageTurnId(message) === payload.turnId
        && message.metadata?.kind !== "session_active_turn_layer" && hasTerminalCanonicalTurnOutcome(message))) {
      return { layer, needsRefresh: false };
    }
    if (recovering) return { layer, needsRefresh: true };
    const decision = gate.decide(payload);
    if (decision.action === "drop-stale") return { layer, needsRefresh: false };
    if (decision.action === "hold-gap") {
      recovering = true;
      recoveryWatermark = Math.max(recoveryWatermark, incomingLedger);
      return { layer, needsRefresh: true };
    }
    // Seed from canonical native rows if the first IPC frame is an append.
    if (lastDeltaTurn !== payload.turnId) {
      decoder.rebase(sessionId, payload.turnId, detailItems(authority, payload.turnId));
    }
    const expanded = decoder.expand(payload);
    if (expanded.gaps.length) {
      recovering = true;
      recoveryWatermark = Math.max(recoveryWatermark, incomingLedger);
      return { layer, needsRefresh: true };
    }
    if (layer && layer.turnId !== payload.turnId) retire(layer.turnId);
    layer = mergeAssistantDeltaIntoActiveTurnLayer(layer, expanded.payload);
    layer = reconcileActiveTurnLayerItemsWithMessages(layer, authority?.messages);
    lastDeltaTurn = payload.turnId;
    lastDeltaSeq = deltaSeq;
    ledgerWatermark = Math.max(ledgerWatermark, incomingLedger);
    return { layer, needsRefresh: payload.done };
  }

  return { apply, reconcile };
}
