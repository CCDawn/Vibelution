import { beforeEach, describe, expect, it, vi } from "vitest";

import { useShellStore } from "./shellStore";

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
    vi.stubGlobal("localStorage", createMemoryStorage());
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

  it("migrates the legacy status-left Chat pane widths to the new conversation-left layout", () => {
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

    useShellStore.persist.rehydrate();

    expect(useShellStore.getState().chatPanelWidths).toEqual({
      leftPanelWidth: 300,
      rightPanelWidth: 220,
    });
  });
});
