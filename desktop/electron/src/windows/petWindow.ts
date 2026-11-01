import { BrowserWindow, screen } from "electron";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath } from "../paths.js";
import type { ElectronWindowCreateOptions } from "./electronWindowProvider.js";
import {
  clampPetWindowBounds,
  desktopPetWindowExpandedBounds,
  defaultPetWindowBounds,
  type PetWindowBounds,
} from "./petWindowBounds.js";

const PET_BOUNDS_FILE = "desktop-pet-window.json";

export function createPetWindow(_url: string, paths: Pick<DesktopPaths, "desktopBundleRoot" | "userDataRoot">,
  _options?: ElectronWindowCreateOptions,
  role: "desktop-pet" | "launcher-assistant" = "desktop-pet"): BrowserWindow {
  const boundsPath = join(paths.userDataRoot, role === "launcher-assistant" ? "launcher-assistant-window.json" : PET_BOUNDS_FILE);
  const saved = readSavedBounds(boundsPath);
  const display = saved
    ? screen.getDisplayNearestPoint({ x: saved.x, y: saved.y })
    : screen.getPrimaryDisplay();
  const bounds = saved
    ? clampPetWindowBounds(saved, display.workArea)
    : defaultPetWindowBounds(display.workArea);

  const window = new BrowserWindow({
    ...bounds,
    show: false,
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    hasShadow: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: resolvePreloadPath(paths),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: [`--vibelution-window-role=${role}`],
    },
  });
  window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  window.webContents.on("did-navigate", (_event, url) => {
    // Re-entering the assistant surface always starts collapsed; expanded sizes are never persisted.
    if (role !== "launcher-assistant" || url !== "vibelution-launcher://launcher/launcher-assistant") return;
    if (window.isDestroyed()) return;
    const current = window.getBounds();
    window.setBounds(desktopPetWindowExpandedBounds(current, screen.getDisplayMatching(current).workArea, false), false);
  });
  window.on("moved", () => persistBounds(boundsPath, window.getBounds()));
  return window;
}

function readSavedBounds(path: string): Pick<PetWindowBounds, "x" | "y"> | null {
  try {
    const payload = JSON.parse(readFileSync(path, "utf8")) as { x?: unknown; y?: unknown };
    if (Number.isFinite(payload.x) && Number.isFinite(payload.y)) {
      return { x: Number(payload.x), y: Number(payload.y) };
    }
  } catch {
    // A missing or malformed preference uses the current primary display.
  }
  return null;
}

function persistBounds(path: string, bounds: Pick<PetWindowBounds, "x" | "y">): void {
  try {
    mkdirSync(dirname(path), { recursive: true });
    const temporary = `${path}.${process.pid}.tmp`;
    writeFileSync(temporary, `${JSON.stringify({ schemaVersion: 1, x: bounds.x, y: bounds.y })}\n`, "utf8");
    renameSync(temporary, path);
  } catch {
    // Position persistence must never break the visible companion.
  }
}
