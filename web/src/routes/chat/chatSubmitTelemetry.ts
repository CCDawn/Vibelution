import { postBrowserTelemetry } from "../../app/browserTelemetry";

export function submitTelemetryFields(
  sessionId: string,
  options: {
    content?: string;
    attachmentCount?: number;
    referenceCount?: number;
    mentalModelEnabled?: boolean;
    runtimeStatusEnabled?: boolean;
    editTargetId?: string;
    composerDisabled?: boolean;
    sessionBusy?: boolean;
    activePhase?: string;
    guardReason?: string;
    imageInputModelId?: string;
    uploadedAttachmentCount?: number;
    clientSubmissionId?: string;
    turnId?: string;
    acceptedAt?: string;
    durationMs?: number;
    submitToOptimisticPaintMs?: number;
    activeStatusSource?: "optimistic_submit" | "assistant_delta";
    error?: unknown;
  } = {},
) {
  const fields: Record<string, unknown> = {
    sessionId,
  };
  if (options.content !== undefined) {
    fields.contentLength = options.content.length;
    fields.hasContent = options.content.trim().length > 0;
  }
  if (options.attachmentCount !== undefined) {
    fields.attachmentCount = options.attachmentCount;
  }
  if (options.referenceCount !== undefined) {
    fields.referenceCount = options.referenceCount;
  }
  if (options.uploadedAttachmentCount !== undefined) {
    fields.uploadedAttachmentCount = options.uploadedAttachmentCount;
  }
  if (options.mentalModelEnabled !== undefined) {
    fields.mentalModelEnabled = options.mentalModelEnabled;
  }
  if (options.runtimeStatusEnabled !== undefined) {
    fields.runtimeStatusEnabled = options.runtimeStatusEnabled;
  }
  if (options.editTargetId !== undefined) {
    fields.editTargetId = options.editTargetId;
  }
  if (options.composerDisabled !== undefined) {
    fields.composerDisabled = options.composerDisabled;
  }
  if (options.sessionBusy !== undefined) {
    fields.sessionBusy = options.sessionBusy;
  }
  if (options.activePhase !== undefined) {
    fields.activePhase = options.activePhase;
  }
  if (options.guardReason !== undefined) {
    fields.guardReason = options.guardReason;
  }
  if (options.imageInputModelId !== undefined) {
    fields.imageInputModelId = options.imageInputModelId;
  }
  if (options.clientSubmissionId !== undefined) {
    fields.clientSubmissionId = options.clientSubmissionId;
  }
  if (options.turnId !== undefined) {
    fields.turnId = options.turnId;
  }
  if (options.acceptedAt !== undefined) {
    fields.acceptedAt = options.acceptedAt;
  }
  if (options.durationMs !== undefined) {
    fields.durationMs = options.durationMs;
  }
  if (options.submitToOptimisticPaintMs !== undefined) {
    fields.submitToOptimisticPaintMs = options.submitToOptimisticPaintMs;
  }
  if (options.activeStatusSource !== undefined) {
    fields.activeStatusSource = options.activeStatusSource;
  }
  if (options.error instanceof Error) {
    fields.errorName = options.error.name;
    fields.errorMessage = options.error.message;
  } else if (options.error !== undefined) {
    fields.errorMessage = String(options.error);
  }
  return fields;
}

export function postSubmitTelemetry(
  eventCode: string,
  message: string,
  sessionId: string,
  options?: Parameters<typeof submitTelemetryFields>[1],
  level: "info" | "warning" | "error" = "info",
) {
  postBrowserTelemetry({
    phase: "chat_submit",
    eventCode,
    message,
    level,
    fields: submitTelemetryFields(sessionId, options),
  });
}
