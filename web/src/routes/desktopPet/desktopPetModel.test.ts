import { describe, expect, it } from "vitest";

import type { PetActivity } from "../../api/types/petActivity";
import {
  petActivityRefetchInterval,
  petPhaseLabel,
} from "./desktopPetModel";

const activity = (activeCount: number, attentionCount: number): PetActivity => ({
  schemaVersion: 1,
  aggregateTone: activeCount ? "running" : "idle",
  animationState: activeCount ? "thinking" : "idle",
  activeCount,
  attentionCount,
  generatedAt: "2026-09-08T02:00:00Z",
  sessions: [],
});

describe("desktop pet model", () => {
  it("polls quickly while work or attention is present and backs off while idle", () => {
    expect(petActivityRefetchInterval(undefined)).toBe(1_000);
    expect(petActivityRefetchInterval(activity(1, 0))).toBe(1_000);
    expect(petActivityRefetchInterval(activity(0, 1))).toBe(1_000);
    expect(petActivityRefetchInterval(activity(0, 0))).toBe(3_000);
  });

  it("keeps activity phases user-readable", () => {
    expect(petPhaseLabel("tooling", "zh")).toBe("操作工具中");
    expect(petPhaseLabel("verifying", "en")).toBe("Verifying");
  });

});
