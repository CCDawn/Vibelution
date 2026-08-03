/**
 * Port/origin-stable UI layout memory.
 *
 * Browser localStorage is origin-scoped (8000 vs 8002 loses state). We dual-write
 * preferred chat/shell widths into project-local `.runtime/workbench/ui-preferences.json`
 * via the backend and hydrate on boot.
 */

import {
  getWorkbenchUiPreferences,
  saveWorkbenchUiPreferences,
  type WorkbenchUiPreferences,
} from "../api/workbenchUiPreferences";
import {
  PANE_LAYOUT_STORAGE_KEY,
  readAllPaneLayouts,
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

  const shell = prefs.shell || {};
  const patch: {
    chatPanelWidths?: { leftPanelWidth: number; rightPanelWidth: number };
    topBarMode?: "full" | "hidden";
  } = {};

  const chat = shell.chatPanelWidths;
  const current = useShellStore.getState().chatPanelWidths;
  if (chat) {
    const left = Number(chat.leftPanelWidth);
    const right = Number(chat.rightPanelWidth);
    if (Number.isFinite(left) && left > 0 && Number.isFinite(right) && right > 0) {
      patch.chatPanelWidths = {
        leftPanelWidth: Math.round(left),
        rightPanelWidth: Math.round(right),
      };
    } else if (Number.isFinite(left) && left > 0) {
      patch.chatPanelWidths = {
        leftPanelWidth: Math.round(left),
        rightPanelWidth: current.rightPanelWidth,
      };
    } else if (Number.isFinite(right) && right > 0) {
      patch.chatPanelWidths = {
        leftPanelWidth: current.leftPanelWidth,
        rightPanelWidth: Math.round(right),
      };
    }
  }

  if (shell.topBarMode === "full" || shell.topBarMode === "hidden") {
    patch.topBarMode = shell.topBarMode;
  }

  if (patch.chatPanelWidths) {
    useShellStore.setState({
      chatPanelWidths: patch.chatPanelWidths,
      ...(patch.topBarMode ? { topBarMode: patch.topBarMode } : {}),
    });
    writePaneLayout(CHAT_PANE_LAYOUT_ID, {
      left: patch.chatPanelWidths.leftPanelWidth,
      right: patch.chatPanelWidths.rightPanelWidth,
    });
  } else if (patch.topBarMode) {
    useShellStore.setState({ topBarMode: patch.topBarMode });
  }

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
        chatPanelWidths: {
          leftPanelWidth: state.chatPanelWidths.leftPanelWidth,
          rightPanelWidth: state.chatPanelWidths.rightPanelWidth,
        },
        topBarMode: state.topBarMode,
      },
    });
  } catch {
    // Offline / early boot — localStorage still holds the session copy.
  }
}

/**
 * Hydrate shell + pane layouts from project-local preferences, then keep them
 * dual-written on subsequent shell changes.
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
