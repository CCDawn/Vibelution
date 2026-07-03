export function safeConversationMarkdownUrl(rawUrl: string): string | null {
  const trimmed = String(rawUrl ?? "").trim();
  if (!trimmed || /[\u0000-\u001f\u007f]/.test(trimmed) || /\s/.test(trimmed)) {
    return null;
  }
  if (trimmed.startsWith("//")) {
    return null;
  }
  if (trimmed.startsWith("/") || trimmed.startsWith("./") || trimmed.startsWith("../") || trimmed.startsWith("#")) {
    return trimmed;
  }
  const schemeMatch = trimmed.match(/^([A-Za-z][A-Za-z0-9+.-]*):/);
  if (!schemeMatch) {
    return trimmed;
  }
  const scheme = schemeMatch[1].toLowerCase();
  return scheme === "http" || scheme === "https" ? trimmed : null;
}
