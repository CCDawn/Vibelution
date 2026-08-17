import { describe, expect, it } from "vitest";
import {
  isWorkbenchCloseControlFetchFailure,
  shouldNotifyForceStopControlFailure
} from "../src/lifecycle/workbenchCloseFailOpen.js";

describe("workbench close control fetch failure", () => {
  it("treats Chromium fetch failed as a fail-open close", () => {
    expect(isWorkbenchCloseControlFetchFailure(new Error("fetch failed"))).toBe(true);
    expect(isWorkbenchCloseControlFetchFailure(new TypeError("Failed to fetch"))).toBe(true);
    expect(isWorkbenchCloseControlFetchFailure("workbench close transaction timed out after 5000ms")).toBe(true);
  });

  it("does not fail-open ordinary transaction contract errors", () => {
    expect(isWorkbenchCloseControlFetchFailure(new Error("confirmation required"))).toBe(false);
    expect(isWorkbenchCloseControlFetchFailure(new Error("active work running"))).toBe(false);
  });

  it("does not toast force-stop disconnects that already tore down the control HTTP server", () => {
    expect(shouldNotifyForceStopControlFailure(new TypeError("fetch failed"))).toBe(false);
    expect(shouldNotifyForceStopControlFailure(new Error("econnreset"))).toBe(false);
    expect(shouldNotifyForceStopControlFailure(new Error("confirmation required"))).toBe(true);
  });
});
