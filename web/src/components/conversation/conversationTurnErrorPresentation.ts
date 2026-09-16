import type { ConversationMessage, SessionTurnError } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";

export type TurnErrorDiagnosticRow = { label: string; value: string };
export type ConversationLanguage = "zh" | "en";
export type TurnErrorRecoveryAction = "compress_context";

/**
 * errorType -> Chat dictionary key for the human-readable chip label. The
 * table covers every errorType the backend writes into turn-error messages
 * (signals_format._failure_error_type plus explicit call-site types);
 * unmapped values (e.g. raw exception class names) fall back to the runtime
 * label and keep the raw code reachable via the chip tooltip.
 */
export const CONVERSATION_TURN_ERROR_TYPE_LABEL_KEYS: Record<string, TranslationKey> = {
  provider_protocol_error: "turnErrorTypeProviderProtocolError",
  provider_upstream_error: "turnErrorTypeProviderUpstreamError",
  provider_error: "turnErrorTypeProviderError",
  runtime_error: "turnErrorTypeRuntimeError",
  prompt_cache_unsupported: "turnErrorTypePromptCacheUnsupported",
  resource_lease_conflict: "turnErrorTypeResourceLeaseConflict",
  agent_llm_resolution_failed: "turnErrorTypeAgentLlmResolutionFailed",
  turn_persistence_failed: "turnErrorTypeTurnPersistenceFailed",
  StaleChatTurnSettled: "turnErrorTypeStaleChatTurnSettled",
};

/** Budget-family failure evidence: recovery is compression / limit adjustment. */
const TURN_ERROR_BUDGET_REASON_CODES = new Set([
  "context_budget_exhausted",
  "budget_exhausted",
  "token_budget_exhausted",
  "context_limit",
]);

