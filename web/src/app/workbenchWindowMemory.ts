/**
 * Remember Workbench window presentation (fullscreen vs windowed + size).
 *
 * Launcher starts Edge with --start-fullscreen / --window-size from operator
 * config. F11 and manual windowize must write those settings back so the next
 * start matches what the user left on screen.
 */

import { fetchJson } from "../api/client";
import { LAUNCHER_ENDPOINT } from "../api/launcher";

export type ObservedWorkbenchWindowMode = "fullscreen" | "windowed";

const SAVE_DEBOUNCE_MS = 700;
const SIZE_QUANTUM = 16;

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let lastSavedMode: ObservedWorkbenchWindowMode | null = null;
let lastSavedSize = "";
let started = false;

/** Fullscreen covers the whole screen (including taskbar region); maximize usually does not. */
export function observeWorkbenchWindowMode(
  win: Pick<Window, "outerWidth" | "outerHeight" | "screen"> = window,
): ObservedWorkbenchWindowMode {
  const width = Number(win.outerWidth) || 0;
  const height = Number(win.outerHeight) || 0;
  const screenWidth = Number(win.screen?.width) || 0;
  const screenHeight = Number(win.screen?.height) || 0;
  if (width <= 0 || height <= 0 || screenWidth <= 0 || screenHeight <= 0) {
    return "windowed";
  }
  const fillsWidth = width >= screenWidth - 2;
  const fillsHeight = height >= screenHeight - 2;
  return fillsWidth && fillsHeight ? "fullscreen" : "windowed";
}

export function observeWorkbenchWindowSize(
  win: Pick<Window, "outerWidth" | "outerHeight" | "screen"> = window,
): string {
  const rawWidth = Math.max(320, Math.round(Number(win.outerWidth) || 0));
  const rawHeight = Math.max(240, Math.round(Number(win.outerHeight) || 0));
  const availWidth = Math.max(320, Math.round(Number(win.screen?.availWidth) || rawWidth));
  const availHeight = Math.max(240, Math.round(Number(win.screen?.availHeight) || rawHeight));
  // Never persist a size larger than the work area — oversized --window-size can
  // leave Edge app windows created but not visible on the next start.
  const width = Math.min(rawWidth, availWidth);
  const height = Math.min(rawHeight, availHeight);
  // Quantize slightly so micro-resizes do not thrash config writes.
  const qWidth = Math.round(width / SIZE_QUANTUM) * SIZE_QUANTUM;
  const qHeight = Math.round(height / SIZE_QUANTUM) * SIZE_QUANTUM;
  return `${Math.max(320, qWidth)}x${Math.max(240, qHeight)}`;
}

async function persistObservedWindow(mode: ObservedWorkbenchWindowMode, size: string): Promise<void> {
  if (mode === lastSavedMode && (mode === "fullscreen" || size === lastSavedSize)) {
    return;
  }
  const workbench: { windowMode: ObservedWorkbenchWindowMode; windowSize?: string } = {
    windowMode: mode,
  };
  if (mode === "windowed" && size) {
    workbench.windowSize = size;
  }
  try {
    // Startup settings accept empty baseHash (soft write). Only patch workbench.
    await fetchJson(`${LAUNCHER_ENDPOINT}/settings/startup`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workbench }),
    });
    lastSavedMode = mode;
    if (mode === "windowed") {
      lastSavedSize = size;
    }
  } catch {
    // Backend may be restarting; try again on next observation.
  }
}

function schedulePersist(): void {
  if (typeof window === "undefined") {
    return;
  }
  if (saveTimer) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    saveTimer = null;
    const mode = observeWorkbenchWindowMode();
    const size = observeWorkbenchWindowSize();
    void persistObservedWindow(mode, size);
  }, SAVE_DEBOUNCE_MS);
}

/**
 * Observe F11 / resize / visibility and persist window_mode (+ window_size when windowed).
 * Returns a disposer.
 */
export function startWorkbenchWindowMemory(): () => void {
  if (typeof window === "undefined" || started) {
    return () => undefined;
  }
  started = true;

  // Seed from first observation without waiting for user input.
  schedulePersist();

  const onResize = () => schedulePersist();
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "F11") {
      // Chromium toggles after the key event; observe shortly after.
      window.setTimeout(schedulePersist, 50);
      window.setTimeout(schedulePersist, 250);
    }
  };
  const onVisibility = () => {
    if (document.visibilityState === "visible") {
      schedulePersist();
    }
  };

  window.addEventListener("resize", onResize);
  window.addEventListener("keydown", onKeyDown);
  document.addEventListener("visibilitychange", onVisibility);

  return () => {
    started = false;
    window.removeEventListener("resize", onResize);
    window.removeEventListener("keydown", onKeyDown);
    document.removeEventListener("visibilitychange", onVisibility);
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
  };
}

export function resetWorkbenchWindowMemoryForTests(): void {
  started = false;
  lastSavedMode = null;
  lastSavedSize = "";
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
}
