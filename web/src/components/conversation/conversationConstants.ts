export const COMPOSER_SESSION_REFERENCE_MIME = "application/vnd.vibelution.session-reference+json";

/** Image types accepted by the session image attachment pipeline. */
export const COMPOSER_IMAGE_ACCEPT_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;

/**
 * Document extensions accepted by the session document attachment pipeline
 * (mirrors core/web/services/session/document_attachments.py).
 */
export const COMPOSER_DOCUMENT_ACCEPT_EXTENSIONS = [
  "md", "markdown", "txt", "csv", "tsv", "json", "jsonl", "yaml", "yml", "xml", "html", "htm",
  "py", "ipynb", "ts", "tsx", "js", "jsx", "css", "sql", "sh", "r", "rb", "java", "c", "cpp",
  "cs", "go", "rs", "toml", "ini", "cfg", "log", "tex", "bib", "pdf",
] as const;

export function composerFileExtension(file: Pick<File, "name">): string {
  const name = String(file.name || "");
  const dotIndex = name.lastIndexOf(".");
  if (dotIndex < 0) {
    return "";
  }
  return name.slice(dotIndex + 1).toLowerCase();
}

export function isComposerDocumentFile(file: File): boolean {
  return (COMPOSER_DOCUMENT_ACCEPT_EXTENSIONS as readonly string[]).includes(composerFileExtension(file));
}

export function isComposerAttachableFile(file: File): boolean {
  return file.type.startsWith("image/") || isComposerDocumentFile(file);
}

export function composerAttachmentAcceptAttribute(): string {
  return [
    ...COMPOSER_IMAGE_ACCEPT_TYPES,
    ...COMPOSER_DOCUMENT_ACCEPT_EXTENSIONS.map((extension) => `.${extension}`),
  ].join(",");
}
