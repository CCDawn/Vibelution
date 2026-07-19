import type { DragEvent } from "react";

import { fetchJson } from "../../api/client";
import type {
  ConversationAttachment,
  SessionReferenceAttachment,
  SessionSummary,
} from "../../api/types";
import { COMPOSER_SESSION_REFERENCE_MIME } from "../../components/conversation/conversationConstants";
import { stableCliHash } from "./cliAgentRunModel";

export const MENTAL_MODEL_TOGGLE_STORAGE_KEY = "vibelution.chat.mentalModelEnabled";
export const MAX_COMPOSER_IMAGE_ATTACHMENTS = 4;
export const MAX_COMPOSER_IMAGE_BYTES = 8 * 1024 * 1024;
export const COMPOSER_IMAGE_ACCEPT_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;

export type ComposerImageAttachment = {
  id: string;
  file: File;
  filename: string;
  previewUrl: string;
  sizeBytes: number;
  contentType: string;
};

export type ComposerSubmitGuardReason = "composer_disabled" | "empty_content" | "";

export function encodeUtf8Base64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

export function clearSessionImageAttachments(
  current: Record<string, ComposerImageAttachment[]>,
  sessionId: string,
) {
  const attachments = current[sessionId] ?? [];
  attachments.forEach((attachment) => URL.revokeObjectURL(attachment.previewUrl));
  const { [sessionId]: _removed, ...remaining } = current;
  return remaining;
}

export function clearSessionReferenceAttachments(
  current: Record<string, SessionReferenceAttachment[]>,
  sessionId: string,
) {
  const { [sessionId]: _removed, ...remaining } = current;
  return remaining;
}

export function sessionReferenceId(reference: SessionReferenceAttachment) {
  return String(reference.referenceId || reference.sessionId || "").trim();
}

export function buildSessionReferencePayload(
  session: SessionSummary,
  displayName: string,
  summary: string,
): SessionReferenceAttachment {
  const sessionId = String(session.id || "").trim();
  return {
    referenceId: `session:${sessionId}`,
    kind: "session",
    sessionId,
    title: String(session.taskTitle || session.resultCard?.title || session.title || sessionId).trim(),
    agentId: String(session.agentId || "").trim(),
    agentCode: String(session.agentCode || "").trim(),
    agentDisplayName: String(displayName || session.agentDisplayName || "").trim(),
    summary: String(summary || session.taskSummary || "").trim(),
    createdAt: new Date().toISOString(),
  };
}

export function startSessionReferenceDrag(
  event: DragEvent<HTMLElement>,
  reference: SessionReferenceAttachment,
) {
  const payload = JSON.stringify(reference);
  event.dataTransfer.setData(COMPOSER_SESSION_REFERENCE_MIME, payload);
  event.dataTransfer.setData("text/plain", `[Session Reference] ${reference.title || reference.sessionId}`);
  event.dataTransfer.effectAllowed = "copy";
}

export function clearSessionDraftForSubmittedTurn(
  current: Record<string, string>,
  sessionId: string,
) {
  if ((current[sessionId] ?? "") === "") {
    return current;
  }
  return {
    ...current,
    [sessionId]: "",
  };
}

export function restoreSubmittedDraftIfComposerStillEmpty(
  current: Record<string, string>,
  sessionId: string,
  content: string,
) {
  if (!content || (current[sessionId] ?? "") !== "") {
    return current;
  }
  return {
    ...current,
    [sessionId]: content,
  };
}

export function removeSessionImageAttachment(
  current: Record<string, ComposerImageAttachment[]>,
  sessionId: string,
  attachmentId: string,
) {
  const attachments = current[sessionId] ?? [];
  const removed = attachments.find((attachment) => attachment.id === attachmentId);
  if (removed) {
    URL.revokeObjectURL(removed.previewUrl);
  }
  return {
    ...current,
    [sessionId]: attachments.filter((attachment) => attachment.id !== attachmentId),
  };
}

export async function uploadSessionImageAttachment(sessionId: string, attachment: ComposerImageAttachment) {
  return fetchJson<ConversationAttachment>(`/api/sessions/${sessionId}/attachments`, {
    method: "POST",
    headers: {
      "Content-Type": attachment.contentType || "application/octet-stream",
      "X-Vibelution-Filename": encodeURIComponent(attachment.filename),
    },
    body: attachment.file,
  });
}

export function classifyComposerImageFiles(
  files: FileList | File[],
  options: {
    createObjectUrl?: (file: File) => string;
    nowMs?: number;
    randomId?: () => string;
  } = {},
) {
  const createObjectUrl = options.createObjectUrl ?? ((file: File) => URL.createObjectURL(file));
  const nowMs = options.nowMs ?? Date.now();
  const randomId = options.randomId ?? (() => Math.random().toString(16).slice(2));
  const incoming = Array.from(files || []).filter((file) => file.type.startsWith("image/"));
  const accepted: ComposerImageAttachment[] = [];
  const rejected: string[] = [];
  for (const file of incoming) {
    if (!(COMPOSER_IMAGE_ACCEPT_TYPES as readonly string[]).includes(file.type)) {
      rejected.push(file.name);
      continue;
    }
    if (file.size > MAX_COMPOSER_IMAGE_BYTES) {
      rejected.push(file.name);
      continue;
    }
    accepted.push({
      id: `${nowMs}-${randomId()}`,
      file,
      filename: file.name || "image",
      previewUrl: createObjectUrl(file),
      sizeBytes: file.size,
      contentType: file.type,
    });
  }
  return { accepted, rejected };
}

export function mergeComposerImageAttachments(
  existing: ComposerImageAttachment[],
  incoming: ComposerImageAttachment[],
  maxAttachments = MAX_COMPOSER_IMAGE_ATTACHMENTS,
) {
  return [...existing, ...incoming].slice(0, maxAttachments);
}

export function resolveComposerSubmitGuard(options: {
  composerDisabled: boolean;
  content: string;
  imageAttachmentCount: number;
  referenceAttachmentCount: number;
}): ComposerSubmitGuardReason {
  if (options.composerDisabled) {
    return "composer_disabled";
  }
  if (!options.content && !options.imageAttachmentCount && !options.referenceAttachmentCount) {
    return "empty_content";
  }
  return "";
}

export function readStoredMentalModelToggle(): boolean | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(MENTAL_MODEL_TOGGLE_STORAGE_KEY);
  if (raw === "true") {
    return true;
  }
  if (raw === "false") {
    return false;
  }
  return null;
}

export function writeStoredMentalModelToggle(enabled: boolean) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(MENTAL_MODEL_TOGGLE_STORAGE_KEY, enabled ? "true" : "false");
}

export function optimisticTurnIdForSubmission(kind: "submit" | "edit", sessionId: string, createdAt: string) {
  return `optimistic-${kind}-${stableCliHash([kind, sessionId, createdAt].join("\n"))}`;
}
