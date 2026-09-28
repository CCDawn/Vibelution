/**
 * Desktop-bridge actions behind workspace-file markdown links. Thin wrappers
 * over `desktopPlatform` that normalize its return shapes into a single
 * "handled vs unavailable" outcome so the link UI can fall back (copy the path
 * + a light hint) when the bridge is missing or the shell call fails.
 *
 * `openPath` returns `""` both on success and when the bridge is absent, so
 * bridge presence is probed here (read-only, same contextBridge global the
 * platform module reads).
 */
import { openPath, showItemInFolder } from "../../api/desktopPlatform";

export type WorkspaceFileActionResult = "done" | "unavailable";

type DesktopLauncherProbe = {
  openPath?: unknown;
  showItemInFolder?: unknown;
};

function desktopLauncherBridge(): DesktopLauncherProbe | null {
  const bridge = (globalThis as { vibelutionLauncher?: unknown }).vibelutionLauncher;
  return typeof bridge === "object" && bridge !== null ? (bridge as DesktopLauncherProbe) : null;
}

function hasDesktopBridgeAction(action: "openPath" | "showItemInFolder"): boolean {
  return typeof desktopLauncherBridge()?.[action] === "function";
}

/** Open with the system default program. "unavailable" outside Electron or on a shell error. */
export async function openWorkspaceFile(path: string): Promise<WorkspaceFileActionResult> {
  const result = await openPath(path);
  if (hasDesktopBridgeAction("openPath") && result === "") {
    return "done";
  }
  return "unavailable";
}

/** Reveal in the system file manager. "unavailable" outside Electron or on a shell error. */
export async function revealWorkspaceFile(path: string): Promise<WorkspaceFileActionResult> {
  if (!hasDesktopBridgeAction("showItemInFolder")) {
    return "unavailable";
  }
  return (await showItemInFolder(path)) ? "done" : "unavailable";
}

/** Clipboard write with the legacy `execCommand` fallback; false when both fail. */
export async function copyWorkspaceFilePath(path: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(path);
      return true;
    } catch {
      return false;
    }
  }
  const textArea = document.createElement("textarea");
  textArea.value = path;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "absolute";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  return copied;
}
