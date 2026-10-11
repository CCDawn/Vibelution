import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import type { MutationCacheNotifyEvent } from "@tanstack/query-core";
import {
  useCallback,
  useEffect,
  useRef,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";

import {
  editResubmitSessionMessage,
  listSessionQueuedTurns,
  regenerateSessionMessage,
  removeSessionQueuedTurn,
  sendNowSessionQueuedTurn,
  stopSessionTurn,
  submitSessionGuidance,
  submitSessionMessage,
  switchSessionHead,
  updateSessionQueuedTurn,
} from "../../api/chat";
import { resolveLocalFilePath } from "../../api/desktopPlatform";
import { submitVirtualHumanConversationMessage } from "../../api/virtualHumanLife";
import { queryKeys } from "../../api/queryKeys";
import type {
  ConversationAttachment,
  ConversationMessage,
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
import { isTempSessionId } from "../sessionOptimisticIds";
import { sessionCreateAttemptState, tempSessionSendBlockedMessage } from "./sessionCreateAttempt";
import { useRerunFileChoice } from "./useRerunFileChoice";
import {
  appendOptimisticUserMessage,
  applyOptimisticEditResubmit,
  applyOptimisticRegenerate,
  clearSessionDetailStopping,
  createClientSubmissionId,
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
  isBusyPhase,
  isRunningPhase,
} from "./chatCodingRouteViewModel";
import {
  MAX_COMPOSER_DOCUMENT_ATTACHMENTS,
  MAX_COMPOSER_IMAGE_ATTACHMENTS,
  applyComposerAttachmentUploadOutcomes,
  classifyComposerFiles,
  clearSessionDraftForSubmittedTurn,
  clearSessionImageAttachments,
  clearUnsupportedSessionImageAttachments,
  clearSessionReferenceAttachments,
  composerUploadedArtifactIds,
  encodeUtf8Base64,
  failedComposerAttachmentUploads,
  markComposerAttachmentsUploading,
  mergeComposerAttachmentsWithRejections,
  needsComposerAttachmentUpload,
  optimisticTurnIdForSubmission,
  resolveComposerSubmitGuard,
  restoreSubmittedDraftIfComposerStillEmpty,
  sessionReferenceId,
  uploadComposerAttachmentsSettled,
  uploadSessionImageAttachment,
  writeStoredMentalModelToggle,
  writeStoredRuntimeStatusToggle,
  type ComposerAttachmentUploadOutcome,
  type ComposerImageAttachment,
} from "./chatComposerSubmitModel";
import { loadTurnStatusTailConfig } from "./turnStatusTailModel";
import { createSubmittedAttachmentPreviews } from "./chatSubmittedAttachmentPreviews";
import {
  beginSessionDraftRecoveryGuard,
  releaseSessionDraftRecoveryGuard,
  removeStoredSessionDraft,
  scheduleSessionDraftRecoverySave,
  scheduleSessionDraftSave,
  type SessionDraftRecoveryGuard,
} from "./chatDraftPersistence";
import { type ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import { appendStoredPromptHistoryEntry } from "../../components/conversation/conversationPromptHistory";
import { postSubmitTelemetry } from "./chatSubmitTelemetry";
import { removeOptimisticUserMessagePaint } from "./chatSessionPaintCache";
import { startUserAction, type UserActionTracker } from "../../app/userActionTelemetry";
import { isEditAcknowledged, rollbackEditResubmit } from "./chatEditResubmitState";
import {
  resolveSessionStopTurnId,
  resolveStopOptimisticTarget,
  cancelCongestedQueriesForSessionStop,
  type DeferredStopIntent,
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
function removeOptimisticUserMessageFromCache(
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

function restoreSubmittedDraftAfterFailure(
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

function exactSubmitTurnId(detail: SessionDetail | undefined, clientSubmissionId: string): string {
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

function isCurrentRunningSessionTurn(
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

function isFailedUploadOutcome(outcome: ComposerAttachmentUploadOutcome): outcome is ComposerAttachmentUploadFailure {
  return outcome.status === "failed";
}

/**
 * A queued turn waiting this long without starting is surfaced to the user:
 * the drain depends on the running turn settling, so a stuck (ghost-running)
 * turn would otherwise leave the message queued forever with zero feedback
 * (defect ①).
 */
export const QUEUED_TURN_STUCK_HINT_MS = 90_000;
const QUEUED_TURN_STUCK_CHECK_INTERVAL_MS = 15_000;

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
    const createdAtMs = Date.parse(String(row.createdAt || ""));
    if (!Number.isFinite(createdAtMs)) {
      return false;
    }
    return nowMs - createdAtMs >= thresholdMs;
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
function restoreQueuedTurnIntoRows(rows: SessionQueuedTurn[], snapshot: QueuedTurnWithdrawSnapshot): SessionQueuedTurn[] {
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
function restoreQueuedTurnOrder(previousRows: SessionQueuedTurn[], currentRows: SessionQueuedTurn[]): SessionQueuedTurn[] {
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

export type UseChatComposerSubmitActionsOptions = ChatComposerTurnMutations & {
  queryClient: QueryClient;
  setActiveTurnLayersBySession?: Dispatch<SetStateAction<Record<string, ActiveTurnLayerState>>>;
  lang: "zh" | "en";
  describeError: (error: unknown, fallback: string) => string;
  setSessionDrafts: Dispatch<SetStateAction<Record<string, string>>>;
  sessionFollowupQueues: Record<string, ComposerQueueItem[]>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setSessionImageAttachments: Dispatch<SetStateAction<Record<string, ComposerImageAttachment[]>>>;
  setSessionReferenceAttachments: Dispatch<SetStateAction<Record<string, SessionReferenceAttachment[]>>>;
  setSessionImageUploadPending: Dispatch<SetStateAction<Record<string, boolean>>>;
  setSessionEditTargets: Dispatch<SetStateAction<Record<string, ChatEditTarget>>>;
  imageUploadInFlightRef: MutableRefObject<Record<string, boolean>>;
  activeSessionId: string | null | undefined;
  activeDraftEffective: string;
  activeImageAttachments: ComposerImageAttachment[];
  activeReferenceAttachments: SessionReferenceAttachment[];
  mentalModelEnabledForNextTurn: boolean;
  runtimeStatusEnabledForNextTurn: boolean;
  /** Sticky per-turn model override for the next send; null follows the session default. */
  turnModelSelection: SessionModelSelection | null;
  resolvedEditTarget: ChatEditTarget | null;
  activeEditTarget: ChatEditTarget | null;
  composerDisabled: boolean;
  sessionBusy: boolean;
  sessionStopping: boolean;
  activePhase: string | null | undefined;
  activeAgentImageInputUnsupported: boolean;
  activeImageInputModelId: string;
  latestUserMessageId: string;
  activeTurnId: string | undefined;
  detail: SessionDetail | undefined;
  setMentalModelEnabledForNextTurn: Dispatch<SetStateAction<boolean>>;
  setRuntimeStatusEnabledForNextTurn: Dispatch<SetStateAction<boolean>>;
  companionAgentId?: string;
};

export type UseChatComposerSubmitActionsResult = {
  handleComposerChange: (value: string) => void;
  handleMentalModelEnabledChange: (enabled: boolean) => void;
  handleRuntimeStatusEnabledChange: (enabled: boolean) => void;
  handleAddComposerAttachments: (files: FileList | File[]) => void;
  handleRemoveComposerAttachment: (attachmentId: string) => void;
  /** Re-upload one failed attachment chip; never auto-sends the draft. */
  handleRetryComposerAttachmentUpload: (attachmentId: string) => void;
  /** Re-upload every failed attachment chip of the active session at once. */
  handleRetryComposerAttachmentUploads: () => void;
  /** Session-keyed retry core (tests and advanced callers). */
  retryComposerAttachmentUploads: (sessionId: string, onlyAttachmentId?: string) => Promise<void>;
  /** Move preview URL ownership with a temporary session's attachment state. */
  rebaseComposerPreviewOwners: (fromSessionId: string, toSessionId: string) => void;
  handleAddComposerReference: (reference: SessionReferenceAttachment) => void;
  handleRemoveComposerReference: (referenceId: string) => void;
  handleSubmitTurn: () => void;
  handleStopTurn: () => void;
  handleSubmitGuidance: (mode: SessionGuidanceMode) => void;
  handleFollowupQueueUpdate: (id: string, text: string) => void;
  handleFollowupQueueRemove: (id: string) => void;
  handleFollowupQueueMove: (fromIndex: number, toIndex: number) => void;
  handleFollowupQueueSteer: (id: string) => void;
  handleFollowupQueueTogglePause: (id: string, paused: boolean) => void;
  handleFollowupQueueSendNow: (id: string) => void;
  handleEditUserMessage: (message: ConversationMessage) => void;
  handleCancelEditMessage: () => void;
  handleRegenerateAssistantMessage: (message: ConversationMessage) => void;
  handleRetryFailedTurn: () => void;
  handleSwitchMessageVersion: (message: ConversationMessage, targetNodeId: string) => void;
  rerunFileChoice: {
    paths: string[];
    error: string;
    restoring: boolean;
  } | null;
  confirmRerunFileRestore: () => Promise<void>;
  keepFilesAndRerun: () => void;
  dismissRerunFileChoice: () => void;
};

/**
 * Composer submit/stop/guidance/edit handlers. Call after composerDisabled is derived.
 */
export function useChatComposerSubmitActions({
  queryClient,
  setActiveTurnLayersBySession,
  lang,
  describeError,
  submitTurnMutation,
  editResubmitMutation,
  regenerateMutation,
  switchHeadMutation,
  stopTurnMutation,
  sessionGuidanceMutation,
  setSessionDrafts,
  sessionFollowupQueues,
  setSessionComposerErrors,
  setSessionImageAttachments,
  setSessionReferenceAttachments,
  setSessionImageUploadPending,
  setSessionEditTargets,
  imageUploadInFlightRef,
  activeSessionId,
  activeDraftEffective,
  activeImageAttachments,
  activeReferenceAttachments,
  mentalModelEnabledForNextTurn,
  runtimeStatusEnabledForNextTurn,
  turnModelSelection,
  resolvedEditTarget,
  activeEditTarget,
  composerDisabled,
  sessionBusy,
  sessionStopping,
  activePhase,
  activeAgentImageInputUnsupported,
  activeImageInputModelId,
  activeTurnId,
  detail,
  setMentalModelEnabledForNextTurn,
  setRuntimeStatusEnabledForNextTurn,
  companionAgentId,
}: UseChatComposerSubmitActionsOptions): UseChatComposerSubmitActionsResult {
  const pendingStopAfterAcceptRef = useRef<Map<string, DeferredStopIntent>>(new Map());
  // Uploading attachments happens before React Query creates the submit/edit
  // mutation. Keep the same submission identity visible to Stop during that
  // gap so a stop requested before upload completion can still match the late
  // mutation acceptance, even after switching sessions.
  const pendingUploadSubmissionRef = useRef<Map<string, string>>(new Map());
  // Per-id optimistic queue intents (mirrors pendingAgentIds in
  // useChatAgentArchiveQueue): a second click on a row whose withdraw is still
  // in flight must not re-send the DELETE, while different rows stay free to
  // race in parallel.
  const pendingQueueWithdrawalIdsRef = useRef<Set<string>>(new Set());
  // This hook owns every composer object URL, including URLs for attachments
  // that are rejected after classification. Files remain in the session tray
  // when its preview URLs are released, so returning to a session can restore
  // its previews without keeping Blob URLs alive in the background.
  const composerPreviewUrlsBySessionRef = useRef<Map<string, Map<string, {
    file: File;
    previewUrl: string | null;
  }>>>(new Map());
  const composerSessionAliasesRef = useRef(new Map<string, string>());
  const pendingPreviewReleaseTokenBySessionRef = useRef(new Map<string, number>());
  const composerLifecycleTokenRef = useRef(0);
  const isMountedRef = useRef(false);
  const clearedEditMutationVariablesRef = useRef<unknown>(null);
  // Defect-① observability: a queued turn whose drain never fires (ghost
  // running marker) would sit silently forever. Surface one composer hint per
  // row once its wait exceeds the threshold; forget a row when it leaves the
  // queue so a re-queued row can be hinted again.
  const queuedStuckHintedIdsRef = useRef<Set<string>>(new Set());
  const resolveComposerSessionId = useCallback((sessionId: string) => {
    let resolved = String(sessionId || "").trim();
    if (!resolved) return resolved;
    const visited = new Set<string>();
    while (!visited.has(resolved)) {
      visited.add(resolved);
      const next = composerSessionAliasesRef.current.get(resolved);
      if (!next) break;
      resolved = next;
    }
    return resolved;
  }, []);
  const {
    rerunFileChoice,
    interceptRerun,
    confirmRerunFileRestore,
    keepFilesAndRerun,
    dismissRerunFileChoice,
  } = useRerunFileChoice({
    sessionId: activeSessionId,
    lang,
    describeError,
  });
  const activeQueuedTurns = detail?.queuedTurns;
  useEffect(() => {
    const sessionId = activeSessionId;
    if (!sessionId) {
      return;
    }
    const surfaceStuckHints = () => {
      const rows = activeQueuedTurns ?? [];
      const aliveIds = new Set(rows.map((row) => row.id));
      for (const hinted of [...queuedStuckHintedIdsRef.current]) {
        if (!aliveIds.has(hinted)) {
          queuedStuckHintedIdsRef.current.delete(hinted);
        }
      }
      const firstStuck = queuedTurnsWaitingBeyondMs(rows, Date.now())[0];
      if (!firstStuck || queuedStuckHintedIdsRef.current.has(firstStuck.id)) {
        return;
      }
      queuedStuckHintedIdsRef.current.add(firstStuck.id);
      const waitedSeconds = Math.max(
        1,
        Math.round((Date.now() - Date.parse(String(firstStuck.createdAt || ""))) / 1000),
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]:
          lang === "zh"
            ? `有排队消息等待超过 ${waitedSeconds} 秒仍未开始，当前轮可能卡住了。可停止当前轮让队列立即发送，或撤回后重发。`
            : `A queued message has waited over ${waitedSeconds} seconds without starting; the current turn may be stuck. Stop the current turn to send the queue now, or withdraw it and resend.`,
      }));
    };
    surfaceStuckHints();
    const timer = window.setInterval(surfaceStuckHints, QUEUED_TURN_STUCK_CHECK_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [activeSessionId, lang, activeQueuedTurns, setSessionComposerErrors]);
  const restorePendingStopAfterUploadFailure = useCallback((sessionId: string) => {
    sessionId = resolveComposerSessionId(sessionId);
    const pendingStop = pendingStopAfterAcceptRef.current.get(sessionId);
    if (pendingStop?.stoppingAt) {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (current) => {
        if (!current) {
          return current;
        }
        return clearSessionDetailStopping(current, {
          requestedAt: pendingStop.stoppingAt!,
          previous: pendingStop.previousDetail,
        });
      });
    }
    pendingStopAfterAcceptRef.current.delete(sessionId);
  }, [queryClient, resolveComposerSessionId]);
  const attachmentSnapshotRef = useRef<{ sessionId: string | null | undefined; attachments: ComposerImageAttachment[] }>({
    sessionId: activeSessionId,
    attachments: activeImageAttachments,
  });
  const lastAttachmentInputRef = useRef(activeImageAttachments);
  if (attachmentSnapshotRef.current.sessionId !== activeSessionId || lastAttachmentInputRef.current !== activeImageAttachments) {
    lastAttachmentInputRef.current = activeImageAttachments;
    attachmentSnapshotRef.current = { sessionId: activeSessionId, attachments: activeImageAttachments };
  }

  const rememberComposerAttachmentUrls = useCallback((sessionId: string, attachments: ComposerImageAttachment[]) => {
    sessionId = resolveComposerSessionId(sessionId);
    if (!sessionId || !attachments.length) {
      return;
    }
    let owners = composerPreviewUrlsBySessionRef.current.get(sessionId);
    if (!owners) {
      owners = new Map();
      composerPreviewUrlsBySessionRef.current.set(sessionId, owners);
    }
    for (const attachment of attachments) {
      if (!owners.has(attachment.id)) {
        owners.set(attachment.id, { file: attachment.file, previewUrl: attachment.previewUrl });
      }
    }
  }, [resolveComposerSessionId]);

  const restoreComposerAttachmentUrls = useCallback((sessionId: string, attachments: ComposerImageAttachment[]) => {
    sessionId = resolveComposerSessionId(sessionId);
    if (!sessionId || !attachments.length) {
      return attachments;
    }
    let owners = composerPreviewUrlsBySessionRef.current.get(sessionId);
    if (!owners) {
      owners = new Map();
      composerPreviewUrlsBySessionRef.current.set(sessionId, owners);
    }
    let changed = false;
    const restored = attachments.map((attachment) => {
      let owned = owners!.get(attachment.id);
      if (!owned) {
        owned = { file: attachment.file, previewUrl: attachment.previewUrl };
        owners!.set(attachment.id, owned);
      }
      if (!owned.previewUrl) {
        owned.previewUrl = URL.createObjectURL(owned.file);
      }
      if (owned.previewUrl === attachment.previewUrl) {
        return attachment;
      }
      changed = true;
      return { ...attachment, previewUrl: owned.previewUrl };
    });
    return changed ? restored : attachments;
  }, [resolveComposerSessionId]);

  const releaseComposerSessionPreviewUrls = useCallback((sessionId: string, forgetFiles: boolean) => {
    sessionId = resolveComposerSessionId(sessionId);
    const owners = composerPreviewUrlsBySessionRef.current.get(sessionId);
    if (!owners) {
      return;
    }
    for (const [attachmentId, owned] of owners) {
      if (owned.previewUrl) {
        URL.revokeObjectURL(owned.previewUrl);
      }
      if (forgetFiles) {
        owners.delete(attachmentId);
      } else {
        owned.previewUrl = null;
      }
    }
    if (forgetFiles || owners.size === 0) {
      composerPreviewUrlsBySessionRef.current.delete(sessionId);
    }
  }, [resolveComposerSessionId]);

  const forgetComposerAttachmentUrl = useCallback((
    sessionId: string,
    attachment: Pick<ComposerImageAttachment, "id" | "previewUrl">,
  ) => {
    sessionId = resolveComposerSessionId(sessionId);
    const owners = composerPreviewUrlsBySessionRef.current.get(sessionId);
    const owned = owners?.get(attachment.id);
    const previewUrl = owned ? owned.previewUrl : attachment.previewUrl;
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    owners?.delete(attachment.id);
    if (owners?.size === 0) {
      composerPreviewUrlsBySessionRef.current.delete(sessionId);
    }
  }, [resolveComposerSessionId]);

  const isComposerAttachmentOwned = useCallback((sessionId: string, attachmentId: string) => (
    composerPreviewUrlsBySessionRef.current.get(resolveComposerSessionId(sessionId))?.has(attachmentId) ?? false
  ), [resolveComposerSessionId]);

  const retainOwnedComposerUploadOutcomes = useCallback((
    sessionId: string,
    attachments: ComposerImageAttachment[],
    outcomes: ComposerAttachmentUploadOutcome[],
  ) => {
    const ownedIds = new Set(
      attachments
        .filter((attachment) => isComposerAttachmentOwned(sessionId, attachment.id))
        .map((attachment) => attachment.id),
    );
    return outcomes.filter((outcome) => ownedIds.has(outcome.id));
  }, [isComposerAttachmentOwned]);

  const cancelScheduledComposerPreviewRelease = useCallback((sessionId: string) => {
    const token = pendingPreviewReleaseTokenBySessionRef.current.get(sessionId) ?? 0;
    pendingPreviewReleaseTokenBySessionRef.current.set(sessionId, token + 1);
  }, []);

  const rebaseComposerPreviewOwners = useCallback((fromSessionId: string, toSessionId: string) => {
    const sourceId = resolveComposerSessionId(fromSessionId);
    const targetId = resolveComposerSessionId(toSessionId);
    if (!sourceId || !targetId || sourceId === targetId) return;
    cancelScheduledComposerPreviewRelease(sourceId);
    cancelScheduledComposerPreviewRelease(targetId);
    const sourceOwners = composerPreviewUrlsBySessionRef.current.get(sourceId);
    // `rekeySessionComposerEntry` keeps an already-present target entry, so
    // dispose the source owners in the same collision case.
    if (composerPreviewUrlsBySessionRef.current.has(targetId)) {
      releaseComposerSessionPreviewUrls(sourceId, true);
      return;
    }
    if (sourceOwners) {
      composerPreviewUrlsBySessionRef.current.set(targetId, sourceOwners);
      composerPreviewUrlsBySessionRef.current.delete(sourceId);
    }
    // An in-flight upload still closes over the temporary id. Keep that id as
    // an alias so settlement writes to the rekeyed attachment state and submits
    // against the newly-created session instead of dropping its upload result.
    composerSessionAliasesRef.current.set(sourceId, targetId);
    if (imageUploadInFlightRef.current[sourceId]) {
      imageUploadInFlightRef.current[targetId] = true;
      delete imageUploadInFlightRef.current[sourceId];
    }
    const pendingUploadSubmission = pendingUploadSubmissionRef.current.get(sourceId);
    if (pendingUploadSubmission) {
      if (!pendingUploadSubmissionRef.current.has(targetId)) {
        pendingUploadSubmissionRef.current.set(targetId, pendingUploadSubmission);
      }
      pendingUploadSubmissionRef.current.delete(sourceId);
    }
    const pendingStop = pendingStopAfterAcceptRef.current.get(sourceId);
    if (pendingStop) {
      if (!pendingStopAfterAcceptRef.current.has(targetId)) {
        pendingStopAfterAcceptRef.current.set(targetId, pendingStop);
      }
      pendingStopAfterAcceptRef.current.delete(sourceId);
    }
    setSessionImageUploadPending((current) => {
      if (!Object.hasOwn(current, sourceId)) return current;
      const { [sourceId]: sourcePending, ...remaining } = current;
      return Object.hasOwn(remaining, targetId)
        ? remaining
        : { ...remaining, [targetId]: sourcePending };
    });
  }, [
    cancelScheduledComposerPreviewRelease,
    imageUploadInFlightRef,
    pendingStopAfterAcceptRef,
    pendingUploadSubmissionRef,
    releaseComposerSessionPreviewUrls,
    resolveComposerSessionId,
    setSessionImageUploadPending,
  ]);

  const scheduleComposerPreviewRelease = useCallback((sessionId: string) => {
    const token = (pendingPreviewReleaseTokenBySessionRef.current.get(sessionId) ?? 0) + 1;
    pendingPreviewReleaseTokenBySessionRef.current.set(sessionId, token);
    void Promise.resolve().then(() => {
      if (pendingPreviewReleaseTokenBySessionRef.current.get(sessionId) !== token) {
        return;
      }
      pendingPreviewReleaseTokenBySessionRef.current.delete(sessionId);
      releaseComposerSessionPreviewUrls(sessionId, false);
    });
  }, [releaseComposerSessionPreviewUrls]);

  const releaseAllComposerPreviewUrls = useCallback(() => {
    for (const sessionId of [...composerPreviewUrlsBySessionRef.current.keys()]) {
      releaseComposerSessionPreviewUrls(sessionId, true);
    }
    composerSessionAliasesRef.current.clear();
  }, [releaseComposerSessionPreviewUrls]);

  useEffect(() => {
    isMountedRef.current = true;
    composerLifecycleTokenRef.current += 1;
    return () => {
      isMountedRef.current = false;
      const token = ++composerLifecycleTokenRef.current;
      void Promise.resolve().then(() => {
        if (composerLifecycleTokenRef.current === token && !isMountedRef.current) {
          releaseAllComposerPreviewUrls();
        }
      });
    };
  }, [releaseAllComposerPreviewUrls]);

  useEffect(() => {
    const sessionId = activeSessionId;
    if (!sessionId) {
      return;
    }
    cancelScheduledComposerPreviewRelease(sessionId);
    const snapshot = attachmentSnapshotRef.current.sessionId === sessionId
      ? attachmentSnapshotRef.current.attachments
      : [];
    const restored = restoreComposerAttachmentUrls(sessionId, snapshot);
    if (restored !== snapshot) {
      setSessionImageAttachments((current) => {
        const latest = current[sessionId] ?? snapshot;
        const owners = composerPreviewUrlsBySessionRef.current.get(sessionId);
        let changed = false;
        const next = latest.map((attachment) => {
          const previewUrl = owners?.get(attachment.id)?.previewUrl;
          if (!previewUrl || previewUrl === attachment.previewUrl) {
            return attachment;
          }
          changed = true;
          return { ...attachment, previewUrl };
        });
        return changed ? { ...current, [sessionId]: next } : current;
      });
    }
    return () => scheduleComposerPreviewRelease(sessionId);
  }, [
    activeSessionId,
    cancelScheduledComposerPreviewRelease,
    restoreComposerAttachmentUrls,
    scheduleComposerPreviewRelease,
    setSessionImageAttachments,
  ]);

  useEffect(() => {
    const variables = editResubmitMutation.variables;
    if (editResubmitMutation.isSuccess && variables?.sessionId && variables !== clearedEditMutationVariablesRef.current) {
      clearedEditMutationVariablesRef.current = variables;
      releaseComposerSessionPreviewUrls(variables.sessionId, true);
    }
  }, [
    editResubmitMutation.isSuccess,
    editResubmitMutation.variables,
    releaseComposerSessionPreviewUrls,
  ]);

  const handleComposerChange = useCallback((value: string) => {
    if (!activeSessionId) {
      return;
    }
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: value,
    }));
    // Debounced localStorage persistence: drafts survive a reload/restart.
    scheduleSessionDraftSave(activeSessionId, value);
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [activeSessionId, setSessionComposerErrors, setSessionDrafts]);

  const handleMentalModelEnabledChange = useCallback((enabled: boolean) => {
    setMentalModelEnabledForNextTurn(enabled);
    writeStoredMentalModelToggle(enabled);
  }, [setMentalModelEnabledForNextTurn]);

  const handleRuntimeStatusEnabledChange = useCallback((enabled: boolean) => {
    setRuntimeStatusEnabledForNextTurn(enabled);
    writeStoredRuntimeStatusToggle(enabled);
  }, [setRuntimeStatusEnabledForNextTurn]);

  const handleAddComposerAttachments = useCallback((files: FileList | File[]) => {
    if (!activeSessionId) {
      return;
    }
    // Desktop shell resolves drag/picker files back to their local paths so the
    // submit upload can register them zero-copy; clipboard screenshots and web
    // browsers resolve to null and keep the in-memory upload path.
    const { accepted: classifiedAccepted, rejected } = classifyComposerFiles(files, {
      resolveLocalPath: resolveLocalFilePath,
    });
    if (!classifiedAccepted.length && !rejected.length) {
      return;
    }
    // Own every URL returned by classification before applying model and
    // capacity filters, so rejected previews are covered by the same cleanup.
    rememberComposerAttachmentUrls(activeSessionId, classifiedAccepted);
    // Document attachments do not depend on the model's image input support;
    // only image attachments are dropped when the dialogue model lacks vision.
    const accepted = activeAgentImageInputUnsupported
      ? classifiedAccepted.filter((attachment) => attachment.kind !== "image")
      : classifiedAccepted;
    const unsupportedImageNames = activeAgentImageInputUnsupported
      ? classifiedAccepted.filter((attachment) => attachment.kind === "image").map((attachment) => attachment.filename)
      : [];
    if (activeAgentImageInputUnsupported) {
      classifiedAccepted
        .filter((attachment) => attachment.kind === "image")
        .forEach((attachment) => forgetComposerAttachmentUrl(activeSessionId, attachment));
    }
    let capacityRejected: ComposerImageAttachment[] = [];
    if (accepted.length) {
      const attachmentSnapshot = attachmentSnapshotRef.current.sessionId === activeSessionId
        ? attachmentSnapshotRef.current.attachments
        : activeImageAttachments;
      const mergePreview = mergeComposerAttachmentsWithRejections(attachmentSnapshot, accepted, {
        maxTotal: MAX_COMPOSER_IMAGE_ATTACHMENTS + MAX_COMPOSER_DOCUMENT_ATTACHMENTS,
        maxImages: MAX_COMPOSER_IMAGE_ATTACHMENTS,
        maxDocuments: MAX_COMPOSER_DOCUMENT_ATTACHMENTS,
      });
      capacityRejected = mergePreview.rejected;
      capacityRejected.forEach((attachment) => forgetComposerAttachmentUrl(activeSessionId, attachment));
      attachmentSnapshotRef.current = { sessionId: activeSessionId, attachments: mergePreview.attachments };
      setSessionImageAttachments((current) => {
        return {
          ...current,
          [activeSessionId]: mergePreview.attachments,
        };
      });
    }
    const rejectedMessages = [
      rejected.length
        ? (lang === "zh" ? `格式或大小不支持：${rejected.join("、")}` : `type or size is unsupported: ${rejected.join(", ")}`)
        : "",
      unsupportedImageNames.length
        ? (lang === "zh" ? `当前模型不支持图片：${unsupportedImageNames.join("、")}` : `images are unsupported by this model: ${unsupportedImageNames.join(", ")}`)
        : "",
      capacityRejected.length
        ? (lang === "zh"
          ? `数量超出上限：${capacityRejected.map((attachment) => attachment.filename).join("、")}`
          : `attachment limit exceeded: ${capacityRejected.map((attachment) => attachment.filename).join(", ")}`)
        : "",
    ].filter(Boolean);
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: rejectedMessages.length
        ? (lang === "zh" ? `部分附件未添加（${rejectedMessages.join("；")}）` : `Some attachments were rejected (${rejectedMessages.join("; ")})`)
        : "",
    }));
  }, [
    activeAgentImageInputUnsupported,
    activeImageAttachments,
    activeSessionId,
    forgetComposerAttachmentUrl,
    lang,
    rememberComposerAttachmentUrls,
    sessionBusy,
    setSessionComposerErrors,
    setSessionImageAttachments,
  ]);

  const handleRemoveComposerAttachment = useCallback((attachmentId: string) => {
    if (!activeSessionId) {
      return;
    }
    const attachmentSnapshot = attachmentSnapshotRef.current.sessionId === activeSessionId
      ? attachmentSnapshotRef.current.attachments
      : activeImageAttachments;
    rememberComposerAttachmentUrls(activeSessionId, attachmentSnapshot);
    const nextAttachments = attachmentSnapshot.filter((attachment) => attachment.id !== attachmentId);
    if (nextAttachments.length === attachmentSnapshot.length) {
      return;
    }
    const removed = attachmentSnapshot.find((attachment) => attachment.id === attachmentId);
    if (removed) forgetComposerAttachmentUrl(activeSessionId, removed);
    attachmentSnapshotRef.current = { sessionId: activeSessionId, attachments: nextAttachments };
    setSessionImageAttachments((current) => ({
      ...current,
      [activeSessionId]: nextAttachments,
    }));
  }, [
    activeImageAttachments,
    activeSessionId,
    forgetComposerAttachmentUrl,
    rememberComposerAttachmentUrls,
    setSessionImageAttachments,
  ]);

  // Upload-repair entry for failed attachment chips: re-uploads only the
  // failed subset (or one chip), respects the same per-session in-flight guard
  // as submit, and never auto-sends — the restored draft waits for the user.
  const retryComposerAttachmentUploads = useCallback(async (sessionId: string, onlyAttachmentId?: string) => {
    if (!isMountedRef.current || !sessionId || imageUploadInFlightRef.current[sessionId]) {
      return;
    }
    const tray = activeImageAttachments;
    const targets = failedComposerAttachmentUploads(tray).filter(
      (attachment) => !onlyAttachmentId || attachment.id === onlyAttachmentId,
    );
    if (!targets.length) {
      return;
    }
    rememberComposerAttachmentUrls(sessionId, targets);
    imageUploadInFlightRef.current[sessionId] = true;
    setSessionImageUploadPending((current) => ({
      ...current,
      [sessionId]: true,
    }));
    setSessionImageAttachments((current) => ({
      ...current,
      [sessionId]: markComposerAttachmentsUploading(
        current[sessionId] ?? [],
        new Set(targets.map((attachment) => attachment.id)),
      ),
    }));
    postSubmitTelemetry(
      "browser.chat_submit.upload_retry_started",
      "Composer attachment upload retry started.",
      sessionId,
      { attachmentCount: targets.length },
    );
    try {
      const settledOutcomes = await uploadComposerAttachmentsSettled(sessionId, targets);
      if (!isMountedRef.current) {
        return;
      }
      const uploadSessionId = resolveComposerSessionId(sessionId);
      const outcomes = retainOwnedComposerUploadOutcomes(uploadSessionId, targets, settledOutcomes);
      setSessionImageAttachments((current) => ({
        ...current,
        [uploadSessionId]: applyComposerAttachmentUploadOutcomes(current[uploadSessionId] ?? [], outcomes),
      }));
      const failedOutcomes = outcomes.filter(isFailedUploadOutcome);
      const remainingFailedChips = failedComposerAttachmentUploads(
        applyComposerAttachmentUploadOutcomes(tray.filter((attachment) => (
          isComposerAttachmentOwned(uploadSessionId, attachment.id)
        )), outcomes),
      ).length;
      if (failedOutcomes.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_retry_failed",
          "Composer attachment upload retry finished with failures.",
          uploadSessionId,
          {
            attachmentCount: targets.length,
            uploadedAttachmentCount: targets.length - failedOutcomes.length,
            error: failedOutcomes[0]?.error,
          },
          "error",
        );
        setSessionComposerErrors((current) => ({
          ...current,
          [uploadSessionId]: describeError(
            failedOutcomes[0]?.error,
            lang === "zh" ? "图片上传失败" : "Image upload failed",
          ),
        }));
      } else {
        postSubmitTelemetry(
          "browser.chat_submit.upload_retry_succeeded",
          "Composer attachment upload retry succeeded.",
          uploadSessionId,
          {
            attachmentCount: targets.length,
            uploadedAttachmentCount: targets.length,
          },
        );
        if (remainingFailedChips === 0) {
          // The upload-failure hint must not outlive its chips; unrelated
          // errors were already replaced by the submit failure branch.
          setSessionComposerErrors((current) => ({
            ...current,
            [uploadSessionId]: "",
          }));
        }
      }
    } finally {
      const finishedSessionId = resolveComposerSessionId(sessionId);
      imageUploadInFlightRef.current[finishedSessionId] = false;
      if (isMountedRef.current) {
        setSessionImageUploadPending((current) => ({
          ...current,
          [finishedSessionId]: false,
        }));
      }
    }
  }, [
    activeImageAttachments,
    describeError,
    imageUploadInFlightRef,
    isComposerAttachmentOwned,
    lang,
    rememberComposerAttachmentUrls,
    retainOwnedComposerUploadOutcomes,
    resolveComposerSessionId,
    setSessionComposerErrors,
    setSessionImageAttachments,
    setSessionImageUploadPending,
  ]);

  const handleRetryComposerAttachmentUploads = useCallback(() => {
    if (!activeSessionId) {
      return;
    }
    void retryComposerAttachmentUploads(activeSessionId);
  }, [activeSessionId, retryComposerAttachmentUploads]);

  const handleRetryComposerAttachmentUpload = useCallback((attachmentId: string) => {
    if (!activeSessionId) {
      return;
    }
    void retryComposerAttachmentUploads(activeSessionId, attachmentId);
  }, [activeSessionId, retryComposerAttachmentUploads]);

  const handleAddComposerReference = useCallback((reference: SessionReferenceAttachment) => {
    if (!activeSessionId) {
      return;
    }
    if (activeEditTarget || resolvedEditTarget) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh"
          ? "编辑重发暂不支持会话引用，请取消编辑后再添加。"
          : "Session references are not supported while editing a message. Cancel the edit first.",
      }));
      return;
    }
    const referenceId = sessionReferenceId(reference);
    if (!referenceId) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh" ? "会话引用缺少有效 id。" : "Session reference is missing a valid id.",
      }));
      return;
    }
    setSessionReferenceAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      if (existing.some((item) => sessionReferenceId(item) === referenceId)) {
        return current;
      }
      return {
        ...current,
        [activeSessionId]: [...existing, reference].slice(-6),
      };
    });
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [
    activeEditTarget,
    activeSessionId,
    lang,
    resolvedEditTarget,
    sessionBusy,
    setSessionComposerErrors,
    setSessionReferenceAttachments,
  ]);

  const handleRemoveComposerReference = useCallback((referenceId: string) => {
    if (!activeSessionId) {
      return;
    }
    setSessionReferenceAttachments((current) => {
      const existing = current[activeSessionId] ?? [];
      const next = existing.filter((reference) => sessionReferenceId(reference) !== referenceId);
      if (next.length === existing.length) {
        return current;
      }
      if (!next.length) {
        return clearSessionReferenceAttachments(current, activeSessionId);
      }
      return {
        ...current,
        [activeSessionId]: next,
      };
    });
  }, [activeSessionId, setSessionReferenceAttachments]);

  const submitTurnWithAttachments = useCallback(async (
    sessionId: string,
    content: string,
    attachments: ComposerImageAttachment[],
    references: SessionReferenceAttachment[],
    mentalModelEnabled: boolean,
    runtimeStatusEnabled: boolean,
    clientSubmissionId: string,
    queuedBehindActiveTurn = false,
    modelSelection: SessionModelSelection | null = null,
  ) => {
    if (!isMountedRef.current) {
      return;
    }
    if (imageUploadInFlightRef.current[sessionId]) {
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit was blocked while image upload was already in flight.",
        sessionId,
        {
          content,
          attachmentCount: attachments.length,
          referenceCount: references.length,
          mentalModelEnabled,
          guardReason: "image_upload_in_flight",
          clientSubmissionId,
        },
        "warning",
      );
      return;
    }
    rememberComposerAttachmentUrls(sessionId, attachments);
    let submittedAttachments = attachments;
    let submittedSessionId = resolveComposerSessionId(sessionId);
    const restoreAttachmentsAfterFailure = () => {
      if (!isMountedRef.current || !attachments.length) return;
      const restoreSessionId = resolveComposerSessionId(sessionId);
      const restored = restoreComposerAttachmentUrls(restoreSessionId, submittedAttachments);
      setSessionImageAttachments((current) => {
        const byId = new Map(restored.map((attachment) => [attachment.id, attachment]));
        for (const attachment of current[restoreSessionId] ?? []) {
          if (!byId.has(attachment.id)) byId.set(attachment.id, attachment);
        }
        return { ...current, [restoreSessionId]: [...byId.values()] };
      });
    };
    const releaseSubmittedComposerAttachmentOwners = () => {
      submittedAttachments.forEach((attachment) => forgetComposerAttachmentUrl(sessionId, attachment));
    };
    imageUploadInFlightRef.current[sessionId] = true;
    pendingUploadSubmissionRef.current.set(sessionId, clientSubmissionId);
    setSessionImageUploadPending((current) => ({
      ...current,
      [sessionId]: true,
    }));
    setSessionDrafts((current) => clearSessionDraftForSubmittedTurn(current, sessionId));
    // The submitted draft must not resurrect from localStorage after a reload.
    removeStoredSessionDraft(sessionId);
    let draftRecoveryGuard = beginSessionDraftRecoveryGuard(sessionId);
    let mutationOwnsRecoveryGuard = false;
    setSessionComposerErrors((current) => ({
      ...current,
      [sessionId]: "",
    }));
    const immediatePreview = !companionAgentId && !queuedBehindActiveTurn;
    let previewAttachments: ConversationAttachment[] = [];
    try {
      previewAttachments = immediatePreview
        ? createSubmittedAttachmentPreviews(queryClient, sessionId, clientSubmissionId, attachments)
        : [];
      if (immediatePreview && previewAttachments.length) {
        const submittedIds = new Set(attachments.map((attachment) => attachment.id));
        // Move the submitted snapshot without revoking the upload owner's URLs.
        setSessionImageAttachments((current) => ({
          ...current,
          [sessionId]: (current[sessionId] ?? []).filter((attachment) => !submittedIds.has(attachment.id)),
        }));
      }
      if (!queuedBehindActiveTurn && (content || references.length || previewAttachments.length)) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
          markSessionDetailRunning(appendOptimisticUserMessage(detailState, { sessionId, content, references, clientSubmissionId, attachments: previewAttachments })),
        );
        if (immediatePreview) {
          setActiveTurnLayersBySession?.((current) => setActiveTurnLayerForSession(current, sessionId,
            createOptimisticActiveTurnLayer({ sessionId, clientSubmissionId, accepted: false }),
          ));
        }
      }
      if (attachments.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_started",
          "Direct chat submit image upload started.",
          sessionId,
          {
            content,
            attachmentCount: attachments.length,
            referenceCount: references.length,
            mentalModelEnabled,
            clientSubmissionId,
          },
        );
      }
      // Per-attachment settle: successes keep their artifactId (reused on
      // resubmit), failures flip their chip to the retryable failed state
      // instead of discarding the whole batch.
      const needUpload = attachments.filter(needsComposerAttachmentUpload);
      let outcomes: ComposerAttachmentUploadOutcome[] = [];
      if (needUpload.length) {
        setSessionImageAttachments((current) => ({
          ...current,
          [sessionId]: markComposerAttachmentsUploading(current[sessionId] ?? []),
        }));
        const settledOutcomes = await uploadComposerAttachmentsSettled(sessionId, needUpload);
        if (!isMountedRef.current) {
          return;
        }
        submittedSessionId = resolveComposerSessionId(sessionId);
        if (draftRecoveryGuard?.sessionId !== submittedSessionId) {
          releaseSessionDraftRecoveryGuard(draftRecoveryGuard);
          draftRecoveryGuard = beginSessionDraftRecoveryGuard(submittedSessionId);
        }
        outcomes = retainOwnedComposerUploadOutcomes(submittedSessionId, needUpload, settledOutcomes);
        submittedAttachments = applyComposerAttachmentUploadOutcomes(attachments, outcomes);
        setSessionImageAttachments((current) => ({
          ...current,
          [submittedSessionId]: applyComposerAttachmentUploadOutcomes(current[submittedSessionId] ?? [], outcomes),
        }));
      }
      if (!isMountedRef.current) {
        return;
      }
      submittedSessionId = resolveComposerSessionId(sessionId);
      const failedOutcomes = outcomes.filter(isFailedUploadOutcome);
      if (failedOutcomes.length) {
        const firstFailure = failedOutcomes[0];
        postSubmitTelemetry(
          "browser.chat_submit.upload_failed",
          "Direct chat submit image upload failed before message POST.",
          submittedSessionId,
          {
            content,
            attachmentCount: attachments.length,
            uploadedAttachmentCount: attachments.length - failedOutcomes.length,
            referenceCount: references.length,
            mentalModelEnabled,
            clientSubmissionId,
            error: firstFailure.error,
          },
          "error",
        );
        setSessionComposerErrors((current) => ({
          ...current,
          [submittedSessionId]: describeError(firstFailure.error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
        }));
        restoreAttachmentsAfterFailure();
        if (content || references.length || previewAttachments.length) {
          removeOptimisticUserMessageFromCache(queryClient, submittedSessionId, { sessionId: submittedSessionId, content, references, clientSubmissionId });
          restoreSubmittedDraftAfterFailure(setSessionDrafts, submittedSessionId, content, draftRecoveryGuard);
        }
        if (immediatePreview) setActiveTurnLayersBySession?.((current) => setActiveTurnLayerForSession(current, submittedSessionId, undefined));
        restorePendingStopAfterUploadFailure(submittedSessionId);
        return;
      }
      if (attachments.length) {
        postSubmitTelemetry(
          "browser.chat_submit.upload_succeeded",
          "Direct chat submit image upload succeeded.",
          submittedSessionId,
          {
            content,
            attachmentCount: attachments.length,
            uploadedAttachmentCount: attachments.length,
            referenceCount: references.length,
            mentalModelEnabled,
            clientSubmissionId,
          },
        );
      }
      const stillOwnedAttachments = attachments.filter((attachment) => (
        isComposerAttachmentOwned(submittedSessionId, attachment.id)
      ));
      const uploadedAttachmentIds = composerUploadedArtifactIds(
        applyComposerAttachmentUploadOutcomes(stillOwnedAttachments, outcomes),
      );
      postSubmitTelemetry(
        "browser.chat_submit.submit_mutate_requested",
        "Direct chat submit mutation was requested.",
        submittedSessionId,
        {
          content,
          attachmentCount: attachments.length,
          uploadedAttachmentCount: uploadedAttachmentIds.length,
          referenceCount: references.length,
          mentalModelEnabled,
          clientSubmissionId,
        },
      );
      submitTurnMutation.mutate({
        sessionId: submittedSessionId,
        clientSubmissionId,
        content,
        draftRecoveryGuard,
        mentalModelEnabled,
        runtimeStatusEnabled,
        turnStatusTail: loadTurnStatusTailConfig(submittedSessionId),
        attachmentIds: uploadedAttachmentIds,
        attachments: previewAttachments,
        composerAttachments: submittedAttachments,
        restoreAttachmentsAfterFailure,
        releaseComposerAttachmentOwners: releaseSubmittedComposerAttachmentOwners,
        references,
        requestStartedAtMs: chatStreamPerformanceNowMs(),
        queuedBehindActiveTurn,
        modelSelection,
      });
      mutationOwnsRecoveryGuard = true;
    } catch (error) {
      if (!isMountedRef.current) {
        return;
      }
      // Defense net only: attachment uploads settle per attachment above, so
      // this keeps any unexpected throw on the same failure semantics.
      postSubmitTelemetry(
          "browser.chat_submit.upload_failed",
          "Direct chat submit image upload failed before message POST.",
          submittedSessionId,
        {
          content,
          attachmentCount: attachments.length,
          referenceCount: references.length,
          mentalModelEnabled,
          clientSubmissionId,
          error,
        },
        "error",
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [submittedSessionId]: describeError(error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
      }));
      restoreAttachmentsAfterFailure();
      if (content || references.length || previewAttachments.length) {
        removeOptimisticUserMessageFromCache(queryClient, submittedSessionId, { sessionId: submittedSessionId, content, references, clientSubmissionId });
        restoreSubmittedDraftAfterFailure(setSessionDrafts, submittedSessionId, content, draftRecoveryGuard);
      }
      if (immediatePreview) setActiveTurnLayersBySession?.((current) => setActiveTurnLayerForSession(current, submittedSessionId, undefined));
      restorePendingStopAfterUploadFailure(submittedSessionId);
    } finally {
      if (!mutationOwnsRecoveryGuard) {
        releaseSessionDraftRecoveryGuard(draftRecoveryGuard);
      }
      const finishedSessionId = resolveComposerSessionId(sessionId);
      if (pendingUploadSubmissionRef.current.get(finishedSessionId) === clientSubmissionId) {
        pendingUploadSubmissionRef.current.delete(finishedSessionId);
      }
      imageUploadInFlightRef.current[finishedSessionId] = false;
      if (isMountedRef.current) {
        setSessionImageUploadPending((current) => ({
          ...current,
          [finishedSessionId]: false,
        }));
      }
    }
  }, [
    companionAgentId,
    restoreComposerAttachmentUrls,
    setSessionImageAttachments,
    setActiveTurnLayersBySession,
    describeError,
    imageUploadInFlightRef,
    isComposerAttachmentOwned,
    forgetComposerAttachmentUrl,
    retainOwnedComposerUploadOutcomes,
    resolveComposerSessionId,
    lang,
    queryClient,
    rememberComposerAttachmentUrls,
    restorePendingStopAfterUploadFailure,
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionImageUploadPending,
    submitTurnMutation,
  ]);

  const syncQueuedTurnsIntoDetail = useCallback((sessionId: string, rows: SessionQueuedTurn[]) => {
    queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
      detailState ? { ...detailState, queuedTurns: rows } : detailState,
    );
  }, [queryClient]);

  const reportQueuedTurnError = useCallback((sessionId: string, error: unknown, fallback: string) => {
    setSessionComposerErrors((current) => ({
      ...current,
      [sessionId]: describeError(error, fallback),
    }));
  }, [describeError, setSessionComposerErrors]);

  const handleFollowupQueueUpdate = useCallback((id: string, text: string) => {
    const sessionId = activeSessionId;
    const content = text.trim();
    if (!sessionId || !content) {
      return;
    }
    // Optimistic edit (same pending-intent style as withdraw): the new text
    // paints at save time while status/pause metadata stay untouched; the
    // PATCH response rebases the authoritative rows and a failure restores
    // the pre-edit text without clobbering fields that moved meanwhile.
    const rowsAtIntent = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.queuedTurns ?? [];
    const snapshotRow = rowsAtIntent.find((row) => row.id === id);
    if (snapshotRow) {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
        detailState
          ? {
            ...detailState,
            queuedTurns: (detailState.queuedTurns ?? []).map((row) =>
              row.id === id ? { ...row, content } : row,
            ),
          }
          : detailState,
      );
    }
    void updateSessionQueuedTurn(sessionId, id, { content })
      .then((rows) => syncQueuedTurnsIntoDetail(sessionId, rows))
      .catch((error) => {
        if (snapshotRow) {
          queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) => {
            if (!detailState) {
              return detailState;
            }
            let reverted = false;
            const queuedTurns = (detailState.queuedTurns ?? []).map((row) => {
              // Roll back only this intent: a row edited again while the
              // failed PATCH was in flight keeps its newer text.
              if (row.id !== id || row.content !== content) {
                return row;
              }
              reverted = true;
              return { ...row, content: snapshotRow.content };
            });
            return reverted ? { ...detailState, queuedTurns } : detailState;
          });
        }
        reportQueuedTurnError(
          sessionId,
          error,
          lang === "zh" ? "修改排队消息失败" : "Failed to update the queued message",
        );
      });
  }, [activeSessionId, lang, queryClient, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  const handleFollowupQueueRemove = useCallback((id: string) => {
    const sessionId = activeSessionId;
    if (!sessionId || pendingQueueWithdrawalIdsRef.current.has(id)) {
      return;
    }
    // Optimistic withdraw (ZCode pending-intent style): the row leaves the bar
    // at click time; the DELETE response only rebases the authoritative rows.
    const rowsAtIntent = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.queuedTurns ?? [];
    const snapshotIndex = rowsAtIntent.findIndex((row) => row.id === id);
    const snapshotRow = snapshotIndex >= 0 ? rowsAtIntent[snapshotIndex] : undefined;
    if (!snapshotRow) {
      return;
    }
    pendingQueueWithdrawalIdsRef.current.add(id);
    queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
      detailState
        ? { ...detailState, queuedTurns: (detailState.queuedTurns ?? []).filter((row) => row.id !== id) }
        : detailState,
    );
    void removeSessionQueuedTurn(sessionId, id)
      .then((rows) => syncQueuedTurnsIntoDetail(sessionId, rows))
      .catch((error) => {
        // Roll back only this intent; authoritative rows that landed meanwhile stay.
        queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
          detailState
            ? {
              ...detailState,
              queuedTurns: restoreQueuedTurnIntoRows(detailState.queuedTurns ?? [], { row: snapshotRow, index: snapshotIndex }),
            }
            : detailState,
        );
        reportQueuedTurnError(
          sessionId,
          error,
          lang === "zh" ? "撤回排队消息失败" : "Failed to withdraw the queued message",
        );
      })
      .finally(() => {
        pendingQueueWithdrawalIdsRef.current.delete(id);
      });
  }, [activeSessionId, lang, queryClient, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  // Steering sends one queued item into the running turn as safe guidance and
  // then withdraws it from the server queue; items carrying attachments or
  // references stay queued because guidance cannot carry them.
  const handleFollowupQueueSteer = useCallback((id: string) => {
    const sessionId = activeSessionId;
    if (!sessionId || pendingQueueWithdrawalIdsRef.current.has(id)) {
      return;
    }
    const item = (sessionFollowupQueues[sessionId] ?? []).find((entry) => entry.id === id);
    if (!item) {
      return;
    }
    if (item.canSteer === false) {
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: lang === "zh"
          ? "这条排队消息带图片或会话引用，无法立即引导；本轮结束后会自动发送。"
          : "This queued message carries images or session references, so it cannot steer the running turn. It sends automatically after the turn ends.",
      }));
      return;
    }
    // Optimistic steer (same pending-intent style as withdraw): the row leaves
    // the bar at click time; guidance + DELETE converge the authoritative rows
    // and either failure rolls the row back into its pre-intent slot. The
    // shared pending set also drops a second click while this steer is still
    // in flight.
    const rowsAtIntent = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.queuedTurns ?? [];
    const snapshotIndex = rowsAtIntent.findIndex((row) => row.id === id);
    const snapshotRow = snapshotIndex >= 0 ? rowsAtIntent[snapshotIndex] : undefined;
    const restoreSteeredRow = () => {
      if (!snapshotRow) {
        return;
      }
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
        detailState
          ? {
            ...detailState,
            queuedTurns: restoreQueuedTurnIntoRows(detailState.queuedTurns ?? [], { row: snapshotRow, index: snapshotIndex }),
          }
          : detailState,
      );
    };
    pendingQueueWithdrawalIdsRef.current.add(id);
    if (snapshotRow) {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
        detailState
          ? { ...detailState, queuedTurns: (detailState.queuedTurns ?? []).filter((row) => row.id !== id) }
          : detailState,
      );
    }
    let guidanceAccepted = false;
    void sessionGuidanceMutation
      .mutateAsync({ sessionId, content: item.text, mode: "safe", steeredQueuedTurnId: id })
      .then(() => {
        guidanceAccepted = true;
        return removeSessionQueuedTurn(sessionId, id);
      })
      .then((rows) => syncQueuedTurnsIntoDetail(sessionId, rows))
      .catch((error) => {
        // Roll back only this intent; authoritative rows that landed meanwhile
        // stay. The guidance mutation surfaces its own copy on its failure, so
        // only the withdraw step reports here.
        restoreSteeredRow();
        if (guidanceAccepted) {
          reportQueuedTurnError(
            sessionId,
            error,
            lang === "zh" ? "立即引导排队消息失败" : "Failed to steer the queued message",
          );
        }
      })
      .finally(() => {
        pendingQueueWithdrawalIdsRef.current.delete(id);
      });
  }, [
    activeSessionId,
    lang,
    queryClient,
    reportQueuedTurnError,
    sessionFollowupQueues,
    sessionGuidanceMutation,
    setSessionComposerErrors,
    syncQueuedTurnsIntoDetail,
  ]);

  const handleFollowupQueueMove = useCallback((fromIndex: number, toIndex: number) => {
    const sessionId = activeSessionId;
    const rows = detail?.queuedTurns ?? [];
    const from = rows[fromIndex];
    const target = rows[toIndex];
    if (!sessionId || fromIndex === toIndex || !from || !target) {
      return;
    }
    // Optimistic reorder (ZCode pending-intent style): the row lands at its
    // target slot at drop time; the PATCH response rebases the authoritative
    // rows and a failure rolls back to the pre-drag order.
    const rowsAtIntent = rows;
    const optimisticRows = [...rowsAtIntent];
    optimisticRows.splice(fromIndex, 1);
    optimisticRows.splice(toIndex, 0, from);
    queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
      detailState ? { ...detailState, queuedTurns: optimisticRows } : detailState,
    );
    void updateSessionQueuedTurn(sessionId, from.id, { position: target.position })
      .then((next) => syncQueuedTurnsIntoDetail(sessionId, next))
      .catch((error) => {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
          detailState
            ? { ...detailState, queuedTurns: restoreQueuedTurnOrder(rowsAtIntent, detailState.queuedTurns ?? []) }
            : detailState,
        );
        reportQueuedTurnError(
          sessionId,
          error,
          lang === "zh" ? "调整排队顺序失败" : "Failed to reorder the queue",
        );
      });
  }, [activeSessionId, detail?.queuedTurns, lang, queryClient, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  // Pausing holds one row out of draining (the server skips paused rows);
  // resuming re-queues it at the tail, mirroring the server semantics.
  const handleFollowupQueueTogglePause = useCallback((id: string, paused: boolean) => {
    const sessionId = activeSessionId;
    if (!sessionId) {
      return;
    }
    void updateSessionQueuedTurn(sessionId, id, { status: paused ? "paused" : "queued" })
      .then((rows) => syncQueuedTurnsIntoDetail(sessionId, rows))
      .catch((error) => reportQueuedTurnError(
        sessionId,
        error,
        paused
          ? (lang === "zh" ? "暂停排队消息失败" : "Failed to pause the queued message")
          : (lang === "zh" ? "恢复排队消息失败" : "Failed to resume the queued message"),
      ));
  }, [activeSessionId, lang, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  // Send-now (Codex sendQueuedNow parity): pin one queued row at the head and
  // stop the running turn; the server keeps the row persisted in the queue so
  // nothing is lost, and the drain submits the pinned row first after the stop
  // settles.
  const handleFollowupQueueSendNow = useCallback((id: string) => {
    const sessionId = activeSessionId;
    if (!sessionId || pendingQueueWithdrawalIdsRef.current.has(id)) {
      return;
    }
    const rowsAtIntent = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.queuedTurns ?? [];
    if (!rowsAtIntent.some((row) => row.id === id)) {
      return;
    }
    // Optimistic pin (same pending-intent style as the other queue intents):
    // the row paints at the head with the send-now flag at click time; the
    // API response rebases the authoritative rows and a rejected stop (the
    // running turn changed or settled meanwhile) restores the pre-click order.
    const optimisticRows = rowsAtIntent
      .map((row) => (row.sendNow ? { ...row, sendNow: false } : row))
      .filter((row) => row.id !== id);
    const snapshotRow = rowsAtIntent.find((row) => row.id === id);
    if (snapshotRow) {
      optimisticRows.unshift({ ...snapshotRow, sendNow: true });
    }
    pendingQueueWithdrawalIdsRef.current.add(id);
    queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
      detailState ? { ...detailState, queuedTurns: optimisticRows } : detailState,
    );
    const expectedTurnId = resolveSessionStopTurnId(detail, activeTurnId);
    void sendNowSessionQueuedTurn(sessionId, id, { expectedTurnId: expectedTurnId || undefined })
      .then((result) => syncQueuedTurnsIntoDetail(sessionId, result.queuedTurns))
      .catch((error) => {
        // Roll back only this intent; authoritative rows that landed meanwhile stay.
        queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (detailState) =>
          detailState
            ? {
              ...detailState,
              queuedTurns: restoreQueuedTurnOrder(rowsAtIntent, detailState.queuedTurns ?? []),
            }
            : detailState,
        );
        reportQueuedTurnError(
          sessionId,
          error,
          lang === "zh" ? "立即发送排队消息失败" : "Failed to send the queued message now",
        );
      })
      .finally(() => {
        pendingQueueWithdrawalIdsRef.current.delete(id);
      });
  }, [activeSessionId, activeTurnId, detail, lang, queryClient, reportQueuedTurnError, syncQueuedTurnsIntoDetail]);

  const handleSubmitTurn = useCallback(() => {
    if (!activeSessionId) {
      return;
    }
    // Optimistic create shells are local-only until the server id is rebased.
    if (isTempSessionId(activeSessionId)) {
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: tempSessionSendBlockedMessage(sessionCreateAttemptState(activeSessionId), lang),
      }));
      return;
    }
    if (sessionBusy && !resolvedEditTarget) {
      const content = activeDraftEffective.trim();
      const hasAttachmentsOrReferences = activeImageAttachments.length > 0 || activeReferenceAttachments.length > 0;
      if (!content && !hasAttachmentsOrReferences) {
        // Codex-style steer: an empty submit on a running turn pushes the first
        // queued item into the active turn instead of waiting for the drain.
        const first = (sessionFollowupQueues[activeSessionId] ?? [])[0];
        if (first) {
          handleFollowupQueueSteer(first.id);
        }
        return;
      }
      if (companionAgentId && (activeImageAttachments.length || activeReferenceAttachments.length)) {
        setSessionComposerErrors((current) => ({
          ...current,
          [activeSessionId]: lang === "zh"
            ? "人物正在回复时只能继续发送文字；附件和会话引用请等当前回复结束后再发送。"
            : "While the companion is replying, only text can be queued. Send attachments or session references after the current reply finishes.",
        }));
        return;
      }
      // The backend owns the queue: this POST lands in the server queue when the
      // requested turn is still running and drains after the turn settles.
      void submitTurnWithAttachments(
        activeSessionId,
        content,
        companionAgentId ? [] : activeImageAttachments,
        companionAgentId ? [] : activeReferenceAttachments,
        mentalModelEnabledForNextTurn,
        runtimeStatusEnabledForNextTurn,
        createClientSubmissionId(activeSessionId),
        true,
        turnModelSelection,
      );
      return;
    }
    const content = activeDraftEffective.trim();
    const clientSubmissionId = createClientSubmissionId(activeSessionId);
    const telemetryActivePhase = activePhase ?? undefined;
    postSubmitTelemetry(
      "browser.chat_submit.requested",
      "Direct chat submit was requested from the composer.",
      activeSessionId,
      {
        content,
        attachmentCount: activeImageAttachments.length,
        referenceCount: activeReferenceAttachments.length,
        mentalModelEnabled: mentalModelEnabledForNextTurn,
        editTargetId: resolvedEditTarget?.messageId,
        composerDisabled,
        sessionBusy,
        activePhase: telemetryActivePhase,
        clientSubmissionId,
      },
    );
    const unsupportedImageAttachments = activeImageAttachments.filter((attachment) => attachment.kind === "image");
    if (unsupportedImageAttachments.length && activeAgentImageInputUnsupported) {
      startUserAction("session_message_submit", {
        sessionId: activeSessionId,
        clientSubmissionId,
        attachmentCount: unsupportedImageAttachments.length,
      }).blocked("image_input_unsupported", {
        imageInputModelId: activeImageInputModelId,
      });
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit image upload was blocked because the active Agent model does not support image input.",
        activeSessionId,
        {
          content,
          attachmentCount: unsupportedImageAttachments.length,
          referenceCount: activeReferenceAttachments.length,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          editTargetId: resolvedEditTarget?.messageId,
          composerDisabled,
          sessionBusy,
          activePhase: telemetryActivePhase,
          guardReason: "image_input_unsupported",
          imageInputModelId: activeImageInputModelId,
          clientSubmissionId,
        },
        "warning",
      );
      setSessionComposerErrors((current) => ({
        ...current,
        [activeSessionId]: lang === "zh" ? "当前 Agent 模型不支持图片输入。" : "The current Agent model does not support image input.",
      }));
      return;
    }
    const guardReason = resolveComposerSubmitGuard({
      composerDisabled,
      content,
      imageAttachmentCount: activeImageAttachments.length,
      referenceAttachmentCount: activeReferenceAttachments.length,
    });
    if (guardReason) {
      startUserAction("session_message_submit", {
        sessionId: activeSessionId,
        clientSubmissionId,
        attachmentCount: activeImageAttachments.length,
        referenceCount: activeReferenceAttachments.length,
      }).blocked(guardReason, {
        composerDisabled,
        sessionBusy,
        activePhase: telemetryActivePhase,
      });
      postSubmitTelemetry(
        "browser.chat_submit.blocked",
        "Direct chat submit was blocked by the composer guard.",
        activeSessionId,
        {
          content,
          attachmentCount: activeImageAttachments.length,
          referenceCount: activeReferenceAttachments.length,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          editTargetId: resolvedEditTarget?.messageId,
          composerDisabled,
          sessionBusy,
          activePhase: telemetryActivePhase,
          guardReason,
          clientSubmissionId,
        },
        "warning",
      );
      return;
    }
    if (resolvedEditTarget) {
      postSubmitTelemetry(
        "browser.chat_submit.edit_resubmit_requested",
        "Edit-resubmit mutation was requested from the composer.",
        activeSessionId,
        {
          content,
          attachmentCount: activeImageAttachments.length,
          referenceCount: activeReferenceAttachments.length,
          mentalModelEnabled: mentalModelEnabledForNextTurn,
          editTargetId: resolvedEditTarget.messageId,
          composerDisabled,
          sessionBusy,
          activePhase: telemetryActivePhase,
          clientSubmissionId,
        },
      );
      const editTarget = resolvedEditTarget;
      const editAttachments = activeImageAttachments;
      const carriedAttachmentIds = resolveEditCarryOverAttachmentIds(detail, editTarget.messageId);
      const editMessages = detail?.messages ?? [];
      const editStartIndex = editMessages.findIndex(
        (message) => String(message.id || "").trim() === editTarget.messageId,
      );
      const continueEdit = () => {
        void (async () => {
          if (!isMountedRef.current) {
            return;
          }
          let editSessionId = resolveComposerSessionId(activeSessionId);
          if (editAttachments.length && imageUploadInFlightRef.current[editSessionId]) {
            return;
          }
          let uploadedAttachmentIds: string[] = [];
          if (editAttachments.length) {
            rememberComposerAttachmentUrls(activeSessionId, editAttachments);
            imageUploadInFlightRef.current[activeSessionId] = true;
            pendingUploadSubmissionRef.current.set(activeSessionId, clientSubmissionId);
            setSessionImageUploadPending((current) => ({
              ...current,
              [activeSessionId]: true,
            }));
            try {
              // Same per-attachment settle as the direct submit: chips that
              // already carry an artifactId ride along without a re-upload, and
              // failures stay in the tray as retryable failed chips.
              let outcomes: ComposerAttachmentUploadOutcome[] = [];
              const needUpload = editAttachments.filter(needsComposerAttachmentUpload);
              if (needUpload.length) {
                setSessionImageAttachments((current) => ({
                  ...current,
                  [activeSessionId]: markComposerAttachmentsUploading(current[activeSessionId] ?? []),
                }));
                const settledOutcomes = await uploadComposerAttachmentsSettled(activeSessionId, needUpload);
                if (!isMountedRef.current) {
                  return;
                }
                editSessionId = resolveComposerSessionId(activeSessionId);
                outcomes = retainOwnedComposerUploadOutcomes(editSessionId, needUpload, settledOutcomes);
                setSessionImageAttachments((current) => ({
                  ...current,
                  [editSessionId]: applyComposerAttachmentUploadOutcomes(current[editSessionId] ?? [], outcomes),
                }));
              }
              editSessionId = resolveComposerSessionId(activeSessionId);
              const failedOutcomes = outcomes.filter(isFailedUploadOutcome);
              if (failedOutcomes.length) {
                setSessionComposerErrors((current) => ({
                  ...current,
                  [editSessionId]: describeError(
                    failedOutcomes[0].error,
                    lang === "zh" ? "图片上传失败" : "Image upload failed",
                  ),
                }));
                restorePendingStopAfterUploadFailure(editSessionId);
                return;
              }
              const stillOwnedAttachments = editAttachments.filter((attachment) => (
                isComposerAttachmentOwned(editSessionId, attachment.id)
              ));
              uploadedAttachmentIds = composerUploadedArtifactIds(
                applyComposerAttachmentUploadOutcomes(stillOwnedAttachments, outcomes),
              );
            } catch (error) {
              if (!isMountedRef.current) {
                return;
              }
              editSessionId = resolveComposerSessionId(activeSessionId);
              setSessionComposerErrors((current) => ({
                ...current,
                [editSessionId]: describeError(error, lang === "zh" ? "图片上传失败" : "Image upload failed"),
              }));
              restorePendingStopAfterUploadFailure(editSessionId);
              return;
            } finally {
              const finishedSessionId = resolveComposerSessionId(activeSessionId);
              if (pendingUploadSubmissionRef.current.get(finishedSessionId) === clientSubmissionId) {
                pendingUploadSubmissionRef.current.delete(finishedSessionId);
              }
              imageUploadInFlightRef.current[finishedSessionId] = false;
              if (isMountedRef.current) {
                setSessionImageUploadPending((current) => ({
                  ...current,
                  [finishedSessionId]: false,
                }));
              }
            }
          }
          if (!isMountedRef.current) {
            return;
          }
          editSessionId = resolveComposerSessionId(activeSessionId);
          editResubmitMutation.mutate({
            sessionId: editSessionId,
            messageId: editTarget.messageId,
            ...(editTarget.nodeId ? { baseMessageId: editTarget.nodeId } : {}),
            clientSubmissionId,
            content,
            attachmentIds: [...carriedAttachmentIds, ...uploadedAttachmentIds],
            mentalModelEnabled: mentalModelEnabledForNextTurn,
            runtimeStatusEnabled: runtimeStatusEnabledForNextTurn,
            turnStatusTail: loadTurnStatusTailConfig(editSessionId),
          });
        })();
      };
      interceptRerun(editMessages, editStartIndex, continueEdit);
      return;
    }
    void submitTurnWithAttachments(
      activeSessionId,
      content,
      activeImageAttachments,
      activeReferenceAttachments,
      mentalModelEnabledForNextTurn,
      runtimeStatusEnabledForNextTurn,
      clientSubmissionId,
      false,
      turnModelSelection,
    );
  }, [
    activeAgentImageInputUnsupported,
    activeDraftEffective,
    activeImageAttachments,
    activeImageInputModelId,
    activePhase,
    activeReferenceAttachments,
    activeSessionId,
    composerDisabled,
    companionAgentId,
    describeError,
    detail,
    editResubmitMutation,
    imageUploadInFlightRef,
    interceptRerun,
    isComposerAttachmentOwned,
    lang,
    mentalModelEnabledForNextTurn,
    runtimeStatusEnabledForNextTurn,
    restorePendingStopAfterUploadFailure,
    resolveComposerSessionId,
    resolvedEditTarget,
    sessionBusy,
    sessionFollowupQueues,
    sessionGuidanceMutation,
    sessionStopping,
    turnModelSelection,
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionImageUploadPending,
    rememberComposerAttachmentUrls,
    retainOwnedComposerUploadOutcomes,
    handleFollowupQueueSteer,
    submitTurnWithAttachments,
  ]);

  const handleEditUserMessage = useCallback((message: ConversationMessage) => {
    if (message.role !== "user") {
      return;
    }
    if (!activeSessionId || sessionBusy) {
      return;
    }
    setSessionEditTargets((current) => ({
      ...current,
      [activeSessionId]: {
        messageId: message.id,
        ...(message.nodeId ? { nodeId: message.nodeId } : {}),
        original: message.content,
      },
    }));
    releaseComposerSessionPreviewUrls(activeSessionId, true);
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
    setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, activeSessionId));
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: message.content,
    }));
    setSessionComposerErrors((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [
    activeSessionId,
    sessionBusy,
    setSessionComposerErrors,
    setSessionDrafts,
    setSessionEditTargets,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
    releaseComposerSessionPreviewUrls,
  ]);

  useEffect(() => {
    if (!activeSessionId || !detail || !activeEditTarget) {
      return;
    }
    const targetStillVisible = (detail.messages ?? []).some(
      (message) => String(message.id || "").trim() === activeEditTarget.messageId,
    );
    if (targetStillVisible) {
      return;
    }
    setSessionEditTargets((current) => {
      const { [activeSessionId]: _removed, ...remaining } = current;
      return remaining;
    });
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
  }, [activeEditTarget, activeSessionId, detail, setSessionDrafts, setSessionEditTargets]);

  const handleCancelEditMessage = useCallback(() => {
    if (!activeSessionId) {
      return;
    }
    setSessionEditTargets((current) => {
      const { [activeSessionId]: _removed, ...remaining } = current;
      return remaining;
    });
    setSessionDrafts((current) => ({
      ...current,
      [activeSessionId]: "",
    }));
    removeStoredSessionDraft(activeSessionId);
    releaseComposerSessionPreviewUrls(activeSessionId, true);
    setSessionImageAttachments((current) => clearSessionImageAttachments(current, activeSessionId));
    setSessionReferenceAttachments((current) => clearSessionReferenceAttachments(current, activeSessionId));
  }, [
    activeSessionId,
    setSessionDrafts,
    setSessionEditTargets,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
    releaseComposerSessionPreviewUrls,
  ]);

  const handleRegenerateAssistantMessage = useCallback((message: ConversationMessage) => {
    if (message.role !== "assistant" || !activeSessionId || sessionBusy) {
      return;
    }
    const messages = detail?.messages ?? [];
    const assistantIndex = messages.findIndex(
      (item) => String(item.id || "").trim() === String(message.id || "").trim(),
    );
    if (assistantIndex <= 0) {
      return;
    }
    let userMessage: ConversationMessage | undefined;
    for (let index = assistantIndex - 1; index >= 0; index -= 1) {
      if (messages[index].role === "user") {
        userMessage = messages[index];
        break;
      }
    }
    if (!userMessage || userMessage.role !== "user") {
      return;
    }
    const rerunUser = userMessage;
    // Branch from the clicked assistant answer when it carries a node id;
    // otherwise fall back to the legacy latest-only regenerate.
    const baseMessageId = String(message.nodeId || rerunUser.nodeId || "").trim();
    const clientSubmissionId = createClientSubmissionId(activeSessionId);
    interceptRerun(messages, assistantIndex, () => {
      regenerateMutation.mutate({
        sessionId: activeSessionId,
        messageId: rerunUser.id,
        ...(baseMessageId ? { baseMessageId } : {}),
        clientSubmissionId,
        content: String(rerunUser.content || ""),
        mentalModelEnabled: mentalModelEnabledForNextTurn,
        runtimeStatusEnabled: runtimeStatusEnabledForNextTurn,
        turnStatusTail: loadTurnStatusTailConfig(activeSessionId),
      });
    });
  }, [
    activeSessionId,
    detail,
    interceptRerun,
    mentalModelEnabledForNextTurn,
    regenerateMutation,
    runtimeStatusEnabledForNextTurn,
    sessionBusy,
  ]);

  // A failed turn has no assistant answer to branch from: retry reruns the
  // latest user message through the same regenerate pipeline as the retry trail.
  const handleRetryFailedTurn = useCallback(() => {
    if (!activeSessionId || sessionBusy) {
      return;
    }
    const messages = detail?.messages ?? [];
    let userMessage: ConversationMessage | undefined;
    let userIndex = -1;
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role === "user") {
        userMessage = messages[index];
        userIndex = index;
        break;
      }
    }
    if (!userMessage || userMessage.role !== "user" || userIndex < 0) {
      return;
    }
    const rerunUser = userMessage;
    const baseMessageId = String(rerunUser.nodeId || "").trim();
    const clientSubmissionId = createClientSubmissionId(activeSessionId);
    interceptRerun(messages, userIndex, () => {
      regenerateMutation.mutate({
        sessionId: activeSessionId,
        messageId: rerunUser.id,
        ...(baseMessageId ? { baseMessageId } : {}),
        clientSubmissionId,
        content: String(rerunUser.content || ""),
        mentalModelEnabled: mentalModelEnabledForNextTurn,
        runtimeStatusEnabled: runtimeStatusEnabledForNextTurn,
        turnStatusTail: loadTurnStatusTailConfig(activeSessionId),
      });
    });
  }, [
    activeSessionId,
    detail,
    interceptRerun,
    mentalModelEnabledForNextTurn,
    regenerateMutation,
    runtimeStatusEnabledForNextTurn,
    sessionBusy,
  ]);

  // Head switching is a server-projected snapshot change: no local tree work,
  // the timeline is replaced by the returned detail.
  const handleSwitchMessageVersion = useCallback((message: ConversationMessage, targetNodeId: string) => {
    if (!activeSessionId || sessionBusy) {
      return;
    }
    const nodeId = String(targetNodeId || "").trim();
    if (!nodeId || nodeId === String(message.nodeId || "").trim()) {
      return;
    }
    switchHeadMutation.mutate({ sessionId: activeSessionId, nodeId });
  }, [activeSessionId, sessionBusy, switchHeadMutation]);

  const handleStopTurn = useCallback(() => {
    if (!activeSessionId || sessionStopping) {
      return;
    }
    const submitPending = Boolean(
      (submitTurnMutation.isPending && submitTurnMutation.variables?.sessionId === activeSessionId)
      || (editResubmitMutation.isPending && editResubmitMutation.variables?.sessionId === activeSessionId)
      || (regenerateMutation.isPending && regenerateMutation.variables?.sessionId === activeSessionId)
    );
    if (!sessionBusy && !submitPending) {
      return;
    }
    void cancelCongestedQueriesForSessionStop(queryClient, activeSessionId);
    const turnId = resolveSessionStopTurnId(detail, activeTurnId);
    if (!turnId) {
      const sessionKey = queryKeys.session(activeSessionId);
      const previousDetail = queryClient.getQueryData<SessionDetail>(sessionKey);
      const stoppingAt = new Date().toISOString();
      const optimisticDetail = markSessionDetailStopping(previousDetail, { requestedAt: stoppingAt });
      if (optimisticDetail) {
        queryClient.setQueryData(sessionKey, optimisticDetail);
      }
      const pendingSubmissionId = submitTurnMutation.isPending
        && submitTurnMutation.variables?.sessionId === activeSessionId
        ? submitTurnMutation.variables.clientSubmissionId
        : editResubmitMutation.isPending
          && editResubmitMutation.variables?.sessionId === activeSessionId
          ? editResubmitMutation.variables.clientSubmissionId
          : regenerateMutation.isPending
            && regenerateMutation.variables?.sessionId === activeSessionId
            ? regenerateMutation.variables.clientSubmissionId
            : pendingUploadSubmissionRef.current.get(activeSessionId);
      pendingStopAfterAcceptRef.current.set(activeSessionId, {
        sessionId: activeSessionId,
        previousDetail,
        stoppingAt,
        clientSubmissionId: pendingSubmissionId,
      });
      return;
    }
    pendingStopAfterAcceptRef.current.delete(activeSessionId);
    stopTurnMutation.mutate({
      sessionId: activeSessionId,
      turnId,
    });
  }, [
    activeSessionId,
    activeTurnId,
    detail,
    editResubmitMutation.isPending,
    editResubmitMutation.variables?.sessionId,
    regenerateMutation.isPending,
    regenerateMutation.variables,
    queryClient,
    sessionBusy,
    sessionStopping,
    stopTurnMutation,
    submitTurnMutation.isPending,
    submitTurnMutation.variables?.sessionId,
  ]);

  const discardDeferredStop = useCallback((sessionId: string, pendingStop: DeferredStopIntent) => {
    pendingStopAfterAcceptRef.current.delete(sessionId);
    if (!pendingStop.stoppingAt) return;
    queryClient.setQueryData<SessionDetail>(queryKeys.session(sessionId), (current) => {
      if (!current) return current;
      return clearSessionDetailStopping(current, {
        requestedAt: pendingStop.stoppingAt!,
        previous: pendingStop.previousDetail,
      });
    });
  }, [queryClient]);

  const dispatchDeferredStop = useCallback((
    sessionId: string,
    pendingStop: DeferredStopIntent,
    acceptedTurnId: string,
    requireCurrentRunningCheck = false,
  ) => {
    const currentDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId));
    if (requireCurrentRunningCheck
      && !isCurrentRunningSessionTurn(currentDetail, sessionId, acceptedTurnId)) {
      discardDeferredStop(sessionId, pendingStop);
      return;
    }
    if (stopTurnMutation.isPending) {
      pendingStop.acceptedTurnId = acceptedTurnId;
      if (requireCurrentRunningCheck) pendingStop.recoveredAcceptedTurnId = acceptedTurnId;
      return;
    }
    pendingStopAfterAcceptRef.current.delete(sessionId);
    stopTurnMutation.mutate({
      sessionId,
      turnId: acceptedTurnId,
      deferredStop: {
        previousDetail: pendingStop.previousDetail,
        stoppingAt: pendingStop.stoppingAt,
      },
    });
  }, [discardDeferredStop, queryClient, stopTurnMutation]);

  // Mutation observers only expose the most recently submitted mutation. A
  // late acceptance from session A can therefore disappear behind a newer
  // submission in session B. Subscribe to the cache so every mutation keeps
  // its own submission identity until the deferred stop is dispatched.
  useEffect(() => {
    const unsubscribe = queryClient.getMutationCache().subscribe((event: MutationCacheNotifyEvent) => {
      if (event.type !== "updated") return;
      const { mutation } = event;
      const variables = mutation.state.variables as {
        sessionId?: unknown;
        clientSubmissionId?: unknown;
        messageId?: unknown;
        recoveredAcceptedTurnId?: unknown;
      } | undefined;
      const sessionId = typeof variables?.sessionId === "string" ? variables.sessionId : "";
      const clientSubmissionId = typeof variables?.clientSubmissionId === "string"
        ? variables.clientSubmissionId
        : "";
      if (!sessionId || !clientSubmissionId) return;
      const pendingStop = pendingStopAfterAcceptRef.current.get(sessionId);
      if (!pendingStop || pendingStop.clientSubmissionId !== clientSubmissionId) return;

      if (mutation.state.status === "error") {
        const recoveredTurnId = typeof variables?.recoveredAcceptedTurnId === "string"
          ? variables.recoveredAcceptedTurnId.trim()
          : "";
        if (recoveredTurnId) {
          pendingStop.recoveredAcceptedTurnId = recoveredTurnId;
          dispatchDeferredStop(sessionId, pendingStop, recoveredTurnId, true);
        } else {
          discardDeferredStop(sessionId, pendingStop);
        }
        return;
      }
      if (mutation.state.status !== "success") return;

      const data = mutation.state.data as {
        sessionId?: unknown;
        turnId?: unknown;
      } | SessionDetail | undefined;
      const isResubmit = mutation.options.mutationKey?.[0] === "session_regenerate"
        || mutation.options.mutationKey?.[0] === "session_edit_resubmit";
      const cachedDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId));
      const acceptedTurnId = isResubmit
        ? exactSubmitTurnId(cachedDetail, clientSubmissionId)
          || exactSubmitTurnId(data as SessionDetail | undefined, clientSubmissionId)
        : data && typeof data === "object" && "turnId" in data
          ? String(data.turnId || "").trim()
          : "";
      if (!acceptedTurnId) {
        if (isResubmit) discardDeferredStop(sessionId, pendingStop);
        return;
      }
      dispatchDeferredStop(sessionId, pendingStop, acceptedTurnId, isResubmit);
    });
    return unsubscribe;
  }, [discardDeferredStop, dispatchDeferredStop, queryClient]);

  useEffect(() => {
    const acceptedSubmit = submitTurnMutation.data;
    const submitVariables = submitTurnMutation.variables;
    const acceptedEdit = editResubmitMutation.data;
    const editVariables = editResubmitMutation.variables;

    for (const [sessionId, pendingStop] of pendingStopAfterAcceptRef.current) {
      if (!pendingStop.clientSubmissionId) continue;
      const submitMatches = acceptedSubmit?.sessionId === sessionId
        && acceptedSubmit.clientSubmissionId === pendingStop.clientSubmissionId;
      const editMatches = editVariables?.sessionId === sessionId
        && editVariables.clientSubmissionId === pendingStop.clientSubmissionId
        && !editResubmitMutation.isPending
        && !editResubmitMutation.error
        && Boolean(acceptedEdit);
      const recoveredSubmitTurnId = submitVariables?.sessionId === sessionId
        && submitVariables.clientSubmissionId === pendingStop.clientSubmissionId
        ? String(submitVariables.recoveredAcceptedTurnId || "").trim()
        : "";
      const recoveredEditTurnId = editVariables?.sessionId === sessionId
        && editVariables.clientSubmissionId === pendingStop.clientSubmissionId
        ? String(editVariables.recoveredAcceptedTurnId || "").trim()
        : "";
      const acceptedTurnId = pendingStop.acceptedTurnId || recoveredSubmitTurnId || recoveredEditTurnId || (submitMatches
        ? String(acceptedSubmit?.turnId || "").trim()
        : editMatches
          ? exactSubmitTurnId(queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId)), pendingStop.clientSubmissionId)
            || exactSubmitTurnId(acceptedEdit, pendingStop.clientSubmissionId)
          : "");
      if (acceptedTurnId) {
        dispatchDeferredStop(
          sessionId,
          pendingStop,
          acceptedTurnId,
          Boolean(pendingStop.recoveredAcceptedTurnId || recoveredSubmitTurnId || recoveredEditTurnId || editMatches),
        );
        return;
      }
      const submitFailed = submitVariables?.sessionId === sessionId
        && submitVariables.clientSubmissionId === pendingStop.clientSubmissionId
        && !submitTurnMutation.isPending
        && Boolean(submitTurnMutation.error)
        && !submitMatches;
      const editFailed = editVariables?.sessionId === sessionId
        && editVariables.clientSubmissionId === pendingStop.clientSubmissionId
        && !editResubmitMutation.isPending
        && Boolean(editResubmitMutation.error)
        && !editMatches;
      if (submitFailed || editFailed) {
        discardDeferredStop(sessionId, pendingStop);
      }
    }

    if (!activeSessionId) return;
    const pendingStop = pendingStopAfterAcceptRef.current.get(activeSessionId);
    if (!pendingStop || pendingStop.clientSubmissionId) return;
    const submitPending = Boolean(
      (submitTurnMutation.isPending && submitTurnMutation.variables?.sessionId === activeSessionId)
      || (editResubmitMutation.isPending && editResubmitMutation.variables?.sessionId === activeSessionId)
      || (regenerateMutation.isPending && regenerateMutation.variables?.sessionId === activeSessionId)
    );
    if (!sessionBusy && !submitPending) {
      pendingStopAfterAcceptRef.current.delete(activeSessionId);
      return;
    }
    if (stopTurnMutation.isPending && stopTurnMutation.variables?.sessionId === activeSessionId) {
      return;
    }
    const turnId = resolveSessionStopTurnId(detail, activeTurnId);
    if (!turnId) {
      return;
    }
    pendingStopAfterAcceptRef.current.delete(activeSessionId);
    stopTurnMutation.mutate({
      sessionId: activeSessionId,
      turnId,
      deferredStop: {
        previousDetail: pendingStop.previousDetail,
        stoppingAt: pendingStop.stoppingAt,
      },
    });
  }, [
    activeSessionId,
    activeTurnId,
    detail,
    editResubmitMutation.isPending,
    editResubmitMutation.variables?.sessionId,
    regenerateMutation.isPending,
    regenerateMutation.variables,
    sessionBusy,
    stopTurnMutation,
    submitTurnMutation.isPending,
    submitTurnMutation.data,
    submitTurnMutation.error,
    submitTurnMutation.variables,
    dispatchDeferredStop,
    discardDeferredStop,
    queryClient,
    editResubmitMutation.data,
    editResubmitMutation.error,
    editResubmitMutation.variables,
    submitTurnMutation.variables?.sessionId,
  ]);

  const handleSubmitGuidance = useCallback((mode: SessionGuidanceMode) => {
    if (!activeSessionId || !sessionBusy || sessionStopping) {
      return;
    }
    const content = activeDraftEffective.trim();
    if (!content) {
      return;
    }
    sessionGuidanceMutation.mutate({
      sessionId: activeSessionId,
      content,
      mode,
    });
  }, [activeDraftEffective, activeSessionId, sessionBusy, sessionGuidanceMutation, sessionStopping]);

  // Deferred stop intents remain keyed by session while the user moves between
  // sessions. A late submit acceptance is matched by submission identity and
  // stopped immediately, without being applied to a newer turn.

  return {
    handleComposerChange,
    handleMentalModelEnabledChange,
    handleRuntimeStatusEnabledChange,
    handleAddComposerAttachments,
    handleRemoveComposerAttachment,
    handleRetryComposerAttachmentUpload,
    handleRetryComposerAttachmentUploads,
    retryComposerAttachmentUploads,
    rebaseComposerPreviewOwners,
    handleAddComposerReference,
    handleRemoveComposerReference,
    handleSubmitTurn,
    handleStopTurn,
    handleSubmitGuidance,
    handleFollowupQueueUpdate,
    handleFollowupQueueRemove,
    handleFollowupQueueMove,
    handleFollowupQueueSteer,
    handleFollowupQueueTogglePause,
    handleFollowupQueueSendNow,
    handleEditUserMessage,
    handleCancelEditMessage,
    handleRegenerateAssistantMessage,
    handleRetryFailedTurn,
    handleSwitchMessageVersion,
    rerunFileChoice,
    confirmRerunFileRestore,
    keepFilesAndRerun,
    dismissRerunFileChoice,
  };
}
