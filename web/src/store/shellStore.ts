import { create } from "zustand";
import { persist } from "zustand/middleware";

type EvolutionTrack = "supervised" | "self";
type EvolutionView = "live" | "runs" | "library" | "overview";

type ChatPanelWidths = {
  leftPanelWidth: number;
  rightPanelWidth: number;
};

type ShellState = {
  evolutionTrack: EvolutionTrack;
  evolutionView: EvolutionView;
  chatPanelWidths: ChatPanelWidths;
  setEvolutionTrack: (track: EvolutionTrack) => void;
  setEvolutionView: (view: EvolutionView) => void;
  setChatPanelWidths: (widths: Partial<ChatPanelWidths>) => void;
};

const DEFAULT_CHAT_PANEL_WIDTHS: ChatPanelWidths = {
  leftPanelWidth: 220,
  rightPanelWidth: 284,
};

export const useShellStore = create<ShellState>()(
  persist(
    (set) => ({
      evolutionTrack: "supervised",
      evolutionView: "live",
      chatPanelWidths: DEFAULT_CHAT_PANEL_WIDTHS,
      setEvolutionTrack: (evolutionTrack) => set({ evolutionTrack }),
      setEvolutionView: (evolutionView) => set({ evolutionView }),
      setChatPanelWidths: (widths) =>
        set((state) => ({
          chatPanelWidths: {
            ...state.chatPanelWidths,
            ...widths,
          },
        })),
    }),
    {
      name: "vibelution-shell-store",
      partialize: (state) => ({
        evolutionTrack: state.evolutionTrack,
        evolutionView: state.evolutionView,
        chatPanelWidths: state.chatPanelWidths,
      }),
    },
  ),
);
