import type { LauncherAssistantControlContinuation, LauncherAssistantDispatch, LauncherAssistantSessionEvent } from "../../api/launcherAssistant";
import type { PetActivityTone, PetAnimationState } from "../../api/types/petActivity";
import type { ConversationMessage, SessionDetail, SessionPendingQuestion, SessionQueuedTurn, SessionReferenceAttachment } from "../../api/types";
import { exactAcceptedSubmitTurnId, findSubmitAcceptanceEvidence } from "../chat/chatSubmitAcceptanceReadback";
import { isLocalQueuedSubmit } from "../chat/sessionSubmitProjection";
import {
  buildComposerContextRingModel, resolveComposerContextUsage,
  type ComposerContextRingModel,
} from "../chat/composerContextModel";
import { promptSegmentDisplayLabel } from "../chat/chatRoutePresentation";
import { dispatchFailureCodeLabel } from "./assistantTasks/assistantTaskPresentation";
import { hasExecutionOwnership, resolveSessionActivity, type SessionActivitySource } from "../sessionActivityState";

export type LauncherAssistantQuestionDraft = { question: SessionPendingQuestion; value: string };
export type LauncherAssistantSubmission = { message: string; requestId: string; draftSnapshot?: string; attachmentIds?: string[]; attachmentSnapshotIds?: string[]; references?: SessionReferenceAttachment[]; preserveDraft?: true; answerQuestion?: SessionPendingQuestion; controlContinuation?: LauncherAssistantControlContinuation };
export type LauncherAssistantQueuedAcceptance = { id: string; clientSubmissionId: string; observed: boolean };
type LauncherAssistantActivitySource = SessionActivitySource & Partial<Pick<SessionDetail, "messages" | "activeTask">>
  & { queuedTurns?: Array<Pick<SessionQueuedTurn, "id" | "status" | "clientSubmissionId">> };

/** Read-only recovery of the original request; queue IDs are never Turn IDs. */
export function launcherAssistantRequestReadback(source: LauncherAssistantActivitySource | undefined, requestId: string): {
  turnId: string; queuedAcceptance: LauncherAssistantQueuedAcceptance | null;
} | null {
  if (!source || !requestId) return null;
  const detail = source as SessionDetail;
  const evidence = findSubmitAcceptanceEvidence(detail, requestId);
  const turnId = evidence ? exactAcceptedSubmitTurnId(detail, requestId, evidence) : "";
  if (turnId) return { turnId, queuedAcceptance: null };
  const queued = source.queuedTurns?.find(row => row.clientSubmissionId === requestId && row.id.trim());
  return queued ? { turnId: "", queuedAcceptance: { id: queued.id, clientSubmissionId: requestId, observed: true } } : null;
}

/** Queue IDs identify native rows, never native Turns. Correlate admission by submission ID. */
export function launcherAssistantQueueReadback(
  source: Pick<SessionDetail, "queuedTurns" | "messages" | "activeTask"> | undefined,
  receipt: LauncherAssistantQueuedAcceptance | null,
): { receipt: LauncherAssistantQueuedAcceptance | null; admittedTurnId: string; removed: boolean } {
  if (!source || !receipt) return { receipt, admittedTurnId: "", removed: false };
  const row = source.queuedTurns?.find(item => item.id === receipt.id && item.clientSubmissionId === receipt.clientSubmissionId);
  if (row) return { receipt: isLocalQueuedSubmit(row as SessionQueuedTurn) || receipt.observed ? receipt : { ...receipt, observed: true }, admittedTurnId: "", removed: false };
  const detail = source as SessionDetail;
  const evidence = findSubmitAcceptanceEvidence(detail, receipt.clientSubmissionId);
  const admittedTurnId = evidence ? exactAcceptedSubmitTurnId(detail, receipt.clientSubmissionId, evidence) : "";
  if (admittedTurnId) return { receipt: null, admittedTurnId, removed: false };
  // A vanished observed row is a removal, not success. Never infer admission from time/status.
  return { receipt, admittedTurnId: "", removed: receipt.observed };
}

