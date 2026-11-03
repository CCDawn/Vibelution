import type { LauncherAssistantDispatch, LauncherAssistantSessionEvent } from "../../api/launcherAssistant";
import type { PetActivityTone, PetAnimationState } from "../../api/types/petActivity";
import type { ConversationMessage, SessionDetail, SessionQueuedTurn } from "../../api/types";
import { exactAcceptedSubmitTurnId, findSubmitAcceptanceEvidence } from "../chat/chatSubmitAcceptanceReadback";
import {
  buildComposerContextRingModel, resolveComposerContextUsage,
  type ComposerContextRingModel,
} from "../chat/composerContextModel";
import { promptSegmentDisplayLabel } from "../chat/chatRoutePresentation";
import { hasExecutionOwnership, resolveSessionActivity, type SessionActivitySource } from "../sessionActivityState";

export type LauncherAssistantSubmission = { message: string; requestId: string; draftSnapshot?: string; attachmentIds?: string[]; attachmentSnapshotIds?: string[]; preserveDraft?: true };
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
  if (row) return { receipt: receipt.observed ? receipt : { ...receipt, observed: true }, admittedTurnId: "", removed: false };
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
): LauncherAssistantSubmission | null {
  if (outstanding) return outstanding;
  const message = draft.trim();
  if (!message && !attachmentIds.length) return null;
  return attachmentIds.length ? { message, requestId: createId(), draftSnapshot: draft, attachmentIds, attachmentSnapshotIds }
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
      || error.message === "ASSISTANT_REQUEST_INVALID");
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

/** Only an authoritative snapshot frame, or a delta that explicitly reports
 * `done === true`, for this very session re-reads detail. Heartbeats, foreign
 * sessions, unfinished deltas and unknown types only prove the channel alive;
 * `done` is outside the frozen envelope, so it is probed and never inferred. */
export function launcherAssistantSessionEventRefreshesDetail(event: LauncherAssistantSessionEvent, sessionId: string): boolean {
  if (!sessionId || event.sessionId !== sessionId) return false;
  if (event.type === "session_detail") return true;
  return event.type === "assistant_delta" && (event as { done?: unknown }).done === true;
}

export type LauncherAssistantLiveText = { turnId: string; text: string };

/** One pushed assistant_delta reduced to the live streaming preview. Only an
 * unfinished delta carrying both the generating turn's id and answer text
 * updates the preview; an explicit `done` finishes it (the caller clears the
 * preview, and the existing refresh gate re-reads detail for the committed
 * answer). Heartbeats, foreign sessions and identity-only envelopes (older
 * shell, oversized-frame fallback) leave the preview untouched, so absence
 * always degrades to today's polling-only path. */
export function launcherAssistantLiveTextFromEvent(
  event: LauncherAssistantSessionEvent, sessionId: string,
): { update: LauncherAssistantLiveText | null; finished: boolean } {
  if (!sessionId || event.sessionId !== sessionId || event.type !== "assistant_delta") return { update: null, finished: false };
  if ((event as { done?: unknown }).done === true) return { update: null, finished: true };
  const turnId = typeof event.turnId === "string" ? event.turnId.trim() : "";
  const text = typeof event.textPreview === "string" ? event.textPreview.trim() : "";
  if (!turnId || !text) return { update: null, finished: false };
  return { update: { turnId, text }, finished: false };
}

function launcherAssistantTurnIdOf(message: ConversationMessage): string {
  return String(
    (message.role === "assistant" ? message.turnId : undefined)
    ?? message.metadata?.turnId
    ?? message.metadata?.turn_id
    ?? "",
  ).replace(/^live:/, "").trim();
}

/** A detail contradiction that retires the streaming preview: another turn took
 * over generation, or this turn's answer already committed as a durable row.
 * The native live-overlay row for the same turn is not a commitment — both may
 * paint while the pump preview is the lower-latency source. */
