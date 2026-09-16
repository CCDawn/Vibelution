import type { DragEvent } from "react";

import { uploadSessionImageAttachment as postSessionImageAttachment } from "../../api/chat";
import type {
  SessionReferenceAttachment,
  SessionSummary,
} from "../../api/types";
import {
  COMPOSER_DOCUMENT_ACCEPT_EXTENSIONS,
  COMPOSER_IMAGE_ACCEPT_TYPES,
  COMPOSER_SESSION_REFERENCE_MIME,
  composerAttachmentAcceptAttribute,
  composerFileExtension,
  isComposerAttachableFile,
  isComposerDocumentFile,
} from "../../components/conversation/conversationConstants";

export {
  composerAttachmentAcceptAttribute,
  composerFileExtension,
  isComposerAttachableFile,
  isComposerDocumentFile,
};
import { stableCliHash } from "./cliAgentRunModel";

export const MENTAL_MODEL_TOGGLE_STORAGE_KEY = "vibelution.chat.mentalModelEnabled";
export const RUNTIME_STATUS_TOGGLE_STORAGE_KEY = "vibelution.chat.runtimeStatusEnabled";
export const MAX_COMPOSER_IMAGE_ATTACHMENTS = 4;
export const MAX_COMPOSER_DOCUMENT_ATTACHMENTS = 4;
export const MAX_COMPOSER_IMAGE_BYTES = 8 * 1024 * 1024;
export const MAX_COMPOSER_DOCUMENT_BYTES = 2 * 1024 * 1024;
export { COMPOSER_IMAGE_ACCEPT_TYPES, COMPOSER_DOCUMENT_ACCEPT_EXTENSIONS };

export type ComposerAttachmentKind = "image" | "document";

export type ComposerImageAttachment = {
  id: string;
  file: File;
  filename: string;
  previewUrl: string;
  sizeBytes: number;
  contentType: string;
  kind: ComposerAttachmentKind;
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

export function buildFileReferencePayload(artifactId: string, filename: string): SessionReferenceAttachment {
  const normalizedArtifactId = String(artifactId || "").trim();
  return {
    referenceId: `file:${normalizedArtifactId}`,
    kind: "file",
    artifactId: normalizedArtifactId,
    title: String(filename || normalizedArtifactId).trim(),
    createdAt: new Date().toISOString(),
  };
}

export function buildKnowledgeBaseReferencePayload(knowledgeBaseId: string, title: string): SessionReferenceAttachment {
  const normalizedBaseId = String(knowledgeBaseId || "").trim();
  return {
    referenceId: `knowledge-base:${normalizedBaseId}`,
    kind: "knowledge_base",
    knowledgeBaseId: normalizedBaseId,
    title: String(title || normalizedBaseId).trim(),
    createdAt: new Date().toISOString(),
  };
}

export function buildKnowledgeItemReferencePayload(
  knowledgeBaseId: string,
  knowledgeItemId: string,
  title: string,
): SessionReferenceAttachment {
  const normalizedBaseId = String(knowledgeBaseId || "").trim();
  const normalizedItemId = String(knowledgeItemId || "").trim();
  return {
    referenceId: `knowledge-item:${normalizedItemId}`,
    kind: "knowledge_item",
    knowledgeBaseId: normalizedBaseId,
    knowledgeItemId: normalizedItemId,
    title: String(title || normalizedItemId).trim(),
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
  return postSessionImageAttachment(sessionId, {
    contentType: attachment.contentType,
    filename: attachment.filename,
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
      kind: "image",
    });
  }
  return { accepted, rejected };
}

export function classifyComposerFiles(
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
  const accepted: ComposerImageAttachment[] = [];
  const rejected: string[] = [];
  for (const file of Array.from(files || [])) {
    if (file.type.startsWith("image/")) {
      if (!(COMPOSER_IMAGE_ACCEPT_TYPES as readonly string[]).includes(file.type) || file.size > MAX_COMPOSER_IMAGE_BYTES) {
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
        kind: "image",
      });
      continue;
    }
    if (isComposerDocumentFile(file)) {
      if (file.size > MAX_COMPOSER_DOCUMENT_BYTES) {
        rejected.push(file.name);
        continue;
      }
      accepted.push({
        id: `${nowMs}-${randomId()}`,
        file,
        filename: file.name || "document",
        previewUrl: createObjectUrl(file),
        sizeBytes: file.size,
        contentType: file.type || "application/octet-stream",
        kind: "document",
      });
      continue;
    }
    rejected.push(file.name);
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

export function mergeComposerAttachments(
  existing: ComposerImageAttachment[],
  incoming: ComposerImageAttachment[],
  options: {
    maxTotal?: number;
    maxImages?: number;
    maxDocuments?: number;
  } = {},
) {
  const maxTotal = options.maxTotal ?? MAX_COMPOSER_IMAGE_ATTACHMENTS + MAX_COMPOSER_DOCUMENT_ATTACHMENTS;
  const merged = [...existing, ...incoming].slice(0, maxTotal);
  const imageCount = merged.filter((item) => item.kind !== "document").length;
  const overflow = Math.max(0, imageCount - (options.maxImages ?? MAX_COMPOSER_IMAGE_ATTACHMENTS));
  if (!overflow) {
    return merged;
  }
  // Drop the newest image attachments that break the per-kind cap, keeping
  // every document regardless of order.
  let imagesToDrop = overflow;
  const kept: ComposerImageAttachment[] = [];
  for (let index = merged.length - 1; index >= 0; index -= 1) {
    const item = merged[index];
    if (item.kind !== "document" && imagesToDrop > 0) {
      imagesToDrop -= 1;
      continue;
    }
    kept.unshift(item);
  }
  return kept;
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

export const PROMPT_SUGGESTION_TOGGLE_STORAGE_PREFIX = "vibelution.chat.promptSuggestionEnabled:";

export function promptSuggestionToggleStorageKey(sessionId: string): string {
  return `${PROMPT_SUGGESTION_TOGGLE_STORAGE_PREFIX}${String(sessionId || "").trim()}`;
}

export function readStoredPromptSuggestionToggle(sessionId: string): boolean {
  if (typeof window === "undefined" || !String(sessionId || "").trim()) {
    return false;
  }
  return window.localStorage.getItem(promptSuggestionToggleStorageKey(sessionId)) === "true";
}

export function writeStoredPromptSuggestionToggle(sessionId: string, enabled: boolean) {
  if (typeof window === "undefined" || !String(sessionId || "").trim()) {
    return;
  }
  window.localStorage.setItem(
    promptSuggestionToggleStorageKey(sessionId),
    enabled ? "true" : "false",
  );
}

export function readStoredRuntimeStatusToggle(): boolean | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(RUNTIME_STATUS_TOGGLE_STORAGE_KEY);
  if (raw === "true") {
    return true;
  }
  if (raw === "false") {
    return false;
  }
  return null;
}

export function writeStoredRuntimeStatusToggle(enabled: boolean) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(RUNTIME_STATUS_TOGGLE_STORAGE_KEY, enabled ? "true" : "false");
}

export function optimisticTurnIdForSubmission(kind: "submit" | "edit", sessionId: string, createdAt: string) {
  return `optimistic-${kind}-${stableCliHash([kind, sessionId, createdAt].join("\n"))}`;
}
