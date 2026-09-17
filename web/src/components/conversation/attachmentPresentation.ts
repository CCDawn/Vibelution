/**
 * Shared attachment presentation rules for the composer tray and sent-message
 * context cards. Keep both surfaces on one classification so a document is
 * never rendered through an image preview again.
 */

type AttachmentPresentationFields = {
  kind?: string;
  contentType?: string;
  imageUrl?: string;
};

/** Kind wins, then MIME, then the legacy imageUrl presence fallback. */
export function isImageAttachment(attachment: AttachmentPresentationFields): boolean {
  const kind = (attachment.kind || "").trim().toLowerCase();
  if (kind) {
    return kind === "image" || kind === "user_image";
  }
  const contentType = (attachment.contentType || "").trim().toLowerCase();
  if (contentType) {
    return contentType.startsWith("image/");
  }
  return Boolean(attachment.imageUrl);
}

/** Compact human-readable size (e.g. 820 KB, 2.4 MB); empty when unknown. */
export function attachmentSizeLabel(sizeBytes: number | undefined): string {
  const bytes = Number(sizeBytes);
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "";
  }
  const megabytes = bytes / (1024 * 1024);
  if (megabytes >= 1) {
    return `${megabytes >= 10 ? Math.round(megabytes) : megabytes.toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
