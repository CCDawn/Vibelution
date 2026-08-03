import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";

import {
  persistPaneWidths,
  readPaneLayout,
  resolveStoredPaneWidth,
} from "../components/layout/paneLayoutPersistence";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";

type EvolutionTrack = "supervised" | "self";
type EvolutionView = "live" | "runs" | "library" | "overview";
export type ShellTopBarMode = "full" | "hidden";

type ChatPanelWidths = {
  leftPanelWidth: number;
  rightPanelWidth: number;
};

type ShellState = {
  evolutionTrack: EvolutionTrack;
  evolutionView: EvolutionView;
  chatPanelWidths: ChatPanelWidths;
  topBarMode: ShellTopBarMode;
  setEvolutionTrack: (track: EvolutionTrack) => void;
  setEvolutionView: (view: EvolutionView) => void;
  setChatPanelWidths: (widths: Partial<ChatPanelWidths>) => void;
  setTopBarMode: (mode: ShellTopBarMode) => void;
};

/** Shared permanent memory under vibelution.pane-layouts.v1["chat"]. */
export const CHAT_PANE_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.chat;

const DEFAULT_CHAT_PANEL_WIDTHS: ChatPanelWidths = {
  leftPanelWidth: 300,
  rightPanelWidth: 220,
};

const LEGACY_STATUS_LEFT_PANEL_WIDTHS: ChatPanelWidths = {
  leftPanelWidth: 260,
  rightPanelWidth: 340,
};

const CHAT_LEFT_PANE_BOUNDS = { min: 260, max: 560 };
const CHAT_RIGHT_PANE_BOUNDS = { min: 200, max: 520 };

function normalizePanelWidth(
  value: unknown,
  fallback: number,
  bounds: { min: number; max: number },
) {
  const numericValue = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numericValue)) {
    return fallback;
  }
  return Math.min(bounds.max, Math.max(bounds.min, Math.round(numericValue)));
}

function dualWriteChatPaneLayouts(widths: ChatPanelWidths): void {
  persistPaneWidths(CHAT_PANE_LAYOUT_ID, {
    left: widths.leftPanelWidth,
    right: widths.rightPanelWidth,
  });
}

function readChatPaneLayoutsFallback(): ChatPanelWidths | null {
  const stored = readPaneLayout(CHAT_PANE_LAYOUT_ID);
  if (!stored.left && !stored.right) {
    return null;
  }
  return {
    leftPanelWidth: resolveStoredPaneWidth(
      CHAT_PANE_LAYOUT_ID,
      "left",
      DEFAULT_CHAT_PANEL_WIDTHS.leftPanelWidth,
      CHAT_LEFT_PANE_BOUNDS.min,
      CHAT_LEFT_PANE_BOUNDS.max,
    ),
    rightPanelWidth: resolveStoredPaneWidth(
      CHAT_PANE_LAYOUT_ID,
      "right",
      DEFAULT_CHAT_PANEL_WIDTHS.rightPanelWidth,
      CHAT_RIGHT_PANE_BOUNDS.min,
      CHAT_RIGHT_PANE_BOUNDS.max,
    ),
  };
}

function normalizePersistedChatPanelWidths(widths: Partial<ChatPanelWidths> | undefined): ChatPanelWidths {
  if (
    widths?.leftPanelWidth === LEGACY_STATUS_LEFT_PANEL_WIDTHS.leftPanelWidth &&
    widths?.rightPanelWidth === LEGACY_STATUS_LEFT_PANEL_WIDTHS.rightPanelWidth
  ) {
    return DEFAULT_CHAT_PANEL_WIDTHS;
  }

  const fromShell = {
    leftPanelWidth: normalizePanelWidth(
      widths?.leftPanelWidth,
      DEFAULT_CHAT_PANEL_WIDTHS.leftPanelWidth,
      CHAT_LEFT_PANE_BOUNDS,
    ),
    rightPanelWidth: normalizePanelWidth(
      widths?.rightPanelWidth,
      DEFAULT_CHAT_PANEL_WIDTHS.rightPanelWidth,
      CHAT_RIGHT_PANE_BOUNDS,
    ),
  };

  // Prefer shell store values when present; otherwise hydrate from shared pane-layouts.
  if (widths?.leftPanelWidth != null || widths?.rightPanelWidth != null) {
    dualWriteChatPaneLayouts(fromShell);
    return fromShell;
  }

  const fromShared = readChatPaneLayoutsFallback();
  return fromShared ?? DEFAULT_CHAT_PANEL_WIDTHS;
}

/**
 * Always read/write the live global localStorage.
 * createJSONStorage() captures getStorage() once at module load; a frozen
 * reference would break tests and any late-available storage.
 */
const DYNAMIC_SHELL_STORAGE: StateStorage = {
  getItem: (name) => {
    try {
      if (typeof localStorage === "undefined") {
        return null;
      }
      return localStorage.getItem(name);
    } catch {
      return null;
    }
  },
  setItem: (name, value) => {
    try {
      if (typeof localStorage === "undefined") {
        return;
      }
      localStorage.setItem(name, value);
    } catch {
      // Quota / private mode — ignore.
    }
  },
  removeItem: (name) => {
    try {
      if (typeof localStorage === "undefined") {
        return;
      }
      localStorage.removeItem(name);
    } catch {
      // ignore
    }
  },
};

export const useShellStore = create<ShellState>()(
  persist(
    (set) => ({
      evolutionTrack: "supervised",
      evolutionView: "live",
      chatPanelWidths: DEFAULT_CHAT_PANEL_WIDTHS,
      topBarMode: "full",
      setEvolutionTrack: (evolutionTrack) => set({ evolutionTrack }),
      setEvolutionView: (evolutionView) => set({ evolutionView }),
      setChatPanelWidths: (widths) =>
        set((state) => {
          const next = {
            ...state.chatPanelWidths,
            ...widths,
          };
          dualWriteChatPaneLayouts(next);
          return { chatPanelWidths: next };
        }),
      setTopBarMode: (topBarMode) => set({ topBarMode }),
    }),
    {
      name: "vibelution-shell-store",
      storage: createJSONStorage(() => DYNAMIC_SHELL_STORAGE),
      partialize: (state) => ({
        evolutionTrack: state.evolutionTrack,
        evolutionView: state.evolutionView,
        chatPanelWidths: state.chatPanelWidths,
        topBarMode: state.topBarMode,
      }),
      merge: (persistedState, currentState) => {
        const persistedShellState =
          persistedState && typeof persistedState === "object" ? persistedState as Partial<ShellState> : {};
        return {
          ...currentState,
          ...persistedShellState,
          chatPanelWidths: normalizePersistedChatPanelWidths(persistedShellState.chatPanelWidths),
        };
      },
    },
  ),
);