export function launcherAssistantQueueLabel(status: string, lang: "zh" | "en"): string {
  const labels: Record<string, readonly [string, string]> = {
    queued: ["已排队", "Queued"], starting: ["排队消息正在入场", "Queued message starting"],
    paused: ["排队消息已暂停", "Queued message paused"], blocked: ["排队消息需要处理", "Queued message blocked"],
  };
  return labels[status]?.[lang === "zh" ? 0 : 1] || `${lang === "zh" ? "原生队列状态" : "Native queue status"}: ${status}`;
}

/** An unconfirmed send is retried verbatim, even if a caller supplies a new draft. */
export function launcherAssistantSubmission(
  outstanding: LauncherAssistantSubmission | null,
  draft: string,
  createId: () => string = () => crypto.randomUUID(),
  attachmentIds: string[] = [],
  attachmentSnapshotIds: string[] = [],
  references: SessionReferenceAttachment[] = [],
): LauncherAssistantSubmission | null {
  if (outstanding) return outstanding;
  const message = draft.trim();
  if (!message && !attachmentIds.length && !references.length) return null;
  return references.length || attachmentIds.length
    ? { message, requestId: createId(), draftSnapshot: draft,
        ...(attachmentIds.length ? { attachmentIds, attachmentSnapshotIds } : {}),
        ...(references.length ? { references } : {}) }
    : { message, requestId: createId(), draftSnapshot: draft };
}

/** Matches the native host's Pydantic `Message.message` max_length and the
 * desktop bridge's pre-admission length check, both 64,000 characters. The
 * composer pre-checks locally so an over-long draft can never dead-end in a
 * rejection loop. Callers pass the exact string that would be sent. */
export const LAUNCHER_ASSISTANT_MAX_MESSAGE_CHARS = 64_000;

export function launcherAssistantMessageOverLimit(message: string): boolean {
  return message.length > LAUNCHER_ASSISTANT_MAX_MESSAGE_CHARS;
}

/** A refusal that provably happened before any admission (renderer-side payload
 * validation, or the desktop bridge rejecting the envelope before the host RPC)
 * leaves nothing queued: the composer may unlock immediately. Everything else —
 * transport loss, timeouts, an unconfirmed host response — keeps the
 * conservative unconfirmed lock because the outcome is genuinely unknown.
 * Classification is structural (name/message) because Electron re-creates the
 * error across the context bridge. */
export function launcherAssistantSendDefinitelyRejected(error: unknown): boolean {
  return error instanceof Error
    && (error.name === "LauncherAssistantRejectedError"
      // The desktop bridge's pre-admission HostError code, surfaced as the
      // caught Error's message; thrown only before the send RPC leaves main.
      || error.message === "ASSISTANT_REQUEST_INVALID"
      || /^Error invoking remote method '[^']+': (?:Error: )?ASSISTANT_REQUEST_INVALID$/.test(error.message));
}

/** Host codes that prove the send never entered execution: quiescence gates
 * (503, pre-admission — the native layer explicitly asks callers to retain and
 * retry the request) and the 409 session-changed conflict (the requestId is
 * idempotent, so a verbatim retry is safe). ASSISTANT_MODEL_BUSY stays out —
 * the api layer already rewrites it into a friendly switch-model message —
 * and so do timeouts and transport failures: their outcome is genuinely
 * unknown and keeps the conservative unconfirmed lock. Codes are matched
 * structurally (name/message, exact equality plus the Electron context-bridge
 * wrapper) exactly like launcherAssistantSendDefinitelyRejected. */
const LAUNCHER_ASSISTANT_RETRYABLE_BUSY_CODES = ["ASSISTANT_QUIESCING", "ASSISTANT_QUIESCENCE_BUSY", "ASSISTANT_STOPPING", "ASSISTANT_NOT_READY", "ASSISTANT_SESSION_CONFLICT"] as const;

function launcherAssistantSendBusyMatch(error: Error, code: string): boolean {
  return error.name === code || error.message === code
    || new RegExp(`^Error invoking remote method '[^']+': (?:Error: )?${code}$`).test(error.message);
}

export function launcherAssistantSendRetryableBusy(error: unknown): boolean {
  return error instanceof Error
    && LAUNCHER_ASSISTANT_RETRYABLE_BUSY_CODES.some(code => launcherAssistantSendBusyMatch(error, code));
}

