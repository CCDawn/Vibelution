import { describe, expect, it } from "vitest";

import { STARTUP_BACKGROUND_WARMUP_MS, isDocumentVisible, isStartupWarmupActive, resolvePollingInterval } from "./pollingPolicy";

describe("pollingPolicy", () => {
  it("treats visible and server-side unknown state as foreground", () => {
    expect(isDocumentVisible("visible")).toBe(true);
    expect(isDocumentVisible(undefined)).toBe(true);
  });

  it("treats hidden and prerendered documents as background", () => {
    expect(isDocumentVisible("hidden")).toBe(false);
    expect(isDocumentVisible("prerender")).toBe(false);
  });

  it("keeps polling fast only while visible by default", () => {
    expect(resolvePollingInterval(true, 5_000)).toBe(5_000);
    expect(resolvePollingInterval(false, 5_000)).toBe(false);
  });

  it("supports deliberate slow background polling for global lifecycle signals", () => {
    expect(resolvePollingInterval(false, 5_000, { backgroundMs: 30_000 })).toBe(30_000);
  });

  it("keeps foreground cadence for shutdown and other forced control paths", () => {
    expect(resolvePollingInterval(false, 1_000, { backgroundMs: 30_000, force: true })).toBe(1_000);
  });

  it("keeps startup warmup active until ready or timeout", () => {
    expect(isStartupWarmupActive(false, 0)).toBe(true);
    expect(isStartupWarmupActive(false, STARTUP_BACKGROUND_WARMUP_MS - 1)).toBe(true);
    expect(isStartupWarmupActive(false, STARTUP_BACKGROUND_WARMUP_MS)).toBe(false);
    expect(isStartupWarmupActive(true, 0)).toBe(false);
    expect(isStartupWarmupActive(false, 60_000, 0)).toBe(true);
  });
});
