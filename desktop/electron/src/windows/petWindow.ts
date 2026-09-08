import { BrowserWindow, screen } from "electron";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import type { DesktopPaths } from "../paths.js";
import { resolvePreloadPath } from "../paths.js";
import {
  clampPetWindowBounds,
  defaultPetWindowBounds,
  type PetWindowBounds,
} from "./petWindowBounds.js";

const PET_BOUNDS_FILE = "desktop-pet-window.json";

export function desktopPetWindowUrl(workbenchUrl: string): string {
  const url = new URL(workbenchUrl);
  url.pathname = "/desktop-pet";
  url.search = "";
  url.hash = "";
  return url.toString();
}

export function isDesktopPetWindowUrl(rawUrl: string): boolean {
  try {
    return new URL(rawUrl).pathname === "/desktop-pet";
  } catch {
    return false;
  }
}

export function createPetWindow(_url: string, paths: DesktopPaths): BrowserWindow {
  const boundsPath = join(paths.userDataRoot, PET_BOUNDS_FILE);
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
      additionalArguments: ["--vibelution-window-role=desktop-pet"],
    },
  });
  window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
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