/** The matched busy code for diagnostics feedback; "" when not retryable-busy. */
export function launcherAssistantSendBusyCode(error: unknown): string {
  if (!(error instanceof Error)) return "";
  return LAUNCHER_ASSISTANT_RETRYABLE_BUSY_CODES.find(code => launcherAssistantSendBusyMatch(error, code)) ?? "";
}

/** The desktop bridge folds AssistantHost.start() refusals into stable codes.
 * ASSISTANT_LIFECYCLE_CLOSING means the resident host is retiring behind a
 * shell exit — including an exit Main later cancelled while it resumes the
 * assistant. That is never the cold-boot backend wait, so the page states it
 * explicitly instead of claiming the workbench backend is still starting.
 * Structural match (name/message plus the Electron context-bridge wrapper),
 * identical to the retryable-busy codes. */
export function launcherAssistantLifecycleClosing(error: unknown): boolean {
  return error instanceof Error && launcherAssistantSendBusyMatch(error, "ASSISTANT_LIFECYCLE_CLOSING");
}

export function launcherAssistantActivity(source: SessionActivitySource = {}): {
  tone: PetActivityTone; animationState: PetAnimationState;
} {
  const state = resolveSessionActivity(source);
  if (state.outcome === "failed") return { tone: "error", animationState: "alert" };
  if (state.execution === "paused") return { tone: "approval", animationState: "waiting" };
  if (hasExecutionOwnership(state.execution)) return { tone: "running", animationState: "thinking" };
  // Resting/ready says nothing about whether the user's goal was achieved.
  return { tone: "idle", animationState: "idle" };
}

/** Cold-boot wait cadence while the first backend status read has never
 * succeeded (the workbench backend may still be starting). The first probe
 * follows a failure after 2s; the interval doubles per elapsed 4s window and
 * caps at 16s, so a booting backend is joined promptly while a long outage
 * never hammers the host RPC. */
export const LAUNCHER_ASSISTANT_WAIT_POLL_FIRST_MS = 2_000;
export const LAUNCHER_ASSISTANT_WAIT_POLL_MAX_MS = 16_000;

export function launcherAssistantWaitInterval(waitStartedAt: number | null, now: number): number {
  if (waitStartedAt === null || !Number.isFinite(waitStartedAt)) return LAUNCHER_ASSISTANT_WAIT_POLL_FIRST_MS;
  const age = Number.isFinite(now) ? Math.max(0, now - waitStartedAt) : 0;
  const steps = Math.min(8, Math.floor(age / (LAUNCHER_ASSISTANT_WAIT_POLL_FIRST_MS * 2)));
  return Math.min(LAUNCHER_ASSISTANT_WAIT_POLL_MAX_MS, LAUNCHER_ASSISTANT_WAIT_POLL_FIRST_MS * 2 ** steps);
}

/** Any pushed session event (heartbeats included, ~15s cadence) seen inside this
 * window proves the push channel alive; two missed heartbeats mark it dead. */
export const LAUNCHER_ASSISTANT_SSE_HEALTH_WINDOW_MS = 35_000;

/** Active polling cadence without a push channel, and the safety-net cadence
 * once events drive detail refreshes. Idle sessions never poll either way. */
const ACTIVE_POLL_MS = 2_000;
const SSE_FALLBACK_POLL_MS = 10_000;

export function launcherAssistantSseHealthy(lastEventAt: number | null | undefined, now: number): boolean {
  return typeof lastEventAt === "number" && Number.isFinite(lastEventAt) && now - lastEventAt <= LAUNCHER_ASSISTANT_SSE_HEALTH_WINDOW_MS;
}

/** Status-poll degradation thresholds: the red banner requires the failure to
 * persist (two consecutive failed polls, or no successful read for 30s) AND
 * the push channel to be dead. A single failed poll stays a weak hint. */
export const LAUNCHER_ASSISTANT_STATUS_DEGRADE_FAILURES = 2;
export const LAUNCHER_ASSISTANT_STATUS_DEGRADE_MAX_SILENCE_MS = 30_000;

export type LauncherAssistantStatusDegradeTone = "quiet" | "soft" | "error";

/** Debounced tone for a status poll whose session content is mounted. The
 * never-succeeded cold boot is owned by the backend-wait surface (quiet). A
 * silence gap alone proves nothing while the poller is paused (no error and
 * no attempt in flight): absence of asks is not failure evidence. While push
 * events keep arriving the conversation still updates live, so a healthy
 * push channel caps the tone at the weak hint no matter how long the poll
 * has been failing. */