export function launcherAssistantLiveTextIsStale(
  live: LauncherAssistantLiveText,
  source: Pick<SessionDetail, "messages" | "activeTurnId"> | undefined,
): boolean {
  if (!source) return false;
  const turnId = live.turnId.replace(/^live:/, "").trim();
  const activeTurnId = String(source.activeTurnId || "").replace(/^live:/, "").trim();
  if (activeTurnId && activeTurnId !== turnId) return true;
  return (source.messages ?? []).some(message => message.role === "assistant"
    && launcherAssistantTurnIdOf(message) === turnId
    && message.metadata?.kind !== "session_live_overlay"
    && !/-message-(live|active)-/.test(message.id));
}

const LAUNCHER_ASSISTANT_LIVE_ROW_ID_PREFIX = "launcher-assistant-live-";

/** The streaming preview as the shared conversation's active-turn overlay row:
 * one revisioned `agent_message` item on a running assistant turn. The timeline
 * projection already owns overlay dedupe (a native live-overlay row for the
 * same turn keeps painting if the preview is absent, and the committed row
 * outranks both), so this stays a display hint that never fights the detail
 * authority. */
export function launcherAssistantActiveTurnMessage(
  sessionId: string, live: LauncherAssistantLiveText,
): ConversationMessage {
  const itemId = `${LAUNCHER_ASSISTANT_LIVE_ROW_ID_PREFIX}${live.turnId}`;
  return {
    id: `${itemId}-row`,
    role: "assistant",
    timestamp: new Date().toISOString(),
    turnId: live.turnId,
    status: "running",
    turnItems: [{
      id: itemId, itemId, version: 3, sessionId, turnId: live.turnId,
      status: "running", revision: 1, sequence: 1,
      type: "agent_message", phase: "final_answer", text: live.text,
    }],
    metadata: { kind: "session_active_turn_layer", sessionId, activeStatusSource: "assistant_delta" },
  };
}

export function launcherAssistantPollInterval(visible: boolean, source?: LauncherAssistantActivitySource, acceptedTurnId?: string, queuedAcceptance?: LauncherAssistantQueuedAcceptance | null, pendingRequestIds: readonly string[] = [], options: { sseHealthy?: boolean } = {}): number | false {
  if (!visible) return false;
  // Every "keep reading" branch below shares one cadence: a healthy push channel
  // already refreshes detail on events, so polling only backstops it.
  const active = options.sseHealthy ? SSE_FALLBACK_POLL_MS : ACTIVE_POLL_MS;
  for (const requestId of pendingRequestIds) {
    const recovered = launcherAssistantRequestReadback(source, requestId);
    if (!recovered || (recovered.turnId && source?.activeTurnId !== recovered.turnId && source?.lastTurnTerminalTurnId !== recovered.turnId)) return active;
  }
  if (queuedAcceptance && !queuedAcceptance.observed) return active;
  if (source?.queuedTurns?.some(row => row.status === "queued" || row.status === "starting")) return active;
  // Acceptance precedes the detail projection. A stale ready/previous terminal
  // must not retire the newly accepted Turn before it becomes authoritative.
  if (acceptedTurnId && source?.activeTurnId !== acceptedTurnId && source?.lastTurnTerminalTurnId !== acceptedTurnId) return active;
  if (!source || hasExecutionOwnership(resolveSessionActivity(source).execution)) return active;
  return false;
}

/** Receipt status belongs to the native task; do not project it as business acceptance. */
export function launcherDispatchLabel(row: LauncherAssistantDispatch, lang: "zh" | "en"): string {
  if (row.lastError) return lang === "zh" ? "回执暂不可用" : "Receipt unavailable";
  const status = row.receipt?.status;
  return status ? `${lang === "zh" ? "原生任务状态" : "Native task status"}: ${status}`
    : lang === "zh" ? "等待原生任务回执" : "Waiting for native task receipt";
}

/** Humanized receipt lead for the embedded page rows. Same branch shape as
 * launcherDispatchLabel (error → unavailable, known enum → word, else
 * waiting), but terminal native statuses read as plain words and an unknown
 * enum keeps the raw fallback instead of pretending success. The floating
 * window keeps launcherDispatchLabel untouched. */
export function launcherDispatchReceiptLabel(row: LauncherAssistantDispatch, lang: "zh" | "en"): string {
  if (row.lastError) return lang === "zh" ? "回执暂不可用" : "Receipt unavailable";
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