function metadataText(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function turnErrorLabel(lang: ConversationLanguage, zh: string, en: string) {
  return lang === "zh" ? zh : en;
}

function isTurnErrorDiagnosticRow(row: TurnErrorDiagnosticRow | null): row is TurnErrorDiagnosticRow {
  return Boolean(row);
}

export function resolveConversationTurnErrorType(message: ConversationMessage) {
  const raw = message.metadata?.errorType ?? message.metadata?.error_type;
  return typeof raw === "string" ? raw.trim() : "";
}

/**
 * Human-readable label key for a raw turn errorType; "" when no type is set.
 * Unknown codes fall back to the runtime label (the raw code stays reachable
 * in the diagnostics surface via the caller's tooltip).
 */
export function resolveTurnErrorTypeLabelKey(rawErrorType: string): TranslationKey | "" {
  const normalized = String(rawErrorType || "").trim();
  if (!normalized) {
    return "";
  }
  return CONVERSATION_TURN_ERROR_TYPE_LABEL_KEYS[normalized] ?? "turnErrorTypeRuntimeError";
}

function budgetFailureEvidence(fields: Record<string, unknown>) {
  const text = (key: string) => String(fields[key] ?? "").trim().toLowerCase();
  if (text("failureDisposition") === "budget_or_context") {
    return true;
  }
  if (TURN_ERROR_BUDGET_REASON_CODES.has(text("reasonCode")) || TURN_ERROR_BUDGET_REASON_CODES.has(text("reason_code"))) {
    return true;
  }
  return text("failureCategory").includes("budget");
}

/**
 * Directed recovery action for a persisted failed turn; budget-family
 * failures point at context compression instead of a plain retry.
 */
export function resolveConversationTurnErrorRecoveryAction(
  message: ConversationMessage,
): TurnErrorRecoveryAction | "" {
  const fields = (message.metadata ?? {}) as Record<string, unknown>;
  return budgetFailureEvidence(fields) ? "compress_context" : "";
}

/** Same detection for the live SessionTurnError banner. */
export function resolveSessionTurnErrorRecoveryAction(
  turnError: Record<string, unknown>,
): TurnErrorRecoveryAction | "" {
  return budgetFailureEvidence(turnError) ? "compress_context" : "";
}

export function buildConversationTurnErrorReasonRows(
  message: ConversationMessage,
  lang: ConversationLanguage,
): TurnErrorDiagnosticRow[] {
  return buildTurnErrorDiagnosticRows(message.metadata, lang);
}

export function buildTurnErrorDiagnosticRows(
  metadata: Record<string, unknown> | undefined,
  lang: ConversationLanguage,
): TurnErrorDiagnosticRow[] {
  const summary = metadataText(metadata, "reasonSummary") || metadataText(metadata, "reason_summary");
  const detail = metadataText(metadata, "reasonDetail") || metadataText(metadata, "reason_detail");
  const code = metadataText(metadata, "reasonCode") || metadataText(metadata, "reason_code");
  const httpStatus = metadataText(metadata, "httpStatus") || metadataText(metadata, "http_status");
  const providerErrorType = metadataText(metadata, "providerErrorType") || metadataText(metadata, "provider_error_type");
  const providerErrorMessage = metadataText(metadata, "providerErrorMessage") || metadataText(metadata, "provider_error_message");
  const provider = metadataText(metadata, "provider");
  const providerHost = metadataText(metadata, "providerHost") || metadataText(metadata, "provider_host");
  const model = metadataText(metadata, "model");
  const chainStage = metadataText(metadata, "chainStage") || metadataText(metadata, "chain_stage");
  const protocol = metadataText(metadata, "protocol");
  const traceId = metadataText(metadata, "traceId") || metadataText(metadata, "trace_id");

  return [
    httpStatus ? { label: turnErrorLabel(lang, "状态码", "Status"), value: httpStatus } : null,
    summary ? { label: turnErrorLabel(lang, "原因", "Reason"), value: summary } : null,
    detail ? { label: turnErrorLabel(lang, "详情", "Detail"), value: detail } : null,
    chainStage ? { label: turnErrorLabel(lang, "阶段", "Stage"), value: chainStage } : null,
    protocol ? { label: turnErrorLabel(lang, "协议", "Protocol"), value: protocol } : null,
    providerErrorType ? { label: turnErrorLabel(lang, "类型", "Type"), value: providerErrorType } : null,
    providerErrorMessage ? { label: turnErrorLabel(lang, "上游", "Upstream"), value: providerErrorMessage } : null,
    provider || providerHost ? { label: turnErrorLabel(lang, "通道", "Provider"), value: [provider, providerHost].filter(Boolean).join(" · ") } : null,
    model ? { label: turnErrorLabel(lang, "模型", "Model"), value: model } : null,
    code ? { label: turnErrorLabel(lang, "代码", "Code"), value: code } : null,
    traceId ? { label: "Trace", value: traceId } : null,
  ].filter(isTurnErrorDiagnosticRow);
}

function turnErrorRetryAttempts(turnError: SessionTurnError): number {
  const history = Array.isArray(turnError.retryHistory) ? turnError.retryHistory : [];
  return history.reduce((max, entry) => Math.max(max, Number(entry?.attempt) || 0), 0);
}

export function buildCurrentTurnErrorRows(
  turnError: SessionTurnError,
  lang: ConversationLanguage,
): TurnErrorDiagnosticRow[] {
  const retryAttempts = turnErrorRetryAttempts(turnError);
  return [
    turnError.httpStatus ? { label: turnErrorLabel(lang, "状态码", "Status"), value: String(turnError.httpStatus) } : null,
    turnError.reasonSummary ? { label: turnErrorLabel(lang, "原因", "Reason"), value: turnError.reasonSummary } : null,
    turnError.reasonDetail ? { label: turnErrorLabel(lang, "详情", "Detail"), value: turnError.reasonDetail } : null,
    turnError.chainStage ? { label: turnErrorLabel(lang, "阶段", "Stage"), value: turnError.chainStage } : null,
    turnError.protocol ? { label: turnErrorLabel(lang, "协议", "Protocol"), value: turnError.protocol } : null,
    turnError.providerErrorType ? { label: turnErrorLabel(lang, "类型", "Type"), value: turnError.providerErrorType } : null,
    turnError.providerErrorMessage ? { label: turnErrorLabel(lang, "上游", "Upstream"), value: turnError.providerErrorMessage } : null,
    turnError.provider || turnError.providerHost ? { label: turnErrorLabel(lang, "通道", "Provider"), value: [turnError.provider, turnError.providerHost].filter(Boolean).join(" · ") } : null,
    turnError.model ? { label: turnErrorLabel(lang, "模型", "Model"), value: turnError.model } : null,
    turnError.reasonCode ? { label: turnErrorLabel(lang, "代码", "Code"), value: turnError.reasonCode } : null,
    retryAttempts > 0 ? { label: turnErrorLabel(lang, "重试", "Retries"), value: turnErrorLabel(lang, `${retryAttempts} 次`, String(retryAttempts)) } : null,
    turnError.traceId ? { label: "Trace", value: turnError.traceId } : null,
  ].filter(isTurnErrorDiagnosticRow);
}

export function summarizeCurrentTurnError(
  turnError: SessionTurnError,
  lang: ConversationLanguage,
) {
  // Codex keeps the settled failure to one plain line. The retry count lives
  // in the collapsed diagnostics instead of the summary.
  return resolveTurnErrorSummaryText(turnError, lang);
}

function resolveTurnErrorSummaryText(
  turnError: SessionTurnError,
  lang: ConversationLanguage,
) {
  const reasonSummary = String(turnError.reasonSummary || "").trim();
  if (reasonSummary) {
    return reasonSummary;
  }
  const message = String(turnError.message || "").replace(/\s+/g, " ").trim();
  if (!message) {
    return turnErrorLabel(lang, "本轮执行失败，请展开诊断详情。", "This turn failed. Expand diagnostics for details.");
  }
  const firstSentence = message.match(/^.{1,180}?[。！？.!?](?=\s|$)/u)?.[0]?.trim();
  if (firstSentence) {
    return firstSentence;
  }
  return message.length > 180 ? `${message.slice(0, 177).trimEnd()}...` : message;
}
