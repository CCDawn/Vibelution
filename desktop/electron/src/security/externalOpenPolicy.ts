/**
 * Pure policy for handing content (links, files) to the operating system.
 * Shared by the IPC handlers (`vui:open-external` / `vui:open-path` /
 * `vui:show-item-in-folder`) and the window-open routing so the renderer
 * bridge and the main-process interception cannot drift apart.
 */

const EXTERNAL_URL_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

/**
 * Whether a URL may leave the app via shell.openExternal. Only http/https and
 * mailto are allowed; everything else (file:, javascript:, custom app
 * protocols, about:) must be rejected so a renderer cannot pivot into
 * arbitrary handlers or script execution.
 */
export function isExternalOpenableUrl(rawUrl: unknown): rawUrl is string {
  if (typeof rawUrl !== "string") {
    return false;
  }
  const trimmed = rawUrl.trim();
  if (trimmed.length === 0) {
    return false;
  }
  try {
    return EXTERNAL_URL_PROTOCOLS.has(new URL(trimmed).protocol);
  } catch {
    return false;
  }
}

/**
 * Normalize a renderer-supplied path for shell.openPath / showItemInFolder.
 * Returns null unless the input is a non-empty absolute filesystem path
 * (Windows drive, Windows UNC, or POSIX absolute). Relative paths and
 * file:// URLs are rejected — callers must never resolve them against an
 * implicit working directory.
 */
export function normalizeAbsoluteOpenPath(rawPath: unknown): string | null {
  if (typeof rawPath !== "string") {
    return null;
  }
  const trimmed = rawPath.trim();
  if (trimmed.length === 0) {
    return null;
  }
  if (/^[a-zA-Z]:[\\/]/.test(trimmed)) {
    return trimmed;
  }
  if (/^\\\\[^\\]/.test(trimmed)) {
    return trimmed;
  }
  if (trimmed.startsWith("/")) {
    return trimmed;
  }
  return null;
}
