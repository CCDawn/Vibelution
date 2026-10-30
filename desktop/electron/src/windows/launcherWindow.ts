import { BrowserWindow } from "electron";
import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath, resolveWorkspaceIconPath } from "../paths.js";
import { instanceWindowTitle } from "./instanceWindowTitle.js";

/**
 * Identity registry for launcher control windows. The assistant invoke handler
 * identifies these senders by exact webContents identity. Privileged IPC also
 * checks the main frame and the URL pinned when the window was created.
 * Membership lives in a WeakSet and disappears with the webContents.
 */
const launcherControlSenders = new WeakSet<object>();
const launcherControlUrls = new WeakMap<object, string>();

/** The trusted destination is pinned when main creates the window. */
export function isTrustedLauncherWindowUrl(candidate: string, expected: string): boolean {
  try {
    const url = new URL(candidate);
    const target = new URL(expected);
    if (url.username || url.password || target.username || target.password
      || url.protocol !== target.protocol || url.host !== target.host) return false;
    const route = (path: string) => path.replace(/\/+$/, "") || "/";
    const expectedRoute = route(target.pathname);
    const actualRoute = route(url.pathname);
    return expectedRoute === "/launcher" || expectedRoute.startsWith("/launcher/")
      ? actualRoute === "/launcher" || actualRoute.startsWith("/launcher/")
      : actualRoute === expectedRoute;
  } catch { return false; }
}

export function isTrustedLauncherControlFrame(event: { sender: unknown; senderFrame?: { url: string } | null }): boolean {
  const sender = event.sender as { mainFrame?: unknown; getURL?: () => string; isDestroyed?: () => boolean } | null;
  if (!sender || !isLauncherControlSender(sender) || !event.senderFrame
      || event.senderFrame !== sender.mainFrame || typeof sender.getURL !== "function"
      || (typeof sender.isDestroyed === "function" && sender.isDestroyed())) return false;
  const expected = launcherControlUrls.get(sender);
  if (!expected) return false;
  try { return isTrustedLauncherWindowUrl(event.senderFrame.url, expected) && isTrustedLauncherWindowUrl(sender.getURL(), expected); }
  catch { return false; }
}

export function isLauncherControlSender(sender: unknown): boolean {
  return typeof sender === "object" && sender !== null && launcherControlSenders.has(sender);
}

export function createLauncherWindow(url: string, paths: DesktopPaths): BrowserWindow {
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    title: instanceWindowTitle("launcher"),
    icon: resolveWorkspaceIconPath(paths),
    backgroundColor: "#e9e9e9",
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#00000000",
      height: 44
    },
    skipTaskbar: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: resolvePreloadPath(paths),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: ["--vibelution-window-role=launcher-control"]
    }
  });
  launcherControlSenders.add(window.webContents);
  launcherControlUrls.set(window.webContents, url);
  window.webContents.on("will-navigate", (event, target) => {
    if (!isTrustedLauncherWindowUrl(event.url ?? target, url)) event.preventDefault();
  });
  window.webContents.on("will-redirect", (event, target, _inPlace, isMainFrame) => {
    if ((event.isMainFrame ?? isMainFrame) !== false && !isTrustedLauncherWindowUrl(event.url ?? target, url)) event.preventDefault();
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  void window.loadURL(url);
  return window;
}
