import { describe, expect, it } from "vitest";
import { ASSISTANT_TASK_PROBE_INTERVALS_MS, assistantTaskErrorProbeInterval } from "./assistantTaskProbes";

describe("assistant task error probe intervals", () => {
  it("starts at the first probe delay without a valid anchor", () => {
    expect(assistantTaskErrorProbeInterval(null, 1_000)).toBe(3_000);
    expect(assistantTaskErrorProbeInterval(Number.NaN, 1_000)).toBe(3_000);
    expect(assistantTaskErrorProbeInterval(Number.POSITIVE_INFINITY, 1_000)).toBe(3_000);
  });

  it("returns the 3s, 6s, 12s backoff sequence between the scheduled probes", () => {
    expect(ASSISTANT_TASK_PROBE_INTERVALS_MS).toEqual([3_000, 6_000, 12_000, 12_000, 12_000]);
    expect(assistantTaskErrorProbeInterval(1_000, 1_000)).toBe(3_000);
    expect(assistantTaskErrorProbeInterval(1_000, 3_999)).toBe(1); // still waiting on the first probe point
    expect(assistantTaskErrorProbeInterval(1_000, 4_000)).toBe(6_000);
    expect(assistantTaskErrorProbeInterval(1_000, 10_000)).toBe(12_000);
    expect(assistantTaskErrorProbeInterval(1_000, 22_000)).toBe(12_000);
    expect(assistantTaskErrorProbeInterval(1_000, 34_000)).toBe(12_000);
  });

  it("stops once the bounded budget of five probes is spent", () => {
    expect(assistantTaskErrorProbeInterval(0, 44_999)).toBe(1);
    expect(assistantTaskErrorProbeInterval(0, 45_000)).toBe(false);
    expect(assistantTaskErrorProbeInterval(0, 300_000)).toBe(false);
  });

  it("clamps a reversed or invalid clock to the first probe delay", () => {
    expect(assistantTaskErrorProbeInterval(10_000, 5_000)).toBe(3_000);
    expect(assistantTaskErrorProbeInterval(10_000, Number.NaN)).toBe(3_000);
    expect(assistantTaskErrorProbeInterval(10_000, Number.NEGATIVE_INFINITY)).toBe(3_000);
  });
});
