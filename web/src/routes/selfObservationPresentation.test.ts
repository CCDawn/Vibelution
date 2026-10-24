import { describe, expect, it } from "vitest";
import { ACTIVITY_CONTRACT } from "../api/generated/activityContract";
import { selfObservationIsActive, selfObservationPollingInterval, selfObservationStatusLabel } from "./selfObservationPresentation";

describe("self observation contract consumers", () => {
  it.each(ACTIVITY_CONTRACT.selfObservation.terminalStatuses)("settles polling and activity for %s", (status) => {
    expect(selfObservationPollingInterval(status, true)).toBe(10_000);
    expect(selfObservationPollingInterval(status, false)).toBe(false);
    expect(selfObservationIsActive(status)).toBe(false);
    expect(selfObservationStatusLabel(status, "zh")).not.toBe(status);
  });

  it.each(["queued", "running"])("retains fast polling and active phase for %s", (status) => {
    expect(selfObservationPollingInterval(status, true)).toBe(2_000);
    expect(selfObservationIsActive(status)).toBe(true);
  });

  it("keeps missing and unknown facts distinct from active work", () => {
    expect(selfObservationPollingInterval(undefined, true)).toBe(10_000);
    expect(selfObservationPollingInterval("future_status", true)).toBe(2_000);
    expect(selfObservationIsActive("future_status")).toBe(false);
    expect(selfObservationStatusLabel("future_status", "zh")).toBe("未知状态");
    expect(selfObservationStatusLabel("future_status", "en")).toBe("Unknown state");
  });
});
