import { describe, expect, it } from "vitest";
import { isWorkbenchCloseControlFetchFailure } from "../src/lifecycle/workbenchCloseFailOpen.js";

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
});
