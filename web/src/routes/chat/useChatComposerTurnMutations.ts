import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useRef,
  type Dispatch,
  type SetStateAction,
} from "react";

import {
  editResubmitSessionMessage,
  listSessionQueuedTurns,
  regenerateSessionMessage,
  stopSessionTurn,
  submitSessionGuidance,
  submitSessionMessage,
  switchSessionHead,
} from "../../api/chat";
import { submitVirtualHumanConversationMessage } from "../../api/virtualHumanLife";
import { queryKeys } from "../../api/queryKeys";
import type {
  ConversationAttachment,
  SessionDetail,
  SessionGuidanceMode,
  SessionModelSelection,
  SessionQueuedTurn,
  SessionReferenceAttachment,
  SessionTurnAcceptedResponse,
} from "../../api/types";
import type { RuntimeSummary } from "../../api/types/runtime";
import type { TranslationKey } from "../../i18n/dictionary";
import { removeChatTurnFromRuntimeSummary } from "./chatActiveWorkCache";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";
import {
  bindActiveTurnLayerToTurnId,
  createOptimisticActiveTurnLayer,
  latestUserTurnId,
  settleActiveTurnLayerFromDetail,
  setActiveTurnLayerForSession,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import type { ActiveTurnLayersStore } from "./activeTurnLayersStore";
import {
  appendOptimisticUserMessage,
  applyOptimisticEditResubmit,
  applyOptimisticRegenerate,
  clearSessionDetailStopping,
  markOptimisticUserMessageAccepted,
  markSessionDetailRunning,
  markSessionDetailStopping,
  markSessionSummaryRunning,
  mergeSessionDetailMessageWindow,
  removeOptimisticUserMessage,
  type OptimisticUserMessageInput,
} from "../chatSessionState";
import { updateSessionSummaryCaches } from "../chatSessionIndexQuery";
import type { ChatEditTarget } from "../chatComposerState";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import {
  chatStreamPerformanceNowMs,
  describeChatSubmitError,
  isRunningPhase,
} from "./chatCodingRouteViewModel";
import {
  clearSessionImageAttachments,
  clearSessionReferenceAttachments,
  encodeUtf8Base64,
  optimisticTurnIdForSubmission,
  restoreSubmittedDraftIfComposerStillEmpty,
  sessionReferenceId,
  type ComposerAttachmentUploadOutcome,
  type ComposerImageAttachment,
} from "./chatComposerSubmitModel";
import { loadTurnStatusTailConfig } from "./turnStatusTailModel";
import {
  releaseSessionDraftRecoveryGuard,
  removeStoredSessionDraft,
  scheduleSessionDraftRecoverySave,
  type SessionDraftRecoveryGuard,
} from "./chatDraftPersistence";
import { appendStoredPromptHistoryEntry } from "../../components/conversation/conversationPromptHistory";
import { postSubmitTelemetry } from "./chatSubmitTelemetry";
import { removeOptimisticUserMessagePaint } from "./chatSessionPaintCache";
import { startUserAction, type UserActionTracker } from "../../app/userActionTelemetry";
import { isEditAcknowledged, rollbackEditResubmit } from "./chatEditResubmitState";
import {
  resolveStopOptimisticTarget,
  cancelCongestedQueriesForSessionStop,
  type StopTurnOptimisticContext,
} from "./chatStopTurnModel";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;

/**
 * Intentional optimistic-row removals must bypass the session detail query's
 * ``structuralSharing``. React Query runs ``query.options.structuralSharing``
 * on every data write (``Query.setData``, manual ``setQueryData`` included),
 * and the workbench registers its windowed UNION merge there
 * (``sessionDetailStructuralSharing``), so a removal updater is undone before
 * it lands: the merge resurrects the optimistic row from the previous data and
 * the row sticks on the timeline forever (multi-file upload allSettled blocked
 * batch residue). Updates survive that merge (same-id messages: later write
 * wins; top-level fields favor ``next``) — only message-array removals die.
 * Write through ``query.setState`` (which skips ``replaceData``) so removals
 * get replace semantics while every other write keeps merge semantics.
 */
export function removeOptimisticUserMessageFromCache(
  queryClient: QueryClient,
  sessionId: string,
  input: OptimisticUserMessageInput,
): void {
  removeOptimisticUserMessagePaint(sessionId, input);
  const query = queryClient
    .getQueryCache()
    .find<SessionDetail>({ queryKey: queryKeys.session(sessionId), exact: true });
  if (!query) {
    return;
  }
  const next = removeOptimisticUserMessage(query.state.data, input);
  if (next === query.state.data) {
    return;
  }
  query.setState({ data: next, dataUpdatedAt: Date.now() });
}

export function restoreSubmittedDraftAfterFailure(
  setSessionDrafts: Dispatch<SetStateAction<Record<string, string>>>,
  sessionId: string,
  content: string,
  recoveryGuard: SessionDraftRecoveryGuard | null | undefined,
) {
  // Persistence is a side effect and must stay outside React's replayable
  // functional updater. The guard rejects late failures after newer input.
  if (recoveryGuard && !scheduleSessionDraftRecoverySave(recoveryGuard, content)) {
    return;
  }
  setSessionDrafts((current) => restoreSubmittedDraftIfComposerStillEmpty(current, sessionId, content));
}

function sameSubmittedReferenceSnapshot(
  current: SessionReferenceAttachment,
  submitted: SessionReferenceAttachment,
): boolean {
  if (sessionReferenceId(current) !== sessionReferenceId(submitted)) {
    return false;
  }
  // A message reference's id names the source message, while its quote is the
  // actual payload. Preserve a re-quoted reference added during the request.
  if (current.kind === "message" || submitted.kind === "message") {
    return current.kind === submitted.kind
      && current.sourceSessionId === submitted.sourceSessionId
      && current.sourceMessageId === submitted.sourceMessageId
      && current.quote === submitted.quote;
  }
  return true;
}

function clearSubmittedReferenceSnapshot(
  current: Record<string, SessionReferenceAttachment[]>,
  sessionId: string,
  submittedReferences: readonly SessionReferenceAttachment[],
): Record<string, SessionReferenceAttachment[]> {
  if (!submittedReferences.length) {
    return current;
  }
  const existing = current[sessionId] ?? [];
  const remaining = existing.filter((reference) =>
    !submittedReferences.some((submitted) => sameSubmittedReferenceSnapshot(reference, submitted)),
  );
  if (remaining.length === existing.length) {
    return current;
  }
  if (!remaining.length) {
    return clearSessionReferenceAttachments(current, sessionId);
  }
  return { ...current, [sessionId]: remaining };
}

export type SubmitTurnVariables = {
  sessionId: string;
  clientSubmissionId: string;
  content: string;
  draftRecoveryGuard?: SessionDraftRecoveryGuard | null;
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  turnStatusTail?: ReturnType<typeof loadTurnStatusTailConfig>;
  attachmentIds?: string[];
  attachments?: ConversationAttachment[];
  composerAttachments?: ComposerImageAttachment[];
  restoreAttachmentsAfterFailure?: () => void;
  releaseComposerAttachmentOwners?: () => void;
  references?: SessionReferenceAttachment[];
  requestStartedAtMs: number;
  queuedBehindActiveTurn?: boolean;
  /** Set only when an error readback confirms this submission is the current running turn. */
  recoveredAcceptedTurnId?: string;
  /** One-shot per-turn model override; null/undefined follows the session default. */
  modelSelection?: SessionModelSelection | null;
};

type SubmitAcceptanceEvidence = "canonical_message" | "queued_turn" | "active_task";

type SubmitAcceptanceReadback = {
  evidence: SubmitAcceptanceEvidence | null;
  status: "cache_confirmed" | "readback_confirmed" | "not_found" | "readback_failed";
};

const SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS = 3_000;

function findSubmitAcceptanceEvidence(
  detail: SessionDetail | undefined,
  clientSubmissionId: string,
): SubmitAcceptanceEvidence | null {
  if (!detail || !clientSubmissionId) return null;
  if (detail.messages?.some((message) => (
    message.role === "user"
    && String(message.metadata?.clientSubmissionId ?? "").trim() === clientSubmissionId
    && message.metadata?.optimisticUserMessage !== true
  ))) {
    return "canonical_message";
  }
  if (detail.queuedTurns?.some((turn) => (
    String(turn.clientSubmissionId ?? "").trim() === clientSubmissionId
  ))) {
    return "queued_turn";
  }
  if (String(detail.activeTask?.metadata?.clientSubmissionId ?? "").trim() === clientSubmissionId) {
    return "active_task";
  }
  return null;
}

export function exactSubmitTurnId(detail: SessionDetail | undefined, clientSubmissionId: string): string {
  const canonicalUserMessage = [...(detail?.messages ?? [])].reverse().find((message) => (
    message.role === "user"
    && String(message.metadata?.clientSubmissionId ?? "").trim() === clientSubmissionId
    && message.metadata?.optimisticUserMessage !== true
  ));
  const rawTurnId = String(canonicalUserMessage?.metadata?.turnId ?? canonicalUserMessage?.metadata?.turn_id ?? "").trim();
  return rawTurnId.startsWith("live:") ? rawTurnId.slice("live:".length) : rawTurnId;
}

function exactAcceptedSubmitTurnId(
  detail: SessionDetail | undefined,
  clientSubmissionId: string,
  evidence: SubmitAcceptanceEvidence,
): string {
  if (evidence === "queued_turn") return "";
  const canonicalTurnId = exactSubmitTurnId(detail, clientSubmissionId);
  if (canonicalTurnId) return canonicalTurnId;
  if (evidence !== "active_task") return "";
  const task = detail?.activeTask;
  if (String(task?.metadata?.clientSubmissionId ?? "").trim() !== clientSubmissionId) return "";
  const taskTurnId = String(task?.metadata?.turnId ?? task?.metadata?.turn_id ?? "").trim();
  return taskTurnId.startsWith("live:") ? taskTurnId.slice("live:".length) : taskTurnId;
}

export function isCurrentRunningSessionTurn(
  detail: SessionDetail | undefined,
  sessionId: string,
  turnId: string,
): boolean {
  const normalizedTurnId = String(turnId || "").trim();
  if (!detail || String(detail.id || "").trim() !== sessionId || !normalizedTurnId) return false;
  const turnLayer = createOptimisticActiveTurnLayer({ sessionId, turnId: normalizedTurnId, accepted: true });
  if (turnLayer && !settleActiveTurnLayerFromDetail(turnLayer, detail)) return false;
  const phase = String(detail.currentPhase || detail.status || "").trim().toLowerCase();
  // Stop click optimistically changes the phase to "stopping" before the
  // deferred request can be sent. Keep that exact, still-busy turn eligible.
  if (!isRunningPhase(phase) && !(phase === "stopping" && detail.stopRequested)) return false;
  const activeTurnId = String(detail.activeTurnId || "").trim().replace(/^live:/, "");
  const activeTaskTurnId = String(
    detail.activeTask?.metadata?.turnId ?? detail.activeTask?.metadata?.turn_id ?? "",
  ).trim().replace(/^live:/, "");
  if (activeTurnId && activeTurnId !== normalizedTurnId) return false;
  if (activeTaskTurnId && activeTaskTurnId !== normalizedTurnId) return false;
  if (activeTurnId || activeTaskTurnId) return true;
  return latestUserTurnId(detail) === normalizedTurnId;
}

function reconcileAcceptedSubmitActiveTurnLayer(
  current: Record<string, ActiveTurnLayerState>,
  input: {
    sessionId: string;
    clientSubmissionId: string;
    turnId: string;
    queued: boolean;
    detail: SessionDetail | undefined;
    updatedAt: string;
  },
): Record<string, ActiveTurnLayerState> {
  const layer = current[input.sessionId];
  const submissionOwnsLayer = layer?.clientSubmissionId === input.clientSubmissionId;
  const turnOwnsLayer = Boolean(layer && input.turnId && layer.turnId === input.turnId);
  if (input.queued) {
    return submissionOwnsLayer
      ? setActiveTurnLayerForSession(current, input.sessionId, undefined)
      : current;
  }

  // An acknowledgement can omit its turn id. In that case the optimistic
  // layer still carries the exact submission identity and must stay visible.
  if (!input.turnId) {
    return current;
  }

  // A late receipt must not replace the layer for a later submission/turn.
  if (layer && !submissionOwnsLayer && !turnOwnsLayer) return current;
  const boundLayer = layer
    ? bindActiveTurnLayerToTurnId(layer, input.turnId)
    : undefined;
  const matchingLayer = boundLayer ?? createOptimisticActiveTurnLayer({
    sessionId: input.sessionId,
    turnId: input.turnId,
    clientSubmissionId: input.clientSubmissionId,
    updatedAt: input.updatedAt,
    accepted: true,
  });
  if (!matchingLayer) return current;
  if (!input.detail) {
    return setActiveTurnLayerForSession(current, input.sessionId, matchingLayer);
  }

  const unsettledLayer = settleActiveTurnLayerFromDetail(matchingLayer, input.detail);
  if (!unsettledLayer) {
    return setActiveTurnLayerForSession(current, input.sessionId, undefined);
  }

  // Preserve streamed output (including a terminal frame) that arrived before
  // the HTTP acknowledgement. The canonical detail path will retire it when
  // the transcript has committed the matching turn.
  if (boundLayer && (boundLayer.status === "completed" || boundLayer.status === "failed" || boundLayer.turnItems.length > 0)) {
    return setActiveTurnLayerForSession(current, input.sessionId, boundLayer);
  }
  if (!isCurrentRunningSessionTurn(input.detail, input.sessionId, input.turnId)) {
    return setActiveTurnLayerForSession(current, input.sessionId, undefined);
  }
  return setActiveTurnLayerForSession(current, input.sessionId, matchingLayer);
}

type AcceptedSubmitReadbackTask = {
  key: string;
  sessionId: string;
  clientSubmissionId: string;
  turnId: string;
  timer: ReturnType<typeof globalThis.setTimeout> | null;
  timeout: ReturnType<typeof globalThis.setTimeout> | null;
  controller: AbortController | null;
  unsubscribe: Array<() => void>;
  cancelled: boolean;
};

function retireAcceptedSubmitReadbackTask(
  tasks: Map<string, AcceptedSubmitReadbackTask>,
  task: AcceptedSubmitReadbackTask,
  abort = true,
): void {
  if (tasks.get(task.key) !== task) return;
  tasks.delete(task.key);
  task.cancelled = true;
  if (task.timer !== null) globalThis.clearTimeout(task.timer);
  if (task.timeout !== null) globalThis.clearTimeout(task.timeout);
  task.timer = null;
  task.timeout = null;
  if (abort) task.controller?.abort();
  task.controller = null;
  task.unsubscribe.splice(0).forEach((unsubscribe) => unsubscribe());
}

async function readbackSubmitAcceptance(
  queryClient: QueryClient,
  sessionId: string,
  clientSubmissionId: string,
): Promise<SubmitAcceptanceReadback> {
  const queryKey = queryKeys.session(sessionId);
  const cachedEvidence = findSubmitAcceptanceEvidence(
    queryClient.getQueryData<SessionDetail>(queryKey),
    clientSubmissionId,
  );
  if (cachedEvidence) {
    return { evidence: cachedEvidence, status: "cache_confirmed" };
  }

  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(
    () => controller.abort(),
    SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS,
  );
  try {
    const readback = await fetchSessionDetailWindow(sessionId, {
      includeSecondary: false,
      signal: controller.signal,
    });
    if (String(readback.id ?? "").trim() !== sessionId) {
      return { evidence: null, status: "not_found" };
    }
    queryClient.setQueryData<SessionDetail>(queryKey, (current) => {
      const currentLedgerSeq = current?.ledgerSeq;
      const readbackLedgerSeq = readback.ledgerSeq;
      if (
        current
        && typeof currentLedgerSeq === "number"
        && Number.isFinite(currentLedgerSeq)
        && typeof readbackLedgerSeq === "number"
        && Number.isFinite(readbackLedgerSeq)
        && currentLedgerSeq > readbackLedgerSeq
      ) {
        return current;
      }
      return mergeSessionDetailMessageWindow(current, readback);
    });
    const evidence = findSubmitAcceptanceEvidence(
      queryClient.getQueryData<SessionDetail>(queryKey) ?? readback,
      clientSubmissionId,
    ) ?? findSubmitAcceptanceEvidence(readback, clientSubmissionId);
    return evidence
      ? { evidence, status: "readback_confirmed" }
      : { evidence: null, status: "not_found" };
  } catch {
    // The POST's original error remains the user-facing failure if this
    // best-effort authority check also fails or is cancelled.
    return { evidence: null, status: "readback_failed" };
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}

type ChatSubmitAcceptedResponse = SessionTurnAcceptedResponse & {
  queued?: boolean;
  queueSequence?: number;
  /** Server timestamp for when the turn entered the session queue. */
  queuedAt?: string;
  /** Active turn id this queued turn waits behind (observability only). */
  queuedBehindTurnId?: string;
};

type ComposerAttachmentUploadFailure = Extract<ComposerAttachmentUploadOutcome, { status: "failed" }>;

export function isFailedUploadOutcome(outcome: ComposerAttachmentUploadOutcome): outcome is ComposerAttachmentUploadFailure {
  return outcome.status === "failed";
}

/**
 * A queued turn waiting this long without starting is surfaced to the user:
 * the drain depends on the running turn settling, so a stuck (ghost-running)
 * turn would otherwise leave the message queued forever with zero feedback
 * (defect ①).
 */
export const QUEUED_TURN_STUCK_HINT_MS = 90_000;
export const QUEUED_TURN_STUCK_CHECK_INTERVAL_MS = 15_000;

export function queuedTurnWaitingSinceMs(row: SessionQueuedTurn): number {
  const createdAt = Date.parse(String(row.createdAt || ""));
  const updatedAt = Date.parse(String(row.updatedAt || ""));
  // Resuming or editing re-queues the row. Time deliberately held in a pause
  // does not indicate a stalled drain; old rows still fall back to creation.
  return Number.isFinite(updatedAt) ? Math.max(Number.isFinite(createdAt) ? createdAt : updatedAt, updatedAt) : createdAt;
}

/** Queued rows that have waited beyond ``thresholdMs`` and are still waiting. */
export function queuedTurnsWaitingBeyondMs(
  rows: SessionQueuedTurn[] | undefined,
  nowMs: number,
  thresholdMs: number = QUEUED_TURN_STUCK_HINT_MS,
): SessionQueuedTurn[] {
  const list = Array.isArray(rows) ? rows : [];
  return list.filter((row) => {
    if (String(row.status || "queued") !== "queued") {
      return false;
    }
    const waitingSinceMs = queuedTurnWaitingSinceMs(row);
    if (!Number.isFinite(waitingSinceMs)) {
      return false;
    }
    return nowMs - waitingSinceMs >= thresholdMs;
  });
}

type ChatSubmitMutationContext = {
  telemetry: UserActionTracker;
};

type QueuedTurnWithdrawSnapshot = {
  row: SessionQueuedTurn;
  index: number;
};

/**
 * Rollback for an optimistically withdrawn queued turn: re-insert the row at
 * its pre-intent slot into the CURRENT rows instead of wholesale-restoring the
 * snapshot, so authoritative rows that landed while the DELETE was in flight
 * (a reorder, pause or steer rebase) are not clobbered. Mirrors
 * restoreOptimisticallyArchivedAgent in useChatAgentArchiveQueue.
 */
export function restoreQueuedTurnIntoRows(rows: SessionQueuedTurn[], snapshot: QueuedTurnWithdrawSnapshot): SessionQueuedTurn[] {
  if (rows.some((row) => row.id === snapshot.row.id)) {
    return rows;
  }
  const next = [...rows];
  next.splice(Math.max(0, Math.min(snapshot.index, next.length)), 0, snapshot.row);
  return next;
}

/**
 * Rollback for an optimistically reordered queue: recover the pre-drag order
 * while keeping current membership — rows authoritative state removed while
 * the PATCH was in flight stay removed, and rows added in the meantime stay
 * (at the tail).
 */
export function restoreQueuedTurnOrder(previousRows: SessionQueuedTurn[], currentRows: SessionQueuedTurn[]): SessionQueuedTurn[] {
  const previousIds = new Set(previousRows.map((row) => row.id));
  const appended = currentRows.filter((row) => !previousIds.has(row.id));
  const restored = previousRows.filter((row) => currentRows.some((current) => current.id === row.id));
  if (
    !appended.length
    && restored.length === currentRows.length
    && restored.every((row, index) => currentRows[index]?.id === row.id)
  ) {
    return currentRows;
  }
  return [...restored, ...appended];
}

export type EditResubmitVariables = {
  sessionId: string;
  messageId: string;
  baseMessageId?: string;
  clientSubmissionId: string;
  content: string;
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  turnStatusTail?: ReturnType<typeof loadTurnStatusTailConfig>;
  attachmentIds?: string[];
  /** Set only when an error readback confirms this edit is the current running turn. */
  recoveredAcceptedTurnId?: string;
};

/**
 * The edit-resubmit API rebuilds the target message's attachments from the
 * submitted ids alone, so the original artifacts must ride along with any new
 * composer uploads; a text-only edit would otherwise silently strip them.
 * Artifact ids resolve server-side against the session ledger metadata, so the
 * already-stored originals reattach without a re-upload.
 */
export function resolveEditCarryOverAttachmentIds(
  detail: SessionDetail | undefined,
  messageId: string,
): string[] {
  if (!detail) {
    return [];
  }
  const normalizedMessageId = String(messageId || "").trim();
  if (!normalizedMessageId) {
    return [];
  }
  const target = (detail.messages ?? []).find(
    (message) => String(message.id || "").trim() === normalizedMessageId,
  );
  if (!target || target.role !== "user") {
    return [];
  }
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const attachment of target.attachments ?? []) {
    const artifactId = String(attachment.artifactId || "").trim();
    if (!artifactId || seen.has(artifactId)) {
      continue;
    }
    seen.add(artifactId);
    ids.push(artifactId);
  }
  return ids;
}

export type RegenerateVariables = {
  sessionId: string;
  messageId: string;
  baseMessageId?: string;
  clientSubmissionId: string;
  content: string;
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  turnStatusTail?: ReturnType<typeof loadTurnStatusTailConfig>;
  recoveredAcceptedTurnId?: string;
};

export type SwitchHeadVariables = {
  sessionId: string;
  nodeId: string;
};

export type StopTurnVariables = {
  sessionId: string;
  turnId: string;
  deferredStop?: StopTurnOptimisticContext;
};

export type ChatComposerTurnMutations = {
  submitTurnMutation: UseMutationResult<ChatSubmitAcceptedResponse, Error, SubmitTurnVariables, unknown>;
  editResubmitMutation: UseMutationResult<SessionDetail, Error, EditResubmitVariables, unknown>;
  regenerateMutation: UseMutationResult<SessionDetail, Error, RegenerateVariables, unknown>;
  switchHeadMutation: UseMutationResult<SessionDetail, Error, SwitchHeadVariables, unknown>;
  stopTurnMutation: UseMutationResult<SessionDetail, Error, StopTurnVariables, unknown>;
  sessionGuidanceMutation: UseMutationResult<
    SessionDetail,
    Error,
    {
      sessionId: string;
      content: string;
      mode: SessionGuidanceMode;
      /** Set by queue steer: keep this row out of the paint until its DELETE rebases. */
      steeredQueuedTurnId?: string;
    },
    unknown
  >;
};

export type UseChatComposerTurnMutationsOptions = {
  queryClient: QueryClient;
  chatWorkspaceCache: ChatWorkspaceCache;
  activeSessionId?: string;
  activeTurnLayersStore?: Pick<ActiveTurnLayersStore, "getSnapshot" | "subscribe">;
  t: (key: TranslationKey) => string;
  describeError: (error: unknown, fallback: string) => string;
  syncSessionDetail: (detail: SessionDetail) => void;
  setActiveTurnLayersBySession: Dispatch<SetStateAction<Record<string, ActiveTurnLayerState>>>;
  setSessionDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setSessionImageAttachments: Dispatch<SetStateAction<Record<string, ComposerImageAttachment[]>>>;
  setSessionReferenceAttachments: Dispatch<SetStateAction<Record<string, SessionReferenceAttachment[]>>>;
  setSessionEditTargets: Dispatch<SetStateAction<Record<string, ChatEditTarget>>>;
  companionAgentId?: string;
};

/**
 * Direct-session turn mutations only (submit / edit-resubmit / stop / guidance).
 * Call early in ChatCodingRoute; does not open session streams.
 */
export function useChatComposerTurnMutations({
  queryClient,
  chatWorkspaceCache,
  activeSessionId,
  activeTurnLayersStore,
  t,
  describeError,
  syncSessionDetail,
  setActiveTurnLayersBySession,
  setSessionDrafts,
  setSessionComposerErrors,
  setSessionImageAttachments,
  setSessionReferenceAttachments,
  setSessionEditTargets,
  companionAgentId,
}: UseChatComposerTurnMutationsOptions): ChatComposerTurnMutations {
  const latestRegenerateSubmissionBySession = useRef(new Map<string, string>());
  const latestEditSubmissionBySession = useRef(new Map<string, string>());
  const acceptedSubmitReadbacksRef = useRef(new Map<string, AcceptedSubmitReadbackTask>());
  const activeSessionIdRef = useRef(String(activeSessionId || "").trim());
  const isMountedRef = useRef(false);

  const retireAcceptedSubmitReadback = useCallback((task: AcceptedSubmitReadbackTask, abort = true) => {
    retireAcceptedSubmitReadbackTask(acceptedSubmitReadbacksRef.current, task, abort);
  }, []);

  useEffect(() => {
    activeSessionIdRef.current = String(activeSessionId || "").trim();
    for (const task of acceptedSubmitReadbacksRef.current.values()) {
      if (task.sessionId !== activeSessionIdRef.current) {
        retireAcceptedSubmitReadback(task);
      }
    }
  }, [activeSessionId, retireAcceptedSubmitReadback]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      for (const task of acceptedSubmitReadbacksRef.current.values()) {
        retireAcceptedSubmitReadback(task);
      }
    };
  }, [retireAcceptedSubmitReadback]);

  const scheduleAcceptedSubmitReadback = useCallback((
    sessionId: string,
    clientSubmissionId: string,
    acceptedTurnId: string,
  ) => {
    if (
      !sessionId
      || !clientSubmissionId
      || companionAgentId
      || !isMountedRef.current
      || activeSessionIdRef.current !== sessionId
    ) return;

    const key = JSON.stringify([sessionId, clientSubmissionId]);
    const previousTask = acceptedSubmitReadbacksRef.current.get(key);
    if (previousTask) retireAcceptedSubmitReadback(previousTask);
    const task: AcceptedSubmitReadbackTask = {
      key,
      sessionId,
      clientSubmissionId,
      turnId: acceptedTurnId,
      timer: null,
      timeout: null,
      controller: null,
      unsubscribe: [],
      cancelled: false,
    };
    acceptedSubmitReadbacksRef.current.set(key, task);

    const projectionHasSettled = () => {
      if (activeSessionIdRef.current !== sessionId) return true;
      const detail = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId));
      const evidence = findSubmitAcceptanceEvidence(detail, clientSubmissionId);
      if (evidence === "canonical_message" || evidence === "queued_turn") return true;
      const turnId = task.turnId || exactSubmitTurnId(detail, clientSubmissionId);
      const layer = activeTurnLayersStore?.getSnapshot()[sessionId];
      if (layer) {
        const ownsLayer = layer.clientSubmissionId === clientSubmissionId
          || Boolean(turnId && layer.turnId === turnId);
        if (!ownsLayer) return true;
        if (layer.status === "completed" || layer.status === "failed") return true;
      }
      if (turnId) {
        const probe = createOptimisticActiveTurnLayer({
          sessionId,
          turnId,
          clientSubmissionId,
          accepted: true,
        });
        if (probe && !settleActiveTurnLayerFromDetail(probe, detail)) return true;
      }
      return false;
    };
    const retireIfSettled = () => {
      if (projectionHasSettled()) retireAcceptedSubmitReadback(task);
    };

    const sessionKey = queryKeys.session(sessionId);
    task.unsubscribe.push(queryClient.getQueryCache().subscribe((event) => {
      if (event.type !== "updated") return;
      const changedKey = event.query.queryKey;
      if (
        changedKey.length !== sessionKey.length
        || changedKey.some((part: unknown, index: number) => part !== sessionKey[index])
      ) return;
      retireIfSettled();
    }));
    if (activeTurnLayersStore) {
      task.unsubscribe.push(activeTurnLayersStore.subscribe(retireIfSettled));
    }

    task.timer = globalThis.setTimeout(() => {
      task.timer = null;
      if (task.cancelled || projectionHasSettled()) {
        retireAcceptedSubmitReadback(task);
        return;
      }
      const controller = new AbortController();
      task.controller = controller;
      const readbackStartedAtMs = chatStreamPerformanceNowMs();
      task.timeout = globalThis.setTimeout(
        () => controller.abort(),
        SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS,
      );
      void fetchSessionDetailWindow(sessionId, {
        includeSecondary: false,
        signal: controller.signal,
      }).then((readback) => {
        if (
          task.cancelled
          || controller.signal.aborted
          || activeSessionIdRef.current !== sessionId
          || String(readback.id || "").trim() !== sessionId
        ) {
          if (!task.cancelled && String(readback.id || "").trim() !== sessionId) {
            postSubmitTelemetry(
              "browser.chat_submit.accepted_projection_readback",
              "One-shot canonical projection readback returned a different session.",
              sessionId,
              {
                clientSubmissionId,
                result: "session_mismatch",
                timeoutMs: SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS,
                durationMs: Math.max(0, chatStreamPerformanceNowMs() - readbackStartedAtMs),
              },
              "warning",
            );
          }
          return;
        }
        // Remove this task's observers before writing the canonical snapshot;
        // that write must settle the projection rather than cancel itself.
        retireAcceptedSubmitReadback(task, false);
        syncSessionDetail(readback);
        const canonicalDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId)) ?? readback;
        const canonicalTurnId = exactSubmitTurnId(canonicalDetail, clientSubmissionId) || task.turnId;
        postSubmitTelemetry(
          "browser.chat_submit.accepted_projection_readback",
          "One-shot canonical projection readback completed.",
          sessionId,
          {
            clientSubmissionId,
            result: findSubmitAcceptanceEvidence(canonicalDetail, clientSubmissionId) ?? "missing_submission",
            timeoutMs: SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS,
            durationMs: Math.max(0, chatStreamPerformanceNowMs() - readbackStartedAtMs),
          },
          "info",
        );
        setActiveTurnLayersBySession((current) => reconcileAcceptedSubmitActiveTurnLayer(current, {
          sessionId,
          clientSubmissionId,
          turnId: canonicalTurnId,
          queued: false,
          detail: canonicalDetail,
          updatedAt: readback.updatedAt,
        }));
      }).catch(() => {
        // The HTTP receipt already established acceptance. This is a single
        // best-effort projection readback, never a retry or a second submit.
        if (!task.cancelled && activeSessionIdRef.current === sessionId) {
          const timedOut = controller.signal.aborted;
          postSubmitTelemetry(
            "browser.chat_submit.accepted_projection_readback",
            "One-shot canonical projection readback did not complete.",
            sessionId,
            {
              clientSubmissionId,
              result: timedOut ? "timeout" : "failed",
              timeoutMs: SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS,
              durationMs: Math.max(0, chatStreamPerformanceNowMs() - readbackStartedAtMs),
            },
            "warning",
          );
        }
      }).finally(() => {
        retireAcceptedSubmitReadback(task, false);
      });
    }, SUBMIT_ACCEPTANCE_READBACK_TIMEOUT_MS);
  }, [
    activeTurnLayersStore,
    companionAgentId,
    queryClient,
    retireAcceptedSubmitReadback,
    setActiveTurnLayersBySession,
    syncSessionDetail,
  ]);

  const submitTurnMutation = useMutation<
    ChatSubmitAcceptedResponse,
    Error,
    SubmitTurnVariables,
    ChatSubmitMutationContext
  >({
    // The backend is local: navigator.onLine must not silently retain a
    // submit for later reconnect. Attempt now so transport failure follows
    // the existing optimistic rollback and draft recovery path.
    networkMode: "always",
    mutationFn: async (
      {
        sessionId,
        clientSubmissionId,
        content,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail,
        attachmentIds,
        references,
        queuedBehindActiveTurn,
        modelSelection,
      }: SubmitTurnVariables,
    ) => {
      const resolvedTail = turnStatusTail ?? loadTurnStatusTailConfig(sessionId);
      postSubmitTelemetry(
        "browser.chat_submit.request_started",
        "Direct chat submit request started.",
        sessionId,
        {
          content,
          attachmentCount: attachmentIds?.length ?? 0,
          referenceCount: references?.length ?? 0,
          mentalModelEnabled,
          runtimeStatusEnabled,
          clientSubmissionId,
        },
      );
      const payload = {
        content,
        clientSubmissionId,
        contentUtf8Base64: encodeUtf8Base64(content),
        attachmentIds: attachmentIds ?? [],
        references: references ?? [],
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail: resolvedTail,
        modelSelection: modelSelection ?? undefined,
      };
      if (companionAgentId) {
        return submitVirtualHumanConversationMessage(companionAgentId, sessionId, payload);
      }
      return submitSessionMessage(sessionId, {
        ...payload,
        queueIfBusy: Boolean(queuedBehindActiveTurn),
      });
    },
    onMutate: async (variables) => {
      const telemetry = startUserAction("session_message_submit", {
        sessionId: variables.sessionId,
        clientSubmissionId: variables.clientSubmissionId,
        attachmentCount: variables.attachmentIds?.length ?? 0,
        referenceCount: variables.references?.length ?? 0,
      });
      postSubmitTelemetry(
        "browser.chat_submit.mutate_called",
        "Direct chat submit mutation started.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
          runtimeStatusEnabled: variables.runtimeStatusEnabled,
          clientSubmissionId: variables.clientSubmissionId,
        },
      );
      const createdAt = new Date().toISOString();
      if (!companionAgentId && !variables.queuedBehindActiveTurn) {
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(
            current,
            variables.sessionId,
            createOptimisticActiveTurnLayer({
              sessionId: variables.sessionId,
              turnId: optimisticTurnIdForSubmission("submit", variables.sessionId, createdAt),
              accepted: false,
              clientSubmissionId: variables.clientSubmissionId,
              updatedAt: createdAt,
            }),
          )
        );
      }
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detailState) =>
        variables.queuedBehindActiveTurn
          ? detailState
          : markSessionDetailRunning(appendOptimisticUserMessage(detailState, variables)),
      );
      updateSessionSummaryCaches(queryClient, (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
      if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
        window.requestAnimationFrame(() => {
          postSubmitTelemetry(
            "browser.chat_submit.optimistic_painted",
            "Optimistic user and Agent rows reached the next browser paint.",
            variables.sessionId,
            {
              clientSubmissionId: variables.clientSubmissionId,
              submitToOptimisticPaintMs: Math.max(
                0,
                Math.round(chatStreamPerformanceNowMs() - variables.requestStartedAtMs),
              ),
              activeStatusSource: "optimistic_submit",
            },
          );
        });
      }
      return { telemetry };
    },
    onSuccess: (acceptedTurn, variables, context) => {
      releaseSessionDraftRecoveryGuard(variables.draftRecoveryGuard);
      variables.releaseComposerAttachmentOwners?.();
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        clientSubmissionId: variables.clientSubmissionId,
        turnId: acceptedTurn.turnId,
        durationMs: Math.max(0, Math.round(chatStreamPerformanceNowMs() - variables.requestStartedAtMs)),
      });
      postSubmitTelemetry(
        "browser.chat_submit.accepted",
        "Direct chat submit was accepted by the backend.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
          clientSubmissionId: variables.clientSubmissionId,
          turnId: acceptedTurn.turnId,
          acceptedAt: acceptedTurn.acceptedAt,
          durationMs: Math.max(0, chatStreamPerformanceNowMs() - variables.requestStartedAtMs),
        },
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionImageAttachments((current) => {
        if (!variables.composerAttachments) return clearSessionImageAttachments(current, variables.sessionId);
        const submittedIds = new Set(variables.composerAttachments.map((attachment) => attachment.id));
        return { ...current, [variables.sessionId]: (current[variables.sessionId] ?? []).filter((attachment) => !submittedIds.has(attachment.id)) };
      });
      setSessionReferenceAttachments((current) => companionAgentId
        ? clearSessionReferenceAttachments(current, variables.sessionId)
        : clearSubmittedReferenceSnapshot(current, variables.sessionId, variables.references ?? []));
      // Backend accepted the turn: the sent prompt becomes ArrowUp-recallable.
      appendStoredPromptHistoryEntry(variables.content);
      const responseTurnId = String(acceptedTurn.turnId || "").trim();
      // A queued acceptance must be projected as "queued", never as
      // "sent/running": the turn did not start, it joined the session queue.
      const isQueuedAcceptance = Boolean(
        acceptedTurn.queued || String(acceptedTurn.queuedTurnId || "").trim(),
      );
      if (isQueuedAcceptance) {
        const queuedTurnId = String(acceptedTurn.queuedTurnId || "").trim();
        if (queuedTurnId) {
          // Optimistic queue projection: the row lands in the follow-up queue
          // bar immediately (from the response's queue facts); the
          // listSessionQueuedTurns rebase below refreshes the authoritative rows.
          const queuedAt = acceptedTurn.queuedAt || acceptedTurn.acceptedAt || new Date().toISOString();
          queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detailState) => {
            if (!detailState) {
              return detailState;
            }
            const rows = detailState.queuedTurns ?? [];
            if (rows.some((row) => row.id === queuedTurnId)) {
              return detailState;
            }
            const optimisticQueuedRow: SessionQueuedTurn = {
              id: queuedTurnId,
              position: acceptedTurn.queuePosition ?? rows.length + 1,
              status: "queued",
              content: variables.content,
              clientSubmissionId: variables.clientSubmissionId,
              createdAt: queuedAt,
              updatedAt: queuedAt,
            };
            return { ...detailState, queuedTurns: [...rows, optimisticQueuedRow] };
          });
        }
      } else {
        const currentDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
        const acceptedTurnId = responseTurnId
          || exactSubmitTurnId(currentDetail, variables.clientSubmissionId);
        queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detailState) => {
          const acceptedDetail = markOptimisticUserMessageAccepted(detailState, variables, acceptedTurnId);
          if (!acceptedTurnId || !isCurrentRunningSessionTurn(acceptedDetail, variables.sessionId, acceptedTurnId)) {
            // SSE may have committed this turn (or a later one) before the HTTP
            // receipt arrived. A receipt is acceptance evidence, not authority
            // to put a terminal/newer session back into running.
            return acceptedDetail;
          }
          const runningDetail = markSessionDetailRunning(acceptedDetail);
          return runningDetail ? { ...runningDetail, activeTurnId: acceptedTurnId } : runningDetail;
        });
      }
      const acceptedDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
      const acceptedTurnId = responseTurnId
        || exactSubmitTurnId(acceptedDetail, variables.clientSubmissionId);
      setActiveTurnLayersBySession((current) => reconcileAcceptedSubmitActiveTurnLayer(current, {
        sessionId: variables.sessionId,
        clientSubmissionId: variables.clientSubmissionId,
        turnId: acceptedTurnId,
        queued: isQueuedAcceptance,
        detail: acceptedDetail,
        updatedAt: acceptedTurn.acceptedAt,
      }));
      if (!isQueuedAcceptance) {
        scheduleAcceptedSubmitReadback(variables.sessionId, variables.clientSubmissionId, acceptedTurnId);
      }
      // The optimistic detail/index updates above already expose the accepted turn.
      // SSE owns authoritative reconciliation when available; the existing polling
      // fallback does the same without competing with the first model request.
      if (acceptedTurn.queuedTurnId) {
        void listSessionQueuedTurns(variables.sessionId)
          .then((rows) => {
            queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detailState) =>
              detailState ? { ...detailState, queuedTurns: rows } : detailState,
            );
          })
          .catch(() => undefined);
      }
    },
    onError: async (error, variables, context) => {
      // The Companion mutation targets the plugin mailbox; its acceptance
      // receipt is not represented by native Session detail or queued turns.
      // Keep the native readback/cache recovery limited to ordinary sessions.
      const readbackAcceptance = companionAgentId
        ? null
        : await readbackSubmitAcceptance(
          queryClient,
          variables.sessionId,
          variables.clientSubmissionId,
        );
      // SSE can confirm this exact ordinary-session submission while the
      // readback is pending. Recheck the newest cache after an unsuccessful
      // readback, including failures and cancellations, before restoring draft.
      const lateCacheEvidence = readbackAcceptance && !readbackAcceptance.evidence
        ? findSubmitAcceptanceEvidence(
          queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId)),
          variables.clientSubmissionId,
        )
        : null;
      const acceptance = readbackAcceptance
        ? lateCacheEvidence
          ? { evidence: lateCacheEvidence, status: "cache_confirmed" as const }
          : readbackAcceptance
        : null;
      if (acceptance?.evidence) {
        releaseSessionDraftRecoveryGuard(variables.draftRecoveryGuard);
        variables.releaseComposerAttachmentOwners?.();
        if (acceptance.evidence === "canonical_message" || acceptance.evidence === "queued_turn") {
          removeOptimisticUserMessageFromCache(queryClient, variables.sessionId, variables);
        }
        setSessionComposerErrors((current) => ({
          ...current,
          [variables.sessionId]: "",
        }));
        setSessionImageAttachments((current) => {
          if (!variables.composerAttachments) return clearSessionImageAttachments(current, variables.sessionId);
          const submittedIds = new Set(variables.composerAttachments.map((attachment) => attachment.id));
          return {
            ...current,
            [variables.sessionId]: (current[variables.sessionId] ?? []).filter((attachment) => !submittedIds.has(attachment.id)),
          };
        });
        setSessionReferenceAttachments((current) =>
          clearSubmittedReferenceSnapshot(current, variables.sessionId, variables.references ?? []));
        const acceptedDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
        const recoveredTurnId = exactAcceptedSubmitTurnId(
          acceptedDetail,
          variables.clientSubmissionId,
          acceptance.evidence,
        );
        if (isCurrentRunningSessionTurn(acceptedDetail, variables.sessionId, recoveredTurnId)) {
          variables.recoveredAcceptedTurnId = recoveredTurnId;
        }
        setActiveTurnLayersBySession((current) => {
          const layer = current[variables.sessionId];
          if (layer?.clientSubmissionId !== variables.clientSubmissionId) return current;
          if (acceptance.evidence === "queued_turn") {
            return setActiveTurnLayerForSession(current, variables.sessionId, undefined);
          }
          const rawTaskTurnId = acceptance.evidence === "active_task"
            ? String(acceptedDetail?.activeTask?.metadata?.turnId ?? acceptedDetail?.activeTask?.metadata?.turn_id ?? "").trim()
            : "";
          const turnId = exactSubmitTurnId(acceptedDetail, variables.clientSubmissionId) || rawTaskTurnId;
          const boundLayer = bindActiveTurnLayerToTurnId(layer, turnId);
          const unsettledLayer = settleActiveTurnLayerFromDetail(boundLayer, acceptedDetail);
          if (!unsettledLayer) {
            return setActiveTurnLayerForSession(current, variables.sessionId, undefined);
          }
          return setActiveTurnLayerForSession(current, variables.sessionId, {
            ...unsettledLayer,
            processStage: unsettledLayer.processStage === "sending"
              ? "user_submit"
              : unsettledLayer.processStage,
          });
        });
        appendStoredPromptHistoryEntry(variables.content);
        context?.telemetry?.succeeded({
          sessionId: variables.sessionId,
          clientSubmissionId: variables.clientSubmissionId,
          acceptanceEvidence: acceptance.evidence,
          confirmation: acceptance.status,
          requestReturnedError: true,
          durationMs: Math.max(0, Math.round(chatStreamPerformanceNowMs() - variables.requestStartedAtMs)),
        });
        postSubmitTelemetry(
          "browser.chat_submit.accepted_after_request_error",
          "The request reported an error after an exact accepted submission was confirmed.",
          variables.sessionId,
          {
            clientSubmissionId: variables.clientSubmissionId,
            durationMs: Math.max(0, chatStreamPerformanceNowMs() - variables.requestStartedAtMs),
            error,
          },
          "warning",
        );
        return;
      }
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        clientSubmissionId: variables.clientSubmissionId,
        durationMs: Math.max(0, Math.round(chatStreamPerformanceNowMs() - variables.requestStartedAtMs)),
      });
      postSubmitTelemetry(
        "browser.chat_submit.request_failed",
        "Direct chat submit failed and backend acceptance could not be confirmed.",
        variables.sessionId,
        {
          content: variables.content,
          attachmentCount: variables.attachmentIds?.length ?? 0,
          referenceCount: variables.references?.length ?? 0,
          mentalModelEnabled: variables.mentalModelEnabled,
          clientSubmissionId: variables.clientSubmissionId,
          durationMs: Math.max(0, chatStreamPerformanceNowMs() - variables.requestStartedAtMs),
          ...(acceptance ? { acceptanceReadback: acceptance.status } : {}),
          error,
        },
        "error",
      );
      removeOptimisticUserMessageFromCache(queryClient, variables.sessionId, variables);
      variables.restoreAttachmentsAfterFailure?.();
      if (!variables.queuedBehindActiveTurn) {
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(current, variables.sessionId, undefined)
        );
      }
      restoreSubmittedDraftAfterFailure(
        setSessionDrafts,
        variables.sessionId,
        variables.content,
        variables.draftRecoveryGuard,
      );
      setSessionComposerErrors((current) => ({
        ...current,
        // Classified human copy (e.g. 409 -> "a turn is already generating");
        // the raw error is reported through telemetry above, not the composer.
        [variables.sessionId]: describeChatSubmitError(error, t, t("submitFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const editResubmitMutation = useMutation({
    mutationKey: ["session_edit_resubmit"],
    mutationFn: async (
      {
        sessionId,
        messageId,
        baseMessageId,
        clientSubmissionId,
        content,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail,
        attachmentIds,
      }: EditResubmitVariables,
    ) =>
      editResubmitSessionMessage(sessionId, {
        messageId,
        ...(baseMessageId ? { baseMessageId } : {}),
        clientSubmissionId,
        content,
        contentUtf8Base64: encodeUtf8Base64(content),
        attachmentIds: attachmentIds ?? [],
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail: turnStatusTail ?? loadTurnStatusTailConfig(sessionId),
      }),
    onMutate: async (variables) => {
      latestEditSubmissionBySession.current.set(variables.sessionId, variables.clientSubmissionId);
      const telemetry = startUserAction("session_edit_resubmit", {
        sessionId: variables.sessionId,
        messageId: variables.messageId,
        clientSubmissionId: variables.clientSubmissionId,
        contentLength: variables.content.length,
      });
      const sessionKey = queryKeys.session(variables.sessionId);
      await queryClient.cancelQueries({ queryKey: sessionKey, exact: true });
      const previousDetail = queryClient.getQueryData<SessionDetail>(sessionKey);
      const createdAt = new Date().toISOString();
      setActiveTurnLayersBySession((current) =>
        setActiveTurnLayerForSession(
          current,
          variables.sessionId,
          createOptimisticActiveTurnLayer({
            sessionId: variables.sessionId,
            turnId: optimisticTurnIdForSubmission("edit", variables.sessionId, createdAt),
            clientSubmissionId: variables.clientSubmissionId,
            updatedAt: createdAt,
          }),
        )
      );
      // Immediately hide the superseded tail; the edit marker blocks stale
      // detail/SSE/paint merges until the authoritative branch arrives.
      queryClient.setQueryData<SessionDetail>(sessionKey, (detailState) =>
        applyOptimisticEditResubmit(detailState, {
          messageId: variables.messageId,
          content: variables.content,
          clientSubmissionId: variables.clientSubmissionId,
        }),
      );
      updateSessionSummaryCaches(queryClient, (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
      return { previousDetail, telemetry };
    },
    onSuccess: (nextDetail, variables, context) => {
      if (latestEditSubmissionBySession.current.get(variables.sessionId) !== variables.clientSubmissionId) return;
      const currentDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
      if (currentDetail?.editResubmitProtection
        && currentDetail.editResubmitProtection.clientSubmissionId !== variables.clientSubmissionId) return;
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        messageId: variables.messageId,
        turnId: exactSubmitTurnId(nextDetail, variables.clientSubmissionId),
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      removeStoredSessionDraft(variables.sessionId);
      setSessionImageAttachments((current) => clearSessionImageAttachments(current, variables.sessionId));
      setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, variables.sessionId));
      setSessionEditTargets((current) => {
        const { [variables.sessionId]: _removed, ...remaining } = current;
        return remaining;
      });
      syncSessionDetail(nextDetail);
      // The HTTP response can arrive after SSE has already painted the
      // accepted turn.  Read the merged cache after sync instead of using the
      // response snapshot: a late running snapshot must not rebuild a fresh
      // layer over terminal/output that belongs to this submission.
      const syncedDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId)) ?? nextDetail;
      const acceptedTurnId = exactSubmitTurnId(syncedDetail, variables.clientSubmissionId)
        || exactSubmitTurnId(nextDetail, variables.clientSubmissionId);
      reconcileResubmittedTurnLayer(variables, syncedDetail, acceptedTurnId);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: async (error, variables, context) => {
      if (latestEditSubmissionBySession.current.get(variables.sessionId) !== variables.clientSubmissionId) return;
      const readback = await readbackSubmitAcceptance(queryClient, variables.sessionId, variables.clientSubmissionId);
      // SSE or a later edit can arrive while the bounded authority check runs.
      const currentDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
      if (latestEditSubmissionBySession.current.get(variables.sessionId) !== variables.clientSubmissionId) return;
      const evidence = findSubmitAcceptanceEvidence(currentDetail, variables.clientSubmissionId) ?? readback.evidence;
      if (evidence) {
        const acceptedTurnId = exactAcceptedSubmitTurnId(currentDetail, variables.clientSubmissionId, evidence);
        if (isCurrentRunningSessionTurn(currentDetail, variables.sessionId, acceptedTurnId)) {
          variables.recoveredAcceptedTurnId = acceptedTurnId;
        }
        reconcileResubmittedTurnLayer(variables, currentDetail, acceptedTurnId);
        setSessionComposerErrors((current) => ({ ...current, [variables.sessionId]: "" }));
        context?.telemetry?.succeeded({
          sessionId: variables.sessionId,
          messageId: variables.messageId,
          turnId: acceptedTurnId,
          acceptanceReadback: readback.status,
        });
        void chatWorkspaceCache.afterSessionChanged();
        return;
      }
      const guard = currentDetail?.editResubmitProtection;
      if (isEditAcknowledged(currentDetail, variables.clientSubmissionId)
        || (guard && (guard.clientSubmissionId !== variables.clientSubmissionId || guard.phase === "accepted"))) return;
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        messageId: variables.messageId,
      });
      const previousDetail = context && typeof context === "object" && "previousDetail" in context
        ? (context as { previousDetail?: SessionDetail }).previousDetail
        : undefined;
      if (previousDetail && guard) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (current) =>
          rollbackEditResubmit(current, previousDetail, variables.clientSubmissionId));
      } else if (!currentDetail) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId), exact: true });
      }
      setActiveTurnLayersBySession((current) =>
        current[variables.sessionId]?.clientSubmissionId === variables.clientSubmissionId
          ? setActiveTurnLayerForSession(current, variables.sessionId, undefined)
          : current,
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("editResubmitFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  function reconcileResubmittedTurnLayer(
    variables: Pick<RegenerateVariables, "sessionId" | "clientSubmissionId">,
    acceptedDetail: SessionDetail | undefined,
    acceptedTurnId: string,
  ) {
    setActiveTurnLayersBySession((current) => {
      const layer = current[variables.sessionId];
      const ownsLayer = layer?.clientSubmissionId === variables.clientSubmissionId
        || Boolean(layer && acceptedTurnId && layer.turnId === acceptedTurnId);
      // A later submission or streamed turn must keep its own layer.
      if (layer && !ownsLayer) return current;
      if (layer && (layer.status === "completed" || layer.status === "failed" || layer.turnItems.length > 0)) {
        return current;
      }
      if (!isCurrentRunningSessionTurn(acceptedDetail, variables.sessionId, acceptedTurnId)) {
        return setActiveTurnLayerForSession(current, variables.sessionId, undefined);
      }
      return setActiveTurnLayerForSession(current, variables.sessionId,
        bindActiveTurnLayerToTurnId(layer, acceptedTurnId) ?? createOptimisticActiveTurnLayer({
          sessionId: variables.sessionId,
          turnId: acceptedTurnId,
          clientSubmissionId: variables.clientSubmissionId,
          updatedAt: acceptedDetail?.updatedAt,
          accepted: true,
        }));
    });
  }

  const regenerateMutation = useMutation({
    mutationKey: ["session_regenerate"],
    mutationFn: async (
      {
        sessionId,
        messageId,
        baseMessageId,
        clientSubmissionId,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail,
      }: RegenerateVariables,
    ) =>
      regenerateSessionMessage(sessionId, {
        messageId,
        ...(baseMessageId ? { baseMessageId } : {}),
        clientSubmissionId,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail: turnStatusTail ?? loadTurnStatusTailConfig(sessionId),
      }),
    onMutate: async (variables) => {
      latestRegenerateSubmissionBySession.current.set(variables.sessionId, variables.clientSubmissionId);
      const telemetry = startUserAction("session_regenerate", {
        sessionId: variables.sessionId,
        messageId: variables.messageId,
        clientSubmissionId: variables.clientSubmissionId,
      });
      const sessionKey = queryKeys.session(variables.sessionId);
      await queryClient.cancelQueries({ queryKey: sessionKey, exact: true });
      const previousDetail = queryClient.getQueryData<SessionDetail>(sessionKey);
      const createdAt = new Date().toISOString();
      setActiveTurnLayersBySession((current) =>
        setActiveTurnLayerForSession(
          current,
          variables.sessionId,
          createOptimisticActiveTurnLayer({
            sessionId: variables.sessionId,
            turnId: optimisticTurnIdForSubmission("edit", variables.sessionId, createdAt),
            clientSubmissionId: variables.clientSubmissionId,
            updatedAt: createdAt,
          }),
        )
      );
      // Keep the journal branch visible while waiting for the accepted snapshot.
      queryClient.setQueryData<SessionDetail>(sessionKey, (detailState) =>
        applyOptimisticRegenerate(detailState, { messageId: variables.messageId }),
      );
      updateSessionSummaryCaches(queryClient, (sessions) =>
        markSessionSummaryRunning(sessions, variables.sessionId),
      );
      return { previousDetail, telemetry };
    },
    onSuccess: (nextDetail, variables, context) => {
      if (latestRegenerateSubmissionBySession.current.get(variables.sessionId) !== variables.clientSubmissionId) return;
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        messageId: variables.messageId,
        turnId: exactSubmitTurnId(nextDetail, variables.clientSubmissionId),
      });
      setSessionComposerErrors((current) => ({ ...current, [variables.sessionId]: "" }));
      syncSessionDetail(nextDetail);
      // A newer SSE snapshot may already own the cache when HTTP arrives.
      const syncedDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId)) ?? nextDetail;
      const acceptedTurnId = exactSubmitTurnId(syncedDetail, variables.clientSubmissionId)
        || exactSubmitTurnId(nextDetail, variables.clientSubmissionId);
      reconcileResubmittedTurnLayer(variables, syncedDetail, acceptedTurnId);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: async (error, variables, context) => {
      if (latestRegenerateSubmissionBySession.current.get(variables.sessionId) !== variables.clientSubmissionId) return;
      const readback = await readbackSubmitAcceptance(queryClient, variables.sessionId, variables.clientSubmissionId);
      const currentDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId));
      const evidence = findSubmitAcceptanceEvidence(currentDetail, variables.clientSubmissionId) ?? readback.evidence;
      if (latestRegenerateSubmissionBySession.current.get(variables.sessionId) !== variables.clientSubmissionId) return;
      if (evidence) {
        const acceptedTurnId = exactAcceptedSubmitTurnId(currentDetail, variables.clientSubmissionId, evidence);
        if (isCurrentRunningSessionTurn(currentDetail, variables.sessionId, acceptedTurnId)) {
          variables.recoveredAcceptedTurnId = acceptedTurnId;
        }
        reconcileResubmittedTurnLayer(variables, currentDetail, acceptedTurnId);
        setSessionComposerErrors((current) => ({ ...current, [variables.sessionId]: "" }));
        context?.telemetry?.succeeded({
          sessionId: variables.sessionId,
          messageId: variables.messageId,
          turnId: acceptedTurnId,
          acceptanceReadback: readback.status,
        });
        void chatWorkspaceCache.afterSessionChanged();
        return;
      }
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        messageId: variables.messageId,
      });
      const previousDetail = context && typeof context === "object" && "previousDetail" in context
        ? (context as { previousDetail?: SessionDetail }).previousDetail
        : undefined;
      if (previousDetail) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), previousDetail);
      } else {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId), exact: true });
      }
      setActiveTurnLayersBySession((current) =>
        current[variables.sessionId]?.clientSubmissionId === variables.clientSubmissionId
          ? setActiveTurnLayerForSession(current, variables.sessionId, undefined)
          : current,
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("regenerateFailed")),
      }));
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const switchHeadMutation = useMutation({
    mutationFn: async ({ sessionId, nodeId }: SwitchHeadVariables) =>
      switchSessionHead(sessionId, { nodeId }),
    onMutate: async (variables) => {
      const telemetry = startUserAction("session_switch_head", {
        sessionId: variables.sessionId,
        nodeId: variables.nodeId,
      });
      const sessionKey = queryKeys.session(variables.sessionId);
      await queryClient.cancelQueries({ queryKey: sessionKey, exact: true });
      const previousDetail = queryClient.getQueryData<SessionDetail>(sessionKey);
      return { previousDetail, telemetry };
    },
    onSuccess: (nextDetail, variables, context) => {
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        nodeId: variables.nodeId,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        nodeId: variables.nodeId,
      });
      const previousDetail = context && typeof context === "object" && "previousDetail" in context
        ? (context as { previousDetail?: SessionDetail }).previousDetail
        : undefined;
      if (previousDetail) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), previousDetail);
      } else {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(variables.sessionId), exact: true });
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("switchBranchFailed")),
      }));
    },
  });

  const stopTurnMutation = useMutation({
    mutationFn: async ({ sessionId, turnId }: StopTurnVariables) =>
      stopSessionTurn(sessionId, turnId),
    onMutate: async (variables: StopTurnVariables) => {
      const telemetry = startUserAction("session_turn_stop", {
        sessionId: variables.sessionId,
        turnId: variables.turnId,
      });
      // Abort congested in-flight queries without waiting for them: the stop
      // POST must not queue behind a slow detail/list fetch.
      void cancelCongestedQueriesForSessionStop(queryClient, variables.sessionId);
      // Enter the stopping phase immediately; the POST only acknowledges the
      // request and the worker publishes the authoritative stopped snapshot.
      // A deferred stop already patched the UI at click time, so it re-applies
      // the same intent while restoring the real pre-stop detail on failure.
      const target = resolveStopOptimisticTarget(
        variables.deferredStop,
        queryClient.getQueryData<SessionDetail>(queryKeys.session(variables.sessionId)),
        new Date().toISOString(),
      );
      const previousDetail = target.previousDetail;
      const stoppingAt = target.stoppingAt;
      const optimisticDetail = markSessionDetailStopping(previousDetail, { requestedAt: stoppingAt });
      if (optimisticDetail) {
        queryClient.setQueryData(queryKeys.session(variables.sessionId), optimisticDetail);
      }
      // The shell active-work indicator is driven by the runtime summary poll;
      // patch it now so a stopped turn leaves the list at click time.
      const runtimeKey = queryKeys.runtimeSummary();
      const previousRuntime = queryClient.getQueryData<RuntimeSummary>(runtimeKey);
      if (previousRuntime) {
        const nextRuntime = removeChatTurnFromRuntimeSummary(previousRuntime, {
          sessionId: variables.sessionId,
          turnId: variables.turnId,
        });
        if (nextRuntime && nextRuntime !== previousRuntime) {
          queryClient.setQueryData(runtimeKey, nextRuntime);
        }
      }
      return { telemetry, previousDetail, stoppingAt, previousRuntime };
    },
    onSuccess: (nextDetail, variables, context) => {
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        turnId: variables.turnId,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      syncSessionDetail(nextDetail);
      void chatWorkspaceCache.afterSessionChanged();
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        turnId: variables.turnId,
      });
      // Clear the optimistic stopping patch only when nothing newer replaced it.
      if (context?.stoppingAt) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (current) => {
          if (!current) {
            return current;
          }
          return clearSessionDetailStopping(current, {
            requestedAt: context.stoppingAt,
            previous: context.previousDetail,
          });
        });
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("stopFailed")),
      }));
      if (context?.previousRuntime) {
        queryClient.setQueryData(queryKeys.runtimeSummary(), context.previousRuntime);
      }
      void chatWorkspaceCache.afterDirectTurnFailed(variables.sessionId);
    },
  });

  const sessionGuidanceMutation = useMutation({
    mutationFn: async (
      {
        sessionId,
        content,
        mode,
      }: {
        sessionId: string;
        content: string;
        mode: SessionGuidanceMode;
        steeredQueuedTurnId?: string;
      },
    ) =>
      submitSessionGuidance(sessionId, { content, mode }),
    onMutate: (variables) => ({
      telemetry: startUserAction("session_guidance_submit", {
        sessionId: variables.sessionId,
        mode: variables.mode,
        contentLength: variables.content.length,
      }),
    }),
    onSuccess: (nextDetail, variables, context) => {
      context?.telemetry?.succeeded({
        sessionId: variables.sessionId,
        mode: variables.mode,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      setSessionDrafts((current) => ({
        ...current,
        [variables.sessionId]: "",
      }));
      removeStoredSessionDraft(variables.sessionId);
      syncSessionDetail(nextDetail);
      if (variables.steeredQueuedTurnId) {
        // Optimistic steer: the row left the cache before the POST, but this
        // response snapshot still carries it because the queue DELETE has not
        // run yet; keep it out of the paint until the DELETE rebases.
        queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (detailState) =>
          detailState
            ? {
              ...detailState,
              queuedTurns: (detailState.queuedTurns ?? []).filter(
                (row) => row.id !== variables.steeredQueuedTurnId,
              ),
            }
            : detailState,
        );
      }
      void chatWorkspaceCache.afterSessionChanged({ sessionId: variables.sessionId });
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sessionId: variables.sessionId,
        mode: variables.mode,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, t("guidanceFailed")),
      }));
      void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId);
    },
  });

  return {
    submitTurnMutation,
    editResubmitMutation,
    regenerateMutation,
    switchHeadMutation,
    stopTurnMutation,
    sessionGuidanceMutation,
  };
}
