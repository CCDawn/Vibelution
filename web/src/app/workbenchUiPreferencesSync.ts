/**
 * Port/origin-stable UI layout memory.
 *
 * Canonical Chat widths live in vibelution.pane-layouts.v1[chat].
 * Server paneLayouts is a durable mirror. leftover shell.chatPanelWidths is
 * migrated once when canonical is missing, then dropped.
 */

import {
  getWorkbenchUiPreferences,
  saveWorkbenchUiPreferences,
  type WorkbenchUiPreferences,
} from "../api/workbenchUiPreferences";
import {
  PANE_LAYOUT_STORAGE_KEY,
  readAllPaneLayouts,
  readPaneLayout,
  setPaneLayoutPersistHook,
  writeAllPaneLayouts,
  writePaneLayout,
  type PaneLayoutsMap,
  type PaneWidthMap,
} from "../components/layout/paneLayoutPersistence";
import { CHAT_PANE_LAYOUT_ID, useShellStore } from "../store/shellStore";

let hydratePromise: Promise<void> | null = null;
let saveTimer: ReturnType<typeof setTimeout> | null = null;
let readyToSave = false;
let applyingServer = false;
let observedLayouts: PaneLayoutsMap = {};
let flushPromise: Promise<void> | null = null;
let flushRequested = false;
let syncEpoch = 0;

// Widths remain in the shared canonical store; this only records unacknowledged edits.
const PENDING_LAYOUTS_KEY = "vibelution.workbench-ui-pending-layouts.v1";

function readPendingLayouts(): Record<string, string> {
  try {
    const value = JSON.parse(window.localStorage.getItem(PENDING_LAYOUTS_KEY) || "null");
    if (value?.schemaVersion !== 1 || !value.layouts || typeof value.layouts !== "object" || Array.isArray(value.layouts)) return {};
    return Object.fromEntries(Object.entries(value.layouts).filter(
      (entry): entry is [string, string] => Boolean(entry[0] && typeof entry[1] === "string" && entry[1]),
    ));
  } catch {
    return {};
  }
}

function writePendingLayouts(layouts: Record<string, string>): void {
  try {
    if (Object.keys(layouts).length) {
      window.localStorage.setItem(PENDING_LAYOUTS_KEY, JSON.stringify({ schemaVersion: 1, layouts }));
    } else {
      window.localStorage.removeItem(PENDING_LAYOUTS_KEY);
    }
  } catch {
    // Storage may be unavailable; do not break pane interaction.
  }
}

function sameWidths(left: PaneWidthMap | undefined, right: PaneWidthMap | undefined): boolean {
  if (!left || !right) return left === right;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every(key => left[key] === right[key]);
}

function observeLocalChanges(): void {
  if (applyingServer) return;
  const current = readAllPaneLayouts();
  const pending = readPendingLayouts();
  let changed = false;
  for (const [layoutId, widths] of Object.entries(current)) {
    if (!sameWidths(widths, observedLayouts[layoutId])) {
      pending[layoutId] = crypto.randomUUID();
      changed = true;
    }
  }
  observedLayouts = current;
  if (changed) {
    writePendingLayouts(pending);
    if (flushPromise) flushRequested = true;
    scheduleServerSave();
  }
}

function applyServerPreferences(prefs: WorkbenchUiPreferences): void {
  const local = readAllPaneLayouts();
  const pending = readPendingLayouts();
  const merged = { ...local };
  for (const [layoutId, widths] of Object.entries(prefs.paneLayouts || {})) {
    if (!pending[layoutId] || !local[layoutId]) merged[layoutId] = widths;
  }
  writeAllPaneLayouts(merged);

  const canonical = readPaneLayout(CHAT_PANE_LAYOUT_ID);
  const hasCanonical = Boolean(canonical.left || canonical.right);
  const shell = prefs.shell || {};
  if (!hasCanonical) {
    const chat = shell.chatPanelWidths;
    const left = Number(chat?.leftPanelWidth);
    const right = Number(chat?.rightPanelWidth);
    if (Number.isFinite(left) && left > 0 && Number.isFinite(right) && right > 0) {
      writePaneLayout(CHAT_PANE_LAYOUT_ID, {
        left: Math.round(left),
        right: Math.round(right),
      });
    }
  }

  const stored = readPaneLayout(CHAT_PANE_LAYOUT_ID);
  const current = useShellStore.getState().chatPanelWidths;
  const nextWidths = {
    leftPanelWidth: stored.left || current.leftPanelWidth,
    rightPanelWidth: stored.right || current.rightPanelWidth,
  };
  useShellStore.setState({
    chatPanelWidths: nextWidths,
  });

  observedLayouts = readAllPaneLayouts();
  for (const layoutId of Object.keys(observedLayouts)) {
    if (!prefs.paneLayouts?.[layoutId] && !pending[layoutId]) pending[layoutId] = crypto.randomUUID();
  }
  writePendingLayouts(pending);
}

