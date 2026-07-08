import {
  isInternalStreamingStatusContent,
  isInternalStreamingStatusStage,
} from "./conversationInternalStatus";

export type RuntimeStatusDisplayInput = {
  kind?: unknown;
  name?: unknown;
  label?: unknown;
  title?: unknown;
  status?: unknown;
  tone?: unknown;
  summary?: unknown;
  resultPreview?: unknown;
  text?: unknown;
  error?: unknown;
  failureClass?: unknown;
  timedOut?: unknown;
};

export type TranscriptCellDisplayInput = RuntimeStatusDisplayInput & {
  id?: unknown;
  messageId?: unknown;
};

export type RuntimeStatusDisplayOptions = {
  includeInternalPipeline?: boolean;
};

export function shouldDisplayRuntimeStatus(
  input: RuntimeStatusDisplayInput,
  options: RuntimeStatusDisplayOptions = {},
) {
  if (normalizedText(input.kind) !== "status") {
    return true;
  }
  if (options.includeInternalPipeline && isInternalRuntimeStatus(input)) {
    return true;
  }
  return hasDisplayableDiagnosticStatus(input);
}

export function shouldDisplayTranscriptCell(cell: TranscriptCellDisplayInput) {
  const kind = normalizedText(cell.kind);
  if (kind === "assistant_markdown" && hasInternalTranscriptText(cell)) {
    return false;
  }
  if (kind !== "status") {
    return true;
  }
  return shouldDisplayRuntimeStatus({
    kind: "status",
    name: cell.name ?? cell.title ?? cell.label,
    status: cell.status,
    tone: cell.tone,
    summary: cell.summary,
    resultPreview: cell.resultPreview ?? cell.text,
    text: cell.text,
    error: cell.error,
    failureClass: cell.failureClass,
    timedOut: cell.timedOut,
  });
}

export function isInternalRuntimeStatus(input: RuntimeStatusDisplayInput) {
  if (normalizedText(input.kind) !== "status") {
    return false;
  }
  const name = normalizedText(input.name ?? input.label ?? input.title);
  if (isInternalStreamingStatusStage(name)) {
    return true;
  }
  const content = [
    input.summary,
    input.resultPreview,
    input.text,
  ].map(compactText).filter(Boolean).join("\n");
  return isInternalStreamingStatusContent(content);
}

function hasDisplayableDiagnosticStatus(input: RuntimeStatusDisplayInput) {
  const status = normalizedText(input.status);
  const tone = normalizedText(input.tone);
  return Boolean(
    isDisplayableProgressStatus(input)
    || compactText(input.error)
    || compactText(input.failureClass)
    || input.timedOut
    || tone === "error"
    || ["failed", "error", "failure", "timeout", "timed_out", "cancelled"].includes(status)
    || ["degraded", "fallback", "partial", "recovered", "unavailable"].includes(status)
  );
}

function hasInternalTranscriptText(cell: TranscriptCellDisplayInput) {
  const content = [
    cell.summary,
    cell.resultPreview,
    cell.text,
  ].map(compactText).filter(Boolean).join("\n");
  return Boolean(content && isInternalStreamingStatusContent(content));
}

function isDisplayableProgressStatus(input: RuntimeStatusDisplayInput) {
  const content = [
    input.name,
    input.label,
    input.title,
    input.summary,
    input.resultPreview,
    input.text,
  ].map(normalizedText).filter(Boolean).join(" ");
  return Boolean(
    content.includes("long_loop_progress")
    || content.includes("尚未形成最终回答")
    || content.includes("本轮尚未形成最终回答")
    || content.includes("工具循环")
    || content.includes("tool loop")
  );
}

function normalizedText(value: unknown) {
  return compactText(value).toLowerCase();
}

function compactText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}
