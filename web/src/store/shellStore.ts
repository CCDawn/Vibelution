import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";

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

const DEFAULT_CHAT_PANEL_WIDTHS: ChatPanelWidths = {
  leftPanelWidth: 220,
  rightPanelWidth: 284,
};

const NOOP_SHELL_STORAGE: StateStorage = {
  getItem: () => null,
  setItem: () => undefined,
  removeItem: () => undefined,
};

function resolveShellStorage(): StateStorage {
  try {
    return typeof localStorage === "undefined" ? NOOP_SHELL_STORAGE : localStorage;
  } catch {
    return NOOP_SHELL_STORAGE;
  }
}

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
        set((state) => ({
          chatPanelWidths: {
            ...state.chatPanelWidths,
            ...widths,
          },
        })),
      setTopBarMode: (topBarMode) => set({ topBarMode }),
    }),
    {
      name: "vibelution-shell-store",
      storage: createJSONStorage(resolveShellStorage),
      partialize: (state) => ({
        evolutionTrack: state.evolutionTrack,
        evolutionView: state.evolutionView,
        chatPanelWidths: state.chatPanelWidths,
        topBarMode: state.topBarMode,
      }),
    },
  ),
);
