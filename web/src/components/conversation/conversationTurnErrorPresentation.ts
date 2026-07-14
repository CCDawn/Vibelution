import type { ConversationMessage, SessionTurnError } from "../../api/types";

export type TurnErrorDiagnosticRow = { label: string; value: string };
export type ConversationLanguage = "zh" | "en";

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

export function buildCurrentTurnErrorRows(
  turnError: SessionTurnError,
  lang: ConversationLanguage,
): TurnErrorDiagnosticRow[] {
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
    turnError.traceId ? { label: "Trace", value: turnError.traceId } : null,
  ].filter(isTurnErrorDiagnosticRow);
}

export function summarizeCurrentTurnError(
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
