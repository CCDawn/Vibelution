import { describe, expect, it } from "vitest";

import { PANE_DOCK_OPEN_DEDUPE_MS, shouldSuppressPaneDockOpen } from "./chatPaneDock";

describe("pane dock open dedupe", () => {
  it("suppresses the same session inside one burst", () => {
    expect(
      shouldSuppressPaneDockOpen({ sessionId: "a", at: 1000 }, "a", 1000 + PANE_DOCK_OPEN_DEDUPE_MS - 1),
    ).toBe(true);
  });

  it("lets the same session through once the burst window passed", () => {
    expect(
      shouldSuppressPaneDockOpen({ sessionId: "a", at: 1000 }, "a", 1000 + PANE_DOCK_OPEN_DEDUPE_MS),
    ).toBe(false);
  });

  it("never suppresses a different session", () => {
    expect(shouldSuppressPaneDockOpen({ sessionId: "a", at: 1000 }, "b", 1000)).toBe(false);
  });

  it("never suppresses without a recent open", () => {
    expect(shouldSuppressPaneDockOpen(null, "a", 1000)).toBe(false);
  });
});
