import { describe, expect, it } from "vitest";

import type { RuntimeSummary } from "../api/types";
import {
  runtimeSummaryEqualIgnoringVolatile,
  shareRuntimeSummaryIfOnlyVolatileChanged,
} from "./runtimeSummaryQueryShare";

function baseSummary(overrides: Record<string, unknown> = {}): RuntimeSummary {
  return {
    status: "ok",
    lifecycleProof: {
      verifiedAt: "2026-08-01T15:00:00Z",
      components: [
        { name: "backend", verifiedAt: "2026-08-01T15:00:00Z" },
        { name: "frontend", verifiedAt: "2026-08-01T15:00:00Z" },
      ],
    },
    runtimeManager: {
      stateVersion: 10,
      status: "running",
    },
    workbench: {
      desiredState: "open",
      observedState: "open",
    },
    ...overrides,
  } as RuntimeSummary;
}

describe("runtimeSummaryQueryShare", () => {
  it("treats verifiedAt and stateVersion-only churn as equal", () => {
    const left = baseSummary();
    const right = baseSummary({
      lifecycleProof: {
        verifiedAt: "2026-08-01T15:00:05Z",
        components: [
          { name: "backend", verifiedAt: "2026-08-01T15:00:05Z" },
          { name: "frontend", verifiedAt: "2026-08-01T15:00:05Z" },
        ],
      },
      runtimeManager: {
        stateVersion: 99,
        status: "running",
      },
    });
    expect(runtimeSummaryEqualIgnoringVolatile(left, right)).toBe(true);
    expect(shareRuntimeSummaryIfOnlyVolatileChanged(left, right)).toBe(left);
  });

  it("does not share when semantic workbench state changes", () => {
    const left = baseSummary();
    const right = baseSummary({
      workbench: {
        desiredState: "open",
        observedState: "degraded",
      },
    });
    expect(runtimeSummaryEqualIgnoringVolatile(left, right)).toBe(false);
    expect(shareRuntimeSummaryIfOnlyVolatileChanged(left, right)).toBe(right);
  });

  it("returns next when previous is missing", () => {
    const next = baseSummary();
    expect(shareRuntimeSummaryIfOnlyVolatileChanged(undefined, next)).toBe(next);
  });
});