export function launcherAssistantStatusDegradeTone(input: {
  isError: boolean; isFetching: boolean; hasData: boolean;
  consecutiveFailures: number; lastSuccessAt: number;
  now: number; sseHealthy: boolean;
}): LauncherAssistantStatusDegradeTone {
  if (!input.hasData) return "quiet";
  const silenceExceeded = Number.isFinite(input.lastSuccessAt)
    && input.now - input.lastSuccessAt > LAUNCHER_ASSISTANT_STATUS_DEGRADE_MAX_SILENCE_MS;
  const failing = input.isError || input.isFetching && silenceExceeded;
  if (!failing) return "quiet";
  if (input.sseHealthy) return "soft";
  const escalated = input.consecutiveFailures >= LAUNCHER_ASSISTANT_STATUS_DEGRADE_FAILURES || silenceExceeded;
  return escalated ? "error" : "soft";
}

/** Only an authoritative snapshot frame, or a delta that explicitly reports
 * `done === true`, for this very session re-reads detail. Heartbeats, foreign
 * sessions, unfinished deltas and unknown types only prove the channel alive;
 * `done` is outside the frozen envelope, so it is probed and never inferred. */
export function launcherAssistantSessionEventRefreshesDetail(event: LauncherAssistantSessionEvent, sessionId: string): boolean {
  if (!sessionId || event.sessionId !== sessionId) return false;
  if (event.type === "session_detail") return true;
  return event.type === "assistant_delta" && (event as { done?: unknown }).done === true;
}

/** A visible window polls every "keep reading" reason below. A hidden window
 * keeps exactly one lifeline: reading back outstanding sends, pinned to the
 * fixed fallback cadence — its push subscription is torn down with the window,
 * so a once-healthy flag would otherwise decay into the 2s active cadence on
 * stale evidence instead of admitting the channel is gone. */
export function launcherAssistantPollInterval(visible: boolean, source?: LauncherAssistantActivitySource, acceptedTurnId?: string, queuedAcceptance?: LauncherAssistantQueuedAcceptance | null, pendingRequestIds: readonly string[] = [], options: { sseHealthy?: boolean } = {}): number | false {
  const hiddenReadback = !visible && pendingRequestIds.length > 0;
  if (!visible && !hiddenReadback) return false;
  // Every "keep reading" branch below shares one cadence: a healthy push channel
  // already refreshes detail on events, so polling only backstops it. Hidden
  // readback always takes the fallback cadence regardless of the stale flag.
  const active = visible && !options.sseHealthy ? ACTIVE_POLL_MS : SSE_FALLBACK_POLL_MS;
  for (const requestId of pendingRequestIds) {
    const recovered = launcherAssistantRequestReadback(source, requestId);
    if (!recovered || (recovered.turnId && source?.activeTurnId !== recovered.turnId && source?.lastTurnTerminalTurnId !== recovered.turnId)) return active;
  }
  // Hidden: the outstanding requests all read back (the route's state settles
  // on the next render), and no branch below justifies a hidden poll.
  if (!visible) return false;
  if (queuedAcceptance && !queuedAcceptance.observed) return active;
  if (source?.queuedTurns?.some(row => row.status === "queued" || row.status === "starting")) return active;
  // Acceptance precedes the detail projection. A stale ready/previous terminal
  // must not retire the newly accepted Turn before it becomes authoritative.
  if (acceptedTurnId && source?.activeTurnId !== acceptedTurnId && source?.lastTurnTerminalTurnId !== acceptedTurnId) return active;
  if (!source || hasExecutionOwnership(resolveSessionActivity(source).execution)) return active;
  return false;
}

/** Receipt status belongs to the native task; do not project it as business acceptance.
 * A known failure code reads as its short label; unknown codes keep the generic fallback. */
export function launcherDispatchLabel(row: LauncherAssistantDispatch, lang: "zh" | "en"): string {
  if (row.lastError) {
    return dispatchFailureCodeLabel(row.lastError.code, lang)
      || (lang === "zh" ? "回执暂不可用" : "Receipt unavailable");
  }
  const status = row.receipt?.status;
  return status ? `${lang === "zh" ? "原生任务状态" : "Native task status"}: ${status}`
    : lang === "zh" ? "等待原生任务回执" : "Waiting for native task receipt";
}

