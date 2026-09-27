/**
 * Desktop-only platform capabilities probed off the `vibelutionLauncher`
 * contextBridge. The web browser build has no such bridge, so every probe
 * degrades to "capability missing" and callers keep their legacy behavior.
 */

type DesktopPathBridge = {
  getPathForFile?: (file: unknown) => string | null;
};

function desktopPathBridge(): DesktopPathBridge | null {
  if (typeof window === "undefined") {
    return null;
  }
  const bridge = (globalThis as { vibelutionLauncher?: unknown }).vibelutionLauncher;
  if (typeof bridge !== "object" || bridge === null) {
    return null;
  }
  const getPathForFile = (bridge as DesktopPathBridge).getPathForFile;
  return typeof getPathForFile === "function" ? { getPathForFile } : null;
}

/**
 * Whether the host can resolve a browser File back to a real local path.
 * Only the desktop preload (Electron webUtils) can; web browsers cannot.
 */
export function canResolveLocalFilePath(): boolean {
  return desktopPathBridge() !== null;
}

/**
 * Resolve a drag-drop / file-picker File to its local absolute path.
 * Returns null when the host lacks the capability, the file carries no path
 * (clipboard screenshots), or the bridge call fails — callers then keep the
 * legacy in-memory upload path.
 */
export function resolveLocalFilePath(file: File): string | null {
  const bridge = desktopPathBridge();
  if (!bridge || !(file instanceof File)) {
    return null;
  }
  try {
    const resolved = bridge.getPathForFile?.(file);
    const normalized = typeof resolved === "string" ? resolved.trim() : "";
    return normalized.length > 0 ? normalized : null;
  } catch {
    return null;
  }
}
