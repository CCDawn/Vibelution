import { beforeEach, describe, expect, it } from "vitest";

import { useShellStore } from "./shellStore";

describe("shellStore", () => {
  beforeEach(() => {
    useShellStore.setState({
      evolutionTrack: "supervised",
      evolutionView: "live",
      chatPanelWidths: {
        leftPanelWidth: 220,
        rightPanelWidth: 284,
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
});
