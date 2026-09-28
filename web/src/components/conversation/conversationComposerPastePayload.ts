/**
 * Composer paste payload model: oversized plain-text pastes convert into a
 * document attachment instead of flooding the textarea (ZCode parity). The
 * decision is pure so the clipboard shapes stay unit-testable without a DOM
 * paste event.
 */

/**
 * Character threshold (strictly greater converts). 15 KiB of text measured in
 * characters — the unit users perceive, and the same metric ZCode uses.
 */
export const COMPOSER_PASTE_TEXT_CHARACTER_LIMIT = 15360;

export type ComposerPasteData = {
  files?: ArrayLike<File> | Iterable<File> | null;
  types?: ArrayLike<string> | Iterable<string> | null;
  getData?: (format: string) => string;
} | null | undefined;

/** `粘贴文本-YYYYMMDD-HHmmss.txt` — locale-independent prefix, second precision. */
export function composerPastedTextAttachmentName(now: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `粘贴文本-${date}-${time}.txt`;
}

export function buildComposerPastedTextAttachment(text: string, now: Date = new Date()): File {
  return new File([text], composerPastedTextAttachmentName(now), { type: "text/plain" });
}

/**
 * Returns the attachment file when the paste is plain text (no file payload)
 * whose character count exceeds the limit; null otherwise so the paste keeps
 * its default textarea insertion. Any clipboard file payload (images included)
 * wins and never triggers the conversion.
 */
export function extractComposerPastedTextOverflow(
  data: ComposerPasteData,
  now: Date = new Date(),
): File | null {
  if (!data?.getData) {
    return null;
  }
  const files = data.files ? Array.from(data.files) : [];
  if (files.length > 0) {
    return null;
  }
  const types = data.types ? Array.from(data.types) : [];
  if (types.length > 0 && !types.includes("text/plain")) {
    return null;
  }
  const text = data.getData("text/plain");
  if (!text || text.length <= COMPOSER_PASTE_TEXT_CHARACTER_LIMIT) {
    return null;
  }
  return buildComposerPastedTextAttachment(text, now);
}
