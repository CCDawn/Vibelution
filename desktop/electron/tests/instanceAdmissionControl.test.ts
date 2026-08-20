import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  ADMISSION_BURST,
  ADMISSION_WINDOW_MS,
  COOLDOWN_CAP_MS,
  COOLDOWN_INITIAL_MS,
  decideAdmission,
  recordAdmissionFailure,
  recordAdmissionSuccess,
  recordAdmittedStart,
  type AdmissionRecord
} from "../src/lifecycle/instanceAdmissionControl.js";

const fixturePath = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "src",
  "lifecycle",
  "__fixtures__",
  "instanceAdmission.cases.json"
);
const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as {
  protocol: {
    burst: number;
    windowMs: number;
    cooldownInitialMs: number;
    cooldownCapMs: number;
  };
  nowMs: number;
  cases: Array<{
    id: string;
    record: AdmissionRecord;
    operation?: string;
    apply?: "failure" | "success";
    expected?: { admitted: boolean; code: string; retryAfterMs: number };
    expectedRecord?: { consecutiveFailures: number; cooldownUntilMs: number };
  }>;
};

describe("instance admission control", () => {
  it("locks shared protocol constants", () => {
    expect(fixture.protocol.burst).toBe(ADMISSION_BURST);
    expect(fixture.protocol.windowMs).toBe(ADMISSION_WINDOW_MS);
    expect(fixture.protocol.cooldownInitialMs).toBe(COOLDOWN_INITIAL_MS);
    expect(fixture.protocol.cooldownCapMs).toBe(COOLDOWN_CAP_MS);
  });

  it.each(fixture.cases)("$id", (item) => {
    if (item.apply === "failure") {
      expect(recordAdmissionFailure(item.record, fixture.nowMs)).toMatchObject(item.expectedRecord || {});
      return;
    }
    if (item.apply === "success") {
      expect(recordAdmissionSuccess(item.record)).toMatchObject(item.expectedRecord || {});
      return;
    }
    const decision = decideAdmission(item.record, fixture.nowMs, item.operation || "start");
    expect(decision.admitted).toBe(item.expected?.admitted);
    expect(decision.code).toBe(item.expected?.code);
    expect(decision.retryAfterMs).toBe(item.expected?.retryAfterMs);
  });

  it("records admitted starts into the sliding window", () => {
    const next = recordAdmittedStart(
      { startTimestampsMs: [fixture.nowMs - 1000], consecutiveFailures: 0, cooldownUntilMs: 0 },
      fixture.nowMs
    );
    expect(next.startTimestampsMs).toEqual([fixture.nowMs - 1000, fixture.nowMs]);
  });
});
