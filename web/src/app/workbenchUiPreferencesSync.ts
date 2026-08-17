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
} from "../components/layout/paneLayoutPersistence";
import { CHAT_PANE_LAYOUT_ID, useShellStore } from "../store/shellStore";

let hydratePromise: Promise<void> | null = null;
let saveTimer: ReturnType<typeof setTimeout> | null = null;
let lastShellFingerprint = "";
let readyToSave = false;

function shellFingerprint(state: {
  leftPanelWidth: number;
  rightPanelWidth: number;
  topBarMode: string;
}): string {
  return `${state.leftPanelWidth}|${state.rightPanelWidth}|${state.topBarMode}`;
}

function applyServerPreferences(prefs: WorkbenchUiPreferences): void {
  if (prefs.paneLayouts && Object.keys(prefs.paneLayouts).length) {
    const local = readAllPaneLayouts();
    writeAllPaneLayouts({ ...local, ...prefs.paneLayouts });
  }

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
  const nextTopBar = shell.topBarMode === "full" || shell.topBarMode === "hidden" ? shell.topBarMode : undefined;
  useShellStore.setState({
    chatPanelWidths: nextWidths,
    ...(nextTopBar ? { topBarMode: nextTopBar } : {}),
  });

  lastShellFingerprint = shellFingerprint({
    leftPanelWidth: useShellStore.getState().chatPanelWidths.leftPanelWidth,
    rightPanelWidth: useShellStore.getState().chatPanelWidths.rightPanelWidth,
    topBarMode: useShellStore.getState().topBarMode,
  });
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
  if (typeof window === "undefined") {
    return;
  }
  const state = useShellStore.getState();
  const fingerprint = shellFingerprint({
    leftPanelWidth: state.chatPanelWidths.leftPanelWidth,
    rightPanelWidth: state.chatPanelWidths.rightPanelWidth,
    topBarMode: state.topBarMode,
  });
  if (fingerprint === lastShellFingerprint) {
    // Still push full pane-layouts map when local storage has more layouts.
  }
  lastShellFingerprint = fingerprint;

  const paneLayouts = readAllPaneLayouts();
  try {
    await saveWorkbenchUiPreferences({
      paneLayouts,
      shell: {
        topBarMode: state.topBarMode,
      },
    });
  } catch {
    // Offline / early boot — localStorage still holds the session copy.
  }
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
    hydratePromise = getWorkbenchUiPreferences()
      .then((prefs) => {
        applyServerPreferences(prefs);
        readyToSave = true;
        // If server empty but local has values, push once.
        const localLayouts = readAllPaneLayouts();
        const serverEmpty = !prefs.paneLayouts || Object.keys(prefs.paneLayouts).length === 0;
        const localHas = Object.keys(localLayouts).length > 0;
        if (serverEmpty && localHas) {
          void flushWorkbenchUiPreferencesToServer();
        }
      })
      .catch(() => {
        // Keep localStorage-only until backend is reachable; still allow later saves.
        readyToSave = true;
      });
  }

  const unsubscribe = useShellStore.subscribe((state, prev) => {
    const widthsChanged =
      state.chatPanelWidths.leftPanelWidth !== prev.chatPanelWidths.leftPanelWidth
      || state.chatPanelWidths.rightPanelWidth !== prev.chatPanelWidths.rightPanelWidth;
    const topBarChanged = state.topBarMode !== prev.topBarMode;
    if (widthsChanged || topBarChanged) {
      scheduleServerSave();
    }
  });

  setPaneLayoutPersistHook(() => {
    scheduleServerSave();
  });

  // Cross-tab: other tabs writing localStorage.
  const onStorage = (event: StorageEvent) => {
    if (event.key === PANE_LAYOUT_STORAGE_KEY && event.newValue) {
      scheduleServerSave();
    }
  };
  window.addEventListener("storage", onStorage);

  return () => {
    unsubscribe();
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
  lastShellFingerprint = "";
  readyToSave = false;
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
}
