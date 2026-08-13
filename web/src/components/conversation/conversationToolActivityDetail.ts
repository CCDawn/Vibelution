import type { CodexTranscriptCell } from "./codexTranscriptCells";
import type { ConversationToolPresentationLanguage } from "./conversationToolPresentation";

export type ConversationToolActivityDetailRow = {
  label: string;
  value: string;
};

const HTTP_FAILURE = /\bHTTP\s+(\d{3})\b(?:\s*[:：]\s*|\s+)(https?:\/\/[^\s)\]>'"]+)/i;
const HTTP_STATUS = /\bHTTP\s+(\d{3})\b/i;
const URL_RE = /https?:\/\/[^\s)\]>'"]+/i;

export function parseToolFailureHint(text: string): { status: string; url: string } {
  const raw = String(text || "");
  const combined = HTTP_FAILURE.exec(raw);
  if (combined) {
    return { status: combined[1], url: stripTrailingPunctuation(combined[2]) };
  }
  return {
    status: HTTP_STATUS.exec(raw)?.[1] ?? "",
    url: stripTrailingPunctuation(URL_RE.exec(raw)?.[0] ?? ""),
  };
}

export function buildConversationToolActivityDetailRows(
  cell: CodexTranscriptCell,
  language: ConversationToolPresentationLanguage,
): ConversationToolActivityDetailRow[] {
  const toolCall = cell.toolLifecycleModel?.toolCalls?.[0];
  const diagnostic = cell.diagnosticSummary ?? {};
  const reasonSummary = metadataText(diagnostic, "reasonSummary") || metadataText(diagnostic, "reason_summary");
  const reasonDetail = metadataText(diagnostic, "reasonDetail") || metadataText(diagnostic, "reason_detail");
  const reasonCode = metadataText(diagnostic, "reasonCode") || metadataText(diagnostic, "reason_code");
  const diagnosticStatus = metadataText(diagnostic, "httpStatus") || metadataText(diagnostic, "http_status");
  const blob = [
    cell.summary,
    cell.title,
    cell.text,
    toolCall?.summary,
    toolCall?.error,
    toolCall?.resultPreview,
    reasonSummary,
    reasonDetail,
  ].filter(Boolean).join("\n");
  const hint = parseToolFailureHint(blob);
  const url = hint.url;
  const status = diagnosticStatus || hint.status;
  const visibleOneLiners = [
    cell.summary,
    cell.text,
    toolCall?.summary,
    toolCall?.error,
    reasonSummary,
    status && url ? `HTTP ${status}: ${url}` : "",
    status && url ? `${status}: ${url}` : "",
    status ? `HTTP ${status}` : "",
  ].filter(Boolean).map(String);

  const rows: ConversationToolActivityDetailRow[] = [];
  if (url) {
    rows.push({ label: "URL", value: url });
  }
  if (status) {
    rows.push({ label: language === "zh" ? "状态" : "Status", value: status });
  }
  const push = (label: string, value: string) => {
    const text = String(value || "").trim();
    if (!text) {
      return;
    }
    if (rows.some((row) => normalizeComparable(row.value) === normalizeComparable(text))) {
      return;
    }
    if (isDuplicateVisibleLine(text, visibleOneLiners, url, status)) {
      return;
    }
    rows.push({ label, value: text });
  };

  push(language === "zh" ? "详情" : "Detail", reasonDetail);
  push(language === "zh" ? "错误" : "Error", String(toolCall?.error || ""));
  push(language === "zh" ? "原因" : "Reason", reasonSummary);
  if (reasonCode && reasonCode !== "tool_failed") {
    push(language === "zh" ? "代码" : "Code", reasonCode);
  }
  return rows;
}

export function conversationToolActivityEmptyDetailLabel(language: ConversationToolPresentationLanguage) {
  return language === "zh" ? "没有额外输出" : "No extra output";
}

function isDuplicateVisibleLine(
  value: string,
  visibleOneLiners: string[],
  url: string,
  status: string,
): boolean {
  const normalized = normalizeComparable(value);
  if (!normalized) {
    return true;
  }
  if (url && normalized === normalizeComparable(url)) {
    return true;
  }
  if (status && (normalized === normalizeComparable(status) || normalized === `http ${status}`)) {
    return true;
  }
  return visibleOneLiners.some((line) => {
    const visible = normalizeComparable(line);
    return visible !== "" && visible === normalized;
  });
}

function metadataText(metadata: Record<string, unknown>, key: string): string {
  const value = metadata[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function normalizeComparable(value: string): string {
  return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function stripTrailingPunctuation(value: string): string {
  return String(value || "").replace(/[.,;]+$/g, "");
}
