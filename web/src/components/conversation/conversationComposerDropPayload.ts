import type { SessionReferenceAttachment } from "../../api/types";
import { COMPOSER_SESSION_REFERENCE_MIME } from "./conversationConstants";

export type ComposerDragData = {
  files?: ArrayLike<File> | Iterable<File> | null;
  items?: ArrayLike<DataTransferItem> | Iterable<DataTransferItem> | null;
  types?: ArrayLike<string> | Iterable<string> | null;
  getData?: (format: string) => string;
} | null | undefined;

export function extractComposerImageDropFiles(data: ComposerDragData): File[] {
  const files = data?.files;
  if (!files) {
    return [];
  }
  return Array.from(files).filter((file) => file.type.startsWith("image/"));
}

export function hasComposerImageDragPayload(data: ComposerDragData): boolean {
  if (extractComposerImageDropFiles(data).length > 0) {
    return true;
  }
  const items = data?.items;
  if (!items) {
    return false;
  }
  return Array.from(items).some((item) => item.kind === "file" && item.type.startsWith("image/"));
}

export function extractComposerSessionReferenceDrop(data: ComposerDragData): SessionReferenceAttachment | null {
  const types = data?.types ? Array.from(data.types) : [];
  if (!types.includes(COMPOSER_SESSION_REFERENCE_MIME) || !data?.getData) {
    return null;
  }
  try {
    const raw = data.getData(COMPOSER_SESSION_REFERENCE_MIME);
    const parsed = JSON.parse(raw) as Partial<SessionReferenceAttachment>;
    const sessionId = String(parsed.sessionId ?? "").trim();
    if (!sessionId) {
      return null;
    }
    return {
      referenceId: String(parsed.referenceId ?? "").trim() || `ref-${sessionId}`,
      kind: "session",
      sessionId,
      title: String(parsed.title ?? "").trim(),
      agentId: String(parsed.agentId ?? "").trim(),
      agentCode: String(parsed.agentCode ?? "").trim(),
      agentDisplayName: String(parsed.agentDisplayName ?? "").trim(),
      summary: String(parsed.summary ?? "").trim(),
      createdAt: String(parsed.createdAt ?? "").trim(),
    };
  } catch {
    return null;
  }
}

export function hasComposerSessionReferenceDragPayload(data: ComposerDragData): boolean {
  return Boolean(extractComposerSessionReferenceDrop(data));
}
