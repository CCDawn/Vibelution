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
  const summary = metadataText(message.metadata, "reasonSummary") || metadataText(message.metadata, "reason_summary");
  const detail = metadataText(message.metadata, "reasonDetail") || metadataText(message.metadata, "reason_detail");
  const code = metadataText(message.metadata, "reasonCode") || metadataText(message.metadata, "reason_code");
  const httpStatus = metadataText(message.metadata, "httpStatus") || metadataText(message.metadata, "http_status");
  const providerErrorType = metadataText(message.metadata, "providerErrorType") || metadataText(message.metadata, "provider_error_type");
  const providerErrorMessage = metadataText(message.metadata, "providerErrorMessage") || metadataText(message.metadata, "provider_error_message");
  const provider = metadataText(message.metadata, "provider");
  const providerHost = metadataText(message.metadata, "providerHost") || metadataText(message.metadata, "provider_host");
  const model = metadataText(message.metadata, "model");

  return [
    httpStatus ? { label: turnErrorLabel(lang, "状态码", "Status"), value: httpStatus } : null,
    summary ? { label: turnErrorLabel(lang, "原因", "Reason"), value: summary } : null,
    detail ? { label: turnErrorLabel(lang, "详情", "Detail"), value: detail } : null,
    providerErrorType ? { label: turnErrorLabel(lang, "类型", "Type"), value: providerErrorType } : null,
    providerErrorMessage ? { label: turnErrorLabel(lang, "上游", "Upstream"), value: providerErrorMessage } : null,
    provider || providerHost ? { label: turnErrorLabel(lang, "通道", "Provider"), value: [provider, providerHost].filter(Boolean).join(" · ") } : null,
    model ? { label: turnErrorLabel(lang, "模型", "Model"), value: model } : null,
    code ? { label: turnErrorLabel(lang, "代码", "Code"), value: code } : null,
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
    turnError.providerErrorType ? { label: turnErrorLabel(lang, "类型", "Type"), value: turnError.providerErrorType } : null,
    turnError.providerErrorMessage ? { label: turnErrorLabel(lang, "上游", "Upstream"), value: turnError.providerErrorMessage } : null,
    turnError.provider || turnError.providerHost ? { label: turnErrorLabel(lang, "通道", "Provider"), value: [turnError.provider, turnError.providerHost].filter(Boolean).join(" · ") } : null,
    turnError.model ? { label: turnErrorLabel(lang, "模型", "Model"), value: turnError.model } : null,
    turnError.reasonCode ? { label: turnErrorLabel(lang, "代码", "Code"), value: turnError.reasonCode } : null,
  ].filter(isTurnErrorDiagnosticRow);
}
