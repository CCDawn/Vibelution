import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  PANE_LAYOUT_STORAGE_KEY,
  readPaneLayout,
} from "../components/layout/paneLayoutPersistence";
import { CHAT_PANE_LAYOUT_ID, useShellStore } from "./shellStore";

function createMemoryStorage(): Storage {
  const entries = new Map<string, string>();
  return {
    get length() {
      return entries.size;
    },
    clear: () => entries.clear(),
    getItem: (key) => entries.get(key) ?? null,
    key: (index) => Array.from(entries.keys())[index] ?? null,
    removeItem: (key) => entries.delete(key),
    setItem: (key, value) => entries.set(key, value),
  };
}

describe("shellStore", () => {
  beforeEach(() => {
    const memoryStorage = createMemoryStorage();
    vi.stubGlobal("localStorage", memoryStorage);
    vi.stubGlobal("window", { localStorage: memoryStorage });
    localStorage.clear();
    useShellStore.setState({
      evolutionTrack: "supervised",
      evolutionView: "live",
      chatPanelWidths: {
        leftPanelWidth: 300,
        rightPanelWidth: 220,
      },
      topBarMode: "full",
    });
  });

  it("keeps the app shell top bar visible by default", () => {
    expect(useShellStore.getState().topBarMode).toBe("full");
  });

  it("stores the app shell top bar visibility mode in the existing shell state", () => {
    useShellStore.getState().setTopBarMode("hidden");

    expect(useShellStore.getState().topBarMode).toBe("hidden");

    useShellStore.getState().setTopBarMode("full");

    expect(useShellStore.getState().topBarMode).toBe("full");
  });

  it("defaults Chat to a wider left conversation column and narrower right status rail", () => {
    expect(useShellStore.getState().chatPanelWidths).toEqual({
      leftPanelWidth: 300,
      rightPanelWidth: 220,
    });
  });

  it("migrates the legacy status-left Chat pane widths to the new conversation-left layout", async () => {
    localStorage.setItem(
      "vibelution-shell-store",
      JSON.stringify({
        state: {
          evolutionTrack: "supervised",
          evolutionView: "live",
          chatPanelWidths: {
            leftPanelWidth: 260,
            rightPanelWidth: 340,
          },
          topBarMode: "full",
        },
        version: 0,
      }),
    );

    await useShellStore.persist.rehydrate();

    expect(useShellStore.getState().chatPanelWidths).toEqual({
      leftPanelWidth: 300,
      rightPanelWidth: 220,
    });
  });

  it("writes Chat panel widths only into shared pane-layouts.v1[chat]", () => {
    useShellStore.getState().setChatPanelWidths({
      leftPanelWidth: 340,
      rightPanelWidth: 260,
    });

    expect(useShellStore.getState().chatPanelWidths).toEqual({
      leftPanelWidth: 340,
      rightPanelWidth: 260,
    });
    expect(readPaneLayout(CHAT_PANE_LAYOUT_ID)).toEqual({
      left: 340,
      right: 260,
    });
    expect(localStorage.getItem(PANE_LAYOUT_STORAGE_KEY)).toContain("chat");
    const persistedShell = localStorage.getItem("vibelution-shell-store") ?? "";
    expect(persistedShell).not.toContain("chatPanelWidths");
  });

  it("restores preferred chat widths below the previous default floor", async () => {
    localStorage.setItem(
      "vibelution-shell-store",
      JSON.stringify({
        state: {
          evolutionTrack: "supervised",
          evolutionView: "live",
          chatPanelWidths: {
            leftPanelWidth: 280,
            rightPanelWidth: 210,
          },
          topBarMode: "full",
        },
        version: 0,
      }),
    );

    await useShellStore.persist.rehydrate();

    expect(useShellStore.getState().chatPanelWidths).toEqual({
      leftPanelWidth: 280,
      rightPanelWidth: 210,
    });
    expect(readPaneLayout(CHAT_PANE_LAYOUT_ID)).toEqual({
      left: 280,
      right: 210,
    });
  });

  it("does not clobber canonical pane-layouts.v1[chat] with leftover shell widths", async () => {
    localStorage.setItem(
      PANE_LAYOUT_STORAGE_KEY,
      JSON.stringify({ chat: { left: 330, right: 240 } }),
    );
    localStorage.setItem(
      "vibelution-shell-store",
      JSON.stringify({
        state: {
          evolutionTrack: "supervised",
          evolutionView: "live",
          chatPanelWidths: {
            leftPanelWidth: 280,
            rightPanelWidth: 210,
          },
          topBarMode: "full",
        },
        version: 0,
      }),
    );

    await useShellStore.persist.rehydrate();

    expect(useShellStore.getState().chatPanelWidths).toEqual({
      leftPanelWidth: 330,
      rightPanelWidth: 240,
    });
    expect(readPaneLayout(CHAT_PANE_LAYOUT_ID)).toEqual({
      left: 330,
      right: 240,
    });
  });

  it("normalizes preferred chat widths through the store setter bounds path", () => {
    useShellStore.getState().setChatPanelWidths({
      leftPanelWidth: 280,
      rightPanelWidth: 210,
    });
    expect(useShellStore.getState().chatPanelWidths).toEqual({
      leftPanelWidth: 280,
      rightPanelWidth: 210,
    });
  });
});
