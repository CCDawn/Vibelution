/**
 * Desktop-only platform capabilities probed off the `vibelutionLauncher`
 * contextBridge. The web browser build has no such bridge, so every probe
 * degrades to "capability missing" and callers keep their legacy behavior.
 */

type DesktopLauncherBridge = {
  getPathForFile?: (file: unknown) => string | null;
  openExternalUrl?: (url: string) => unknown;
  openPath?: (path: string) => unknown;
  showItemInFolder?: (path: string) => unknown;
};

function desktopBridge(): DesktopLauncherBridge | null {
  if (typeof window === "undefined") {
    return null;
  }
  const bridge = (globalThis as { vibelutionLauncher?: unknown }).vibelutionLauncher;
  if (typeof bridge !== "object" || bridge === null) {
    return null;
  }
  return bridge as DesktopLauncherBridge;
}

/** http/https/mailto are the only schemes allowed to leave the app. */
const EXTERNAL_URL_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

function isExternalHttpMailtoUrl(rawUrl: string): boolean {
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

/** Windows drive, Windows UNC, or POSIX absolute — anything else is rejected. */
export function isAbsoluteFileSystemPath(rawPath: string): boolean {
  const trimmed = rawPath.trim();
  if (trimmed.length === 0) {
    return false;
  }
  return /^[a-zA-Z]:[\\/]/.test(trimmed) || /^\\\\[^\\]/.test(trimmed) || trimmed.startsWith("/");
}

/**
 * Whether the host can resolve a browser File back to a real local path.
 * Only the desktop preload (Electron webUtils) can; web browsers cannot.
 */
export function canResolveLocalFilePath(): boolean {
  return typeof desktopBridge()?.getPathForFile === "function";
}

/**
 * Resolve a drag-drop / file-picker File to its local absolute path.
 * Returns null when the host lacks the capability, the file carries no path
 * (clipboard screenshots), or the bridge call fails — callers then keep the
 * legacy in-memory upload path.
 */
export function resolveLocalFilePath(file: File): string | null {
  const getPathForFile = desktopBridge()?.getPathForFile;
  if (typeof getPathForFile !== "function" || !(file instanceof File)) {
    return null;
  }
  try {
    const resolved = getPathForFile(file);
    const normalized = typeof resolved === "string" ? resolved.trim() : "";
    return normalized.length > 0 ? normalized : null;
  } catch {
    return null;
  }
}

/**
 * Open an http/https/mailto URL with the system's default handler.
 * The scheme is re-validated here (the Electron main process validates
 * again). Returns false outside Electron, for rejected schemes
 * (file:, javascript:, custom protocols), or when the shell call fails.
 */
export async function openExternalUrl(url: string): Promise<boolean> {
  const openExternal = desktopBridge()?.openExternalUrl;
  if (typeof openExternal !== "function" || !isExternalHttpMailtoUrl(url)) {
    return false;
  }
  try {
    return (await openExternal(url)) === true;
  } catch {
    return false;
  }
}

/**
 * Open a local file or directory with the system default program.
 * Only absolute paths are accepted; relative paths and file:// URLs are
 * rejected before reaching the bridge. Returns the shell result string
 * ("" on success, error text otherwise) or "" when unavailable.
 */
export async function openPath(path: string): Promise<string> {
  const openPathBridge = desktopBridge()?.openPath;
  if (typeof openPathBridge !== "function" || !isAbsoluteFileSystemPath(path)) {
    return "";
  }
  try {
    const result = await openPathBridge(path);
    return typeof result === "string" ? result : "";
  } catch {
    return "";
  }
}

/**
 * Reveal a local file or directory in the system file manager.
 * Same absolute-path rule as openPath. Returns false outside Electron, for
 * rejected paths, or when the shell call fails.
 */
export async function showItemInFolder(path: string): Promise<boolean> {
  const showInFolder = desktopBridge()?.showItemInFolder;
  if (typeof showInFolder !== "function" || !isAbsoluteFileSystemPath(path)) {
    return false;
  }
  try {
    return (await showInFolder(path)) === true;
  } catch {
    return false;
  }
}