function scheduleServerSave(): void {
  if (typeof window === "undefined" || !readyToSave) {
    return;
  }
  if (saveTimer) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    saveTimer = null;
    void flushWorkbenchUiPreferencesToServer();
  }, 450);
}

export async function flushWorkbenchUiPreferencesToServer(): Promise<void> {
  if (typeof window === "undefined" || !readyToSave) return;
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
  if (flushPromise) { flushRequested = true; return flushPromise; }
  const epoch = syncEpoch;
  const attempted = new Map<string, string>();
  flushPromise = (async () => {
    do {
      flushRequested = false;
      for (const [layoutId, generation] of Object.entries(readPendingLayouts())) {
        if (epoch !== syncEpoch) return;
        if (attempted.get(layoutId) === generation) continue;
        const widths = readPaneLayout(layoutId);
        if (!Object.keys(widths).length) continue;
        attempted.set(layoutId, generation);
        try {
          const result = await saveWorkbenchUiPreferences({ paneLayout: { layoutId, widths } });
          if (epoch !== syncEpoch) return;
          const pending = readPendingLayouts();
          if (result.ok && sameWidths(result.preferences.paneLayouts?.[layoutId], widths)
            && pending[layoutId] === generation && sameWidths(readPaneLayout(layoutId), widths)) {
            delete pending[layoutId];
            writePendingLayouts(pending);
          }
        } catch {
          // Keep the edit pending across reload. Retry on a later change or flush.
        }
      }
    } while (flushRequested && epoch === syncEpoch);
  })().finally(() => {
    if (epoch === syncEpoch) flushPromise = null;
  });
  return flushPromise;
}

/**
 * Hydrate shell + pane layouts from project-local preferences, then mirror
 * paneLayouts to the server. Chat widths are not written back to shell.chatPanelWidths.
 */
export function startWorkbenchUiPreferencesSync(): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }

  if (!hydratePromise) {
    const epoch = syncEpoch;
    observedLayouts = readAllPaneLayouts();
    hydratePromise = getWorkbenchUiPreferences()
      .then((prefs) => {
        if (epoch !== syncEpoch) return;
        applyingServer = true;
        try { applyServerPreferences(prefs); } finally { applyingServer = false; }
        readyToSave = true;
        if (Object.keys(readPendingLayouts()).length) {
          void flushWorkbenchUiPreferencesToServer();
        }
      })
      .catch(() => {
        if (epoch !== syncEpoch) return;
        // Keep localStorage-only until backend is reachable; still allow later saves.
        readyToSave = true;
      });
  }

  setPaneLayoutPersistHook(observeLocalChanges);

  // Cross-tab: other tabs writing localStorage.
  const onStorage = (event: StorageEvent) => {
    if (event.key === PANE_LAYOUT_STORAGE_KEY && event.newValue) {
      observeLocalChanges();
    }
  };
  window.addEventListener("storage", onStorage);

  return () => {
    setPaneLayoutPersistHook(null);
    window.removeEventListener("storage", onStorage);
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
  };
}

export function resetWorkbenchUiPreferencesSyncForTests(): void {
  hydratePromise = null;
  readyToSave = false;
  applyingServer = false;
  observedLayouts = {};
  flushPromise = null;
  flushRequested = false;
  syncEpoch += 1;
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
}
