/**
 * Remember Workbench window presentation (fullscreen vs windowed + size + position).
 *
 * Launcher starts Edge with --start-fullscreen / --window-size / --window-position
 * from operator config. F11, resize, and drag-move must write those settings back so
 * the next start matches what the user left on screen.
 */

import { fetchJson } from "../api/client";
import { LAUNCHER_ENDPOINT } from "../api/launcher";

export type ObservedWorkbenchWindowMode = "fullscreen" | "windowed";

const SAVE_DEBOUNCE_MS = 700;
const SIZE_QUANTUM = 16;
const POSITION_QUANTUM = 8;
/** Pure window moves do not fire `resize`; poll lightly so drag position is durable. */
const POSITION_POLL_MS = 1000;

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let positionPollTimer: ReturnType<typeof setInterval> | null = null;
let lastSavedMode: ObservedWorkbenchWindowMode | null = null;
let lastSavedSize = "";
let lastSavedPosition = "";
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

/** Usable workbench floor — never persist Edge --app chrome sizes like 320x240. */
export const WORKBENCH_WINDOW_SIZE_MIN_WIDTH = 960;
export const WORKBENCH_WINDOW_SIZE_MIN_HEIGHT = 600;

export function observeWorkbenchWindowSize(
  win: Pick<Window, "outerWidth" | "outerHeight" | "screen"> = window,
): string {
  const rawWidth = Math.round(Number(win.outerWidth) || 0);
  const rawHeight = Math.round(Number(win.outerHeight) || 0);
  const availWidth = Math.max(
    WORKBENCH_WINDOW_SIZE_MIN_WIDTH,
    Math.round(Number(win.screen?.availWidth) || rawWidth),
  );
  const availHeight = Math.max(
    WORKBENCH_WINDOW_SIZE_MIN_HEIGHT,
    Math.round(Number(win.screen?.availHeight) || rawHeight),
  );
  // Never persist a size larger than the work area — oversized --window-size can
  // leave Edge app windows created but not visible on the next start.
  const width = Math.min(Math.max(rawWidth, 0), availWidth);
  const height = Math.min(Math.max(rawHeight, 0), availHeight);
  // Quantize slightly so micro-resizes do not thrash config writes.
  const qWidth = Math.round(width / SIZE_QUANTUM) * SIZE_QUANTUM;
  const qHeight = Math.round(height / SIZE_QUANTUM) * SIZE_QUANTUM;
  return `${Math.max(WORKBENCH_WINDOW_SIZE_MIN_WIDTH, qWidth)}x${Math.max(WORKBENCH_WINDOW_SIZE_MIN_HEIGHT, qHeight)}`;
}

export function isPersistableWorkbenchWindowSize(size: string): boolean {
  const match = /^(\d{3,5})x(\d{3,5})$/.exec(String(size || "").trim().toLowerCase());
  if (!match) {
    return false;
  }
  const width = Number(match[1]);
  const height = Number(match[2]);
  return (
    width >= WORKBENCH_WINDOW_SIZE_MIN_WIDTH
    && height >= WORKBENCH_WINDOW_SIZE_MIN_HEIGHT
    && width <= 7680
    && height <= 4320
  );
}

/** Multi-monitor positions allowed; extremes like ±20000 are treated as unusable/off-screen. */
export const WORKBENCH_WINDOW_POSITION_MAX_ABS = 8000;

/**
 * Observe top-left outer position as `X,Y` (screen coords; may be negative on multi-monitor).
 * Quantized so drag micro-jitter does not thrash operator config writes.
 * Does not clamp to extremes — off-screen garbage must fail isPersistable instead.
 */
export function observeWorkbenchWindowPosition(
  win: Pick<Window, "screenX" | "screenY"> = window,
): string {
  const rawX = Math.round(Number(win.screenX) || 0);
  const rawY = Math.round(Number(win.screenY) || 0);
  const qX = Math.round(rawX / POSITION_QUANTUM) * POSITION_QUANTUM;
  const qY = Math.round(rawY / POSITION_QUANTUM) * POSITION_QUANTUM;
  return `${qX},${qY}`;
}

export function isPersistableWorkbenchWindowPosition(position: string): boolean {
  const match = /^(-?\d{1,5}),(-?\d{1,5})$/.exec(String(position || "").trim().toLowerCase());
  if (!match) {
    return false;
  }
  const x = Number(match[1]);
  const y = Number(match[2]);
  // Reject ±20000-class sentinels that place the next Edge start fully off-screen.
  return (
    Number.isFinite(x)
    && Number.isFinite(y)
    && Math.abs(x) <= WORKBENCH_WINDOW_POSITION_MAX_ABS
    && Math.abs(y) <= WORKBENCH_WINDOW_POSITION_MAX_ABS
  );
}

async function persistObservedWindow(
  mode: ObservedWorkbenchWindowMode,
  size: string,
  position: string,
): Promise<void> {
  if (
    mode === lastSavedMode
    && (mode === "fullscreen" || (size === lastSavedSize && position === lastSavedPosition))
  ) {
    return;
  }
  const workbench: {
    windowMode: ObservedWorkbenchWindowMode;
    windowSize?: string;
    windowPosition?: string;
  } = {
    windowMode: mode,
  };
  // Skip tiny frames (orphan Edge shells / failed restores) so the next start
  // is not locked to 320x240-class sizes. Position is only meaningful when windowed.
  if (mode === "windowed" && size && isPersistableWorkbenchWindowSize(size)) {
    workbench.windowSize = size;
  }
  if (mode === "windowed" && position && isPersistableWorkbenchWindowPosition(position)) {
    workbench.windowPosition = position;
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
      lastSavedPosition = position;
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
    const position = observeWorkbenchWindowPosition();
    void persistObservedWindow(mode, size, position);
  }, SAVE_DEBOUNCE_MS);
}

/**
 * Observe F11 / resize / drag-move / visibility and persist
 * window_mode (+ window_size / window_position when windowed).
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
  positionPollTimer = window.setInterval(schedulePersist, POSITION_POLL_MS);

  return () => {
    started = false;
    window.removeEventListener("resize", onResize);
    window.removeEventListener("keydown", onKeyDown);
    document.removeEventListener("visibilitychange", onVisibility);
    if (positionPollTimer) {
      clearInterval(positionPollTimer);
      positionPollTimer = null;
    }
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
  lastSavedPosition = "";
  if (positionPollTimer) {
    clearInterval(positionPollTimer);
    positionPollTimer = null;
  }
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
}