/** Humanized receipt lead for the embedded page rows. Same branch shape as
 * launcherDispatchLabel (error → known-code label, else unavailable, known
 * enum → word, else waiting), but terminal native statuses read as plain
 * words and an unknown enum keeps the raw fallback instead of pretending
 * success. The floating window keeps launcherDispatchLabel untouched. */
export function launcherDispatchReceiptLabel(row: LauncherAssistantDispatch, lang: "zh" | "en"): string {
  if (row.lastError) {
    return dispatchFailureCodeLabel(row.lastError.code, lang)
      || (lang === "zh" ? "回执暂不可用" : "Receipt unavailable");
  }
  const status = row.receipt?.status;
  const words: Record<string, readonly [string, string]> = {
    succeeded: ["成功", "Succeeded"], failed: ["失败", "Failed"],
    cancelled: ["已取消", "Cancelled"], timed_out: ["已超时", "Timed out"],
  };
  if (status && words[status]) return words[status][lang === "zh" ? 0 : 1];
  return status ? `${lang === "zh" ? "原生任务状态" : "Native task status"}: ${status}`
    : lang === "zh" ? "待回执" : "Awaiting receipt";
}

/** The assistant identity's bound dialogue model, read-only. The launcher
 * surface never edits model parameters (no native verb), so this stays a plain
 * display string; an unset binding says so instead of pretending a model. */
export function launcherAssistantModelDisplay(modelId: string | undefined | null, lang: "zh" | "en"): string {
  const id = String(modelId ?? "").trim();
  return id || (lang === "zh" ? "未绑定模型" : "No model bound");
}

/** The launcher host's lightweight dictionary avoids the workbench dictionary
 * loader; segment labels fall back to promptSegmentDisplayLabel's built-in
 * mapping, and only unknown keys degrade to the generic "other" name. */
const launcherIdentityTranslator = (key: string) => key;

/** Read-only composer context ring from the native detail's usage projections.
 * Same builders as the chat page; the cache-diagnostics handoff and the
 * auto-compression countdown stay off because the launcher surface mounts
 * neither the diagnostics dialog nor the runtime compression settings. */
export function launcherAssistantContextRing(
  detail: Pick<SessionDetail, "contextUsage" | "lastContextComposition" | "lastCacheComposition" | "llmUsage"> | undefined,
  lang: "zh" | "en",
): ComposerContextRingModel | null {
  if (!detail || (!detail.contextUsage && !detail.lastContextComposition)) return null;
  const usage = resolveComposerContextUsage({
    contextUsage: detail.contextUsage ?? null,
    contextComposition: detail.lastContextComposition ?? null,
  });
  const cache = detail.lastCacheComposition;
  return buildComposerContextRingModel({
    usageUsed: usage.used,
    usageLimit: usage.limit,
    hitPercent: Math.round(Math.max(0, Math.min(1, cache?.cacheHitRate ?? 0)) * 100),
    detailAvailable: false,
    segments: (detail.lastContextComposition?.segments ?? []).map(segment => ({
      ...segment,
      label: promptSegmentDisplayLabel(segment, lang, launcherIdentityTranslator),
      contentPreview: segment.description,
    })),
    lang,
    cacheSource: cache?.source,
    cacheUsageObserved: cache?.cacheUsageObserved,
    cachedInputTokens: cache?.cachedInputTokens,
    cacheCreationInputTokens: cache?.cacheCreationInputTokens,
    tokensPerSecond: detail.llmUsage?.tokensPerSecond ?? null,
  });
}

/** The assistant's edit affordance backfills the composer with a previous user
 * message's text for a NEW send: the native facade has no edit-resubmit verb,
 * so history is never replaced and the copy must not claim it. Returns null
 * for non-user rows or empty content (nothing honest to backfill). */
export function launcherAssistantEditBackfillDraft(message: { role: ConversationMessage["role"]; content?: string }): string | null {
  if (message.role !== "user") return null;
  const content = String(message.content ?? "");
  return content.trim() ? content : null;
}
