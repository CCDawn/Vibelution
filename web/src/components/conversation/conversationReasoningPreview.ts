/**
 * Soft humanize for streamed reasoning previews that arrive without spaces
 * (common with some DeepSeek-style reasoning channels).
 */

const MAX_PREVIEW_LENGTH = 96;

export function humanizeReasoningPreview(value: string, maxLength = MAX_PREVIEW_LENGTH): string {
  const raw = String(value || "").replace(/\s+/g, " ").trim();
  if (!raw) {
    return "";
  }

  let text = raw
    // CamelCase / PascalCase boundaries.
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    // Letter ↔ CJK boundaries.
    .replace(/([A-Za-z])([\u4e00-\u9fff])/g, "$1 $2")
    .replace(/([\u4e00-\u9fff])([A-Za-z])/g, "$1 $2")
    // Sentence punctuation glue.
    .replace(/\.([A-Za-z\u4e00-\u9fff])/g, ". $1")
    .replace(/([A-Za-z\u4e00-\u9fff])(["“”])/g, "$1 $2")
    .replace(/(["“”])([A-Za-z\u4e00-\u9fff])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim();

  // Long all-lowercase ASCII blobs are unreadable; keep a short head only.
  const asciiOnly = /^[\x20-\x7E]+$/.test(text);
  const spaceCount = (text.match(/ /g) || []).length;
  if (asciiOnly && text.length > 48 && spaceCount < 3) {
    text = `${text.slice(0, Math.min(40, maxLength - 1)).trimEnd()}…`;
    return text;
  }

  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength - 1).trimEnd()}…`;
}
