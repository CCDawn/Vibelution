import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  readSourceCollectionPanelState,
  writeSourceCollectionPanelState,
} from "./useSourceCollectionWorkspace";

function stubSessionStorage() {
  const store = new Map<string, string>();
  const storage = {
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
  };
  vi.stubGlobal("window", { sessionStorage: storage });
  return storage;
}

describe("source-collection panel state recovery", () => {
  beforeEach(() => {
    stubSessionStorage();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("round-trips expanded/focused panel ids per team", () => {
    writeSourceCollectionPanelState("team-a", {
      expandedPanelId: "source-collection-candidates-panel",
      focusedPanelId: "source-collection-candidates-panel",
    });
    expect(readSourceCollectionPanelState("team-a")).toEqual({
      expandedPanelId: "source-collection-candidates-panel",
      focusedPanelId: "source-collection-candidates-panel",
    });
    // Another team must not see team-a's panels.
    expect(readSourceCollectionPanelState("team-b")).toBeNull();
  });

  it("returns null for missing, empty, or corrupt snapshots", () => {
    expect(readSourceCollectionPanelState("")).toBeNull();
    expect(readSourceCollectionPanelState("team-missing")).toBeNull();
    window.sessionStorage.setItem("vibelution.sc-workspace-panels.team-x", "{not json");
    expect(readSourceCollectionPanelState("team-x")).toBeNull();
  });

  it("normalizes non-string fields to empty ids instead of crashing", () => {
    window.sessionStorage.setItem(
      "vibelution.sc-workspace-panels.team-y",
      JSON.stringify({ expandedPanelId: 42, focusedPanelId: null }),
    );
    expect(readSourceCollectionPanelState("team-y")).toEqual({
      expandedPanelId: "",
      focusedPanelId: "",
    });
  });

  it("degrades to no-op when window/sessionStorage is unavailable", () => {
    vi.unstubAllGlobals();
    expect(readSourceCollectionPanelState("team-a")).toBeNull();
    expect(() =>
      writeSourceCollectionPanelState("team-a", { expandedPanelId: "p", focusedPanelId: "p" }),
    ).not.toThrow();
  });
});
