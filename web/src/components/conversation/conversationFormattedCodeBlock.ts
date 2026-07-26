/**
 * Pretty-print JSON fenced code blocks for transcript rendering (structure M8).
 * Pure: no React / DOM.
 */
export function formattedCodeBlockContent(content: string, language?: string): string {
  const raw = String(content ?? "");
  if (String(language ?? "").trim().toLowerCase() !== "json") {
    return raw;
  }

  const trimmed = raw.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) {
    return raw;
  }

  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return raw;
  }
}
